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
    draft_dir,
    ensure_dir,
    find_image_path,
    list_images_options,
    list_jsons_options,
    list_label_filenames,
    load_labelme,
    normalize_images_dirname,
    normalize_jsons_dirname,
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
# 目录签名（仅 listdir + stat，不解析标签）
#-------------#
def build_validate_signature(root: str, jsons_dirname: str, images_dirname: str) -> dict:
    jsons_dirname = normalize_jsons_dirname(jsons_dirname)
    images_dirname = normalize_images_dirname(images_dirname)
    img_dir = resolve_images_dir(root, images_dirname)
    json_dir = resolve_jsons_dir(root, jsons_dirname)

    files = list_label_filenames(json_dir) if os.path.isdir(json_dir) else []
    parts = []
    max_mtime = 0.0
    size_sum = 0
    for fname in files:
        path = os.path.join(json_dir, fname)
        try:
            st = os.stat(path)
            parts.append(f"{fname}:{st.st_size}:{int(st.st_mtime)}")
            max_mtime = max(max_mtime, float(st.st_mtime))
            size_sum += int(st.st_size)
        except OSError:
            parts.append(f"{fname}:?:?")

    n_images = 0
    if os.path.isdir(img_dir):
        try:
            for name in os.listdir(img_dir):
                if Path(name).suffix.lower() in IMG_EXTS and os.path.isfile(
                    os.path.join(img_dir, name)
                ):
                    n_images += 1
        except OSError:
            pass

    fp = hashlib.md5("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()
    return {
        "images_dirname": images_dirname,
        "jsons_dirname": jsons_dirname,
        "n_labels": len(files),
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
        "n_images_matched": 0,
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
    if not os.path.isdir(img_dir):
        hint = f"可选: {', '.join(img_options)}" if img_options else "未发现含图片的目录"
        errors.append(f"缺少图像目录 {img_label}: {img_dir}（{hint}）")
    else:
        try:
            has_img = any(
                os.path.isfile(os.path.join(img_dir, n))
                and Path(n).suffix.lower() in IMG_EXTS
                for n in os.listdir(img_dir)
            )
        except OSError:
            has_img = False
        if not has_img:
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

    seen_types = set()
    for fname in files:
        stats["n_json"] += 1
        path = os.path.join(json_dir, fname)
        stem = Path(fname).stem
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

        if os.path.isdir(img_dir):
            img = find_image_path(img_dir, stem, data.get("imagePath", ""))
            if img:
                stats["n_images_matched"] += 1
            else:
                errors.append(
                    f"{fname}: 图像目录中找不到对应图像 "
                    f"(stem={stem}, dir={img_label})"
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

    force=False：若 draft/validate_log.json 签名未变，直接复用，避免全量读标签。
    """
    jsons_dirname = normalize_jsons_dirname(jsons_dirname)
    images_dirname = normalize_images_dirname(images_dirname)
    options = list_jsons_options(root) if root else []
    img_options = list_images_options(root) if root else []

    if not root or not os.path.isdir(root):
        return {
            "ok": False,
            "geometry": None,
            "jsons_dirname": jsons_dirname,
            "images_dirname": images_dirname,
            "jsons_options": options,
            "images_options": img_options,
            "errors": [f"目录不存在: {root}"],
            "stats": {},
            "from_cache": False,
        }

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
