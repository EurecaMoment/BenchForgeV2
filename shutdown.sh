#!/usr/bin/env bash
# 一键关停：DSH Web -> BenchForge 服务 -> PostgreSQL（--keep-db 可保留数据库）
# Isaac Sim gRPC 服务（本地 mock 或远程仿真器）不在此管理，需单独手动停止。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
SERVER_CONFIG="$ROOT/config/generated/benchforge-server.local.json"
LEGACY_CONFIG="$ROOT/config/generated/spatialforge-server.local.json"
STATE="$ROOT/.benchforge"
RUN_DIR="$STATE/run"
SERVICE_PID_FILE="$RUN_DIR/benchforge.pid"
LEGACY_PID_FILE="$RUN_DIR/spatialforge.pid"
DSH_PID_FILE="$RUN_DIR/dsh.pid"
DB_PROJECT_FILE="$RUN_DIR/database-project"
DB_ENV="$ROOT/config/generated/database.env"
KEEP_DB=0
RESTART=0

for arg in "$@"; do
  case "$arg" in
    --keep-db) KEEP_DB=1 ;;
    --for-restart) RESTART=1 ;;
    -h | --help)
      echo "用法: ./shutdown.sh [--keep-db]"
      exit 0
      ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

stop_process() {
  local name="$1" pidfile="$2" expected pid command group target matched=0
  shift 2
  if [ ! -f "$pidfile" ]; then
    echo "  $name 未由本脚本启动"
    return 0
  fi
  pid="$(<"$pidfile")"
  if [[ ! "$pid" =~ ^[1-9][0-9]*$ ]]; then
    echo "  $name 的 PID 记录无效，保留记录" >&2
    return 1
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "  $name 的记录进程已退出"
    rm -f "$pidfile"
    return 0
  fi
  command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  for expected in "$@"; do
    if [[ "$command" == *"$expected"* ]]; then
      matched=1
      break
    fi
  done
  if [ "$matched" -eq 0 ]; then
    echo "  $name 的 PID 与预期命令不符，保留进程和记录" >&2
    return 1
  fi
  # start.sh uses setsid. Stop the owned session's process group so the Python
  # launcher does not leave its Node child listening after a restart.
  group="$(ps -p "$pid" -o pgid= 2>/dev/null | tr -d ' ' || true)"
  target="$pid"
  [ "$group" = "$pid" ] && target="-$pid"
  echo "  停止 $name (PID: $pid)"
  kill -TERM -- "$target" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 -- "$target" 2>/dev/null || break
    sleep 1
  done
  if kill -0 -- "$target" 2>/dev/null && ! kill -KILL -- "$target" 2>/dev/null \
    && kill -0 -- "$target" 2>/dev/null; then
    echo "  $name 仍在运行，保留进程记录" >&2
    return 1
  fi
  rm -f "$pidfile"
}

DB_PROJECT=""
if [ -f "$DB_PROJECT_FILE" ]; then
  DB_PROJECT="$(<"$DB_PROJECT_FILE")"
elif [ -f "$DB_ENV" ]; then
  DB_PROJECT="$("$PY" benchforge_app.py setting database.previous_project)"
fi
if [ "$RESTART" -eq 1 ] && [ -n "$DB_PROJECT" ]; then
  DB_MANAGED="$("$PY" benchforge_app.py setting database.managed)"
  if [ "$DB_MANAGED" = true ]; then
    NEXT_PROJECT="$("$PY" benchforge_app.py setting database.project)"
    if [ "$DB_PROJECT" = "$NEXT_PROJECT" ]; then KEEP_DB=1; fi
  fi
fi

echo "[1/3] 停止 BenchForge DSH Web"
stop_process "DSH Web" "$DSH_PID_FILE" "$ROOT/benchforge.py start"

echo "[2/3] 停止 BenchForge 服务"
if [ -f "$SERVICE_PID_FILE" ] || [ ! -f "$LEGACY_PID_FILE" ]; then
  stop_process "BenchForge" "$SERVICE_PID_FILE" "$ROOT/benchforge_app.py serve" \
    "scene_production.service --config $SERVER_CONFIG"
fi
if [ -f "$LEGACY_PID_FILE" ]; then
  stop_process "BenchForge" "$LEGACY_PID_FILE" "$ROOT/spatialforge_app.py serve" \
    "spatialforge.service --config $LEGACY_CONFIG"
fi

# Isaac Sim gRPC 服务（本地 mock 或远程仿真器）不在此管理，需单独手动停止。

if [ "$KEEP_DB" -eq 1 ]; then
  echo "[3/3] 保留 PostgreSQL"
  if [ -n "$DB_PROJECT" ]; then
    mkdir -p "$RUN_DIR"
    printf '%s\n' "$DB_PROJECT" > "$DB_PROJECT_FILE"
  fi
elif [ -z "$DB_PROJECT" ]; then
  echo "[3/3] 本实例没有记录的 PostgreSQL 项目"
else
  echo "[3/3] 停止 PostgreSQL ($DB_PROJECT)"
  "$PY" benchforge_app.py db --stop --project "$DB_PROJECT"
  mkdir -p "$RUN_DIR"
  : > "$DB_PROJECT_FILE"
fi

echo "已停止。"
echo "💡 提示：下次重启 dsh-home/sessions 还在，旧浏览器 tab 刷新就能续上。"
echo "   只有在 session 完全损坏时才需要 rm -rf .benchforge/dsh-home"
