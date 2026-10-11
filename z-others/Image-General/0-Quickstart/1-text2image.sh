#!/bin/bash
###
 # @Author: AI产品研发组
 # @Date: 2026-10-09
 # @Description: Qwen-Image-2.1 文生图示例，调用 /v1/images/generations
 # @Command: bash 0-Quickstart/1-text2image.sh
###

set -euo pipefail

#-----------------#
# ⭐需要修改的值⭐
#-----------------#
prompt="一只水豚在烛光下看书"                          # 文生图提示词
#----------------------------------------------------#
save_dir="results"                                     # 保存目录，相对项目根目录；也可写绝对路径
#----------------------------------------------------#
host="127.0.0.1"                                       # 服务地址
#----------------------------------------------------#
port=30000                                             # 服务端口
#----------------------------------------------------#
model_name="Qwen-Image-2.1"                            # 模型名
#----------------------------------------------------#
size="1024x1024"                                       # 宽高，需为 32 的倍数
#----------------------------------------------------#
seed=42                                                # 随机种子
#--------------------------------------------------------------------------------------#


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [[ "${save_dir}" = /* ]]; then
    OUT_DIR="${save_dir}"
else
    OUT_DIR="${PROJECT_ROOT}/${save_dir}"
fi
mkdir -p "${OUT_DIR}"

OUT_PNG="${OUT_DIR}/t2i_output.png"
RESP_JSON="${OUT_DIR}/t2i_response.json"

echo "🎨 文生图: ${prompt}"
echo "   POST http://${host}:${port}/v1/images/generations"
echo "   保存到 ${OUT_DIR}"

curl -sS --max-time 300 \
    "http://${host}:${port}/v1/images/generations" \
    -H "Content-Type: application/json" \
    -d "{
        \"model\": \"${model_name}\",
        \"prompt\": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "${prompt}"),
        \"size\": \"${size}\",
        \"n\": 1,
        \"seed\": ${seed},
        \"response_format\": \"b64_json\"
    }" > "${RESP_JSON}"

python3 - "${RESP_JSON}" "${OUT_PNG}" <<'PY'
import base64, json, sys
from pathlib import Path

resp_path, out_path = sys.argv[1], sys.argv[2]
payload = json.loads(Path(resp_path).read_text())
if "error" in payload or "data" not in payload:
    raise SystemExit(f"请求失败: {json.dumps(payload, ensure_ascii=False)[:500]}")
Path(out_path).write_bytes(base64.b64decode(payload["data"][0]["b64_json"]))
print(f"✅ 已保存: {out_path}")
PY
