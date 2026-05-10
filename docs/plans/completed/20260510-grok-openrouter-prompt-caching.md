# Grok OpenRouter prompt caching with root-thread affinity

## Overview
- add Grok-specific prompt-cache affinity support for OpenRouter requests by sending a stable `x-grok-conv-id` header
- scope the affinity key to the root Telegram conversation thread so divergent reply branches still land on the same xAI server and can reuse shared cached prefixes
- keep the change local to the current chat handler flow; avoid schema changes unless implementation proves they are needed
- expected result: Grok requests made through OpenRouter use a deterministic per-root-thread affinity key, existing reply-chain reconstruction continues to work unchanged, and non-Grok models behave exactly as before

## Context
- `bot/handlers/gpt_handlers.py` is the main LLM entry point and currently constructs `OpenRouter(...)` without any custom cache-affinity header
- the bot already models conversation history as a reply tree and reconstructs the active ancestor path for each user reply
- assistant chunk aliases already resolve back to one canonical assistant history record, so the codebase already has a stable notion of a root thread and canonical branch ancestry
- prompt construction appears prefix-stable enough for caching: one static system prompt plus the reconstructed ancestor path plus the current user turn
- the installed LlamaIndex OpenAI/OpenRouter stack supports `default_headers`, which is the best place to inject `x-grok-conv-id` in this project
- project guidance favors pragmatic, simple changes over extra architecture; this bot is small-scale and does not need a session-management subsystem unless a concrete need appears

## Chosen Approach
- derive a deterministic UUIDv5 affinity key from stable root-thread identifiers, likely `chat_id` plus the root canonical message id
- send that key as `x-grok-conv-id` only when the selected model is a Grok model routed through OpenRouter
- keep one affinity key per root thread, not per branch path
- do not add a database column or persisted mutable session id in the first iteration

### Why this approach
- xAI cache matching is prefix-based, while `x-grok-conv-id` controls server affinity; keeping sibling branches on the same server maximizes reuse of shared prefixes
- a branch-path-specific key would route sibling branches to different servers and duplicate cache warmup for the same ancestor history
- deterministic derivation keeps the solution inspectable and reproducible without schema work or backfilling stored session ids

### Rejected alternatives
- branch-path affinity keys
  - rejected because they split shared prefixes across servers and likely reduce cache reuse for reply-tree conversations
- random session UUID persisted in SQLite
  - rejected for now because it adds migration and lifecycle complexity without a clear functional benefit over deterministic root-thread keys
- global per-chat affinity key
  - rejected because separate top-level prompts in the same chat should not be forced onto one cache affinity stream unnecessarily

## Development Approach
- testing approach: implementation-first with focused unit tests around affinity-key derivation and OpenRouter construction
- keep changes small and local to the existing chat/history flow
- complete one task fully before starting the next
- update the plan if scope changes materially
- prefer simple helpers over a new session abstraction

## Testing Strategy
- update `tests/handlers/test_gpt_handlers.py` to cover affinity-key behavior for top-level prompts, linear replies, and replies to older assistant chunks / aliases
- verify the same root thread yields the same derived conv id across branches
- verify separate top-level prompts yield different conv ids
- verify non-Grok models do not receive the Grok-specific header
- verify the OpenRouter client is constructed with `default_headers={"x-grok-conv-id": ...}` for Grok models
- update `tests/e2e/test_chat_openrouter_e2e.py` to validate a two-message sequence and inspect the outbound OpenRouter request shape, including headers and preserved conversation payload/prefix behavior where the harness exposes it
- run focused pytest coverage for the handler tests after each task
- run the relevant e2e test coverage before closing the work

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Document root-thread affinity rules in code and tests

**Files:**
- Modify: `bot/handlers/gpt_handlers.py`
- Modify: `tests/handlers/test_gpt_handlers.py`

- [x] identify the exact root-thread inputs available in the current handler flow (chat id, canonical message id, alias resolution behavior)
- [x] add a small helper that derives the Grok affinity key from root-thread metadata without changing persistence
- [x] encode the intended behavior in tests: same root thread across older-branch replies keeps one key; different top-level prompts get different keys
- [x] add or update tests for alias/canonical assistant reply continuity
- [x] run relevant tests / validation before moving on

### Task 2: Inject Grok affinity headers into OpenRouter construction

**Files:**
- Modify: `bot/handlers/gpt_handlers.py`
- Modify: `tests/handlers/test_gpt_handlers.py`

- [x] detect when the configured model is a Grok model that should receive `x-grok-conv-id`
- [x] pass the derived affinity key through LlamaIndex using `default_headers`
- [x] keep non-Grok model construction unchanged
- [x] add or update tests asserting `default_headers` is present for Grok and absent for non-Grok models
- [x] run relevant tests / validation before moving on

### Task 3: Verify branch behavior and guard against regressions

**Files:**
- Modify: `tests/handlers/test_gpt_handlers.py`
- Modify: `tests/e2e/test_chat_openrouter_e2e.py`
- Modify if needed: `bot/clients/sqlite_client.py`

- [x] add focused tests for replying to an older message in the same thread and confirming the derived affinity key remains root-thread scoped
- [x] verify assistant alias rows still resolve to the same canonical root data used for affinity-key derivation
- [x] add or update an e2e test that drives at least a two-message Grok/OpenRouter sequence and asserts the affinity header is sent consistently across the thread
- [x] inspect the observable outbound request data in e2e coverage to confirm header wiring and expected prefix preservation behavior
- [x] confirm no schema change is required for the chosen implementation
- [x] add or update tests for any edge case discovered during implementation
- [x] run relevant tests / validation before moving on

### Task 4: Verify acceptance criteria and document operational notes

**Files:**
- Modify if needed: `README.md`
- Modify: `docs/plans/20260510-grok-openrouter-prompt-caching.md`

- [x] verify all requirements from Overview are covered
- [x] verify edge cases and regressions are addressed
- [x] run the relevant unit and e2e test suite
- [x] document any operator-facing note only if configuration or debugging expectations changed materially
- [x] move or mark the plan as completed if the project has that convention

## Technical Notes
- affinity should follow the root conversation thread, not the exact branch path
- the cache keying benefit comes from server affinity plus exact prompt-prefix reuse; the header does not override prefix matching
- deterministic UUIDv5 is preferred so the same thread always maps to the same affinity id without persistence
- header injection should be isolated so future provider-specific knobs can be added without entangling the core history logic
- if implementation reveals missing root-thread metadata in some edge case, prefer a tiny helper adjustment over a schema expansion

## Post-Completion
- manually verify Grok requests in a real chat if provider-side observability is available
- if durable debugging or operations knowledge emerges, update project guidance files
- revisit persisted session ids only if deterministic root-thread affinity proves insufficient in practice

Final state: completed.

Validation:
- `RUN_OPENROUTER_E2E=1 mise exec -- direnv exec . uv run pytest tests/handlers/test_gpt_handlers.py tests/e2e/test_chat_openrouter_e2e.py -rs`
- result: `17 passed`

Notes:
- real-network coverage now verifies Grok/OpenRouter root-thread affinity by spying on `gpt_handlers.llm(...)` while still delegating to the real OpenRouter client
- low-value implementation-detail unit tests for the affinity helper/header construction were removed; focused handler coverage remains for distinct-root and non-Grok behavior
