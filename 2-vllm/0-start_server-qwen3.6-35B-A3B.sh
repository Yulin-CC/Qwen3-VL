#!/bin/bash
###
 # @Author: AI产品研发组
 # @Date: 2026-06-30
 # @Description: vLLM OpenAI 兼容 API 服务启动脚本 — Qwen3.6-35B-A3B (MoE)
###

#-----------------#
# ⭐需要修改的值⭐
#-----------------#
gpu_ids="0,1"                                          # 35B-A3B MoE 建议双卡
#----------------------------------------------------#
weight='/home/ubuntu/models/Qwen3.6-35B-A3B'           # 模型权重路径
#----------------------------------------------------#
port=8081                                              # 服务端口
#----------------------------------------------------#
model_name="qwen3.6-35b-a3b"                           # 对外暴露的模型名
#----------------------------------------------------#
max_model_len=131072                                   # 双卡 4090 建议 16k~32k
#----------------------------------------------------#
gpu_memory_utilization=0.85                            # MoE 全量权重较大，可按需下调
#----------------------------------------------------#
language_model_only=false                              # true=纯文本省显存；要识图/视频改 false
#----------------------------------------------------#
allowed_media_path="/home"                             # 允许加载本地图片的目录（仅 VLM 模式生效）
#--------------------------------------------------------------------------------------#


#---------------#
# 切换到虚拟环境
#---------------#
source /home/ubuntu/miniconda3/etc/profile.d/conda.sh   # 虚拟环境切换实例化
conda activate qwen                                     # 换到 qwen 虚拟环境
#---------------------------------------------------------------------------------------------------------#

#---------------#
# 启动 vLLM 服务
#---------------#
export CUDA_VISIBLE_DEVICES=${gpu_ids}
export CUDA_HOME=/usr/local/cuda


IFS=',' read -ra gpu_array <<< "${gpu_ids}"
tp_size=${#gpu_array[@]}

vllm_args=(
    --host 0.0.0.0
    --port "${port}"
    --served-model-name "${model_name}"
    --tensor-parallel-size "${tp_size}"
    --max-model-len "${max_model_len}"
    --gpu-memory-utilization "${gpu_memory_utilization}"
    --trust-remote-code
    --attention-backend FLASHINFER
    --reasoning-parser qwen3
    --enable-auto-tool-choice
    --tool-call-parser qwen3_coder
)

if [ "${language_model_only}" = true ]; then
    vllm_args+=(--language-model-only)
else
    vllm_args+=(
        --mm-processor-kwargs '{"max_pixels": 200704, "min_pixels": 784}'
        --mm-encoder-attn-backend TORCH_SDPA
        --allowed-local-media-path "${allowed_media_path}"
    )
fi

# nohup + & 后台启动，关掉终端也不会断
LOG_FILE="$(pwd)/vllm_${port}.log"
nohup vllm serve "${weight}" "${vllm_args[@]}" > "${LOG_FILE}" 2>&1 &
echo "vLLM server starting on port ${port} (PID: \$!). Log: vllm_${port}.log"
