"""
# @Author: AI产品研发组
# @Date: 2026-08-21
# @Description: 通用 describe 引擎，对应 rules/describe_rules.md（scene=default）
# @Command: 由 util/describe.py 按 rules_scene 自动加载
"""

from describe_common import (
    label_natural_reading,
    locked_axis_tokens,
    phrase_content_key,
    phrase_synonym_key,
    policy_max_phrases,
    shares_locked_axis,
)
from rules_io import get_scene_policy
from vllm_client import extract_json_object


RULES_FILE = "describe_rules.md"

SYSTEM_PROMPT = (
    "You describe ONE object for visual grounding. "
    "The given class label is GROUND TRUTH: every phrase must stay in that class "
    "(never swap car↔motorcycle, etc.). "
    "Output JSON only: {\"phrases\":[...]} with short English noun phrases. "
    "Within ONE phrases list, diversify axes "
    "(e.g. helmet / shirt / standing — different dimensions); "
    "do NOT co-list near-paraphrases or synonyms "
    "(person in red helmet ≈ person wearing red helmet; "
    "helmet ≈ hard hat). "
    "Do not re-offer synonyms of already-used phrases either "
    "(if avoid has helmet, do not emit hard hat). "
    "If some phrases are already locked, do NOT reuse their distinctive "
    "modifiers (red sedan → not red car / red private car); "
    "switch to remaining axes (parked car, car with sunroof). "
    "No markdown, no thinking."
)


