#!/bin/bash
###
 # @Author: 算法组
 # @Date: 2026-08-21
 # @Description: grounding 生成：check → crop → describe(+policy) → caption
###
_SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -f "$_SCRIPT_DIR/util/generate.py" ]; then
  WORK_DIR="$_SCRIPT_DIR"
else
  WORK_DIR=$(cd "$_SCRIPT_DIR/.." && pwd)
fi

#--------------------------------------#
# 需要修改的值
#--------------------------------------#
dataset="/path/to/dataset"                 # 含 images/ + jsons-segm|jsons-detect|jsons
#--------------------------------------#
n_captions=5
#--------------------------------------#
expand_ratio=1.5
#--------------------------------------#
workers=4
#--------------------------------------#
# 空=通用 default；appearance=只写外观
rules_scene=""
#--------------------------------------#

# vLLM 默认读 model/server.json 中 default=true
# 覆盖：--base_url http://host:port/v1 --model NAME

if [ -f /home/ubuntu/miniconda3/etc/profile.d/conda.sh ]; then
  source /home/ubuntu/miniconda3/etc/profile.d/conda.sh
  conda activate qwen 2>/dev/null || true
fi

cd "$WORK_DIR"
python util/generate.py \
  --dataset       "$dataset" \
  --n_captions    "$n_captions" \
  --expand_ratio  "$expand_ratio" \
  --workers       "$workers" \
  --rules-scene   "$rules_scene" \
  "$@"
