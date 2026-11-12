#!/usr/bin/env bash
# 调用 Isaac Sim gRPC 服务的便捷封装（BenchForge 侧）。
# 用法:
#   ./call_client.sh                      # 默认发送 "ping"
#   ./call_client.sh "hello isaac"        # 发送自定义 info
#   ./call_client.sh --endpoint 10.0.0.5:50051 "hello"
# 端点默认读 config/benchforge.local.json 的 isaac.grpc。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../../.." && pwd)"
PY="$ROOT/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "未找到 $PY，请先运行 ./start.sh 或 spatialforge_app.py setup" >&2
  exit 1
fi

# 无参数时给一个默认 info，避免 argparse 报 "the following arguments are required: info"
if [[ $# -eq 0 ]]; then
  set -- "ping"
fi

exec "$PY" "$DIR/client.py" "$@"
