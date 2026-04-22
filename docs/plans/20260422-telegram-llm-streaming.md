# Telegram LLM streaming with chunk-aware message editing

## Overview
- add visible LLM reply streaming to private chat and voice-driven chat turns by editing Telegram messages as OpenRouter tokens arrive
- keep the existing canonical-plus-alias SQLite history model for long replies so every visible assistant chunk still resolves to one semantic assistant turn
- avoid schema changes and avoid a large architecture change; keep the work local to the current chat handler flow
- expected result: the bot replies immediately with an in-progress placeholder like `...🤔`, keeps updating it while the assistant reply grows, long replies continue into additional Telegram messages when needed, failures replace the in-progress text with a visible error message, and replying to any visible chunk continues the same conversation context

## Context
- `bot/handlers/gpt_handlers.py` is the main chat path
  - `handle_chat_turn()` stores the user turn and calls `generate_llm_reply()`
  - `generate_llm_reply()` currently uses `await llm_.achat(...)`, then sends one or more final Telegram reply messages
  - long assistant replies already persist as one canonical assistant row plus alias rows for later visible chunks
- `bot/handlers/voice_handler.py` feeds transcribed voice/audio into `handle_chat_turn()`, so assistant streaming should work there automatically if the chat reply path changes
- `bot/clients/sqlite_client.py` already supports the needed message-centric storage model
  - canonical assistant row stores full text once
  - later visible assistant chunks are alias rows with `text = NULL`
  - `get_canonical_history_record()` already resolves any chunk reply back to the canonical row
- `tests/handlers/test_gpt_handlers.py` already covers long non-streaming assistant chunk persistence and reply-chain resolution from later assistant chunks
- the LlamaIndex OpenRouter client supports `astream_chat(...)`, so transport-level streaming is available
- project guidance from `AGENTS.md`: prefer pragmatic, simple solutions over heavy architecture; load is tiny, so a lightweight in-process streaming helper is appropriate

## Chosen Approach
- keep the current chat flow shape and implement streaming locally inside `generate_llm_reply()` plus a couple of tiny file-local helpers in `gpt_handlers.py`
- use `OpenRouter.astream_chat(...)` to collect streamed deltas into one growing `full_text`
- immediately send the first assistant message with an in-progress marker like `...🤔`
- on each throttled flush:
  - split `full_text` into Telegram-safe chunks using `MAX_MESSAGE_LENGTH`
  - keep a list of visible Telegram assistant messages
  - edit only the current last visible chunk if its text changed
  - send a new continuation Telegram message when a new chunk appears
  - keep the in-progress marker on the currently growing last chunk until streaming finishes
- throttle all Telegram writes, including both `edit_text()` and new `reply_text()` calls, to a simple per-chat cadence such as roughly once per second
- persist assistant history only after the stream finishes successfully
  - first visible assistant chunk becomes the canonical assistant history row with full final text
  - later visible chunks become alias rows with `text = NULL`
- if generation fails after the placeholder was sent, update the active visible chunk to a clear error message instead of leaving a stale in-progress marker behind

### Concrete implementation shape
- add a few file-local constants near `MAX_MESSAGE_LENGTH`, for example:
  - `STREAM_IN_PROGRESS_SUFFIX = ' ...🤔'`
  - `STREAM_ERROR_TEXT = 'Ошибка генерации ответа.'`
  - `STREAM_FLUSH_INTERVAL_SECONDS = 1.0`
- keep helper count small and purpose-specific; for example:
  - `split_text_for_telegram(text: str) -> list[str]`
  - `build_visible_stream_chunks(full_text: str, is_final: bool) -> list[str]`
  - `flush_stream_updates(...) -> list[Message]`
  - `persist_assistant_history(...) -> None`
- pass the original incoming user `message` into `generate_llm_reply()` as today; all assistant chunk messages should still use `reply_to_message_id=message.message_id`
- keep the existing `markdown_to_telegram_html(..., parse_mode='HTML')` behavior for every streamed update and the final flush; do not introduce a separate plain-text streaming mode in this change

### Step-by-step algorithm
1. Build LLM messages exactly as today.
2. Send the initial assistant placeholder reply with `...🤔` and store that returned Telegram `Message` as `reply_messages[0]`.
3. Start `async for chunk in llm_.astream_chat(messages=messages):`.
4. For each streamed chunk:
   - append `chunk.delta` if present; otherwise ignore empty events
   - if enough time has passed since the last flush, recompute visible chunks and flush Telegram updates
5. Visible chunk computation rules:
   - derive chunks from the current `full_text`
   - if streaming is still in progress, append ` ...🤔` only to the last visible chunk
   - while streaming, treat the suffix as part of the visible text for chunk splitting, so the active chunk may split slightly earlier than the final text
   - if `full_text` is empty, visible chunks should still be `["...🤔"]`
6. Flush rules:
   - if a visible chunk already has a Telegram message and text changed, re-render that chunk from scratch via `markdown_to_telegram_html(...)` and call `edit_text()` with the full newly formatted chunk text
   - if a visible chunk has no Telegram message yet, create it with `message.reply_text(...)` using the full formatted chunk text
   - do not try to patch only the delta inside an existing chunk; each update should replace the whole visible chunk content
   - do not touch earlier chunks whose text is already final and unchanged
