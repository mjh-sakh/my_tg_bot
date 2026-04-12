import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.clients.sqlite_client import SQLiteClient
from bot.handlers.security import Feature, Role
from bot.handlers import gpt_handlers, security


pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(
    os.getenv('RUN_OPENROUTER_E2E') != '1',
    reason='Set RUN_OPENROUTER_E2E=1 to run the real OpenRouter chat e2e test.',
)
async def test_authorized_chat_message_gets_real_openrouter_reply(tmp_path, monkeypatch):
    openrouter_key = os.getenv('OPENROUTER_KEY')
    if not openrouter_key:
        pytest.skip('OPENROUTER_KEY is not configured.')

    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    client.upsert_user(123456, Role.user.value)
    client.enable_feature(123456, Feature.chat.value)

    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(security, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(security, 'ADMIN_ID', 0)

    bot_reply = SimpleNamespace(chat_id=999, message_id=200)
    message = SimpleNamespace(
        chat_id=999,
        message_id=100,
        text='Reply in exactly two words: ping check',
        reply_to_message=None,
        reply_text=AsyncMock(return_value=bot_reply),
        from_user=SimpleNamespace(id=123456),
    )
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=123456),
    )

    wrapped = security.authorize_func(
        gpt_handlers.handle_text_chat,
        required_feature=Feature.chat,
    )

    await wrapped(update, object())

    message.reply_text.assert_awaited_once()
    reply_args = message.reply_text.await_args
    assert reply_args.kwargs['parse_mode'] == 'HTML'
    assert reply_args.args[0].strip()

    user_record = client.get_history_record(999, 100)
    assistant_record = client.get_history_record(999, 200)
    assert user_record is not None
    assert assistant_record is not None
    assert assistant_record['text'].strip()
