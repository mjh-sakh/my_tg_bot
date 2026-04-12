from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers.admin_handler import adduser
from bot.handlers.start_handler import start, whoami


@pytest.mark.asyncio
async def test_start_replies_with_liveness_message():
    update = type('Update', (), {'message': type('Message', (), {'reply_text': AsyncMock()})()})()
    context = object()

    await start(update, context)

    update.message.reply_text.assert_awaited_once_with("I'm alive, yeah! Do I know you?")


@pytest.mark.asyncio
async def test_whoami_replies_with_user_id():
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=123456))

    await whoami(update, object())

    message.reply_text.assert_awaited_once_with("Your Telegram user id is: 123456")


@pytest.mark.asyncio
async def test_adduser_authorizes_target_id(monkeypatch):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=['123456'])

    recorded = {}

    class FakeSQLiteClient:
        def upsert_user(self, user_id, role):
            recorded['user_id'] = user_id
            recorded['role'] = role

    monkeypatch.setattr('bot.handlers.admin_handler.SQLiteClient', FakeSQLiteClient)

    await adduser(update, context)

    assert recorded == {'user_id': 123456, 'role': 'user'}
    message.reply_text.assert_awaited_once_with('Authorized user 123456.')


@pytest.mark.asyncio
async def test_adduser_rejects_missing_argument():
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=[])

    await adduser(update, context)

    message.reply_text.assert_awaited_once_with('Usage: /adduser <telegram_user_id>')


@pytest.mark.asyncio
async def test_adduser_rejects_non_integer_id():
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=['abc'])

    await adduser(update, context)

    message.reply_text.assert_awaited_once_with('User id must be an integer.')
