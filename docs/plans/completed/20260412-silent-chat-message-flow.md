# Silent text-based LLM chat flow

## Overview
- replace command-based `/chat` usage with a natural text-message flow for private chats
- make authorization checks silent by default: unauthorized users and users without required features should be ignored without a reply
- consolidate chat, reply-chain reconstruction, and history persistence into one text handler
- expected result: authorized users with the `chat` feature can message the bot directly, replies continue known LLM threads, and everyone else is silently ignored

## Context
- `bot/handlers/security.py` currently wraps handlers with authorization but always sends denial messages on failure
- `bot/handlers/gpt_handlers.py` currently splits chat behavior across three paths: `/chat`, passive history tracking, and reply continuation
- `bot/main.py` still wires `track_history_handler` globally while chat and reply handlers remain commented out
- SQLite history persistence already exists and can support reply-chain reconstruction without adding new storage
- project scope is small and private, so a single explicit text-chat handler is preferable to layered middleware or multiple overlapping handlers

## Chosen Approach
- make `add_authorization` silent on denial by default instead of adding a separate silent flag
- keep denial logging for troubleshooting, but do not send denial messages back to Telegram users
- replace the current `/chat` + reply + history split with one private non-command text handler
- record every authorized `chat` text message in SQLite before or alongside processing, because Telegram message lookup by id is not available later and reply chains must be reconstructable from local history
- when a message is a reply to known stored history, rebuild the prior chain and continue it; otherwise treat the message as a fresh prompt
- reject alternatives that keep separate tracking middleware, because they record unrelated messages and complicate the flow

## Development Approach
- testing approach: implementation-first with immediate test updates in each task
- keep changes small and focused
- complete one task fully before starting the next
- update the plan if scope changes materially
- prefer simple solutions over speculative abstractions

## Testing Strategy
- update authorization tests to verify silent denial behavior
- add chat-handler tests for fresh prompts, reply-chain continuation, and reply behavior when only locally stored user history exists
- remove or adapt tests tied to `/chat` command parsing and global history tracking
- run `mise exec -- direnv exec . uv run pytest`

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Make authorization silent by default

**Files:**
- Modify: `bot/handlers/security.py`
- Modify: `tests/handlers/test_security.py`

- [x] change authorization denial behavior to return silently instead of replying to the user
- [x] keep successful authorization and feature checks unchanged
- [x] add or update tests to verify silent ignore for unauthorized and feature-disabled users
- [x] run relevant tests / validation before moving on

### Task 2: Refactor LLM text handling into one message flow

**Files:**
- Modify: `bot/handlers/gpt_handlers.py`
- Modify: `tests/handlers/test_gpt_handlers.py`

- [x] introduce a unified private text chat handler for non-command text messages
- [x] reuse existing history helpers to persist every authorized `chat` text message needed for later reply reconstruction
- [x] rebuild reply chains from stored assistant history when available
- [x] treat replies without matching stored history as fresh prompts
- [x] remove command-prefix stripping and obsolete split-handler logic
- [x] add or update tests for fresh prompts, reply continuation, and edge cases
- [x] run relevant tests / validation before moving on

### Task 3: Rewire application setup around the new chat flow

**Files:**
- Modify: `bot/main.py`
- Modify: `bot/handlers/__init__.py`

- [x] register the unified text chat handler with `feature=Feature.chat`
- [x] stop registering obsolete `/chat`, reply, and passive history handlers
- [x] keep admin and voice handler wiring intact
- [x] run relevant tests / validation before moving on

### Task 4: Verify acceptance criteria and cleanup
- [x] verify unauthorized and feature-disabled users are silently ignored across protected handlers
- [x] verify chat users can start fresh conversations and continue reply chains naturally
- [x] run the full relevant test suite
- [x] update this plan to reflect final completion state

## Technical Notes
- silent authorization means admin commands will also ignore unauthorized callers; explicit denial responses can be reintroduced later if needed
- keep warning/error logging for authorization denials and processing failures, but avoid logging full user message text unless needed later
- the unified chat handler should target `filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND`
- reply-chain reconstruction should continue using stored SQLite history keyed by `(chat_id, message_id)`
- history writes should happen inside the chat handler, not via a global side-channel handler

## Post-Completion
- manually confirm the Telegram UX feels natural when sending plain text and replying to bot messages
- decide later whether any protected admin-only commands should regain explicit denial responses
