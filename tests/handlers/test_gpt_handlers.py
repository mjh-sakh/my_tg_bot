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

    fake_llm = FakeLLM('assistant reply')
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    update = make_update(chat_id=55, message_id=11, text='hello there')

    await gpt_handlers.handle_text_chat(update, object())

    sent_messages = fake_llm.achat.await_args.kwargs['messages']
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
        'assistant reply',
        parse_mode='HTML',
        reply_to_message_id=11,
    )


@pytest.mark.asyncio
async def test_handle_text_chat_rebuilds_reply_chain_from_stored_history(tmp_path, monkeypatch):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)

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

    fake_llm = FakeLLM('assistant reply')
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    update = make_update(
        chat_id=77,
        message_id=3,
        text='third user message',
        reply_to_message=SimpleNamespace(chat_id=77, message_id=2),
    )

    await gpt_handlers.handle_text_chat(update, object())

    sent_messages = fake_llm.achat.await_args.kwargs['messages']
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

    fake_llm = FakeLLM('assistant reply')
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    update = make_update(
        chat_id=77,
        message_id=12,
        text='reply to transcript alias',
        reply_to_message=SimpleNamespace(chat_id=77, message_id=11),
    )

    await gpt_handlers.handle_text_chat(update, object())

    sent_messages = fake_llm.achat.await_args.kwargs['messages']
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

    fake_llm = FakeLLM('assistant reply')
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    update = make_update(
        chat_id=88,
        message_id=5,
        text='fresh despite reply',
        reply_to_message=SimpleNamespace(chat_id=88, message_id=4),
    )

    await gpt_handlers.handle_text_chat(update, object())

    sent_messages = fake_llm.achat.await_args.kwargs['messages']
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


class FakeLLM:
    def __init__(self, *contents: str):
        self.contents = list(contents)
        self.calls = []
        self.achat = AsyncMock(side_effect=self._achat)

    async def _achat(self, *, messages):
        self.calls.append(messages)
        content = self.contents.pop(0)
        return SimpleNamespace(
            message=SimpleNamespace(content=content),
            raw={'usage': {'total_tokens': 1}},
        )


def make_update(chat_id: int, message_id: int, text: str, reply_to_message=None):
    next_reply_message_id = message_id + 1

    async def reply_text(reply_text, **kwargs):
        nonlocal next_reply_message_id
        reply_message = SimpleNamespace(
            chat_id=chat_id,
            message_id=next_reply_message_id,
            text=reply_text,
        )
        next_reply_message_id += 1
        return reply_message

    message = SimpleNamespace(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_to_message=reply_to_message,
        reply_text=AsyncMock(side_effect=reply_text),
    )
    return SimpleNamespace(message=message)


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


@pytest.mark.asyncio
async def test_handle_text_chat_chunks_long_assistant_reply_into_one_canonical_row_plus_aliases(
    tmp_path,
    monkeypatch,
):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)

    long_reply = 'a' * 9000
    fake_llm = FakeLLM(long_reply)
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    update = make_update(chat_id=55, message_id=11, text='hello there')

    await gpt_handlers.handle_text_chat(update, object())

    assert update.message.reply_text.await_count == 3
    assert [len(call.args[0]) for call in update.message.reply_text.await_args_list] == [4096, 4096, 808]

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
    fake_llm = FakeLLM(first_reply, second_reply)
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

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


def test_extract_usage_supports_object_and_dict_shapes():
    object_usage = SimpleNamespace(usage=SimpleNamespace(total_tokens=123))

    assert gpt_handlers.extract_usage(object_usage).total_tokens == 123
    assert gpt_handlers.extract_usage({'usage': {'total_tokens': 456}}) == {'total_tokens': 456}
    assert gpt_handlers.extract_usage(None) is None
