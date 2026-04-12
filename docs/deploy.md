# Deploy to the Netcup VPS

This project is deployed to the VPS by copying only the files needed for the Docker build over SSH with `rsync` and then running Docker Compose on the host.

## Runtime shape

- one Docker Compose service: `bot`
- persistent SQLite file in the container: `/app/data/bot.sqlite`
- host data directory bound into the container: `/opt/my_tg_bot/data` → `/app/data`
- local dev DB path in the repo: `data/bot.sqlite`

## Prerequisites

On the local machine:
- SSH access to host `netcup` from `~/.ssh/config`
- `rsync`
- Docker only if you want to validate the Compose stack locally before upload

On the VPS:
- Docker
- Docker Compose
- app directory: `/opt/my_tg_bot`
- persistent data directory: `/opt/my_tg_bot/data`

## Production config

Start from the current local `.env` and copy it to the server:

```bash
rsync -zv .env netcup:/opt/my_tg_bot/.env
```

Then make sure `/opt/my_tg_bot/.env` contains production values for at least:
- `TELEGRAM_TOKEN`
- `OPENROUTER_KEY`
- `TOGETHER_API_KEY`
- `ADMIN_ID`

No DB connection env var is needed. The app uses the fixed SQLite path exposed by the bind mount.

## Upload application files

From the repository root, sync only the files required to build and run the container on the VPS:

```bash
ssh netcup 'mkdir -p /opt/my_tg_bot/data'

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
  ./ netcup:/opt/my_tg_bot/
```

This keeps deploys fast because it avoids uploading docs, tests, local tooling files, caches, and other files that are irrelevant on the server. The server-side Docker build still benefits from Docker layer caching when `pyproject.toml` and `uv.lock` do not change.

## Start or update the stack

```bash
ssh netcup "mkdir -p /opt/my_tg_bot/data && cd /opt/my_tg_bot && docker compose up -d --build --remove-orphans"
```

Or use the helper script from the repo root, which performs the focused `rsync` upload and then rebuilds the stack:

```bash
./scripts/deploy.sh
```

## Check status

```bash
ssh netcup 'cd /opt/my_tg_bot && docker compose ps'
ssh netcup 'cd /opt/my_tg_bot && docker compose logs --tail=100 bot'
ssh netcup 'ls -lah /opt/my_tg_bot/data'
```

## Restart

```bash
ssh netcup 'cd /opt/my_tg_bot && docker compose restart bot'
```

## Stop

```bash
ssh netcup 'cd /opt/my_tg_bot && docker compose down'
```

## Verify

After startup:
- check that the `bot` service is running
- confirm `/opt/my_tg_bot/data/bot.sqlite` exists on the host after the bot starts
- confirm the bot responds to `/start`
- confirm the bot responds to `/whoami`
- if credentials are ready, test one `/chat` request and one voice message
- restart or recreate the container and confirm `/opt/my_tg_bot/data/bot.sqlite` is still present
