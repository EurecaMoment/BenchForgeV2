#!/usr/bin/env bash
# 关停本地测试用 Isaac Sim gRPC 服务。
# 只按 pid 文件 / 本目录 server.py 进程匹配，不会影响远程仿真服务器。
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/.test_server.pid"

stop_pid() {
  local pid="$1"
  kill -TERM "$pid" 2>/dev/null || return 1
  for _ in $(seq 1 50); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.2
  done
  kill -KILL "$pid" 2>/dev/null || true
}

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if stop_pid "$PID"; then
    echo "测试 gRPC 服务已停止 (pid $PID)"
  else
    echo "pid $PID 未在运行，清理 pid 文件"
  fi
  rm -f "$PID_FILE"
  exit 0
fi

# 兜底：pid 文件丢失时按本目录路径精确匹配
PIDS="$(pgrep -f "$DIR/server.py" || true)"
if [[ -z "$PIDS" ]]; then
  echo "未发现运行中的测试 gRPC 服务"
  exit 0
fi
for PID in $PIDS; do
  if stop_pid "$PID"; then
    echo "测试 gRPC 服务已停止 (pid $PID)"
  fi
done
