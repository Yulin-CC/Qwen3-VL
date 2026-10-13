"""
# @Author: AI产品研发组
# @Date: 2026-09-12
# @Description: 对齐官方 qwen-vl-utils 的视觉预处理与生成
# @Command: 由 0-QuickStart/scripts/inference.py 调用
"""

import json
import os
from pathlib import Path

from qwen_vl_utils import process_vision_info


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}


#-------------#
# 创建输入信息
#-------------#
def build_messages(description, file_path, min_pixels=None, max_pixels=None, video_fps=None):
    if os.path.isfile(file_path) and os.path.splitext(file_path)[1].lower() in IMAGE_EXTENSIONS:
        media = {"type": "image", "image": file_path}
        _apply_pixels(media, min_pixels, max_pixels)
        content = [media, {"type": "text", "text": description}]
    elif os.path.isfile(file_path) and os.path.splitext(file_path)[1].lower() in VIDEO_EXTENSIONS:
        media = {"type": "video", "video": file_path}
        _apply_pixels(media, min_pixels, max_pixels)
        if video_fps is not None:
            media["fps"] = video_fps
        content = [media, {"type": "text", "text": description}]
    elif os.path.isdir(file_path):
        files = sorted(
            f for f in os.listdir(file_path)
            if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
        )
        if not files:
            raise ValueError(f"目录下没有图片文件: {file_path}")
        content = []
        for name in files:
            media = {"type": "image", "image": os.path.join(file_path, name)}
            _apply_pixels(media, min_pixels, max_pixels)
            content.append(media)
        content.append({"type": "text", "text": description})
    else:
        raise ValueError(f"图像路径不合法: {file_path}")

    return [{"role": "user", "content": content}]


def _apply_pixels(media, min_pixels, max_pixels):
    if min_pixels is not None:
        media["min_pixels"] = min_pixels
    if max_pixels is not None:
        media["max_pixels"] = max_pixels


#-------------#
# 官方预处理
#-------------#
def prepare_inputs(processor, messages, image_patch_size=16, return_video_metadata=True):
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    images, videos, video_kwargs = process_vision_info(
        messages,
        image_patch_size=image_patch_size,
        return_video_kwargs=True,
        return_video_metadata=return_video_metadata,
    )

    video_metadatas = None
    if videos is not None and return_video_metadata:
        videos, video_metadatas = zip(*videos)
        videos, video_metadatas = list(videos), list(video_metadatas)

    kwargs = dict(
        text=text,
        images=images,
        videos=videos,
        do_resize=False,
        return_tensors="pt",
        **(video_kwargs or {}),
    )
    if video_metadatas is not None:
        kwargs["video_metadata"] = video_metadatas
    return processor(**kwargs)


#-------------#
# 生成回复
#-------------#
def generate_reply(model, processor, inputs, max_new_tokens=256):
    inputs = inputs.to(model.device)
    generated_ids = model.generate(**inputs, max_new_tokens=max_new_tokens)
    generated_ids_trimmed = [
        out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    return output_text[0]


#-------------#
# 保存结果
#-------------#
def save_result(output_dir, file_path, description, answer):
    if not output_dir:
        return None
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(file_path).name if os.path.isdir(file_path) else Path(file_path).stem
    dest = out / f"{stem}.json"
    dest.write_text(
        json.dumps(
            {"filepath": file_path, "description": description, "answer": answer},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return str(dest)
