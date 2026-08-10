"""
# @Author: AI产品研发组
# @Date: 2026-08-05
# @Description: 3x3 覆盖 + 随机锚点邻域 + 全局随机 生成 >=5 条 caption
# @Command: python util/caption.py --dataset /path/to/rm
"""

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from tqdm import tqdm

from common import bbox_center, draft_dir, ensure_dir, phrase_token_span, write_json
from rules_io import load_caption_rules_text, set_rules_scene
from vllm_client import VLLMClient, extract_json_object


def load_caption_rules(scene: str = None) -> str:
    """加载当前/指定场景的 caption_rules*.md（见 rules_io）。"""
    return load_caption_rules_text(scene)


#-------------#
# 网格
#-------------#
def grid_cell(cx, cy, width, height, grid=3):
    gx = min(grid - 1, max(0, int(cx / max(width, 1) * grid)))
    gy = min(grid - 1, max(0, int(cy / max(height, 1) * grid)))
    return gy * grid + gx


def load_desc_map(dataset_root, stem):
    ddir = os.path.join(draft_dir(dataset_root), "descriptions")
    mapping = {}
    for p in Path(ddir).glob(f"{stem}_obj*.json"):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        mapping[int(data["obj_id"])] = data
    return mapping


def nearest_group(objects, anchor_idx, k):
    anchor = objects[anchor_idx]
    acx, acy = bbox_center(anchor["bbox_xyxy"])
    scored = []
    for i, obj in enumerate(objects):
        if i == anchor_idx:
            continue
        cx, cy = bbox_center(obj["bbox_xyxy"])
        dist = math.hypot(cx - acx, cy - acy)
        scored.append((dist, i))
    scored.sort()
    ids = [objects[anchor_idx]["obj_id"]] + [objects[i]["obj_id"] for _, i in scored[: max(0, k - 1)]]
    return ids


