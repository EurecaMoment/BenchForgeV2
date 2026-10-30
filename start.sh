#!/usr/bin/env bash
# 一键启动：PostgreSQL -> SpatialForge 服务 -> BenchForge DSH Web
# 配置全部来自 config/ 目录；日志写入 .benchforge/logs/，PID 写入 .benchforge/run/。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
SF_PY="$ROOT/.spatialforge/venv/bin/python"
SERVER_CONFIG="$ROOT/config/spatialforge-server.local.json"
SERVICE_CONFIG="$ROOT/config/spatialforge.local.json"
PRESET="$ROOT/config/benchforge.local.yml"
STATE="$ROOT/.benchforge"
RUN_DIR="$STATE/run"
LOG_DIR="$STATE/logs"
SF_PID_FILE="$RUN_DIR/spatialforge.pid"
DSH_PID_FILE="$RUN_DIR/dsh.pid"
WEB_PORT="${BENCHFORGE_WEB_PORT:-3081}"

mkdir -p "$RUN_DIR" "$LOG_DIR"

die() { echo "错误: $*" >&2; exit 1; }

for path in "$PY" "$SF_PY" "$SERVER_CONFIG" "$SERVICE_CONFIG" "$PRESET" "$STATE/runtime.json"; do
  [ -e "$path" ] || die "缺少 $path，请先按 README 的安装步骤准备环境"
done

SERVICE_PORT="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1]))["port"])' "$SERVER_CONFIG")"

port_open() { ss -ltn 2>/dev/null | grep ":$1 " > /dev/null; }
pid_alive() { [ -f "$1" ] && kill -0 "$(<"$1")" 2>/dev/null; }
port_pids() { ss -ltnp 2>/dev/null | grep ":$1 " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true; }

wait_port() {
  local port="$1" timeout="$2" i
  for ((i = 0; i < timeout; i++)); do
    port_open "$port" && return 0
    sleep 1
  done
  return 1
}

# DSH 绑定端口后还要等 Loader 装载完成才打印 token；卡住时 token 永远不出现。
token_line_count() { grep -c 'dsh web: .*token=' "$LOG_DIR/dsh.log" 2>/dev/null || true; }

wait_new_token() {
  local before="$1" timeout="$2" i
  for ((i = 0; i < timeout; i++)); do
    [ "$(token_line_count)" -gt "$before" ] && return 0
    sleep 1
  done
  return 1
}

latest_url() {
  grep -oE "http://127.0.0.1:${WEB_PORT}/?\\?token=[A-Za-z0-9_-]+" "$LOG_DIR/dsh.log" 2>/dev/null | tail -n 1 || true
}

url_status() { curl -s -o /dev/null -w '%{http_code}' "$1" 2>/dev/null || true; }

echo "[1/3] 启动 PostgreSQL"
"$PY" spatialforge_app.py db

echo "[2/3] 启动 SpatialForge 服务 (端口 $SERVICE_PORT)"
if port_open "$SERVICE_PORT"; then
  LISTENER="$(port_pids "$SERVICE_PORT" | head -n 1)"
  [ -n "$LISTENER" ] && echo "$LISTENER" > "$SF_PID_FILE"
  echo "  已在运行 (PID ${LISTENER:-unknown})，跳过"
else
  echo "==== $(date '+%F %T') start ====" >> "$LOG_DIR/spatialforge.log"
  # setsid 脱离当前终端会话，关闭终端后服务继续运行
  setsid "$SF_PY" -m spatialforge.service --config "$SERVER_CONFIG" >> "$LOG_DIR/spatialforge.log" 2>&1 < /dev/null &
  echo $! > "$SF_PID_FILE"
  if ! wait_port "$SERVICE_PORT" 90; then
    tail -n 20 "$LOG_DIR/spatialforge.log" >&2 || true
    kill "$(<"$SF_PID_FILE")" 2>/dev/null || true
    rm -f "$SF_PID_FILE"
    die "SpatialForge 在 90 秒内未监听 $SERVICE_PORT，见 $LOG_DIR/spatialforge.log"
  fi
  LISTENER="$(port_pids "$SERVICE_PORT" | head -n 1)"
  [ -n "$LISTENER" ] && echo "$LISTENER" > "$SF_PID_FILE"
  echo "  已启动 (PID ${LISTENER:-$(<"$SF_PID_FILE")})"
