"""
# @Author: AI产品研发组
# @Date: 2026-08-05
# @Description: 1.5x 扩展裁剪目标，命名附类别，并写出 objects 元数据
# @Command: python -m util.crop_objects --dataset /path/to/rm
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from PIL import Image, ImageDraw
from tqdm import tqdm

from common import (
    draft_dir,
    ensure_dir,
    find_image_path,
    load_labelme,
    match_segs_to_boxes,
    normalize_images_dirname,
    normalize_jsons_dirname,
    parse_yolo_seg_line,
    resolve_images_dir,
    resolve_jsons_dir,
    shape_xyxy,
    write_draft_config,
    write_json,
    xyxy_to_xywh,
)


#-------------#
# 画框
#-------------#
def _draw_box_on_crop(img_crop, x1_orig, y1_orig, x2_orig, y2_orig,
                      crop_x1, crop_y1, box_color=(0, 255, 0), box_width=1):
    if img_crop.mode not in ("RGB", "RGBA"):
        img_crop = img_crop.convert("RGB")
    bx1 = int(x1_orig - crop_x1)
    by1 = int(y1_orig - crop_y1)
    bx2 = int(x2_orig - crop_x1)
    by2 = int(y2_orig - crop_y1)
    cw, ch = img_crop.size
    bx1, by1 = max(0, bx1), max(0, by1)
    bx2, by2 = min(cw - 1, bx2), min(ch - 1, by2)
    if bx2 <= bx1 or by2 <= by1:
        return img_crop
    draw = ImageDraw.Draw(img_crop)
    draw.rectangle([bx1, by1, bx2, by2], outline=box_color, width=max(1, int(box_width)))
    return img_crop


#-------------#
# 读取分割
#-------------#
def load_segs(label_path, img_w, img_h):
    if not label_path or not os.path.isfile(label_path):
        return []
    segs = []
    with open(label_path, encoding="utf-8") as f:
        for line in f:
            parsed = parse_yolo_seg_line(line, img_w, img_h)
            if parsed is None:
                continue
            _, flat, xyxy = parsed
            segs.append({"flat": flat, "xyxy": xyxy})
    return segs


#-------------#
# 选用 shapes（混存时避免双计）
#-------------#
def _select_shapes(shapes, prefer=None):
    """
    有效 shape：有 points 且类型为 rectangle/polygon。
    prefer: 'rectangle' | 'polygon' | None
    混存时按 prefer 取一类；未指定则优先 rectangle。
    """
    rects, polys, others = [], [], []
    for shape in shapes or []:
        pts = shape.get("points") or []
        if not pts:
            continue
        st = (shape.get("shape_type") or "").strip().lower()
        if st == "rectangle":
            rects.append(shape)
        elif st == "polygon":
            polys.append(shape)
        else:
            others.append(shape)
    prefer = (prefer or "").strip().lower()
    if prefer == "polygon":
        return polys or rects or others
    if prefer == "rectangle":
        return rects or polys or others
    if rects and polys:
        return rects
    if rects:
        return rects
    if polys:
        return polys
    return others


#-------------#
# 裁剪一张图
#-------------#
def crop_one_image(dataset_root, json_path, expand_ratio=1.5, draw_box=True,
                   prefer_geometry=None, images_dirname="images"):
    data = load_labelme(json_path)
    stem = Path(json_path).stem
    img_dir = resolve_images_dir(dataset_root, images_dirname)
    img_path = find_image_path(img_dir, stem, data.get("imagePath", ""))
    if not img_path:
        return None

    img = Image.open(img_path)
    img_w, img_h = img.size
    shapes = _select_shapes(data.get("shapes", []), prefer=prefer_geometry)
    if not shapes:
        return None

    boxes = [shape_xyxy(s["points"]) for s in shapes]

    label_path = os.path.join(dataset_root, "labels", f"{stem}.txt")
    segs = load_segs(label_path, img_w, img_h)
    aligned_segs = match_segs_to_boxes(boxes, segs)

    crops_dir = ensure_dir(os.path.join(draft_dir(dataset_root), "crops"))
    objects = []
    for idx, shape in enumerate(shapes):
        label = shape.get("label", "unknown")
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
        x1_orig, y1_orig, x2_orig, y2_orig = boxes[idx]
        shape_type = (shape.get("shape_type") or "").strip().lower() or "rectangle"
        pts = shape.get("points") or []
        poly_flat = None
        if shape_type == "polygon" and len(pts) >= 3:
            poly_flat = []
            for p in pts:
                poly_flat.extend([float(p[0]), float(p[1])])
        # 优先 YOLO seg；多边形标注则用自身 points
        seg_flat = aligned_segs[idx]
        if poly_flat and (not seg_flat or shape_type == "polygon"):
            seg_flat = poly_flat

        cx = (x1_orig + x2_orig) / 2
        cy = (y1_orig + y2_orig) / 2
        ew = max(1.0, (x2_orig - x1_orig) * expand_ratio)
        eh = max(1.0, (y2_orig - y1_orig) * expand_ratio)
        x1 = max(0, int(cx - ew / 2))
        y1 = max(0, int(cy - eh / 2))
        x2 = min(img_w, int(cx + ew / 2))
        y2 = min(img_h, int(cy + eh / 2))
        if x2 <= x1 or y2 <= y1:
            continue

        crop_name = f"{stem}_obj{idx:04d}_{safe_label}.jpg"
        crop_path = os.path.join(crops_dir, crop_name)
        img_crop = img.crop([x1, y1, x2, y2])
        if draw_box:
            img_crop = _draw_box_on_crop(
                img_crop, x1_orig, y1_orig, x2_orig, y2_orig, x1, y1
            )
        # JPEG 不支持 RGBA/P/LA 等模式
        if img_crop.mode != "RGB":
            img_crop = img_crop.convert("RGB")
        img_crop.save(crop_path, quality=95)

        objects.append({
            "obj_id": idx,
            "label": label,
            "shape_type": shape_type,
            "points": pts,
            "bbox_xyxy": [x1_orig, y1_orig, x2_orig, y2_orig],
            "bbox_xywh": xyxy_to_xywh(x1_orig, y1_orig, x2_orig, y2_orig),
            "polygon": poly_flat,
            "segmentation": seg_flat,
            "crop_path": os.path.relpath(crop_path, dataset_root),
            "crop_box": [x1, y1, x2, y2],
        })

    meta = {
        "stem": stem,
        "image": os.path.basename(img_path),
        "image_path": os.path.relpath(img_path, dataset_root),
        "width": img_w,
        "height": img_h,
        "objects": objects,
    }
    write_json(os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json"), meta)
    return meta


#-------------#
# 写一条 jsonl
#-------------#
def _jsonl_row(meta, obj):
    return json.dumps({
        "image": meta["image"],
        "stem": meta["stem"],
        "obj_id": obj["obj_id"],
        "label": obj["label"],
        "bbox": obj["bbox_xyxy"],
        "bbox_xywh": obj["bbox_xywh"],
        "seg": obj.get("segmentation"),
        "crop_path": obj["crop_path"],
    }, ensure_ascii=False)


#-------------#
# 重建 jsonl
#-------------#
def _rewrite_objects_jsonl(dataset_root, stems_order=None):
    """按 objects/*.json 重建 objects.jsonl（续跑时合并旧+新）。"""
    obj_dir = os.path.join(draft_dir(dataset_root), "objects")
    jsonl_path = os.path.join(draft_dir(dataset_root), "objects.jsonl")
    if stems_order is None:
        stems = sorted(Path(p).stem for p in Path(obj_dir).glob("*.json"))
    else:
        stems = list(stems_order)
    n_obj = 0
    with open(jsonl_path, "w", encoding="utf-8") as fout:
        for stem in stems:
            path = os.path.join(obj_dir, f"{stem}.json")
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                meta = json.load(f)
            for obj in meta.get("objects") or []:
                fout.write(_jsonl_row(meta, obj) + "\n")
                n_obj += 1
    return n_obj


#-------------#
# 批量裁剪
#-------------#
def crop_dataset(dataset_root, expand_ratio=1.5, draw_box=True, limit=None,
                 force=False, jsons_dirname="jsons", images_dirname="images",
                 progress_cb=None, prefer_geometry=None):
    """
    force=False 时跳过已有 draft/objects/{stem}.json 的图，并合并重建 objects.jsonl。
    jsons_dirname / images_dirname: 相对名、'.' 或绝对路径
    prefer_geometry: rectangle|polygon，混存时按属性筛选
    progress_cb: optional callable(done, total, detail)
    """
    from common import detect_geometry
    jsons_dirname = normalize_jsons_dirname(jsons_dirname)
    images_dirname = normalize_images_dirname(images_dirname)
    json_dir = resolve_jsons_dir(dataset_root, jsons_dirname)
    img_dir = resolve_images_dir(dataset_root, images_dirname)
    assert os.path.isdir(json_dir), f"缺少标签目录: {json_dir}"
    assert os.path.isdir(img_dir), f"缺少图像目录: {img_dir}"
    from common import list_label_filenames
    files = list_label_filenames(json_dir)
    if limit:
        files = files[:limit]

    if not prefer_geometry:
        g = detect_geometry(json_dir)
        prefer_geometry = g.get("geometry") if g.get("geometry") != "mixed" else "rectangle"

    ensure_dir(os.path.join(draft_dir(dataset_root), "crops"))
    obj_dir = ensure_dir(os.path.join(draft_dir(dataset_root), "objects"))

    total = len(files)
    if progress_cb:
        progress_cb(0, max(total, 1), f"0/{total}")

    n_new, n_skip = 0, 0
    for i, fname in enumerate(tqdm(files, desc="crop"), start=1):
        stem = Path(fname).stem
        obj_path = os.path.join(obj_dir, f"{stem}.json")
        if not force and os.path.isfile(obj_path):
            n_skip += 1
            if progress_cb:
                progress_cb(i, total, f"{i}/{total}")
            continue
        meta = crop_one_image(
            dataset_root, os.path.join(json_dir, fname),
            expand_ratio=expand_ratio, draw_box=draw_box,
            prefer_geometry=prefer_geometry,
            images_dirname=images_dirname,
        )
        if meta:
            n_new += len(meta["objects"])
        if progress_cb:
            progress_cb(i, total, f"{i}/{total}")

    stems_order = [Path(f).stem for f in files]
    existing = {Path(p).stem for p in Path(obj_dir).glob("*.json")}
    for s in sorted(existing):
        if s not in stems_order:
            stems_order.append(s)
    n_obj = _rewrite_objects_jsonl(dataset_root, stems_order)
    write_draft_config(dataset_root, {
        "jsons_dirname": jsons_dirname,
        "images_dirname": images_dirname,
        "geometry": prefer_geometry,
        "jsons_path": json_dir,
        "images_path": img_dir,
    })
    print(
        f"裁剪完成: 新处理 {len(files) - n_skip}/{len(files)} 图"
        f"（跳过 {n_skip}）, 共 {n_obj} 目标 → {draft_dir(dataset_root)}"
        f" [images={img_dir} jsons={json_dir} geom={prefer_geometry}]"
    )
    if progress_cb and total:
        progress_cb(total, total, f"{total}/{total}")
    return n_obj


def parse_args():
    p = argparse.ArgumentParser(description="裁剪 grounding 目标")
    p.add_argument("--dataset", required=True, help="数据集根目录")
    p.add_argument("--expand_ratio", type=float, default=1.5)
    p.add_argument("--no_box", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true", help="强制重裁所有图")
    p.add_argument("--jsons", default="jsons", help="jsons|jsons-det|jsons-segm|绝对路径")
    p.add_argument("--images", default="images", help="images|JPEGImages|.|绝对路径")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    crop_dataset(
        args.dataset,
        expand_ratio=args.expand_ratio,
        draw_box=not args.no_box,
        limit=args.limit,
        force=args.force,
        jsons_dirname=args.jsons,
        images_dirname=args.images,
    )
