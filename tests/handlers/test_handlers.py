from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
