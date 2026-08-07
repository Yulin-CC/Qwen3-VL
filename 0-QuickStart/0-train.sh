#!/bin/bash
###
 # @Author: AI产品研发组
 # @Date: 2026-02-27
 # @Description: Qwen3VL 微调脚本
###

#-------------------------------------#
# ⭐需要修改的值⭐
#-------------------------------------#
device=2,3                              # 使用的 GPU 编号，单卡填 0，多卡用逗号分隔如 0,1,2,3
#-------------------------------------------#
weight='weights/Qwen3-VL-4B-Instruct'       # 模型路径
#-------------------------------------------#
datasets='data/0-Qwen.yaml'                 # 数据集：可传 .yaml/.json/.jsonl 路径，或在 __init__.py 中注册的名字
#-------------------------------------------#
config='config/default.yaml'                # 配置文件
#-------------------------------------------#
project='Qwen3VL_2602-test'                 # 输出目录
#-------------------------------------------#
epoch=3                                     # 训练轮数
#-------------------------------------------#

#---------------#
# 切换到虚拟环境
#---------------#
source /opt/anaconda3/etc/profile.d/conda.sh
conda activate qwen
#-----------------------------------------------#

#---------------#
# READY
#---------------#
nproc=$(echo "$device" | tr ',' '\n' | wc -l)

#---------------#
# 执行训练
#---------------#
cd "$(dirname $0)/.."
output="./runs/0-train/$project"
CUDA_VISIBLE_DEVICES=$device                      \
torchrun --nproc_per_node=${nproc}                \
         --master_addr=${MASTER_ADDR:-127.0.0.1}  \
         --master_port=${MASTER_PORT:-29500}      \
         train.py                                 \
         --config ${config}                       \
         --model_name_or_path ${weight}           \
         --dataset_use ${datasets}                \
         --output_dir ${output}                   \
         --num_train_epochs ${epoch}              \

#------------------------------------------------------#
# 其余超参见 config/default.yaml
# 如需临时覆盖，直接在下方 torchrun 命令中追加对应参数即可
# 例如：--num_train_epochs 2 --learning_rate 2e-5
#------------------------------------------------------#