#!/bin/bash
###
 # @Author: AI产品研发组
 # @Date: 2026-02-12
 # @Description: Qwen3VL vLLM API 请求脚本，需先运行 0-start_server.sh 启动服务
###

#-----------------#
# ⭐需要修改的值⭐
#-----------------#
#----------------------------------------------------#
filepath="/home/yulin/0-data/0-public/sample/tea.jpg"             # 要测试的图片文件路径
#----------------------------------------------------#
description="请描述一下图像"                     # 问答
#----------------------------------------------------#


#---------------#
# 切换到虚拟环境
#---------------#
source /home/ubuntu/miniconda3/etc/profile.d/conda.sh   # 虚拟环境切换实例化 (本地服务器的 anaconda 所在的位置)
conda activate qwen                                     # 换到 qwen 虚拟环境
#---------------------------------------------------------------------------------------------------------#

#---------------#
# 发送 API 请求
#---------------#
cd "$(dirname $0)/.."
python 2-vllm/util/api_client.py --filepath "$filepath"   \
                                 --description "$description"
