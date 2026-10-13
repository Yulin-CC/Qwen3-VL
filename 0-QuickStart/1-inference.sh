#!/bin/bash
###
 # @Author: AI产品研发组
 # @Date: 2026-02-12
 # @LastEditTime: 2026-09-12
 # @Description: Qwen3-VL 推理脚本（官方 qwen-vl-utils 预处理）
###
WORK_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "$WORK_DIR/.." && pwd)

#--------------------------------------#
# 需要修改的值
#--------------------------------------#
devices=0                                            # GPU 设备 ID
#--------------------------------------#
project="Qwen3VL_2602-test"                          # 权重保存文件夹名（与训练时一致）
#--------------------------------------#
weights="/home/ubuntu/models/Qwen3.8-27B"            # 预训练权重完整路径
#--------------------------------------#
dataset="/home/yulin/0-data/0-public/sample/tea.jpg" # 测试输入（单张图片/视频/目录）
#--------------------------------------#
description="图中的茶叶是什么品种？"                    # 问答
#--------------------------------------#
config="config/default.yaml"                         # 推理超参在 predict: 段
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
# 运行推理程序
#---------------#
cd "$ROOT_DIR"

# 固定路径（无需修改，cd 后判断确保相对路径正确）
# 单文件输入 → <文件所在目录>/repro/
# 目录输入   → <目录>/repro/
if [ -f "$dataset" ]; then
    output="$(dirname "$dataset")/repro/"
elif [ -d "$dataset" ]; then
    output="$dataset/repro"
else
    echo "Error: dataset not found: $dataset"
    exit 1
fi

mkdir -p "$output"
python 0-QuickStart/scripts/inference.py \
  --config "$config" \
  --device "$devices" \
  --weight "$weights" \
  --filepath "$dataset" \
  --description "$description" \
  --output "$output"