7. After the stream completes, do one final flush with `is_final=True` so the `...🤔` suffix is removed.
8. Persist history using the final `full_text` and the collected `reply_messages`.
9. If streaming raises after the placeholder exists, replace the currently active visible chunk text with `Ошибка генерации ответа.` and skip assistant history persistence.
10. If the stream yields no non-empty deltas, finish by replacing the placeholder with a simple fallback final text instead of leaving `...🤔`; use `Ошибка генерации ответа.` for this case too.

### Why this fits the current codebase
- the current canonical/alias model already matches streamed multi-message assistant output
- the existing reply-chain resolution logic does not need to change if final history rows are written in the same canonical-plus-alias shape as today
- voice chat gets the feature automatically because it already reuses `handle_chat_turn()`
- the only genuinely new concern is Telegram presentation state, so the plan keeps new code concentrated in `gpt_handlers.py` and avoids introducing a new reusable abstraction layer before we know we need one

### Rejected alternatives
- stream only within one Telegram message and fall back to non-streaming chunk sends after overflow
  - rejected because the user explicitly prefers full chunk-aware streaming and the existing alias model already supports it cleanly
- redesign storage around a separate turns/chunks table
  - rejected because current message-centric canonical alias storage is already sufficient
- introduce a generic background scheduler or queue for stream flushing
  - rejected because the bot has tiny load and does not need infrastructure beyond one async helper per request
- change voice transcript storage as part of this work
  - rejected because transcript chunk aliasing already works and is independent from assistant-side streaming

## Development Approach
- testing approach: implementation-first with focused unit tests around the streamed reply path
- keep existing reply-chain and storage helpers unless a concrete test proves they need adjustment
- minimize new abstractions; prefer a straightforward `generate_llm_reply()` refactor with small file-local helpers over a new class-heavy design
- prefer deterministic flush logic that can be tested without sleeping in real time
- keep the final persistence contract identical to current long-reply behavior: one canonical assistant row plus aliases

## Testing Strategy
- update `tests/handlers/test_gpt_handlers.py` to cover streamed assistant replies in both single-chunk and multi-chunk cases
- do not rely on a special LlamaIndex test helper; instead monkeypatch `llm()` to return a tiny fake object whose `astream_chat()` yields deterministic async chunks
- verify throttled streaming behavior with mocked time / injected clock values instead of real waiting where possible
- preserve existing long-reply canonical/alias expectations and update them to operate through the new streaming path
- add coverage for the in-progress marker on partial updates and for replacing it with an error message on simple failure scenarios after streaming has started

### Recommended fake streaming test setup
- keep test scaffolding close to current `FakeLLM` patterns in `tests/handlers/test_gpt_handlers.py`
- extend the fake to support:
  - `astream_chat()` yielding `SimpleNamespace(delta='...')` items
  - optional terminal event carrying `raw={'usage': ...}` if the implementation wants usage logging at the end
  - optional exception injection after N chunks for failure-path tests
- for message doubles:
  - the incoming user message should still expose `reply_text=AsyncMock(...)`
  - returned assistant message doubles should expose `edit_text=AsyncMock(...)`
  - multi-chunk tests should return distinct assistant message doubles with stable `message_id` values so alias persistence can be asserted
- for throttling tests, monkeypatch a small `now()` helper or `time.monotonic()` wrapper in `gpt_handlers.py`; do not sleep in tests

### Minimum acceptance test list
- short streamed reply:
  - sends immediate `...🤔`
  - edits same assistant message as chunks arrive
  - each streamed update re-formats the entire visible chunk through `markdown_to_telegram_html(..., parse_mode='HTML')`, not just the new delta
  - final edit removes `...🤔`
  - persists one canonical assistant row
- long streamed reply:
  - creates second/third assistant Telegram messages when text exceeds `MAX_MESSAGE_LENGTH`
  - covers boundary cases around the suffix affecting the active chunk length
  - persists first assistant message as canonical and later ones as aliases
- reply continuity:
  - replying to a later streamed assistant chunk resolves to the canonical assistant turn and includes full prior assistant text once in the next prompt
- simple failure handling:
  - if streaming fails after partial output, active chunk shows a visible error message
  - if streaming yields no non-empty deltas, the placeholder is replaced with the same error message
  - no assistant history row is written for the failed generation
- focused commands:
  - `mise exec -- direnv exec . uv run pytest tests/handlers/test_gpt_handlers.py`
  - `mise exec -- direnv exec . uv run pytest tests/handlers/test_voice_handler.py tests/handlers/test_gpt_handlers.py`
- manual Telegram verification:
  - send a short text prompt and confirm one message is edited in place while the reply grows
  - send a prompt that produces a long reply and confirm a second/third assistant message appears when the current chunk fills
  - reply to the last visible assistant chunk and confirm prior context includes the full canonical assistant reply once
  - send a voice/audio message and confirm assistant streaming works there too

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Refactor assistant reply generation with minimal local helpers

