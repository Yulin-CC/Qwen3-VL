"""
# @Author: AI产品研发组
# @Date: 2026-08-21
# @Description: grounding 批量生成：check → crop → describe(+policy) → caption → 可选 export
# @Command: python util/generate.py --dataset /path/to/data --rules-scene appearance --limit 1
"""

import argparse
import os
import sys
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="Grounding 批量生成（default / appearance 由 --rules-scene 切换）")
    p.add_argument("--dataset", required=True, help="数据集根目录")
    p.add_argument("--expand_ratio", type=float, default=1.5)
    p.add_argument("--base_url", default="", help="空则读 model/server.json 的 default")
    p.add_argument("--model", default="", help="空则读 model/server.json 的 default")
    p.add_argument("--n_captions", type=int, default=5)
    p.add_argument("--limit", type=int, default=None, help="仅处理前 N 张")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no_llm", action="store_true", help="描述/caption 跳过模型（调试）")
    p.add_argument("--export", action="store_true", help="生成后导出 jsons-GD")
    p.add_argument("--workers", type=int, default=4, help="describe / exhaustive 并发")
    p.add_argument("--timeout", type=int, default=600, help="vLLM HTTP 超时秒数")
    p.add_argument(
        "--stages", default="all",
        help="all|check|crop|describe|caption|export 逗号分隔",
    )
    p.add_argument("--jsons", default="", help="jsons-segm|jsons-detect|jsons|空=自动")
    p.add_argument("--images", default="", help="images|空=自动")
    p.add_argument(
        "--rules-scene",
        default=os.environ.get("RULES_SCENE", ""),
        help="default 空=通用；appearance=只写外观",
    )
    return p.parse_args()


def _resolve_service(base_url, model):
    sys.path.insert(0, os.path.dirname(__file__))
    from servers_io import get_default_service
    svc = get_default_service() or {}
    url = (base_url or "").strip() or svc.get("base_url") or "http://127.0.0.1:8081/v1"
    name = (model or "").strip() or svc.get("model") or "qwen3.6-35b-a3b"
    return url.rstrip("/"), name, svc.get("name") or name


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
                 deep: bool = True, images_dirname="images") -> dict:
    """
    缺啥补啥评估。不传 force：已有非占位结果视为完成。
    deep=False：打开数据集快速路径——只做文件存在性统计，不逐文件解析
                 JSON / 不跑 captions_need_rebuild（预生成齐套时可从几十秒降到秒级）。
    以图像文件为准：缺图的 objects / 标签不计入宇宙。
    Returns:
      need_crop, need_describe, need_caption, ready, missing_* counts, stages[]
    """
    sys.path.insert(0, os.path.dirname(__file__))
    from common import (
        draft_dir,
        list_image_stems,
        load_json,
        normalize_images_dirname,
        normalize_jsons_dirname,
        read_draft_config,
        resolve_images_dir,
    )

    jsons_dirname = normalize_jsons_dirname(jsons_dirname)
    images_dirname = normalize_images_dirname(images_dirname)
    obj_dir = os.path.join(draft_dir(dataset_root), "objects")
    desc_dir = os.path.join(draft_dir(dataset_root), "descriptions")
    cap_dir = os.path.join(draft_dir(dataset_root), "captions")
    img_stems = list_image_stems(resolve_images_dir(dataset_root, images_dirname))

    obj_stems = [s for s in _listdir_stems(obj_dir) if (not img_stems or s in img_stems)]
    cap_stems_set = set(
        s for s in _listdir_stems(cap_dir) if (not img_stems or s in img_stems)
    )
    obj_stems_set = set(obj_stems)

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

    missing_desc = 0
    missing_cap = 0
    missing_objects = []
    stems = []

    if not deep:
        # 秒开：以 draft/objects 为宇宙，不 listdir 全量标签目录
        check_stems = obj_stems
        if limit:
            check_stems = check_stems[:limit]
        need_crop = bool(force_crop) or (not check_stems)
        stems = list(check_stems)
        desc_counts = _desc_counts_by_stem(desc_dir)
        for stem in check_stems:
            if stem not in cap_stems_set:
                missing_cap += 1
            if desc_counts.get(stem, 0) < 1:
                missing_desc += 1
        n_desc_files = sum(desc_counts.values())
        if check_stems and n_desc_files < len(check_stems):
            missing_desc = max(missing_desc, len(check_stems) - n_desc_files)
    else:
        stems = list_json_stems(dataset_root, limit=limit, jsons_dirname=jsons_dirname)
        if img_stems:
            stems = [s for s in stems if s in img_stems]
        if limit:
            keep = set(stems)
            obj_stems = [s for s in obj_stems if s in keep]
            obj_stems_set = set(obj_stems)
        missing_objects = [s for s in stems if s not in obj_stems_set]
        need_crop = bool(missing_objects) or force_crop
        check_stems = obj_stems if obj_stems else []
        from caption import captions_need_rebuild
        from describe import is_placeholder_desc

        for stem in check_stems:
            meta = load_json(os.path.join(obj_dir, f"{stem}.json")) or {}
            for obj in meta.get("objects") or []:
                oid = obj["obj_id"]
                path = os.path.join(desc_dir, f"{stem}_obj{oid:04d}.json")
                if not os.path.isfile(path):
                    missing_desc += 1
                    continue
                desc = load_json(path)
                if desc is None or is_placeholder_desc(desc):
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
        "n_images": len(img_stems),
        "n_objects": len(obj_stems),
        "missing_objects": len(missing_objects),
        "missing_desc": missing_desc,
        "missing_cap": missing_cap,
        "stages": stages,
        "jsons_dirname": jsons_dirname,
        "images_dirname": images_dirname,
        "prev_jsons_dirname": prev_jsons or None,
        "geometry": cur_geom or None,
        "prev_geometry": prev_geom or None,
        "deep": bool(deep),
    }


