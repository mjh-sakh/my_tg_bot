#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-netcup}"
REMOTE_DIR="${REMOTE_DIR:-/opt/my_tg_bot}"

cd "$(dirname "$0")/.."

ssh "${REMOTE_HOST}" "mkdir -p '${REMOTE_DIR}/data'"

rsync -rlzv \
  --delete \
  --prune-empty-dirs \
  --exclude '__pycache__/' \
  --exclude '*.py[cod]' \
  --include '/.dockerignore' \
  --include '/Dockerfile' \
  --include '/docker-compose.yml' \
  --include '/pyproject.toml' \
  --include '/uv.lock' \
  --include '/bot/' \
  --include '/bot/***' \
  --exclude '*' \
  ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

rsync -zv .env "${REMOTE_HOST}:${REMOTE_DIR}/.env"

ssh "${REMOTE_HOST}" "chmod 700 '${REMOTE_DIR}/data' && chmod 600 '${REMOTE_DIR}/.env' && chown root:root '${REMOTE_DIR}/.env' && cd '${REMOTE_DIR}' && docker compose up -d --build --remove-orphans"
