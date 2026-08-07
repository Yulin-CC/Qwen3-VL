"""
Qwen3-VL 图像推理脚本
支持单文件、文件夹、图像和视频推理
"""

from ntpath import isfile
import os
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

# 常见文件后缀
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}

def build_messages(description, file_path):
    #--------------------------#
    # 检查图像路径：单文件 or 目录
    #--------------------------#
    if os.path.isfile(file_path) and os.path.splitext(file_path)[1].lower() in IMAGE_EXTENSIONS:
        message_mode = "single_image"
    elif os.path.isfile(file_path) and os.path.splitext(file_path)[1].lower() in VIDEO_EXTENSIONS:
        message_mode = "single_video"
    elif os.path.isdir(file_path):
        message_mode = "multiple_images"
    else:
        raise ValueError(f"❌ 图像路径不合法: {file_path}")

    # 单图
    if message_mode == "single_image":
        content = [
            {"type": "image", "image": file_path},
            {"type": "text", "text": description},
        ]
    elif message_mode == "single_video":
        content = [
            {"type": "video", "video": file_path},
            {"type": "text", "text": description},
        ]
    else:
        # 多图：目录下按文件名排序的图片依次加入
        files = [
            f for f in os.listdir(file_path)
            if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
        ]
        files.sort()
        if not files:
            raise ValueError(f"❌ 目录下没有图片文件: {file_path}")
        content = []
        for f in files:
            full_path = os.path.join(file_path, f)
            content.append({"type": "image", "image": full_path})
        content.append({"type": "text", "text": description})

    # 创建输入信息
    messages = [{"role": "user", "content": content}]

    return messages


def inference(weight, file_path, description, device="auto"):

    #-------------#
    # 加载模型 
    #-------------#
    print(f"🟡 正在加载模型: {weight}")
    device_map = f"cuda:{device}" if str(device).isdigit() else device
    model = AutoModelForImageTextToText.from_pretrained(weight, dtype="auto", device_map=device_map, trust_remote_code=True)
    processor = AutoProcessor.from_pretrained(weight, trust_remote_code=True)
    print("✅ 模型加载完成！\n")

    #-------------#
    # 输入信息 
    #-------------#
    messages = build_messages(description, file_path)
    print(f"⛺ 图像路径: {file_path}")
    print(f"🔍 问题: {messages[0]['content'][-1]['text']}\n")

    #-------------#
    # 加载信息
    #-------------#
    inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt")
    inputs = inputs.to(model.device)

    # 生成回复
    print("正在生成回复...")
    generated_ids = model.generate(**inputs, max_new_tokens=256)
    generated_ids_trimmed = [out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)]
    output_text = processor.batch_decode(generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)

    print(f"✨ 回答: {output_text[0]}")



from argparse import ArgumentParser
def parse_args():

    parser = ArgumentParser(description='MMDetection Unified Inference (Image/Video)')

    parser.add_argument('--device', type=str, default='1', help='GPU device to use')
    parser.add_argument('--weight', type=str, default='weights/Qwen3-VL-4B-Instruct', help='Model weight path')
    parser.add_argument('--filepath', type=str, default='', help='File/folder path')
    parser.add_argument('--description', type=str, default='请描述这张图片', help='Question')

    return parser.parse_args()

if __name__ == "__main__":

    args = parse_args()

    #------------#
    # 配置参数
    #----------------------------#
    device = args.device         # GPU 编号，或 "auto"、"cpu"
    #----------------------------#
    weight_path = args.weight    # 模型路径
    file_path = args.filepath    # 文件/文件夹路径
    #----------------------------#
    # 问题
    #----------------------------#
    description = args.description
    #-----------------------------#

    # 图像推理
    inference(weight_path, file_path, description, device)

