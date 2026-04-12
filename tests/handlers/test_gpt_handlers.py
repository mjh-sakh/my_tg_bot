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
async def test_record_history_carries_llm_chain_flag_from_replied_message(tmp_path, monkeypatch):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)

    await gpt_handlers.write_history_record(
        chat_id=55,
        message_id=10,
        text='assistant answer',
        role=MessageRole.ASSISTANT,
        is_llm_chain=True,
    )

    update = SimpleNamespace(
        message=SimpleNamespace(
            chat_id=55,
            message_id=11,
            text='follow-up',
            reply_to_message=SimpleNamespace(chat_id=55, message_id=10),
        )
    )

    await gpt_handlers.record_history(update, object())

    record = await gpt_handlers.get_history_record(55, 11)

    assert record is not None
    assert record.reply_chat_id == 55
    assert record.reply_message_id == 10
    assert record.is_llm_chain is True


@pytest.mark.asyncio
async def test_direct_reply_builds_chain_from_reply_links(tmp_path, monkeypatch):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)

    await gpt_handlers.write_history_record(
        chat_id=77,
        message_id=1,
        text='user asks',
        role=MessageRole.USER,
        is_llm_chain=False,
    )
    await gpt_handlers.write_history_record(
        chat_id=77,
        message_id=2,
        text='assistant answers',
        reply_chat_id=77,
        reply_message_id=1,
        role=MessageRole.ASSISTANT,
        is_llm_chain=True,
    )

    ask_gpt = AsyncMock()
    monkeypatch.setattr(gpt_handlers, 'ask_gpt', ask_gpt)

    context = SimpleNamespace()
    update = SimpleNamespace(
        message=SimpleNamespace(
            reply_to_message=SimpleNamespace(chat_id=77, message_id=2),
        )
    )

    await gpt_handlers.direct_reply(update, context)

    ask_gpt.assert_awaited_once_with(update, context)
    assert [record.text for record in context.chain] == ['user asks', 'assistant answers']


@pytest.mark.asyncio
async def test_get_history_record_returns_none_on_sqlite_error(monkeypatch):
    class BrokenSQLiteClient:
        def get_history_record(self, chat_id, message_id):
            raise RuntimeError('sqlite down')

    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', BrokenSQLiteClient)

    record = await gpt_handlers.get_history_record(1, 2)

    assert record is None
