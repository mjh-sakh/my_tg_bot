# Persist transcript chunk aliases so replies to any chunk continue the same chat chain

## Overview
- fix the regression/limitation where long voice transcripts are split into multiple Telegram messages but only the first visible chunk is represented in SQLite history
- ensure every visible transcript chunk is stored as an alias row that points to the same canonical voice message id
- preserve the current semantic model: the original voice message remains the single canonical user turn, while transcript chunks are lookup-only aliases
- expected result: if a user replies to any transcript chunk, especially the last one, reply resolution finds the same canonical user turn and the full conversation chain is rebuilt correctly

## Context
- relevant chat/history flow lives in `bot/handlers/gpt_handlers.py`
  - reply continuation resolves the replied-to Telegram message through `get_canonical_history_record(chat_id, message_id)`
  - chain reconstruction then walks canonical rows only via `reply_message_id`
- voice transcription flow lives in `bot/handlers/voice_handler.py`
  - `send_transcript_reply()` already splits long transcripts into Telegram-safe chunks
  - after that, `handle_voice()` currently writes exactly one alias history row using `transcript_messages[0]`
- SQLite history model lives in `bot/clients/sqlite_client.py`
  - rows are keyed by `(chat_id, message_id)`
  - `canonical_message_id` already allows multiple message ids to resolve to one semantic message
  - no schema change is needed for this fix; the current structure already supports many aliases for one canonical row
- existing coverage lives in `tests/handlers/test_voice_handler.py` and `tests/handlers/test_gpt_handlers.py`
- newly added failing regression test proves the current bug: only the first transcript chunk is persisted, so replying to a later chunk cannot resolve to the canonical voice turn
- project guidance from `AGENTS.md`: keep the solution simple and pragmatic; no heavy architecture needed

## Chosen Approach
- keep the current canonical/alias database model
- after sending transcript chunks, write one alias history row per visible chunk message
- make every alias row use:
  - `message_id = transcript chunk Telegram message id`
  - `canonical_message_id = original voice message id`
  - `reply_message_id = original voice message id`
  - `is_llm_chain = False`
- leave `gpt_handlers` canonical resolution logic unchanged, because it already does the right thing once all chunk aliases exist
- update tests to verify both persistence and reply-chain reconstruction from a non-first transcript chunk

### Why the DB structure already helps
- the current `history` table is message-centric, so each visible Telegram chunk can have its own `(chat_id, message_id)` row
- `canonical_message_id` is exactly the indirection we need: many chunk rows can point back to one canonical voice turn
- `get_canonical_history_record()` already resolves any alias message id to the canonical row, so the chat-chain logic does not need a new concept of chunk groups or special-case traversal
- this makes the fix small: populate the existing alias rows correctly rather than redesigning storage

### Rejected alternatives
- keep storing only the first chunk and add special logic to infer sibling chunks from nearby message ids
  - rejected because it is brittle, Telegram-message-order dependent, and unnecessary when alias rows already solve lookup cleanly
- redesign transcript storage into a dedicated chunks table or a separate conversation-turn/link model
  - rejected because the existing `canonical_message_id` model is already sufficient for this bot
- store each chunk as a canonical LLM history row
  - rejected because it would duplicate one user turn into multiple semantic nodes and pollute LLM context

## Development Approach
- testing approach: test-first from the already-added failing regression test
- keep changes small and local to the voice transcript persistence path
- do not change prompt-building or canonical chain traversal unless testing shows a real gap
- prefer a tiny helper for chunk-alias persistence if it improves readability, but avoid introducing new layers

## Testing Strategy
- keep the current failing regression test as the primary acceptance test
- add or adjust voice-handler tests to verify:
  - all transcript chunks are persisted as alias rows
  - all alias rows point to the same canonical voice message id
  - replying to the last visible transcript chunk rebuilds the same canonical chain
- run focused tests first:
  - `mise exec -- direnv exec . uv run pytest tests/handlers/test_voice_handler.py -k transcript`
