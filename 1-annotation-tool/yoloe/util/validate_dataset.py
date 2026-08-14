"""
# @Author: AI产品研发组
# @Date: 2026-08-05
# @Description: 校验数据集 images/+jsons*/ 结构（rectangle / polygon / 二者皆可）
# @Command: python util/validate_dataset.py --dataset /path/to/rm --jsons jsons-det
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from common import (
    IMG_EXTS,
    LABEL_EXTS,
    draft_dir,
    ensure_dir,
    find_image_path,
    list_image_stems,
    list_images_options,
    list_jsons_options,
    list_label_filenames,
    load_labelme,
    normalize_images_dirname,
    normalize_jsons_dirname,
    read_draft_config,
    resolve_images_dir,
    resolve_jsons_dir,
    write_json,
)


ALLOWED_TYPES = {"rectangle", "polygon"}
VALIDATE_LOG_NAME = "validate_log.json"


#-------------#
# 规范化类型
#-------------#
def normalize_shape_type(raw) -> str:
    t = (raw or "").strip().lower()
    if t in ALLOWED_TYPES:
        return t
    return t


def validate_log_path(dataset_root: str) -> str:
    return os.path.join(draft_dir(dataset_root), VALIDATE_LOG_NAME)


#-------------#
# 目录签名（scandir 聚合，不解析标签、不拼全量文件名）
#-------------#
def build_validate_signature(root: str, jsons_dirname: str, images_dirname: str) -> dict:
    jsons_dirname = normalize_jsons_dirname(jsons_dirname)
    images_dirname = normalize_images_dirname(images_dirname)
    img_dir = resolve_images_dir(root, images_dirname)
    json_dir = resolve_jsons_dir(root, jsons_dirname)

    n_labels = 0
    max_mtime = 0.0
    size_sum = 0
    # 轻量指纹：数量 + 体积 + 最晚 mtime + 首尾文件名（避免万级文件拼 md5）
    first_name = ""
    last_name = ""
    if os.path.isdir(json_dir):
        try:
            with os.scandir(json_dir) as it:
                for ent in it:
                    if not ent.is_file():
                        continue
                    if Path(ent.name).suffix.lower() not in LABEL_EXTS:
                        continue
                    n_labels += 1
                    if not first_name or ent.name < first_name:
                        first_name = ent.name
                    if ent.name > last_name:
                        last_name = ent.name
                    try:
                        st = ent.stat()
                        max_mtime = max(max_mtime, float(st.st_mtime))
                        size_sum += int(st.st_size)
                    except OSError:
                        pass
        except OSError:
            pass

    n_images = 0
    if os.path.isdir(img_dir):
        try:
            with os.scandir(img_dir) as it:
                for ent in it:
                    if ent.is_file() and Path(ent.name).suffix.lower() in IMG_EXTS:
                        n_images += 1
        except OSError:
            pass

    raw = f"{n_labels}:{size_sum}:{int(max_mtime)}:{first_name}:{last_name}:{n_images}"
    fp = hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()
    return {
        "images_dirname": images_dirname,
        "jsons_dirname": jsons_dirname,
        "n_labels": n_labels,
        "n_images": n_images,
        "labels_fingerprint": fp,
        "labels_mtime_max": max_mtime,
        "labels_size_sum": size_sum,
    }


def _read_validate_log(dataset_root: str) -> dict:
    path = validate_log_path(dataset_root)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write_validate_log(dataset_root: str, signature: dict, result: dict):
    ensure_dir(draft_dir(dataset_root))
    payload = {
        "version": 1,
        "validated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "signature": signature,
        "result": {
            "ok": bool(result.get("ok")),
            "geometry": result.get("geometry"),
            "jsons_dirname": result.get("jsons_dirname"),
            "images_dirname": result.get("images_dirname"),
            "errors": list(result.get("errors") or []),
            "stats": dict(result.get("stats") or {}),
        },
    }
    write_json(validate_log_path(dataset_root), payload)


def _result_from_log(log: dict, options: list, img_options: list) -> dict:
    r = dict(log.get("result") or {})
    r["jsons_options"] = options
    r["images_options"] = img_options
    r["from_cache"] = True
    r["cache_path"] = VALIDATE_LOG_NAME
    return r


#-------------#
# 全量校验（读每个标签）
#-------------#
def _validate_dataset_full(root: str, jsons_dirname: str, images_dirname: str) -> dict:
    errors = []
    jsons_dirname = normalize_jsons_dirname(jsons_dirname)
    images_dirname = normalize_images_dirname(images_dirname)
    stats = {
        "n_json": 0,
        "n_images": 0,
        "n_images_matched": 0,
        "n_labels_skipped_no_image": 0,
        "n_shapes": 0,
        "n_rectangle": 0,
        "n_polygon": 0,
    }
    geometry = None
    options = list_jsons_options(root) if root else []
    img_options = list_images_options(root) if root else []

    def _fail(errs):
        return {
            "ok": False,
            "geometry": None,
            "jsons_dirname": jsons_dirname,
            "images_dirname": images_dirname,
            "jsons_options": options,
            "images_options": img_options,
            "errors": errs,
            "stats": stats,
            "from_cache": False,
        }

    if not root or not os.path.isdir(root):
        return _fail([f"目录不存在: {root}"])

    img_dir = resolve_images_dir(root, images_dirname)
    json_dir = resolve_jsons_dir(root, jsons_dirname)
    img_label = "根目录" if images_dirname == "." else images_dirname
    img_stems = set()
    if not os.path.isdir(img_dir):
        hint = f"可选: {', '.join(img_options)}" if img_options else "未发现含图片的目录"
        errors.append(f"缺少图像目录 {img_label}: {img_dir}（{hint}）")
    else:
        img_stems = list_image_stems(img_dir)
        stats["n_images"] = len(img_stems)
        if not img_stems:
            errors.append(f"图像目录为空或无图片: {img_dir}")

    if not os.path.isdir(json_dir):
        hint = (
            f"可选: {', '.join(options)}"
            if options
            else "未发现 jsons*/annotations/xmls 等标签目录"
        )
        errors.append(f"缺少标签目录 {jsons_dirname}/: {json_dir}（{hint}）")
        return _fail(errors)

    files = list_label_filenames(json_dir)
    if not files:
        errors.append(f"{jsons_dirname}/ 下无 .json/.xml 标签: {json_dir}")
        return _fail(errors)

    # 以图像为准：无对应图像的标签直接跳过，不报错、不计入校验总数
    seen_types = set()
    for fname in files:
        path = os.path.join(json_dir, fname)
        stem = Path(fname).stem
        if img_stems and stem not in img_stems:
            # imagePath 提示偶发与文件名不一致时再试一次
            try:
                peek = load_labelme(path)
                hint_name = (peek.get("imagePath") or "").strip()
            except Exception:
                hint_name = ""
            if not (hint_name and find_image_path(img_dir, stem, hint_name)):
                stats["n_labels_skipped_no_image"] += 1
                continue

        stats["n_json"] += 1
        try:
            data = load_labelme(path)
        except Exception as e:
            kind = "XML" if fname.lower().endswith(".xml") else "JSON"
            errors.append(f"{fname}: 无法解析 {kind} ({e})")
            continue

        shapes = data.get("shapes") or []
        valid_shapes = []
        for i, shape in enumerate(shapes):
            pts = shape.get("points") or []
            if not pts:
                continue
            st = normalize_shape_type(shape.get("shape_type"))
            if st not in ALLOWED_TYPES:
                errors.append(
                    f"{fname}: shapes[{i}] shape_type 非法 "
                    f"'{shape.get('shape_type')}'（仅允许 rectangle/polygon）"
                )
                continue
            valid_shapes.append(st)

        if not valid_shapes:
            # VOC 常见空标注 XML：跳过不报错；LabelMe JSON 仍要求至少一框
            if fname.lower().endswith(".xml"):
                continue
            errors.append(f"{fname}: shapes 为空或无有效 points，不能没有任何标注")
            continue

        for st in valid_shapes:
            seen_types.add(st)
            stats["n_shapes"] += 1
            if st == "rectangle":
                stats["n_rectangle"] += 1
            else:
                stats["n_polygon"] += 1

        stats["n_images_matched"] += 1

    if stats["n_json"] == 0 and files:
        errors.append(
            f"标签均无对应图像，已跳过 {stats['n_labels_skipped_no_image']} 个空标签"
            f"（以图像为准，当前图像数={stats['n_images']}）"
        )

    if len(seen_types) > 1:
        geometry = "mixed"
    elif len(seen_types) == 1:
        geometry = next(iter(seen_types))
    elif stats["n_json"] > 0 and not seen_types:
        errors.append("所有标签均无有效 rectangle/polygon 标注")

    return {
        "ok": len(errors) == 0,
        "geometry": geometry,
        "jsons_dirname": jsons_dirname,
        "images_dirname": images_dirname,
        "jsons_options": options,
        "images_options": img_options,
        "errors": errors,
        "stats": stats,
        "from_cache": False,
    }


def _count_json_stems(dir_path: str) -> int:
    if not os.path.isdir(dir_path):
        return 0
    n = 0
    try:
        with os.scandir(dir_path) as it:
            for ent in it:
                if ent.is_file() and ent.name.endswith(".json"):
                    n += 1
    except OSError:
        return 0
    return n


def _soft_validate_from_draft(root, jsons_dirname, images_dirname, signature,
                              options, img_options):
    """
    draft 已齐套且 config 带 geometry 时，跳过全量读标签。
    条件：objects/captions 数量 ≥ 标签数，且 config 目录与当前一致。
    """
    cfg = read_draft_config(root) if os.path.isdir(draft_dir(root)) else {}
    if not cfg:
        return None
    if normalize_jsons_dirname(cfg.get("jsons_dirname") or "") != jsons_dirname:
        return None
    if normalize_images_dirname(cfg.get("images_dirname") or "") != images_dirname:
        return None
    geom = (cfg.get("geometry") or "").strip().lower()
    if geom not in {"rectangle", "polygon", "mixed"}:
        return None
    n_labels = int(signature.get("n_labels") or 0)
    n_images = int(signature.get("n_images") or 0)
    # 以图像为准：齐套门槛取「有图可对齐」规模（标签与图像的交集上界）
    n_expect = min(n_labels, n_images) if (n_labels and n_images) else (n_labels or n_images)
    if n_expect < 1:
        return None
    n_obj = _count_json_stems(os.path.join(draft_dir(root), "objects"))
    n_cap = _count_json_stems(os.path.join(draft_dir(root), "captions"))
    if n_obj < n_expect or n_cap < n_expect:
        return None
    img_dir = resolve_images_dir(root, images_dirname)
    if not os.path.isdir(img_dir):
        return None
    return {
        "ok": True,
        "geometry": geom,
        "jsons_dirname": jsons_dirname,
        "images_dirname": images_dirname,
        "jsons_options": options,
        "images_options": img_options,
        "errors": [],
        "stats": {
            "n_json": n_expect,
            "n_images": n_images,
            "n_images_matched": n_expect,
            "n_shapes": 0,
            "n_rectangle": 0,
            "n_polygon": 0,
            "n_objects_draft": n_obj,
            "n_captions_draft": n_cap,
        },
        "from_cache": True,
        "cache_path": "draft/config+objects+captions",
    }


def _try_resume_without_scan(root, jsons_dirname, images_dirname):
    """
    续跑秒开：validate_log 已通过且目录名一致、draft 齐套时，
    不再 scandir 全量标签/图片做指纹（大数据集可从几十秒降到毫秒级）。
    「重新生成」走 force=True，仍会全量校验。
    """
    log = _read_validate_log(root)
    if log.get("version") != 1:
        return None
    result = log.get("result")
    if not isinstance(result, dict) or not result.get("ok"):
        return None
    old_sig = log.get("signature") or {}
    if old_sig.get("jsons_dirname") != jsons_dirname:
        return None
    if old_sig.get("images_dirname") != images_dirname:
        return None
    geom = (result.get("geometry") or "").strip().lower()
    if geom not in {"rectangle", "polygon", "mixed"}:
        cfg = read_draft_config(root)
        geom = (cfg.get("geometry") or "").strip().lower()
        if geom not in {"rectangle", "polygon", "mixed"}:
            return None
    n_labels = int(old_sig.get("n_labels") or result.get("stats", {}).get("n_json") or 0)
    n_images = int(old_sig.get("n_images") or result.get("stats", {}).get("n_images") or 0)
    n_expect = min(n_labels, n_images) if (n_labels and n_images) else (n_labels or n_images)
    n_obj = _count_json_stems(os.path.join(draft_dir(root), "objects"))
    n_cap = _count_json_stems(os.path.join(draft_dir(root), "captions"))
    if n_expect < 1 or n_obj < n_expect or n_cap < n_expect:
        return None
    img_dir = resolve_images_dir(root, images_dirname)
    json_dir = resolve_jsons_dir(root, jsons_dirname)
    if not os.path.isdir(img_dir) or not os.path.isdir(json_dir):
        return None
    # 选项只做候选目录名探测（早停），避免为秒开再扫万级文件
    options = list_jsons_options(root) if root else []
    img_options = list_images_options(root) if root else []
    cached = _result_from_log(log, options, img_options)
    cached["ok"] = True
    cached["geometry"] = geom
    cached["jsons_dirname"] = jsons_dirname
    cached["images_dirname"] = images_dirname
    cached["from_cache"] = True
    cached["cache_path"] = f"{VALIDATE_LOG_NAME}(skip-scan)"
    stats = dict(cached.get("stats") or {})
    stats["n_json"] = n_expect
    stats["n_images"] = n_images
    stats["n_objects_draft"] = n_obj
    stats["n_captions_draft"] = n_cap
    cached["stats"] = stats
    return cached


#-------------#
# 校验数据集（优先 draft/validate_log.json）
#-------------#
def validate_dataset(root: str, jsons_dirname: str = "jsons",
                     images_dirname: str = "images", force: bool = False) -> dict:
    """
    Returns:
      {ok, geometry, jsons_dirname, images_dirname, errors[], stats,
       jsons_options, from_cache}
    geometry: 'rectangle' | 'polygon' | 'mixed' | None

    force=False：
      1) validate_log 已通过 + draft 齐套 → 秒开（不扫标签指纹）
      2) 签名未变 → 复用
      3) draft 已齐套且 config 有 geometry → 软通过
      4) 否则全量校验并写 log
    """
    jsons_dirname = normalize_jsons_dirname(jsons_dirname)
    images_dirname = normalize_images_dirname(images_dirname)

    if not root or not os.path.isdir(root):
        return {
            "ok": False,
            "geometry": None,
            "jsons_dirname": jsons_dirname,
            "images_dirname": images_dirname,
            "jsons_options": [],
            "images_options": [],
            "errors": [f"目录不存在: {root}"],
            "stats": {},
            "from_cache": False,
        }

    if not force:
        fast = _try_resume_without_scan(root, jsons_dirname, images_dirname)
        if fast is not None:
            return fast

    options = list_jsons_options(root) if root else []
    img_options = list_images_options(root) if root else []

    signature = build_validate_signature(root, jsons_dirname, images_dirname)
    if not force:
        log = _read_validate_log(root)
        old_sig = log.get("signature") or {}
        if (
            log.get("version") == 1
            and old_sig.get("labels_fingerprint") == signature.get("labels_fingerprint")
            and old_sig.get("images_dirname") == signature.get("images_dirname")
            and old_sig.get("jsons_dirname") == signature.get("jsons_dirname")
            and old_sig.get("n_images") == signature.get("n_images")
            and isinstance(log.get("result"), dict)
        ):
            cached = _result_from_log(log, options, img_options)
            # 目录选项随时刷新，其余复用
            cached["jsons_dirname"] = jsons_dirname
            cached["images_dirname"] = images_dirname
            return cached

        soft = _soft_validate_from_draft(
            root, jsons_dirname, images_dirname, signature, options, img_options,
        )
        if soft is not None:
            try:
                _write_validate_log(root, signature, soft)
            except Exception:
                pass
            return soft

    result = _validate_dataset_full(root, jsons_dirname, images_dirname)
    try:
        _write_validate_log(root, signature, result)
    except Exception:
        pass
    result["from_cache"] = False
    return result


def parse_args():
    p = argparse.ArgumentParser(description="校验 grounding 数据集结构")
    p.add_argument("--dataset", required=True)
    p.add_argument("--jsons", default="jsons", help="jsons|jsons-det|jsons-segm|绝对路径")
    p.add_argument("--images", default="images", help="images|JPEGImages|.|绝对路径")
    p.add_argument("--force", action="store_true", help="忽略 draft/validate_log.json 强制全量校验")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = validate_dataset(
        args.dataset, jsons_dirname=args.jsons, images_dirname=args.images,
        force=args.force,
    )
    cache = "cache" if result.get("from_cache") else "full"
    print(
        f"ok={result['ok']} geometry={result['geometry']} mode={cache} "
        f"images={result['images_dirname']} jsons={result['jsons_dirname']} "
        f"stats={result['stats']}"
    )
    for e in result["errors"]:
        print(f"  - {e}")
    sys.exit(0 if result["ok"] else 1)
