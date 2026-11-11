#!/usr/bin/env bash
# ============================================================================
# SilentTrack AI — Safe Linux Shutdown Script
# Stops ONLY the backend and frontend processes started by SilentTrack AI.
# ============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"

BOLD="\033[1m"
GREEN="\033[1;32m"
CYAN="\033[1;36m"
YELLOW="\033[1;33m"
RESET="\033[0m"

stop_pid_file() {
  local label="$1"
  local pid_file="$2"
  local match_token="$3"

  if [ ! -f "$pid_file" ]; then
    return 0
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null | tr -d '[:space:]' || true)"
  if [ -z "$pid" ]; then
    rm -f "$pid_file"
    return 0
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    return 0
  fi

  # Verify the process belongs to SilentTrack AI before stopping
  local cmdline=""
  if [ -r "/proc/$pid/cmdline" ]; then
    cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  else
    cmdline="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  fi

  if [[ "$cmdline" != *"$ROOT_DIR"* ]] && [[ "$cmdline" != *"$match_token"* ]]; then
    echo -e "${YELLOW}[WARN]${RESET} Skipping PID $pid ($label): process does not match SilentTrack AI."
    rm -f "$pid_file"
    return 0
  fi

  echo -e "${CYAN}[INFO]${RESET} Stopping SilentTrack AI $label (PID $pid)..."

  # Find direct child processes spawned by this PID (e.g., esbuild under vite)
  local children=""
  if command -v pgrep >/dev/null 2>&1; then
    children="$(pgrep -P "$pid" 2>/dev/null || true)"
  fi

  kill -TERM "$pid" 2>/dev/null || true
  for child in $children; do
    kill -TERM "$child" 2>/dev/null || true
  done

  # Wait up to 5 seconds for graceful shutdown
  for _ in $(seq 1 25); do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done

  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
  for child in $children; do
    if kill -0 "$child" 2>/dev/null; then
      kill -KILL "$child" 2>/dev/null || true
    fi
  done

  rm -f "$pid_file"
  echo -e "${GREEN}  ✓${RESET} Stopped $label"
}

mkdir -p "$RUNTIME_DIR"

STOPPED_ANY=false
if [ -f "$RUNTIME_DIR/frontend.pid" ] || [ -f "$RUNTIME_DIR/backend.pid" ]; then
  STOPPED_ANY=true
fi

stop_pid_file "Frontend (Vite)" "$RUNTIME_DIR/frontend.pid" "vite"
stop_pid_file "Backend (FastAPI)" "$RUNTIME_DIR/backend.pid" "app.main:app"

if [ "$STOPPED_ANY" = false ]; then
  echo -e "${CYAN}[INFO]${RESET} No running SilentTrack AI instances found."
else
  echo -e "${GREEN}${BOLD}SilentTrack AI has been stopped safely.${RESET}"
fi