def describe_object(client, crop_abs: str, label: str, rules: str = "",
                    avoid_phrases=None, min_phrases=None, with_zh: bool = False,
                    max_retries: int = 3, seed_phrases=None, lock_phrases=None):
    pol = get_scene_policy()
    need = max(1, int(min_phrases if min_phrases is not None else policy_max_phrases(pol)))
    avoid = [
        str(p).strip() for p in (avoid_phrases or [])
        if isinstance(p, str) and str(p).strip()
    ]
    seeds = [
        str(p).strip() for p in (seed_phrases or [])
        if isinstance(p, str) and str(p).strip()
    ]
    locked = [
        str(p).strip() for p in (lock_phrases or [])
        if isinstance(p, str) and str(p).strip()
    ]
    lock_axis = locked_axis_tokens(locked)
    retries = max(1, int(max_retries or 1))
    avoid_line = ""
    if avoid:
        listed = "; ".join(avoid[:16])
        avoid_line = (
            f"Do NOT reuse, lightly paraphrase, or synonym-swap these already-used phrases: {listed}.\n"
            f"Counts as duplicate: preposition swap "
            f"(person in red helmet ≈ person wearing red helmet) "
            f"AND noun synonym (helmet ≈ hard hat).\n"
            f"Emit DIFFERENT attribute axes instead "
            f"(e.g. if helmet was used → prefer shirt / standing / location).\n"
        )
    lock_line = ""
    if locked:
        listed = "; ".join(locked[:8])
        mods = ", ".join(sorted(lock_axis)[:12]) if lock_axis else "(distinctive modifiers in the locked phrases)"
        lock_line = (
            f"LOCKED phrases (annotator already chose these; keep their attributes occupied): {listed}.\n"
            f"Do NOT reuse these distinctive modifiers in any NEW phrase: {mods}.\n"
            f"Write remaining visible axes instead: action/state, location, part/accessory, "
            f"other appearance (not the locked modifiers). Other subtype words are OK "
            f"(sedan locked → SUV with sunroof OK; red locked → red car FORBIDDEN).\n"
            f"Bad: red sedan → red car / red private car. "
            f"Good: parked car; car with sunroof.\n"
        )
        seeds = []
    seed_line = ""
    if seeds:
        listed = "; ".join(seeds[:8])
        seed_line = (
            f"The annotator kept these as closest-but-not-precise enough: {listed}.\n"
            f"Write up to {need} NEW short English noun phrases that stay CLOSE to them "
            f"(same object / same key attributes) but are more precise or better wording.\n"
            f"Return whatever you can; do NOT pad with low-quality fillers.\n"
            f"Do NOT repeat the kept phrases verbatim.\n"
        )
    if with_zh:
        example = (
            '{"phrases":["blue scooter","parked scooter"],'
            '"zh":["蓝色滑板车","停放的滑板车"]}'
        )
        zh_line = (
            "Also provide Simplified Chinese for each phrase in parallel array \"zh\" "
            "(same count/order).\n"
        )
        max_tokens = 512
    else:
        example = '{"phrases":["blue scooter","two-wheeled vehicle","parked scooter"]}'
        zh_line = ""
        max_tokens = 384
    hint = label_natural_reading(label)
    cover_line = (
        f"Write up to {need} short English noun phrases that stay close to the seed phrases above; "
        f"still keep each phrase to 1–2 attribute axes only. "
        f"Each new phrase must change an axis vs the seeds "
        f"(not just in↔wearing / with↔holding / helmet↔hard hat). "
        f"Fewer is OK if the crop is limited — do not pad.\n"
        if seeds else
        f"Write up to {need} short English noun phrases (fewer is OK; do not pad). "
        f"Across the set, diversify these axes when visible: "
        f"(1) subtype/role (2) appearance/color (3) action/state "
        f"(4) location (5) partial feature "
        f"(good set: helmet / shirt / standing — different dimensions). "
        f"Each single phrase must combine only 1–2 axes "
        f"(e.g. red car; car on the road; car with sunroof); "
        f"do NOT stack three or more modifiers in one phrase. "
        f"Do NOT list near-paraphrases or synonyms together "
        f"(person in red helmet + person wearing red helmet; "
        f"helmet + hard hat — forbidden).\n"
    )
    task = (
        f"Class label (GROUND TRUTH): {label}\n"
        f"Natural reading of label: {hint}\n"
        f"CRITICAL: Every phrase MUST describe this class only. "
        f"Do NOT rename it to another category even if the crop looks similar "
        f"(e.g. label=car → never motorcycle/bike/scooter; "
        f"label=specialvehicle → special/utility/engineering vehicle, not private car or motorcycle). "
        f"Subtype words are OK only within the same class family "
        f"(car→sedan/SUV/taxi OK).\n"
        f"{lock_line}"
        f"{seed_line}"
        f"{cover_line}"
        f"Prefer keeping a class-family head noun in the phrases.\n"
        f"{avoid_line}"
        f"{zh_line}"
        f"Follow the rules above when they apply.\n"
        f"Return ONLY valid JSON, example: {example}"
    )
    prompt = (str(rules).strip() + "\n\n" + task) if rules and str(rules).strip() else task
    avoid_l = {a.lower() for a in avoid}
    last_err = None
    for _ in range(retries):
        try:
            raw = client.describe_image(
                crop_abs, prompt,
                system=SYSTEM_PROMPT,
                max_tokens=max_tokens,
            )
            data = extract_json_object(raw)
            phrases = [
                p.strip() for p in (data.get("phrases") or [])
                if isinstance(p, str) and p.strip()
            ]
            zh_raw = data.get("zh") or []
            ban_keys = {phrase_content_key(a) for a in avoid if phrase_content_key(a)}
            ban_syn = {phrase_synonym_key(a) for a in avoid if phrase_synonym_key(a)}
            kept_zh = []
            kept_ph = []
            for i, p in enumerate(phrases):
                if p.lower() in avoid_l:
                    continue
                key = phrase_content_key(p)
                if key and key in ban_keys:
                    continue
                syn = phrase_synonym_key(p)
                if syn and syn in ban_syn:
                    continue
                if lock_axis and shares_locked_axis(p, lock_axis):
                    continue
                if key:
                    ban_keys.add(key)
                if syn:
                    ban_syn.add(syn)
                kept_ph.append(p)
                if i < len(zh_raw) and isinstance(zh_raw[i], str) and zh_raw[i].strip():
                    kept_zh.append(zh_raw[i].strip())
                else:
                    kept_zh.append("")
            phrases, zh_raw = kept_ph, kept_zh
            if len(phrases) < 1:
                raise ValueError(f"模型未返回有效短语: {data}")
            phrases = phrases[:need]
            zh = []
            if with_zh:
                for i in range(len(phrases)):
                    if i < len(zh_raw) and isinstance(zh_raw[i], str) and zh_raw[i].strip():
                        zh.append(zh_raw[i].strip())
                    else:
                        zh.append("")
            return {
                "label": label,
                "phrases": phrases,
                "source": "vllm",
                "error": None,
                "zh": zh,
            }
        except Exception as e:
            last_err = e
    raise RuntimeError(f"描述失败 ({label}): {last_err}")
