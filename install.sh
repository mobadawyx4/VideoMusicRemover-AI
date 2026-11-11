#!/usr/bin/env bash
# ============================================================================
# SilentTrack AI — Cross-Distro Linux Installer
# Supports Ubuntu, Debian, Linux Mint, Pop!_OS, Fedora, Arch, and compatible distros
# ============================================================================
set -euo pipefail

# Installer options
AUTO_LAUNCH=true
for arg in "$@"; do
  case "$arg" in
    --no-launch) AUTO_LAUNCH=false ;;
    -h|--help)
      echo "Usage: ./install.sh [--no-launch]"
      echo "  --no-launch  Install without starting the application"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg"
      exit 2
      ;;
  esac
done

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

info()  { echo -e "${CYAN}[INFO]${RESET} $*"; }
ok()    { echo -e "${GREEN}  ✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET} $*"; }
fail()  { echo -e "\n${RED}[ERROR]${RESET} $*\n" >&2; exit 1; }

echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  SilentTrack AI — Automated Linux Installation${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo ""

# ----------------------------------------------------------------------------
# [1/5] Checking prerequisites...
# ----------------------------------------------------------------------------
echo -e "${BOLD}[1/5] Checking prerequisites...${RESET}"

DISTRO_NAME="Linux"
DISTRO_ID="linux"
if [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  DISTRO_NAME="${PRETTY_NAME:-${NAME:-Linux}}"
  DISTRO_ID="${ID:-linux}"
fi
ok "Detected operating system: $DISTRO_NAME"

# Check available disk space (require >= 500 MB for safe setup)
FREE_MB="$(df -Pm "$ROOT_DIR" | awk 'NR==2 {print $4}')"
if [ -n "$FREE_MB" ] && [ "$FREE_MB" -lt 500 ]; then
  fail "Insufficient disk space (${FREE_MB} MB free). Please free up at least 500 MB and try again."
fi
ok "Available disk space: ${FREE_MB} MB"

# Find Python 3.10 - 3.12
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
    case "$ver" in
      3.10|3.11|3.12)
        PYTHON_BIN="$(command -v "$candidate")"
        PYTHON_VER="$("$PYTHON_BIN" --version 2>&1)"
        break
        ;;
    esac
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo ""
  echo -e "${YELLOW}Helpful installation instructions for Python 3.10–3.12:${RESET}"
  echo "  Ubuntu / Debian / Linux Mint:  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  echo "  Fedora:                        sudo dnf install -y python3 python3-pip"
  echo "  Arch Linux:                    sudo pacman -S python python-pip"
  fail "Python 3.10, 3.11, or 3.12 was not found on your system."
fi
ok "Found $PYTHON_VER ($PYTHON_BIN)"

# Check python3-venv availability
if ! "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
  echo ""
  echo -e "${YELLOW}The Python 'venv' module is required:${RESET}"
  echo "  Ubuntu / Debian / Linux Mint:  sudo apt update && sudo apt install -y python3-venv"
  fail "Python venv module is missing."
fi

# Check Node.js & npm
if ! command -v node >/dev/null 2>&1; then
  echo ""
  echo -e "${YELLOW}Helpful installation instructions for Node.js (v18+):${RESET}"
  echo "  Ubuntu / Debian / Linux Mint:  sudo apt update && sudo apt install -y nodejs npm"
  echo "  Or via NVM:                    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash && nvm install 22"
  fail "Node.js is not installed or not in PATH."
fi
NODE_VER="$(node --version)"
ok "Found Node.js $NODE_VER ($(command -v node))"

if ! command -v npm >/dev/null 2>&1; then
  echo ""
  echo -e "${YELLOW}Helpful installation instructions for npm:${RESET}"
  echo "  Ubuntu / Debian / Linux Mint:  sudo apt update && sudo apt install -y npm"
  fail "npm is not installed or not in PATH."
fi
NPM_VER="$(npm --version)"
ok "Found npm v$NPM_VER ($(command -v npm))"

# Check FFmpeg and FFprobe
FFMPEG_BIN=""
FFPROBE_BIN=""
if [ -x "$ROOT_DIR/tools/ffmpeg/ffmpeg" ] && [ -x "$ROOT_DIR/tools/ffmpeg/ffprobe" ]; then
  FFMPEG_BIN="$ROOT_DIR/tools/ffmpeg/ffmpeg"
  FFPROBE_BIN="$ROOT_DIR/tools/ffmpeg/ffprobe"
elif command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  FFMPEG_BIN="$(command -v ffmpeg)"
  FFPROBE_BIN="$(command -v ffprobe)"
fi

if [ -z "$FFMPEG_BIN" ] || [ -z "$FFPROBE_BIN" ]; then
  echo ""
  echo -e "${YELLOW}FFmpeg and FFprobe are required for video/audio processing.${RESET}"
  echo "Install FFmpeg with your package manager:"
  echo "  Ubuntu / Debian / Linux Mint:  sudo apt update && sudo apt install -y ffmpeg"
  echo "  Fedora:                        sudo dnf install -y ffmpeg"
  echo "  Arch Linux:                    sudo pacman -S ffmpeg"
  fail "FFmpeg / FFprobe not found."
fi
ok "Found FFmpeg ($FFMPEG_BIN)"
ok "Found FFprobe ($FFPROBE_BIN)"
echo ""

# ----------------------------------------------------------------------------
# [2/5] Setting up Python environment...
# ----------------------------------------------------------------------------
echo -e "${BOLD}[2/5] Setting up Python environment...${RESET}"

VENV_DIR="$ROOT_DIR/.venv"
if [ -x "$VENV_DIR/bin/python" ]; then
  ok "Existing Python virtual environment detected at .venv (reusing)"
else
  info "Creating Python virtual environment at .venv..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  ok "Created virtual environment at .venv"
fi

# Create .env from .env.example if missing (preserve existing user configuration)
if [ -f "$ROOT_DIR/.env" ]; then
  ok "Existing .env configuration found (preserved)"
elif [ -f "$ROOT_DIR/.env.example" ]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  ok "Created .env from .env.example (defaulting to localhost)"
fi

mkdir -p "$ROOT_DIR/data/jobs" "$ROOT_DIR/data/models" "$ROOT_DIR/.runtime"
echo ""

# ----------------------------------------------------------------------------
# [3/5] Installing backend dependencies...
# ----------------------------------------------------------------------------
echo -e "${BOLD}[3/5] Installing backend dependencies...${RESET}"

REQ_FILE="$ROOT_DIR/backend/requirements.txt"
REQ_STAMP="$VENV_DIR/.requirements.sha256"
CURRENT_REQ_HASH="$(sha256sum "$REQ_FILE" | awk '{print $1}')"
INSTALLED_REQ_HASH=""
if [ -f "$REQ_STAMP" ]; then
  INSTALLED_REQ_HASH="$(cat "$REQ_STAMP" 2>/dev/null || true)"
fi

BACKEND_IMPORTS_OK=false
if "$VENV_DIR/bin/python" -c "import fastapi, uvicorn, torch, soundfile, huggingface_hub, safetensors, aiofiles, pytest, httpx" >/dev/null 2>&1; then
  BACKEND_IMPORTS_OK=true
fi

if [ "$BACKEND_IMPORTS_OK" = true ] && [ "$CURRENT_REQ_HASH" = "$INSTALLED_REQ_HASH" ]; then
  ok "Backend Python dependencies are already installed and up to date"
elif [ "$BACKEND_IMPORTS_OK" = true ] && [ -z "$INSTALLED_REQ_HASH" ]; then
  echo "$CURRENT_REQ_HASH" > "$REQ_STAMP"
  ok "Verified existing backend Python packages in .venv"
else
  info "Installing Python packages from backend/requirements.txt..."
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENV_DIR/bin/python" -r "$REQ_FILE"
  else
    "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null 2>&1 || true
    "$VENV_DIR/bin/pip" install -r "$REQ_FILE"
  fi
  echo "$CURRENT_REQ_HASH" > "$REQ_STAMP"
  ok "Installed backend Python dependencies"
fi

info "Verifying TIGER-DnR AI audio separation model cache..."
PYTHONPATH="$ROOT_DIR/backend" "$VENV_DIR/bin/python" -c "
from app.services.separation import separator_service
snap = separator_service.ensure_model_cached()
print(f'  ✓ AI model ready in local cache: {snap}')
"
echo ""

# ----------------------------------------------------------------------------
# [4/5] Installing frontend dependencies...
# ----------------------------------------------------------------------------
echo -e "${BOLD}[4/5] Installing frontend dependencies...${RESET}"

FRONTEND_DIR="$ROOT_DIR/frontend"
LOCK_FILE="$FRONTEND_DIR/package-lock.json"
if [ ! -f "$LOCK_FILE" ]; then
  LOCK_FILE="$FRONTEND_DIR/package.json"
fi
NPM_STAMP="$FRONTEND_DIR/node_modules/.package.sha256"
CURRENT_NPM_HASH="$(sha256sum "$LOCK_FILE" | awk '{print $1}')"
INSTALLED_NPM_HASH=""
if [ -f "$NPM_STAMP" ]; then
  INSTALLED_NPM_HASH="$(cat "$NPM_STAMP" 2>/dev/null || true)"
fi

if [ -x "$FRONTEND_DIR/node_modules/.bin/vite" ] && [ "$CURRENT_NPM_HASH" = "$INSTALLED_NPM_HASH" ]; then
  ok "Frontend npm dependencies are already installed and up to date"
elif [ -x "$FRONTEND_DIR/node_modules/.bin/vite" ] && [ -z "$INSTALLED_NPM_HASH" ]; then
  echo "$CURRENT_NPM_HASH" > "$NPM_STAMP"
  ok "Verified existing frontend node_modules"
else
  info "Installing frontend packages in frontend/..."
  (cd "$FRONTEND_DIR" && npm install --no-audit --no-fund)
  echo "$CURRENT_NPM_HASH" > "$NPM_STAMP"
  ok "Installed frontend npm dependencies"
fi
echo ""

# ----------------------------------------------------------------------------
# [5/5] Validating installation...
# ----------------------------------------------------------------------------
echo -e "${BOLD}[5/5] Validating installation...${RESET}"

PYTHONPATH="$ROOT_DIR/backend" "$VENV_DIR/bin/python" -c "
from app.main import app
from app.services.media_service import check_ffmpeg_installed
from app.services.separation import separator_service

ff_ok, fp_ok = check_ffmpeg_installed()
assert ff_ok and fp_ok, 'FFmpeg or FFprobe validation failed'
assert separator_service.is_model_available(), 'TIGER-DnR model cache validation failed'
print('  ✓ FastAPI application & routes verified')
print('  ✓ FFmpeg & FFprobe integration verified')
print(f'  ✓ TIGER-DnR AI model verified (device: {separator_service.device})')
"
test -x "$FRONTEND_DIR/node_modules/.bin/vite" && ok "React + Vite frontend verified"

echo ""
echo -e "${GREEN}${BOLD}SUCCESS:${RESET}"
echo -e "${BOLD}VideoMusicRemover AI installation completed!${RESET}"
echo ""

if [ "$AUTO_LAUNCH" = true ]; then
  echo -e "${CYAN}Starting the application automatically...${RESET}"
  echo ""
  "$ROOT_DIR/start.sh"
else
  echo "Installation completed without launching."
  echo "To start later, run: ./start.sh"
  echo "Application URL: http://localhost:5173"
fi
echo ""
