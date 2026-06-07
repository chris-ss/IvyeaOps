#!/usr/bin/env bash
# Start IvyeaOps (Linux/macOS). Host/port are read from server/.env.
#
# Usage:
#   bash scripts/start.sh
set -euo pipefail

cd "$(dirname "$0")/../server"

if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 server/.venv —— 请先运行：bash scripts/install.sh" >&2
  exit 1
fi

exec .venv/bin/python -m app.main
