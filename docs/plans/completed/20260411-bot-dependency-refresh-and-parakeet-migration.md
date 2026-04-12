# Refresh bot dependencies and migrate speech-to-text to Parakeet

## Overview
- Modernize the project toolchain and dependencies before changing runtime behavior.
- Replace the current Replicate Whisper model with `nvidia/parakeet-rnnt-1.1b` for speech-to-text.
- Remove stale local artifacts (`.venv`, `node_modules`) and drop Node tooling entirely if it is not actually used.
- Move Python environment management to `mise` + `uv` so local development and container builds use a reproducible flow.
- Expected result:
  - project bootstraps cleanly with `mise` and `uv`
  - obsolete Node artifacts/config are removed if unused
  - dependencies are broadly refreshed to current compatible versions
  - voice transcription works with Replicate Parakeet
  - transcription behavior, docs, and tests reflect the new setup

## Context
- Main runtime entrypoint: `bot/main.py`
- Voice handling: `bot/handlers/voice_handler.py`
- Transcription logic: `bot/clients/transcription_clients.py`
- Python deps currently live only in `requirements.txt`
- Tooling files currently present:
  - `.tool-versions` pins `python 3.12.3` and `nodejs 22.3.0`
  - `.envrc` still uses `asdf`
  - `package.json` / `package-lock.json` only contain `wrangler`
  - checked-in `.venv/` and `node_modules/` are stale
- Current STT implementation details:
  - default Replicate model env var: `WHISPER_REPLICATE_MODEL_NAME`
  - Replicate request payload assumes Whisper-style input: `{task: "transcribe", audio: ...}`
  - Replicate response parsing assumes dict output with `output['text']`
  - OpenAI fallback uses `whisper-1`
  - adaptive routing switches by file size and duration
- Replicate model inspection for `nvidia/parakeet-rnnt-1.1b` shows:
  - input field is `audio_file`
  - output is a plain string
  - latest version is available via Replicate API
- Tests are currently minimal: only `tests/handlers/test_handlers.py`, effectively empty.

## Chosen Approach
- Use a two-part migration:
  1. toolchain/dependency refresh first
  2. STT provider migration second
- Replace the ad-hoc `requirements.txt`-only workflow with a `pyproject.toml` + `uv` managed environment, while keeping any generated lock file committed for reproducibility.
- Remove Node-related files if no actual project usage is found; current inspection suggests `wrangler` is unused.
- Keep the migration focused on Replicate Parakeet and remove the current OpenAI transcription fallback for now.

### Rejected alternatives
- **Change only the model name and leave everything else untouched**
  - Rejected because Parakeet uses a different input/output contract than the current Whisper-oriented Replicate code.
- **Refresh dependencies and STT logic in one unstructured pass**
  - Rejected because it makes regressions harder to isolate.
- **Keep Node tooling “just in case”**
  - Rejected because no current code path appears to use it, and the user explicitly wants it removed if unused.
- **Keep the old OpenAI transcription fallback during the Parakeet migration**
  - Rejected because the desired scope is to move to Parakeet first and empirically test different audio lengths rather than preserve the current fallback path.

## Development Approach
- testing approach: implementation-first, with focused regression tests added alongside each code change
- keep changes small and focused
- complete one task fully before starting the next
- update the plan if scope changes materially
- prefer simple solutions over speculative abstractions
- validate the newest Python version reported by `mise`, but pin the newest version that actually works with the refreshed dependency set instead of assuming `latest` is automatically safe

## Testing Strategy
- Add unit tests around transcription client payload/response handling.
- Add unit tests around the single-provider Replicate transcription flow and failure behavior.
- Add at least one handler-level test for voice transcription happy path using mocks/fakes.
- Validate environment bootstrapping commands locally using the intended invocation pattern:
  - `mise exec -- direnv exec . uv venv`
  - `mise exec -- direnv exec . uv sync`
  - `mise exec -- direnv exec . uv run pytest`
- Manual verification:
  - start the bot locally
  - invite the user to send a short Telegram voice message
  - confirm transcript is returned using Parakeet
  - invite the user to try different audio lengths and note any practical limits or degraded behavior

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Audit and replace local toolchain metadata

**Files:**
- Create: `pyproject.toml`
- Create: `uv.lock`
- Modify: `.tool-versions`
- Modify: `.envrc`
- Modify: `.gitignore`
- Modify: `README.md`
- Remove: `requirements.txt` or reduce it to a compatibility shim if still needed
- Remove: `package.json`
- Remove: `package-lock.json`

- [x] confirm Node has no real project use and remove Node package metadata
- [x] update `.tool-versions` to the newest Python version that passes dependency validation; remove `nodejs` unless a real project use is discovered during implementation
- [x] switch `.envrc` from `asdf`-oriented setup to a simple dotenv workflow that works with the intended `mise exec -- direnv exec . uv ...` commands
- [x] define project metadata and dependencies in `pyproject.toml`
- [x] generate a `uv.lock` lockfile
- [x] update `.gitignore` so local env/build artifacts stay untracked
- [x] document the new bootstrap/run/test commands in `README.md`
- [x] remove stale local directories `.venv/` and `node_modules/`
- [x] validate bootstrap commands before moving on

