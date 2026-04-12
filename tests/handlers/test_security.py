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
    update = SimpleNamespace(
        message=SimpleNamespace(
            from_user=SimpleNamespace(id=722182029),
            reply_text=AsyncMock(),
        )
    )

    await wrapper(update, object())

    handler.assert_awaited_once()
    update.message.reply_text.assert_not_awaited()
