"""
# @Author: AI产品研发组
# @Date: 2026-09-12
# @Description: Qwen3-VL 推理入口，预处理走官方 qwen-vl-utils
# @Command: bash 0-QuickStart/1-inference.sh
"""

import sys
from argparse import ArgumentParser
from pathlib import Path

import yaml
from transformers import AutoModelForImageTextToText, AutoProcessor

QS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = QS_DIR.parent
sys.path.insert(0, str(QS_DIR))

from utils.inference_utils import build_messages, generate_reply, prepare_inputs, save_result


#-------------#
# 读取 yaml
#-------------#
def load_predict_defaults(config_path):
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    predict = cfg.get("predict")
    return predict if isinstance(predict, dict) else {}


#-------------#
# 参数
#-------------#
def parse_args():
    pre = ArgumentParser(add_help=False)
    pre.add_argument("--config", type=str, default="config/default.yaml")
    pre_args, _ = pre.parse_known_args()
    defaults = load_predict_defaults(pre_args.config)

    parser = ArgumentParser(description="Qwen3-VL Inference (Image/Video)")
    parser.add_argument("--config", type=str, default="config/default.yaml")
    parser.add_argument("--device", type=str, default="0")
    parser.add_argument("--weight", type=str, default="weights/Qwen3-VL-4B-Instruct")
    parser.add_argument("--filepath", type=str, default="")
    parser.add_argument("--description", type=str, default="请描述这张图片")
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--image_patch_size", type=int, default=defaults.get("image_patch_size", 16))
    parser.add_argument("--min_pixels", type=int, default=defaults.get("min_pixels", 784))
    parser.add_argument("--max_pixels", type=int, default=defaults.get("max_pixels", 50176))
    parser.add_argument("--max_new_tokens", type=int, default=defaults.get("max_new_tokens", 256))
    parser.add_argument("--video_fps", type=float, default=defaults.get("video_fps", 2.0))
    parser.add_argument(
        "--return_video_metadata",
        type=lambda x: str(x).lower() not in ("0", "false", "no"),
        default=defaults.get("return_video_metadata", True),
    )
    return parser.parse_args()


#-------------#
# 推理
#-------------#
def inference(args):
    #-------------#
    # 加载模型
    #-------------#
    print(f"正在加载模型: {args.weight}")
    device_map = f"cuda:{args.device}" if str(args.device).isdigit() else args.device
    model = AutoModelForImageTextToText.from_pretrained(
        args.weight, dtype="auto", device_map=device_map, trust_remote_code=True
    )
    processor = AutoProcessor.from_pretrained(args.weight, trust_remote_code=True)
    print("模型加载完成\n")

    #-------------#
    # 官方预处理
    #-------------#
    messages = build_messages(
        args.description, args.filepath, args.min_pixels, args.max_pixels, args.video_fps
    )
    print(f"输入路径: {args.filepath}")
    print(f"问题: {args.description}\n")
    inputs = prepare_inputs(
        processor, messages, args.image_patch_size, args.return_video_metadata
    )

    #-------------#
    # 生成
    #-------------#
    print("正在生成回复...")
    answer = generate_reply(model, processor, inputs, args.max_new_tokens)
    print(f"回答: {answer}")
    dest = save_result(args.output, args.filepath, args.description, answer)
    if dest:
        print(f"已写入: {dest}")


if __name__ == "__main__":
    inference(parse_args())
