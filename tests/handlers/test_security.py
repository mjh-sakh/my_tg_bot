from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import security


@pytest.mark.asyncio
async def test_find_role_returns_admin_for_env_admin(monkeypatch):
    monkeypatch.setattr(security, 'ADMIN_ID', 722182029)

    role = await security.find_role(722182029)

    assert role == security.Role.admin


@pytest.mark.asyncio
async def test_find_role_handles_mongo_errors(monkeypatch):
    monkeypatch.setattr(security, 'ADMIN_ID', 722182029)

    class BrokenUsers:
        async def find_one(self, query):
            raise RuntimeError('mongo down')

    class BrokenDb:
        def __getitem__(self, name):
            return BrokenUsers()

    class BrokenMongoClient:
        def get_db(self):
            return BrokenDb()

    monkeypatch.setattr(security, 'MongoClient', BrokenMongoClient)

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
