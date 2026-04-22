from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from llama_index.core.base.llms.types import MessageRole
from pydantic import ValidationError

from bot.clients.sqlite_client import SQLiteClient
from bot.handlers import gpt_handlers


@pytest.mark.asyncio
async def test_history_records_use_chat_scoped_keys(tmp_path, monkeypatch):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)

    await gpt_handlers.write_history_record(
        chat_id=1,
        message_id=42,
        text='from chat 1',
        role=MessageRole.USER,
    )
    await gpt_handlers.write_history_record(
        chat_id=2,
        message_id=42,
        text='from chat 2',
        role=MessageRole.USER,
    )

    record_1 = await gpt_handlers.get_history_record(1, 42)
    record_2 = await gpt_handlers.get_history_record(2, 42)

    assert record_1 is not None
    assert record_2 is not None
    assert record_1.text == 'from chat 1'
    assert record_2.text == 'from chat 2'


@pytest.mark.asyncio
async def test_handle_text_chat_sends_fresh_prompt_and_records_history(tmp_path, monkeypatch):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 2.0, 2.0]))

    fake_llm = FakeLLM(chunks=['assistant reply'])
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    update = make_update(chat_id=55, message_id=11, text='hello there')

    await gpt_handlers.handle_text_chat(update, object())

    sent_messages = fake_llm.calls[0]
    assert [message.role for message in sent_messages] == [MessageRole.SYSTEM, MessageRole.USER]
    assert sent_messages[-1].content == 'hello there'

    user_record = await gpt_handlers.get_history_record(55, 11)
    assistant_record = await gpt_handlers.get_history_record(55, 12)
    assert user_record is not None
    assert user_record.text == 'hello there'
    assert user_record.canonical_message_id == 11
    assert assistant_record is not None
    assert assistant_record.text == 'assistant reply'
    assert assistant_record.reply_message_id == 11

    update.message.reply_text.assert_awaited_once_with(
        '...🤔',
        parse_mode='HTML',
        reply_to_message_id=11,
    )
    assistant_message = update.message.sent_replies[0]
    assert [call.args[0] for call in assistant_message.edit_text.await_args_list] == [
        'assistant reply ...🤔',
        'assistant reply',
    ]


@pytest.mark.asyncio
async def test_handle_text_chat_rebuilds_reply_chain_from_stored_history(tmp_path, monkeypatch):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 2.0, 2.0]))

    await gpt_handlers.write_history_record(
        chat_id=77,
        message_id=1,
        text='first user message',
        role=MessageRole.USER,
    )
    await gpt_handlers.write_history_record(
        chat_id=77,
        message_id=2,
        text='second user message',
        reply_chat_id=77,
        reply_message_id=1,
        role=MessageRole.USER,
    )

    fake_llm = FakeLLM(chunks=['assistant reply'])
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    update = make_update(
        chat_id=77,
        message_id=3,
        text='third user message',
        reply_to_message=SimpleNamespace(chat_id=77, message_id=2),
    )

    await gpt_handlers.handle_text_chat(update, object())

    sent_messages = fake_llm.calls[0]
    assert [message.content for message in sent_messages] == [
        gpt_handlers.SYSTEM_PROMPT,
        'first user message',
        'second user message',
        'third user message',
    ]


@pytest.mark.asyncio
async def test_handle_text_chat_resolves_reply_to_alias_backed_message(tmp_path, monkeypatch):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 2.0, 2.0]))

    await gpt_handlers.write_history_record(
        chat_id=77,
        message_id=10,
        canonical_message_id=10,
        text='voice transcript',
        role=MessageRole.USER,
    )
    await gpt_handlers.write_history_record(
        chat_id=77,
        message_id=11,
        canonical_message_id=10,
        text=None,
        reply_chat_id=77,
        reply_message_id=10,
        role=MessageRole.USER,
    )

    fake_llm = FakeLLM(chunks=['assistant reply'])
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    update = make_update(
        chat_id=77,
        message_id=12,
        text='reply to transcript alias',
        reply_to_message=SimpleNamespace(chat_id=77, message_id=11),
    )

    await gpt_handlers.handle_text_chat(update, object())

    sent_messages = fake_llm.calls[0]
    assert [message.content for message in sent_messages] == [
        gpt_handlers.SYSTEM_PROMPT,
        'voice transcript',
        'reply to transcript alias',
    ]

    user_record = await gpt_handlers.get_history_record(77, 12)
    assert user_record is not None
    assert user_record.reply_message_id == 10


