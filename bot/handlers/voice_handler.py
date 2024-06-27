import io
import os
from functools import partial

from telegram import Update
from telegram.ext import CallbackContext, MessageHandler, filters
from bot.clients import BaseTranscribeClient

MAX_MESSAGE_LENGTH = os.getenv('MAX_MESSAGE_LENGTH', 4096)


async def handle_voice(update: Update, context: CallbackContext, client: BaseTranscribeClient) -> None:
    try:
        if update.message.voice:
            file_handle = await context.bot.get_file(update.message.voice.file_id)
        elif update.message.audio:
            file_handle = await context.bot.get_file(update.message.audio.file_id)
        else:
            raise ValueError('Can handle only voice and audio messages.')
        file_data = io.BytesIO()
        await file_handle.download_to_memory(file_data)
        duration = update.message.voice.duration if update.message.voice else update.message.audio.duration
        transcript = await client.transcribe(audio_data=file_data, duration=duration)
        for i in range(0, len(transcript), MAX_MESSAGE_LENGTH):
            await update.message.reply_text(transcript[i:i + MAX_MESSAGE_LENGTH],
                                            reply_to_message_id=update.message.message_id)

    except Exception as e:
        await update.message.reply_text(f'Ошибочка: {e}', reply_to_message_id=update.message.message_id)
        # sentry_sdk.capture_exception(e)


def create_voice_handler(client: BaseTranscribeClient):
    handle_voice_ = partial(handle_voice, client=client)
    return MessageHandler(filters.ChatType.PRIVATE & (filters.VOICE | filters.AUDIO), handle_voice_)
