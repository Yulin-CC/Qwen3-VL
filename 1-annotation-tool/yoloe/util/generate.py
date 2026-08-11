"""
# @Author: AI产品研发组
# @Date: 2026-08-05
# @Description: grounding 批量生成入口：crop → describe → caption → 可选 export
# @Command: python util/generate.py --dataset /path/to/rm --limit 2
"""

import argparse
import json
import os
import sys
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="YOLOE grounding 批量生成")
    p.add_argument("--dataset", required=True, help="数据集根目录（图像/标签目录可用 --images/--jsons 指定）")
    p.add_argument("--expand_ratio", type=float, default=1.5)
    p.add_argument("--base_url", default="http://127.0.0.1:8081/v1")
    p.add_argument("--model", default="qwen3.6-35b-a3b")
    p.add_argument("--n_captions", type=int, default=5)
    p.add_argument("--limit", type=int, default=None, help="仅处理前 N 张（试验用）")
    p.add_argument("--force", action="store_true")
    p.add_argument("--skip_describe", action="store_true")
    p.add_argument("--skip_caption", action="store_true")
    p.add_argument("--no_llm", action="store_true", help="描述/caption 跳过模型（调试）")
    p.add_argument("--export", action="store_true", help="生成后直接导出 jsons-GD")
    p.add_argument("--workers", type=int, default=8, help="describe 并发数（默认 8）")
    p.add_argument("--stages", default="all",
                   help="all|crop|describe|caption|export 逗号分隔")
    p.add_argument("--jsons", default="jsons", help="jsons|jsons-det|jsons-segm|绝对路径")
    p.add_argument("--images", default="images", help="images|JPEGImages|.|绝对路径")
    return p.parse_args()


#-------------#
# 列出 json stem
#-------------#
def list_json_stems(dataset_root, limit=None, jsons_dirname="jsons"):
    sys.path.insert(0, os.path.dirname(__file__))
    from common import resolve_jsons_dir
    json_dir = resolve_jsons_dir(dataset_root, jsons_dirname)
    if not os.path.isdir(json_dir):
        return []
    from common import list_label_filenames
    stems = sorted(Path(f).stem for f in list_label_filenames(json_dir))
    if limit:
        stems = stems[:limit]
    return stems


#-------------#
# 评估 draft 缺口
#-------------#
def _listdir_stems(dir_path, suffix=".json"):
    if not os.path.isdir(dir_path):
        return []
    out = []
    try:
        with os.scandir(dir_path) as it:
            for ent in it:
                if ent.is_file() and ent.name.endswith(suffix):
                    out.append(Path(ent.name).stem)
    except OSError:
        return []
    out.sort()
    return out


def _desc_counts_by_stem(desc_dir):
    """stem -> 描述文件数（一次 scandir，不读内容）。"""
    counts = {}
    if not os.path.isdir(desc_dir):
        return counts
    try:
        with os.scandir(desc_dir) as it:
            for ent in it:
                if not ent.is_file() or not ent.name.endswith(".json"):
                    continue
                # {stem}_obj0001.json
                base = ent.name[:-5]
                if "_obj" not in base:
                    continue
                stem = base.rsplit("_obj", 1)[0]
                counts[stem] = counts.get(stem, 0) + 1
    except OSError:
        return {}
    return counts


