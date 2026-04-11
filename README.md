# About
Personal Telegram bot that is in a heavy development stage.

Features in place:
- transcription of voice messages using Replicate API (`nvidia/parakeet-rnnt-1.1b`)
- chatting with LLM model, keeping the context by replying to the bot answers

Secondary features:
- user authorization

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
