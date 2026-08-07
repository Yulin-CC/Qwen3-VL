#!/bin/bash
# ──────────────────────────────────────────────────────────
# Grounding 批量生成：crop → describe → caption
#
# 用法：
#   bash 0-generate.sh                    # 正式：必须先启动 vLLM@8081
#   bash 0-generate.sh --limit 2          # 试验少量图（仍会调 Qwen）
#   bash 0-generate.sh --export           # 生成后直接导出 jsons-GD
#   bash 0-generate.sh --no_llm           # 仅调试占位，描述会是 "car object" 之类
#   bash 0-generate.sh --stages describe,caption --workers 8
#
# 依赖：本地 vLLM 多模态服务（默认 http://127.0.0.1:8081）
# 若之前用过 --no_llm，直接再跑本脚本会自动重写占位描述。
# ──────────────────────────────────────────────────────────

cd "$(dirname "$0")"

#-----------------#
# ⭐需要修改的值⭐
#-----------------#
DATASET="/home/yulin/0-data/2-DroneObject/grounding_sample/rm"
#----------------------------------------------------#
BASE_URL="http://127.0.0.1:8081/v1"
#----------------------------------------------------#
MODEL="qwen3.6-35b-a3b"
#----------------------------------------------------#
N_CAPTIONS=5
#----------------------------------------------------#
EXPAND_RATIO=1.5
#----------------------------------------------------#
WORKERS=8                                              # describe 并发（可调到 12~16）
#--------------------------------------------------------------------------------------#

EXTRA_ARGS=("$@")

python3 util/generate.py \
  --dataset "$DATASET" \
  --base_url "$BASE_URL" \
  --model "$MODEL" \
  --n_captions "$N_CAPTIONS" \
  --expand_ratio "$EXPAND_RATIO" \
  --workers "$WORKERS" \
  "${EXTRA_ARGS[@]}"
