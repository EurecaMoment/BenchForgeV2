#!/usr/bin/env bash
# 一键重启：保留 PostgreSQL，重启 SpatialForge 与 DSH Web
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$ROOT/shutdown.sh" --keep-db
exec "$ROOT/start.sh"
