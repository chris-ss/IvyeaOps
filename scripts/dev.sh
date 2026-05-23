#!/usr/bin/env bash
# Run backend + frontend in dev mode.
# Backend: 127.0.0.1:8001 (FastAPI with hot reload)
# Frontend: 127.0.0.1:5174 (Vite dev server proxying /api to backend)
#
# Open http://127.0.0.1:5174 in a browser (or SSH-tunnel).
set -e
cd "$(dirname "$0")/.."

# Backend in background
(
  cd server
  OPSHUB_DEV=1 python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
) &
BACK=$!
trap "kill $BACK 2>/dev/null || true" EXIT

# Frontend in foreground
cd client
npm run dev
