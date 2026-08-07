"""
数据集配置模块

用法：在 sh 脚本中通过 --dataset_use 传入 .yaml 文件路径（支持逗号分隔多个、%N 采样）

  datasets='data/0-Demo.yaml'                        # 单个数据集
  datasets='data/A.yaml,data/B.yaml'                 # 多数据集混合
  datasets='data/A.yaml%50,data/B.yaml'              # A 只用 50%，B 全量

yaml 文件格式：
  annotation_path: /abs/path/to/annotation.json      # 标注文件路径（必填）
  data_path:       /abs/path/to/images/              # 图像根目录（可选，供 image 字段拼绝对路径用）

annotation.json 格式（每条为一个训练样本）：
  [
    {
      "image": "001.jpg",                            # 相对于 data_path 的路径
      "conversations": [
        { "from": "human", "value": "<image>\n问题" },
        { "from": "gpt",   "value": "答案" }
      ]
    }
  ]
"""

import re
import os
import yaml


def _parse_sampling_rate(name: str) -> float:
    """从名字末尾提取 %N 采样率，如 'data/A.yaml%50' → 0.5。"""
    match = re.search(r"%(\d+)$", name)
    return int(match.group(1)) / 100.0 if match else 1.0


def data_list(dataset_names: list) -> list:
    """将数据集名字列表解析为 [{annotation_path, data_path, sampling_rate}, ...}]。"""
    configs = []
    for name in dataset_names:
        sampling_rate = _parse_sampling_rate(name)
        path = re.sub(r"%(\d+)$", "", name)   # 去掉 %N 后缀

        if not os.path.exists(path):
            raise FileNotFoundError(f"数据集配置文件不存在: {path}")

        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        configs.append({
            "annotation_path": cfg["annotation_path"],
            "data_path":       cfg.get("data_path", ""),
            "sampling_rate":   sampling_rate,
        })

    return configs
