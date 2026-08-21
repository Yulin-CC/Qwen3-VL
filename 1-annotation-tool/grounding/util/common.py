"""
# @Author: AI产品研发组
# @Date: 2026-08-05
# @Description: YOLOE grounding 公共工具（路径、bbox、分割对齐）
"""

import json
import os
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path


IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
# 源标签文件：LabelMe JSON 或 Pascal VOC XML（bbox）
LABEL_EXTS = {".json", ".xml"}

# 可选标签目录（jsons-sem→jsons-segm；jsons-det→jsons-detect；annotations/xmls 多为 VOC）
JSONS_CANDIDATES = (
    "jsons-segm", "jsons-sem",
    "jsons-detect", "jsons-det",
    "jsons",
    "annotations", "xmls", "voc",
)

JSONS_AUTO_PRIORITY = (
    ("jsons-segm", "polygon"),
    ("jsons-sem", "polygon"),
    ("jsons-detect", "rectangle"),
    ("jsons-det", "rectangle"),
    ("jsons", None),
)

# 常见图像目录名（选中此类文件夹时，父目录作为 dataset_root）
IMAGES_CANDIDATES = (
    "images", "image", "imgs", "img",
    "JPEGImages", "jpegimages", "JPG", "jpg", "PNG", "png",
    "pictures", "photos", "pic", "photo",
)


def is_label_filename(name: str) -> bool:
    return Path(name).suffix.lower() in LABEL_EXTS


def list_label_filenames(label_dir: str) -> list:
    if not label_dir or not os.path.isdir(label_dir):
        return []
    try:
        return sorted(f for f in os.listdir(label_dir) if is_label_filename(f))
    except OSError:
        return []


def draft_dir(dataset_root: str) -> str:
    return os.path.join(dataset_root, "draft")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def draft_config_path(dataset_root: str) -> str:
    return os.path.join(draft_dir(dataset_root), "config.json")


