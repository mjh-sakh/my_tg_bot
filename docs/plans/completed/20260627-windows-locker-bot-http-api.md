# Windows locker Telegram bot HTTP API

## Overview
- add a small unauthenticated HTTP API to the existing Telegram bot process for the Windows screen-time companion app
- expose two endpoints:
  - `GET /locker/auth` returns the current mode as plain text: `keep going` or `restricted`
  - `POST /locker/logs` forwards the posted log body to the Telegram admin chat and returns `200 OK` only after successful forwarding
- add one admin-only Telegram command:
  - `/locker` shows current mode
  - `/locker on` sets restricted mode
  - `/locker off` sets normal mode
- persist only the current locker mode in SQLite; do not store pings or logs
- notify the Telegram admin chat on every auth check and every log upload
- expected result: the Windows service can be built with `AuthURL=http://.../locker/auth` and `LogURL=http://.../locker/logs`, while the Telegram admin can inspect and change the mode from the bot

## Context
- `../windows_locker/README.md` says the Windows executable is configured at build time with `AuthURL` and `LogURL`.
- `../windows_locker/internal/auth/auth.go` accepts only exact `200 OK` response bodies:
  - `restricted`
  - `keep going`
  - any other payload is fail-open
- `../windows_locker/internal/logstore/logstore.go` sends logs as `POST` with `Content-Type: application/x-ndjson` and truncates local logs only after HTTP `200 OK`.
- `bot/main.py` currently starts `python-telegram-bot` with `application.run_polling()`, which owns the loop and does not leave an easy place to run an HTTP server.
- `bot/clients/sqlite_client.py` already initializes and migrates SQLite at `data/bot.sqlite`; extending it with a simple settings table fits current persistence patterns.
- `bot/handlers/admin_handler.py` has the current admin command style and direct `SQLiteClient()` usage.
- `bot/handlers/security.py` already supports admin-only handlers via `add_authorization(..., Role.admin)`.
- `pyproject.toml` does not currently include `aiohttp`.
- `docker-compose.yml` currently has no published HTTP port because the bot only polls Telegram today.
- Project guidance: small personal bot, no meaningful load, optimize for simplicity.

## Chosen Approach
- use `aiohttp` in the same asyncio event loop as `python-telegram-bot`
- replace `application.run_polling()` with explicit lifecycle management:
  - build and register Telegram handlers
  - build the `aiohttp.web.Application`
  - install `SIGINT` / `SIGTERM` handlers that set a shutdown event
  - use `async with telegram_application:` for PTB initialize/shutdown
  - call `await application.start()` and `await application.updater.start_polling()` explicitly
  - start the aiohttp server
  - on shutdown, stop HTTP intake first, then stop polling and the bot application
- store the mode as one SQLite setting or one-row locker table, defaulting to normal when absent
- send notifications to `ADMIN_ID` because this is already the configured bot owner/admin identity
- handle notification failure differently by endpoint:
  - `GET /locker/auth`: notification is best-effort; still return the exact current mode because auth should fail open/continue based on stored state
  - `POST /locker/logs`: return success only after the log was sent to Telegram; if forwarding fails or no `ADMIN_ID` is configured, return non-200 so the Windows app keeps local logs for retry

### Rejected alternatives
- **FastAPI/Uvicorn:** works, but adds a second server lifecycle layer and dependencies for only two simple endpoints. No schema/OpenAPI need here.
- **Separate HTTP service:** cleaner isolation, but more deployment and secret/config management for a family-scale bot.
- **Pending decisions on each ping:** rejected by requirement; auth returns the current persisted mode immediately.
- **Storing log uploads:** rejected by requirement; logs are forwarded to Telegram only.
- **URL secret/token:** rejected by requirement; endpoint is plain HTTP and unauthenticated.

## Development Approach
- testing approach: implementation-first with focused unit tests after each layer, because the integration is small and existing tests are unit-oriented
- keep changes small and focused
- avoid introducing a generic settings subsystem beyond what the locker mode needs unless it makes the SQLite code simpler
- update the plan if deployment/exposure requirements change materially

## Testing Strategy
- add SQLite tests for default mode and set/get mode round trips
- add command handler tests for `/locker`, `/locker on`, `/locker off`, and invalid arguments
- add aiohttp handler tests for:
  - `GET /locker/auth` returns exact Windows payloads
  - `GET /locker/auth` sends an admin notification
  - `POST /locker/logs` sends a Telegram notification and returns `200 OK` only on successful forwarding
  - `GET /locker/auth` notification errors do not change the exact auth response
  - `POST /locker/logs` notification errors return non-200 so Windows preserves local logs
- run full test suite:

```bash
mise exec -- direnv exec . uv run pytest
```

- manual validation after implementation:

```bash
curl -i http://localhost:8080/locker/auth
curl -i -X POST --data-binary $'{"event":"test"}\n' http://localhost:8080/locker/logs
```

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Add persistent locker mode to SQLite

**Files:**
- Modify: `bot/clients/sqlite_client.py`
- Modify: `tests/clients/test_sqlite_client.py`

- [x] add a small table for bot settings or a dedicated one-row `locker_state` table during `init_db()`
- [x] add `get_locker_restricted() -> bool` that defaults to `False` when no row exists
- [x] add `set_locker_restricted(restricted: bool) -> None`
- [x] test fresh database default is normal mode
- [x] test setting restricted and then normal round trips
- [x] run SQLite client tests before moving on

### Task 2: Add `/locker` admin command

**Files:**
- Create: `bot/handlers/locker_handler.py`
- Modify: `bot/handlers/__init__.py`
- Modify: `bot/main.py`
- Modify: `tests/handlers/test_locker_handler.py`