**Files:**
- Modify: `bot/handlers/gpt_handlers.py`
- Modify: `tests/handlers/test_gpt_handlers.py`

- [x] add the streaming constants and a tiny `now()` wrapper in `gpt_handlers.py` so throttling is easy to test
- [x] refactor `generate_llm_reply()` just enough to separate chunk splitting, visible message updates, and final persistence into small file-local helpers
- [x] keep streaming state simple and local: accumulated `full_text`, visible Telegram messages, and last flush timestamp / last sent chunk texts
- [x] keep chunk splitting based on `MAX_MESSAGE_LENGTH` so streamed and final persistence use the same visible boundaries
- [x] add or update tests for helper behavior and a single-chunk streamed reply, including the immediate `...🤔` placeholder behavior
- [x] run relevant tests / validation before moving on

### Task 2: Implement chunk-aware Telegram streaming updates

**Files:**
- Modify: `bot/handlers/gpt_handlers.py`
- Modify: `tests/handlers/test_gpt_handlers.py`

- [x] switch the assistant generation path from `achat()` to `astream_chat()` for the main reply flow
- [x] append streamed deltas into accumulated `full_text`, ignoring empty / missing deltas
- [x] send the initial placeholder message before consuming the stream so users see immediate progress feedback
- [x] throttle Telegram writes so repeated updates do not attempt to edit on every token and do not create continuation chunks too quickly
- [x] edit only the current last visible chunk when text changes within that chunk
- [x] create a new continuation Telegram reply message when accumulated text produces a new chunk beyond the existing visible messages
- [x] keep the currently growing last chunk marked with `...🤔` until the stream completes
- [x] add or update tests covering multi-chunk streamed output, suffix-related boundary behavior, and the correct sequence of throttled `reply_text()` / `edit_text()` calls
- [x] run relevant tests / validation before moving on

### Task 3: Persist final streamed assistant output as canonical plus aliases

**Files:**
- Modify: `bot/handlers/gpt_handlers.py`
- Modify: `tests/handlers/test_gpt_handlers.py`
- Modify if needed: `tests/handlers/test_voice_handler.py`

- [x] persist history only after stream completion using the final `full_text` and the collected visible assistant messages
- [x] keep the first visible assistant message as the canonical assistant row containing full final text
- [x] keep later visible assistant messages as alias rows with `text = NULL`
- [x] ensure replies to later streamed assistant chunks still resolve to the same canonical assistant turn
- [x] confirm voice-driven chat inherits the same assistant persistence behavior without changing transcript storage semantics
- [x] add or update tests for reply-chain reconstruction from a later streamed assistant chunk
- [x] run relevant tests / validation before moving on

### Task 4: Error handling, final flush, and acceptance verification

**Files:**
- Modify: `bot/handlers/gpt_handlers.py`
- Modify: `tests/handlers/test_gpt_handlers.py`
- Modify if needed: `README.md`

- [x] ensure a final flush happens after streaming ends so Telegram shows the full completed text and the in-progress marker is removed
- [x] handle only simple Telegram edit edge cases pragmatically, especially retry-after and no-op edit scenarios, without corrupting final output
- [x] ensure stream failures after the placeholder was sent replace the active chunk with a visible error message and do not write inconsistent assistant history rows
- [x] verify all acceptance criteria from Overview are covered
- [x] run the relevant test suite
- [x] update documentation only if behavior changes are worth noting for future maintenance

## Technical Notes
- keep the implementation local and boring: file-local helpers are fine, but avoid introducing a new conversation abstraction or a reusable streaming framework in this change
- the source of truth during generation is accumulated assistant `full_text`; visible chunk texts are derived from it on flush, and each changed chunk is fully re-formatted before sending the edit
- only the last visible chunk should keep changing after previous chunks fill up
- each partial visible update should show the in-progress marker on the currently active chunk; the final flush removes it
- each new visible assistant chunk is a real Telegram message id and must be retained for final alias persistence
- reply parent linkage should remain the canonical user turn passed into `generate_llm_reply()`; do not point assistant chunk aliases at each other
- keep sleep/time behavior injectable or isolated enough that tests can drive throttled flushes deterministically
- avoid schema changes unless implementation reveals a concrete storage gap, which is not expected

### Guardrails / non-goals for the implementer
- do not change voice transcript alias persistence in `voice_handler.py`; this plan is assistant-streaming only
- do not refactor unrelated history helpers just because streaming touches the same file
- do not add background tasks, queues, threads, or persistence of partial assistant text
- keep the existing markdown-to-HTML formatting path; do not add a separate rendering mode in this change
- keep error handling simple; cover obvious retry-after / no-op edit behavior and visible failure messaging, but do not build a large recovery system
- if usage extraction from streamed responses is awkward, keep existing usage logging only where it is easy and correct rather than blocking the feature on it

## Post-Completion
- manually verify UX in a real Telegram chat for both short and long replies
- decide later whether final formatting should remain exactly as-is or be adjusted separately from streaming mechanics
- if durable implementation learnings emerge, update `agents.md` or another guidance file after the feature is stable
