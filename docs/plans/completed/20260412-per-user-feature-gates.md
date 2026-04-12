# Per-user feature gates via handler authorization

## Overview
- add explicit per-user feature flags to the existing SQLite-backed authorization model
- extend handler authorization so `main.py` can declare which feature a handler requires
- keep policy wiring explicit in `bot/main.py` instead of introducing separate feature defaults
- expected result: admins can authorize users and toggle named features per user, and handlers can require those features through `add_authorization(..., feature=...)`

## Context
- `bot/handlers/security.py` already wraps handlers with `add_authorization` and resolves roles from `ADMIN_ID` plus SQLite
- `bot/clients/sqlite_client.py` already owns schema creation and user persistence
- `bot/handlers/admin_handler.py` currently supports only `/adduser`
- `bot/main.py` is the natural place to keep explicit handler-to-feature wiring
- tests already cover SQLite persistence and authorization wrappers; extend those patterns instead of adding new layers

## Chosen Approach
- add a `user_features` SQLite table where row presence means a feature is enabled for a user
- extend `add_authorization` / `authorize_func` with an optional `feature` parameter
- keep supported feature names in a small enum for typo safety, while keeping enablement policy explicit in `main.py`
- add admin commands to enable, disable, and inspect features for a user
- avoid feature default matrices or separate policy configuration

## Development Approach
- testing approach: implementation-first with immediate test updates in each task
- keep changes small and focused
- complete one task fully before starting the next
- update the plan if scope changes materially
- prefer simple solutions over speculative abstractions

## Testing Strategy
- add SQLite tests for feature persistence helpers
- add authorization tests for feature checks and admin bypass behavior
- add handler tests for admin feature-management commands
- run `mise exec -- direnv exec . uv run pytest`

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Add SQLite feature persistence

**Files:**
- Modify: `bot/clients/sqlite_client.py`
- Modify: `tests/clients/test_sqlite_client.py`

- [x] create the `user_features` table in SQLite initialization
- [x] add helpers to enable, disable, check, and list features for a user
- [x] add tests for feature enable/disable and listing behavior
- [x] run relevant tests / validation before moving on

### Task 2: Extend authorization and admin feature management

**Files:**
- Modify: `bot/handlers/security.py`
- Modify: `bot/handlers/admin_handler.py`
- Modify: `bot/handlers/__init__.py`
- Modify: `tests/handlers/test_security.py`
- Modify: `tests/handlers/test_handlers.py`

- [x] add an optional feature requirement to handler authorization
- [x] allow admins to bypass feature checks for operational safety
- [x] add admin commands to enable, disable, and inspect user features
- [x] add tests for success and denial paths
- [x] run relevant tests / validation before moving on

### Task 3: Wire explicit feature requirements in application setup

**Files:**
- Modify: `bot/main.py`

- [x] declare feature requirements explicitly in handler registration
- [x] register the new admin feature-management handlers
- [x] keep the policy readable from `main.py`
- [x] run relevant tests / validation before moving on

### Task 4: Verify acceptance criteria and cleanup
- [x] verify explicit handler feature wiring works with the new API shape
- [x] verify admins can manage features and remain unblocked by feature checks
- [x] run the full relevant test suite
- [x] update this plan to reflect final completion state

## Technical Notes
- feature rows are presence-based: existing row means enabled, missing row means disabled
- role authorization remains separate from feature authorization
- `ADMIN_ID` should continue to bootstrap admin access even if SQLite is empty
- feature name validation should be lightweight and consistent across admin commands and handler wiring

## Post-Completion
- manually confirm the chosen command names for feature management feel ergonomic in Telegram
- if chat/reply handlers are enabled later, decide whether background history tracking should remain open or also become feature-gated