def set_overlap(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def pick_groups(objects, width, height, n_captions=5, grid=3, seed=None):
    """Return list of {obj_ids, strategy, grid_cell}."""
    rng = random.Random(seed)
    n = len(objects)
    if n == 0:
        return []

    # index by cell
    cells = {i: [] for i in range(grid * grid)}
    for i, obj in enumerate(objects):
        cx, cy = bbox_center(obj["bbox_xyxy"])
        cells[grid_cell(cx, cy, width, height, grid)].append(i)
    non_empty = [c for c, idxs in cells.items() if idxs]

    groups = []
    used_cells = []

    # ~1 global random
    n_global = 1 if n_captions >= 2 and n >= 3 else 0
    n_local = n_captions - n_global

    for gi in range(n_local):
        # prefer unused cells
        candidates = [c for c in non_empty if c not in used_cells] or non_empty or [None]
        cell = rng.choice(candidates) if candidates[0] is not None else None
        if cell is not None:
            anchor_idx = rng.choice(cells[cell])
            used_cells.append(cell)
        else:
            anchor_idx = rng.randrange(n)
        k = rng.randint(3, min(10, n)) if n >= 3 else n
        obj_ids = nearest_group(objects, anchor_idx, k)
        groups.append({
            "obj_ids": obj_ids,
            "strategy": "anchor_neighbor",
            "grid_cell": cell if cell is not None else -1,
        })

    for _ in range(n_global):
        k = rng.randint(3, min(10, n)) if n >= 3 else n
        obj_ids = [o["obj_id"] for o in rng.sample(objects, k)]
        groups.append({
            "obj_ids": obj_ids,
            "strategy": "global_random",
            "grid_cell": -1,
        })

    # dedupe by overlap
    unique = []
    for g in groups:
        if any(set_overlap(g["obj_ids"], u["obj_ids"]) > 0.7 for u in unique):
            # resample once
            if g["strategy"] == "global_random":
                k = min(len(g["obj_ids"]), n)
                g = {
                    "obj_ids": [o["obj_id"] for o in rng.sample(objects, k)],
                    "strategy": "global_random",
                    "grid_cell": -1,
                }
            else:
                anchor_idx = rng.randrange(n)
                k = len(g["obj_ids"])
                g = {
                    "obj_ids": nearest_group(objects, anchor_idx, k),
                    "strategy": "anchor_neighbor",
                    "grid_cell": g.get("grid_cell", -1),
                }
        if any(set_overlap(g["obj_ids"], u["obj_ids"]) > 0.7 for u in unique):
            continue
        unique.append(g)

    # pad if too few after dedupe
    attempts = 0
    while len(unique) < n_captions and n > 0 and attempts < 40:
        attempts += 1
        anchor_idx = rng.randrange(n)
        k = rng.randint(1, min(10, n))
        g = {
            "obj_ids": nearest_group(objects, anchor_idx, k),
            "strategy": "anchor_neighbor",
            "grid_cell": -1,
        }
        if any(set_overlap(g["obj_ids"], u["obj_ids"]) > 0.85 for u in unique):
            # 配额不足时放宽去重，避免死循环
            if attempts >= 20 or n <= 3:
                unique.append(g)
            continue
        unique.append(g)

    # 仍不足则复制变体补齐（目标极少时）
    while len(unique) < max(n_captions, 5) and unique:
        g = dict(unique[len(unique) % len(unique)])
        g = {
            "obj_ids": list(g["obj_ids"]),
            "strategy": g.get("strategy", "anchor_neighbor"),
            "grid_cell": g.get("grid_cell", -1),
        }
        unique.append(g)

    return unique[: max(n_captions, 5)] if n_captions >= 5 else unique[:n_captions]


def _is_weak_phrase(phrase: str, label: str) -> bool:
    p = (phrase or "").strip().lower()
    lab = (label or "").strip().lower()
    if not p:
        return True
    weak = {lab, f"{lab} object", f"{lab} in the scene", "object", "in the scene"}
    return p in weak


def used_phrases_by_obj(captions, exclude_sentence_id=None):
    """统计各 caption 已选用短语：obj_id -> set(phrase)。可排除某一条 caption。"""
    out = {}
    for i, c in enumerate(captions or []):
        if exclude_sentence_id is not None and i == exclude_sentence_id:
            continue
        for ph in c.get("phrases") or []:
            if not isinstance(ph, dict):
                continue
            oid = ph.get("obj_id")
            phrase = (ph.get("phrase") or "").strip()
            if oid is None or not phrase:
                continue
            out.setdefault(int(oid), set()).add(phrase)
    return out


def pick_phrases_for_group(objects, desc_map, obj_ids, rng, avoid_by_obj=None):
    """从目标描述 phrases 中抽样；优先避开 label/object 占位词与其它 caption 已用短语。"""
    id2obj = {o["obj_id"]: o for o in objects}
    avoid_by_obj = avoid_by_obj or {}
    phrases = []
    for oid in obj_ids:
        obj = id2obj[oid]
        desc = desc_map.get(oid, {})
        opts = [x for x in (desc.get("phrases") or []) if isinstance(x, str) and x.strip()]
        strong = [x for x in opts if not _is_weak_phrase(x, obj["label"])]
        pool = strong or opts or [obj["label"]]
        avoid = avoid_by_obj.get(int(oid)) or set()
        if avoid:
            fresh = [x for x in pool if x not in avoid]
            if fresh:
                pool = fresh
        # 偏好稍长、信息更多的短语
        pool = sorted(pool, key=lambda s: (-len(s.split()), -len(s)))
        top = pool[: max(1, min(3, len(pool)))]
        phrases.append({
            "obj_id": oid,
            "phrase": rng.choice(top),
            "label": obj["label"],
        })
    return phrases


def _format_phrases_for_prompt(phrases):
    """按 obj_id 分组列出短语，便于模型识别「同目标多描述」。"""
    from collections import OrderedDict

    groups = OrderedDict()
    for p in phrases:
        oid = p.get("obj_id")
        key = int(oid) if oid is not None else -1
        groups.setdefault(key, []).append((p.get("phrase") or "").strip())

    n_objs = len(groups)
    lines = [
        "Phrases (tagged by obj_id):",
        "- SAME obj_id = ONE entity (different wordings). Do NOT split with near/beside/next to.",
        "- DIFFERENT obj_id = DIFFERENT entities. Do NOT merge with is/is a/is also/who is also.",
        f"- This caption has {n_objs} distinct obj_id(s).",
    ]
    for oid, phs in groups.items():
        tag = f"obj {oid}" if oid >= 0 else "obj ?"
        if len(phs) == 1:
            lines.append(f"- [{tag}] {phs[0]}")
        else:
            lines.append(f"- [{tag}] (ONE entity; {len(phs)} phrases):")
            for ph in phs:
                lines.append(f"    - {ph}")
    return "\n".join(lines)


def build_caption_with_llm(client: VLLMClient, phrases, rules=None, vary_structure=False):
    """
    用 LLM 把给定短语拼成一句 caption。
    vary_structure=True（刷新）：短语锁定，只改句式组合。
    """
    rules = load_caption_rules() if rules is None else rules
    locked = (
        "You MUST include EVERY phrase below EXACTLY (same spelling/spacing).\n"
        "Do NOT replace/omit/paraphrase any phrase.\n"
        "Do NOT add grounding referents that are not in the list.\n"
        "SAME obj_id → ONE entity (never split with near/beside/next to/stands near).\n"
        "DIFFERENT obj_id → DISTINCT entities (never merge with is/is a/is also/"
        "who is also/known as; use near/and/with between them instead).\n"
    )
    if vary_structure:
        task = (
            "Rewrite ONE natural English grounding caption by changing ONLY the "
            "sentence structure / word order / connectives around the locked phrases.\n"
        )
    else:
        task = "Compose ONE natural English grounding caption from the locked phrases.\n"
    parts = []
    if rules:
        parts.append(rules)
        parts.append("")
    parts.append(task + locked)
    parts.append('Return JSON only: {"caption": "..."}\n')
    parts.append(_format_phrases_for_prompt(phrases))
    prompt = "\n".join(parts)
    raw = client.text(
        prompt,
        system=(
            "Output JSON only. Keep every given phrase verbatim. "
            "Same obj_id = one entity; different obj_id = different entities "
            "(never say A is also B across obj_ids)."
        ),
        temperature=0.55 if vary_structure else 0.5,
        max_tokens=256,
    )
    data = extract_json_object(raw)
    caption = (data.get("caption") or "").strip()
    return caption


def template_caption(phrases):
    """Fallback without LLM: join phrases into a simple sentence."""
    if not phrases:
        return ""
    from collections import OrderedDict

    groups = OrderedDict()
    for p in phrases:
        oid = p.get("obj_id")
        key = int(oid) if oid is not None else id(p)
        groups.setdefault(key, []).append((p.get("phrase") or "").strip())

    chunks = []
    for phs in groups.values():
        phs = [x for x in phs if x]
        if not phs:
            continue
        if len(phs) == 1:
            chunks.append(phs[0])
        elif len(phs) == 2:
            chunks.append(f"{phs[0]}, a {phs[1]}")
        else:
            chunks.append(f"{phs[0]}, a {', a '.join(phs[1:-1])}, with a {phs[-1]}")

    if not chunks:
        return ""
    if len(chunks) == 1:
        return f"There is a {chunks[0]} in the scene."
    if len(chunks) == 2:
        return f"A {chunks[0]} is near a {chunks[1]}."
    head, *mid, tail = chunks
    mid_s = ", ".join(mid)
    return f"A {head}, {mid_s}, and a {tail} are in the scene."


def ensure_phrases_in_caption(caption, phrases):
    """If some phrases missing, append them; recompute spans."""
    missing = [p["phrase"] for p in phrases if p["phrase"] not in caption]
    if missing:
        caption = caption.rstrip(". ") + ", with " + ", ".join(missing) + "."
    spans = []
    for p in phrases:
        span = phrase_token_span(caption, p["phrase"])
        spans.append({"obj_id": p["obj_id"], "phrase": p["phrase"], "tokens_positive": span})
    return caption, spans


def locked_phrases_from_entry(sent, objects):
    """取出 caption 中用户已选短语（刷新时优先锁定，不重抽）。"""
    id2label = {o["obj_id"]: o.get("label", "object") for o in objects}
    valid = set(id2label)
    out = []
    seen = set()
    for ph in sent.get("phrases") or []:
        oid = ph.get("obj_id")
        phrase = (ph.get("phrase") or "").strip()
        if oid is None or oid not in valid or not phrase:
            continue
        key = (int(oid), phrase)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "obj_id": int(oid),
            "phrase": phrase,
            "label": id2label[oid],
        })
    return out


