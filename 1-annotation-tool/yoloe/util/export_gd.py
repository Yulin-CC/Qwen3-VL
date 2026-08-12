"""
# @Author: AI产品研发组
# @Date: 2026-08-05
# @Description: 将 draft captions/objects 导出为 Flickr 风格 jsons-GD
# @Command: python util/export_gd.py --dataset /path/to/rm
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from tqdm import tqdm

from common import assign_phrase_token_spans, draft_dir, ensure_dir, write_json


def poly_area(flat):
    if not flat or len(flat) < 6:
        return 0.0
    xs = flat[0::2]
    ys = flat[1::2]
    area = 0.0
    n = len(xs)
    for i in range(n):
        j = (i + 1) % n
        area += xs[i] * ys[j] - xs[j] * ys[i]
    return abs(area) / 2.0


def build_gd_for_stem(dataset_root, stem, dataset_name="drone"):
    obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    cap_path = os.path.join(draft_dir(dataset_root), "captions", f"{stem}.json")
    if not os.path.isfile(obj_path) or not os.path.isfile(cap_path):
        return None

    with open(obj_path, encoding="utf-8") as f:
        meta = json.load(f)
    with open(cap_path, encoding="utf-8") as f:
        caps = json.load(f)

    id2obj = {o["obj_id"]: o for o in meta["objects"]}
    images = []
    annotations = []
    ann_id = 0

    for sent in caps.get("captions", []):
        caption = sent["caption"]
        image_id = sent.get("sentence_id", len(images))
        # 统一非重叠分配，避免短串误标在更长短语内部
        phrases = sent.get("phrases") or []
        spans = assign_phrase_token_spans(caption, phrases)
        tokens_positive_eval = []
        for ph, span in zip(phrases, spans):
            ph["tokens_positive"] = span
            if span:
                tokens_positive_eval.append([span])

        images.append({
            "file_name": meta["image"],
            "height": str(meta["height"]),
            "width": str(meta["width"]),
            "id": image_id,
            "caption": caption,
            "dataset_name": dataset_name,
            "tokens_negative": [[0, len(caption)]],
            "sentence_id": image_id,
            "original_img_id": stem,
            "tokens_positive_eval": tokens_positive_eval,
        })

        for ph in sent.get("phrases", []):
            span = ph.get("tokens_positive")
            if not span:
                continue
            obj = id2obj.get(ph["obj_id"])
            if not obj:
                continue
            seg = obj.get("segmentation")
            segmentation = [seg] if seg else []
            bbox = obj["bbox_xywh"]
            area = poly_area(seg) if seg else float(bbox[2] * bbox[3])
            annotations.append({
                "area": float(area),
                "iscrowd": 0,
                "image_id": image_id,
                "category_id": 1,
                "id": ann_id,
                "bbox": [float(v) for v in bbox],
                "tokens_positive": [span],
                "segmentation": segmentation,
            })
            ann_id += 1

    return {
        "info": [],
        "categories": [{"supercategory": "object", "id": 1, "name": "object"}],
        "images": images,
        "annotations": annotations,
    }


def export_stem(dataset_root, stem, out_dir=None, dataset_name="drone"):
    gd = build_gd_for_stem(dataset_root, stem, dataset_name=dataset_name)
    if gd is None:
        return None
    out_dir = out_dir or os.path.join(dataset_root, "jsons-GD")
    ensure_dir(out_dir)
    out_path = os.path.join(out_dir, f"{stem}.json")
    write_json(out_path, gd)
    return out_path


def export_dataset(dataset_root, limit=None, dataset_name="drone"):
    cap_dir = os.path.join(draft_dir(dataset_root), "captions")
    if not os.path.isdir(cap_dir):
        print(f"导出跳过: 无 captions 目录 {cap_dir}")
        return 0
    stems = sorted(Path(p).stem for p in Path(cap_dir).glob("*.json"))
    if limit:
        stems = stems[:limit]
    out_dir = ensure_dir(os.path.join(dataset_root, "jsons-GD"))
    n = 0
    for stem in tqdm(stems, desc="export-gd"):
        if export_stem(dataset_root, stem, out_dir=out_dir, dataset_name=dataset_name):
            n += 1
    print(f"导出完成: {n} → {out_dir}")
    return n


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dataset_name", default="drone")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    export_dataset(args.dataset, limit=args.limit, dataset_name=args.dataset_name)
