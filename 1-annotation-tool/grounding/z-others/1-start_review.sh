#!/bin/bash
# ──────────────────────────────────────────────────────────
# Grounding 人工检查界面
#
# 用法：
#   bash 1-start_review.sh
#   bash 1-start_review.sh --port 8082
#
# Windows 请用同目录 1-start_review.bat（可连远程 vLLM）
#
# 远程端口映射：
#   ssh -L 8082:localhost:8082 user@serve
#   浏览器打开 http://localhost:8082
# ──────────────────────────────────────────────────────────

_SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
if [ -f "$_SCRIPT_DIR/util/app.py" ]; then
  cd "$_SCRIPT_DIR"
else
  cd "$_SCRIPT_DIR/.."
fi

if [ -f /home/ubuntu/miniconda3/etc/profile.d/conda.sh ]; then
  source /home/ubuntu/miniconda3/etc/profile.d/conda.sh
  conda activate qwen 2>/dev/null || true
fi

if ! python3 -c "import flask" 2>/dev/null; then
  echo "正在安装 Flask..."
  pip install flask -q
fi

#-----------------#
# 可选参数
#-----------------#
# 默认不预设数据集，启动后在界面点「选择数据集」。
# 也可：bash 1-start_review.sh --dataset /path/to/dataset
DATASET=""
PORT=8082
#--------------------------------------------------------------------------------------#

while [[ "$#" -gt 0 ]]; do
  case $1 in
    --port) PORT="$2"; shift ;;
    --dataset) DATASET="$2"; shift ;;
  esac
  shift
done

# 多开：首选端口占用则 PORT+1 ...（不杀已有实例）
_port_free() {
  if command -v ss >/dev/null 2>&1; then
    ! ss -ltn "( sport = :$1 )" 2>/dev/null | grep -q ":$1"
  else
    ! fuser "$1/tcp" >/dev/null 2>&1
  fi
}
PREFERRED="$PORT"
for i in $(seq 0 19); do
  try=$((PREFERRED + i))
  if _port_free "$try"; then
    PORT="$try"
    break
  fi
done
if [[ "$PORT" != "$PREFERRED" ]]; then
  echo "  Port ${PREFERRED} busy -> using ${PORT} (multi-instance)"
fi

echo ""
echo "  ┌─────────────────────────────────────────────────┐"
echo "  │   Grounding 检查界面                             │"
echo "  │   http://localhost:${PORT}                      │"
echo "  │   dataset: ${DATASET:-（未预设，请在界面选择）}   │"
echo "  │   ssh -L ${PORT}:localhost:${PORT} user@server  │"
echo "  │   Ctrl+C / 关终端 → 释放本实例端口 ${PORT}       │"
echo "  └─────────────────────────────────────────────────┘"
echo ""

# 仅释放本实例端口（勿杀其它多开窗口）
_cleanup_port() {
  fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
}
trap _cleanup_port EXIT INT TERM HUP

if [[ -n "$DATASET" ]]; then
  python3 util/app.py --port "$PORT" --dataset "$DATASET"
else
  python3 util/app.py --port "$PORT"
fi
