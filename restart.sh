#!/usr/bin/env bash
# 一键重启：重启 SpatialForge 与 DSH Web；同一 PostgreSQL 项目继续运行。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$ROOT/shutdown.sh" --for-restart
exec "$ROOT/start.sh"
