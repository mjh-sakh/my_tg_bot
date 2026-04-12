# Replace MongoDB with SQLite and simplify deployment

## Overview
- Replace the bot’s current MongoDB usage with a local SQLite database.
- Remove MongoDB from runtime dependencies, configuration, and deployment.
- Keep the SQLite file under a gitignored data directory and mount that directory from the host in production.
- Keep the scope focused on the two current persistence needs: user authorization and reply-chain history.
- Preserve the current application behavior and usage patterns; this is a storage-backend change, not a feature redesign.
- Expected result:
  - the bot runs with no MongoDB service
  - authorization and chat history still work
  - deployment becomes a single-container Docker Compose setup with persistent SQLite storage
  - no Mongo data migration is required; starting with a fresh SQLite DB is acceptable

## Context
- Current Mongo usage is limited to:
  - `bot/handlers/security.py` → `users` lookup by Telegram user id
  - `bot/handlers/gpt_handlers.py` → `history` storage for reply-chain context
- Current connection wiring lives in `bot/clients/mongo_client.py` and `bot/clients/__init__.py`.
- Current deployment still assumes Mongo:
  - `docker-compose.yml`
  - `.env.example`
  - `docs/deploy.md`
  - `scripts/deploy.sh`
- Existing tests cover auth behavior in `tests/handlers/test_security.py`, but history persistence has little or no direct test coverage.
- The repo is intentionally small and pragmatic (`agents.md`): few users, no meaningful load, no backward-compatibility requirement.
- Important existing data-model issue: history currently keys records by `message_id` alone, which is risky because Telegram message ids are chat-scoped. This migration is a good point to fix that by storing `chat_id + message_id` while keeping the user-visible reply-chain behavior the same.
- Out of scope:
  - changing who can use the bot or how non-admin users are managed
  - adding admin/user management commands or new operational workflows
  - redesigning chat/history behavior beyond the keying fix required for safe storage

## Chosen Approach
- Use SQLite as the only application database and access it through a small project-local client wrapper.
- Keep the implementation simple and pragmatic:
  - use a single SQLite DB file
  - keep it under a gitignored `data/` directory locally
  - initialize schema idempotently on startup
  - use straightforward SQL for the two tables currently needed
- Preserve the current auth and history features as they are used today; do not add new management flows or redesign behavior.
- Update the history schema to use `chat_id` plus `message_id` as the stable identity for messages and reply links, as the minimum internal fix needed for correct storage semantics.
- Persist the DB through a host bind mount into the bot container instead of a separate database container.
- In production, use `/opt/my_tg_bot/data` mounted into the container data directory used by the app, so the SQLite file remains a normal host file.

### Rejected alternatives
- **Keep MongoDB**
  - Rejected because the app’s actual storage needs are tiny and do not justify a separate DB service.
- **Introduce a full ORM / SQLAlchemy layer**
  - Rejected as unnecessary abstraction for two small tables and a few queries.
- **Use Syncthing as live SQLite replication across multiple running instances**
  - Rejected for now because this bot is single-instance and Syncthing is better suited to backup/snapshot sync than multi-writer live DB sharing.

## Development Approach
- testing approach: implementation-first, with local unit tests for changed logic and final smoke testing in production
- keep changes small and focused
- complete one task fully before moving on
- prefer standard-library/simple solutions over new abstractions unless the code clearly benefits
- do not preserve Mongo compatibility or dual-write behavior

## Testing Strategy
- Unit tests:
  - update auth tests to target SQLite-backed role lookup
  - add focused tests for history write/read behavior and reply-chain reconstruction inputs
  - cover missing-record and database-error paths where practical
- Local validation:
  - run `mise exec -- direnv exec . uv run pytest`
  - run `docker compose config`
  - build the image after dependency/config changes
- Production verification:
  - deploy the updated single-service stack to the VPS
  - verify the SQLite file persists on the host across container recreation
  - smoke-test `/start`, `/whoami`, `/chat`, reply-chain context, and one voice transcription flow
  - verify non-admin access still behaves as expected

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Add a SQLite storage layer and schema

**Files:**
- Create: `bot/clients/sqlite_client.py`
- Modify: `bot/clients/__init__.py`
- Modify: `bot/main.py`
- Remove or stop using: `bot/clients/mongo_client.py`

**Concrete interface to implement:**
- fixed DB location:
  - local/dev: `data/bot.sqlite`
  - in container: `/app/data/bot.sqlite`
- schema init on startup via `init_db()`
- role lookup used by auth code:
  - `get_user_role(user_id: int) -> str | None`
- history helpers used by GPT handlers:
  - `insert_history_record(...) -> None`
  - `get_history_record(chat_id: int, message_id: int) -> dict | None`
- implementation note:
  - because handlers are async and SQLite access is local/small, keep the storage wrapper simple and synchronous unless code inspection during implementation shows a real need for thread offloading

- [x] add a small SQLite client wrapper that opens the DB, initializes schema, and exposes the concrete minimal interface above
- [x] define tables for `users` and `history`
- [x] make schema initialization idempotent so a fresh deploy creates the DB automatically
- [x] use the fixed DB path that matches the repo/container structure
- [x] handle the main edge case: create the parent `data/` directory automatically when it does not yet exist
- [x] add or update tests for schema/client behavior where it is easiest to verify directly
- [x] run relevant tests / validation before moving on

### Task 2: Migrate authorization to SQLite without changing auth behavior

**Files:**
- Modify: `bot/handlers/security.py`
- Modify: `tests/handlers/test_security.py`

