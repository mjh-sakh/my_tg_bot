# Deploy to the Netcup VPS

This project is deployed to the VPS by copying the repo over SSH with `rsync` and running it with Docker Compose.

## Prerequisites

On the local machine:
- SSH access to host `netcup` from `~/.ssh/config`
- `rsync`
- Docker only if you want to validate the Compose stack locally before upload

On the VPS:
- Docker
- Docker Compose
- app directory: `/opt/my_tg_bot`

## Production config

Start from the current local `.env` and copy it to the server:

```bash
rsync -av .env netcup:/opt/my_tg_bot/.env
```

Then make sure `/opt/my_tg_bot/.env` contains production values for at least:
- `TELEGRAM_TOKEN`
- `OPENROUTER_KEY`
- `TOGETHER_API_KEY`
- `ADMIN_ID`
- `MONGO_URI=mongodb://mongo:27017`

## Upload application files

From the repository root:

```bash
rsync -av \
  --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.pytest_cache' \
  --exclude '.idea' \
  --exclude '__pycache__' \
  --exclude '.env' \
  ./ netcup:/opt/my_tg_bot/
```

## Start or update the stack

```bash
ssh netcup 'cd /opt/my_tg_bot && docker compose up -d --build'
```

Or use the helper script from the repo root:

```bash
./scripts/deploy.sh
```

## Check status

```bash
ssh netcup 'cd /opt/my_tg_bot && docker compose ps'
ssh netcup 'cd /opt/my_tg_bot && docker compose logs --tail=100 bot'
ssh netcup 'cd /opt/my_tg_bot && docker compose logs --tail=100 mongo'
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
- check that both `bot` and `mongo` are running
- confirm the bot responds to `/start`
- confirm the bot responds to `/whoami`
- if credentials are ready, test one `/chat` request and one voice message