def assess_draft(dataset_root, limit=None, jsons_dirname="jsons", geometry=None,
                 deep: bool = True) -> dict:
    """
    缺啥补啥评估。不传 force：已有非占位结果视为完成。
    deep=False：打开数据集快速路径——只做文件存在性统计，不逐文件解析
                 JSON / 不跑 captions_need_rebuild（预生成齐套时可从几十秒降到秒级）。
    Returns:
      need_crop, need_describe, need_caption, ready, missing_* counts, stages[]
    """
    sys.path.insert(0, os.path.dirname(__file__))
    from common import draft_dir, normalize_jsons_dirname, read_draft_config

    jsons_dirname = normalize_jsons_dirname(jsons_dirname)
    stems = list_json_stems(dataset_root, limit=limit, jsons_dirname=jsons_dirname)
    obj_dir = os.path.join(draft_dir(dataset_root), "objects")
    desc_dir = os.path.join(draft_dir(dataset_root), "descriptions")
    cap_dir = os.path.join(draft_dir(dataset_root), "captions")

    obj_stems = _listdir_stems(obj_dir)
    if limit:
        keep = set(stems)
        obj_stems = [s for s in obj_stems if s in keep]
    cap_stems_set = set(_listdir_stems(cap_dir))
    obj_stems_set = set(obj_stems)

    missing_objects = [s for s in stems if s not in obj_stems_set]

    # 标签目录 / 几何属性切换后需重裁，才能让主窗口画正确的框/多边形
    draft_cfg = read_draft_config(dataset_root) if os.path.isdir(draft_dir(dataset_root)) else {}
    prev_jsons = normalize_jsons_dirname(draft_cfg.get("jsons_dirname") or "")
    prev_geom = (draft_cfg.get("geometry") or "").strip().lower()
    cur_geom = (geometry or "").strip().lower()
    has_objects = bool(obj_stems)
    source_mismatch = bool(
        has_objects and prev_jsons and prev_jsons != jsons_dirname
    )
    geometry_mismatch = bool(
        has_objects and prev_geom and cur_geom and prev_geom != cur_geom
    )
    force_crop = source_mismatch or geometry_mismatch
    need_crop = bool(missing_objects) or force_crop

    missing_desc = 0
    missing_cap = 0
    check_stems = obj_stems if obj_stems else []

    if not deep:
        # 快速：caption 缺文件即算缺；describe 用「每图至少有描述文件」+
        # 描述总数与目标文件数的粗检（不打开 objects/desc 内容）
        desc_counts = _desc_counts_by_stem(desc_dir)
        for stem in check_stems:
            if stem not in cap_stems_set:
                missing_cap += 1
            n_desc = desc_counts.get(stem, 0)
            if n_desc < 1:
                missing_desc += 1
        # 若描述文件总数明显偏少（多目标图），标 need_describe，触发后续补齐
        n_desc_files = sum(desc_counts.values())
        if check_stems and n_desc_files < len(check_stems):
            missing_desc = max(missing_desc, len(check_stems) - n_desc_files)
    else:
        from caption import captions_need_rebuild
        from describe import is_placeholder_desc

        for stem in check_stems:
            with open(os.path.join(obj_dir, f"{stem}.json"), encoding="utf-8") as f:
                meta = json.load(f)
            for obj in meta.get("objects") or []:
                oid = obj["obj_id"]
                path = os.path.join(desc_dir, f"{stem}_obj{oid:04d}.json")
                if not os.path.isfile(path):
                    missing_desc += 1
                    continue
                with open(path, encoding="utf-8") as f:
                    desc = json.load(f)
                if is_placeholder_desc(desc):
                    missing_desc += 1

            if captions_need_rebuild(dataset_root, stem):
                missing_cap += 1

    # LLM 阶段仅看 draft 缺口；force_crop 本身不强制重跑 describe/caption（避免离线误触 vLLM）
    # 尚无 objects 时：crop 后必需要 LLM，先标上以便进度展示（真正 health_check 仍在 run_generate）
    if not obj_stems:
        need_describe = True
        need_caption = True
    else:
        need_describe = missing_desc > 0
        need_caption = missing_cap > 0

    stages = []
    if need_crop:
        stages.append("crop")
    if need_describe:
        stages.append("describe")
    if need_caption:
        stages.append("caption")

    return {
        "need_crop": need_crop,
        "need_describe": need_describe,
        "need_caption": need_caption,
        "ready": not stages,
        "force_crop": force_crop,
        "n_json": len(stems),
        "n_objects": len(obj_stems),
        "missing_objects": len(missing_objects),
        "missing_desc": missing_desc,
        "missing_cap": missing_cap,
        "stages": stages,
        "jsons_dirname": jsons_dirname,
        "prev_jsons_dirname": prev_jsons or None,
        "geometry": cur_geom or None,
        "prev_geometry": prev_geom or None,
        "deep": bool(deep),
    }


