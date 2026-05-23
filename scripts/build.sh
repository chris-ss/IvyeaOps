#!/usr/bin/env bash
# Build the React client into client/dist.
# After this, `systemctl restart ops-hub` (FastAPI will serve dist/).
set -e
cd "$(dirname "$0")/../client"
[ -d node_modules ] || npm install
npm run build
echo "Built into $(pwd)/dist"
