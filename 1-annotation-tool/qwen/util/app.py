import os
import json
import glob
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory

app = Flask(__name__)

SUPPORTED_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tiff'}

config = {
    "images_dir": "",
    "annotations_dir": "",
}


# ── helpers ──────────────────────────────────────────────

def get_image_list():
    d = config["images_dir"]
    if not d or not os.path.isdir(d):
        return []
    return sorted(
        f for f in os.listdir(d)
        if Path(f).suffix.lower() in SUPPORTED_EXTS
    )


def annotation_path(image_name: str) -> str:
    return os.path.join(config["annotations_dir"], Path(image_name).stem + ".json")


# ── page ─────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── directory browser ─────────────────────────────────────

@app.route("/api/browse")
def browse():
    """
    List subdirectories (and optionally files) under a given path.
    ?path=/some/dir   — target directory (default: filesystem root or HOME)
    ?show_files=1     — also include image files in listing
    """
    req_path = request.args.get("path", "").strip() or os.path.expanduser("~")
    req_path = os.path.realpath(req_path)

    if not os.path.isdir(req_path):
        return jsonify({"error": f"不是有效目录: {req_path}"}), 400

    show_files = request.args.get("show_files", "0") == "1"

    entries = []
    try:
        for name in sorted(os.listdir(req_path)):
            full = os.path.join(req_path, name)
            if os.path.isdir(full):
                entries.append({"name": name, "type": "dir", "path": full})
            elif show_files and Path(name).suffix.lower() in SUPPORTED_EXTS:
                entries.append({"name": name, "type": "file", "path": full})
    except PermissionError:
        return jsonify({"error": "无读取权限"}), 403

    parent = str(Path(req_path).parent) if req_path != "/" else None
    return jsonify({
        "current": req_path,
        "parent": parent,
        "entries": entries,
    })


# ── config ────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(config)


@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.json or {}
    images_dir      = data.get("images_dir", "").strip()
    annotations_dir = data.get("annotations_dir", "").strip()

    if images_dir and not os.path.isdir(images_dir):
        return jsonify({"error": f"图像目录不存在: {images_dir}"}), 400
    if annotations_dir:
        try:
            os.makedirs(annotations_dir, exist_ok=True)
        except Exception as e:
            return jsonify({"error": f"无法创建标注目录: {e}"}), 400

    config["images_dir"]      = images_dir
    config["annotations_dir"] = annotations_dir
    return jsonify({"ok": True, "config": config})


# ── image list & stats ────────────────────────────────────

@app.route("/api/images")
def list_images():
    result = []
    for name in get_image_list():
        ann_file  = annotation_path(name)
        annotated = os.path.isfile(ann_file)
        qa_count  = 0
        if annotated:
            try:
                with open(ann_file, encoding="utf-8") as f:
                    d = json.load(f)
                qa_count = len(d) if isinstance(d, list) else 0
            except Exception:
                pass
        result.append({"name": name, "annotated": annotated, "qa_count": qa_count})
    return jsonify(result)


@app.route("/api/stats")
def stats():
    images = get_image_list()
    total  = len(images)
    done   = sum(1 for n in images if os.path.isfile(annotation_path(n)))
    return jsonify({"total": total, "done": done, "remaining": total - done})


# ── serve image ───────────────────────────────────────────

@app.route("/api/image/<path:filename>")
def serve_image(filename):
    img_dir = config["images_dir"]
    if not img_dir:
        return jsonify({"error": "未配置图像目录"}), 400
    full = os.path.join(img_dir, filename)
    if not os.path.isfile(full):
        return jsonify({"error": "文件不存在"}), 404
    return send_from_directory(img_dir, filename)


# ── annotation CRUD ───────────────────────────────────────

@app.route("/api/annotation/<path:image_name>", methods=["GET"])
def get_annotation(image_name):
    if not config["annotations_dir"]:
        return jsonify([])
    p = annotation_path(image_name)
    if not os.path.isfile(p):
        return jsonify([])
    with open(p, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/annotation/<path:image_name>", methods=["POST"])
def save_annotation(image_name):
    if not config["annotations_dir"]:
        return jsonify({"error": "未配置标注目录"}), 400

    data = request.json
    if not isinstance(data, list):
        return jsonify({"error": "数据格式错误，应为数组"}), 400

    normalized = []
    img_rel = f"images/{image_name}"
    for idx, item in enumerate(data):
        convs = item.get("conversations", [])
        if not convs:
            continue
        normalized.append({"id": idx + 1, "image": img_rel, "conversations": convs})

    p = annotation_path(image_name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True, "saved": len(normalized), "path": p})


@app.route("/api/annotation/<path:image_name>", methods=["DELETE"])
def delete_annotation(image_name):
    p = annotation_path(image_name)
    if os.path.isfile(p):
        os.remove(p)
    return jsonify({"ok": True})


# ── export all → train.jsonl ──────────────────────────────

@app.route("/api/export", methods=["POST"])
def export_jsonl():
    ann_dir = config["annotations_dir"]
    if not ann_dir or not os.path.isdir(ann_dir):
        return jsonify({"error": "标注目录未设置或不存在"}), 400

    all_records = []
    for jf in sorted(glob.glob(os.path.join(ann_dir, "*.json"))):
        try:
            with open(jf, encoding="utf-8") as f:
                records = json.load(f)
            if isinstance(records, list):
                all_records.extend(records)
        except Exception:
            pass

    for i, rec in enumerate(all_records):
        rec["id"] = i + 1

    out_path = os.path.join(ann_dir, "train.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return jsonify({"ok": True, "records": len(all_records), "path": out_path})


# ── main ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="图像标注平台")
    parser.add_argument("--port", type=int, default=7860, help="监听端口 (默认 7860)")
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    print(f"\n  图像标注平台已启动 → http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=False)
