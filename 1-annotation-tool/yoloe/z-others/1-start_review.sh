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
#   ssh -L 8082:localhost:8082 user@server
#   浏览器打开 http://localhost:8082
# ──────────────────────────────────────────────────────────

cd "$(dirname "$0")"

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

echo ""
echo "  ┌─────────────────────────────────────────────────┐"
echo "  │   Grounding 检查界面                             │"
echo "  │   http://localhost:${PORT}                      │"
echo "  │   dataset: ${DATASET:-（未预设，请在界面选择）}   │"
echo "  │   ssh -L ${PORT}:localhost:${PORT} user@server  │"
echo "  │   Ctrl+C / 关终端 → 自动释放端口 ${PORT}         │"
echo "  └─────────────────────────────────────────────────┘"
echo ""

# 退出时释放端口（Ctrl+C、正常结束；强杀终端时由进程组一并结束）
_cleanup_port() {
  fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
}
trap _cleanup_port EXIT INT TERM HUP

# 启动前清掉残留占用
_cleanup_port

if [[ -n "$DATASET" ]]; then
  python3 util/app.py --port "$PORT" --dataset "$DATASET"
else
  python3 util/app.py --port "$PORT"
fi
