"""
# @Author: AI产品研发组
# @Date: 2026-08-21
# @Description: describe 调度：按 rules_scene 加载 describe_<slug>.py，与 rules/describe_rules*.md 一一对应
# @Command: python util/describe.py --dataset /path/to/data --rules-scene appearance
#
# 对应关系（新增场景只加一对 md + 一份 py，不必改本文件）：
#   rules/describe_rules.md              ↔ util/describe_default.py
#   rules/describe_rules_appearance.md   ↔ util/describe_appearance.py
#   rules/describe_rules_<slug>.md       ↔ util/describe_<slug>.py
"""

import argparse
import importlib
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from tqdm import tqdm

# TMonitor 在 Windows / 管道捕获下会和主线程抢 write lock，atexit 时 join 死锁。
tqdm.monitor_interval = 0

from common import draft_dir, ensure_dir, load_json, write_json
from describe_common import (
    fallback_phrases,
    is_placeholder_desc,
    label_natural_reading,
    load_rules,
    locked_axis_tokens,
    phrase_content_key,
    phrase_synonym_key,
    shares_locked_axis,
)
from rules_io import (
    get_rules_scene,
    get_scene_policy,
    normalize_scene,
    resolve_describe_rules_path,
    set_rules_scene,
)
from vllm_client import VLLMClient


def scene_engine_name(scene=None) -> str:
    sc = normalize_scene(scene) if scene is not None else get_rules_scene()
    if not sc:
        return "describe_default"
    return "describe_" + sc.replace("-", "_")


def scene_engine(scene=None):
    """加载与当前 rules_scene 对应的 describe_<slug> 模块；缺失则回退 default。"""
    name = scene_engine_name(scene)
    try:
        return importlib.import_module(name)
    except ImportError:
        if name != "describe_default":
            print(f"⚠ 未找到 {name}.py，回退 describe_default.py（对应 describe_rules.md）")
        return importlib.import_module("describe_default")


def describe_object(client: VLLMClient, crop_abs: str, label: str, rules: str = "",
                    avoid_phrases=None, min_phrases=None, with_zh: bool = False,
                    max_retries: int = 3, seed_phrases=None, lock_phrases=None):
    desc = scene_engine().describe_object(
        client, crop_abs, label, rules=rules,
        avoid_phrases=avoid_phrases, min_phrases=min_phrases, with_zh=with_zh,
        max_retries=max_retries, seed_phrases=seed_phrases, lock_phrases=lock_phrases,
    )
    if isinstance(desc, dict):
        desc["rules_scene"] = get_rules_scene()
    return desc


def describe_one_object(dataset_root, stem, obj_id, client: VLLMClient, rules: str = "",
                        write: bool = True, avoid_phrases=None, min_phrases=None,
                        with_zh: bool = False, max_retries: int = 3, seed_phrases=None,
                        lock_phrases=None):
    obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    meta = load_json(obj_path)
    if not meta:
        raise FileNotFoundError(f"无 objects 数据: {stem}")
    obj = next((o for o in meta["objects"] if o["obj_id"] == obj_id), None)
    if not obj:
        raise ValueError(f"obj_id 不存在: {obj_id}")
    crop_abs = os.path.join(dataset_root, obj["crop_path"])
    desc = describe_object(
        client, crop_abs, obj["label"], rules,
        avoid_phrases=avoid_phrases, min_phrases=min_phrases,
        with_zh=with_zh, max_retries=max_retries, seed_phrases=seed_phrases,
        lock_phrases=lock_phrases,
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
        meta = load_json(obj_path)
        if not meta:
            continue
        for obj in meta.get("objects") or []:
            out_p = os.path.join(out_dir, f"{stem}_obj{obj['obj_id']:04d}.json")
            existing = load_json(out_p) if os.path.isfile(out_p) else None
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
            "exhaustive": False,
            "exhaustive_added": [],
        }
    desc["obj_id"] = job["obj_id"]
    desc["stem"] = job["stem"]
    write_json(job["out_p"], desc)
    return desc


