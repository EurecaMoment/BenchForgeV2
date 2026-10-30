#!/usr/bin/env bash
# 一键关停：DSH Web -> SpatialForge 服务 -> PostgreSQL（--keep-db 可保留数据库）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
SERVER_CONFIG="$ROOT/config/spatialforge-server.local.json"
STATE="$ROOT/.benchforge"
RUN_DIR="$STATE/run"
SF_PID_FILE="$RUN_DIR/spatialforge.pid"
DSH_PID_FILE="$RUN_DIR/dsh.pid"
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

port_pids() { ss -ltnp 2>/dev/null | grep ":$1 " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true; }

stop_port() {
  local name="$1" pidfile="$2" port="$3" pids pid
  pids="$(
    {
      if [ -f "$pidfile" ] && kill -0 "$(<"$pidfile")" 2>/dev/null; then cat "$pidfile"; fi
      if [ -n "$port" ]; then port_pids "$port"; fi
    } | sort -u
  )"
  if [ -z "$pids" ]; then
    echo "  $name 未运行"
    rm -f "$pidfile"
    return 0
  fi
  echo "  停止 $name (PID: $(echo "$pids" | tr '\n' ' '))"
  for pid in $pids; do kill -TERM "$pid" 2>/dev/null || true; done
  for _ in $(seq 1 20); do
    local alive=0
    for pid in $pids; do kill -0 "$pid" 2>/dev/null && alive=1; done
    [ "$alive" -eq 0 ] && break
    sleep 1
  done
  for pid in $pids; do kill -KILL "$pid" 2>/dev/null || true; done
  rm -f "$pidfile"
}

if [ -f "$SERVER_CONFIG" ]; then
  SERVICE_PORT="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1]))["port"])' "$SERVER_CONFIG" 2>/dev/null || echo 3856)"
else
  SERVICE_PORT=3856
fi

echo "[1/3] 停止 BenchForge DSH Web (端口 $WEB_PORT)"
stop_port "DSH Web" "$DSH_PID_FILE" "$WEB_PORT"

echo "[2/3] 停止 SpatialForge 服务 (端口 $SERVICE_PORT)"
stop_port "SpatialForge" "$SF_PID_FILE" "$SERVICE_PORT"

if [ "$KEEP_DB" -eq 1 ]; then
  echo "[3/3] 保留 PostgreSQL (--keep-db)"
else
  echo "[3/3] 停止 PostgreSQL"
  docker compose -p benchforgev2-spatialforge --env-file config/database.env \
    -f components/spatialforge/deploy/compose.yml down
fi

echo "已停止。"