- [x] replace Mongo-based role lookup with SQLite-backed role lookup while preserving the existing `ADMIN_ID` bypass and current auth behavior
- [x] keep the current role model unchanged (`admin` / `user`) and do not add any user-management features
- [x] handle the main edge cases: unknown users and DB failures should continue to deny access gracefully instead of crashing handlers
- [x] add or update tests for success cases
- [x] add or update tests for failure / edge cases
- [x] run relevant tests / validation before moving on

### Task 3: Migrate history storage to SQLite without changing reply-chain behavior

**Files:**
- Modify: `bot/handlers/gpt_handlers.py`
- Create: `tests/handlers/test_gpt_handlers.py`

- [x] replace Mongo-based history writes/reads with SQLite-backed history storage while preserving current reply-chain behavior
- [x] update history identity to use `chat_id + message_id` instead of `message_id` alone
- [x] update reply-link storage so chain reconstruction is unambiguous across chats
- [x] keep stored fields aligned with current handler needs; do not expand history into a broader feature or analytics store
- [x] handle the main edge cases: missing history rows and DB failures should degrade gracefully instead of crashing handlers where practical
- [x] add or update tests for success cases
- [x] add or update tests for failure / edge cases
- [x] run relevant tests / validation before moving on

### Task 4: Remove Mongo from dependencies and deployment

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `Dockerfile` if runtime filesystem setup is needed
- Modify: `.gitignore`
- Modify: `scripts/deploy.sh`

- [x] remove the `motor` dependency and any Mongo-specific configuration
- [x] do not introduce a SQLite path env var; keep the DB location fixed by project structure and Docker bind mount
- [x] simplify `docker-compose.yml` from bot + mongo to a single bot service with a host bind mount for the SQLite data directory
- [x] ensure the runtime data path is gitignored and not accidentally uploaded from the local machine during deploy
- [x] handle the main edge case: persistence still works after rebuild/restart because the SQLite file lives under a host-mounted data directory
- [x] add or update tests for config-sensitive code if applicable
- [x] run relevant tests / validation before moving on

### Task 5: Update docs and production runbook

**Files:**
- Modify: `README.md`
- Modify: `docs/deploy.md`
- Modify: `agents.md` only if the persistence/deploy guidance needs one short durable note

- [x] update setup and deployment docs so they describe the SQLite-based runtime accurately
- [x] remove Mongo-specific operational instructions and checks
- [x] document the persistent SQLite location and the expected deployment flow clearly, including the host bind mount path
- [x] keep Syncthing-related backup ideas out of the core deployment path unless they are explicitly implemented now
- [x] add or update manual verification steps for the new single-container deployment
- [x] run relevant validation before moving on

### Task 6: Deploy to production and verify real behavior

**Files:**
- Modify: remote `/opt/my_tg_bot/.env` if needed
- Modify: remote Docker Compose state on the VPS
- Modify: remote host data directory `/opt/my_tg_bot/data` only if deployment adjustments are required

- [x] deploy the updated application to the VPS
- [x] confirm the old Mongo service is no longer part of the running stack
- [x] verify the bot starts cleanly with SQLite and auto-creates its schema if the DB is fresh
- [ ] smoke-test `/start`, `/whoami`, `/chat`, reply-chain context, and one voice message in production
- [ ] verify authorization still works for the admin path and for any SQLite-backed allowed user path that is actually configured
- [x] verify the SQLite file persists in `/opt/my_tg_bot/data` across container restart/recreation
- [x] capture any deployment-time corrections in docs before considering the work done

### Task 7: Verify acceptance criteria
- [ ] verify all requirements from Overview are covered
- [x] verify edge cases and regressions are addressed
- [x] run the relevant test suite
- [ ] run end-to-end or manual verification in production

### Task 8: Final documentation and cleanup
- [x] remove dead Mongo code/files if any remain
- [x] ensure docs/config/examples no longer mention MongoDB
- [ ] move or mark the plan as completed if the project has that convention
- [ ] capture any durable lessons in project guidance if new patterns were discovered

## Technical Notes
- Schema shape:
  - `users(user_id PRIMARY KEY, role TEXT NOT NULL)`
  - `history(chat_id, message_id, text, reply_chat_id, reply_message_id, role, is_llm_chain, schema_version, PRIMARY KEY(chat_id, message_id))`
- Delegation boundaries:
  - Task 1 should be completed first because it defines the storage API used by later tasks
  - Task 2 and Task 3 can be delegated separately after Task 1 is merged or the interface is treated as fixed
  - Task 4 and Task 5 are strong subagent candidates because they are bounded to config/deploy and docs respectively
  - Task 6 should stay with the main execution thread because it touches real production state
- Pathing:
  - local DB path: `data/bot.sqlite`
  - local `data/` directory is gitignored
  - production host data directory: `/opt/my_tg_bot/data`
  - production bind mount: `/opt/my_tg_bot/data` → `/app/data`
  - production DB path inside the container: `/app/data/bot.sqlite`
- The app can continue to treat `ADMIN_ID` as an env-based override without storing that admin row in SQLite.
- For this small bot, SQLite via standard library access is likely sufficient; no ORM is needed.
- The migration does not need to import old Mongo data unless production usage reveals that existing history is worth preserving.
- If Syncthing backup is added later, prefer syncing exported snapshots or a single-instance DB file from the server, not multiple live writers.

## Post-Completion
- manual checks requiring human confirmation:
  - confirm any intended non-admin users are still allowed after their existing access entries are present in SQLite
  - confirm production behavior is acceptable without migrating old Mongo history
- deployment or environment changes:
  - production env/config will stop using `MONGO_URI`
  - Docker Compose will no longer run a Mongo container
- external follow-up items:
  - optionally add a tiny admin/bootstrap command or documented script for inserting/updating SQLite `users` rows if non-admin access needs to be managed regularly
