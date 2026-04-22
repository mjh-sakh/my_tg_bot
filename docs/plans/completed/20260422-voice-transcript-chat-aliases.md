# Voice transcripts as canonical chat turns with Telegram message aliases

## Overview
- integrate direct private voice/audio messages into the same AI chat pipeline used by plain text messages
- keep transcripts visible in Telegram while avoiding duplicate semantic history in SQLite
- preserve reply continuity when a user replies to either the original voice message or the visible transcript message
- keep the design small and local-first by extending the existing message-centric SQLite history model with canonical message aliases instead of introducing a separate turns table
- expected result: direct voice messages can start or continue an AI conversation, text and voice can alternate naturally, and reply-chain reconstruction remains deterministic

## Context
- stack: Python 3.13, `python-telegram-bot` 22.7, SQLite, LlamaIndex chat message types, OpenRouter for LLM replies, Together AI for speech-to-text (`nvidia/parakeet-tdt-0.6b-v3`)
- current text chat flow lives in `bot/handlers/gpt_handlers.py`
  - stores each authorized text message in SQLite history keyed by `(chat_id, message_id)`
  - rebuilds a single backward reply chain from stored history
  - sends an LLM reply and stores the assistant message in history
- current voice flow lives in `bot/handlers/voice_handler.py`
  - downloads voice/audio
  - transcribes it
  - replies visibly with the transcript
  - does not write history and does not call the LLM chat pipeline
- current SQLite history schema in `bot/clients/sqlite_client.py` stores message-centric rows and has no aliasing concept
- current tests already cover:
  - SQLite history round-trips in `tests/clients/test_sqlite_client.py`
  - text chat reconstruction in `tests/handlers/test_gpt_handlers.py`
  - voice transcription reply behavior in `tests/handlers/test_voice_handler.py`
- Telegram library support relevant to this task:
  - `Message.reply_to_message` is available for reply-chain continuation
  - `Message.forward_origin` and `Message.is_automatic_forward` can distinguish forwarded/automatic-forwarded messages from direct ones
- project constraints from `AGENTS.md`:
  - very small audience, low load
  - no meaningful backward-compatibility requirements
  - prefer pragmatic and simple solutions over heavy architecture

## Chosen Approach
- extend the existing `history` table with a lightweight canonical alias mechanism instead of redesigning storage into separate turns and link tables
- add `canonical_message_id` to each history row
  - canonical rows represent real LLM turns and have `canonical_message_id == message_id`
  - alias rows exist only for lookup and have `canonical_message_id != message_id`
- store the semantic user turn for a voice message on the original user voice message id
- store the visible transcript message as an alias row that resolves back to the original voice message id
- always resolve replied-to message ids to their canonical history row before:
  - reconstructing context
  - storing parent links for new user or assistant turns
- keep alias rows out of LLM history so transcript text is stored once semantically and never duplicated in the prompt
- treat only direct private voice/audio messages as AI-chat input; forwarded or automatic-forwarded messages should not enter the AI chat chain

### Rejected alternatives
- duplicate the transcript as separate history rows for both the voice message and the transcript message
  - rejected because it creates two competing semantic nodes for one user turn and makes branching/reconstruction ambiguous
- redesign storage around fully separate `chat_turns` and `message_turn_links` tables
  - rejected because it is clean but larger than necessary for this small bot and current codebase

### Notable trade-offs
- alias rows keep the current schema mostly intact, but they require careful helper usage so only canonical rows are used for chain traversal
- using the original voice message id as the canonical id makes replies to the audio bubble work naturally, while the transcript remains a visible alias
- schema migration is required for existing SQLite databases because `CREATE TABLE IF NOT EXISTS` alone will not add the new column
- the plan chooses explicit backfill over implicit "use `canonical_message_id` if present else fall back to `message_id`" behavior, because a fully populated column keeps lookup logic simpler, avoids mixed-row semantics, and makes production inspection/debugging easier

## Development Approach
- testing approach: implementation-first with immediate test updates in each task
- keep changes small and focused
- complete one task fully before starting the next
- update the plan if scope changes materially
- prefer simple shared helpers over speculative abstractions
- keep the final implementation understandable to someone new to the codebase

## Testing Strategy
- extend SQLite tests for canonical rows, alias rows, and canonical resolution
- extend text chat handler tests to verify canonical parent resolution and unchanged text behavior
- extend voice handler tests to verify:
  - transcript visibility
  - canonical/alias history writes
  - voice-initiated LLM replies
  - reply continuation through both voice and transcript message ids
  - forwarded voice/audio exclusion from AI chat
- add at least one integration-style handler test covering a mixed text/voice/thread continuation flow
- run `mise exec -- direnv exec . uv run pytest`
- manual verification in Telegram after implementation:
  - send a direct voice message and confirm transcript + AI reply
  - reply to the original voice message with text and confirm context continues
  - reply to the visible transcript with voice and confirm context continues
  - confirm forwarded voice/audio does not enter AI chat context

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Add canonical alias support to SQLite history

**Files:**
- Modify: `bot/clients/sqlite_client.py`
- Modify: `tests/clients/test_sqlite_client.py`

