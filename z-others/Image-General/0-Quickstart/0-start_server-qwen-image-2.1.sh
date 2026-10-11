#!/bin/bash
###
 # @Author: AI产品研发组
 # @Date: 2026-10-09
 # @Description: SGLang Diffusion 服务启动脚本 — Qwen-Image-2.1
###

set -euo pipefail

#-----------------#
# ⭐需要修改的值⭐
#-----------------#
gpu_ids="0,1"                                          # 使用的 GPU
#----------------------------------------------------#
weight='/home/ubuntu/qwen/models/Qwen-Image-2.1'       # 模型权重路径
#----------------------------------------------------#
port=30000                                             # 服务端口
#----------------------------------------------------#
model_name="Qwen-Image-2.1"                            # 对外暴露的模型名
#----------------------------------------------------#
performance_mode="speed"                               # speed / memory / auto / manual
#----------------------------------------------------#
container_name="sglang"                                # Docker 容器名
#----------------------------------------------------#
image="lmsysorg/sglang:latest"                         # 容器镜像
#--------------------------------------------------------------------------------------#


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/sglang_${port}.log"

IFS=',' read -ra gpu_array <<< "${gpu_ids}"
tp_size=${#gpu_array[@]}

ensure_container() {
    if docker inspect "${container_name}" >/dev/null 2>&1; then
        if [ "$(docker inspect -f '{{.State.Running}}' "${container_name}")" != "true" ]; then
            echo "Starting existing container: ${container_name}"
            docker start "${container_name}" >/dev/null
        fi
        return
    fi

    echo "Creating container: ${container_name}"
    docker run -d \
        --name "${container_name}" \
        --gpus all \
        --shm-size 32g \
        --ipc=host \
        --network=host \
        --ulimit memlock=-1 \
        --ulimit stack=67108864 \
        -v /home/ubuntu:/home/ubuntu \
        -w /home/ubuntu \
        "${image}" \
        sleep infinity >/dev/null
}

run_serve() {
    local serve_cmd=(
        sglang serve
        --model-path "${weight}"
        --model-id "${model_name}"
        --served-model-name "${model_name}"
        --performance-mode "${performance_mode}"
        --num-gpus "${tp_size}"
        --tp-size "${tp_size}"
        --host 0.0.0.0
        --port "${port}"
        --strict-ports
    )

    export CUDA_VISIBLE_DEVICES="${gpu_ids}"
    nohup "${serve_cmd[@]}" > "${LOG_FILE}" 2>&1 &
    echo "SGLang server starting on port ${port} (PID: $!). Log: ${LOG_FILE}"
}

if curl -fsS --max-time 2 "http://127.0.0.1:${port}/liveness" >/dev/null 2>&1; then
    echo "SGLang server already running on port ${port}"
    curl -fsS --max-time 2 "http://127.0.0.1:${port}/v1/models" || true
    exit 0
fi

# 宿主机走 Docker 容器；容器内直接启动
if [ -f /.dockerenv ]; then
    run_serve
else
    ensure_container
    docker exec -d \
        -e CUDA_VISIBLE_DEVICES="${gpu_ids}" \
        "${container_name}" \
        bash -lc "cd '${SCRIPT_DIR}' && nohup sglang serve \
            --model-path '${weight}' \
            --model-id '${model_name}' \
            --served-model-name '${model_name}' \
            --performance-mode '${performance_mode}' \
            --num-gpus '${tp_size}' \
            --tp-size '${tp_size}' \
            --host 0.0.0.0 \
            --port '${port}' \
            --strict-ports \
            > '${LOG_FILE}' 2>&1"
    echo "SGLang server starting in container ${container_name} on port ${port}. Log: ${LOG_FILE}"
fi

echo "Check: curl http://127.0.0.1:${port}/liveness"
echo "Docs:  http://127.0.0.1:${port}/docs"
