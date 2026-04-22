import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from llama_index.core.base.llms.types import ChatMessage, MessageRole
from llama_index.llms.openai_like import OpenAILike
from llama_index.llms.openrouter import OpenRouter
from pydantic import BaseModel, model_validator
from telegram import Message, Update
from telegram.ext import CallbackContext, MessageHandler, filters

from bot.clients import SQLiteClient

MAX_MESSAGE_LENGTH = 4096
DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'meta-llama/llama-3-70b-instruct')
SYSTEM_PROMPT = Path('bot', 'handlers', 'prompts', 'helpful_assistant_prompt.txt').read_text()


class HistoryRecord(BaseModel):
    chat_id: int
    message_id: int
    canonical_message_id: Optional[int] = None
    text: Optional[str] = None
    reply_chat_id: Optional[int] = None
    reply_message_id: Optional[int] = None
    role: MessageRole
    schema_version: int = 1

    @model_validator(mode='after')
    def validate_text_for_canonical_rows(self):
        if self.canonical_message_id in (None, self.message_id) and self.text is None:
            raise ValueError('Canonical history rows must have text')
        return self


def llm(model: str = DEFAULT_MODEL, **kwargs) -> OpenAILike:
    params = dict(
        api_key=os.getenv('OPENROUTER_KEY'),
        max_tokens=256,
        context_window=4096,
        model=model,
    ) | kwargs
    return OpenRouter(**params)


def markdown_to_telegram_html(markdown_text: str) -> str:
    markdown_text = re.sub(r'\*\*(.*?)\*\*|\*(.*?)\*', r'<b>\1\2</b>', markdown_text)
    markdown_text = re.sub(r'__(.*?)__|_(.*?)_', r'<i>\1\2</i>', markdown_text)
    markdown_text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', markdown_text)
    markdown_text = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', markdown_text)

    def code_block_replace(match):
        code = match.group(2).strip()
        lang = match.group(1).strip() if match.group(1) else ''
        if lang:
            return f'<pre><code class="language-{lang}">{code}</code></pre>'
        return f'<pre><code>{code}</code></pre>'

    markdown_text = re.sub(r'```(\w*)\n?([\s\S]+?)```', code_block_replace, markdown_text)
    markdown_text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', markdown_text)
    return markdown_text


async def write_history_record(**kwargs) -> None:
    record = HistoryRecord(**kwargs)
    try:
        SQLiteClient().insert_history_record(**record.model_dump())
    except Exception as e:
        logging.warning(
            'Failed to write history record to SQLite for '
            f'chat_id={record.chat_id}, message_id={record.message_id}: {e}'
        )


async def get_history_record(chat_id: int, message_id: int) -> Optional[HistoryRecord]:
    try:
        record = SQLiteClient().get_history_record(chat_id, message_id)
    except Exception as e:
        logging.warning(
            'Failed to read history record from SQLite for '
            f'chat_id={chat_id}, message_id={message_id}: {e}'
        )
        return None
    return HistoryRecord(**record) if record else None


async def get_canonical_history_record(chat_id: int, message_id: int) -> Optional[HistoryRecord]:
    try:
        record = SQLiteClient().get_canonical_history_record(chat_id, message_id)
    except Exception as e:
        logging.warning(
            'Failed to resolve canonical history record from SQLite for '
            f'chat_id={chat_id}, message_id={message_id}: {e}'
        )
        return None
    return HistoryRecord(**record) if record else None


async def build_chain_from_record(history_record: HistoryRecord) -> list[HistoryRecord]:
    if history_record.canonical_message_id not in (None, history_record.message_id):
        resolved = await get_canonical_history_record(history_record.chat_id, history_record.message_id)
        if resolved is None:
            return []
        history_record = resolved

    chain = []
    current = history_record
    while current:
        chain.append(current)
        if current.reply_chat_id is None or current.reply_message_id is None:
            break
        current = await get_history_record(current.reply_chat_id, current.reply_message_id)
    chain.reverse()
    return chain


def build_llm_messages(text: str, chain: list[HistoryRecord]) -> list[ChatMessage]:
    messages = [ChatMessage.from_str(content=SYSTEM_PROMPT, role=MessageRole.SYSTEM)]
    messages.extend(ChatMessage.from_str(content=record.text or '', role=record.role) for record in chain)
    messages.append(ChatMessage.from_str(content=text, role=MessageRole.USER))
    return messages


async def resolve_reply_chain(message: Message) -> tuple[list[HistoryRecord], Optional[HistoryRecord]]:
    reply_message = message.reply_to_message
    if not reply_message:
        return [], None

    history_record = await get_canonical_history_record(reply_message.chat_id, reply_message.message_id)
    if not history_record:
        return [], None

    chain = await build_chain_from_record(history_record)
    logging.info(f'{len(chain)} messages were added into the context')
    return chain, history_record


async def generate_llm_reply(
    *,
    message: Message,
    text: str,
    chain: list[HistoryRecord],
    parent_chat_id: int,
    parent_message_id: int,
) -> None:
    llm_ = llm()
    messages = build_llm_messages(text, chain)
    response = await llm_.achat(messages=messages)
    usage = extract_usage(response.raw)
    if usage is not None:
        logging.info(f'LLM use stats: {usage}')

    for i in range(0, len(response.message.content), MAX_MESSAGE_LENGTH):
        reply_text = markdown_to_telegram_html(response.message.content[i:i + MAX_MESSAGE_LENGTH])
        reply_message = await message.reply_text(
            reply_text,
            parse_mode='HTML',
            reply_to_message_id=message.message_id,
        )
        await write_history_record(
            chat_id=reply_message.chat_id,
            message_id=reply_message.message_id,
            canonical_message_id=reply_message.message_id,
            text=response.message.content,
            reply_chat_id=parent_chat_id,
            reply_message_id=parent_message_id,
            role=MessageRole.ASSISTANT,
        )


async def handle_chat_turn(
    *,
    message: Message,
    text: str,
    canonical_message_id: Optional[int] = None,
) -> None:
    chain, parent_record = await resolve_reply_chain(message)
    parent_chat_id = parent_record.chat_id if parent_record else None
    parent_message_id = parent_record.message_id if parent_record else None
    canonical_message_id = canonical_message_id or message.message_id

    await write_history_record(
        chat_id=message.chat_id,
        message_id=canonical_message_id,
        canonical_message_id=canonical_message_id,
        text=text,
        reply_chat_id=parent_chat_id,
        reply_message_id=parent_message_id,
        role=MessageRole.USER,
    )
    await generate_llm_reply(
        message=message,
        text=text,
        chain=chain,
        parent_chat_id=message.chat_id,
        parent_message_id=canonical_message_id,
    )


async def handle_text_chat(update: Update, context: CallbackContext) -> None:
    del context
    await handle_chat_turn(message=update.message, text=update.message.text)


def extract_usage(raw: Any) -> object | None:
    if raw is None:
        return None
    if hasattr(raw, 'usage'):
        return raw.usage
    if isinstance(raw, dict):
        return raw.get('usage')
    return None


text_chat_handler = MessageHandler(
    filters.ChatType.PRIVATE & filters.TEXT & (~filters.COMMAND),
    handle_text_chat,
)
