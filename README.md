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

### Reasoning effort

Set `REASONING_EFFORT` in `.env` to pass OpenRouter `reasoning.effort` to the
assistant model (for example, `REASONING_EFFORT=low`). Leave it blank or unset to
use the provider default. Supported values depend on the selected model.
Restart the bot after changing its environment.

## Test

```bash
mise exec -- direnv exec . uv run pytest
```

The real OpenRouter chat test also makes paid API requests and is opt-in:

```bash
mise exec -- direnv exec . env RUN_OPENROUTER_E2E=1 uv run pytest tests/e2e/test_chat_openrouter_e2e.py -q
```

It uses `DEFAULT_MODEL` and `REASONING_EFFORT`; set `OPENROUTER_E2E_MODEL` to
override the model for the test. `OPENROUTER_KEY` is required.

The real Together STT test is skipped by default because it makes paid API requests.
Opt in with `RUN_TOGETHER_E2E=1`; `TOGETHER_API_KEY` is required:

```bash
mise exec -- direnv exec . env RUN_TOGETHER_E2E=1 uv run pytest tests/e2e/test_transcription_together_e2e.py -q
```

It transcribes a bundled synthetic English voice clip using the configured model
(`TOGETHER_TRANSCRIBE_MODEL` overrides the default).

## Deployment

Deployment instructions for the Netcup VPS are in `docs/deploy.md`.
A deploy helper is available at `scripts/deploy.sh`.