- then run broader handler coverage:
  - `mise exec -- direnv exec . uv run pytest tests/handlers/test_voice_handler.py tests/handlers/test_gpt_handlers.py`
- if the change is very small and clean, optionally run the full suite before closing:
  - `mise exec -- direnv exec . uv run pytest`
- manual verification in Telegram if desired:
  - send a long voice message that transcribes past 4096 chars
  - reply to the final transcript chunk
  - confirm prior context is preserved

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Persist alias rows for every transcript chunk

**Files:**
- Modify: `bot/handlers/voice_handler.py`
- Modify: `tests/handlers/test_voice_handler.py`

- [ ] update the voice flow so it writes alias history for every message returned by `send_transcript_reply()` instead of only the first one
- [ ] keep the canonical voice-message history row unchanged so one voice input still maps to one semantic user turn
- [ ] ensure every chunk alias uses the original voice message id as `canonical_message_id`
- [ ] add or update tests proving all chunk aliases are persisted for a long transcript
- [ ] run focused voice-handler tests before moving on

### Task 2: Verify reply-chain reconstruction from non-first transcript chunks

**Files:**
- Modify: `tests/handlers/test_voice_handler.py`
- Modify if needed: `tests/handlers/test_gpt_handlers.py`

- [ ] verify replying to the last visible transcript chunk resolves through `get_canonical_history_record()` to the canonical voice row
- [ ] confirm the LLM prompt contains the full canonical transcript once, not per chunk
- [ ] add or refine tests for the specific regression path from the failing test
- [ ] run relevant handler tests before moving on

### Task 3: Verify acceptance criteria and document the behavior

**Files:**
- Modify: `docs/plans/20260422-transcript-chunk-alias-history.md`
- Modify if needed: `README.md`
- Modify if needed: `docs/plans/completed/20260422-voice-transcript-chat-aliases.md`

- [ ] verify all Overview requirements are covered
- [ ] verify there is still only one canonical semantic user turn per voice message
- [ ] verify transcript chunk alias rows remain excluded from LLM history building
- [ ] update any documentation or prior plan notes that currently state only the first chunk is persisted
- [ ] run the final relevant test suite

## Technical Notes
- likely implementation shape in `voice_handler.py`:
  - keep `transcript_messages = await send_transcript_reply(...)`
  - after `handle_chat_turn(...)`, iterate `for transcript_message in transcript_messages:` and write one alias row per message
- alias rows should continue using the visible chunk text for `text`, because that is what was actually shown under that Telegram `message_id`
- canonical resolution should still return the original voice row, because `get_canonical_history_record()` first looks up the alias row’s `canonical_message_id` and then fetches the canonical row by that id
- no SQLite migration is needed; this is a data-writing behavior fix, not a schema fix
- if tests reveal a need to preserve chunk ordering explicitly, first check whether current Telegram message ids and insertion order already make that unnecessary before adding extra fields

## Post-Completion
- optionally verify the behavior in the real Telegram bot with a long transcription
- if this becomes a recurring pattern for other chunked outputs, consider a tiny shared helper for alias persistence later, but do not generalize preemptively

## Plan Review

### Problem / Solution Fit
- the plan directly targets the observed bug: missing history rows for later transcript chunks
- it keeps the existing conversation semantics intact while fixing reply lookup for all visible chunks

### Scope Control
- the plan stays bounded to voice-handler persistence, regression tests, and a small documentation correction if needed
- it deliberately avoids schema changes or broader chat refactors

### Over-Engineering Check
- no new tables, services, or abstractions are required
- the existing `canonical_message_id` mechanism is reused exactly as intended

### Testing Coverage
- the known failing regression test is central to the plan
- both persistence behavior and reply-chain behavior are explicitly covered

### Convention Fit
- the plan follows the existing docs/plans structure and pytest-based workflow already used in the repo
- it matches the project preference for simple, pragmatic fixes
