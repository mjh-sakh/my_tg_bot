# Persist chunked Telegram messages as one canonical turn plus aliases

## Overview
- fix the regression/limitation where long voice transcripts are split into multiple Telegram messages but only the first visible chunk is represented in SQLite history
- extend the same canonical-plus-alias model to long LLM replies, which are also split into multiple Telegram messages today
- ensure every visible transcript chunk and every visible assistant chunk is stored as a Telegram-message alias that points to a single canonical history row
- store the full transcript only once on the canonical voice history row keyed by the original voice `message_id`
- store the full assistant reply only once on one canonical assistant history row, with the remaining visible assistant chunks stored as aliases
- stop storing chunk text on non-canonical rows; those rows should be pure aliases used only for canonical lookup
- expected result: if a user replies to any transcript chunk or any assistant chunk, reply resolution finds the same canonical turn and the full conversation chain is rebuilt correctly without duplicated text in alias rows

## Context
- relevant chat/history flow lives in `bot/handlers/gpt_handlers.py`
  - reply continuation resolves the replied-to Telegram message through `get_canonical_history_record(chat_id, message_id)`
  - chain reconstruction then walks canonical rows only via `reply_message_id`
  - recent refactor made `HistoryRecord.text` nullable for alias rows and validates that canonical rows still require text
  - `generate_llm_reply()` already chunks long assistant output for Telegram, but it currently stores each chunk as its own canonical row with the full assistant text duplicated across rows
- voice transcription flow lives in `bot/handlers/voice_handler.py`
  - `send_transcript_reply()` already splits long transcripts into Telegram-safe chunks
  - after that, `handle_voice()` currently writes exactly one alias history row using `transcript_messages[0]`
  - that alias-writing path still reflects the old duplication model and needs to be updated to create one alias row per chunk without storing chunk text
- SQLite history model lives in `bot/clients/sqlite_client.py`
  - rows are keyed by `(chat_id, message_id)`
  - `canonical_message_id` already allows multiple message ids to resolve to one semantic message
  - alias rows can now safely use `text = NULL`, while canonical rows continue storing the full semantic content
  - no schema change is needed for this fix beyond the refactor already completed; the current structure already supports many aliases for one canonical row
- existing coverage lives in `tests/handlers/test_voice_handler.py` and `tests/handlers/test_gpt_handlers.py`
- newly added failing regression test proves the current voice bug: only the first transcript chunk is persisted, so replying to a later chunk cannot resolve to the canonical voice turn
- there is also a parallel assistant-side limitation: long LLM replies are chunked visually but persisted as multiple canonical history rows instead of one canonical row plus aliases
- project guidance from `AGENTS.md`: keep the solution simple and pragmatic; no heavy architecture needed
- explicit non-goal for this plan: do not introduce new abstractions for future streaming support yet; keep changes local to current non-streaming chunked send paths

## Chosen Approach
- keep the current canonical/alias database model
- for voice input:
  - store the full transcript exactly once on the canonical history row keyed by the original voice message id
  - after sending transcript chunks, write one alias history row per visible chunk message
  - make every transcript alias row use:
    - `message_id = transcript chunk Telegram message id`
    - `canonical_message_id = original voice message id`
    - `reply_message_id = original voice message id`
    - `text = NULL`
- for assistant output:
  - keep sending long replies as multiple Telegram messages to respect Telegram limits
  - send all visible assistant chunks first and persist history only after successful sends, so stored rows match what Telegram actually showed
  - treat the first visible assistant chunk as the canonical assistant history row
  - store the full assistant reply text on that first assistant chunk's `message_id`
  - store every later assistant chunk as an alias row pointing back to the first assistant chunk's `message_id`
  - make every assistant alias row use `text = NULL`
- leave canonical reply resolution and chain traversal logic unchanged, because it already does the right thing once all chunk aliases exist
- update tests to verify both voice-side and assistant-side alias persistence plus reply-chain reconstruction from non-first chunks

### Why the DB structure already helps
- the current `history` table is message-centric, so each visible Telegram chunk can have its own `(chat_id, message_id)` row
- `canonical_message_id` is exactly the indirection we need: many chunk rows can point back to one canonical semantic turn, whether that turn started from a voice message or from the first assistant reply chunk
- nullable alias `text` means those chunk rows do not need to duplicate semantic content just to support reply lookup
- `get_canonical_history_record()` already resolves any alias message id to the canonical row, so the chat-chain logic does not need a new concept of chunk groups or special-case traversal
- this makes the fix small: populate the existing alias rows correctly rather than redesigning storage

