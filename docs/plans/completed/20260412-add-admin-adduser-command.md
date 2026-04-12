# Add admin-only `/adduser` command for authorization

## Overview
- Add a Telegram command `/adduser <id>` that lets the admin authorize a user by Telegram user id.
- The command should write the target id into the existing SQLite `users` table with role `user`.
- Keep the scope intentionally small: no username lookup, no remove/list commands, no broader auth redesign.
- Expected result: the configured `ADMIN_ID` can authorize a new user from Telegram, and that user can then access handlers protected by the current authorization checks.

## Context
- Authorization already exists in `bot/handlers/security.py`.
  - `ADMIN_ID` from env is treated as `Role.admin` automatically.
  - Non-admin access is resolved through `SQLiteClient().get_user_role(user_id)`.
- SQLite is already the source of truth for authorized users in `bot/clients/sqlite_client.py`.
  - `users(user_id INTEGER PRIMARY KEY, role TEXT NOT NULL)` already exists.
  - There is currently no write helper for users, only role lookup.
- Handler registration currently happens in `bot/main.py`.
  - `/start` and `/whoami` are open.
  - voice handler is protected by `add_authorization(...)`.
  - chat handlers are currently disabled.
- Existing test patterns:
  - DB tests live in `tests/clients/test_sqlite_client.py`.
  - auth tests live in `tests/handlers/test_security.py`.
  - simple command-handler tests live in `tests/handlers/test_handlers.py`.
- Project guidance prefers pragmatic, easy-going solutions over heavy architecture.

## Chosen Approach
- Add a small SQLite helper to insert or upsert a user role.
- Add a dedicated admin handler implementing `/adduser <id>`.
- Register that handler in `bot/main.py` with `add_authorization(..., Role.admin)`.
- Add focused tests for DB write behavior and command behavior.

### Rejected alternatives
- **Manually editing SQLite on disk or on the server**
  - Rejected because it is operationally clumsy and defeats the purpose of managing access from Telegram.
- **Building a broader admin management surface now (`/deluser`, `/listusers`, role editing)**
  - Rejected because the approved scope is only adding users by id.
- **Embedding the command into `start_handler.py`**
  - Possible, but a small dedicated admin handler file is clearer and still simple.

## Development Approach
- Testing approach: implementation-first with immediate test coverage in the same task.
- Keep changes narrow and aligned with existing command and auth patterns.
- Prefer a straightforward SQLite upsert over extra abstraction.
- Do not change current auth semantics beyond enabling the new admin write path.

## Testing Strategy
- Add/update unit tests for SQLite user insertion/upsert behavior.
- Add/update handler tests for:
  - valid `/adduser <id>` flow
  - invalid or missing id arguments
  - admin-only protection behavior
- Run the relevant test suite with:
  - `mise exec -- direnv exec . uv run pytest`
- Manual verification after deploy if needed:
  - admin sends `/whoami` to confirm their id
  - admin sends `/adduser <target_id>`
  - target user tries an authorized bot feature

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Add SQLite write support for authorized users

**Files:**
- Modify: `bot/clients/sqlite_client.py`
- Modify: `tests/clients/test_sqlite_client.py`

- [x] add a small method to insert or upsert a user role in the `users` table
- [x] keep the method simple and compatible with the existing schema
- [x] add/update tests covering insert behavior for a new user
- [x] add/update tests covering idempotent or upsert behavior for an existing user
- [x] run the relevant tests for the SQLite client before moving on

### Task 2: Add the admin-only `/adduser` command handler

**Files:**
- Create: `bot/handlers/admin_handler.py`
- Modify: `bot/handlers/__init__.py`
- Modify: `bot/main.py`
- Modify: `tests/handlers/test_handlers.py`

- [x] implement `/adduser <id>` parsing using existing Telegram command patterns
- [x] validate missing or non-integer ids and reply with a clear usage/error message
- [x] write the target id to SQLite with role `user`
- [x] expose the handler via `bot/handlers/__init__.py`
- [x] register the handler in `bot/main.py` with `add_authorization(handler, Role.admin)`
- [x] add/update handler tests for success and invalid-input paths
- [x] run the relevant handler tests before moving on

### Task 3: Verify authorization behavior end to end

**Files:**
- Possibly modify: `tests/handlers/test_security.py`

- [x] confirm existing admin bypass behavior remains unchanged
- [x] add or adjust tests only if the new command exposes a missing auth edge case
- [x] verify that a user inserted through SQLite resolves to `Role.user`
- [x] run the relevant auth tests before moving on

### Task 4: Verify acceptance criteria
- [x] verify `/adduser <id>` is admin-only
- [x] verify successful command execution persists the target user in SQLite
- [x] verify invalid input does not crash and returns a clear message
- [x] run the relevant test suite
- [ ] do a short manual verification in Telegram and confirm behavior on the deployed bot

### Task 5: Final documentation and cleanup
- [x] update `README.md` only if admin usage should be documented now
- [x] update project guidance files only if a durable new pattern is discovered during implementation
- [ ] move or mark the plan as completed after human confirmation of the deployed command

## Technical Notes
- Keep roles aligned with the existing `Role` enum values: `admin` and `user`.
- The command actor and the target id are different values:
  - actor id comes from `update.message.from_user.id`
  - target id comes from `context.args[0]`
- The simplest acceptable persistence behavior is `INSERT OR REPLACE` / upsert for `(user_id, role)`.
- No DB migration is required because the `users` table already exists.
- No deployment/config changes are expected.

## Post-Completion
- Manual checks requiring human confirmation:
  - confirm the intended target user id via `/whoami` from that user
  - confirm the newly added user can access an authorized feature
- Deployment or environment changes:
  - redeploy the bot after merge so the new command is available in production
- External follow-up items:
  - optional future commands: `/deluser`, `/listusers`