def describe_image_objects(dataset_root, stem, client: VLLMClient, rules: str, force=False):
    jobs = _collect_jobs(dataset_root, [stem], force=force)
    results = []
    for job in jobs:
        results.append(_run_job(client, job, rules=rules or ""))
    obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    meta = load_json(obj_path)
    if not meta:
        return results
    done_ids = {r["obj_id"] for r in results}
    for obj in meta.get("objects") or []:
        if obj["obj_id"] in done_ids:
            continue
        p = os.path.join(draft_dir(dataset_root), "descriptions",
                         f"{stem}_obj{obj['obj_id']:04d}.json")
        if os.path.isfile(p):
            data = load_json(p)
            if data:
                results.append(data)
    return results


def _remaining_phrases(obj_phrases, pool_phrases):
    have = {phrase_content_key(p) for p in obj_phrases if phrase_content_key(p)}
    out, seen = [], set()
    for p in pool_phrases:
        key = phrase_content_key(p)
        if not key or key in have or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _unique_pool(phrases_lists):
    pool, seen = [], set()
    for phrases in phrases_lists:
        for p in phrases or []:
            if not isinstance(p, str) or not p.strip():
                continue
            key = phrase_content_key(p)
            if not key or key in seen:
                continue
            seen.add(key)
            pool.append(p.strip())
    return pool


def _load_image_descs(dataset_root, stem, objects):
    ddir = os.path.join(draft_dir(dataset_root), "descriptions")
    rows = []
    for obj in objects or []:
        path = os.path.join(ddir, f"{stem}_obj{obj['obj_id']:04d}.json")
        desc = load_json(path) if os.path.isfile(path) else None
        if not desc:
            desc = {
                "obj_id": obj["obj_id"],
                "stem": stem,
                "label": obj["label"],
                "phrases": [],
                "source": "missing",
                "exhaustive": False,
                "exhaustive_added": [],
            }
        rows.append({
            "stem": stem,
            "obj": obj,
            "desc": desc,
            "path": path,
            "crop_abs": os.path.join(dataset_root, obj["crop_path"]),
        })
    return rows


def _exhaustive_one(client, row, remaining, check_fn):
    """同类短语补查。max_phrases 只约束初次 describe；补查命中即可追加，不截断。"""
    desc = dict(row["desc"] or {})
    phrases = [p for p in (desc.get("phrases") or []) if isinstance(p, str) and p.strip()]
    added = []
    if remaining and check_fn:
        matched = check_fn(
            client, row["crop_abs"], desc.get("label") or row["obj"]["label"],
            already=phrases, candidates=remaining,
        )
        have = {phrase_content_key(p) for p in phrases}
        for p in matched:
            key = phrase_content_key(p)
            if not key or key in have:
                continue
            phrases.append(p)
            added.append(p)
            have.add(key)
    desc["phrases"] = phrases
    desc["exhaustive"] = True
    desc["exhaustive_added"] = added
    desc["obj_id"] = row["obj"]["obj_id"]
    desc["stem"] = row.get("stem") or desc.get("stem")
    write_json(row["path"], desc)
    return desc


def exhaustive_one_image(dataset_root, stem, client: VLLMClient, force=False, workers=8):
    obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    meta = load_json(obj_path)
    if not meta:
        return []
    rows = _load_image_descs(dataset_root, stem, meta.get("objects") or [])
    if not force and rows and all((r["desc"] or {}).get("exhaustive") for r in rows):
        return [r["desc"] for r in rows]

    check_fn = getattr(scene_engine(), "check_phrases_apply", None)
    by_class = defaultdict(list)
    for i, row in enumerate(rows):
        hint = label_natural_reading(row["obj"].get("label") or "")
        by_class[hint].append(i)

    jobs = []
    for hint, idxs in by_class.items():
        pool = _unique_pool([(rows[i]["desc"] or {}).get("phrases") for i in idxs])
        for i in idxs:
            phrases = (rows[i]["desc"] or {}).get("phrases") or []
            remaining = _remaining_phrases(phrases, pool)
            jobs.append((rows[i], remaining))

    results = []
    n_workers = max(1, int(workers or 1))
    if n_workers == 1 or len(jobs) <= 1:
        for row, remaining in jobs:
            results.append(_exhaustive_one(client, row, remaining, check_fn))
        return results

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = [
            pool.submit(_exhaustive_one, client, row, remaining, check_fn)
            for row, remaining in jobs
        ]
        for fut in as_completed(futs):
            results.append(fut.result())
    return results