def build_one_caption_entry(objects, desc_map, obj_ids, strategy, grid_cell,
                            sentence_id, client=None, rng=None,
                            fixed_phrases=None, vary_structure=False,
                            keep_obj_ids=None, avoid_by_obj=None):
    """仅为指定 obj_ids / 锁定短语生成一条 caption。

    keep_obj_ids: 刷新时保留的关联目标列表。不得因「未选用短语」而丢掉目标
    （取消选用 ≠ 删除目标；删除只能走 delete_object）。
    avoid_by_obj: 其它 caption 已用短语，抽样时尽量避开。
    """
    rng = rng or random.Random()
    # 过滤已删除的目标
    valid_ids = {o["obj_id"] for o in objects}
    if fixed_phrases is not None:
        phrases = [
            p for p in fixed_phrases
            if p.get("obj_id") in valid_ids and (p.get("phrase") or "").strip()
        ]
        # 关联目标：优先保留调用方传入的 keep/obj_ids，再并上短语所属目标
        base_ids = list(keep_obj_ids if keep_obj_ids is not None else (obj_ids or []))
        merged = []
        for oid in list(base_ids) + [p["obj_id"] for p in phrases]:
            if oid in valid_ids and oid not in merged:
                merged.append(oid)
        obj_ids = merged
        # 允许 phrases 为空：表示用户清空了选用，但仍保留关联目标
        if not phrases:
            return {
                "sentence_id": sentence_id,
                "caption": "",
                "obj_ids": list(obj_ids),
                "strategy": strategy or "refresh",
                "grid_cell": grid_cell,
                "phrases": [],
                "zh": "",
            }
    else:
        obj_ids = [oid for oid in (obj_ids or []) if oid in valid_ids]
        if not obj_ids:
            return None
        phrases = pick_phrases_for_group(
            objects, desc_map, obj_ids, rng, avoid_by_obj=avoid_by_obj,
        )
        if not phrases:
            return None
    if client is not None:
        try:
            cap = build_caption_with_llm(
                client, phrases, vary_structure=vary_structure,
            )
        except Exception:
            cap = template_caption(phrases)
    else:
        cap = template_caption(phrases)
    cap, spans = ensure_phrases_in_caption(cap, phrases)
    return {
        "sentence_id": sentence_id,
        "caption": cap,
        "obj_ids": list(obj_ids),
        "strategy": strategy or "refresh",
        "grid_cell": grid_cell,
        "phrases": spans,
        "zh": "",
    }


