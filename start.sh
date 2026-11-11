#!/usr/bin/env bash
# ============================================================================
# SilentTrack AI — One-Command Linux Startup Script
# Usage: ./start.sh [--lan] [--no-browser] [--daemon]
# ============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Include NVM Node.js, ~/.local/bin, and bundled tools/ffmpeg in PATH if present
if [ -d "$HOME/.nvm/versions/node" ]; then
  LATEST_NVM_NODE="$(find "$HOME/.nvm/versions/node" -maxdepth 1 -mindepth 1 -type d | sort -V | tail -n 1 || true)"
  if [ -n "$LATEST_NVM_NODE" ] && [ -d "$LATEST_NVM_NODE/bin" ]; then
    export PATH="$LATEST_NVM_NODE/bin:$PATH"
  fi
fi
export PATH="$ROOT_DIR/tools/ffmpeg:$HOME/.local/bin:$PATH"

BOLD="\033[1m"
GREEN="\033[1;32m"
CYAN="\033[1;36m"
YELLOW="\033[1;33m"
RED="\033[1;31m"
RESET="\033[0m"

LAN_MODE=false
OPEN_BROWSER=true
DAEMON_MODE=false

for arg in "$@"; do
  case "$arg" in
    --lan)
      LAN_MODE=true
      ;;
    --no-browser)
      OPEN_BROWSER=false
      ;;
    --daemon)
      DAEMON_MODE=true
      OPEN_BROWSER=false
      ;;
    -h|--help)
      echo "Usage: ./start.sh [--lan] [--no-browser] [--daemon]"
      echo "  --lan         Enable LAN access for other devices on your local network"
      echo "  --no-browser  Do not automatically open the web browser on startup"
      echo "  --daemon      Start services in the background and exit after health checks"
      exit 0
      ;;
  esac
done

# Load .env settings if present
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env"
  set +a
fi

if [ "${ENABLE_LAN_ACCESS:-false}" = "true" ] || [ "${ENABLE_LAN_ACCESS:-false}" = "1" ]; then
  LAN_MODE=true
fi

BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${PORT:-8000}"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

if [ "$LAN_MODE" = true ]; then
  FRONTEND_HOST="0.0.0.0"
fi

# 1. Verify installation
if [ ! -x "$ROOT_DIR/.venv/bin/python" ] || [ ! -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ]; then
  echo -e "${YELLOW}[INFO]${RESET} First-time setup required. Running ./install.sh..."
  "$ROOT_DIR/install.sh"
fi

mkdir -p "$ROOT_DIR/.runtime" "$ROOT_DIR/data/jobs" "$ROOT_DIR/data/models"

# Stop any previous stale SilentTrack AI instance before starting
if [ -f "$ROOT_DIR/.runtime/backend.pid" ] || [ -f "$ROOT_DIR/.runtime/frontend.pid" ]; then
  "$ROOT_DIR/stop.sh" >/dev/null 2>&1 || true
fi

echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  Starting SilentTrack AI${RESET}"
echo -e "${BOLD}============================================================${RESET}"

# 2. Start FastAPI Backend
echo -e "${CYAN}[1/4]${RESET} Starting FastAPI backend on http://${BACKEND_HOST}:${BACKEND_PORT}..."
PYTHONPATH="$ROOT_DIR/backend" "$ROOT_DIR/.venv/bin/python" -m uvicorn app.main:app \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" \
  >"$ROOT_DIR/.runtime/backend.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$ROOT_DIR/.runtime/backend.pid"

# 3. Start React/Vite Frontend
echo -e "${CYAN}[2/4]${RESET} Starting React/Vite frontend on http://localhost:${FRONTEND_PORT}..."
(
  cd "$ROOT_DIR/frontend"
  exec env VITE_DEV_HOST="$FRONTEND_HOST" VITE_DEV_PORT="$FRONTEND_PORT" VITE_BACKEND_ORIGIN="http://127.0.0.1:${BACKEND_PORT}" \
    "$ROOT_DIR/frontend/node_modules/.bin/vite" --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" \
    >"$ROOT_DIR/.runtime/frontend.log" 2>&1
) &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$ROOT_DIR/.runtime/frontend.pid"

