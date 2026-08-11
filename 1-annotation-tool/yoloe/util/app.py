"""
# @Author: AI产品研发组
# @Date: 2026-08-05
# @Description: Grounding 人工检查 Flask 后端（刷新/手改/导出）
# @Command: python util/app.py --port 8082
"""

import json
import os
import sys
import threading
import traceback
from collections import deque
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

sys.path.insert(0, os.path.dirname(__file__))
from caption import add_caption_prefer_uncovered, regenerate_single_caption
from common import (
    detect_geometry,
    dir_has_images,
    dir_has_label_jsons,
    draft_dir,
    list_jsons_options,
    normalize_images_dirname,
    normalize_jsons_dirname,
    phrase_token_span,
    read_draft_config,
    resolve_images_dir,
    resolve_images_root,
    resolve_jsons_dir,
    write_draft_config,
    write_json,
)
from describe import describe_one_object, load_rules
from export_gd import export_dataset, export_stem
from generate import assess_draft, run_generate
from rules_io import (
    get_rules_scene,
    list_rule_scenes,
    resolve_caption_rules_path,
    resolve_describe_rules_path,
    set_rules_scene,
)
from validate_dataset import validate_dataset
from vllm_client import VLLMClient
from servers_io import (
    get_default_service,
    get_service,
    list_services,
    probe_services,
    servers_config_path,
)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.svg",
        mimetype="image/svg+xml",
    )


@app.after_request
def _no_cache_html(resp):
    if resp.content_type and "text/html" in resp.content_type:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp


state = {
    "dataset_root": "",
    "jsons_dirname": "jsons",
    "images_dirname": "images",
    "geometry": "",  # rectangle | polygon | mixed
    "rules_scene": get_rules_scene(),  # ""=通用；如 vesthalmet
    "service_id": "",
    "base_url": os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8081/v1"),
    "model": os.environ.get("VLLM_MODEL", "qwen3.6-35b-a3b"),
    "n_captions": int(os.environ.get("N_CAPTIONS", "5")),
    "expand_ratio": float(os.environ.get("EXPAND_RATIO", "1.5")),
    "workers": int(os.environ.get("DESCRIBE_WORKERS", "8")),
}


def _apply_service(svc: dict):
    if not svc:
        return
    state["service_id"] = svc.get("id") or ""
    if svc.get("base_url"):
        state["base_url"] = str(svc["base_url"]).rstrip("/")
    if svc.get("model"):
        state["model"] = str(svc["model"])


# model/server.json 默认服务优先于硬编码；环境变量仍可在无配置时兜底
_svc0 = get_default_service()
if _svc0:
    _apply_service(_svc0)
elif os.environ.get("VLLM_BASE_URL") or os.environ.get("VLLM_MODEL"):
    state["base_url"] = os.environ.get("VLLM_BASE_URL", state["base_url"])
    state["model"] = os.environ.get("VLLM_MODEL", state["model"])

# 进程内单例 generate 任务
_gen_lock = threading.Lock()
_gen_job = {
    "status": "idle",  # idle|running|done|error
    "stage": "",
    "dataset_root": "",
    "jsons_dirname": "jsons",
    "images_dirname": "images",
    "assessment": None,
    "error": "",
    "logs": deque(maxlen=400),
    "progress": [],  # [{id,label,status: pending|running|done|skip|error}]
}


def _default_progress(stages=None):
    stages = set(stages or [])
    steps = [
        {"id": "validate", "label": "数据集校验", "status": "pending", "pct": 0, "detail": ""},
        {"id": "crop", "label": "裁剪目标 (crop)", "status": "pending", "pct": 0, "detail": ""},
        {"id": "describe", "label": "标签描述 (describe)", "status": "pending", "pct": 0, "detail": ""},
        {"id": "caption", "label": "生成 caption", "status": "pending", "pct": 0, "detail": ""},
        {"id": "done", "label": "完成", "status": "pending", "pct": 0, "detail": ""},
    ]
    for s in steps:
        if s["id"] in {"crop", "describe", "caption"} and s["id"] not in stages:
            s["status"] = "skip"
            s["pct"] = 100
    return steps


def _set_progress(step_id, status, pct=None, detail=None):
    with _gen_lock:
        for s in _gen_job["progress"]:
            if s["id"] == step_id:
                s["status"] = status
                if pct is not None:
                    s["pct"] = int(max(0, min(100, pct)))
                elif status == "done" or status == "skip":
                    s["pct"] = 100
                elif status == "pending":
                    s["pct"] = 0
                if detail is not None:
                    s["detail"] = detail
                break
        if status == "running":
            _gen_job["stage"] = step_id


def _stage_progress(stage, done, total, detail=""):
    """细粒度阶段进度：更新 pct / detail，并写一条轻量日志。"""
    total = max(int(total or 0), 1)
    done = max(0, min(int(done or 0), total))
    pct = int(round(100.0 * done / total))
    _set_progress(stage, "running", pct=pct, detail=detail or f"{done}/{total}")
    # 节流日志：每 10% 或完成时写一行
    with _gen_lock:
        key = f"_last_log_{stage}"
        last = _gen_job.get(key, -1)
        if pct >= 100 or pct - last >= 10 or done == total:
            _gen_job[key] = pct
            _gen_job["logs"].append(f"[{stage}] {pct}% ({detail or f'{done}/{total}'})")


def _root():
    return state["dataset_root"]


def _client():
    return VLLMClient(
        base_url=state["base_url"], model=state["model"], enable_thinking=False
    )


def list_stems():
    obj_dir = os.path.join(draft_dir(_root()), "objects")
    if not os.path.isdir(obj_dir):
        return []
    return sorted(Path(p).stem for p in Path(obj_dir).glob("*.json"))


def load_json(path, default=None):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def translate_text(text: str) -> str:
    if not text:
        return ""
    try:
        raw = _client().text(
            "Translate to Simplified Chinese. Return Chinese only, no quotes.\n\n"
            + text,
            temperature=0.2,
            max_tokens=512,
        )
        return (raw or "").strip().strip('"').strip("'")
    except Exception as e:
        print(f"[warn] translate_text failed: {e}")
        return ""


def translate_batch(texts):
    """Translate many English strings in one vLLM call. Returns list[str]."""
    texts = [t or "" for t in texts]
    if not texts:
        return []
    if len(texts) == 1:
        return [translate_text(texts[0])]
    # 分块：短语短可加大块；失败时整块降级单条（慢），尽量少触发
    out = [""] * len(texts)
    avg_len = sum(len(t) for t in texts) / max(1, len(texts))
    chunk = 24 if avg_len < 80 else 12
    max_tokens = 1024 if avg_len < 80 else 2048
    from vllm_client import extract_json_object
    for start in range(0, len(texts), chunk):
        part = texts[start:start + chunk]
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(part))
        prompt = (
            "Translate each English line to Simplified Chinese.\n"
            "Return JSON only: {\"zh\": [\"...\", ...]} same count/order.\n\n"
            f"{numbered}"
        )
        try:
            raw = _client().text(prompt, temperature=0.2, max_tokens=max_tokens)
            data = extract_json_object(raw)
            zh = data.get("zh") or []
            for i, t in enumerate(part):
                val = zh[i] if i < len(zh) and zh[i] else translate_text(t)
                out[start + i] = str(val).strip()
        except Exception as e:
            print(f"[warn] translate_batch chunk failed: {e}")
            for i, t in enumerate(part):
                out[start + i] = translate_text(t)
    return out


