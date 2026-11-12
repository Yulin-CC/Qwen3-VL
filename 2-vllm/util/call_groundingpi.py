"""
# @Author: AI产品研发组
# @Date: 2026-11-06
# @Description: 其它机器调用本机 GroundingPI（OpenAI 兼容 /v1）。仅标准库。
# @Command: python call_groundingpi.py
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import sys
from urllib import error, request

#-----------------#
# ⭐需要修改的值⭐
#-----------------#
image = r""                                                    # 本地图片路径（Windows 可用 r"D:\pic.jpg"）
#----------------------------------------------------#
prompt = "Locate all the instances that match the following categories: car</c>truck</c>bus</c>van</c>construction vehicle."
#----------------------------------------------------#
base_url = "http://<ip>:8082/v1"                     # GroundingPI 外网
#----------------------------------------------------#
model_name = "groundingpi"                                     # 对外模型名
#----------------------------------------------------#
timeout = 120                                                  # 秒
#----------------------------------------------------#
max_tokens = 2048
#----------------------------------------------------#
print_raw = False                                              # True=额外打印模型原文
#----------------------------------------------------#
probe_only = False                                             # True=只探测 /models，不推理
#--------------------------------------------------------------------------------------#

REF_RE = re.compile(
    r"<\|object_ref_start\|>(.*?)<\|object_ref_end\|>\s*<\|box_start\|>(.*?)<\|box_end\|>",
    re.S,
)
COORD_RE = re.compile(r"<(\d{1,4})>")


def encode_data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def probe(base_url: str, timeout: float = 8.0) -> bool:
    url = base_url.rstrip("/") + "/models"
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        names = [x.get("id") for x in (body.get("data") or [])]
        print(f"[ok] {url}  models={names}")
        return True
    except Exception as e:
        print(f"[FAIL] {url}: {e}")
        return False


def chat(base_url: str, model: str, image: str, prompt: str, timeout: int, max_tokens: int) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": encode_data_url(image)}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "skip_special_tokens": False,
        "spaces_between_special_tokens": False,
    }
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except error.URLError as e:
        raise SystemExit(f"请求失败 {url}: {e}") from e
    msg = body["choices"][0]["message"]
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise SystemExit(f"空 content: {msg!r}")
    return content


def parse_boxes(raw: str, width: int | None = None, height: int | None = None) -> list[dict]:
    """GAM 坐标 token → 0–999 网格框；若给了宽高则再给 pixel xyxy。"""
    out = []
    for m in REF_RE.finditer(raw):
        label = (m.group(1) or "").strip()
        inner = (m.group(2) or "").strip()
        if not label or inner.lower() == "none":
            continue
        for g in [x.strip() for x in inner.split(",") if x.strip()]:
            nums = [int(x) for x in COORD_RE.findall(g)]
            if len(nums) < 4:
                continue
            x1, y1, x2, y2 = nums[:4]
            rec = {"label": label, "grid": [x1, y1, x2, y2]}
            if width and height:
                rec["xyxy"] = [
                    int(round(x1 / 999.0 * (width - 1))),
                    int(round(y1 / 999.0 * (height - 1))),
                    int(round(x2 / 999.0 * (width - 1))),
                    int(round(y2 / 999.0 * (height - 1))),
                ]
            out.append(rec)
    return out


def image_size(path: str) -> tuple[int, int] | None:
    try:
        import struct
        with open(path, "rb") as f:
            head = f.read(32)
        if head.startswith(b"\x89PNG"):
            w, h = struct.unpack(">II", head[16:24])
            return int(w), int(h)
        if head[:2] == b"\xff\xd8":
            with open(path, "rb") as f:
                f.read(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2:
                        break
                    if marker[0] != 0xFF:
                        break
                    if marker[1] in (0xC0, 0xC1, 0xC2):
                        f.read(3)
                        h, w = struct.unpack(">HH", f.read(4))
                        return int(w), int(h)
                    length = struct.unpack(">H", f.read(2))[0]
                    f.read(max(0, length - 2))
    except Exception:
        return None
    return None


def main() -> int:
    if probe_only or not str(image).strip():
        ok = probe(base_url)
        if probe_only or not str(image).strip():
            return 0 if ok else 1

    if not os.path.isfile(image):
        raise SystemExit(f"找不到图片: {image}")

    raw = chat(base_url, model_name, image, prompt, timeout, max_tokens)
    size = image_size(image)
    boxes = parse_boxes(raw, *(size or (None, None)))
    result = {
        "base_url": base_url,
        "model": model_name,
        "image": os.path.abspath(image),
        "size": {"width": size[0], "height": size[1]} if size else None,
        "n": len(boxes),
        "boxes": boxes,
    }
    if print_raw:
        result["raw"] = raw
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
