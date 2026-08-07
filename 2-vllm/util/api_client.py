"""
Qwen3-VL vLLM API 客户端
配合 0-start_server.sh 启动的服务，通过 OpenAI 兼容接口发送图像+问答请求
"""

import argparse
import base64
import sys
from pathlib import Path

from openai import OpenAI

# 常见图片后缀
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def encode_image_to_base64(image_path: str) -> str:
    """将本地图片编码为 base64 字符串。"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def infer_with_base64(client: OpenAI, image_path: str, prompt: str, model_name: str) -> str:
    """方式一：本地图片 base64 编码后发送，不依赖服务端文件路径。"""
    img_b64 = encode_image_to_base64(image_path)
    suffix = Path(image_path).suffix.lower()
    mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".webp": "webp"}
    mime_type = mime_map.get(suffix, "jpeg")

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/{mime_type};base64,{img_b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=512,
        temperature=0.7,
    )
    return response.choices[0].message.content or ""


def infer_with_file_url(client: OpenAI, file_url: str, prompt: str, model_name: str) -> str:
    """方式二：传 file:// URL，需服务端 --allowed-local-media-path 允许该路径。"""
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": file_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=512,
        temperature=0.7,
    )
    return response.choices[0].message.content or ""


def request(api_base: str, model_name: str, filepath: str, description: str, use_base64: bool = True) -> str:
    """
    向本地 vLLM 服务发一次图像问答请求。
    use_base64=True 用 base64 传图，False 用 file:// 传图（需服务端白名单）。
    """
    client = OpenAI(base_url=api_base, api_key="not-needed")

    if use_base64:
        return infer_with_base64(client, filepath, description, model_name)
    file_url = f"file://{filepath}" if not filepath.startswith("file://") else filepath
    return infer_with_file_url(client, file_url, description, model_name)


def parse_args():
    parser = argparse.ArgumentParser(description="Qwen3-VL vLLM API 客户端（图像+问答）")
    parser.add_argument("--filepath", type=str, default="/home/cyl/data/sample/tea.jpg", help="要测试的图片文件路径")
    parser.add_argument("--description", type=str, default="请描述这张图片", help="问答内容")
    parser.add_argument("--api-base", type=str, default="http://localhost:8081/v1", help="vLLM 服务地址")
    parser.add_argument("--model-name", type=str, default="qwen3-vl-8b", help="服务端 --served-model-name")
    parser.add_argument("--use-file-url", action="store_true", help="使用 file:// 传图（否则用 base64）")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    filepath = args.filepath
    description = args.description
    api_base = args.api_base
    model_name = args.model_name
    use_base64 = not args.use_file_url

    #-------------#
    # 检查图片路径
    #-------------#
    if not Path(filepath).is_file():
        print(f"❌ 图像路径不合法或文件不存在: {filepath}")
        sys.exit(1)
    if Path(filepath).suffix.lower() not in IMAGE_EXTENSIONS:
        print(f"❌ 不支持的图片格式: {filepath}")
        sys.exit(1)

    #-------------#
    # 发送请求
    #-------------#
    print(f"⛺ 图像路径: {filepath}")
    print(f"🔍 问题: {description}")
    print(f"🟡 服务地址: {api_base}\n")

    try:
        result = request(api_base, model_name, filepath, description, use_base64=use_base64)
        print(f"✨ 回答: {result}")
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        sys.exit(1)