### Rejected alternatives
- keep storing only the first visible chunk and add special logic to infer sibling chunks from nearby message ids
  - rejected because it is brittle, Telegram-message-order dependent, and unnecessary when alias rows already solve lookup cleanly
- redesign chunk storage into a dedicated chunks table or a separate conversation-turn/link model
  - rejected because the existing `canonical_message_id` model is already sufficient for this bot
- store chunk text on every alias row
  - rejected because alias rows are lookup-only, not semantic history; duplicating transcript or assistant text wastes space and blurs the canonical/alias distinction
- store every visible assistant chunk as its own canonical history row
  - rejected because it duplicates one assistant turn into multiple semantic nodes and pollutes LLM context / reply-chain semantics
- introduce a generalized abstraction for future streaming in this change
  - rejected because streaming is not in scope yet and the project prefers simple local fixes over speculative architecture

## Development Approach
- testing approach: test-first from the already-added failing regression test, plus new assistant-chunk tests asserting canonical-vs-alias behavior
- keep changes small and local to the existing non-streaming chunk persistence paths
- do not introduce new abstractions just to prepare for streaming
- do not change prompt-building or canonical chain traversal unless testing shows a real gap
- keep `resolve_reply_chain()` and `build_chain_from_record()` unchanged unless a test proves they are insufficient

## Testing Strategy
- keep the current failing voice regression test as one primary acceptance test
- add or adjust voice-handler tests to verify:
  - all transcript chunks are persisted as alias rows
  - all alias rows point to the same canonical voice message id
  - all alias rows store `text = NULL`
  - the canonical voice row stores the full transcript text once
  - replying to the last visible transcript chunk rebuilds the same canonical chain
- add or adjust gpt-handler tests to verify:
  - a long assistant reply is split into multiple visible Telegram messages
  - the first assistant chunk is the canonical history row and stores the full assistant text once
  - later assistant chunks are alias rows with `text = NULL`
  - replying to a later assistant chunk resolves to the same canonical assistant turn
- run focused tests first:
  - `mise exec -- direnv exec . uv run pytest tests/handlers/test_voice_handler.py tests/handlers/test_gpt_handlers.py -k "transcript or assistant"`
- then run broader handler coverage:
  - `mise exec -- direnv exec . uv run pytest tests/handlers/test_voice_handler.py tests/handlers/test_gpt_handlers.py tests/clients/test_sqlite_client.py`
- if the change is very small and clean, optionally run the full suite before closing:
  - `mise exec -- direnv exec . uv run pytest`
- manual verification in Telegram if desired:
  - send a long voice message that transcribes past 4096 chars and reply to the final transcript chunk
  - trigger a long LLM reply and reply to its final visible chunk
  - confirm prior context is preserved in both cases

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Persist text-free alias rows for every transcript chunk

**Files:**
- Modify: `bot/handlers/voice_handler.py`
- Modify: `tests/handlers/test_voice_handler.py`

- [x] update the voice flow so it writes alias history for every message returned by `send_transcript_reply()` instead of only the first one
- [x] keep the canonical voice-message history row unchanged so one voice input still maps to one semantic user turn and still stores the full transcript text
- [x] ensure every chunk alias uses the original voice message id as `canonical_message_id`
- [x] ensure every chunk alias stores `text = NULL` so transcript chunks become pure aliases
- [x] add or update tests proving all chunk aliases are persisted for a long transcript and carry no text
- [x] run focused voice-handler tests before moving on

### Task 2: Persist long assistant replies as one canonical row plus chunk aliases

**Files:**
- Modify: `bot/handlers/gpt_handlers.py`
- Modify: `tests/handlers/test_gpt_handlers.py`

- [x] update long assistant reply persistence so only one assistant chunk is canonical and later visible chunks are aliases
- [x] use the first visible assistant reply chunk as the canonical assistant `message_id`
- [x] ensure the canonical assistant row stores the full assistant text once
- [x] ensure later assistant chunk rows use that first assistant message id as `canonical_message_id` and store `text = NULL`
- [x] add or update tests proving long assistant replies are chunked visibly while history contains one canonical assistant row plus aliases
- [x] run focused gpt-handler tests before moving on

### Task 3: Verify reply-chain reconstruction from non-first chunks

**Files:**
- Modify: `tests/handlers/test_voice_handler.py`
- Modify: `tests/handlers/test_gpt_handlers.py`

- [x] verify replying to the last visible transcript chunk resolves through `get_canonical_history_record()` to the canonical voice row
- [x] verify replying to a non-first assistant chunk resolves to the canonical assistant row
- [x] confirm the LLM prompt contains the full canonical transcript or assistant reply once, not per chunk, even though alias rows exist for visible chunks
- [x] add or refine tests for both regression paths
- [x] run relevant handler tests before moving on