def read_draft_config(dataset_root: str) -> dict:
    path = draft_config_path(dataset_root)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_draft_config(dataset_root: str, data: dict):
    path = draft_config_path(dataset_root)
    ensure_dir(os.path.dirname(path))
    cur = read_draft_config(dataset_root)
    cur.update(data or {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)


def normalize_jsons_dirname(name: str) -> str:
    """相对目录名规范化；绝对路径原样返回。"""
    n = (name or "jsons").strip()
    if os.path.isabs(n):
        return n.rstrip("/") or n
    n = n.strip("/")
    if n == "jsons-sem":
        return "jsons-segm"
    if n == "jsons-det":
        return "jsons-detect"
    if n in JSONS_CANDIDATES or n == "jsons-segm":
        return n
    return n or "jsons"


def list_jsons_options(dataset_root: str) -> list:
    """返回数据集根下存在的标签目录名（优先顺序）。"""
    if not dataset_root or not os.path.isdir(dataset_root):
        return []
    found = []
    seen = set()
    for name in JSONS_CANDIDATES:
        path = os.path.join(dataset_root, name)
        if not os.path.isdir(path):
            continue
        key = normalize_jsons_dirname(name)
        display = name if name == "jsons-sem" and not os.path.isdir(
            os.path.join(dataset_root, "jsons-segm")
        ) else key
        if display in seen:
            continue
        if dir_has_label_jsons(path):
            found.append(display)
            seen.add(display)
    return found


def resolve_jsons_dir(dataset_root: str, jsons_dirname: str = "jsons") -> str:
    """
    解析标签目录绝对路径。
    jsons_dirname 可为相对名（jsons/jsons-det/…）或绝对路径。
    """
    raw = (jsons_dirname or "jsons").strip()
    if os.path.isabs(raw) and os.path.isdir(raw):
        return os.path.realpath(raw)
    name = normalize_jsons_dirname(raw)
    if os.path.isabs(name) and os.path.isdir(name):
        return os.path.realpath(name)
    cand = os.path.join(dataset_root, name)
    if os.path.isdir(cand):
        return os.path.realpath(cand)
    if name == "jsons-segm":
        alt = os.path.join(dataset_root, "jsons-sem")
        if os.path.isdir(alt):
            return os.path.realpath(alt)
    if name == "jsons-detect":
        alt = os.path.join(dataset_root, "jsons-det")
        if os.path.isdir(alt):
            return os.path.realpath(alt)
    return cand


def geometry_for_jsons_dirname(jsons_dirname: str):
    """segm→polygon，detect→rectangle，jsons→None（再探测）。"""
    name = normalize_jsons_dirname(jsons_dirname)
    if os.path.isabs(name):
        name = os.path.basename(name.rstrip("/"))
    if name in {"jsons-segm", "jsons-sem"}:
        return "polygon"
    if name in {"jsons-detect", "jsons-det"}:
        return "rectangle"
    return None


def detect_dataset_layout(dataset_root, images_dirname=None, jsons_dirname=None) -> dict:
    """读取并校验 images/ + (jsons-segm | jsons-detect | jsons)。未指定标签目录时按优先级自动选。"""
    root = os.path.realpath(dataset_root or "")
    if not root or not os.path.isdir(root):
        return {
            "ok": False,
            "error": f"数据集根目录不存在: {dataset_root}",
            "images_dirname": None,
            "jsons_dirname": None,
            "geometry": None,
            "images_dir": None,
            "jsons_dir": None,
            "n_images": 0,
            "n_jsons": 0,
            "n_paired": 0,
        }

    if images_dirname:
        img_dir = resolve_images_dir(root, images_dirname)
        img_name = normalize_images_dirname(images_dirname)
    else:
        img_dir = resolve_images_dir(root, "images")
        img_name = "images"
        if not os.path.isdir(img_dir) or not dir_has_images(img_dir):
            _, nested, nested_name = resolve_images_root(root, deep=False)
            if nested:
                img_dir, img_name = nested, nested_name

    if not os.path.isdir(img_dir) or not dir_has_images(img_dir):
        return {
            "ok": False,
            "error": f"未找到图像目录 images/（或等价目录）: {root}",
            "images_dirname": img_name,
            "jsons_dirname": None,
            "geometry": None,
            "images_dir": img_dir,
            "jsons_dir": None,
            "n_images": 0,
            "n_jsons": 0,
            "n_paired": 0,
        }

    picked_name = None
    json_dir = None
    if jsons_dirname:
        picked_name = normalize_jsons_dirname(jsons_dirname)
        json_dir = resolve_jsons_dir(root, jsons_dirname)
        if not os.path.isdir(json_dir) or not dir_has_label_jsons(json_dir):
            return {
                "ok": False,
                "error": f"指定标签目录无效: {jsons_dirname} → {json_dir}",
                "images_dirname": img_name,
                "jsons_dirname": picked_name,
                "geometry": geometry_for_jsons_dirname(picked_name),
                "images_dir": img_dir,
                "jsons_dir": json_dir,
                "n_images": len(list_image_stems(img_dir)),
                "n_jsons": 0,
                "n_paired": 0,
            }
    else:
        for name, _geom in JSONS_AUTO_PRIORITY:
            cand = os.path.join(root, name)
            if os.path.isdir(cand) and dir_has_label_jsons(cand):
                picked_name = normalize_jsons_dirname(name)
                json_dir = os.path.realpath(cand)
                break
        if not picked_name:
            found = list_jsons_options(root)
            return {
                "ok": False,
                "error": (
                    "未找到标签目录。需要 images/ + jsons-segm 或 jsons-detect 或 jsons"
                    + (f"（发现: {found}）" if found else "")
                ),
                "images_dirname": img_name,
                "jsons_dirname": None,
                "geometry": None,
                "images_dir": img_dir,
                "jsons_dir": None,
                "n_images": len(list_image_stems(img_dir)),
                "n_jsons": 0,
                "n_paired": 0,
            }

    img_stems = list_image_stems(img_dir)
    json_files = list_label_filenames(json_dir)
    json_stems = {Path(f).stem for f in json_files}
    paired = img_stems & json_stems
    geom = geometry_for_jsons_dirname(picked_name)
    return {
        "ok": True,
        "error": None,
        "images_dirname": img_name,
        "jsons_dirname": picked_name,
        "geometry": geom,
        "images_dir": os.path.realpath(img_dir),
        "jsons_dir": os.path.realpath(json_dir),
        "n_images": len(img_stems),
        "n_jsons": len(json_files),
        "n_paired": len(paired),
        "n_img_only": len(img_stems - json_stems),
        "n_json_only": len(json_stems - img_stems),
    }


def dir_has_images(path: str, max_check: int = 400) -> bool:
    """是否含图片。scandir + 早停，避免大目录 os.listdir 卡死。"""
    if not path or not os.path.isdir(path):
        return False
    try:
        n = 0
        with os.scandir(path) as it:
            for ent in it:
                if not ent.is_file(follow_symlinks=False):
                    continue
                n += 1
                if Path(ent.name).suffix.lower() in IMG_EXTS:
                    return True
                if n >= max_check:
                    return False
    except OSError:
        return False
    return False


def dir_has_label_jsons(path: str, max_check: int = 400) -> bool:
    """目录内是否有 LabelMe .json 或 VOC .xml 标签。scandir + 早停。"""
    if not path or not os.path.isdir(path):
        return False
    try:
        n = 0
        with os.scandir(path) as it:
            for ent in it:
                if not ent.is_file(follow_symlinks=False):
                    continue
                n += 1
                if is_label_filename(ent.name):
                    return True
                if n >= max_check:
                    return False
    except OSError:
        return False
    return False


def normalize_images_dirname(name: str) -> str:
    """相对目录名规范化；绝对路径原样；'.' 表示图像就在 dataset_root 下。"""
    n = (name or "images").strip()
    if os.path.isabs(n):
        return n.rstrip("/\\") or n
    n = n.strip("/\\")
    if n in {".", ""}:
        return "."
    return n or "images"


def list_images_options(dataset_root: str) -> list:
    """返回数据集根下存在的常见图像目录名。"""
    if not dataset_root or not os.path.isdir(dataset_root):
        return []
    found = []
    seen = set()
    # 根目录自身有图
    if dir_has_images(dataset_root):
        found.append(".")
        seen.add(".")
    for name in IMAGES_CANDIDATES:
        path = os.path.join(dataset_root, name)
        if not os.path.isdir(path) or not dir_has_images(path):
            continue
        key = name  # 保留原大小写（JPEGImages）
        low = key.lower()
        if low in seen:
            continue
        found.append(key)
        seen.add(low)
    # 其它含图的一级子目录
    try:
        for name in sorted(os.listdir(dataset_root)):
            if name.startswith("."):
                continue
            path = os.path.join(dataset_root, name)
            if not os.path.isdir(path) or not dir_has_images(path):
                continue
            low = name.lower()
            if low in seen:
                continue
            found.append(name)
            seen.add(low)
    except OSError:
        pass
    return found


def resolve_images_dir(dataset_root: str, images_dirname: str = "images") -> str:
    """
    解析图像目录绝对路径。
    images_dirname 可为相对名（images/JPEGImages/…）、'.'（根目录即图像）或绝对路径。
    """
    raw = (images_dirname or "images").strip()
    if os.path.isabs(raw) and os.path.isdir(raw):
        return os.path.realpath(raw)
    name = normalize_images_dirname(raw)
    if os.path.isabs(name) and os.path.isdir(name):
        return os.path.realpath(name)
    if name == ".":
        return os.path.realpath(dataset_root)
    cand = os.path.join(dataset_root, name)
    if os.path.isdir(cand):
        return os.path.realpath(cand)
    # 大小写不敏感回退（Windows 外也尽量找常见名）
    low = name.lower()
    try:
        for child in os.listdir(dataset_root):
            if child.lower() == low and os.path.isdir(os.path.join(dataset_root, child)):
                return os.path.realpath(os.path.join(dataset_root, child))
    except OSError:
        pass
    return cand


def resolve_images_root(path: str, deep: bool = True):
    """
    从用户选择的路径解析 (dataset_root, images_dir, images_dirname)。
    - 选中含 images/（或其它常见图像子目录）的根 → (root, root/<dir>, <dir>)
    - 选中常见图像文件夹本身 → (parent, that_dir, basename)
    - 选中直接放图的普通目录 → (path, path, '.')
    deep=False：不扫「任意名」一级子目录（浏览导航时更快）。
    """
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        return None, None, None

    # 1) 优先：根下常见图像子目录（只探测已知名，不 listdir 全量子目录）
    for name in IMAGES_CANDIDATES:
        nested = os.path.join(path, name)
        if os.path.isdir(nested) and dir_has_images(nested):
            return path, nested, name

    # 2) 当前目录本身有图
    if dir_has_images(path):
        base = os.path.basename(path)
        parent = str(Path(path).parent)
        if base.lower() in {x.lower() for x in IMAGES_CANDIDATES}:
            return parent, path, base
        return path, path, "."

    # 3) 其它含图的一级子目录（任意名，如 train_imgs）——浏览时跳过
    if deep:
        try:
            checked = 0
            with os.scandir(path) as it:
                for ent in it:
                    if not ent.is_dir(follow_symlinks=False):
                        continue
                    if ent.name.startswith("."):
                        continue
                    checked += 1
                    if checked > 24:
                        break
                    if dir_has_images(ent.path):
                        return path, ent.path, ent.name
        except OSError:
            pass

    return None, None, None


def detect_geometry(json_dir: str, sample_limit: int = 80) -> dict:
    """
    扫描标签目录，返回 geometry: rectangle|polygon|mixed|None 及计数。
    """
    stats = {"n_json": 0, "n_xml": 0, "n_rectangle": 0, "n_polygon": 0, "n_shapes": 0}
    if not dir_has_label_jsons(json_dir):
        return {"ok": False, "geometry": None, "stats": stats, "error": "无 json/xml 标签"}
    files = list_label_filenames(json_dir)
    seen = set()
    for fname in files[: max(1, sample_limit)]:
        ext = Path(fname).suffix.lower()
        if ext == ".xml":
            stats["n_xml"] += 1
        else:
            stats["n_json"] += 1
        try:
            data = load_labelme(os.path.join(json_dir, fname))
        except Exception:
            continue
        for shape in data.get("shapes") or []:
            pts = shape.get("points") or []
            if not pts:
                continue
            st = (shape.get("shape_type") or "").strip().lower()
            if st not in {"rectangle", "polygon"}:
                continue
            seen.add(st)
            stats["n_shapes"] += 1
            if st == "rectangle":
                stats["n_rectangle"] += 1
            else:
                stats["n_polygon"] += 1
    if len(seen) > 1:
        geom = "mixed"
    elif seen:
        geom = next(iter(seen))
    else:
        geom = None
    return {
        "ok": geom is not None,
        "geometry": geom,
        "stats": stats,
        "error": None if geom else "无有效 rectangle/polygon",
    }


def shape_xyxy(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))