@pytest.mark.asyncio
async def test_handle_text_chat_treats_reply_to_unknown_message_as_fresh_prompt(tmp_path, monkeypatch):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 2.0, 2.0]))

    fake_llm = FakeLLM(chunks=['assistant reply'])
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    update = make_update(
        chat_id=88,
        message_id=5,
        text='fresh despite reply',
        reply_to_message=SimpleNamespace(chat_id=88, message_id=4),
    )

    await gpt_handlers.handle_text_chat(update, object())

    sent_messages = fake_llm.calls[0]
    assert [message.role for message in sent_messages] == [MessageRole.SYSTEM, MessageRole.USER]
    assert sent_messages[-1].content == 'fresh despite reply'

    user_record = await gpt_handlers.get_history_record(88, 5)
    assert user_record is not None
    assert user_record.reply_message_id is None


@pytest.mark.asyncio
async def test_get_history_record_returns_none_on_sqlite_error(monkeypatch):
    class BrokenSQLiteClient:
        def get_history_record(self, chat_id, message_id):
            raise RuntimeError('sqlite down')

    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', BrokenSQLiteClient)

    record = await gpt_handlers.get_history_record(1, 2)

    assert record is None


@pytest.mark.asyncio
async def test_handle_text_chat_chunks_long_streamed_reply_into_one_canonical_row_plus_aliases(
    tmp_path,
    monkeypatch,
):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 2.0, 2.0, 2.0]))

    long_reply = 'a' * 9000
    fake_llm = FakeLLM(chunks=[long_reply])
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    update = make_update(chat_id=55, message_id=11, text='hello there')

    await gpt_handlers.handle_text_chat(update, object())

    assert update.message.reply_text.await_count == 3
    reply_calls = update.message.reply_text.await_args_list
    assert reply_calls[0].args[0] == '...🤔'
    assert len(reply_calls[1].args[0]) == 4096
    assert len(reply_calls[2].args[0]) == 813
    assert update.message.sent_replies[0].edit_text.await_args_list[-1].args[0] == 'a' * 4096
    assert update.message.sent_replies[2].edit_text.await_args_list[-1].args[0] == 'a' * 808

    canonical_assistant_record = await gpt_handlers.get_history_record(55, 12)
    assistant_alias_1 = await gpt_handlers.get_history_record(55, 13)
    assistant_alias_2 = await gpt_handlers.get_history_record(55, 14)

    assert canonical_assistant_record is not None
    assert canonical_assistant_record.canonical_message_id == 12
    assert canonical_assistant_record.text == long_reply
    assert canonical_assistant_record.reply_message_id == 11

    assert assistant_alias_1 is not None
    assert assistant_alias_1.canonical_message_id == 12
    assert assistant_alias_1.text is None
    assert assistant_alias_1.reply_message_id == 11

    assert assistant_alias_2 is not None
    assert assistant_alias_2.canonical_message_id == 12
    assert assistant_alias_2.text is None
    assert assistant_alias_2.reply_message_id == 11


@pytest.mark.asyncio
async def test_handle_text_chat_reply_to_later_assistant_chunk_uses_canonical_assistant_turn(
    tmp_path,
    monkeypatch,
):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)

    first_reply = 'b' * 9000
    second_reply = 'follow-up reply'
    fake_llm = FakeLLM(chunks=[first_reply], extra_streams=[[second_reply]])
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 2.0, 2.0, 2.0, 10.0, 12.0, 12.0]))

    initial_update = make_update(chat_id=55, message_id=11, text='hello there')
    await gpt_handlers.handle_text_chat(initial_update, object())

    follow_up_update = make_update(
        chat_id=55,
        message_id=20,
        text='what did you mean?',
        reply_to_message=SimpleNamespace(chat_id=55, message_id=14),
    )
    await gpt_handlers.handle_text_chat(follow_up_update, object())

    second_call_messages = fake_llm.calls[1]
    assert [message.content for message in second_call_messages] == [
        gpt_handlers.SYSTEM_PROMPT,
        'hello there',
        first_reply,
        'what did you mean?',
    ]

    follow_up_record = await gpt_handlers.get_history_record(55, 20)
    assert follow_up_record is not None
    assert follow_up_record.reply_message_id == 12


@pytest.mark.asyncio
async def test_streaming_updates_placeholder_then_final_reply_with_full_rerender(monkeypatch):
    update = make_update(chat_id=99, message_id=7, text='hello')
    fake_llm = FakeLLM(chunks=['**Hello**', ' world'])
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 1.4, 1.4, 2.6, 2.6]))
    write_history_record = AsyncMock()
    monkeypatch.setattr(gpt_handlers, 'write_history_record', write_history_record)

    await gpt_handlers.generate_llm_reply(
        message=update.message,
        text='hello',
        chain=[],
        parent_chat_id=99,
        parent_message_id=7,
    )

    update.message.reply_text.assert_awaited_once_with(
        '...🤔',
        parse_mode='HTML',
        reply_to_message_id=7,
    )
    assistant_message = update.message.sent_replies[0]
    assert [call.args[0] for call in assistant_message.edit_text.await_args_list] == [
        '<b>Hello</b> ...🤔',
        '<b>Hello</b> world ...🤔',
        '<b>Hello</b> world',
    ]
    assert write_history_record.await_count == 1


