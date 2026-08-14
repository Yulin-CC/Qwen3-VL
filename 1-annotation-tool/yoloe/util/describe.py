"""
# @Author: AI产品研发组
# @Date: 2026-08-05
# @Description: 调用 vLLM 为每个 crop 生成 >=3 条英文目标短语（支持并发）
# @Command: python util/describe.py --dataset /path/to/rm --workers 8
"""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from tqdm import tqdm

from common import draft_dir, ensure_dir, write_json
from rules_io import (
    get_rules_scene,
    load_describe_rules,
    resolve_describe_rules_path,
    set_rules_scene,
)
from vllm_client import VLLMClient, extract_json_object


# 短系统提示（完整规则仍由 load_rules / rules_io 注入 user prompt）
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
    "No markdown, no thinking."
)

# 近义过滤：去掉虚词后比较内容词（in/wearing/with 等不计）
_PHRASE_STOPWORDS = frozenset({
    "a", "an", "the", "in", "on", "at", "of", "with", "without",
    "wearing", "wears", "worn", "holding", "holds", "and", "or",
    "to", "for", "from", "by", "into", "onto", "over", "under",
})

# 同组内近义折叠（跨 caption 仍可用近义替换，故 avoid 不用 synonym key）
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


def _content_tokens(phrase: str):
    toks = re.findall(r"[a-z0-9]+", (phrase or "").lower())
    return [t for t in toks if t not in _PHRASE_STOPWORDS]


def _canonicalize_tokens(tokens):
    """hard hat → helmet 等；用于同组维度去重。"""
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
    """person in red helmet / person wearing red helmet → 同一 key（虚词忽略）。"""
    return " ".join(_content_tokens(phrase))


def phrase_synonym_key(phrase: str) -> str:
    """同组近义：red helmet ≈ red hard hat → 同一 key。"""
    return " ".join(_canonicalize_tokens(_content_tokens(phrase)))


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
    """加载当前/指定场景的 describe_rules*.md（见 rules_io）。"""
    return load_describe_rules(scene)


def label_natural_reading(label: str) -> str:
    """specialvehicle / hard_hat → special vehicle / hard hat，供 prompt 提示。"""
    raw = (label or "").strip()
    if not raw:
        return "object"
    s = re.sub(r"[_\-]+", " ", raw)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s or raw.lower()


def fallback_phrases(label: str):
    hint = label_natural_reading(label)
    return [
        label,
        hint if hint != (label or "").strip().lower() else f"{label} object",
        f"{hint} in the scene",
    ]


def is_placeholder_desc(desc) -> bool:
    """Detect no_llm / failed fallback placeholders that need regeneration."""
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


def describe_object(client: VLLMClient, crop_abs: str, label: str, rules: str = "",
                    avoid_phrases=None, min_phrases=5, with_zh: bool = False,
                    max_retries: int = 3, seed_phrases=None):
    # 规则全文进 user prompt（与 caption 一致）；任务指令置后
    # with_zh=True：同一次视觉调用带回中文，避免刷新后再串行翻译
    # seed_phrases：围绕已选「接近但不贴切」的短语生成更贴切变体
    avoid = [
        str(p).strip() for p in (avoid_phrases or [])
        if isinstance(p, str) and str(p).strip()
    ]
    seeds = [
        str(p).strip() for p in (seed_phrases or [])
        if isinstance(p, str) and str(p).strip()
    ]
    need = max(1, int(min_phrases or 5))
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
        f"{seed_line}"
        f"{cover_line}"
        f"Prefer keeping a class-family head noun in the phrases.\n"
        f"{avoid_line}"
        f"{zh_line}"
        f"Follow the rules above when they apply.\n"
        f"Return ONLY valid JSON, example: {example}"
    )
    if rules and str(rules).strip():
        prompt = str(rules).strip() + "\n\n" + task
    else:
        prompt = task
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
            # 他用 + 同组：虚词折叠与同义折叠都剔除（候选里直接不要重复）
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
            # 有多少用多少：不强制凑满 need；至少 1 条即可落盘
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


def describe_one_object(dataset_root, stem, obj_id, client: VLLMClient, rules: str = "",
                        write: bool = True, avoid_phrases=None, min_phrases=5,
                        with_zh: bool = False, max_retries: int = 3, seed_phrases=None):
    """生成单目标描述。write=False 时只返回结果，由调用方决定是否落盘（避免半成品覆盖）。"""
    obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    with open(obj_path, encoding="utf-8") as f:
        meta = json.load(f)
    obj = next((o for o in meta["objects"] if o["obj_id"] == obj_id), None)
    if not obj:
        raise ValueError(f"obj_id 不存在: {obj_id}")
    crop_abs = os.path.join(dataset_root, obj["crop_path"])
    desc = describe_object(
        client, crop_abs, obj["label"], rules,
        avoid_phrases=avoid_phrases, min_phrases=min_phrases,
        with_zh=with_zh, max_retries=max_retries, seed_phrases=seed_phrases,
    )
    desc["obj_id"] = obj_id
    desc["stem"] = stem
    if write:
        out_p = os.path.join(
            draft_dir(dataset_root), "descriptions", f"{stem}_obj{obj_id:04d}.json"
        )
        write_json(out_p, desc)
    return desc


