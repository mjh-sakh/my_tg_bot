from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.clients.sqlite_client import SQLiteClient
from bot.handlers import security


@pytest.mark.asyncio
async def test_find_role_returns_admin_for_env_admin(monkeypatch):
    monkeypatch.setattr(security, 'ADMIN_ID', 722182029)

    role = await security.find_role(722182029)

    assert role == security.Role.admin


@pytest.mark.asyncio
async def test_find_role_returns_sqlite_role_for_known_user(tmp_path, monkeypatch):
    monkeypatch.setattr(security, 'ADMIN_ID', 722182029)
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    with client._connect() as connection:
        connection.execute(
            'INSERT INTO users (user_id, role) VALUES (?, ?)',
            (123, 'user'),
        )
        connection.commit()

    monkeypatch.setattr(security, 'SQLiteClient', lambda: client)

    role = await security.find_role(123)

    assert role == security.Role.user


@pytest.mark.asyncio
async def test_find_role_handles_sqlite_errors(monkeypatch):
    monkeypatch.setattr(security, 'ADMIN_ID', 722182029)

    class BrokenSQLiteClient:
        def get_user_role(self, user_id):
            raise RuntimeError('sqlite down')

    monkeypatch.setattr(security, 'SQLiteClient', BrokenSQLiteClient)

    role = await security.find_role(123)

    assert role is None


@pytest.mark.asyncio
async def test_authorize_func_allows_env_admin(monkeypatch):
    monkeypatch.setattr(security, 'ADMIN_ID', 722182029)

    handler = AsyncMock()
    wrapper = security.authorize_func(handler)
    update = make_update(722182029)

    await wrapper(update, object())

    handler.assert_awaited_once()
    update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorize_func_allows_user_with_enabled_feature(tmp_path, monkeypatch):
    monkeypatch.setattr(security, 'ADMIN_ID', 722182029)
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    client.upsert_user(123, security.Role.user.value)
    client.enable_feature(123, security.Feature.voice.value)
    monkeypatch.setattr(security, 'SQLiteClient', lambda: client)

    handler = AsyncMock()
    wrapper = security.authorize_func(handler, required_feature=security.Feature.voice)
    update = make_update(123)

    await wrapper(update, object())

    handler.assert_awaited_once()
    update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorize_func_silently_rejects_user_without_enabled_feature(tmp_path, monkeypatch):
    monkeypatch.setattr(security, 'ADMIN_ID', 722182029)
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    client.upsert_user(123, security.Role.user.value)
    monkeypatch.setattr(security, 'SQLiteClient', lambda: client)

    handler = AsyncMock()
    wrapper = security.authorize_func(handler, required_feature=security.Feature.voice)
    update = make_update(123)

    await wrapper(update, object())

    handler.assert_not_awaited()
    update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorize_func_allows_admin_to_bypass_feature_check(monkeypatch):
    monkeypatch.setattr(security, 'ADMIN_ID', 722182029)

    handler = AsyncMock()
    wrapper = security.authorize_func(handler, required_feature=security.Feature.voice)
    update = make_update(722182029)

    await wrapper(update, object())

    handler.assert_awaited_once()
    update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_has_required_role_treats_admin_as_higher_than_user():
    assert security.has_required_role(security.Role.admin, security.Role.user) is True


@pytest.mark.asyncio
async def test_authorize_func_silently_rejects_unauthorized_user(monkeypatch):
    monkeypatch.setattr(security, 'ADMIN_ID', 722182029)

    handler = AsyncMock()
    wrapper = security.authorize_func(handler)
    update = make_update(123)

    await wrapper(update, object())

    handler.assert_not_awaited()
    update.message.reply_text.assert_not_awaited()


def make_update(user_id: int):
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=user_id))