# 4. Check Backend Health
echo -e "${CYAN}[3/4]${RESET} Verifying backend API health (http://127.0.0.1:${BACKEND_PORT}/api/health)..."
BACKEND_READY=false
for _ in $(seq 1 40); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo -e "${RED}[ERROR]${RESET} Backend exited unexpectedly. Recent log output:"
    tail -n 25 "$ROOT_DIR/.runtime/backend.log" >&2 || true
    "$ROOT_DIR/stop.sh" >/dev/null 2>&1 || true
    exit 1
  fi
  if curl -sf "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    BACKEND_READY=true
    break
  fi
  sleep 0.5
done

if [ "$BACKEND_READY" = false ]; then
  echo -e "${RED}[ERROR]${RESET} Backend did not become healthy in time. Log output:"
  tail -n 25 "$ROOT_DIR/.runtime/backend.log" >&2 || true
  "$ROOT_DIR/stop.sh" >/dev/null 2>&1 || true
  exit 1
fi
echo -e "${GREEN}  ✓${RESET} Backend API is healthy"

# 5. Check Frontend Availability
echo -e "${CYAN}[4/4]${RESET} Verifying frontend availability (http://localhost:${FRONTEND_PORT})..."
FRONTEND_READY=false
for _ in $(seq 1 40); do
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo -e "${RED}[ERROR]${RESET} Frontend exited unexpectedly. Recent log output:"
    tail -n 25 "$ROOT_DIR/.runtime/frontend.log" >&2 || true
    "$ROOT_DIR/stop.sh" >/dev/null 2>&1 || true
    exit 1
  fi
  if curl -sf "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null 2>&1; then
    FRONTEND_READY=true
    break
  fi
  sleep 0.5
done

if [ "$FRONTEND_READY" = false ]; then
  echo -e "${RED}[ERROR]${RESET} Frontend did not become ready in time. Log output:"
  tail -n 25 "$ROOT_DIR/.runtime/frontend.log" >&2 || true
  "$ROOT_DIR/stop.sh" >/dev/null 2>&1 || true
  exit 1
fi
echo -e "${GREEN}  ✓${RESET} Frontend server is online"

echo ""
echo -e "${GREEN}${BOLD}SUCCESS:${RESET}"
echo -e "${BOLD}SilentTrack AI is ready!${RESET}"
echo ""
echo -e "Open:"
echo -e "  ${CYAN}http://localhost:${FRONTEND_PORT}${RESET}"
echo ""
echo -e "Backend API:    http://127.0.0.1:${BACKEND_PORT}"
echo -e "Health Check:   http://127.0.0.1:${BACKEND_PORT}/api/health"

if [ "$LAN_MODE" = true ]; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  if [ -n "$LAN_IP" ]; then
    echo -e "LAN Access URL: ${CYAN}http://${LAN_IP}:${FRONTEND_PORT}${RESET} (accessible to devices on your Wi-Fi/LAN)"
  fi
fi
echo ""

# Open default browser automatically when running interactively with a display
if [ "$OPEN_BROWSER" = true ] && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:${FRONTEND_PORT}" >/dev/null 2>&1 || true
  fi
fi

if [ "$DAEMON_MODE" = true ]; then
  echo -e "Services are running in the background. Stop them anytime with: ${CYAN}./stop.sh${RESET}"
  exit 0
fi

echo -e "Press ${BOLD}Ctrl+C${RESET} to stop SilentTrack AI (or run ${CYAN}./stop.sh${RESET} from another terminal)."

cleanup_on_exit() {
  echo ""
  "$ROOT_DIR/stop.sh"
}
trap cleanup_on_exit INT TERM

# Wait while both processes remain alive
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

cleanup_on_exit
