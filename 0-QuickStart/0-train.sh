#!/bin/bash
###
 # @Author: AI产品研发组
 # @Date: 2026-02-27
 # @LastEditTime: 2026-09-12
 # @Description: Qwen3-VL 微调脚本（官方 flash-attn + DeepSpeed ZeRO）
###
WORK_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "$WORK_DIR/.." && pwd)

#--------------------------------------#
# 需要修改的值
#--------------------------------------#
devices=2,3                            # GPU 设备 ID，多卡用逗号分隔
#--------------------------------------#
project="Qwen3VL_2602-test"            # 权重保存文件夹名 → ./runs/0-train/$project
#--------------------------------------#
weights="weights/Qwen3-VL-4B-Instruct" # 预训练权重路径
#--------------------------------------#
dataset="data/0-Qwen.yaml"             # 数据集 yaml / json / jsonl
#--------------------------------------#
config="config/default.yaml"           # 默认超参（CLI 覆盖 yaml）
#--------------------------------------#
deepspeed="Qwen/qwen-vl-finetune/scripts/zero3.json"  # 官方 4B 用 zero3；MoE 改 zero2.json；留空则不开
#--------------------------------------#
epochs=3                               # 训练轮数
#--------------------------------------#


#---------------#
# 切换到虚拟环境（conda 路径因机器而异，clone 后请修改 CONDA_BASE）
#   常见：$HOME/miniconda3 | $HOME/anaconda3 | /opt/conda | /opt/anaconda3
#   查找：dirname "$(dirname "$(which conda)")"
#   环境名须与 README 环境搭建中 conda create -n 一致
#---------------#
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate qwen


#---------------#
# 运行训练程序
#---------------#
cd "$ROOT_DIR"

# 固定路径（无需修改）
output="./runs/0-train/$project"
nproc=$(echo "$devices" | tr ',' '\n' | wc -l)

mkdir -p "$output"
ds_args=()
if [ -n "$deepspeed" ]; then
    ds_args+=(--deepspeed "$deepspeed")
fi

CUDA_VISIBLE_DEVICES=$devices \
torchrun --nproc_per_node=${nproc} \
         --master_addr=${MASTER_ADDR:-127.0.0.1} \
         --master_port=${MASTER_PORT:-29500} \
         0-QuickStart/scripts/train.py \
         --config ${config} \
         --model_name_or_path ${weights} \
         --dataset_use ${dataset} \
         --output_dir ${output} \
         --num_train_epochs ${epochs} \
         "${ds_args[@]}"

# 其余超参见 config/default.yaml
# 装不上 flash-attn：yaml 里 attn_implementation=sdpa，data_flatten=false
# 临时覆盖可在上方 torchrun 后追加，例如：--learning_rate 2e-5 --attn_implementation sdpa
