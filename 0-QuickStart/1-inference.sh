#!/bin/bash
###
 # @Author: AI产品研发组
 # @Date: 2026-02-12
 # @Description: Qwen3VL 推理脚本，支持文件夹，图像和视频推理
###

#-----------------#
# ⭐需要修改的值⭐
#-----------------#
device=0                                             # GPU
#----------------------------------------------------#
weight='weights/Qwen3-VL-4B-Instruct'                # 模型权重文件路径
#----------------------------------------------------#
filepath="/home/yulin/0-data/0-public/sample/tea.jpg"             # 要测试的图片文件路径
#----------------------------------------------------#
description="图中的茶叶是什么品种？"                     # 问答
#----------------------------------------------------#


#---------------#
# 切换到虚拟环境
#---------------#
source /home/ubuntu/miniconda3/etc/profile.d/conda.sh   # 虚拟环境切换实例化 (本地服务器的 annaconda 所在的位置)
conda activate qwen                            # 换到 qwen 虚拟环境 (实际的虚拟环境的路径)
#---------------------------------------------------------------------------------------------------------#

#---------------#
# 执行推理
#---------------#
cd "$(dirname $0)/.."
python inference.py --device $device                    \
                    --weight $weight                    \
                    --filepath $filepath                \
                    --description $description          \