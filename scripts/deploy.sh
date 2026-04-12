#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-netcup}"
REMOTE_DIR="${REMOTE_DIR:-/opt/my_tg_bot}"

cd "$(dirname "$0")/.."

rsync -av \
  --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.pytest_cache' \
  --exclude '.idea' \
  --exclude '__pycache__' \
  --exclude '.env' \
  --exclude '.pi-runtime' \
  ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

rsync -av .env "${REMOTE_HOST}:${REMOTE_DIR}/.env"

ssh "${REMOTE_HOST}" "chmod 600 '${REMOTE_DIR}/.env' && chown root:root '${REMOTE_DIR}/.env' && cd '${REMOTE_DIR}' && docker compose up -d --build"
