from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers.admin_handler import adduser, disablefeature, enablefeature, features
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

    client = FakeSQLiteClient()
    monkeypatch.setattr('bot.handlers.admin_handler.SQLiteClient', lambda: client)

    await adduser(update, context)

    assert client.users == {123456: 'user'}
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


@pytest.mark.asyncio
async def test_enablefeature_enables_feature_for_authorized_user(monkeypatch):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=['123456', 'voice'])

    client = FakeSQLiteClient(users={123456: 'user'})
    monkeypatch.setattr('bot.handlers.admin_handler.SQLiteClient', lambda: client)

    await enablefeature(update, context)

    assert client.enabled_features == {123456: {'voice'}}
    message.reply_text.assert_awaited_once_with('Enabled feature voice for user 123456.')


@pytest.mark.asyncio
async def test_enablefeature_rejects_unknown_feature(monkeypatch):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=['123456', 'unknown'])

    monkeypatch.setattr('bot.handlers.admin_handler.SQLiteClient', FakeSQLiteClient)

    await enablefeature(update, context)

    message.reply_text.assert_awaited_once_with('Unknown feature. Supported features: voice, chat')


@pytest.mark.asyncio
async def test_disablefeature_removes_feature_for_authorized_user(monkeypatch):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=['123456', 'voice'])

    client = FakeSQLiteClient(users={123456: 'user'}, enabled_features={123456: {'voice', 'chat'}})
    monkeypatch.setattr('bot.handlers.admin_handler.SQLiteClient', lambda: client)

    await disablefeature(update, context)

    assert client.enabled_features == {123456: {'chat'}}
    message.reply_text.assert_awaited_once_with('Disabled feature voice for user 123456.')


@pytest.mark.asyncio
async def test_features_lists_enabled_features(monkeypatch):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=['123456'])

    client = FakeSQLiteClient(users={123456: 'user'}, enabled_features={123456: {'voice', 'chat'}})
    monkeypatch.setattr('bot.handlers.admin_handler.SQLiteClient', lambda: client)

    await features(update, context)

    message.reply_text.assert_awaited_once_with('Enabled features for user 123456: chat, voice.')


class FakeSQLiteClient:
    def __init__(self, users=None, enabled_features=None):
        self.users = users or {}
        self.enabled_features = enabled_features or {}

    def upsert_user(self, user_id, role):
        self.users[user_id] = role

    def get_user_role(self, user_id):
        return self.users.get(user_id)

    def enable_feature(self, user_id, feature):
        self.enabled_features.setdefault(user_id, set()).add(feature)

    def disable_feature(self, user_id, feature):
        self.enabled_features.setdefault(user_id, set()).discard(feature)

    def list_features(self, user_id):
        return sorted(self.enabled_features.get(user_id, set()))
