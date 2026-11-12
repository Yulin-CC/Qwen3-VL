#!/bin/bash
###
 # @Author: AI产品研发组
 # @Date: 2026-11-06
 # @Description: vLLM OpenAI 兼容 API 服务启动脚本 — GroundingPI (4.84B 视觉 Grounding)
 # @Docs: https://www.modelscope.cn/models/GroundingPI/GroundingPI
 #        https://github.com/groundingpi/GroundingPI
###

#-----------------#
# ⭐需要修改的值⭐
#-----------------#
gpu_ids="0"                                            # 官方 TP=1；4B BF16 约 10GB，单卡 4090 足够
#----------------------------------------------------#
weight='/path/to/models/GroundingPI'               # 模型权重路径
#----------------------------------------------------#
port=8082                                              # 服务端口（避开 8081 上的 Qwen）
#----------------------------------------------------#
model_name="groundingpi"                               # 对外暴露的模型名（官方默认 ID）
#----------------------------------------------------#
max_model_len=16384                                    # 官方默认：含图像 + 提示 + 输出
#----------------------------------------------------#
gpu_memory_utilization=0.70                            # 官方默认 0.7
#----------------------------------------------------#
max_num_seqs=1                                         # 官方默认：同时只跑 1 条请求
#----------------------------------------------------#
allowed_media_path="/home"                             # 允许加载本地图片的目录
#--------------------------------------------------------------------------------------#


#---------------#
# 切换到虚拟环境
#---------------#
source /path/to/miniconda3/etc/profile.d/conda.sh   # 虚拟环境切换实例化
conda activate vllm                                     # 换到 vllm 虚拟环境
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
#---------------------------------------------------------------------------------------------------------#

#---------------#
# 启动 vLLM 服务
#---------------#
# GroundingPI 走 vLLM Transformers backend（--model-impl transformers），
# 权重目录已含 serving overlay（ProcessorMixin / SDPA / 坐标 token）。
# 官方 recipe：BF16、eager、单图、关视频、关 CUDA Graph。
# 自定义请求务必 skip_special_tokens=false，否则 <0>..<999> 坐标 token 会被丢掉。
export CUDA_VISIBLE_DEVICES=${gpu_ids}
export CUDA_HOME=/usr/local/cuda
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1


IFS=',' read -ra gpu_array <<< "${gpu_ids}"
tp_size=${#gpu_array[@]}

vllm_args=(
    --host 0.0.0.0
    --port "${port}"
    --served-model-name "${model_name}"
    --model-impl transformers
    --dtype bfloat16
    --enforce-eager
    --trust-remote-code
    --tensor-parallel-size "${tp_size}"
    --max-model-len "${max_model_len}"
    --max-num-seqs "${max_num_seqs}"
    --gpu-memory-utilization "${gpu_memory_utilization}"
    --limit-mm-per-prompt '{"image":1,"video":0}'
    --allowed-local-media-path "${allowed_media_path}"
)

# nohup + & 后台启动，关掉终端也不会断
LOG_FILE="$(pwd)/vllm_${port}.log"
nohup vllm serve "${weight}" "${vllm_args[@]}" > "${LOG_FILE}" 2>&1 &
echo "GroundingPI starting on port ${port} (PID: $!). Log: vllm_${port}.log"
echo "  GET  http://127.0.0.1:${port}/v1/models"
echo "  POST http://127.0.0.1:${port}/v1/chat/completions  model=${model_name}"
echo "  请求时设置 skip_special_tokens=false, spaces_between_special_tokens=false"
