#!/usr/bin/env bash
# 一键关停：DSH Web -> SpatialForge 服务 -> PostgreSQL（--keep-db 可保留数据库）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
SERVER_CONFIG="$ROOT/config/generated/spatialforge-server.local.json"
STATE="$ROOT/.benchforge"
RUN_DIR="$STATE/run"
SF_PID_FILE="$RUN_DIR/spatialforge.pid"
DSH_PID_FILE="$RUN_DIR/dsh.pid"
# 端口唯一权威来源是 config/ports.env，这里只做读取
[ -f "$ROOT/config/ports.env" ] && . "$ROOT/config/ports.env"
WEB_PORT="${BENCHFORGE_WEB_PORT:-3081}"
KEEP_DB=0

for arg in "$@"; do
  case "$arg" in
    --keep-db) KEEP_DB=1 ;;
    -h | --help)
      echo "用法: ./shutdown.sh [--keep-db]"
      exit 0
      ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

stop_port() {
  local name="$1" pidfile="$2" expected="$3" pid command
  if [ ! -f "$pidfile" ]; then
    echo "  $name 未由本脚本启动"
    return 0
  fi
  pid="$(<"$pidfile")"
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "  $name 的记录进程已退出"
    rm -f "$pidfile"
    return 0
  fi
  command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  case "$command" in
    *"$expected"*) ;;
    *) echo "  $name 的 PID 与预期命令不符，保留进程和记录"; return 0 ;;
  esac
  echo "  停止 $name (PID: $pid)"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
  rm -f "$pidfile"
}

if [ -f "$SERVER_CONFIG" ]; then
  SERVICE_PORT="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1]))["port"])' "$SERVER_CONFIG" 2>/dev/null || echo "${SPATIALFORGE_PORT:-3856}")"
else
  SERVICE_PORT="${SPATIALFORGE_PORT:-3856}"
fi

echo "[1/4] 停止 BenchForge DSH Web (端口 $WEB_PORT)"
stop_port "DSH Web" "$DSH_PID_FILE" "benchforge.py start --port"

echo "[2/4] 停止 SpatialForge 服务 (端口 $SERVICE_PORT)"
stop_port "SpatialForge" "$SF_PID_FILE" "spatialforge.service --config $SERVER_CONFIG"

echo "[3/4] 停止 Isaac Sim gRPC mock"
bash "$ROOT/components/spatialforge/grpc/stop_test_server.sh" || true

if [ "$KEEP_DB" -eq 1 ]; then
  echo "[4/4] 保留 PostgreSQL (--keep-db)"
else
  echo "[4/4] 停止 PostgreSQL"
  docker compose -p benchforgev2-spatialforge --env-file config/generated/database.env \
    -f components/spatialforge/deploy/compose.yml down
fi

echo "已停止。"
echo "💡 提示：下次重启 dsh-home/sessions 还在，旧浏览器 tab 刷新就能续上。"
echo "   只有在 session 完全损坏时才需要 rm -rf .benchforge/dsh-home"
