# About
Personal Telegram bot that is in a heavy development stage.

Features in place:
- transcription of voice messages using Together AI (`nvidia/parakeet-tdt-0.6b-v3`)
- chatting with an LLM in private messages, keeping context by replying to prior bot or user turns
- direct private voice/audio messages can enter the same AI chat flow as text messages
- visible transcript messages are stored as Telegram aliases of the canonical voice turn, so replying to either the original voice message or the transcript continues the same conversation

Secondary features:
- user authorization

Persistence:
- local SQLite database at `data/bot.sqlite`
- in production, `/opt/my_tg_bot/data` is bind-mounted to `/app/data`

## Tooling

This project now uses:
- `mise` for Python runtime pinning
- `direnv` for loading `.env`
- `uv` for Python environments, locking, and commands

## Setup

```bash
mise install
mise exec -- direnv exec . uv venv
mise exec -- direnv exec . uv sync
```

This repository no longer uses Node or `wrangler`.

## Run

```bash
mise exec -- direnv exec . uv run python bot/main.py
```

## Test

```bash
mise exec -- direnv exec . uv run pytest
```

## Deployment

Deployment instructions for the Netcup VPS are in `docs/deploy.md`.
A deploy helper is available at `scripts/deploy.sh`.
