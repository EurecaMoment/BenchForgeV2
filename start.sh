#!/usr/bin/env bash
# 一键启动：PostgreSQL -> SpatialForge 服务 -> BenchForge DSH Web
# 配置来自 config/benchforge.local.json；日志和运行记录写入 .benchforge/。
# Isaac Sim gRPC 服务不在此管理：本地 mock 或远程仿真器请单独手动启动。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
SF_PY="$ROOT/.spatialforge/venv/bin/python"
PRESET="$ROOT/config/generated/benchforge.local.yml"
STATE="$ROOT/.benchforge"
RUN_DIR="$STATE/run"
LOG_DIR="$STATE/logs"
SF_PID_FILE="$RUN_DIR/spatialforge.pid"
DSH_PID_FILE="$RUN_DIR/dsh.pid"
DB_PROJECT_FILE="$RUN_DIR/database-project"
DB_ENV="$ROOT/config/generated/database.env"

mkdir -p "$RUN_DIR" "$LOG_DIR"

die() { echo "错误: $*" >&2; exit 1; }

for path in "$PY" "$SF_PY" "$PRESET" "$STATE/runtime.json"; do
  [ -e "$path" ] || die "缺少 $path，请先按 README 的安装步骤准备环境"
done

port_open() { ss -ltn 2>/dev/null | grep ":$1 " > /dev/null; }

check_previous_process() {
  local name="$1" pidfile="$2" port="$3" pid
  if [ -f "$pidfile" ]; then
    pid="$(<"$pidfile")"
    if [[ ! "$pid" =~ ^[1-9][0-9]*$ ]]; then
      die "$name 的 PID 记录无效"
    fi
    if kill -0 "$pid" 2>/dev/null && ! port_open "$port"; then
      die "$name 仍在运行，端口 $port 未监听，请执行 ./restart.sh"
    fi
  fi
}

WEB_PORT="$("$PY" spatialforge_app.py setting web.port)"
SERVICE_PORT="$("$PY" spatialforge_app.py setting server.port)"
if [[ ! "$WEB_PORT" =~ ^[1-9][0-9]*$ || ! "$SERVICE_PORT" =~ ^[1-9][0-9]*$ ]]; then
  die "无法读取有效的 Web 和 SpatialForge 端口"
fi
check_previous_process "DSH Web" "$DSH_PID_FILE" "$WEB_PORT"
check_previous_process "SpatialForge" "$SF_PID_FILE" "$SERVICE_PORT"

PREVIOUS_PROJECT=""
if [ -f "$DB_PROJECT_FILE" ]; then
  PREVIOUS_PROJECT="$(<"$DB_PROJECT_FILE")"
elif [ -f "$DB_ENV" ] && ! grep -qx 'BENCHFORGE_DATABASE_MANAGED=false' "$DB_ENV" \
  && grep -q '^POSTGRES_PASSWORD=' "$DB_ENV"; then
  PREVIOUS_PROJECT="$(grep -m 1 '^COMPOSE_PROJECT_NAME=' "$DB_ENV" | cut -d= -f2- || true)"
  PREVIOUS_PROJECT="${PREVIOUS_PROJECT:-benchforgev2-spatialforge}"
fi
if [ -n "$PREVIOUS_PROJECT" ]; then
  DB_MANAGED="$("$PY" spatialforge_app.py setting database.managed)"
  DB_PROJECT="$("$PY" spatialforge_app.py setting database.project)"
  if [ "$DB_MANAGED" != true ] || [ "$DB_PROJECT" != "$PREVIOUS_PROJECT" ]; then
    die "数据库项目或部署方式已修改，请执行 ./restart.sh 切换"
  fi
fi
"$PY" spatialforge_app.py sync

"$PY" benchforge.py start --port "$WEB_PORT" --config-synced --check-config

wait_port() {
  local port="$1" timeout="$2" i
  for ((i = 0; i < timeout; i++)); do
    port_open "$port" && return 0
    sleep 1
  done
  return 1
}

# DSH 绑定端口后还要等 Loader 装载完成才打印 token；卡住时 token 永远不出现。
token_line_count() {
  local count
  count="$(grep -c 'dsh web: .*token=' "$LOG_DIR/dsh.log" 2>/dev/null || true)"
  # The log does not exist on the first installation.
  printf '%s\n' "${count:-0}"
}

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

fail_start() {
  local pidfile="$1" pid
  pid="$(<"$pidfile")"
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM -- "$pid" 2>/dev/null || true
  rm -f "$pidfile"
}

DB_MANAGED="$("$PY" spatialforge_app.py setting database.managed)"
if [ "$DB_MANAGED" = true ]; then
  DB_PROJECT="$("$PY" spatialforge_app.py setting database.project)"
  echo "[1/3] 启动 PostgreSQL ($DB_PROJECT)"
  printf '%s\n' "$DB_PROJECT" > "$DB_PROJECT_FILE"
  "$PY" spatialforge_app.py db --project "$DB_PROJECT"
