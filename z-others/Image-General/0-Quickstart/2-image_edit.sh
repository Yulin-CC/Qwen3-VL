#!/bin/bash
###
 # @Author: AI产品研发组
 # @Date: 2026-10-09
 # @Description: Qwen-Image-2.1 图像编辑示例，调用 /v1/images/edits
 # @Command: bash 0-Quickstart/2-image_edit.sh
###

set -euo pipefail

#-----------------#
# ⭐需要修改的值⭐
#-----------------#
input_image="datadir/20251125104824_VIS.jpeg"                   # 输入图；相对路径相对项目根目录
#----------------------------------------------------#
prompt="在道路上随机加几个坑洼"                            # 编辑指令
#----------------------------------------------------#
save_dir="results"                                     # 保存目录，相对项目根目录；也可写绝对路径
#----------------------------------------------------#
host="127.0.0.1"                                       # 服务地址
#----------------------------------------------------#
port=30000                                             # 服务端口
#----------------------------------------------------#
model_name="Qwen-Image-2.1"                            # 模型名
#----------------------------------------------------#
size="1024x1024"                                       # 输出尺寸
#----------------------------------------------------#
seed=42                                                # 随机种子
#--------------------------------------------------------------------------------------#


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ "${input_image}" = /* ]]; then
    INPUT_PATH="${input_image}"
else
    INPUT_PATH="${PROJECT_ROOT}/${input_image}"
fi

if [ ! -f "${INPUT_PATH}" ]; then
    echo "❌ 找不到输入图: ${INPUT_PATH}"
    echo "   请在脚本顶部修改 input_image"
    exit 1
fi

if [[ "${save_dir}" = /* ]]; then
    OUT_DIR="${save_dir}"
else
    OUT_DIR="${PROJECT_ROOT}/${save_dir}"
fi
mkdir -p "${OUT_DIR}"

OUT_PNG="${OUT_DIR}/edit_output.png"
RESP_JSON="${OUT_DIR}/edit_response.json"

echo "🖌️  图像编辑: ${prompt}"
echo "   输入图 ${INPUT_PATH}"
echo "   POST http://${host}:${port}/v1/images/edits"
echo "   保存到 ${OUT_DIR}"

curl -sS --max-time 300 \
    "http://${host}:${port}/v1/images/edits" \
    -F "model=${model_name}" \
    -F "prompt=${prompt}" \
    -F "image=@${INPUT_PATH}" \
    -F "size=${size}" \
    -F "seed=${seed}" \
    -F "response_format=b64_json" \
    > "${RESP_JSON}"

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
