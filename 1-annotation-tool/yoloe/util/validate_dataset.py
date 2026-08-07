"""
# @Author: AI产品研发组
# @Date: 2026-08-05
# @Description: 校验数据集 images/+jsons*/ 结构（rectangle / polygon / 二者皆可）
# @Command: python util/validate_dataset.py --dataset /path/to/rm --jsons jsons-det
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from common import (
    IMG_EXTS,
    find_image_path,
    list_images_options,
    list_jsons_options,
    list_label_filenames,
    load_labelme,
    normalize_images_dirname,
    normalize_jsons_dirname,
    resolve_images_dir,
    resolve_jsons_dir,
)


ALLOWED_TYPES = {"rectangle", "polygon"}


#-------------#
# 规范化类型
#-------------#
def normalize_shape_type(raw) -> str:
    t = (raw or "").strip().lower()
    if t in ALLOWED_TYPES:
        return t
    return t


#-------------#
# 校验数据集
#-------------#
def validate_dataset(root: str, jsons_dirname: str = "jsons",
                     images_dirname: str = "images") -> dict:
    """
    Returns:
      {ok, geometry, jsons_dirname, images_dirname, errors[], stats, jsons_options}
    geometry: 'rectangle' | 'polygon' | 'mixed' | None
    """
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
    }


def parse_args():
    p = argparse.ArgumentParser(description="校验 grounding 数据集结构")
    p.add_argument("--dataset", required=True)
    p.add_argument("--jsons", default="jsons", help="jsons|jsons-det|jsons-segm|绝对路径")
    p.add_argument("--images", default="images", help="images|JPEGImages|.|绝对路径")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = validate_dataset(
        args.dataset, jsons_dirname=args.jsons, images_dirname=args.images,
    )
    print(
        f"ok={result['ok']} geometry={result['geometry']} "
        f"images={result['images_dirname']} jsons={result['jsons_dirname']} "
        f"stats={result['stats']}"
    )
    for e in result["errors"]:
        print(f"  - {e}")
    sys.exit(0 if result["ok"] else 1)