elif [ "$DB_MANAGED" = false ]; then
  echo "[1/3] 使用外部 PostgreSQL"
  : > "$DB_PROJECT_FILE"
else
  die "无法读取数据库部署方式"
fi

echo "[2/3] 启动 SpatialForge 服务 (端口 $SERVICE_PORT)"
if port_open "$SERVICE_PORT"; then
  echo "  端口已监听，保留现有进程"
else
  echo "==== $(date '+%F %T') start ====" >> "$LOG_DIR/spatialforge.log"
  # setsid 脱离当前终端会话，关闭终端后服务继续运行
  setsid "$PY" "$ROOT/spatialforge_app.py" serve >> "$LOG_DIR/spatialforge.log" 2>&1 < /dev/null &
  echo $! > "$SF_PID_FILE"
  if ! wait_port "$SERVICE_PORT" 90; then
    tail -n 20 "$LOG_DIR/spatialforge.log" >&2 || true
    fail_start "$SF_PID_FILE"
    die "BenchForgeV2 在 90 秒内未监听 $SERVICE_PORT，见 $LOG_DIR/spatialforge.log"
  fi
  echo "  已启动 (PID $(<"$SF_PID_FILE"))"
fi

echo "[3/3] 启动 BenchForge DSH Web (端口 $WEB_PORT)"
if port_open "$WEB_PORT"; then
  echo "  端口已监听，保留现有进程"
else
  TOKEN_BEFORE="$(token_line_count)"
  echo "==== $(date '+%F %T') start ====" >> "$LOG_DIR/dsh.log"
  setsid "$PY" "$ROOT/benchforge.py" start --port "$WEB_PORT" --config-synced --no-open >> "$LOG_DIR/dsh.log" 2>&1 < /dev/null &
  echo $! > "$DSH_PID_FILE"
  if ! wait_port "$WEB_PORT" 240; then
    tail -n 20 "$LOG_DIR/dsh.log" >&2 || true
    fail_start "$DSH_PID_FILE"
    die "DSH 在 240 秒内未监听 $WEB_PORT，见 $LOG_DIR/dsh.log"
  fi
  # 端口监听不等于启动完成：必须等到本次新生成的 token 行。
  if ! wait_new_token "$TOKEN_BEFORE" 180; then
    tail -n 20 "$LOG_DIR/dsh.log" >&2 || true
    echo "诊断: DSH 端口已监听，但 180 秒内没有输出新的 token，服务仍卡在启动阶段。" >&2
    echo "  inotify watches 上限=$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo unknown)" >&2
    echo "  hmr 拿不到文件监视器会导致永不完成启动，请提高上限后重试：" >&2
    echo "    sudo sysctl -w fs.inotify.max_user_watches=524288" >&2
    fail_start "$DSH_PID_FILE"
    die "DSH 未完成启动，已停止该进程以免占用端口，见 $LOG_DIR/dsh.log"
  fi
  echo "  已启动 (PID $(<"$DSH_PID_FILE"))"
fi

echo
echo "验证："
if "$PY" spatialforge_app.py status > /dev/null 2>&1; then
  echo "  数据库 / 服务 / 令牌：正常"
else
  die "数据库 / BenchForgeV2 服务 / DSH 令牌健康检查失败；未报告启动成功。请查看 $LOG_DIR 下的服务日志并修复后重试。"
fi

URL="$(latest_url)"
WEB_STATUS=""
[ -n "$URL" ] && WEB_STATUS="$(url_status "$URL")"
if [ -z "$URL" ]; then
  die "未找到 DSH Web token 地址，未报告启动成功；请检查 $LOG_DIR/dsh.log"
fi
if [ "$WEB_STATUS" != "200" ] && [ "$WEB_STATUS" != "303" ]; then
  die "DSH Web token readiness 检查返回 $WEB_STATUS，未报告启动成功；请检查 $LOG_DIR/dsh.log"
fi
echo
echo "启动完成。"
echo "  服务端: http://127.0.0.1:$SERVICE_PORT"
echo "  Web:    ${URL:-http://127.0.0.1:$WEB_PORT/ （token 见 .benchforge/logs/dsh.log）}"
echo "  日志:   $LOG_DIR"
echo "  停止:   ./shutdown.sh"
echo
# --- 浏览器操作指引（重启翻车 99% 是旧 tab 没关）---
HAS_SESSIONS=0
[ -d "$STATE/dsh-home/sessions" ] && HAS_SESSIONS=1
if [ "$HAS_SESSIONS" -eq 1 ]; then
  echo "📋 浏览器操作：直接刷新你现有的 DSH tab 即可（session 文件保留了）"
else
  echo "⚠️  浏览器操作：关掉所有旧的 DSH tab，用上面的 Web URL 重新打开！"
  echo "   （dsh-home/sessions 已被清理，旧 tab 会报 ENOENT）"
fi
echo "   不想关 tab? 只要你没手动 rm dsh-home，下次重启就能刷新续上"