def describe_dataset(dataset_root, base_url, model, limit=None, force=False,
                     workers=4, timeout=600, progress_cb=None, on_image_done=None):
    """on_image_done: optional callable(stem)，每张图 exhaustive 结束后调用（可用来立刻 caption）。"""
    obj_dir = os.path.join(draft_dir(dataset_root), "objects")
    assert os.path.isdir(obj_dir), "请先运行 crop"
    stems = sorted(Path(p).stem for p in Path(obj_dir).glob("*.json"))
    if limit:
        stems = stems[:limit]

    client = VLLMClient(base_url=base_url, model=model, timeout=timeout, enable_thinking=False)
    if not client.health_check():
        raise RuntimeError(
            f"vLLM 不可用: {base_url} 。请先启动 2-vllm 服务，或仅调试时显式传 --no_llm"
        )

    jobs = _collect_jobs(dataset_root, stems, force=force)
    rules = load_rules()
    rules_path = resolve_describe_rules_path()
    pol = get_scene_policy()
    eng = scene_engine_name()
    print(
        f"待描述目标: {len(jobs)} （workers={workers}, timeout={timeout}s, thinking=off, "
        f"scene={get_rules_scene() or 'default'}, engine={eng}.py, "
        f"rules={os.path.basename(rules_path)}, "
        f"max_phrases={pol.get('max_phrases')}, exhaustive={bool(pol.get('exhaustive'))}）"
    )

    if jobs:
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
    else:
        print("无需描述（均已完成）")
        if progress_cb and not pol.get("exhaustive"):
            progress_cb(1, 1, "无需描述")

    if pol.get("exhaustive"):
        print("→ exhaustive: 按图统计同类短语并补查（命中即可追加，不受 max_phrases 截断）")
        n_added = 0
        log_path = os.path.join(draft_dir(dataset_root), "exhaustive.log")
        for i, stem in enumerate(tqdm(stems, desc="exhaustive", mininterval=1.0), start=1):
            results = exhaustive_one_image(
                dataset_root, stem, client, force=force, workers=workers,
            )
            added_now = sum(len((r or {}).get("exhaustive_added") or []) for r in results)
            n_added += added_now
            if i == 1 or i % 20 == 0 or added_now:
                line = f"{i}/{len(stems)} {stem} +{added_now} (cum {n_added})\n"
                try:
                    with open(log_path, "a", encoding="utf-8") as lf:
                        lf.write(line)
                        lf.flush()
                except OSError:
                    pass
            if progress_cb:
                progress_cb(i, len(stems), f"exhaustive {i}/{len(stems)}")
            if on_image_done:
                on_image_done(stem)
        print(f"穷尽检查完成: {len(stems)} 图，补短语 {n_added} 条")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True)
    p.add_argument("--base_url", default="http://127.0.0.1:8081/v1")
    p.add_argument("--model", default="qwen3.6-35b-a3b")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument(
        "--rules-scene",
        default=os.environ.get("RULES_SCENE", ""),
        help="对应 rules/describe_rules_<scene>.md 与 util/describe_<scene>.py；空=default",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    set_rules_scene(args.rules_scene)
    describe_dataset(
        args.dataset, args.base_url, args.model,
        args.limit, args.force, workers=args.workers, timeout=args.timeout,
    )
