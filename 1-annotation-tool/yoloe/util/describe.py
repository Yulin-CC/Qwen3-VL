"""
# @Author: AI产品研发组
# @Date: 2026-08-05
# @Description: 调用 vLLM 为每个 crop 生成 >=3 条英文目标短语（支持并发）
# @Command: python util/describe.py --dataset /path/to/rm --workers 8
"""

import argparse
import json
import os
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
    "Output JSON only: {\"phrases\":[...]} with >=3 short English noun phrases "
    "(attribute / appearance / action). No markdown, no thinking."
)


def load_rules(scene: str = None) -> str:
    """加载当前/指定场景的 describe_rules*.md（见 rules_io）。"""
    return load_describe_rules(scene)


def fallback_phrases(label: str):
    return [
        label,
        f"{label} object",
        f"{label} in the scene",
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


def describe_object(client: VLLMClient, crop_abs: str, label: str, rules: str = ""):
    # 规则全文进 user prompt（与 caption 一致）；任务指令置后
    task = (
        f"Class label: {label}\n"
        f"Write AT LEAST 3 short English noun phrases covering: "
        f"(1) subtype/role (2) appearance/color (3) action/state.\n"
        f"Follow the rules above when they apply.\n"
        f'Return ONLY valid JSON, example: '
        f'{{"phrases":["blue scooter","two-wheeled vehicle","parked scooter"]}}'
    )
    if rules and str(rules).strip():
        prompt = str(rules).strip() + "\n\n" + task
    else:
        prompt = task
    last_err = None
    for _ in range(3):
        try:
            raw = client.describe_image(
                crop_abs, prompt,
                system=SYSTEM_PROMPT,
                max_tokens=256,
            )
            data = extract_json_object(raw)
            phrases = [
                p.strip() for p in (data.get("phrases") or [])
                if isinstance(p, str) and p.strip()
            ]
            if len(phrases) < 3:
                raise ValueError(f"模型返回短语不足 3 条: {phrases}")
            return {
                "label": label,
                "phrases": phrases[:8],
                "source": "vllm",
                "error": None,
                "zh": [],
            }
        except Exception as e:
            last_err = e
    raise RuntimeError(f"描述失败 ({label}): {last_err}")


def describe_one_object(dataset_root, stem, obj_id, client: VLLMClient, rules: str = "",
                        write: bool = True):
    """生成单目标描述。write=False 时只返回结果，由调用方决定是否落盘（避免半成品覆盖）。"""
    obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    with open(obj_path, encoding="utf-8") as f:
        meta = json.load(f)
    obj = next((o for o in meta["objects"] if o["obj_id"] == obj_id), None)
    if not obj:
        raise ValueError(f"obj_id 不存在: {obj_id}")
    crop_abs = os.path.join(dataset_root, obj["crop_path"])
    desc = describe_object(client, crop_abs, obj["label"], rules)
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
