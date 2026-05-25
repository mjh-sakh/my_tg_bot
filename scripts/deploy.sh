#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-netcup}"
REMOTE_DIR="${REMOTE_DIR:-/srv/my_tg_bot/app}"
REMOTE_DATA_DIR="${REMOTE_DATA_DIR:-/var/lib/my_tg_bot/data}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-/etc/my_tg_bot/my_tg_bot.env}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-my_tg_bot}"
MY_TG_BOT_IMAGE="${MY_TG_BOT_IMAGE:-my-tg-bot:manual}"
MY_TG_BOT_UID="${MY_TG_BOT_UID:-101}"
MY_TG_BOT_GID="${MY_TG_BOT_GID:-104}"
EXPECTED_REMOTE="${EXPECTED_REMOTE:-git@github.com:mjh-sakh/my_tg_bot.git}"

cd "$(dirname "$0")/.."

remote_quote() {
  printf '%q' "$1"
}

remote_dir_q="$(remote_quote "$REMOTE_DIR")"
remote_data_dir_q="$(remote_quote "$REMOTE_DATA_DIR")"
remote_env_file_q="$(remote_quote "$REMOTE_ENV_FILE")"
expected_remote_q="$(remote_quote "$EXPECTED_REMOTE")"

ssh "${REMOTE_HOST}" "
  set -euo pipefail
  install -d -m 755 -o root -g root ${remote_dir_q}
  install -d -m 750 -o ${MY_TG_BOT_UID} -g ${MY_TG_BOT_GID} ${remote_data_dir_q}
  test -f ${remote_env_file_q}
  test -d ${remote_dir_q}/.git
  test \"\$(git -C ${remote_dir_q} remote get-url origin)\" = ${expected_remote_q}
"

rsync -rlzv \
  --delete \
  --prune-empty-dirs \
  --filter='P /.git/***' \
  --filter='P /.git/' \
  --filter='P /.env' \
  --filter='P /data/***' \
  --filter='P /data/' \
  --exclude '__pycache__/' \
  --exclude '*.py[cod]' \
  --exclude '.git/' \
  --exclude '.gitignore' \
  --exclude '.env' \
  --exclude 'data/' \
  --include '/.dockerignore' \
  --include '/Dockerfile' \
  --include '/docker-compose.yml' \
  --include '/pyproject.toml' \
  --include '/uv.lock' \
  --include '/bot/' \
  --include '/bot/***' \
  --exclude '*' \
  ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

ssh "${REMOTE_HOST}" "
  set -euo pipefail
  test -d ${remote_dir_q}/.git
  test \"\$(git -C ${remote_dir_q} remote get-url origin)\" = ${expected_remote_q}
  git -C ${remote_dir_q} status --short
  cd ${remote_dir_q}
  COMPOSE_PROJECT_NAME=$(printf '%q' "$COMPOSE_PROJECT_NAME") \
  MY_TG_BOT_IMAGE=$(printf '%q' "$MY_TG_BOT_IMAGE") \
  MY_TG_BOT_ENV_FILE=${remote_env_file_q} \
  MY_TG_BOT_DATA_DIR=${remote_data_dir_q} \
  MY_TG_BOT_UID=$(printf '%q' "$MY_TG_BOT_UID") \
  MY_TG_BOT_GID=$(printf '%q' "$MY_TG_BOT_GID") \
  docker compose down
  COMPOSE_PROJECT_NAME=$(printf '%q' "$COMPOSE_PROJECT_NAME") \
  MY_TG_BOT_IMAGE=$(printf '%q' "$MY_TG_BOT_IMAGE") \
  MY_TG_BOT_ENV_FILE=${remote_env_file_q} \
  MY_TG_BOT_DATA_DIR=${remote_data_dir_q} \
  MY_TG_BOT_UID=$(printf '%q' "$MY_TG_BOT_UID") \
  MY_TG_BOT_GID=$(printf '%q' "$MY_TG_BOT_GID") \
  docker compose up -d --build --remove-orphans
"