def _collect_jobs(dataset_root, stems, force=False):
    jobs = []
    out_dir = ensure_dir(os.path.join(draft_dir(dataset_root), "descriptions"))
    for stem in stems:
        obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
        if not os.path.isfile(obj_path):
            continue
        with open(obj_path, encoding="utf-8") as f:
            meta = json.load(f)
        for obj in meta["objects"]:
            out_p = os.path.join(out_dir, f"{stem}_obj{obj['obj_id']:04d}.json")
            existing = None
            if os.path.isfile(out_p):
                with open(out_p, encoding="utf-8") as f:
                    existing = json.load(f)
            if not force and existing is not None and not is_placeholder_desc(existing):
                continue
            jobs.append({
                "stem": stem,
                "obj_id": obj["obj_id"],
                "label": obj["label"],
                "crop_abs": os.path.join(dataset_root, obj["crop_path"]),
                "out_p": out_p,
            })
    return jobs


def _run_job(client, job, rules=""):
    try:
        desc = describe_object(client, job["crop_abs"], job["label"], rules=rules)
    except Exception as e:
        desc = {
            "label": job["label"],
            "phrases": fallback_phrases(job["label"]),
            "source": "failed",
            "error": str(e),
            "zh": [],
        }
    desc["obj_id"] = job["obj_id"]
    desc["stem"] = job["stem"]
    write_json(job["out_p"], desc)
    return desc


def describe_image_objects(dataset_root, stem, client: VLLMClient, rules: str, force=False):
    """兼容旧接口：单图串行（刷新单目标时仍可用 describe_one_object）。"""
    jobs = _collect_jobs(dataset_root, [stem], force=force)
    results = []
    for job in jobs:
        results.append(_run_job(client, job, rules=rules or ""))
    # also return skipped existing
    obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    if not os.path.isfile(obj_path):
        return results
    with open(obj_path, encoding="utf-8") as f:
        meta = json.load(f)
    done_ids = {r["obj_id"] for r in results}
    for obj in meta["objects"]:
        if obj["obj_id"] in done_ids:
            continue
        p = os.path.join(draft_dir(dataset_root), "descriptions",
                         f"{stem}_obj{obj['obj_id']:04d}.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                results.append(json.load(f))
    return results


def describe_dataset(dataset_root, base_url, model, limit=None, force=False,
                     workers=8, progress_cb=None):
    """
    progress_cb: optional callable(done, total, detail) 用于 UI 实时百分比。
    """
    obj_dir = os.path.join(draft_dir(dataset_root), "objects")
    assert os.path.isdir(obj_dir), "请先运行 crop"
    stems = sorted(Path(p).stem for p in Path(obj_dir).glob("*.json"))
    if limit:
        stems = stems[:limit]

    client = VLLMClient(base_url=base_url, model=model, enable_thinking=False)
    if not client.health_check():
        raise RuntimeError(
            f"vLLM 不可用: {base_url} 。请先启动 2-vllm 服务，或仅调试时显式传 --no_llm"
        )

    jobs = _collect_jobs(dataset_root, stems, force=force)
    rules = load_rules()
    rules_path = resolve_describe_rules_path()
    print(
        f"待描述目标: {len(jobs)} （workers={workers}, thinking=off, "
        f"scene={get_rules_scene() or 'default'}, rules={os.path.basename(rules_path)}）"
    )
    if not jobs:
        print("无需描述（均已完成）")
        if progress_cb:
            progress_cb(1, 1, "无需描述")
        return

    total = len(jobs)
    if progress_cb:
        progress_cb(0, total, f"0/{total}")

    n_fail = 0
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futs = [pool.submit(_run_job, client, job, rules) for job in jobs]
        for fut in tqdm(as_completed(futs), total=len(futs), desc="describe"):
            desc = fut.result()
            if desc.get("source") == "failed":
                n_fail += 1
            done += 1
            if progress_cb:
                progress_cb(done, total, f"{done}/{total}")

    print(f"描述完成: {len(jobs)} 目标 → {draft_dir(dataset_root)}/descriptions")
    if n_fail:
        print(f"⚠ 其中 {n_fail} 个失败（已写 failed 占位，可再次运行自动重试）")
    if progress_cb:
        progress_cb(total, total, f"{total}/{total}")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True)
    p.add_argument("--base_url", default="http://127.0.0.1:8081/v1")
    p.add_argument("--model", default="qwen3.6-35b-a3b")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--workers", type=int, default=8, help="并发请求数（默认 8）")
    p.add_argument(
        "--rules-scene",
        default=os.environ.get("RULES_SCENE", ""),
        help="场景规则 id，对应 rules/describe_rules_<scene>.md；空=通用",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    set_rules_scene(args.rules_scene)
    describe_dataset(
        args.dataset, args.base_url, args.model,
        args.limit, args.force, workers=args.workers,
    )
