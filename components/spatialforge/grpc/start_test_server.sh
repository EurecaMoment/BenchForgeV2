#!/usr/bin/env bash
# 启动本地测试用 Isaac Sim gRPC 服务（127.0.0.1:50051）。
# 仅用于验证 BenchForge -> gRPC 调用链路，不加载 Isaac Sim。
# 生产环境请把 components/spatialforge/grpc 部署到远程仿真服务器执行 python server.py。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../../.." && pwd)"
PY="$ROOT/.venv/bin/python"
HOST="${GRPC_HOST:-127.0.0.1}"
PORT="${GRPC_PORT:-50051}"
PID_FILE="$DIR/.test_server.pid"
LOG_FILE="$DIR/.test_server.log"

if [[ ! -x "$PY" ]]; then
  echo "未找到 $PY，请先运行 ./start.sh 或 spatialforge_app.py setup" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "测试 gRPC 服务已在运行 (pid $(cat "$PID_FILE"))，日志: $LOG_FILE"
  exit 0
fi

# 脱离当前终端会话（setsid），避免脚本所在 shell 退出时连带杀掉服务进程。
LAUNCH=(nohup)
command -v setsid >/dev/null 2>&1 && LAUNCH=(setsid nohup)
"${LAUNCH[@]}" "$PY" "$DIR/server.py" --host "$HOST" --port "$PORT" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

# 等待端口就绪，最多 10 秒
for _ in $(seq 1 50); do
  if "$PY" - "$HOST" "$PORT" <<'EOF'
import socket, sys
s = socket.socket()
s.settimeout(0.2)
sys.exit(0 if s.connect_ex((sys.argv[1], int(sys.argv[2]))) == 0 else 1)
EOF
  then
    echo "测试 gRPC 服务已启动: $HOST:$PORT (pid $(cat "$PID_FILE"))"
    echo "日志: $LOG_FILE"
    exit 0
  fi
  sleep 0.2
done

echo "启动失败或端口被占用，最近日志:" >&2
tail -n 20 "$LOG_FILE" >&2 || true
rm -f "$PID_FILE"
exit 1
