import io
import os
from functools import partial

from telegram import Message, Update
from telegram.ext import CallbackContext, MessageHandler, filters

from bot.clients import BaseTranscribeClient
from bot.handlers.gpt_handlers import handle_chat_turn, write_history_record
from bot.handlers.security import Feature, Role, find_role, has_feature

MAX_MESSAGE_LENGTH = int(os.getenv('MAX_MESSAGE_LENGTH', 4096))


def is_forwarded_message(message: Message) -> bool:
    return bool(message.forward_origin or message.is_automatic_forward)


async def can_use_chat(update: Update) -> bool:
    user = update.effective_user or update.message.from_user
    if not user:
        return False
    role = await find_role(user.id)
    if role == Role.admin:
        return True
    return await has_feature(user.id, Feature.chat)


async def send_transcript_reply(message: Message, transcript: str) -> list[Message]:
    replies = []
    for i in range(0, len(transcript), MAX_MESSAGE_LENGTH):
        replies.append(
            await message.reply_text(
                transcript[i:i + MAX_MESSAGE_LENGTH],
                reply_to_message_id=message.message_id,
            )
        )
    return replies


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
        transcript_messages = await send_transcript_reply(update.message, transcript)

        if not transcript_messages:
            return
        if is_forwarded_message(update.message):
            return
        if not await can_use_chat(update):
            return

        await handle_chat_turn(
            message=update.message,
            text=transcript,
            canonical_message_id=update.message.message_id,
        )
        await write_history_record(
            chat_id=transcript_messages[0].chat_id,
            message_id=transcript_messages[0].message_id,
            canonical_message_id=update.message.message_id,
            text=transcript_messages[0].text,
            reply_chat_id=update.message.chat_id,
            reply_message_id=update.message.message_id,
            role='user',
            is_llm_chain=False,
        )

    except Exception as e:
        await update.message.reply_text(f'Ошибочка: {e}', reply_to_message_id=update.message.message_id)
        # sentry_sdk.capture_exception(e)


def create_voice_handler(client: BaseTranscribeClient):
    handle_voice_ = partial(handle_voice, client=client)
    return MessageHandler(filters.ChatType.PRIVATE & (filters.VOICE | filters.AUDIO), handle_voice_)