- [x] add `canonical_message_id` to the `history` schema for fresh databases
- [x] add a lightweight migration path for existing databases, including backfilling existing rows with `canonical_message_id = message_id`
- [x] add one explicit alias-supporting index: `idx_history_chat_canonical_message_id` on `(chat_id, canonical_message_id)`
- [x] add or update persistence helpers so inserts can store canonical rows and alias rows explicitly
- [x] add a helper that resolves a `(chat_id, message_id)` lookup to the canonical history row
- [x] add tests for canonical row round-trip, alias row round-trip, and canonical resolution behavior
- [x] add tests for migration/backfill behavior on a database created without the new column
- [x] run relevant tests / validation before moving on

### Task 2: Refactor chat history helpers around canonical resolution

**Files:**
- Modify: `bot/handlers/gpt_handlers.py`
- Modify: `tests/handlers/test_gpt_handlers.py`

- [x] introduce shared helper functions that work from explicit user text plus the incoming Telegram message, so text and voice can reuse one chat-turn pipeline
- [x] update history lookup to resolve replied-to messages through the new canonical SQLite helper before chain reconstruction
- [x] ensure stored `reply_message_id` values always point to canonical parent rows, never alias rows
- [x] keep `build_chain_from_record()` traversing only canonical rows and never alias rows
- [x] preserve current text chat behavior for fresh prompts and reply continuation
- [x] add tests proving replies to alias-backed messages resolve to the correct canonical chain
- [x] add tests proving plain text flows are unchanged after the refactor
- [x] run relevant tests / validation before moving on

### Task 3: Integrate direct voice/audio into the shared AI chat pipeline

**Files:**
- Modify: `bot/handlers/voice_handler.py`
- Modify: `bot/handlers/gpt_handlers.py`
- Modify: `tests/handlers/test_voice_handler.py`
- Modify: `tests/handlers/test_gpt_handlers.py`

- [x] update voice handling to treat only direct private `voice` or `audio` messages as AI-chat input
- [x] explicitly detect forwarded or automatic-forwarded messages and keep them out of AI chat history and LLM context
- [x] after transcription, store a canonical user history row on the original voice message id using the transcript text
- [x] keep the transcript visible by sending a Telegram text reply and storing that message as an alias row pointing to the original voice message id
- [x] feed the transcript text into the shared chat-turn pipeline so the assistant reply is generated and stored like any other chat reply
- [x] ensure the assistant reply stores its parent as the canonical user voice turn, even if the visible transcript message exists
- [x] preserve transcript chunking behavior if needed for long transcripts, or replace it deliberately with one-message transcript behavior and update tests/documentation accordingly
- [x] add tests for a fresh direct voice message producing transcript visibility, history writes, and an assistant reply
- [x] add tests for forwarded voice/audio not entering AI chat
- [x] run relevant tests / validation before moving on

### Task 4: Verify mixed text/voice reply continuity and handler wiring

**Files:**
- Modify: `bot/main.py`
- Modify: `tests/handlers/test_voice_handler.py`
- Modify: `tests/handlers/test_gpt_handlers.py`
- Modify: `tests/e2e/test_chat_openrouter_e2e.py`

- [x] confirm handler wiring still keeps text chat on the existing private non-command path and voice/audio on the voice handler path
- [x] decide and codify the authorization/feature-gate policy for voice-driven AI chat; keep existing voice transcription authorization and require chat-enabled users (or admins) for LLM participation
- [x] add integration-style tests covering at least these chains:
  - direct voice -> transcript -> assistant -> text reply continues context
  - direct voice -> transcript -> assistant -> voice reply continues context
  - reply to transcript alias resolves to the same canonical chain as reply to original voice message
- [x] update or add an e2e test if practical to cover a real OpenRouter reply after a transcribed user turn, otherwise document why this remains manual-only
- [x] run relevant tests / validation before moving on

Status note: the existing OpenRouter e2e test remains text-only; transcribed-turn verification is still manual-only because the current e2e harness does not exercise Telegram voice download/transcription flow against external providers.

### Task 5: Verify acceptance criteria

- [x] verify all requirements from Overview are covered
- [x] verify transcript text is stored once semantically and alias rows are excluded from LLM message history
- [x] verify replies to both the original voice message and the visible transcript resolve to the same canonical user turn
- [x] verify forwarded voice/audio messages do not contaminate AI chat history
- [x] run the full relevant test suite
- [ ] run end-to-end or manual verification in Telegram if applicable

### Task 6: Deploy and verify in the real bot environment

**Files:**
- Modify if needed: `docs/deploy.md`
- Modify if needed: `scripts/deploy.sh`
- Modify: `docs/plans/20260422-voice-transcript-chat-aliases.md`

- [x] deploy the change to the environment used for real Telegram verification
- [x] verify startup migration succeeds on the deployed SQLite database without manual DB intervention
- [x] perform real-user verification of these flows after deploy:
  - direct voice -> visible transcript -> assistant reply
  - reply to original voice message continues context
  - reply to visible transcript continues the same context
  - text and voice can alternate within one thread
