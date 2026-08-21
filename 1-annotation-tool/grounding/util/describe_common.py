"""
# @Author: AI产品研发组
# @Date: 2026-08-21
# @Description: describe 共用：短语去重 / 占位检测 / 条数。场景实现见 describe_default / describe_<slug>
"""

import os
import re

from rules_io import get_scene_policy, load_describe_rules


_PHRASE_STOPWORDS = frozenset({
    "a", "an", "the", "in", "on", "at", "of", "with", "without",
    "wearing", "wears", "worn", "holding", "holds", "and", "or",
    "to", "for", "from", "by", "into", "onto", "over", "under",
})

_MULTIWORD_SYNONYMS = {
    ("hard", "hat"): "helmet",
    ("hard", "hats"): "helmet",
    ("safety", "helmet"): "helmet",
    ("safety", "hat"): "helmet",
    ("safety", "hats"): "helmet",
    ("t", "shirt"): "shirt",
    ("tee", "shirt"): "shirt",
    ("cell", "phone"): "phone",
    ("mobile", "phone"): "phone",
    ("smart", "phone"): "phone",
}
_TOKEN_SYNONYMS = {
    "hardhat": "helmet",
    "hardhats": "helmet",
    "helmets": "helmet",
    "shirts": "shirt",
    "tshirt": "shirt",
    "tshirts": "shirt",
    "phones": "phone",
    "cellphone": "phone",
    "smartphone": "phone",
}

_CLASS_HEADS = frozenset({
    "person", "people", "man", "woman", "child", "boy", "girl", "adult", "human",
    "car", "sedan", "suv", "coupe", "hatchback", "wagon", "van", "minivan", "jeep",
    "truck", "pickup", "bus", "taxi", "cab", "vehicle", "automobile", "auto",
    "motorcycle", "motorbike", "bike", "bicycle", "scooter", "moped",
    "boat", "ship", "vessel", "airplane", "aircraft", "plane", "helicopter",
    "object", "item", "specialvehicle",
})


def _content_tokens(phrase: str):
    toks = re.findall(r"[a-z0-9]+", (phrase or "").lower())
    return [t for t in toks if t not in _PHRASE_STOPWORDS]


def _canonicalize_tokens(tokens):
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        hit = False
        for span in (3, 2):
            if i + span <= n:
                key = tuple(tokens[i:i + span])
                canon = _MULTIWORD_SYNONYMS.get(key)
                if canon:
                    out.append(canon)
                    i += span
                    hit = True
                    break
        if hit:
            continue
        out.append(_TOKEN_SYNONYMS.get(tokens[i], tokens[i]))
        i += 1
    return out


def phrase_content_key(phrase: str) -> str:
    return " ".join(_content_tokens(phrase))


def phrase_synonym_key(phrase: str) -> str:
    return " ".join(_canonicalize_tokens(_content_tokens(phrase)))


def phrase_axis_tokens(phrase: str):
    toks = _canonicalize_tokens(_content_tokens(phrase))
    return {t for t in toks if t and t not in _CLASS_HEADS}


def locked_axis_tokens(phrases) -> set:
    axes = set()
    for p in phrases or []:
        axes |= phrase_axis_tokens(p if isinstance(p, str) else str(p or ""))
    return axes


def shares_locked_axis(phrase: str, lock_axis) -> bool:
    if not lock_axis:
        return False
    return bool(phrase_axis_tokens(phrase) & lock_axis)


def is_near_duplicate_phrase(phrase: str, ban_keys) -> bool:
    key = phrase_content_key(phrase)
    if not key:
        return False
    return key in (ban_keys or set())


def is_synonym_duplicate_phrase(phrase: str, ban_syn_keys) -> bool:
    key = phrase_synonym_key(phrase)
    if not key:
        return False
    return key in (ban_syn_keys or set())


def load_rules(scene: str = None) -> str:
    return load_describe_rules(scene)


def label_natural_reading(label: str) -> str:
    raw = (label or "").strip()
    if not raw:
        return "object"
    s = re.sub(r"[_\-]+", " ", raw)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s or raw.lower()


def policy_max_phrases(policy=None) -> int:
    pol = policy if policy is not None else get_scene_policy()
    try:
        return max(1, int(pol.get("max_phrases") or 8))
    except (TypeError, ValueError):
        return 8


def fallback_phrases(label: str):
    hint = label_natural_reading(label)
    return [
        label,
        hint if hint != (label or "").strip().lower() else f"{label} object",
        f"{hint} in the scene",
    ]


def is_placeholder_desc(desc) -> bool:
    if not desc:
        return True
    src = (desc.get("source") or "").lower()
    if src in {"no_llm", "failed", "placeholder"}:
        return True
    err = (desc.get("error") or "").lower()
    if err and src != "vllm":
        return True
    if desc.get("source") == "vllm" and desc.get("phrases"):
        return False
    phrases = desc.get("phrases") or []
    label = desc.get("label") or ""
    fb = set(fallback_phrases(label)) if label else set()
    if phrases and set(phrases).issubset(fb):
        return True
    return False