def regenerate_single_caption(dataset_root, stem, sentence_id, client=None, seed=None):
    """只重写 captions[sentence_id]：保留用户已选短语，仅重组句式。"""
    obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    out_path = os.path.join(draft_dir(dataset_root), "captions", f"{stem}.json")
    with open(obj_path, encoding="utf-8") as f:
        meta = json.load(f)
    if not os.path.isfile(out_path):
        raise FileNotFoundError(f"无 caption draft: {stem}")
    with open(out_path, encoding="utf-8") as f:
        old = json.load(f)
    caps = old.get("captions") or []
    if not (0 <= sentence_id < len(caps)):
        raise IndexError(f"sentence_id 越界: {sentence_id}")
    sent = caps[sentence_id]
    objects = meta["objects"]
    desc_map = load_desc_map(dataset_root, stem)
    rng = random.Random(seed if seed is not None else random.randint(0, 10**9))
    locked = locked_phrases_from_entry(sent, objects)
    raw_phrases = sent.get("phrases")
    keep_ids = list(sent.get("obj_ids") or [])
    # 用户显式清空选用（phrases=[]）：禁止重抽；caption 必须为空
    if isinstance(raw_phrases, list) and len(raw_phrases) == 0:
        replacement = dict(sent)
        replacement["phrases"] = []
        replacement["caption"] = ""
        replacement["zh"] = ""
        replacement["obj_ids"] = keep_ids
        replacement["sentence_id"] = sentence_id
    elif locked:
        replacement = build_one_caption_entry(
            objects, desc_map,
            obj_ids=keep_ids,
            strategy=sent.get("strategy") or "refresh",
            grid_cell=sent.get("grid_cell"),
            sentence_id=sentence_id,
            client=client,
            rng=rng,
            fixed_phrases=locked,
            vary_structure=True,
            keep_obj_ids=keep_ids,
        )
    else:
        # 旧数据无 phrases 字段时，才按 obj_ids 重抽（避开其它 caption 已用短语）
        avoid = used_phrases_by_obj(caps, exclude_sentence_id=sentence_id)
        replacement = build_one_caption_entry(
            objects, desc_map,
            obj_ids=keep_ids,
            strategy=sent.get("strategy"),
            grid_cell=sent.get("grid_cell"),
            sentence_id=sentence_id,
            client=client,
            rng=rng,
            vary_structure=True,
            keep_obj_ids=keep_ids,
            avoid_by_obj=avoid,
        )
    if replacement is None:
        raise ValueError("该 caption 无有效目标，无法刷新")
    # 硬保留关联目标：刷新不得因未选用短语而丢掉目标
    merged_ids = []
    for oid in list(keep_ids) + list(replacement.get("obj_ids") or []):
        if oid not in merged_ids:
            merged_ids.append(oid)
    replacement["obj_ids"] = merged_ids
    caps[sentence_id] = replacement
    # 重排 sentence_id
    for i, c in enumerate(caps):
        c["sentence_id"] = i
    old["captions"] = caps
    write_json(out_path, old)
    return old, replacement