#-------------#
# 执行生成 stages
#-------------#
def run_generate(
    dataset_root,
    stages=None,
    expand_ratio=1.5,
    base_url="http://127.0.0.1:8081/v1",
    model="qwen3.6-35b-a3b",
    n_captions=5,
    limit=None,
    force=False,
    no_llm=False,
    workers=8,
    log=None,
    jsons_dirname="jsons",
    images_dirname="images",
    progress=None,
    prefer_geometry=None,
):
    """
    供 CLI / Flask 共用。stages 为 set/list；None 时按 assess_draft 自动选。
    log: callable(str) 可选日志回调。
    progress: optional callable(stage, done, total, detail) 细粒度百分比。
    """
    sys.path.insert(0, os.path.dirname(__file__))
    from common import normalize_images_dirname, normalize_jsons_dirname
    jsons_dirname = normalize_jsons_dirname(jsons_dirname)
    images_dirname = normalize_images_dirname(images_dirname)

    def _log(msg):
        print(msg)
        if log:
            try:
                log(msg)
            except Exception:
                pass

    def _prog(stage, done, total, detail=""):
        if not progress:
            return
        try:
            progress(stage, done, total, detail)
        except Exception:
            pass

    if stages is None:
        assessment = assess_draft(
            dataset_root, limit=limit, jsons_dirname=jsons_dirname,
        )
        stages = set(assessment["stages"])
        _log(f"assess: {assessment}")
    else:
        stages = set(stages)

    if not stages:
        _log("draft 已完整，跳过 generate")
        return {"ok": True, "skipped": True, "stages": []}

    need_llm = (("describe" in stages) or ("caption" in stages)) and not no_llm
    if need_llm:
        from vllm_client import VLLMClient
        client = VLLMClient(base_url=base_url, model=model)
        if not client.health_check():
            raise RuntimeError(
                f"vLLM 不可用 ({base_url})。请先启动 2-vllm 服务后再生成"
            )
        _log(f"✓ vLLM 就绪: {base_url} model={model}")
    elif no_llm and (("describe" in stages) or ("caption" in stages)):
        _log("⚠ 使用 --no_llm：描述将是占位短语，仅供调试")

    ran = []
    if "crop" in stages:
        from crop_objects import crop_dataset
        _log("→ stage: crop" + (" (force)" if force else ""))
        crop_dataset(
            dataset_root, expand_ratio=expand_ratio, limit=limit, force=force,
            jsons_dirname=jsons_dirname,
            images_dirname=images_dirname,
            progress_cb=lambda d, t, det="": _prog("crop", d, t, det),
            prefer_geometry=prefer_geometry,
        )
        ran.append("crop")

    if "describe" in stages:
        from describe import describe_dataset, fallback_phrases
        from common import draft_dir, write_json
        _log("→ stage: describe")
        if no_llm:
            obj_dir = os.path.join(draft_dir(dataset_root), "objects")
            out_dir = os.path.join(draft_dir(dataset_root), "descriptions")
            os.makedirs(out_dir, exist_ok=True)
            stems = sorted(Path(p).stem for p in Path(obj_dir).glob("*.json"))
            if limit:
                stems = stems[:limit]
            total = len(stems)
            for i, stem in enumerate(stems, start=1):
                with open(os.path.join(obj_dir, f"{stem}.json"), encoding="utf-8") as f:
                    meta = json.load(f)
                for obj in meta["objects"]:
                    out_p = os.path.join(out_dir, f"{stem}_obj{obj['obj_id']:04d}.json")
                    if not force and os.path.isfile(out_p):
                        continue
                    desc = {
                        "obj_id": obj["obj_id"],
                        "stem": stem,
                        "label": obj["label"],
                        "phrases": fallback_phrases(obj["label"]),
                        "source": "no_llm",
                        "error": "no_llm",
                        "zh": [],
                    }
                    write_json(out_p, desc)
                _prog("describe", i, total, f"{i}/{total}")
            _log(f"[no_llm] 描述占位完成: {len(stems)} 图")
        else:
            describe_dataset(
                dataset_root, base_url, model,
                limit=limit, force=force, workers=workers,
                progress_cb=lambda d, t, det="": _prog("describe", d, t, det),
            )
        ran.append("describe")

    if "caption" in stages:
        from caption import caption_dataset
        _log("→ stage: caption")
        caption_dataset(
            dataset_root, base_url, model,
            n_captions=n_captions, limit=limit,
            force=force, no_llm=no_llm,
            progress_cb=lambda d, t, det="": _prog("caption", d, t, det),
        )
        ran.append("caption")

    if "export" in stages:
        from export_gd import export_dataset
        _log("→ stage: export")
        export_dataset(dataset_root, limit=limit)
        ran.append("export")

    _log("generate 完成")
    return {"ok": True, "skipped": False, "stages": ran}


def main():
    sys.path.insert(0, os.path.dirname(__file__))
    args = parse_args()
    stages = set(s.strip() for s in args.stages.split(","))
    if "all" in stages:
        stages = {"crop", "describe", "caption"}
        if args.export:
            stages.add("export")

    need_llm = (("describe" in stages and not args.skip_describe) or
                ("caption" in stages and not args.skip_caption))
    if need_llm and args.no_llm:
        print("⚠ 使用 --no_llm：描述将是占位短语（如 'car object'），仅供调试，不可用于正式标注")
    if need_llm and not args.no_llm:
        from vllm_client import VLLMClient
        client = VLLMClient(base_url=args.base_url, model=args.model)
        if not client.health_check():
            raise SystemExit(
                f"错误: vLLM 不可用 ({args.base_url})。请先启动 2-vllm 服务后再运行 "
                f"0-generate.sh（不要加 --no_llm）"
            )
        print(f"✓ vLLM 就绪: {args.base_url} model={args.model}")

    run_stages = set()
    if "crop" in stages:
        run_stages.add("crop")
    if "describe" in stages and not args.skip_describe:
        run_stages.add("describe")
    if "caption" in stages and not args.skip_caption:
        run_stages.add("caption")
    if "export" in stages or args.export:
        run_stages.add("export")

    run_generate(
        args.dataset,
        stages=run_stages,
        expand_ratio=args.expand_ratio,
        base_url=args.base_url,
        model=args.model,
        n_captions=args.n_captions,
        limit=args.limit,
        force=args.force,
        no_llm=args.no_llm,
        workers=args.workers,
        jsons_dirname=args.jsons,
        images_dirname=args.images,
    )


if __name__ == "__main__":
    main()