- [x] record observed behavior, surprises, and any follow-up fixes in this plan before closing it out

Deployment note: deployed to `netcup` with `scripts/deploy.sh`. Container started cleanly, startup logs were healthy, and the production SQLite file remained present at `/opt/my_tg_bot/data/bot.sqlite`.

Real Telegram verification note: confirmed working end-to-end. Direct voice produced a visible transcript and assistant reply, and replying to either the original voice message or the transcript continued the same conversation context. No follow-up fixes were needed during verification.

### Task 7: Final documentation and cleanup

**Files:**
- Modify: `README.md`
- Modify: `docs/plans/20260422-voice-transcript-chat-aliases.md`
- ➕ Modify if needed: `AGENTS.md`

- [x] update README or developer documentation to explain the new voice-to-chat behavior and canonical alias history model if needed
- [x] update this plan with final completion state, notable deviations, and follow-up items
- [x] update project guidance files only if durable implementation knowledge was discovered during the work
- [x] move or mark the plan as completed if the project uses that convention

Final state: completed and deployed.

Notable implementation details:
- transcript chunking was preserved for Telegram visibility, but only the first visible transcript message is persisted as the alias row
- voice transcription remains available under the existing voice handler authorization, while LLM participation for voice turns requires chat access (admins bypass feature gating)
- the OpenRouter e2e test remains text-only; real transcribed-turn verification was completed manually in Telegram after deploy

Follow-up items:
- if forwarded voice UX needs to change later, decide whether forwarded items should be silently ignored or receive transcription-only behavior outside the AI chat path

## Technical Notes
- preferred canonical semantics:
  - canonical user voice row: stored on the original incoming voice/audio `message_id`
  - visible transcript row: alias row whose `canonical_message_id` points to the original voice/audio `message_id`
  - assistant row: canonical row whose `reply_message_id` points to the canonical parent user row
- alias rows should not be added to `build_llm_messages()` output
- keep role values and existing LlamaIndex `ChatMessage` construction unchanged for canonical rows
- if transcript text is chunked into multiple visible Telegram messages, either:
  - make only the first transcript message an alias and treat the rest as presentation-only messages with no history role, or
  - simplify the UX to a single visible transcript message before implementation; do not silently create multiple semantic aliases for one canonical user turn
- because existing production/dev SQLite files may already exist, migration must be additive and safe on startup
- run migration/backfill/index creation from `SQLiteClient.init_db()` or a helper it calls, rather than introducing a separate migration module for this change
- planned indexes for this change are:
  - keep the existing primary key on `(chat_id, message_id)` for direct and canonical row fetches
  - add `idx_history_chat_canonical_message_id` on `(chat_id, canonical_message_id)` to support alias-oriented lookups and inspection
  - do not add a reply-link index in this change, because chain traversal still resolves parents through primary-key lookups by `(chat_id, message_id)`
- consider adding a dedicated helper name that makes intent obvious, e.g. `get_canonical_history_record()` or `resolve_history_record()`
- keep the implementation grounded in current repository patterns; avoid introducing services, repositories, or event layers for this change

## Post-Completion
- manually confirm Telegram UX feels natural when the bot posts both transcript and assistant reply for a voice message
- decide whether forwarded voice/audio should be silently ignored or still receive visible transcription outside the AI chat path; this plan assumes they stay out of AI chat, but final UX wording may still need confirmation
- if the chosen feature-gate policy for voice-driven AI chat is stricter than current behavior, confirm it with real user accounts after deployment
- if deployment verification reveals migration friction or awkward transcript UX, capture the durable lesson in project guidance before the next related change

## Plan Review

### Problem / Solution Fit
- the plan directly addresses the real problem: one logical user voice turn may correspond to multiple Telegram message ids, and both ids must continue the same AI conversation
- the canonical alias design keeps transcripts visible while avoiding duplicate semantic rows in LLM history
- reply resolution, migration, and mixed text/voice flows are explicitly covered so the solution does not stop at transcription-only behavior

### Scope Control
- the plan is limited to SQLite history, text/voice handlers, wiring, tests, and small documentation updates
- it intentionally avoids broader architecture changes such as a dedicated conversation graph layer or a full turn/link table split
- the only open scope item is final voice feature-gate policy; the plan calls this out instead of hiding it

### Over-Engineering Check
- the plan adds one column, minimal migration/index work, and a few targeted helpers rather than a new abstraction stack
- it reuses existing handler structure and SQLite persistence instead of introducing new storage layers
- alias rows are a narrow mechanism for Telegram lookup, not a generalized graph engine

### Testing Coverage
- every code-changing task includes explicit test updates
- success cases, migration cases, reply-alias cases, and forwarded-message edge cases are all covered
- validation is included after each task and again at acceptance verification

### Convention Fit
- the plan follows the existing repository layout and completed-plan style under `docs/plans`
- it uses current libraries, the SQLite-backed history pattern, and pytest-based testing already present in the repo
- it stays aligned with the project guidance to prefer pragmatic, easy-going solutions over heavy architecture