def covered_obj_ids(captions):
    covered = set()
    for c in captions or []:
        covered.update(c.get("obj_ids") or [])
    return covered


def pick_group_prefer_uncovered(objects, existing_caps, rng=None):
    """新增 caption：优先选尚未出现在已有 caption 中的目标。"""
    rng = rng or random.Random()
    n = len(objects)
    if n == 0:
        return None
    covered = covered_obj_ids(existing_caps)
    uncovered = [o for o in objects if o["obj_id"] not in covered]
    id2idx = {o["obj_id"]: i for i, o in enumerate(objects)}
    k = rng.randint(3, min(10, n)) if n >= 3 else n

    if uncovered:
        unc_idxs = [id2idx[o["obj_id"]] for o in uncovered]
        anchor_idx = rng.choice(unc_idxs)
        neighbors = nearest_group(objects, anchor_idx, min(k, n))
        unc_set = {o["obj_id"] for o in uncovered}
        # 未覆盖目标优先，再补邻域
        chosen = [oid for oid in neighbors if oid in unc_set]
        for oid in neighbors:
            if oid not in chosen:
                chosen.append(oid)
            if len(chosen) >= k:
                break
        for o in uncovered:
            if o["obj_id"] not in chosen:
                chosen.append(o["obj_id"])
            if len(chosen) >= k:
                break
        # 仍不足则从全图补
        for o in objects:
            if o["obj_id"] not in chosen:
                chosen.append(o["obj_id"])
            if len(chosen) >= k:
                break
        return {
            "obj_ids": chosen[:k],
            "strategy": "uncovered_prefer",
            "grid_cell": -1,
        }

    # 全部已覆盖：优先低频目标
    freq = {}
    for c in existing_caps or []:
        for oid in c.get("obj_ids") or []:
            freq[oid] = freq.get(oid, 0) + 1
    ranked = sorted(
        objects,
        key=lambda o: (freq.get(o["obj_id"], 0), rng.random()),
    )
    anchor_idx = id2idx[ranked[0]["obj_id"]]
    return {
        "obj_ids": nearest_group(objects, anchor_idx, k),
        "strategy": "low_freq",
        "grid_cell": -1,
    }


def add_caption_prefer_uncovered(dataset_root, stem, client=None, seed=None):
    """追加一条 caption，优先覆盖初始 5 条之外尚未出现的目标。"""
    obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    out_path = os.path.join(draft_dir(dataset_root), "captions", f"{stem}.json")
    with open(obj_path, encoding="utf-8") as f:
        meta = json.load(f)
    if os.path.isfile(out_path):
        with open(out_path, encoding="utf-8") as f:
            old = json.load(f)
    else:
        old = {
            "stem": stem,
            "image": meta["image"],
            "width": meta["width"],
            "height": meta["height"],
            "captions": [],
        }
    objects = meta["objects"]
    if not objects:
        raise ValueError("无可用目标")
    caps = old.get("captions") or []
    rng = random.Random(seed if seed is not None else random.randint(0, 10**9))
    g = pick_group_prefer_uncovered(objects, caps, rng=rng)
    if not g:
        raise ValueError("无法采样目标组")
    desc_map = load_desc_map(dataset_root, stem)
    avoid = used_phrases_by_obj(caps)
    entry = build_one_caption_entry(
        objects, desc_map, g["obj_ids"], g["strategy"], g["grid_cell"],
        sentence_id=len(caps), client=client, rng=rng,
        avoid_by_obj=avoid,
    )
    if entry is None:
        raise ValueError("生成 caption 失败")
    caps.append(entry)
    for i, c in enumerate(caps):
        c["sentence_id"] = i
    old["captions"] = caps
    write_json(out_path, old)
    return old, entry


