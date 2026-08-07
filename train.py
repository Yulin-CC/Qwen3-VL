# Adopted from https://github.com/lm-sys/FastChat. Below is the original copyright:
# Adopted from tatsu-lab@stanford_alpaca. Below is the original copyright:
#    Copyright 2023 Rohan Taori, Ishaan Gulrajani, Tianyi Zhang, Yann Dubois, Xuechen Li
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Qwen VL 系列模型微调训练入口
支持 Qwen2-VL / Qwen2.5-VL / Qwen3-VL（密集版 & MoE 版）
支持 LoRA 微调 和 全量/部分参数微调两种模式
"""

import os
import logging
import pathlib
import torch
import transformers
import sys
import yaml
from pathlib import Path

# 将 qwen-vl-finetune 加入模块搜索路径
finetune_root = Path(__file__).parent / "Qwen" / "qwen-vl-finetune"
sys.path.insert(0, str(finetune_root))

from qwenvl.train.trainer import replace_qwen2_vl_attention_class

from transformers import (
    Qwen2VLForConditionalGeneration,
    Qwen2_5_VLForConditionalGeneration,
    Qwen3VLForConditionalGeneration,
    Qwen3VLMoeForConditionalGeneration
)
from qwenvl.data.data_processor import make_supervised_data_module
from qwenvl.train.argument import (
    ModelArguments,
    DataArguments,
    TrainingArguments,
)
from transformers import AutoProcessor, Trainer

local_rank = None  # 当前进程在分布式训练中的 rank，由 training_args 初始化


def rank0_print(*args):
    # 仅 rank 0 进程打印，避免多卡训练时日志重复输出
    if local_rank == 0:
        print(*args)


def safe_save_model_for_hf_trainer(trainer: transformers.Trainer, output_dir: str):
    """安全保存模型权重到磁盘。
    - DeepSpeed 模式：同步 CUDA 后直接调用 save_model
    - 普通模式：先将 state_dict 搬到 CPU，再落盘，避免 GPU OOM
    """

    if trainer.deepspeed:
        torch.cuda.synchronize()
        trainer.save_model(output_dir)
        return

    state_dict = trainer.model.state_dict()
    if trainer.args.should_save:
        cpu_state_dict = {key: value.cpu() for key, value in state_dict.items()}
        del state_dict  # 立即释放 GPU 显存
        trainer._save(output_dir, state_dict=cpu_state_dict)  # noqa


def set_model(model_args, model):
    """按照三个开关参数，精细控制各模块是否参与训练（全量/部分微调时使用）。

    tune_mm_vision : 视觉编码器 (ViT)
    tune_mm_mlp    : 视觉-语言连接层 (MLP Projector / merger)
    tune_mm_llm    : 语言模型主干 + lm_head
    """

    #------------------------------#
    # 视觉编码器 (ViT) 是否解冻
    #------------------------------#
    if model_args.tune_mm_vision:
        for n, p in model.visual.named_parameters():
            p.requires_grad = True
    else:
        for n, p in model.visual.named_parameters():
            p.requires_grad = False

    #------------------------------#
    # MLP Projector (merger) 是否解冻
    #------------------------------#
    if model_args.tune_mm_mlp:
        for n, p in model.visual.merger.named_parameters():
            p.requires_grad = True
    else:
        for n, p in model.visual.merger.named_parameters():
            p.requires_grad = False

    #------------------------------#
    # 语言模型主干 是否解冻
    #------------------------------#
    if model_args.tune_mm_llm:
        for n, p in model.language_model.named_parameters():
            p.requires_grad = True
        model.lm_head.requires_grad = True
    else:
        for n, p in model.language_model.named_parameters():
            p.requires_grad = False
        model.lm_head.requires_grad = False


def train(model_args, data_args, training_args, attn_implementation="flash_attention_2"):
    global local_rank

    local_rank = training_args.local_rank
    os.makedirs(training_args.output_dir, exist_ok=True)

    #-----------------------------#
    # 加载模型（按路径名自动识别版本）
    # qwen3 + "a" → MoE 版（如 30A3B）
    # qwen3       → 密集版
    # qwen2.5     → Qwen2.5-VL
    # 其他        → Qwen2-VL
    #-----------------------------#
    if "qwen3" in model_args.model_name_or_path.lower() and "a" in Path(model_args.model_name_or_path.rstrip("/")).name.lower():
        model = Qwen3VLMoeForConditionalGeneration.from_pretrained(
            model_args.model_name_or_path,
            cache_dir=training_args.cache_dir,
            attn_implementation=attn_implementation,
            dtype=(torch.bfloat16 if training_args.bf16 else None),
        )
        data_args.model_type = "qwen3vl"
    elif "qwen3" in model_args.model_name_or_path.lower():
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            model_args.model_name_or_path,
            cache_dir=training_args.cache_dir,
            attn_implementation=attn_implementation,
            dtype=(torch.bfloat16 if training_args.bf16 else None),
        )
        data_args.model_type = "qwen3vl"
    elif "qwen2.5" in model_args.model_name_or_path.lower():
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_args.model_name_or_path,
            cache_dir=training_args.cache_dir,
            attn_implementation=attn_implementation,
            dtype=(torch.bfloat16 if training_args.bf16 else None),
        )
        data_args.model_type = "qwen2.5vl"
    else:
        model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_args.model_name_or_path,
            cache_dir=training_args.cache_dir,
            attn_implementation=attn_implementation,
            dtype=(torch.bfloat16 if training_args.bf16 else None),
        )
        data_args.model_type = "qwen2vl"

    print(f'the initlized model is {model_args.model_name_or_path} the class is {model.__class__.__name__}')

    # 加载多模态处理器（含图像预处理配置）
    processor = AutoProcessor.from_pretrained(model_args.model_name_or_path)

    # 数据展平 / 序列打包时，替换 Attention 实现以支持变长序列高效计算
    if data_args.data_flatten or data_args.data_packing:
        replace_qwen2_vl_attention_class()
    model.config.use_cache = False  # 训练阶段关闭 KV Cache

    #-----------------------------#
    # 梯度检查点（用时间换显存）
    #-----------------------------#
    if training_args.gradient_checkpointing:
        if hasattr(model, "enable_input_require_grads"):
            model.enable_input_require_grads()
        else:
            # 对不支持该接口的模型，通过 forward hook 确保输入 embedding 保留梯度
            def make_inputs_require_grad(module, input, output):
                output.requires_grad_(True)

            model.get_input_embeddings().register_forward_hook(make_inputs_require_grad)

    # 加载 tokenizer，padding 统一向右对齐
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        model_args.model_name_or_path,
        cache_dir=training_args.cache_dir,
        model_max_length=training_args.model_max_length,
        padding_side="right",
        use_fast=False,
    )

    #-----------------------------#
    # 参数冻结策略：LoRA 或 全量/部分微调
    #-----------------------------#
    if training_args.lora_enable:
        from peft import LoraConfig, get_peft_model, TaskType
        print("LoRA enabled")

        # 先冻结全部参数，再由 LoRA 插入可训练的低秩矩阵
        for p in model.parameters():
            p.requires_grad = False

        lora_config = LoraConfig(
            r=training_args.lora_r or 64,                  # 低秩矩阵的秩
            lora_alpha=training_args.lora_alpha or 128,     # 缩放系数
            lora_dropout=training_args.lora_dropout or 0.05,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],  # Attention 的四个线性层
            bias="none",
            task_type=TaskType.CAUSAL_LM,
        )
        model = get_peft_model(model, lora_config)
    else:
        # 根据 tune_mm_* 开关按模块解冻，支持灵活的部分微调
        set_model(model_args, model)

        if torch.distributed.get_rank() == 0:
            model.visual.print_trainable_parameters()
            model.model.print_trainable_parameters()

    #-----------------------------#
    # 构建数据集 & 启动训练
    #-----------------------------#
    data_module = make_supervised_data_module(processor, data_args=data_args)
    trainer = Trainer(model=model, processing_class=tokenizer, args=training_args, **data_module)

    # 检测是否存在断点，自动续训
    if list(pathlib.Path(training_args.output_dir).glob("checkpoint-*")):
        logging.info("checkpoint found, resume training")
        trainer.train(resume_from_checkpoint=True)
    else:
        trainer.train()
    trainer.save_state()

    model.config.use_cache = True  # 恢复 KV Cache，方便后续推理

    #-----------------------------#
    # 保存模型权重 & 处理器配置
    #-----------------------------#
    safe_save_model_for_hf_trainer(trainer=trainer, output_dir=training_args.output_dir)
    processor.save_pretrained(training_args.output_dir)  # 保存图像预处理配置，推理时需要


def _inject_yaml_defaults():
    """读取 --config yaml 文件，将其中的参数作为默认值注入 sys.argv。
    命令行中已显式指定的同名参数不会被覆盖（命令行优先级更高）。
    --config 本身会在注入完成后从 sys.argv 中移除，避免 HfArgumentParser 报错。
    """
    argv = sys.argv[1:]

    #--------------------------#
    # 定位 --config 参数的值
    #--------------------------#
    config_path = None
    config_indices = []
    for i, arg in enumerate(argv):
        if arg == "--config" and i + 1 < len(argv):
            config_path = argv[i + 1]
            config_indices = [i, i + 1]   # --config 和紧随的路径都要移除
            break
        elif arg.startswith("--config="):
            config_path = arg.split("=", 1)[1]
            config_indices = [i]
            break

    if config_path is None:
        return  # 未传 --config，不做任何处理

    #--------------------------#
    # 加载 yaml 默认值
    #--------------------------#
    with open(config_path, "r", encoding="utf-8") as f:
        defaults = yaml.safe_load(f) or {}

    # 从 argv 中移除 --config 及其路径（HfArgumentParser 不认识这个参数）
    clean_argv = [arg for i, arg in enumerate(argv) if i not in config_indices]

    # 收集命令行中已经显式指定的参数 key，这些不会被 yaml 覆盖
    cli_keys = {arg.lstrip("-").split("=")[0] for arg in clean_argv if arg.startswith("--")}

    #--------------------------#
    # 将 yaml 中缺失的参数追加到 sys.argv 前端
    # （命令行参数在后，HfArgumentParser 取最后一个值，所以命令行始终优先）
    #--------------------------#
    extra = []
    for key, val in defaults.items():
        if key in cli_keys:
            continue  # 命令行已指定，跳过
        if isinstance(val, bool):
            extra += [f"--{key}", "True" if val else "False"]
        else:
            extra += [f"--{key}", str(val)]

    sys.argv = sys.argv[:1] + extra + clean_argv


def parse_args():
    """注入 yaml 默认值后，再用 HfArgumentParser 解析命令行参数。"""
    _inject_yaml_defaults()
    parser = transformers.HfArgumentParser((ModelArguments, DataArguments, TrainingArguments))
    return parser.parse_args_into_dataclasses()


if __name__ == "__main__":
    model_args, data_args, training_args = parse_args()
    # train(model_args, data_args, training_args)
    # flash_attention_2 需要 glibc>=2.32，系统不满足时改用 sdpa（PyTorch 内置，无额外依赖）
    train(model_args, data_args, training_args, attn_implementation="sdpa")
