"""
# @Author: AI产品研发组
# @Date: 2026-08-07
# @Description: 场景 rules 解析与加载（describe_rules[_scene].md / caption_rules[_scene].md）
#
# 切换场景无需改代码：
#   - 环境变量 RULES_SCENE=vesthalmet
#   - CLI --rules-scene vesthalmet
#   - 审阅界面下拉 / draft config rules_scene
#   - 新场景：在 rules/ 新增成对 md 即可被自动发现
"""

import os
import re
from pathlib import Path
from typing import List, Optional


RULES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rules")

_active_scene = os.environ.get("RULES_SCENE", "").strip()


def normalize_scene(scene: Optional[str]) -> str:
    s = (scene or "").strip().lower()
    if s in {"", "default", "base", "general", "none"}:
        return ""
    s = s.replace("\\", "/").split("/")[-1]
    if s.endswith(".md"):
        s = s[:-3]
    for prefix in ("describe_rules_", "caption_rules_", "describe_rules", "caption_rules"):
        if s.startswith(prefix) and prefix.endswith("_"):
            s = s[len(prefix) :]
            break
        if s in {"describe_rules", "caption_rules"}:
            return ""
    s = re.sub(r"[^a-z0-9_\-]+", "", s)
    return s


def get_rules_scene() -> str:
    return normalize_scene(_active_scene)


def set_rules_scene(scene: Optional[str]) -> str:
    global _active_scene
    _active_scene = normalize_scene(scene)
    os.environ["RULES_SCENE"] = _active_scene
    return _active_scene


def describe_rules_filename(scene: Optional[str] = None) -> str:
    sc = normalize_scene(scene) if scene is not None else get_rules_scene()
    return f"describe_rules_{sc}.md" if sc else "describe_rules.md"


def caption_rules_filename(scene: Optional[str] = None) -> str:
    sc = normalize_scene(scene) if scene is not None else get_rules_scene()
    return f"caption_rules_{sc}.md" if sc else "caption_rules.md"


def describe_rules_path(scene: Optional[str] = None) -> str:
    return os.path.join(RULES_DIR, describe_rules_filename(scene))


def caption_rules_path(scene: Optional[str] = None) -> str:
    return os.path.join(RULES_DIR, caption_rules_filename(scene))


def _resolve_existing(preferred: str, fallback: str) -> str:
    if preferred and os.path.isfile(preferred):
        return preferred
    if os.path.isfile(fallback):
        return fallback
    return preferred or fallback


def resolve_describe_rules_path(scene: Optional[str] = None) -> str:
    sc = normalize_scene(scene) if scene is not None else get_rules_scene()
    preferred = describe_rules_path(sc)
    fallback = describe_rules_path("")
    return _resolve_existing(preferred, fallback)


def resolve_caption_rules_path(scene: Optional[str] = None) -> str:
    sc = normalize_scene(scene) if scene is not None else get_rules_scene()
    preferred = caption_rules_path(sc)
    fallback = caption_rules_path("")
    return _resolve_existing(preferred, fallback)


def load_describe_rules(scene: Optional[str] = None) -> str:
    path = resolve_describe_rules_path(scene)
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_caption_rules_text(scene: Optional[str] = None) -> str:
    path = resolve_caption_rules_path(scene)
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def list_rule_scenes() -> List[dict]:
    """
    扫描 rules/ 下成对/单侧场景文件。
    返回 [{id, label, describe, caption, describe_ok, caption_ok}, ...]
    首项 id="" 为通用默认。
    """
    root = Path(RULES_DIR)
    scenes = {
        "": {
            "id": "",
            "label": "通用 (default)",
            "describe": describe_rules_filename(""),
            "caption": caption_rules_filename(""),
            "describe_ok": (root / describe_rules_filename("")).is_file(),
            "caption_ok": (root / caption_rules_filename("")).is_file(),
        }
    }
    if root.is_dir():
        for p in sorted(root.glob("describe_rules_*.md")):
            sc = normalize_scene(p.name)
            if not sc:
                continue
            cap = root / caption_rules_filename(sc)
            scenes[sc] = {
                "id": sc,
                "label": sc,
                "describe": p.name,
                "caption": cap.name,
                "describe_ok": True,
                "caption_ok": cap.is_file(),
            }
        for p in sorted(root.glob("caption_rules_*.md")):
            sc = normalize_scene(p.name)
            if not sc or sc in scenes:
                continue
            desc = root / describe_rules_filename(sc)
            scenes[sc] = {
                "id": sc,
                "label": sc,
                "describe": desc.name,
                "caption": p.name,
                "describe_ok": desc.is_file(),
                "caption_ok": True,
            }
    # 通用置顶
    out = [scenes.pop("")]
    out.extend(scenes[k] for k in sorted(scenes.keys()))
    return out