fi

echo "[3/3] 启动 BenchForge DSH Web (端口 $WEB_PORT)"
if port_open "$WEB_PORT"; then
  LISTENER="$(port_pids "$WEB_PORT" | head -n 1)"
  [ -n "$LISTENER" ] && echo "$LISTENER" > "$DSH_PID_FILE"
  echo "  已在运行 (PID ${LISTENER:-unknown})，跳过"
else
  TOKEN_BEFORE="$(token_line_count)"
  # 模型凭据只从本地 gitignored 文件注入（config/dsh.env），供 llm-pi-ai 的 apiKeyEnv 读取。
  if [ -f "$ROOT/config/dsh.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$ROOT/config/dsh.env"
    set +a
  fi
  echo "==== $(date '+%F %T') start ====" >> "$LOG_DIR/dsh.log"
  setsid "$PY" "$ROOT/benchforge.py" start --port "$WEB_PORT" --no-open >> "$LOG_DIR/dsh.log" 2>&1 < /dev/null &
  echo $! > "$DSH_PID_FILE"
  if ! wait_port "$WEB_PORT" 240; then
    tail -n 20 "$LOG_DIR/dsh.log" >&2 || true
    kill "$(<"$DSH_PID_FILE")" 2>/dev/null || true
    rm -f "$DSH_PID_FILE"
    die "DSH 在 240 秒内未监听 $WEB_PORT，见 $LOG_DIR/dsh.log"
  fi
  # 端口监听不等于启动完成：必须等到本次新生成的 token 行。
  if ! wait_new_token "$TOKEN_BEFORE" 180; then
    tail -n 20 "$LOG_DIR/dsh.log" >&2 || true
    echo "诊断: DSH 端口已监听，但 180 秒内没有输出新的 token，服务仍卡在启动阶段。" >&2
    echo "  inotify watches 上限=$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo unknown)，已用=$(cat /proc/*/fdinfo/* 2>/dev/null | grep -c 'inotify wd:' || true)" >&2
    echo "  hmr 拿不到文件监视器会导致永不完成启动，请提高上限后重试：" >&2
    echo "    sudo sysctl -w fs.inotify.max_user_watches=524288" >&2
    kill "$(<"$DSH_PID_FILE")" 2>/dev/null || true
    rm -f "$DSH_PID_FILE"
    die "DSH 未完成启动，已停止该进程以免占用端口，见 $LOG_DIR/dsh.log"
  fi
  LISTENER="$(port_pids "$WEB_PORT" | head -n 1)"
  [ -n "$LISTENER" ] && echo "$LISTENER" > "$DSH_PID_FILE"
  echo "  已启动 (PID ${LISTENER:-$(<"$DSH_PID_FILE")})"
fi

echo
echo "验证："
if "$PY" spatialforge_app.py status > /dev/null 2>&1; then
  echo "  数据库 / 服务 / 令牌：正常"
else
  echo "  数据库 / 服务 / 令牌：检查失败，手动执行 .venv/bin/python spatialforge_app.py status"
fi

URL="$(latest_url)"
WEB_STATUS=""
[ -n "$URL" ] && WEB_STATUS="$(url_status "$URL")"
echo
echo "启动完成。"
echo "  服务端: http://127.0.0.1:$SERVICE_PORT"
echo "  Web:    ${URL:-http://127.0.0.1:$WEB_PORT/ （token 见 .benchforge/logs/dsh.log）}"
if [ -n "$URL" ] && { [ "$WEB_STATUS" != "200" ] && [ "$WEB_STATUS" != "303" ]; }; then
  echo "  警告:   该 token 访问返回 $WEB_STATUS，可能属于上一次未完成启动的进程，请查看日志"
fi
echo "  日志:   $LOG_DIR"
echo "  停止:   ./shutdown.sh"
