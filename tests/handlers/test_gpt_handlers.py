from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from llama_index.core.base.llms.types import MessageRole

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
    assert user_record.is_llm_chain is True
    assert assistant_record is not None
    assert assistant_record.text == 'assistant reply'
    update.message.reply_text.assert_awaited_once_with('assistant reply', parse_mode='HTML')


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
        is_llm_chain=True,
    )
    await gpt_handlers.write_history_record(
        chat_id=77,
        message_id=2,
        text='second user message',
        reply_chat_id=77,
        reply_message_id=1,
        role=MessageRole.USER,
        is_llm_chain=True,
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


@pytest.mark.asyncio
async def test_get_history_record_returns_none_on_sqlite_error(monkeypatch):
    class BrokenSQLiteClient:
        def get_history_record(self, chat_id, message_id):
            raise RuntimeError('sqlite down')

    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', BrokenSQLiteClient)

    record = await gpt_handlers.get_history_record(1, 2)

    assert record is None


class FakeLLM:
    def __init__(self, content: str):
        self.achat = AsyncMock(
            return_value=SimpleNamespace(
                message=SimpleNamespace(content=content),
                raw={'usage': {'total_tokens': 1}},
            )
        )


def make_update(chat_id: int, message_id: int, text: str, reply_to_message=None):
    reply_message = SimpleNamespace(chat_id=chat_id, message_id=message_id + 1)
    message = SimpleNamespace(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_to_message=reply_to_message,
        reply_text=AsyncMock(return_value=reply_message),
    )
    return SimpleNamespace(message=message)