### Task 4: Verify acceptance criteria and document the behavior

**Files:**
- Modify: `docs/plans/20260422-transcript-chunk-alias-history.md`
- Modify if needed: `README.md`
- Modify if needed: `docs/plans/completed/20260422-voice-transcript-chat-aliases.md`

- [x] verify all Overview requirements are covered
- [x] verify there is still only one canonical semantic turn per voice input and per assistant reply
- [x] verify chunk alias rows remain excluded from LLM history building and do not store duplicated text
- [x] update any documentation or prior plan notes that currently state only the first transcript chunk is persisted or that imply visible chunk rows carry semantic text
- [x] run the final relevant test suite

## Technical Notes
- likely implementation shape in `voice_handler.py`:
  - keep `transcript_messages = await send_transcript_reply(...)`
  - after `handle_chat_turn(...)`, iterate `for transcript_message in transcript_messages:` and write one alias row per message
  - each alias row should set `text=None` and `canonical_message_id=update.message.message_id`
- likely implementation shape in `gpt_handlers.py`:
  - send all assistant chunks, collect returned Telegram messages, then persist history from those returned messages
  - use the first returned assistant chunk as the canonical assistant row with full assistant text
  - persist later assistant chunks as alias rows with `text=None` and `canonical_message_id=<first assistant chunk message_id>`
  - all assistant chunk rows should keep the same canonical parent user turn via `reply_message_id`
- the canonical voice row written via `handle_chat_turn(...)` should remain the only row that stores the full transcript text for that voice turn
- the canonical assistant row should remain the only row that stores the full assistant text for that assistant turn
- canonical resolution should still return the appropriate canonical row, because `get_canonical_history_record()` first looks up the alias row’s `canonical_message_id` and then fetches the canonical row by that id
- no SQLite migration is needed; this is a data-writing behavior fix on top of the nullable-alias-text refactor, not a schema fix
- streaming is explicitly out of scope for this plan; do not contort this implementation to pre-solve future streaming behavior
- if tests reveal a need to preserve chunk ordering explicitly, first check whether current Telegram message ids and insertion order already make that unnecessary before adding extra fields

## Post-Completion
- [x] verify the behavior in the real Telegram bot with a long transcription and a long assistant reply
- [x] restore production `MAX_MESSAGE_LENGTH` to `4096` after temporary low-limit verification and redeploy
- if chunked persistence patterns recur later, reconsider a shared helper only after real duplication appears in more than these two paths

## Final State
- completed and deployed
- manual verification was done in the real bot by temporarily setting `MAX_MESSAGE_LENGTH=100`, deploying, testing transcript-chunk and assistant-chunk reply continuity, then restoring `MAX_MESSAGE_LENGTH=4096` and redeploying
- final persistence semantics:
  - canonical voice row: original voice `message_id`, full transcript text stored once
  - transcript chunk rows: alias rows with `text = NULL` pointing to the canonical voice row
  - canonical assistant row: first visible assistant chunk `message_id`, full assistant text stored once
  - later assistant chunk rows: alias rows with `text = NULL` pointing to the canonical assistant row
- replying to any visible transcript chunk or assistant chunk now resolves through `canonical_message_id` to the same semantic turn
- validated with full test suite before deploy: `50 passed, 1 skipped`

## Plan Review

### Problem / Solution Fit
- the plan directly targets the observed voice bug: missing history rows for later transcript chunks
- it also addresses the parallel assistant-side inconsistency where long replies are visually chunked but semantically persisted as multiple canonical rows
- it aligns with the newer storage model where alias rows are non-semantic lookups and therefore should not store duplicated text
- it keeps the existing conversation semantics intact while fixing reply lookup for all visible chunks

### Scope Control
- the plan stays bounded to current non-streaming chunk persistence in `voice_handler.py` and `gpt_handlers.py`, related regression tests, and small documentation corrections if needed
- it deliberately avoids schema changes, streaming work, or broader chat refactors

### Over-Engineering Check
- no new tables, services, or abstractions are required
- the existing `canonical_message_id` mechanism is reused exactly as intended

### Testing Coverage
- the known failing regression test is central to the plan
- both persistence behavior and reply-chain behavior are explicitly covered
- the plan now also checks the new invariant: canonical row has text, alias rows do not

### Convention Fit
- the plan follows the existing docs/plans structure and pytest-based workflow already used in the repo
- it matches the project preference for simple, pragmatic fixes
