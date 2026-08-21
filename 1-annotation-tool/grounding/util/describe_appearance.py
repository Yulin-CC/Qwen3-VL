"""
# @Author: AI产品研发组
# @Date: 2026-08-21
# @Description: 外观 describe 引擎，对应 rules/describe_rules_appearance.md
# @Command: 由 util/describe.py 在 --rules-scene appearance 时加载
"""

import re

from describe_common import label_natural_reading, phrase_content_key, policy_max_phrases
from rules_io import get_scene_policy
from vllm_client import extract_json_object


RULES_FILE = "describe_rules_appearance.md"

SYSTEM_PROMPT = (
    "You describe ONE cropped object for visual grounding. "
    "Only appearance (color, clothing, visible surface). "
    "No pose, action, role, subtype, or location. "
    "Every phrase MUST keep the given class as the head noun "
    "(car → 'white car', never 'white sedan' / never bare 'car'). "
    "Output JSON only. No markdown, no thinking."
)

EXHAUSTIVE_SYSTEM = (
    "You check whether THIS cropped object also matches extra appearance phrases "
    "already used by other same-class objects in the same image. "
    "Be strict: match only if the attribute is clearly visible. "
    "Output JSON only: {\"matched\":[...]}. No markdown, no thinking."
)

_VEHICLE_LABELS = frozenset({
    "car", "truck", "bus", "van", "motorcycle", "motorbike", "bike",
    "bicycle", "specialvehicle",
})
_BANNED_SUBTYPES = frozenset({
    "sedan", "suv", "pickup", "coupe", "hatchback", "wagon", "minivan",
    "taxi", "cab", "limousine", "convertible", "crossover", "jeep",
    "mpv", "saloon", "estate", "roadster",
})


def is_vehicle_label(label: str) -> bool:
    hint = label_natural_reading(label)
    if hint in _VEHICLE_LABELS:
        return True
    return any(h in hint.split() for h in _VEHICLE_LABELS)


def _rewrite_vehicle_phrase(phrase: str, label: str) -> str:
    hint = label_natural_reading(label)
    head = hint.split()[-1] if hint else "car"
    toks = re.findall(r"[A-Za-z0-9]+", phrase or "")
    out = []
    for t in toks:
        low = t.lower()
        if low in _BANNED_SUBTYPES:
            out.append(head)
        else:
            out.append(t.lower())
    if not out:
        return ""
    compact = []
    for t in out:
        if compact and compact[-1] == t:
            continue
        compact.append(t)
    if head not in compact:
        compact.append(head)
    return " ".join(compact)


def sanitize_phrases(phrases, label: str, max_n=None):
    need = max_n if max_n is not None else policy_max_phrases()
    hint = label_natural_reading(label)
    raw_label = (label or "").strip().lower()
    vehicle = is_vehicle_label(label)
    kept, seen = [], set()
    for p in phrases or []:
        if not isinstance(p, str):
            continue
        text = re.sub(r"\s+", " ", p.strip())
        if not text:
            continue
        if vehicle:
            text = _rewrite_vehicle_phrase(text, label)
        if not text:
            continue
        low = text.lower().strip(" .")
        if low in {raw_label, hint, f"a {hint}", f"the {hint}"}:
            continue
        if not re.search(r"\b" + re.escape(hint) + r"\b", low):
            text = f"{text} {hint}"
            low = text.lower()
        key = phrase_content_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(text)
        if len(kept) >= need:
            break
    return kept