- [x] implement `/locker` status reply
- [x] implement `/locker on` to set restricted mode
- [x] implement `/locker off` to set normal mode
- [x] reject other arguments with concise usage text
- [x] register the handler as admin-only with `add_authorization(locker_handler, Role.admin)`
- [x] test all command paths with a fake SQLite client
- [x] run handler tests before moving on

### Task 3: Add aiohttp locker HTTP endpoints

**Files:**
- Create: `bot/locker_http.py`
- Create: `tests/test_locker_http.py` or `tests/http/test_locker_http.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [x] add `aiohttp` runtime dependency and update the lock file
- [x] implement `GET /locker/auth`
  - [x] read SQLite mode
  - [x] return exact text `restricted` when restricted, otherwise `keep going`
  - [x] notify `ADMIN_ID` of the check and current mode
- [x] implement `POST /locker/logs`
  - [x] read raw request body with an explicit max body size
  - [x] decode as UTF-8 with replacement for invalid bytes
  - [x] send a Telegram message with the log content
  - [x] return `200 OK` only after Telegram send succeeds
  - [x] return `502`/`503` if Telegram forwarding fails or `ADMIN_ID` is missing
- [x] truncate log messages to one Telegram message with a clear `[truncated]` suffix instead of unbounded chunking/spam
- [x] catch Telegram send errors and log them; fail only the log upload request, not auth
- [x] test exact response bodies and status codes
- [x] test notifications are attempted
- [x] test `GET /locker/auth` notification failure still returns the mode
- [x] test `POST /locker/logs` notification failure returns non-200
- [x] run HTTP tests before moving on

### Task 4: Replace `run_polling()` with coordinated PTB + aiohttp lifecycle

**Files:**
- Modify: `bot/main.py`
- Optionally create: `bot/app.py` if extracting handler registration makes tests/readability better

- [x] extract Telegram application setup/handler registration into a small helper if useful
- [x] create the aiohttp app and register locker routes
- [x] implement async `main()` with signal-driven shutdown event and call it via `asyncio.run(main())`
- [x] use PTB lifecycle correctly:
  - [x] `async with application:`
  - [x] `await application.start()`
  - [x] `await application.updater.start_polling()`
  - [x] wrap startup/runtime in `try/finally` so partial startup failures still clean up
  - [x] on shutdown: `await runner.cleanup()`
  - [x] `await application.updater.stop()` if polling was started
  - [x] `await application.stop()` if the application was started
- [x] guard signal setup for platforms where `loop.add_signal_handler` is unavailable if needed
- [x] keep `python -m bot.main` as the Docker entrypoint
- [x] run full tests before moving on

### Task 5: Update Docker and environment configuration

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `docs/deploy.md`
- Optionally modify: `README.md`

- [x] add `LOCKER_HTTP_HOST=0.0.0.0` and `LOCKER_HTTP_PORT=8080` examples
- [x] publish/map the locker HTTP port in Docker Compose, or document the chosen host/reverse-proxy exposure path
- [x] document Windows build URLs:
  - [x] `AuthURL=http://<host>:<port>/locker/auth`
  - [x] `LogURL=http://<host>:<port>/locker/logs`
- [x] document that the endpoint is unauthenticated and should only be exposed where that risk is acceptable
- [x] run `docker compose config` validation if Docker is available

### Task 6: Verify acceptance criteria

**Files:**
- No expected code files unless fixes are discovered

- [x] `/locker` returns current mode
- [x] `/locker on` persists restricted mode
- [x] `/locker off` persists normal mode
- [x] `GET /locker/auth` returns `restricted` when restricted
- [x] `GET /locker/auth` returns `keep going` by default and after `/locker off`
- [x] every auth check attempts a Telegram admin notification
- [x] `POST /locker/logs` sends a Telegram admin notification and does not persist logs
- [x] `GET /locker/auth` notification failures do not cause Windows auth requests to fail
- [x] `POST /locker/logs` notification failures cause non-200 so Windows keeps logs for retry
- [x] full test suite passes

## Technical Notes
- Windows auth payload contract is exact and whitespace-sensitive after trim on the Windows side; keep responses simple `text/plain` bodies.
- Default mode must be normal/fail-open-friendly: absent DB row means `False` / `keep going`.
- Telegram messages have a 4096 character limit. Prefer one truncated message with margin, e.g. 3500-3900 chars plus `[truncated]`, to avoid spam from large uploads.
- Since there is no endpoint secret, anyone who can reach the HTTP server can trigger Telegram spam and read/change behavior indirectly only through auth response. Operational exposure matters.
- `ADMIN_ID` must be configured because HTTP handlers need a chat id for notifications.
- If `ADMIN_ID` is absent/zero, auth should still return the current mode, but log upload should return non-200 because the log cannot be displayed anywhere.

## Open Decision
- [x] Production exposure shape for this implementation: direct Docker port mapping by default, with deployment docs warning to restrict exposure with firewall/reverse-proxy rules if needed.

## Post-Completion
- rebuild the Windows executable with:

```bash
GOOS=windows GOARCH=amd64 go build \
  -ldflags="-s -w -H=windowsgui \
    -X 'windows_locker/internal/config.AuthURL=http://<host>:8080/locker/auth' \
    -X 'windows_locker/internal/config.LogURL=http://<host>:8080/locker/logs'" \
  -o screentime.exe ./cmd/screentime
```

- deploy bot update to VPS
- verify from the Windows machine/network that both HTTP endpoints are reachable
- manually test one Windows service run in normal mode and one in restricted mode