@pytest.mark.asyncio
async def test_streaming_failure_replaces_active_chunk_with_error_and_skips_persistence(monkeypatch):
    update = make_update(chat_id=99, message_id=7, text='hello')
    fake_llm = FakeLLM(chunks=['partial'], error_after=1)
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 2.0, 2.0]))
    write_history_record = AsyncMock()
    monkeypatch.setattr(gpt_handlers, 'write_history_record', write_history_record)

    await gpt_handlers.generate_llm_reply(
        message=update.message,
        text='hello',
        chain=[],
        parent_chat_id=99,
        parent_message_id=7,
    )

    assistant_message = update.message.sent_replies[0]
    assert [call.args[0] for call in assistant_message.edit_text.await_args_list] == [
        'partial ...🤔',
        gpt_handlers.STREAM_ERROR_TEXT,
    ]
    write_history_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_stream_replaces_placeholder_with_error_and_skips_persistence(monkeypatch):
    update = make_update(chat_id=99, message_id=7, text='hello')
    fake_llm = FakeLLM(chunks=[])
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0]))
    write_history_record = AsyncMock()
    monkeypatch.setattr(gpt_handlers, 'write_history_record', write_history_record)

    await gpt_handlers.generate_llm_reply(
        message=update.message,
        text='hello',
        chain=[],
        parent_chat_id=99,
        parent_message_id=7,
    )

    assistant_message = update.message.sent_replies[0]
    assistant_message.edit_text.assert_awaited_once_with(gpt_handlers.STREAM_ERROR_TEXT, parse_mode='HTML')
    write_history_record.assert_not_awaited()


def test_build_visible_stream_chunks_handles_suffix_boundary(monkeypatch):
    monkeypatch.setattr(gpt_handlers, 'MAX_MESSAGE_LENGTH', 10)

    assert gpt_handlers.build_visible_stream_chunks('abcdef', is_final=False) == ['abcdef ...', '🤔']
    assert gpt_handlers.build_visible_stream_chunks('abcdef', is_final=True) == ['abcdef']


def test_history_record_requires_text_for_canonical_rows():
    with pytest.raises(ValidationError):
        gpt_handlers.HistoryRecord(
            chat_id=1,
            message_id=10,
            canonical_message_id=10,
            text=None,
            role=MessageRole.USER,
        )

    alias_record = gpt_handlers.HistoryRecord(
        chat_id=1,
        message_id=11,
        canonical_message_id=10,
        text=None,
        role=MessageRole.USER,
    )
    assert alias_record.text is None


def test_extract_usage_supports_object_and_dict_shapes():
    object_usage = SimpleNamespace(usage=SimpleNamespace(total_tokens=123))

    assert gpt_handlers.extract_usage(object_usage).total_tokens == 123
    assert gpt_handlers.extract_usage({'usage': {'total_tokens': 456}}) == {'total_tokens': 456}
    assert gpt_handlers.extract_usage(None) is None


class Clock:
    def __init__(self, values):
        self.values = list(values)
        self.last = values[-1] if values else 0.0

    def __call__(self):
        if self.values:
            self.last = self.values.pop(0)
        return self.last


class FakeReplyMessage:
    def __init__(self, *, chat_id: int, message_id: int, text: str):
        self.chat_id = chat_id
        self.message_id = message_id
        self.text = text
        self.edit_text = AsyncMock(side_effect=self._edit_text)
        self.delete = AsyncMock()

    async def _edit_text(self, text, **kwargs):
        self.text = text
        return self


class FakeLLM:
    def __init__(self, *, chunks, extra_streams=None, error_after=None):
        self.streams = [list(chunks), *(list(stream) for stream in (extra_streams or []))]
        self.error_after = error_after
        self.calls = []

    async def astream_chat(self, *, messages):
        self.calls.append(messages)
        stream = self.streams.pop(0)
        emitted = 0
        for chunk in stream:
            yield SimpleNamespace(delta=chunk)
            emitted += 1
            if self.error_after is not None and emitted >= self.error_after:
                raise RuntimeError('boom')
        yield SimpleNamespace(delta='', raw={'usage': {'total_tokens': 1}})


def make_update(chat_id: int, message_id: int, text: str, reply_to_message=None):
    next_reply_message_id = message_id + 1
    sent_replies = []

    async def reply_text(reply_text, **kwargs):
        nonlocal next_reply_message_id
        reply_message = FakeReplyMessage(
            chat_id=chat_id,
            message_id=next_reply_message_id,
            text=reply_text,
        )
        sent_replies.append(reply_message)
        next_reply_message_id += 1
        return reply_message

    message = SimpleNamespace(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_to_message=reply_to_message,
        reply_text=AsyncMock(side_effect=reply_text),
        sent_replies=sent_replies,
    )
    return SimpleNamespace(message=message)
