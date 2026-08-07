#!/bin/bash
# ──────────────────────────────────────────────────────────
# 图像标注平台启动脚本
#
# 用法：
#   bash start.sh               # 默认端口 8080
#   bash start.sh --port 8080   # 自定义端口
#
# 启动后在浏览器打开对应地址，通过页面弹窗选择目录。
# 如需端口映射（远程服务器）：
#   本地执行: ssh -L 8080:localhost:8080 user@server
#   然后访问: http://localhost:8080
# ──────────────────────────────────────────────────────────

cd "$(dirname "$0")"

if ! python3 -c "import flask" 2>/dev/null; then
  echo "正在安装 Flask..."
  pip install flask -q
fi

PORT=${1:-8080}
# 支持 --port 8080 形式
while [[ "$#" -gt 0 ]]; do
  case $1 in
    --port) PORT="$2"; shift ;;
  esac
  shift
done

echo ""
echo "  ┌─────────────────────────────────────────────────┐"
echo "  │   图像标注平台                                    │"
echo "  │   http://localhost:${PORT}                      │"
echo "  │                                                 │"
echo "  │   远程端口映射                                    │"
echo "  │   ssh -L ${PORT}:localhost:${PORT} user@server  │"
echo "  └─────────────────────────────────────────────────┘"
echo ""

python3 util/app.py --port "$PORT"