def xyxy_to_xywh(x1, y1, x2, y2):
    return [float(x1), float(y1), float(x2 - x1), float(y2 - y1)]


def bbox_center(bbox_xyxy):
    x1, y1, x2, y2 = bbox_xyxy
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def bbox_iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def parse_yolo_seg_line(line, img_w, img_h):
    """YOLO seg: class x1 y1 x2 y2 ... (normalized) → (cls_id, flat_abs_xy, xyxy)."""
    parts = line.strip().split()
    if len(parts) < 7:
        return None
    cls_id = int(float(parts[0]))
    coords = [float(v) for v in parts[1:]]
    if len(coords) % 2 != 0:
        return None
    xs, ys = [], []
    flat = []
    for i in range(0, len(coords), 2):
        x = coords[i] * img_w
        y = coords[i + 1] * img_h
        xs.append(x)
        ys.append(y)
        flat.extend([x, y])
    xyxy = (min(xs), min(ys), max(xs), max(ys))
    return cls_id, flat, xyxy


def load_voc_xml(xml_path: str) -> dict:
    """
    Pascal VOC XML → LabelMe 兼容结构（仅 bbox → rectangle）。
    参考: <annotation><filename/><object><name/><bndbox/></object>...
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    filename = (root.findtext("filename") or "").strip()
    shapes = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "unknown").strip() or "unknown"
        bb = obj.find("bndbox")
        if bb is None:
            continue
        try:
            xmin = float(bb.findtext("xmin"))
            ymin = float(bb.findtext("ymin"))
            xmax = float(bb.findtext("xmax"))
            ymax = float(bb.findtext("ymax"))
        except (TypeError, ValueError):
            continue
        if xmax <= xmin or ymax <= ymin:
            continue
        shapes.append({
            "label": name,
            "shape_type": "rectangle",
            "points": [[xmin, ymin], [xmax, ymax]],
        })
    return {
        "version": "voc-xml",
        "flags": {},
        "imagePath": filename,
        "shapes": shapes,
    }


def load_labelme(path: str) -> dict:
    """加载 LabelMe .json 或 VOC .xml，统一返回含 shapes 的 dict。"""
    if Path(path).suffix.lower() == ".xml":
        return load_voc_xml(path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_image_path(img_dir, stem_or_name, image_path_hint=""):
    if image_path_hint:
        cand = os.path.join(img_dir, os.path.basename(image_path_hint))
        if os.path.isfile(cand):
            return cand
    stem = Path(stem_or_name).stem
    for ext in IMG_EXTS:
        cand = os.path.join(img_dir, stem + ext)
        if os.path.isfile(cand):
            return cand
        cand = os.path.join(img_dir, stem + ext.upper())
        if os.path.isfile(cand):
            return cand
    return None


def list_image_stems(img_dir: str) -> set:
    """图像目录下所有图片 stem（一次 scandir，供以图为准过滤标签）。"""
    out = set()
    if not img_dir or not os.path.isdir(img_dir):
        return out
    try:
        with os.scandir(img_dir) as it:
            for ent in it:
                if not ent.is_file(follow_symlinks=False):
                    continue
                if Path(ent.name).suffix.lower() in IMG_EXTS:
                    out.add(Path(ent.name).stem)
    except OSError:
        return set()
    return out


def match_segs_to_boxes(boxes_xyxy, segs):
    """
    Greedy IoU match: list of seg dicts {flat, xyxy} → list aligned to boxes (or None).
    """
    used = set()
    aligned = []
    for box in boxes_xyxy:
        best_i, best_iou = -1, 0.0
        for i, seg in enumerate(segs):
            if i in used:
                continue
            iou = bbox_iou(box, seg["xyxy"])
            if iou > best_iou:
                best_iou, best_i = iou, i
        if best_i >= 0 and best_iou >= 0.1:
            used.add(best_i)
            aligned.append(segs[best_i]["flat"])
        else:
            aligned.append(None)
    return aligned


def load_objects_for_image(dataset_root, stem):
    """Load objects from draft/objects/{stem}.json if present."""
    p = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    return load_json(p)


def _win_file_busy(err):
    code = getattr(err, "winerror", None)
    if code in (5, 32):  # Access denied / sharing violation
        return True
    return isinstance(err, PermissionError)


def write_json(path, data):
    """原子写入。Windows 上目标文件被读/杀毒/网盘占用时 replace 会 WinError 5，需重试。"""
    ensure_dir(os.path.dirname(path) or ".")
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
        last_err = None
        for attempt in range(12):
            try:
                os.replace(tmp, path)
                return
            except OSError as e:
                if not _win_file_busy(e):
                    raise
                last_err = e
                time.sleep(0.03 * (attempt + 1))
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
        except OSError:
            if last_err:
                raise last_err
            raise
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def load_json(path, default=None, repair=True):
    """读 JSON。空文件重试；一份文件里拼了两段 JSON 时取第一段并可回写修复。"""
    if not path or not os.path.isfile(path):
        return default
    last_err = None
    for attempt in range(8):
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
        except OSError as e:
            last_err = e
            time.sleep(0.03 * (attempt + 1))
            continue
        text = (raw or "").lstrip("\ufeff").strip()
        if not text:
            last_err = "empty"
            time.sleep(0.03)
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_err = e
            if "Extra data" in str(e):
                try:
                    obj, _end = json.JSONDecoder().raw_decode(text)
                except Exception:
                    obj = None
                if obj is not None:
                    if repair:
                        try:
                            write_json(path, obj)
                        except Exception:
                            pass
                    return obj
            time.sleep(0.03)
    return default


def phrase_token_span(caption: str, phrase: str):
    """Return [start, end) of the first match, or None.

    注意：短短语可能落在更长短语内部。批量对齐请用 assign_phrase_token_spans。
    """
    phrase = (phrase or "").strip()
    if not caption or not phrase:
        return None
    idx = caption.find(phrase)
    if idx < 0:
        return None
    return [idx, idx + len(phrase)]


def assign_phrase_token_spans(caption: str, phrases) -> list:
    """为多条短语分配互不重叠的 [start, end)。

    - 按长度从长到短贪心，每条最多一个 span
    - 要求词边界，避免 a/with 命中 compact / without
    - 避免「green car」占住后「car」再抢同一段，或短串误标在长串内部
    - 返回与 phrases 等长的 list，元素为 [start,end) 或 None
    phrases 元素可以是 str，或带 "phrase" 的 dict。
    """
    caption = caption or ""
    texts = []
    for p in phrases or []:
        if isinstance(p, dict):
            texts.append((p.get("phrase") or "").strip())
        else:
            texts.append(str(p or "").strip())
    n = len(texts)
    spans = [None] * n
    claimed = []  # (start, end)
    order = sorted(range(n), key=lambda i: (-len(texts[i]), i))

    def _word_char(ch):
        return bool(ch) and ch.isalnum() and ("A" <= ch <= "Z" or "a" <= ch <= "z" or ch.isdigit())

    for i in order:
        ph = texts[i]
        if not ph:
            continue
        pos = 0
        while pos <= len(caption) - len(ph):
            idx = caption.find(ph, pos)
            if idx < 0:
                break
            end = idx + len(ph)
            overlap = any(not (end <= a or idx >= b) for a, b in claimed)
            left_ok = idx <= 0 or not _word_char(caption[idx - 1])
            right_ok = end >= len(caption) or not _word_char(caption[end])
            if not overlap and left_ok and right_ok:
                spans[i] = [idx, end]
                claimed.append((idx, end))
                break
            pos = idx + 1
    return spans