#-------------#
# 执行生成 stages
#-------------#
def check_dataset(dataset_root, jsons_dirname="", images_dirname="", log=print):
    sys.path.insert(0, os.path.dirname(__file__))
    from common import detect_dataset_layout
    layout = detect_dataset_layout(
        dataset_root,
        images_dirname=images_dirname or None,
        jsons_dirname=jsons_dirname or None,
    )
    if not layout.get("ok"):
        raise RuntimeError(layout.get("error") or "数据集布局检查失败")
    geom = layout.get("geometry") or "auto"
    log(
        f"✓ 布局: images={layout['images_dirname']} ({layout['n_images']})  "
        f"jsons={layout['jsons_dirname']} ({layout['n_jsons']})  "
        f"配对 {layout['n_paired']}  geom={geom}"
    )
    if layout.get("n_img_only"):
        log(f"  ⚠ 仅有图无标签: {layout['n_img_only']}")
    if layout.get("n_json_only"):
        log(f"  ⚠ 仅有标签无图: {layout['n_json_only']}")
    if layout["n_paired"] <= 0:
        raise RuntimeError("图像与标签 stem 无配对，请检查文件名是否一致")
    return layout


def run_generate(
    dataset_root,
    stages=None,
    expand_ratio=1.5,
    base_url="",
    model="",
    n_captions=5,
    limit=None,
    force=False,
    no_llm=False,
    workers=4,
    timeout=600,
    log=None,
    jsons_dirname="",
    images_dirname="",
    progress=None,
    prefer_geometry=None,
    rules_scene=None,
):
    """
    供 CLI / Flask 共用。stages 为 set/list；None 时按 assess_draft 自动选。
    log: callable(str) 可选日志回调。
    progress: optional callable(stage, done, total, detail) 细粒度百分比。
    """
    sys.path.insert(0, os.path.dirname(__file__))
    from common import (
        geometry_for_jsons_dirname,
        normalize_images_dirname,
        normalize_jsons_dirname,
        write_draft_config,
    )
    from rules_io import get_rules_scene, get_scene_policy, set_rules_scene

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

    if rules_scene is not None:
        set_rules_scene(rules_scene)
    scene = get_rules_scene()
    pol = get_scene_policy()
    try:
        write_draft_config(dataset_root, {"rules_scene": scene})
    except Exception:
        pass

    layout = None
    if not (jsons_dirname or "").strip() or not (images_dirname or "").strip():
        layout = check_dataset(
            dataset_root,
            jsons_dirname=jsons_dirname,
            images_dirname=images_dirname,
            log=_log,
        )
        jsons_dirname = layout["jsons_dirname"]
        images_dirname = layout["images_dirname"]
        if prefer_geometry is None:
            prefer_geometry = layout.get("geometry") or geometry_for_jsons_dirname(jsons_dirname)
    else:
        jsons_dirname = normalize_jsons_dirname(jsons_dirname)
        images_dirname = normalize_images_dirname(images_dirname)
        if prefer_geometry is None:
            prefer_geometry = geometry_for_jsons_dirname(jsons_dirname)

    _log(
        f"rules_scene={scene or 'default'}  max_phrases={pol.get('max_phrases')}  "
        f"ban_subtypes={bool(pol.get('ban_vehicle_subtypes'))}  "
        f"exhaustive={bool(pol.get('exhaustive'))}  "
        f"caption_cover_all={bool(pol.get('caption_cover_all'))}"
    )

    url, model_name, svc_name = _resolve_service(base_url, model)

    if stages is None:
        assessment = assess_draft(
            dataset_root, limit=limit, jsons_dirname=jsons_dirname,
            images_dirname=images_dirname,
        )
        stages = set(assessment["stages"])
        _log(f"assess: {assessment}")
    else:
        stages = set(stages)
    stages.discard("check")
    stages.discard("all")

    if not stages:
        _log("draft 已完整，跳过 generate")
        return {"ok": True, "skipped": True, "stages": [], "layout": layout}

    need_llm = (("describe" in stages) or ("caption" in stages)) and not no_llm
    if need_llm:
        from vllm_client import VLLMClient
        client = VLLMClient(base_url=url, model=model_name, timeout=timeout)
        if not client.health_check():
            raise RuntimeError(f"vLLM 不可用 ({url} / {svc_name})。请检查 model/server.json")
        _log(f"✓ vLLM 就绪: {url} model={model_name} ({svc_name})")
    elif no_llm and (("describe" in stages) or ("caption" in stages)):
        _log("⚠ 使用 --no_llm：描述将是占位短语，仅供调试")

    ran = []
    pipeline_caption = False
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
        from describe import describe_dataset, fallback_phrases, is_placeholder_desc
        from common import draft_dir, load_json, write_json
        _log("→ stage: describe" + (" (+exhaustive)" if pol.get("exhaustive") else ""))
        if no_llm:
            obj_dir = os.path.join(draft_dir(dataset_root), "objects")
            out_dir = os.path.join(draft_dir(dataset_root), "descriptions")
            os.makedirs(out_dir, exist_ok=True)
            stems = sorted(Path(p).stem for p in Path(obj_dir).glob("*.json"))
            if limit:
                stems = stems[:limit]
            total = len(stems)
            for i, stem in enumerate(stems, start=1):
                meta = load_json(os.path.join(obj_dir, f"{stem}.json")) or {}
                for obj in meta.get("objects") or []:
                    out_p = os.path.join(out_dir, f"{stem}_obj{obj['obj_id']:04d}.json")
                    if not force and os.path.isfile(out_p):
                        existing = load_json(out_p)
                        if existing and not is_placeholder_desc(existing):
                            continue
                    write_json(out_p, {
                        "obj_id": obj["obj_id"],
                        "stem": stem,
                        "label": obj["label"],
                        "phrases": fallback_phrases(obj["label"]),
                        "source": "no_llm",
                        "error": "no_llm",
                        "zh": [],
                        "exhaustive": False,
                        "exhaustive_added": [],
                    })
                _prog("describe", i, total, f"{i}/{total}")
            _log(f"[no_llm] 描述占位完成: {len(stems)} 图")
        else:
            on_image_done = None
            cap_pool = None
            pipeline_caption = ("caption" in stages) and bool(pol.get("exhaustive"))
            if pipeline_caption:
                from concurrent.futures import ThreadPoolExecutor
                from caption import caption_one_image
                from common import draft_dir, ensure_dir
                import threading
                ensure_dir(os.path.join(draft_dir(dataset_root), "captions"))
                cap_workers = max(1, min(2, int(workers) or 1))
                cap_pool = ThreadPoolExecutor(max_workers=cap_workers)
                cap_client = None if no_llm else client
                n_pipe = {"ok": 0, "fail": 0}
                pipe_lock = threading.Lock()
                cap_log = os.path.join(draft_dir(dataset_root), "caption-pipeline.log")
                _log(
                    f"→ caption 流水线: 每张 exhaustive 完成后立即排队 "
                    f"（workers={cap_workers}）"
                )

                def _cap_one(stem):
                    try:
                        caption_one_image(
                            dataset_root, stem, client=cap_client,
                            n_captions=n_captions, force=force,
                        )
                        with pipe_lock:
                            n_pipe["ok"] += 1
                            n_ok = n_pipe["ok"]
                        if n_ok == 1 or n_ok % 20 == 0:
                            line = f"caption {n_ok} {stem}\n"
                            try:
                                with open(cap_log, "a", encoding="utf-8") as lf:
                                    lf.write(line)
                                    lf.flush()
                            except OSError:
                                pass
                    except Exception as e:
                        with pipe_lock:
                            n_pipe["fail"] += 1
                        print(f"  ⚠ caption {stem}: {e}")

                def on_image_done(stem):
                    cap_pool.submit(_cap_one, stem)

            describe_dataset(
                dataset_root, url, model_name,
                limit=limit, force=force, workers=workers, timeout=timeout,
                progress_cb=lambda d, t, det="": _prog("describe", d, t, det),
                on_image_done=on_image_done,
            )
            if cap_pool is not None:
                cap_pool.shutdown(wait=True)
                _log(
                    f"caption 流水线结束: ok={n_pipe['ok']} fail={n_pipe['fail']}"
                )
        ran.append("describe")

    if "caption" in stages:
        from caption import caption_dataset
        _log("→ stage: caption" + ("（补漏，已有会跳过）" if pipeline_caption else ""))
        caption_dataset(
            dataset_root, url, model_name,
            n_captions=n_captions, limit=limit,
            force=force, no_llm=no_llm, timeout=timeout,
            progress_cb=lambda d, t, det="": _prog("caption", d, t, det),
        )
        ran.append("caption")

    if "export" in stages:
        from export_gd import export_dataset
        _log("→ stage: export")
        export_dataset(dataset_root, limit=limit)
        ran.append("export")

    _log("generate 完成")
    return {"ok": True, "skipped": False, "stages": ran, "layout": layout}


def main():
    sys.path.insert(0, os.path.dirname(__file__))
    args = parse_args()
    from rules_io import set_rules_scene
    set_rules_scene(args.rules_scene)
    stages = set(s.strip() for s in args.stages.split(",") if s.strip())
    if "all" in stages:
        stages = {"check", "crop", "describe", "caption"}
        if args.export:
            stages.add("export")
    if args.export:
        stages.add("export")

    run_generate(
        args.dataset,
        stages=stages,
        expand_ratio=args.expand_ratio,
        base_url=args.base_url,
        model=args.model,
        n_captions=args.n_captions,
        limit=args.limit,
        force=args.force,
        no_llm=args.no_llm,
        workers=args.workers,
        timeout=args.timeout,
        jsons_dirname=args.jsons,
        images_dirname=args.images,
        rules_scene=args.rules_scene,
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        raise SystemExit(f"错误: {e}")
