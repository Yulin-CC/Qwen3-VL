#!/usr/bin/env python3
"""
Annotations 转 train.jsonl 工具（按 PCI 子文件夹批量）

功能：
1. 遍历 base_path 下所有以 PCI 为前缀的子文件夹（如 PCI-demo），每个子文件夹含 images + annotations
2. 在每个子文件夹内从其 annotations 生成该目录下的 train.jsonl
3. 汇总所有子文件夹的记录，在 base_path 根目录生成一份合并的 train.jsonl（图片路径带子文件夹名，如 PCI-demo/images/xxx.png）
"""

import json
import re
import yaml
from pathlib import Path

# ================================================================================================
# 配置参数区域 - 修改下面的参数即可
# ================================================================================================

def get_config():
    """获取配置参数 - 修改这里即可"""
    # 修改 ------------------------------------------------------------------------------------------------------------------#
    #---------------------------------------------#
    # 负责人
    #---------------------------------------------#
    incharge = "yulin"                            # 负责人
    #---------------------------------------------#
    project = "Qwen"                              # 项目名称
    model_vision = "Qwen3V-test-v1.0"             # 模型版本
    #---------------------------------------------#
    Vision_Instruction = "[无人机] Qwen 测试"       # 该版本数据更新说明
    #---------------------------------------------#
    base_path = "/data/yulin/data/z-qwen/"        # 数据路径
    #---------------------------------------------#
    subdir_prefix = "PCI"                         # 子文件夹前缀（仅处理以此前缀开头的子文件夹）
    #---------------------------------------------#
    data_ratio = 1.0                              # 数据读取比例
    #------------------------------------------------------------------------------------#
    
    return {
        "incharge": incharge,
        "project": project,
        "model_vision": model_vision,
        "Vision_Instruction": Vision_Instruction,
        "base_path": base_path,
        "subdir_prefix": subdir_prefix,
        "data_ratio": data_ratio,
    }


def normalize_conversations_image(conversations):
    """多轮对话中仅在首轮 human 保留 <image>，后续 human 轮移除 <image>，避免占位符多于图片数。"""
    out = []
    first_human = True
    for t in conversations:
        if t.get("from") == "human":
            if first_human:
                out.append(t)
                first_human = False
            else:
                v = re.sub(r"\n*<image>\n*", "\n", t["value"]).strip()
                out.append({"from": t["from"], "value": v})
        else:
            out.append(t)
    return out


def build_records_from_annotations(annotations_dir):
    """从 annotations 目录读取所有 .json，按图片合并对话，返回记录列表（id 从 1 起）"""
    annotations_dir = Path(annotations_dir)
    json_files = sorted(annotations_dir.glob("*.json"))
    merged_records = []
    for json_path in json_files:
        with open(json_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        if not items:
            continue
        image = items[0]["image"]
        conversations = []
        for item in items:
            conversations.extend(item["conversations"])
        conversations = normalize_conversations_image(conversations)
        merged_records.append({
            "id": len(merged_records) + 1,
            "image": image,
            "conversations": conversations,
        })
    return merged_records


def write_jsonl(path, records):
    """将记录列表按行写入 jsonl 文件"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    config = get_config()
    base_path = Path(config["base_path"])
    prefix = config["subdir_prefix"]

    if not base_path.is_dir():
        raise FileNotFoundError(f"根目录不存在: {base_path}")

    # 仅处理以 prefix 开头的子文件夹
    subdirs = sorted([d for d in base_path.iterdir() if d.is_dir() and d.name.startswith(prefix)])
    if not subdirs:
        print(f"在 {base_path} 下未找到以 '{prefix}' 开头的子文件夹")
        return

    all_records = []

    # ==================== 遍历每个 PCI 子文件夹 ====================
    for subdir in subdirs:
        annotations_dir = subdir / "annotations"
        if not annotations_dir.is_dir():
            print(f"跳过（无 annotations）: {subdir.name}")
            continue

        records = build_records_from_annotations(annotations_dir)
        if not records:
            print(f"跳过（无有效标注）: {subdir.name}")
            continue

        # 1. 子文件夹下生成 train.jsonl（图片路径保持相对该子文件夹）
        subdir_jsonl = subdir / "train.jsonl"
        write_jsonl(subdir_jsonl, records)
        print(f"已写入 {len(records)} 条 -> {subdir_jsonl}")

        # 2. 汇总到总表：图片路径加上子文件夹名前缀，便于根目录训练时定位
        for r in records:
            all_records.append({
                "id": 0,  # 稍后统一重排
                "image": f"{subdir.name}/{r['image']}",
                "conversations": r["conversations"],
            })

    # ==================== 根目录写入合并的 train.jsonl ====================
    for i, rec in enumerate(all_records, start=1):
        rec["id"] = i
    root_jsonl = base_path / f"{config['project']}_train.jsonl"
    write_jsonl(root_jsonl, all_records)
    print(f"✅ 生成训练数据集：{root_jsonl}")

    # ==================== 生成 data/0-Demo.yaml（训练用数据集配置） ====================
    yaml_path = Path(__file__).resolve().parent / f"0-{config['project']}.yaml"
    yaml_data = {
        "incharge": config["incharge"],
        "model_vision": config["model_vision"],
        "data_path": str(base_path).rstrip("/"),
        "annotation_path": str(base_path / f"{config['project']}_train.jsonl"),
        "vision_instruction": config["Vision_Instruction"],
    }
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"✅ 已生成数据集配置：{yaml_path}")


if __name__ == "__main__":
    main()