def describe_object(client, crop_abs: str, label: str, rules: str = "",
                    avoid_phrases=None, min_phrases=None, with_zh: bool = False,
                    max_retries: int = 2, seed_phrases=None, lock_phrases=None):
    pol = get_scene_policy()
    need = max(1, int(min_phrases if min_phrases is not None else policy_max_phrases(pol)))
    if lock_phrases or seed_phrases or with_zh:
        from describe_default import describe_object as _base
        desc = _base(
            client, crop_abs, label, rules=rules,
            avoid_phrases=avoid_phrases, min_phrases=need, with_zh=with_zh,
            max_retries=max_retries, seed_phrases=seed_phrases,
            lock_phrases=lock_phrases,
        )
        phrases = sanitize_phrases(desc.get("phrases") or [], label, max_n=need)
        if not phrases:
            raise ValueError("外观策略清洗后无有效短语")
        desc["phrases"] = phrases
        desc["zh"] = (desc.get("zh") or [])[:len(phrases)]
        while len(desc["zh"]) < len(phrases):
            desc["zh"].append("")
        return desc

    hint = label_natural_reading(label)
    example = '{"phrases":["white car","black car"]}'
    if hint == "person":
        example = '{"phrases":["person wearing black jacket","person wearing blue jeans"]}'
    person_line = (
        "Person may mention visible clothing / accessories "
        "(person wearing black jacket; person wearing a mask).\n"
        if hint == "person" else
        "Do NOT use subtype words (sedan/SUV/pickup/taxi). "
        "Only color (or other surface look) + class: white car, gray truck.\n"
    )
    task = (
        f"Class label (GROUND TRUTH): {label}\n"
        f"Natural reading: {hint}\n"
        f"Write 1–{need} short English noun phrases. Fewer is OK; do not pad.\n"
        f"Rules:\n"
        f"- Appearance only (color, clothing, visible surface). "
        f"No pose/action/role/location/orientation.\n"
        f"- Combine with the base class. Never emit the bare label '{label}'.\n"
        f"- {person_line}"
        f"- Each phrase 2–8 words.\n"
        f"Return ONLY valid JSON, example: {example}"
    )
    prompt = (str(rules).strip() + "\n\n" + task) if rules and str(rules).strip() else task
    last_err = None
    for _ in range(max(1, int(max_retries or 1))):
        try:
            raw = client.describe_image(
                crop_abs, prompt,
                system=SYSTEM_PROMPT,
                max_tokens=256,
                temperature=0.4,
            )
            data = extract_json_object(raw)
            phrases = sanitize_phrases(data.get("phrases") or [], label, max_n=need)
            if not phrases:
                raise ValueError(f"模型未返回有效外观短语: {data}")
            return {
                "label": label,
                "phrases": phrases,
                "source": "vllm",
                "error": None,
                "zh": [],
                "exhaustive": False,
                "exhaustive_added": [],
            }
        except Exception as e:
            last_err = e
    raise RuntimeError(f"描述失败 ({label}): {last_err}")


def check_phrases_apply(client, crop_abs: str, label: str,
                        already: list, candidates: list, max_retries: int = 2):
    if not candidates:
        return []
    already_s = "; ".join(already) if already else "(none)"
    cand_s = "; ".join(candidates)
    hint = label_natural_reading(label)
    task = (
        f"Class: {hint}\n"
        f"Phrases already assigned to THIS object: {already_s}\n"
        f"Candidate phrases from OTHER same-class objects in this image: {cand_s}\n"
        f"Return only the candidates that ALSO clearly match THIS crop.\n"
        f"Do not invent new phrases. Do not match on pose or location.\n"
        f'Return JSON: {{"matched":["..."]}}  (empty list if none)'
    )
    last_err = None
    cand_keys = {phrase_content_key(c): c for c in candidates if phrase_content_key(c)}
    for _ in range(max(1, int(max_retries or 1))):
        try:
            raw = client.describe_image(
                crop_abs, task,
                system=EXHAUSTIVE_SYSTEM,
                max_tokens=256,
                temperature=0.15,
            )
            data = extract_json_object(raw)
            matched = []
            seen = set()
            for p in data.get("matched") or []:
                if not isinstance(p, str) or not p.strip():
                    continue
                key = phrase_content_key(p)
                if not key or key in seen:
                    continue
                if key not in cand_keys:
                    continue
                matched.append(cand_keys[key])
                seen.add(key)
            return matched
        except Exception as e:
            last_err = e
    print(f"  ⚠ 穷尽检查失败 ({label}): {last_err}")
    return []
