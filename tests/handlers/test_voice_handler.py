from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers.voice_handler import handle_voice


class DummyMessage:
    def __init__(self, *, voice=None, audio=None, message_id=123):
        self.voice = voice
        self.audio = audio
        self.message_id = message_id
        self.reply_text = AsyncMock()


@pytest.mark.asyncio
async def test_handle_voice_replies_with_transcript_chunks():
    file_handle = SimpleNamespace(download_to_memory=AsyncMock(side_effect=lambda buffer: buffer.write(b'audio')))
    bot = SimpleNamespace(get_file=AsyncMock(return_value=file_handle))
    context = SimpleNamespace(bot=bot)
    client = SimpleNamespace(transcribe=AsyncMock(return_value='x' * 5000))
    message = DummyMessage(voice=SimpleNamespace(file_id='file-1', duration=12))
    update = SimpleNamespace(message=message)

    await handle_voice(update, context, client)

    client.transcribe.assert_awaited_once()
    assert message.reply_text.await_count == 2
    first_call = message.reply_text.await_args_list[0]
    second_call = message.reply_text.await_args_list[1]
    assert len(first_call.args[0]) == 4096
    assert len(second_call.args[0]) == 904


@pytest.mark.asyncio
async def test_handle_voice_reports_transcription_errors():
    file_handle = SimpleNamespace(download_to_memory=AsyncMock(side_effect=lambda buffer: buffer.write(b'audio')))
    bot = SimpleNamespace(get_file=AsyncMock(return_value=file_handle))
    context = SimpleNamespace(bot=bot)
    client = SimpleNamespace(transcribe=AsyncMock(side_effect=RuntimeError('boom')))
    message = DummyMessage(voice=SimpleNamespace(file_id='file-1', duration=12))
    update = SimpleNamespace(message=message)

    await handle_voice(update, context, client)

    message.reply_text.assert_awaited_once()
    assert 'Ошибочка: boom' in message.reply_text.await_args.args[0]
