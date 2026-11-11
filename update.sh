#!/usr/bin/env bash
# ============================================================================
# SilentTrack AI — Safe Linux Update Script
# Preserves .env user configuration and data/ (cached models & jobs)
# ============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BOLD="\033[1m"
GREEN="\033[1;32m"
CYAN="\033[1;36m"
YELLOW="\033[1;33m"
RESET="\033[0m"

echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  SilentTrack AI — Safe Local Update${RESET}"
echo -e "${BOLD}============================================================${RESET}"

# 1. Stop running SilentTrack AI processes safely
if [ -x "$ROOT_DIR/stop.sh" ]; then
  "$ROOT_DIR/stop.sh"
fi

# 2. Backup .env if present
ENV_BACKUP=""
if [ -f "$ROOT_DIR/.env" ]; then
  ENV_BACKUP="$ROOT_DIR/.runtime/.env.backup"
  mkdir -p "$ROOT_DIR/.runtime"
  cp "$ROOT_DIR/.env" "$ENV_BACKUP"
  echo -e "${GREEN}  ✓${RESET} Backed up custom .env configuration"
fi

# 3. Pull latest Git commits if a remote repository is configured
if [ -d "$ROOT_DIR/.git" ] && command -v git >/dev/null 2>&1; then
  if git remote get-url origin >/dev/null 2>&1; then
    echo -e "${CYAN}[INFO]${RESET} Pulling latest updates from Git remote..."
    if git pull --ff-only; then
      echo -e "${GREEN}  ✓${RESET} Repository updated from origin"
    else
      echo -e "${YELLOW}[WARN]${RESET} Could not fast-forward from Git remote; keeping local working tree."
    fi
  else
    echo -e "${CYAN}[INFO]${RESET} No Git remote configured; skipping git pull and refreshing dependencies."
  fi
fi

# 4. Restore .env if needed
if [ -n "$ENV_BACKUP" ] && [ -f "$ENV_BACKUP" ] && [ ! -f "$ROOT_DIR/.env" ]; then
  cp "$ENV_BACKUP" "$ROOT_DIR/.env"
fi

# 5. Re-validate and sync backend & frontend dependencies
"$ROOT_DIR/install.sh"

echo -e "${GREEN}${BOLD}Update complete! Your configuration (.env) and cached models (data/) were preserved.${RESET}"