def ensure_zh_for_item(stem, meta, caps, descs, obj_ids=None, mode="all"):
    """
    Fill missing Chinese; English unchanged.
    mode: captions | descs | all
      - captions：只补 caption.zh（界面先出中文）
      - descs：只补目标短语 zh
      - all：两者都做
    """
    mode = (mode or "all").strip().lower()
    if mode not in {"captions", "descs", "all"}:
        mode = "all"
    did = False

    # 1) captions 优先（界面立刻要看）
    if mode in {"captions", "all"}:
        cap_jobs = []
        for si, sent in enumerate(caps.get("captions", [])):
            if not sent.get("zh"):
                cap_jobs.append((si, sent.get("caption", "")))
        if cap_jobs:
            zh_caps = translate_batch([t for _, t in cap_jobs])
            for (si, _), z in zip(cap_jobs, zh_caps):
                caps["captions"][si]["zh"] = z
            write_json(os.path.join(draft_dir(_root()), "captions", f"{stem}.json"), caps)
            did = True

    # 2) 目标短语：默认只补传入 / caption 关联的 obj_ids
    if mode in {"descs", "all"}:
        if obj_ids is None:
            obj_ids = set()
            for sent in caps.get("captions", []):
                obj_ids.update(sent.get("obj_ids") or [])
        obj_ids = set(int(x) for x in obj_ids)

        desc_jobs = []
        for oid in obj_ids:
            key = str(oid)
            desc = descs.get(key)
            if not desc:
                continue
            phrases = desc.get("phrases") or []
            zh = list(desc.get("zh") or [])
            while len(zh) < len(phrases):
                zh.append("")
            desc["zh"] = zh
            descs[key] = desc
            for i, p in enumerate(phrases):
                if not zh[i]:
                    desc_jobs.append((key, i, p))

        if desc_jobs:
            zh_list = translate_batch([t for _, _, t in desc_jobs])
            for (key, i, _), z in zip(desc_jobs, zh_list):
                descs[key]["zh"][i] = z
            for key in {j[0] for j in desc_jobs}:
                path = os.path.join(
                    draft_dir(_root()), "descriptions", f"{stem}_obj{int(key):04d}.json"
                )
                disk = load_json(path)
                mem = descs[key]
                if disk is not None and (disk.get("phrases") or []) != (mem.get("phrases") or []):
                    continue
                write_json(path, {**mem, "obj_id": int(key), "stem": stem})
            did = True

    return did


@app.route("/")
def index():
    return render_template("index.html")


def _isdir_quick(path: str, timeout: float = 0.35) -> bool:
    """带超时的 isdir，避免网络盘/卡住盘符把选夹按钮拖死。"""
    if not path:
        return False
    box = {"ok": False}

    def _run():
        try:
            box["ok"] = os.path.isdir(path)
        except Exception:
            box["ok"] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    return bool(box["ok"]) if not t.is_alive() else False


def _default_browse_root() -> str:
    """未指定 path 时的浏览起点：优先用户主目录，盘符探测带超时。"""
    home = os.path.expanduser("~")
    if home and _isdir_quick(home, 0.5):
        return os.path.realpath(home)
    if os.name != "nt":
        for cand in ("/home/yulin", "/"):
            if _isdir_quick(cand, 0.35):
                return os.path.realpath(cand)
        return os.getcwd()
    # Windows：不要同步死等 D:/E: 网络盘
    for drive in ("C:\\", "D:\\", "E:\\"):
        if _isdir_quick(drive, 0.25):
            return drive
    return os.getcwd()


def _safe_dir_name(name: str) -> bool:
    """过滤隐藏目录与含路径分隔符的异常名（如误创建的 '\\'）。"""
    if not name or name in {".", ".."}:
        return False
    if name.startswith("."):
        return False
    if "/" in name or "\\" in name:
        return False
    return True


def _normalize_user_path(raw: str) -> str:
    p = (raw or "").strip().strip('"')
    if not p:
        return ""
    # 保留 Windows 盘符路径；仅统一多余分隔
    if os.name == "nt":
        p = p.replace("/", "\\")
    else:
        p = p.replace("\\", "/")
    return p


def _probe_dir(req_path: str, *, light: bool = False) -> dict:
    """目录探测结果（供网页浏览 / 原生选夹共用）。

    light=True：浏览导航用——不扫任意子目录找图、不解析标签几何（避免大盘卡顿）。
    """
    req_path = os.path.realpath(req_path)
    if not os.path.isdir(req_path):
        return {"error": f"不是有效目录: {req_path}"}
    entries = []
    try:
        # scandir 比 listdir+isdir 快；子目录名排序在收集后做
        dirs = []
        with os.scandir(req_path) as it:
            for ent in it:
                if not ent.is_dir(follow_symlinks=False):
                    continue
                if not _safe_dir_name(ent.name):
                    continue
                dirs.append(ent.name)
        for name in sorted(dirs):
            entries.append({
                "name": name,
                "type": "dir",
                "path": os.path.join(req_path, name),
            })
    except PermissionError:
        return {"error": "无读取权限"}
    parent_path = str(Path(req_path).parent)
    parent = None if parent_path == req_path else parent_path
    # 浏览时不必枚举 jsons 候选；选夹确认时再取
    jsons_options = [] if light else list_jsons_options(req_path)
    img_root, img_dir, images_dirname = resolve_images_root(
        req_path, deep=not light,
    )
    label_ok = dir_has_label_jsons(req_path)
    geometry = None
    if label_ok and not light:
        # 选夹确认：只抽很少样本判几何，完整校验交给 openDataset
        geometry = detect_geometry(req_path, sample_limit=5).get("geometry")
    return {
        "current": req_path,
        "parent": parent,
        "entries": entries,
        "jsons_options": jsons_options,
        "has_images": bool(img_root),
        "images_root": img_root,
        "images_dir": img_dir,
        "images_dirname": images_dirname,
        "has_label_jsons": label_ok,
        "geometry": geometry,
        "light": bool(light),
    }


def _native_folder_picker_available() -> bool:
    """本机原生选文件夹：Windows 可用；其它平台回退网页浏览。"""
    return os.name == "nt"


