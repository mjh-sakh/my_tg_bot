from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers.locker_handler import locker


@pytest.mark.asyncio
async def test_locker_reports_current_normal_mode(monkeypatch, locker_sqlite_client):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=[])
    monkeypatch.setattr('bot.handlers.locker_handler.SQLiteClient', lambda: locker_sqlite_client)

    await locker(update, context)

    message.reply_text.assert_awaited_once_with('Locker mode: keep going.')


@pytest.mark.asyncio
async def test_locker_reports_current_restricted_mode(monkeypatch, locker_sqlite_client):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=[])
    locker_sqlite_client.set_locker_restricted(True)
    monkeypatch.setattr('bot.handlers.locker_handler.SQLiteClient', lambda: locker_sqlite_client)

    await locker(update, context)

    message.reply_text.assert_awaited_once_with('Locker mode: restricted.')


@pytest.mark.asyncio
async def test_locker_on_sets_restricted_mode(monkeypatch, locker_sqlite_client):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=['on'])
    monkeypatch.setattr('bot.handlers.locker_handler.SQLiteClient', lambda: locker_sqlite_client)

    await locker(update, context)

    assert locker_sqlite_client.get_locker_restricted() is True
    message.reply_text.assert_awaited_once_with('Locker mode: restricted.')


@pytest.mark.asyncio
async def test_locker_off_sets_normal_mode(monkeypatch, locker_sqlite_client):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=['off'])
    locker_sqlite_client.set_locker_restricted(True)
    monkeypatch.setattr('bot.handlers.locker_handler.SQLiteClient', lambda: locker_sqlite_client)

    await locker(update, context)

    assert locker_sqlite_client.get_locker_restricted() is False
    message.reply_text.assert_awaited_once_with('Locker mode: keep going.')


@pytest.mark.asyncio
async def test_locker_rejects_unknown_argument(monkeypatch, locker_sqlite_client):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=['maybe'])
    monkeypatch.setattr('bot.handlers.locker_handler.SQLiteClient', lambda: locker_sqlite_client)

    await locker(update, context)

    message.reply_text.assert_awaited_once_with('Usage: /locker [on|off]')


@pytest.mark.asyncio
async def test_locker_rejects_too_many_arguments(monkeypatch, locker_sqlite_client):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(args=['on', 'now'])
    monkeypatch.setattr('bot.handlers.locker_handler.SQLiteClient', lambda: locker_sqlite_client)

    await locker(update, context)

    message.reply_text.assert_awaited_once_with('Usage: /locker [on|off]')