def caption_one_image(dataset_root, stem, client=None, n_captions=5, seed=None, force=False):
    obj_path = os.path.join(draft_dir(dataset_root), "objects", f"{stem}.json")
    out_path = os.path.join(draft_dir(dataset_root), "captions", f"{stem}.json")
    if os.path.isfile(out_path) and not force:
        with open(out_path, encoding="utf-8") as f:
            return json.load(f)

    with open(obj_path, encoding="utf-8") as f:
        meta = json.load(f)
    objects = meta["objects"]
    desc_map = load_desc_map(dataset_root, stem)
    rng = random.Random(seed if seed is not None else hash(stem) & 0xFFFFFFFF)

    groups = pick_groups(
        objects, meta["width"], meta["height"],
        n_captions=max(5, n_captions), seed=rng.randint(0, 10**9),
    )

    captions = []
    for i, g in enumerate(groups):
        avoid = used_phrases_by_obj(captions)
        entry = build_one_caption_entry(
            objects, desc_map, g["obj_ids"], g["strategy"], g["grid_cell"],
            sentence_id=i, client=client, rng=rng,
            avoid_by_obj=avoid,
        )
        if entry:
            captions.append(entry)

    result = {
        "stem": stem,
        "image": meta["image"],
        "width": meta["width"],
        "height": meta["height"],
        "captions": captions,
    }
    write_json(out_path, result)
    return result


def captions_need_rebuild(dataset_root, stem) -> bool:
    """若描述已是 vllm，但 caption 仍大量使用占位短语，则需重建。"""
    cap_path = os.path.join(draft_dir(dataset_root), "captions", f"{stem}.json")
    if not os.path.isfile(cap_path):
        return True
    with open(cap_path, encoding="utf-8") as f:
        caps = json.load(f)
    desc_map = load_desc_map(dataset_root, stem)
    if not any((d or {}).get("source") == "vllm" for d in desc_map.values()):
        return False
    weak_hits, total = 0, 0
    for sent in caps.get("captions", []):
        for ph in sent.get("phrases", []):
            total += 1
            oid = ph.get("obj_id")
            label = (desc_map.get(oid) or {}).get("label") or ""
            if _is_weak_phrase(ph.get("phrase", ""), label):
                weak_hits += 1
    if total == 0:
        return True
    return (weak_hits / total) >= 0.4


def caption_dataset(dataset_root, base_url, model, n_captions=5, limit=None,
                    force=False, no_llm=False, progress_cb=None):
    """
    progress_cb: optional callable(done, total, detail) 用于 UI 实时百分比。
    """
    obj_dir = os.path.join(draft_dir(dataset_root), "objects")
    stems = sorted(Path(p).stem for p in Path(obj_dir).glob("*.json"))
    if limit:
        stems = stems[:limit]
    client = None if no_llm else VLLMClient(
        base_url=base_url, model=model, enable_thinking=False
    )
    ensure_dir(os.path.join(draft_dir(dataset_root), "captions"))
    n_rebuild = 0
    total = len(stems)
    if progress_cb:
        progress_cb(0, max(total, 1), f"0/{total}")
    for i, stem in enumerate(tqdm(stems, desc="caption"), start=1):
        do_force = force or (not no_llm and captions_need_rebuild(dataset_root, stem))
        if do_force and not force:
            n_rebuild += 1
        caption_one_image(
            dataset_root, stem, client=client,
            n_captions=n_captions, force=do_force,
        )
        if progress_cb:
            progress_cb(i, total, f"{i}/{total}")
    print(f"caption 完成: {len(stems)} 图" + (f"（自动重建 {n_rebuild}）" if n_rebuild else ""))
    if progress_cb and total:
        progress_cb(total, total, f"{total}/{total}")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True)
    p.add_argument("--base_url", default="http://127.0.0.1:8081/v1")
    p.add_argument("--model", default="qwen3.6-35b-a3b")
    p.add_argument("--n_captions", type=int, default=5)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--no_llm", action="store_true", help="仅用模板拼句（调试）")
    p.add_argument(
        "--rules-scene",
        default=os.environ.get("RULES_SCENE", ""),
        help="场景规则 id，对应 rules/caption_rules_<scene>.md；空=通用",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    set_rules_scene(args.rules_scene)
    caption_dataset(
        args.dataset, args.base_url, args.model,
        n_captions=args.n_captions, limit=args.limit,
        force=args.force, no_llm=args.no_llm,
    )
