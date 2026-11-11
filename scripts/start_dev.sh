#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/home/mohamed/.nvm/versions/node/v22.23.3/bin:$ROOT_DIR/tools/ffmpeg:$PATH"

echo "===================================================="
echo " Starting SilentTrack AI (Backend + Frontend)"
echo "===================================================="

cleanup() {
  echo ""
  echo "Shutting down SilentTrack AI services..."
  kill $(jobs -p) 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$ROOT_DIR/backend"
PYTHONPATH="$ROOT_DIR/backend" "$ROOT_DIR/.venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

cd "$ROOT_DIR/frontend"
npm run dev -- --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!

echo " -> Backend API:  http://localhost:8000 (Docs: http://localhost:8000/docs)"
echo " -> Frontend UI:  http://localhost:5173"
echo "Press Ctrl+C to stop both servers."

wait "$BACKEND_PID" "$FRONTEND_PID"
