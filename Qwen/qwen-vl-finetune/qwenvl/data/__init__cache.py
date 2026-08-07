"""
数据集配置与注册模块

支持三种方式指定训练数据集（通过 sh 脚本的 --dataset_use 参数传入）：

─────────────────────────────────────────────────────────────
方式一：直接传 .yaml 配置文件路径（推荐）
─────────────────────────────────────────────────────────────
  datasets='data/0-Demo.yaml'

  yaml 文件格式：
      annotation_path: /abs/path/to/annotation.json   # 标注文件（必填）
      data_path:       /abs/path/to/images/           # 图像根目录（可选）

  annotation.json 里 image 字段写相对于 data_path 的路径：
      [{"image": "001.jpg", "conversations": [...]}]

─────────────────────────────────────────────────────────────
方式二：直接传 .json / .jsonl 标注文件路径
─────────────────────────────────────────────────────────────
  datasets='/abs/path/to/annotation.json'

  无需 yaml，data_path 留空，要求 json 里 image 字段写绝对路径：
      [{"image": "/abs/path/to/images/001.jpg", "conversations": [...]}]

─────────────────────────────────────────────────────────────
方式三：在下方 data_dict 中注册名字后使用（适合公共/复用数据集）
─────────────────────────────────────────────────────────────
  datasets='my_dataset'

  注册方式（在本文件 data_dict 中新增一行）：
      MY_DATASET = {
          "annotation_path": "/abs/path/to/annotation.json",
          "data_path":       "/abs/path/to/images/",
      }
      data_dict = { ..., "my_dataset": MY_DATASET }

─────────────────────────────────────────────────────────────
多数据集混合 & 采样率
─────────────────────────────────────────────────────────────
  多数据集混合（逗号分隔）：
      datasets='data/A.yaml,data/B.yaml'

  按比例采样（%后接整数，表示百分比，三种方式均支持）：
      datasets='data/A.yaml%50,data/B.yaml'              # A 只用 50%，B 全量
      datasets='/abs/annotation.json%30,data/B.yaml%80'  # 方式二也支持
      datasets='cambrian_737k%20'                        # 方式三也支持
─────────────────────────────────────────────────────────────
"""

import re
import yaml
import os

# Define placeholders for dataset paths
CAMBRIAN_737K = {
    "annotation_path": "PATH_TO_CAMBRIAN_737K_ANNOTATION",
    "data_path": "",
}

CAMBRIAN_737K_PACK = {
    "annotation_path": f"PATH_TO_CAMBRIAN_737K_ANNOTATION_PACKED",
    "data_path": f"",
}

MP_DOC = {
    "annotation_path": "PATH_TO_MP_DOC_ANNOTATION",
    "data_path": "PATH_TO_MP_DOC_DATA",
}

CLEVR_MC = {
    "annotation_path": "PATH_TO_CLEVR_MC_ANNOTATION",
    "data_path": "PATH_TO_CLEVR_MC_DATA",
}

VIDEOCHATGPT = {
    "annotation_path": "PATH_TO_VIDEOCHATGPT_ANNOTATION",
    "data_path": "PATH_TO_VIDEOCHATGPT_DATA",
}

data_dict = {
    "cambrian_737k": CAMBRIAN_737K,
    "cambrian_737k_pack": CAMBRIAN_737K_PACK,
    "mp_doc": MP_DOC,
    "clevr_mc": CLEVR_MC,
    "videochatgpt": VIDEOCHATGPT,
}


def parse_sampling_rate(dataset_name):
    match = re.search(r"%(\d+)$", dataset_name)
    if match:
        return int(match.group(1)) / 100.0
    return 1.0


def data_list(dataset_names):
    config_list = []
    for dataset_name in dataset_names:
        sampling_rate = parse_sampling_rate(dataset_name)
        dataset_name = re.sub(r"%(\d+)$", "", dataset_name)

        # 直接传 yaml 文件路径时，从文件中读取 annotation_path 和 data_path
        if dataset_name.endswith(".yaml") or dataset_name.endswith(".yml"):
            if not os.path.exists(dataset_name):
                raise FileNotFoundError(f"数据集配置文件不存在: {dataset_name}")
            with open(dataset_name, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            config = {
                "annotation_path": cfg["annotation_path"],
                "data_path":       cfg.get("data_path", ""),
                "sampling_rate":   sampling_rate,
            }
            config_list.append(config)

        # 直接传 json/jsonl 标注文件路径时，data_path 留空（json 里用绝对路径）
        elif dataset_name.endswith(".json") or dataset_name.endswith(".jsonl"):
            if not os.path.exists(dataset_name):
                raise FileNotFoundError(f"标注文件不存在: {dataset_name}")
            config = {
                "annotation_path": dataset_name,
                "data_path":       "",
                "sampling_rate":   sampling_rate,
            }
            config_list.append(config)

        # 原有逻辑：在 data_dict 里按名字查找
        elif dataset_name in data_dict.keys():
            config = data_dict[dataset_name].copy()
            config["sampling_rate"] = sampling_rate
            config_list.append(config)

        else:
            raise ValueError(
                f"找不到数据集 '{dataset_name}'。\n"
                f"请在 qwenvl/data/__init__.py 中注册，或直接传入 .yaml / .json / .jsonl 文件路径。"
            )
    return config_list


if __name__ == "__main__":
    dataset_names = ["cambrian_737k"]
    configs = data_list(dataset_names)
    for config in configs:
        print(config)