def _pick_folder_windows(initial: str = "", title: str = "选择文件夹") -> str:
    """
    弹出 Windows 原生「浏览文件夹」对话框（tkinter → 系统对话框）。
    在独立子进程中打开，避免阻塞 Flask 线程时 GUI 出问题。
    """
    import subprocess
    import sys
    import tempfile

    init = _normalize_user_path(initial)
    if not init or not os.path.isdir(init):
        init = _default_browse_root()
    title = (title or "选择文件夹").replace("\r", " ").replace("\n", " ")

    helper = r'''
import os, sys
import tkinter as tk
from tkinter import filedialog
init = sys.argv[1] if len(sys.argv) > 1 else ""
title = sys.argv[2] if len(sys.argv) > 2 else "Select Folder"
out_path = sys.argv[3] if len(sys.argv) > 3 else ""
if not init or not os.path.isdir(init):
    init = os.path.expanduser("~") or "C:\\"
root = tk.Tk()
root.withdraw()
try:
    root.attributes("-topmost", True)
except Exception:
    pass
path = filedialog.askdirectory(initialdir=init, title=title, mustexist=True)
try:
    root.destroy()
except Exception:
    pass
data = path or ""
if out_path:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(data)
else:
    sys.stdout.write(data)
'''
    # 写临时脚本避免 -c 引号/编码坑；优先 pythonw 以免多一个控制台窗
    # 结果写文件：pythonw 下 stdout 不可靠
    fd, helper_path = tempfile.mkstemp(suffix=".py", prefix="pick_folder_")
    out_fd, out_path = tempfile.mkstemp(suffix=".txt", prefix="pick_folder_out_")
    os.close(out_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(helper)
        exe = sys.executable
        if os.name == "nt" and exe.lower().endswith("python.exe"):
            pyw = exe[:-10] + "pythonw.exe"
            if os.path.isfile(pyw):
                exe = pyw
        subprocess.run(
            [exe, helper_path, init, title, out_path],
            timeout=600,
        )
        try:
            with open(out_path, encoding="utf-8") as f:
                path = f.read().strip().strip('"')
        except OSError:
            path = ""
        if path and os.path.isdir(path):
            return os.path.realpath(path)
        return ""
    finally:
        for p in (helper_path, out_path):
            try:
                os.remove(p)
            except OSError:
                pass



@app.route("/api/browse")
def browse():
    raw = _normalize_user_path(request.args.get("path") or "")
    req_path = raw or _default_browse_root()
    # 默认 light：翻目录不深探；确认前可 ?light=0
    light_q = (request.args.get("light") or "1").strip().lower()
    light = light_q not in {"0", "false", "no"}
    info = _probe_dir(req_path, light=light)
    if info.get("error"):
        code = 403 if info["error"] == "无读取权限" else 400
        return jsonify(info), code
    return jsonify(info)


@app.route("/api/pick_folder", methods=["POST"])
def pick_folder():
    """Windows：原生选文件夹；其它平台返回 native=false，前端走网页浏览。"""
    data = request.json or {}
    title = (data.get("title") or "选择文件夹").strip()
    initial = _normalize_user_path(data.get("initial") or "")
    if not _native_folder_picker_available():
        return jsonify({
            "ok": False,
            "native": False,
            "error": "当前系统请使用网页目录浏览",
        })
    try:
        path = _pick_folder_windows(initial=initial, title=title)
    except Exception as e:
        return jsonify({"ok": False, "native": True, "error": f"打开选夹对话框失败: {e}"}), 500
    if not path:
        return jsonify({"ok": False, "native": True, "cancelled": True})
    info = _probe_dir(path)
    if info.get("error"):
        return jsonify({"ok": False, "native": True, "error": info["error"]}), 400
    info.update({"ok": True, "native": True, "path": info["current"]})
    return jsonify(info)


@app.route("/api/probe_labels", methods=["POST"])
def probe_labels():
    """探测标签目录几何属性（rectangle / polygon / mixed）。"""
    data = request.json or {}
    path = (data.get("path") or "").strip()
    root = (data.get("dataset_root") or _root() or "").strip()
    jsons_dirname = data.get("jsons_dirname")
    if path:
        json_dir = os.path.realpath(path)
    elif root and jsons_dirname:
        json_dir = resolve_jsons_dir(root, jsons_dirname)
    else:
        return jsonify({"error": "未指定标签路径"}), 400
    if not os.path.isdir(json_dir):
        return jsonify({"error": f"目录不存在: {json_dir}"}), 400
    result = detect_geometry(json_dir)
    result["path"] = json_dir
    return jsonify(result)


@app.route("/api/rules_scenes")
def rules_scenes_api():
    """列出 rules/ 下可用场景（自动发现 describe_rules_<scene>.md）。"""
    scenes = list_rule_scenes()
    cur = get_rules_scene()
    return jsonify({
        "ok": True,
        "scene": cur,
        "scenes": scenes,
        "describe_path": resolve_describe_rules_path(cur),
        "caption_path": resolve_caption_rules_path(cur),
    })


@app.route("/api/config", methods=["GET", "POST"])
def config_api():
    if request.method == "GET":
        payload = dict(state)
        payload["platform"] = os.name
        payload["native_folder_picker"] = _native_folder_picker_available()
        payload["rules_scene"] = get_rules_scene()
        payload["rules_scenes"] = list_rule_scenes()
        payload["describe_rules_path"] = resolve_describe_rules_path()
        payload["caption_rules_path"] = resolve_caption_rules_path()
        payload["model_services"] = list_services()
        payload["servers_path"] = servers_config_path()
        return jsonify(payload)
    data = request.json or {}
    root = (data.get("dataset_root") or "").strip()
    if root:
        if not os.path.isdir(root):
            return jsonify({"error": f"目录不存在: {root}"}), 400
        state["dataset_root"] = root
    if data.get("jsons_dirname"):
        state["jsons_dirname"] = normalize_jsons_dirname(data["jsons_dirname"])
    if data.get("images_dirname"):
        state["images_dirname"] = normalize_images_dirname(data["images_dirname"])
    if data.get("geometry"):
        state["geometry"] = data["geometry"]
    if data.get("service_id"):
        svc = get_service(str(data["service_id"]))
        if not svc:
            return jsonify({"error": f"未知模型服务: {data['service_id']}"}), 400
        _apply_service(svc)
    if data.get("base_url"):
        state["base_url"] = str(data["base_url"]).rstrip("/")
    if data.get("model"):
        state["model"] = data["model"]
    if "rules_scene" in data:
        sc = set_rules_scene(data.get("rules_scene"))
        state["rules_scene"] = sc
        if state.get("dataset_root"):
            write_draft_config(state["dataset_root"], {"rules_scene": sc})
    return jsonify({"ok": True, "config": {
        **state,
        "rules_scene": get_rules_scene(),
        "describe_rules_path": resolve_describe_rules_path(),
        "caption_rules_path": resolve_caption_rules_path(),
        "model_services": list_services(),
        "servers_path": servers_config_path(),
    }})


@app.route("/api/model_services", methods=["GET"])
def model_services_api():
    """列出 model/server.json 中的服务；probe=1 时并行探测可用性。"""
    probe = str(request.args.get("probe") or "").lower() in ("1", "true", "yes")
    if probe:
        services = probe_services(timeout=2.5)
    else:
        services = list_services()
    return jsonify({
        "ok": True,
        "path": servers_config_path(),
        "service_id": state.get("service_id") or "",
        "base_url": state.get("base_url") or "",
        "model": state.get("model") or "",
        "services": services,
    })


@app.route("/api/model_services/select", methods=["POST"])
def model_services_select_api():
    data = request.json or {}
    sid = str(data.get("service_id") or data.get("id") or "").strip()
    if not sid:
        return jsonify({"error": "缺少 service_id"}), 400
    svc = get_service(sid)
    if not svc:
        return jsonify({"error": f"未知模型服务: {sid}"}), 400
    _apply_service(svc)
    return jsonify({
        "ok": True,
        "service_id": state["service_id"],
        "base_url": state["base_url"],
        "model": state["model"],
        "service": svc,
    })


@app.route("/api/validate", methods=["POST"])
def validate_api():
    data = request.json or {}
    root = (data.get("dataset_root") or _root() or "").strip()
    if not root:
        return jsonify({"error": "未指定数据集"}), 400
    jsons_dirname = normalize_jsons_dirname(
        data.get("jsons_dirname") or state.get("jsons_dirname") or "jsons"
    )
    images_dirname = normalize_images_dirname(
        data.get("images_dirname") or state.get("images_dirname") or "images"
    )
    force = bool(data.get("force"))
    result = validate_dataset(
        root, jsons_dirname=jsons_dirname, images_dirname=images_dirname,
        force=force,
    )
    return jsonify(result)


def _gen_log(msg: str):
    with _gen_lock:
        _gen_job["logs"].append(str(msg))
        text = str(msg)
        if text.startswith("→ stage:"):
            stage = text.split(":", 1)[-1].strip()
            _gen_job["stage"] = stage
    # 阶段切换：当前 running，上一个 done
    if msg.startswith("→ stage:"):
        stage = msg.split(":", 1)[-1].strip().split()[0]
        order = ["crop", "describe", "caption"]
        if stage in order:
            idx = order.index(stage)
            for prev in order[:idx]:
                with _gen_lock:
                    for s in _gen_job["progress"]:
                        if s["id"] == prev and s["status"] in {"running", "pending"}:
                            s["status"] = "done"
                            s["pct"] = 100
            _set_progress(stage, "running", pct=0, detail="0/?")
    elif msg.strip() == "generate 完成":
        for sid in ("crop", "describe", "caption"):
            with _gen_lock:
                for s in _gen_job["progress"]:
                    if s["id"] == sid and s["status"] == "running":
                        s["status"] = "done"
                        s["pct"] = 100
        _set_progress("done", "done", pct=100)


def _run_generate_thread(root: str, assessment: dict, jsons_dirname: str,
                         force: bool = False, images_dirname: str = "images"):
    try:
        stages = list(assessment.get("stages") or [])
        force_crop = bool(assessment.get("force_crop"))
        force_llm = bool(force)
        _gen_log(
            f"开始生成 stages={stages} images={images_dirname} jsons={jsons_dirname}"
            + (" force_crop" if force_crop else "")
            + (" force_llm" if force_llm else "")
        )
        prefer = state.get("geometry") or None
        if prefer == "mixed":
            prefer = "rectangle"
        did_crop = False
        if "crop" in stages:
            from crop_objects import crop_dataset
            _gen_log("→ stage: crop" + (" (force)" if force_crop else ""))
            crop_dataset(
                root,
                expand_ratio=state["expand_ratio"],
                force=force_crop,
                jsons_dirname=jsons_dirname,
                images_dirname=images_dirname,
                progress_cb=lambda d, t, det="": _stage_progress("crop", d, t, det),
                prefer_geometry=prefer,
            )
            _set_progress("crop", "done", pct=100)
            stages = [s for s in stages if s != "crop"]
            did_crop = True

        # crop 后重评估；force_llm 时仍强制跑 describe/caption
        if did_crop:
            reassess = assess_draft(
                root,
                jsons_dirname=jsons_dirname,
                geometry=state.get("geometry") or None,
            )
            stages = [s for s in (reassess.get("stages") or []) if s != "crop"]
            if force_llm:
                for s in ("describe", "caption"):
                    if s not in stages:
                        stages.append(s)
            _gen_log(f"crop 后重评估: ready={reassess.get('ready')} stages={stages}")
            with _gen_lock:
                _gen_job["assessment"] = reassess
                for s in _gen_job["progress"]:
                    if s["id"] in ("describe", "caption"):
                        if s["id"] in stages:
                            if s["status"] == "skip":
                                s["status"] = "pending"
                                s["pct"] = 0
                        else:
                            s["status"] = "skip"
                            s["pct"] = 100
                            s["detail"] = "draft 已完整"

        if not stages:
            _gen_log("draft 已完整，跳过 vLLM ✅")
            with _gen_lock:
                for s in _gen_job["progress"]:
                    if s["id"] == "done":
                        s["status"] = "done"
                        s["pct"] = 100
                    elif s["status"] == "pending":
                        s["status"] = "skip"
                        s["pct"] = 100
                _gen_job["status"] = "done"
                _gen_job["stage"] = "done"
            return

        llm_stages = [s for s in stages if s in ("describe", "caption")]
        if llm_stages:
            _gen_log(f"需要 vLLM 阶段: {llm_stages}")
        else:
            _gen_log("无需 vLLM 阶段")

        run_generate(
            root,
            stages=stages,
            expand_ratio=state["expand_ratio"],
            base_url=state["base_url"],
            model=state["model"],
            n_captions=state["n_captions"],
            force=force_llm,
            no_llm=False,
            workers=state["workers"],
            log=_gen_log,
            jsons_dirname=jsons_dirname,
            images_dirname=images_dirname,
            progress=_stage_progress,
            prefer_geometry=prefer,
        )
        with _gen_lock:
            for s in _gen_job["progress"]:
                if s["status"] == "running":
                    s["status"] = "done"
                    s["pct"] = 100
                if s["id"] == "done":
                    s["status"] = "done"
                    s["pct"] = 100
            _gen_job["status"] = "done"
            _gen_job["stage"] = "done"
    except Exception as e:
        tb = traceback.format_exc()
        _gen_log(f"ERROR: {e}")
        _gen_log(tb)
        with _gen_lock:
            for s in _gen_job["progress"]:
                if s["status"] == "running":
                    s["status"] = "error"
            _gen_job["status"] = "error"
            _gen_job["error"] = str(e)


@app.route("/api/generate/start", methods=["POST"])
def generate_start():
    data = request.json or {}
    root = (data.get("dataset_root") or _root() or "").strip()
    jsons_dirname = normalize_jsons_dirname(
        data.get("jsons_dirname") or state.get("jsons_dirname") or "jsons"
    )
    images_dirname = normalize_images_dirname(
        data.get("images_dirname") or state.get("images_dirname") or "images"
    )
    # mode: resume（缺啥补啥）| regenerate（强制重跑 describe+caption）
    mode = (data.get("mode") or "resume").strip().lower()
    force = bool(data.get("force")) or mode == "regenerate"
    if "rules_scene" in data:
        state["rules_scene"] = set_rules_scene(data.get("rules_scene"))
    else:
        set_rules_scene(state.get("rules_scene") or get_rules_scene())
    if not root:
        return jsonify({"error": "未指定数据集"}), 400
    if not os.path.isdir(root):
        return jsonify({"error": f"目录不存在: {root}"}), 400

    with _gen_lock:
        if _gen_job["status"] == "running":
            return jsonify({
                "ok": True,
                "status": "running",
                "message": "已有生成任务在运行",
                "assessment": _gen_job.get("assessment"),
                "progress": list(_gen_job.get("progress") or []),
                "jsons_dirname": _gen_job.get("jsons_dirname"),
                "images_dirname": _gen_job.get("images_dirname"),
            })

    progress = _default_progress()
    progress[0]["status"] = "running"
    with _gen_lock:
        _gen_job["progress"] = progress
        _gen_job["logs"].clear()
        _gen_job["logs"].append(
            f"dataset={root} images={images_dirname} jsons={jsons_dirname} "
            f"mode={mode} force={force} rules_scene={get_rules_scene() or 'default'}"
        )
        _gen_job["error"] = ""
        _gen_job["status"] = "running"
        _gen_job["stage"] = "validate"
        _gen_job["dataset_root"] = root
        _gen_job["jsons_dirname"] = jsons_dirname
        _gen_job["images_dirname"] = images_dirname

    # regenerate(force) 强制全量校验；续跑优先 draft/validate_log.json
    validation = validate_dataset(
        root, jsons_dirname=jsons_dirname, images_dirname=images_dirname,
        force=bool(force),
    )
    if validation.get("from_cache"):
        _gen_log(
            f"校验快速通过（{validation.get('cache_path') or 'cache'}），跳过全量读标签"
        )
    else:
        _gen_log("校验完成，已写入 draft/validate_log.json")
    if not validation.get("ok"):
        _set_progress("validate", "error")
        with _gen_lock:
            _gen_job["status"] = "error"
            _gen_job["error"] = "数据集校验失败"
        return jsonify({
            "ok": False,
            "status": "error",
            "error": "数据集校验失败",
            "validation": validation,
            "progress": list(_gen_job["progress"]),
            "jsons_dirname": jsons_dirname,
            "images_dirname": images_dirname,
        }), 400

    geom = validation.get("geometry") or data.get("geometry") or ""
    state["geometry"] = geom
    cache_tag = "缓存" if validation.get("from_cache") else "全量"
    _set_progress(
        "validate", "done", pct=100,
        detail=f"通过 · {geom or '?'} · {cache_tag}",
    )
    # 打开/续跑：快速评估（不逐文件深扫）；重新生成仍 deep 精检
    assessment = assess_draft(
        root, jsons_dirname=jsons_dirname, geometry=geom, deep=bool(force),
    )
    if force:
        stages = list(assessment.get("stages") or [])
        for s in ("describe", "caption"):
            if s not in stages:
                stages.append(s)
        order = ["crop", "describe", "caption"]
        stages = [s for s in order if s in stages] + [s for s in stages if s not in order]
        assessment = dict(assessment)
        assessment["stages"] = stages
        assessment["ready"] = False
        assessment["force_llm"] = True
    state["dataset_root"] = root
    state["jsons_dirname"] = jsons_dirname
    state["images_dirname"] = images_dirname

    # 按实际 stages 标记 skip
    with _gen_lock:
        _gen_job["progress"] = _default_progress(assessment.get("stages"))
        _gen_job["progress"][0]["status"] = "done"  # validate
        _gen_job["progress"][0]["pct"] = 100
        _gen_job["progress"][0]["detail"] = "通过"
        _gen_job["assessment"] = assessment
        _gen_job["logs"].append(
            f"校验通过✅ geometry={validation.get('geometry')} "
            f"images={images_dirname} jsons={jsons_dirname}"
        )
        _gen_job["logs"].append(f"assess={assessment}")

    if assessment.get("ready") and not force:
        write_draft_config(root, {
            "jsons_dirname": jsons_dirname,
            "images_dirname": images_dirname,
            "geometry": geom,
            "rules_scene": get_rules_scene(),
        })
        with _gen_lock:
            for s in _gen_job["progress"]:
                if s["id"] != "validate" and s["status"] != "skip":
                    s["status"] = "skip"
                if s["id"] == "done":
                    s["status"] = "done"
            _gen_job["status"] = "done"
            _gen_job["stage"] = "ready"
            _gen_job["logs"].append("draft 已完整，无需 generate ✅")
        return jsonify({
            "ok": True,
            "status": "ready",
            "assessment": assessment,
            "validation": validation,
            "progress": list(_gen_job["progress"]),
            "jsons_dirname": jsons_dirname,
            "images_dirname": images_dirname,
            "geometry": validation.get("geometry"),
        })

    write_draft_config(root, {
        "jsons_dirname": jsons_dirname,
        "images_dirname": images_dirname,
        "geometry": geom,
        "rules_scene": get_rules_scene(),
    })

    with _gen_lock:
        _gen_job["status"] = "running"
        first = assessment["stages"][0] if assessment["stages"] else ""
        _gen_job["stage"] = first
        if first:
            for s in _gen_job["progress"]:
                if s["id"] == first:
                    s["status"] = "running"

    t = threading.Thread(
        target=_run_generate_thread,
        args=(root, assessment, jsons_dirname, force, images_dirname),
        daemon=True,
    )
    t.start()
    return jsonify({
        "ok": True,
        "status": "running",
        "assessment": assessment,
        "validation": validation,
        "progress": list(_gen_job["progress"]),
        "jsons_dirname": jsons_dirname,
        "images_dirname": images_dirname,
        "geometry": validation.get("geometry"),
        "mode": mode,
        "force": force,
    })


@app.route("/api/generate/status")
def generate_status():
    with _gen_lock:
        logs = list(_gen_job["logs"])
        return jsonify({
            "status": _gen_job["status"],
            "stage": _gen_job["stage"],
            "dataset_root": _gen_job["dataset_root"],
            "jsons_dirname": _gen_job.get("jsons_dirname") or state.get("jsons_dirname"),
            "assessment": _gen_job["assessment"],
            "error": _gen_job["error"],
            "logs": logs[-120:],
            "progress": list(_gen_job.get("progress") or []),
        })


@app.route("/api/images")
def images():
    """列表：只 scandir，不逐张读 caption（打开大数据集时差一个数量级）。"""
    if not _root():
        return jsonify([])
    root = _root()
    gd_dir = os.path.join(root, "jsons-GD")
    cap_dir = os.path.join(draft_dir(root), "captions")
    exported = set()
    if os.path.isdir(gd_dir):
        try:
            with os.scandir(gd_dir) as it:
                for ent in it:
                    if ent.is_file() and ent.name.endswith(".json"):
                        exported.add(Path(ent.name).stem)
        except OSError:
            pass
    has_cap = set()
    if os.path.isdir(cap_dir):
        try:
            with os.scandir(cap_dir) as it:
                for ent in it:
                    if ent.is_file() and ent.name.endswith(".json"):
                        has_cap.add(Path(ent.name).stem)
        except OSError:
            pass
    result = []
    for stem in list_stems():
        result.append({
            "stem": stem,
            "name": f"{stem}.jpg",
            # 列表不解析条数；有 caption 文件则标 -1 让前端显示「captions」
            "n_captions": -1 if stem in has_cap else 0,
            "exported": stem in exported,
        })
    return jsonify(result)


def _load_item_payload(stem):
    meta = load_json(os.path.join(draft_dir(_root()), "objects", f"{stem}.json"))
    caps = load_json(os.path.join(draft_dir(_root()), "captions", f"{stem}.json"), {"captions": []})
    if not meta:
        return None
    descs = {}
    ddir = os.path.join(draft_dir(_root()), "descriptions")
    for obj in meta["objects"]:
        p = os.path.join(ddir, f"{stem}_obj{obj['obj_id']:04d}.json")
        descs[str(obj["obj_id"])] = load_json(
            p, {"phrases": [obj["label"]], "label": obj["label"], "zh": []}
        )
    return {"meta": meta, "captions": caps, "descriptions": descs}


@app.route("/api/item/<stem>")
def get_item(stem):
    """Fast path: never block on vLLM translation."""
    if not _root():
        return jsonify({"error": "未配置数据集"}), 400
    payload = _load_item_payload(stem)
    if not payload:
        return jsonify({"error": "无 objects 数据"}), 404
    return jsonify(payload)


@app.route("/api/ensure_zh/<stem>", methods=["POST"])
def ensure_zh_api(stem):
    """Async-friendly: batch translate missing zh, then return updated item.
    body.mode: captions|descs|all — 前端可先 captions 再 descs，优先当前图可见内容。
    """
    if not _root():
        return jsonify({"error": "未配置数据集"}), 400
    payload = _load_item_payload(stem)
    if not payload:
        return jsonify({"error": "无 objects 数据"}), 404
    data = request.json or {}
    obj_ids = data.get("obj_ids")
    mode = data.get("mode") or "all"
    try:
        ensure_zh_for_item(
            stem, payload["meta"], payload["captions"], payload["descriptions"],
            obj_ids=obj_ids,
            mode=mode,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    payload = _load_item_payload(stem)
    return jsonify({"ok": True, **payload})


@app.route("/api/image/<stem>")
def serve_image(stem):
    meta = load_json(os.path.join(draft_dir(_root()), "objects", f"{stem}.json"))
    if not meta:
        return jsonify({"error": "not found"}), 404
    images_dirname = state.get("images_dirname") or "images"
    cfg = read_draft_config(_root())
    if cfg.get("images_dirname"):
        images_dirname = normalize_images_dirname(cfg["images_dirname"])
        state["images_dirname"] = images_dirname
    img_dir = resolve_images_dir(_root(), images_dirname)
    return send_from_directory(img_dir, meta["image"])


@app.route("/api/crop/<stem>/<int:obj_id>")
def serve_crop(stem, obj_id):
    meta = load_json(os.path.join(draft_dir(_root()), "objects", f"{stem}.json"))
    if not meta:
        return jsonify({"error": "not found"}), 404
    for obj in meta["objects"]:
        if obj["obj_id"] == obj_id:
            full = os.path.join(_root(), obj["crop_path"])
            return send_from_directory(os.path.dirname(full), os.path.basename(full))
    return jsonify({"error": "obj not found"}), 404


@app.route("/api/save/<stem>", methods=["POST"])
def save_item(stem):
    data = request.json or {}
    # descriptions
    if "descriptions" in data:
        for oid, desc in data["descriptions"].items():
            phrases = [p.strip() for p in desc.get("phrases", []) if str(p).strip()]
            out = {
                "obj_id": int(oid),
                "stem": stem,
                "label": desc.get("label", ""),
                "phrases": phrases,
                "zh": desc.get("zh", []),
            }
            write_json(
                os.path.join(draft_dir(_root()), "descriptions", f"{stem}_obj{int(oid):04d}.json"),
                out,
            )
    # captions: refresh token spans；无选用短语时强制 caption 为空
    if "captions" in data:
        caps = data["captions"]
        for sent in caps.get("captions", []):
            phrases = sent.get("phrases") or []
            has_sel = any(
                isinstance(ph, dict) and str(ph.get("phrase") or "").strip()
                for ph in phrases
            )
            if not has_sel:
                sent["phrases"] = []
                sent["caption"] = ""
                sent["zh"] = ""
                continue
            caption = sent.get("caption", "")
            for ph in phrases:
                if isinstance(ph, dict):
                    ph["tokens_positive"] = phrase_token_span(
                        caption, ph.get("phrase", "")
                    )
        write_json(os.path.join(draft_dir(_root()), "captions", f"{stem}.json"), caps)
    return jsonify({"ok": True})


@app.route("/api/refresh_desc/<stem>/<int:obj_id>", methods=["POST"])
def refresh_desc(stem, obj_id):
    """刷新单个目标描述；失败时不覆盖已有 draft。

    若 body 带 sentence_id：保留该 caption 已选用短语，只重刷其余空位（合计最多 3 条）。
    """
    if not _root():
        return jsonify({"error": "未配置数据集"}), 400
    desc_path = os.path.join(
        draft_dir(_root()), "descriptions", f"{stem}_obj{obj_id:04d}.json"
    )
    old = load_json(desc_path)
    try:
        body = request.json or {}
        sentence_id = body.get("sentence_id")
        try:
            sentence_id = int(sentence_id) if sentence_id is not None else None
        except (TypeError, ValueError):
            sentence_id = None

        cap_path = os.path.join(draft_dir(_root()), "captions", f"{stem}.json")
        caps = load_json(cap_path, {"captions": []})
        sents = caps.get("captions") or []

        keep = []
        avoid = []
        if sentence_id is not None and 0 <= sentence_id < len(sents):
            for ph in sents[sentence_id].get("phrases") or []:
                if not isinstance(ph, dict) or ph.get("obj_id") != obj_id:
                    continue
                p = (ph.get("phrase") or "").strip()
                if p and p not in keep:
                    keep.append(p)
        for sent in sents:
            for ph in sent.get("phrases") or []:
                if not isinstance(ph, dict) or ph.get("obj_id") != obj_id:
                    continue
                p = (ph.get("phrase") or "").strip()
                if p and p not in avoid:
                    avoid.append(p)

        DISPLAY_N = 3
        keep = keep[:DISPLAY_N]
        n_new = max(0, DISPLAY_N - len(keep)) if keep else DISPLAY_N
        old_phrases = (old or {}).get("phrases") or []
        old_zh = (old or {}).get("zh") or []
        old_zh_map = {}
        for i, p in enumerate(old_phrases):
            if isinstance(p, str) and p.strip() and i < len(old_zh) and old_zh[i]:
                old_zh_map[p.strip()] = old_zh[i]

        def _attach_zh(phrases, model_zh=None):
            """优先复用旧中文 / 模型同次返回；缺的再批量翻译（避免 N 次串行）。"""
            model_zh = list(model_zh or [])
            out = [""] * len(phrases)
            miss_idx = []
            miss_txt = []
            for i, p in enumerate(phrases):
                if p in old_zh_map:
                    out[i] = old_zh_map[p]
                elif i < len(model_zh) and isinstance(model_zh[i], str) and model_zh[i].strip():
                    out[i] = model_zh[i].strip()
                else:
                    miss_idx.append(i)
                    miss_txt.append(p)
            if miss_txt:
                filled = translate_batch(miss_txt)
                for j, i in enumerate(miss_idx):
                    out[i] = filled[j] if j < len(filled) else ""
            return out

        if keep and n_new == 0:
            r = dict(old or {})
            r["obj_id"] = obj_id
            r["stem"] = stem
            r["phrases"] = keep
            r["zh"] = _attach_zh(keep)
            r["label"] = (old or {}).get("label") or r.get("label") or ""
            write_json(desc_path, r)
            return jsonify({
                "ok": True, "description": r, "kept": keep, "refreshed": [],
            })

        avoid_for_gen = list(dict.fromkeys(avoid + keep))
        min_phrases = n_new if keep else DISPLAY_N
        # 交互刷新：同次要中文 + 少重试，少一轮串行翻译
        r = describe_one_object(
            _root(), stem, obj_id, _client(), load_rules(),
            write=False, avoid_phrases=avoid_for_gen, min_phrases=min_phrases,
            with_zh=True, max_retries=2,
        )
        fresh = [p for p in (r.get("phrases") or []) if isinstance(p, str) and p.strip()]
        fresh_zh_all = list(r.get("zh") or [])
        keep_l = {p.lower() for p in keep}
        fresh_f, fresh_zh = [], []
        for i, p in enumerate(fresh):
            if p.lower() in keep_l:
                continue
            fresh_f.append(p)
            fresh_zh.append(fresh_zh_all[i] if i < len(fresh_zh_all) else "")
            if len(fresh_f) >= n_new:
                break
        fresh = fresh_f
        if keep:
            if len(fresh) < 1:
                raise ValueError("模型未返回可替换的新短语")
            phrases = (keep + fresh)[:DISPLAY_N]
            model_zh_aligned = ([""] * len(keep) + fresh_zh)[:len(phrases)]
        else:
            phrases = fresh[:DISPLAY_N]
            model_zh_aligned = fresh_zh[:len(phrases)]
        if len(phrases) < 1:
            raise ValueError("模型未返回有效短语")

        r["phrases"] = phrases
        r["zh"] = _attach_zh(phrases, model_zh_aligned)
        r["label"] = (old or {}).get("label") or r.get("label") or ""
        write_json(desc_path, r)
        return jsonify({
            "ok": True,
            "description": r,
            "kept": keep,
            "refreshed": fresh if keep else phrases,
        })
    except Exception as e:
        return jsonify({"error": str(e), "description": old}), 500


@app.route("/api/refresh_caption/<stem>/<int:sentence_id>", methods=["POST"])
def refresh_caption(stem, sentence_id):
    """仅刷新指定一条 caption，不重建整图。"""
    if not _root():
        return jsonify({"error": "未配置数据集"}), 400
    try:
        old, replacement = regenerate_single_caption(
            _root(), stem, sentence_id, client=_client()
        )
        replacement["zh"] = translate_text(replacement.get("caption", ""))
        old["captions"][sentence_id] = replacement
        write_json(os.path.join(draft_dir(_root()), "captions", f"{stem}.json"), old)
        return jsonify({"ok": True, "captions": old})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/delete_caption/<stem>/<int:sentence_id>", methods=["POST"])
def delete_caption(stem, sentence_id):
    if not _root():
        return jsonify({"error": "未配置数据集"}), 400
    path = os.path.join(draft_dir(_root()), "captions", f"{stem}.json")
    old = load_json(path)
    if not old:
        return jsonify({"error": "无 caption draft"}), 404
    caps = old.get("captions") or []
    if not (0 <= sentence_id < len(caps)):
        return jsonify({"error": "sentence_id 越界"}), 400
    del caps[sentence_id]
    for i, c in enumerate(caps):
        c["sentence_id"] = i
    old["captions"] = caps
    write_json(path, old)
    return jsonify({"ok": True, "captions": old})


@app.route("/api/add_caption/<stem>", methods=["POST"])
def add_caption(stem):
    """新增一条 caption，优先选尚未被已有 caption 覆盖的目标。"""
    if not _root():
        return jsonify({"error": "未配置数据集"}), 400
    try:
        old, entry = add_caption_prefer_uncovered(
            _root(), stem, client=_client()
        )
        entry["zh"] = translate_text(entry.get("caption", ""))
        caps = old.get("captions") or []
        if caps:
            caps[-1] = entry
            old["captions"] = caps
            write_json(os.path.join(draft_dir(_root()), "captions", f"{stem}.json"), old)
        return jsonify({"ok": True, "captions": old, "sentence_id": entry["sentence_id"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _strip_phrase_from_caption(caption: str, phrase: str) -> str:
    if not caption or not phrase:
        return caption or ""
    text = caption.replace(phrase, " ")
    text = " ".join(text.split())
    text = text.replace(" ,", ",").replace(" .", ".").replace(",,", ",")
    return text.strip(" ,.") + ("." if caption.rstrip().endswith(".") else "")


@app.route("/api/delete_object/<stem>/<int:obj_id>", methods=["POST"])
def delete_object(stem, obj_id):
    """删除目标框：从 objects / descriptions / 所有 caption 中移除。"""
    if not _root():
        return jsonify({"error": "未配置数据集"}), 400
    obj_path = os.path.join(draft_dir(_root()), "objects", f"{stem}.json")
    meta = load_json(obj_path)
    if not meta:
        return jsonify({"error": "无 objects 数据"}), 404

    targets = [o for o in meta.get("objects", []) if o.get("obj_id") == obj_id]
    if not targets:
        return jsonify({"error": f"obj {obj_id} 不存在"}), 404
    obj = targets[0]
    meta["objects"] = [o for o in meta["objects"] if o.get("obj_id") != obj_id]
    write_json(obj_path, meta)

    # 描述文件
    desc_path = os.path.join(
        draft_dir(_root()), "descriptions", f"{stem}_obj{obj_id:04d}.json"
    )
    if os.path.isfile(desc_path):
        try:
            os.remove(desc_path)
        except OSError:
            pass

    # crop（可选清理）
    crop_rel = obj.get("crop_path") or ""
    if crop_rel:
        crop_abs = os.path.join(_root(), crop_rel)
        if os.path.isfile(crop_abs):
            try:
                os.remove(crop_abs)
            except OSError:
                pass

    # 所有 caption 去掉该目标
    cap_path = os.path.join(draft_dir(_root()), "captions", f"{stem}.json")
    caps = load_json(cap_path, {"captions": []})
    for sent in caps.get("captions", []):
        removed = [p for p in (sent.get("phrases") or []) if p.get("obj_id") == obj_id]
        sent["obj_ids"] = [x for x in (sent.get("obj_ids") or []) if x != obj_id]
        sent["phrases"] = [p for p in (sent.get("phrases") or []) if p.get("obj_id") != obj_id]
        caption = sent.get("caption", "")
        for p in removed:
            caption = _strip_phrase_from_caption(caption, p.get("phrase", ""))
        sent["caption"] = caption
        for ph in sent.get("phrases", []):
            ph["tokens_positive"] = phrase_token_span(caption, ph.get("phrase", ""))
        # 清掉旁译，前端可再请求
        if removed:
            sent["zh"] = ""
    write_json(cap_path, caps)

    # objects.jsonl 同步删行（若存在）
    jsonl = os.path.join(draft_dir(_root()), "objects.jsonl")
    if os.path.isfile(jsonl):
        kept = []
        with open(jsonl, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    kept.append(line)
                    continue
                if row.get("stem") == stem and int(row.get("obj_id", -1)) == obj_id:
                    continue
                kept.append(line)
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))

    payload = _load_item_payload(stem)
    return jsonify({"ok": True, **payload})


@app.route("/api/translate", methods=["POST"])
def translate_api():
    data = request.json or {}
    text = data.get("text", "")
    return jsonify({"zh": translate_text(text)})


@app.route("/api/export/<stem>", methods=["POST"])
def export_one(stem):
    if not _root():
        return jsonify({"error": "未配置数据集"}), 400
    path = export_stem(_root(), stem)
    if not path:
        return jsonify({"error": "导出失败，缺少 draft"}), 400
    return jsonify({"ok": True, "scope": "current", "path": path, "count": 1})


@app.route("/api/export", methods=["POST"])
def export_api():
    """scope=current|all：导出当前文件或整个文件夹到 jsons-GD。"""
    if not _root():
        return jsonify({"error": "未配置数据集"}), 400
    data = request.json or {}
    scope = (data.get("scope") or "current").strip().lower()
    if scope == "all":
        n = export_dataset(_root())
        out_dir = os.path.join(_root(), "jsons-GD")
        return jsonify({
            "ok": True,
            "scope": "all",
            "count": int(n or 0),
            "path": out_dir,
        })
    stem = (data.get("stem") or "").strip()
    if not stem:
        return jsonify({"error": "未指定 stem"}), 400
    path = export_stem(_root(), stem)
    if not path:
        return jsonify({"error": "导出失败，缺少 draft"}), 400
    return jsonify({"ok": True, "scope": "current", "path": path, "count": 1})


#-------------#
# 浏览器关闭 → 释放本实例端口（刷新可被心跳取消）
#-------------#
_shutdown_lock = threading.Lock()
_shutdown_timer = None
_BROWSER_SHUTDOWN_DELAY = 2.5


def _exit_release_port(reason: str = ""):
    msg = "正在退出，释放端口…"
    if reason:
        msg = f"{reason}，{msg}"
    print(f"\n  {msg}", flush=True)
    os._exit(0)


def _cancel_pending_shutdown():
    global _shutdown_timer
    with _shutdown_lock:
        t = _shutdown_timer
        _shutdown_timer = None
    if t is not None:
        try:
            t.cancel()
        except Exception:
            pass


def _schedule_browser_shutdown(delay: float = _BROWSER_SHUTDOWN_DELAY):
    """关标签后短延迟退出；若期间收到心跳（刷新）则取消。"""
    global _shutdown_timer

    def _do():
        _exit_release_port("浏览器已关闭")

    with _shutdown_lock:
        if _shutdown_timer is not None:
            try:
                _shutdown_timer.cancel()
            except Exception:
                pass
        _shutdown_timer = threading.Timer(max(0.3, float(delay)), _do)
        _shutdown_timer.daemon = True
        _shutdown_timer.start()


@app.route("/api/heartbeat", methods=["GET", "POST"])
def heartbeat_api():
    """页面心跳：仅用于取消「关页预约」的 shutdown（例如刷新）。"""
    _cancel_pending_shutdown()
    return jsonify({"ok": True})


@app.route("/api/shutdown", methods=["GET", "POST"])
def shutdown_api():
    """浏览器关闭/刷新时调用；短延迟后退出，心跳可取消。"""
    delay = _BROWSER_SHUTDOWN_DELAY
    try:
        if request.is_json and isinstance(request.json, dict) and "delay" in request.json:
            delay = float(request.json.get("delay"))
        elif request.args.get("delay") is not None:
            delay = float(request.args.get("delay"))
    except Exception:
        delay = _BROWSER_SHUTDOWN_DELAY
    _schedule_browser_shutdown(delay)
    return jsonify({"ok": True, "shutdown_in": delay})


def _install_shutdown_handlers():
    """Ctrl+C / 关控制台窗口时尽快退出，便于释放端口。"""
    import signal

    def _stop(*_args):
        _exit_release_port("控制台关闭")

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _stop)
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            import ctypes

            @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
            def _console_ctrl(ctrl_type):
                # 0=C 1=BREAK 2=CLOSE 5=LOGOFF 6=SHUTDOWN
                if ctrl_type in (0, 1, 2, 5, 6):
                    _stop()
                    return 1
                return 0

            # 保持引用，避免被 GC
            app._console_ctrl_handler = _console_ctrl  # type: ignore[attr-defined]
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_ctrl, 1)
        except Exception:
            pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--dataset", default="")
    parser.add_argument(
        "--rules-scene",
        default=os.environ.get("RULES_SCENE", ""),
        help="场景规则 id（rules/describe_rules_<scene>.md）；空=通用",
    )
    args = parser.parse_args()
    state["rules_scene"] = set_rules_scene(args.rules_scene)
    if args.dataset:
        state["dataset_root"] = args.dataset
        cfg = read_draft_config(args.dataset)
        if cfg.get("jsons_dirname"):
            state["jsons_dirname"] = normalize_jsons_dirname(cfg["jsons_dirname"])
        if cfg.get("images_dirname"):
            state["images_dirname"] = normalize_images_dirname(cfg["images_dirname"])
        if cfg.get("geometry"):
            state["geometry"] = cfg["geometry"]
        if cfg.get("rules_scene") is not None and not args.rules_scene:
            state["rules_scene"] = set_rules_scene(cfg.get("rules_scene"))
    _install_shutdown_handlers()
    print(f"\n  Grounding 检查界面 → http://{args.host}:{args.port}\n")
    print(f"  rules_scene: {get_rules_scene() or 'default'}")
    print(f"  describe: {resolve_describe_rules_path()}")
    print(f"  caption:  {resolve_caption_rules_path()}")
    print("  提示: 关闭网页标签 / 启动窗口 / Ctrl+C 将自动释放本实例端口\n")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