### Task 2: Broadly refresh Python dependencies with compatibility checks

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `Dockerfile`
- Modify: `README.md`
- Possibly modify: `docker-compose.yml`

- [x] review each current dependency and keep only what is actually used
- [x] upgrade runtime and dev dependencies to current compatible versions
- [x] verify imports and APIs still match upgraded packages, especially the `python-telegram-bot`, `replicate`, `motor`, `redis`, and `llama-index` stack in active use
- [x] simplify or remove unused dependencies if discovered during code audit
- [x] update `Dockerfile` to build/install using `uv` rather than `pip -r requirements.txt`
- [x] ensure the container still includes any OS packages needed by the remaining runtime dependencies
- [x] run tests and basic import/startup validation before moving on

### Task 3: Migrate the Replicate transcription client to Parakeet

**Files:**
- Modify: `bot/clients/transcription_clients.py`
- Modify: `bot/clients/__init__.py` if exports change
- Modify: `.env.example`
- Modify: `README.md`

- [x] rename the model configuration env var away from Whisper-specific naming to `REPLICATE_TRANSCRIBE_MODEL`
- [x] keep temporary backward compatibility with `WHISPER_REPLICATE_MODEL_NAME` during the migration
- [x] set the default model to `nvidia/parakeet-rnnt-1.1b`
- [x] update Replicate request payload from Whisper-style fields to Parakeet’s expected `audio_file`
- [x] update Replicate response handling from dict parsing to string output handling
- [x] preserve timeout retry behavior where still useful
- [x] review version-resolution logic and ensure it still works with the new model
- [x] document the new model and env vars in `.env.example` and `README.md`
- [x] add or update tests for Parakeet payload/response behavior
- [x] run relevant tests before moving on

### Task 4: Simplify transcription flow around Replicate Parakeet only

**Files:**
- Modify: `bot/clients/transcription_clients.py`
- Modify: `bot/handlers/voice_handler.py` if message/error handling needs adjustment
- Modify: `.env.example`
- Modify: `README.md`
- Create or modify: `tests/...` covering routing logic

- [x] remove the current OpenAI transcription fallback and any now-unused routing thresholds/config
- [x] simplify the transcription client selection logic so Replicate Parakeet is the single active speech-to-text path
- [x] ensure provider failures are explicit and easy to diagnose in logs and chat replies
- [x] document any remaining practical limits as observational/manual-test notes rather than enforced fallback rules
- [x] add tests covering the simplified provider path and provider failure behavior
- [ ] manually validate with different audio lengths before moving on

### Task 5: Add regression tests and validation harness for the refreshed project

**Files:**
- Create or modify: `tests/clients/test_transcription_clients.py`
- Create or modify: `tests/handlers/test_voice_handler.py`
- Modify: `tests/handlers/test_handlers.py` or replace with meaningful coverage
- Modify: `README.md`

- [x] add focused unit tests for Replicate client setup and payload mapping
- [x] add tests for the single-provider transcription path using mocks
- [x] add a voice handler test for transcript reply chunking / happy path
- [x] add a voice handler test for provider exception handling
- [x] make the documented test command match the new `mise` + `uv` workflow
- [x] run the relevant test suite before moving on

### Task 6: Verify acceptance criteria
- [x] verify project setup no longer depends on checked-in `.venv` or `node_modules`
- [x] verify Node artifacts/config are removed if unused
- [x] verify local setup works through `mise` + `direnv` + `uv`
- [x] verify Parakeet is the default and only active STT model path
- [x] verify docs and env examples match the final implementation
- [x] run the relevant test suite
- [ ] run manual end-to-end verification if credentials are available
- [ ] invite the user to test different audio lengths and note the observed behavior

### Task 7: Final documentation and cleanup
- [ ] remove any leftover obsolete dependency or tooling references
- [ ] update README setup, run, and troubleshooting notes
- [ ] update project guidance files if durable patterns are discovered
- [ ] move or mark the plan as completed if the project adopts that convention

## Technical Notes
- `nvidia/parakeet-rnnt-1.1b` differs from the current Whisper-based Replicate model contract:
  - input field: `audio_file`
  - output: plain string
- The current `MAX_MESSAGE_LENGTH` is read from env without type coercion; if touched during refactoring, convert it to `int` to avoid slicing issues with string env values.
- Current imports in `bot/main.py` use top-level `from handlers` / `from clients`; dependency and packaging cleanup should avoid accidentally breaking local execution semantics.
- Python `3.14.4` was the latest version reported by `mise`, but `replicate` currently breaks there via `pydantic.v1`; implementation pinned to Python `3.13.13` as the newest validated version.
- If `llama-index` or related packages are unused at runtime, consider removing them rather than carrying them through the upgrade.

## Post-Completion
- human-confirm that removing Node/wrangler has no deployment impact outside this repository
- if Python must be pinned below the latest available version for compatibility, document the reason clearly
- optionally add CI later to enforce `uv sync` + `uv run pytest` on future dependency updates
- after implementation, have the user try different audio lengths and use those results to decide whether any explicit non-Parakeet fallback is worth reintroducing later
