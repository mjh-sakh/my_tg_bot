import logging
import os
import re
from pathlib import Path
from typing import Optional

from llama_index.core.base.llms.types import ChatMessage, MessageRole
from llama_index.llms.openai_like import OpenAILike
from llama_index.llms.openrouter import OpenRouter
from pydantic import BaseModel
from telegram import Update
from telegram.ext import CallbackContext, MessageHandler, filters

from bot.clients import SQLiteClient

MAX_MESSAGE_LENGTH = 4096
DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'meta-llama/llama-3-70b-instruct')
SYSTEM_PROMPT = Path('bot', 'handlers', 'prompts', 'helpful_assistant_prompt.txt').read_text()


class HistoryRecord(BaseModel):
    chat_id: int
    message_id: int
    text: str
    reply_chat_id: Optional[int] = None
    reply_message_id: Optional[int] = None
    role: MessageRole
    is_llm_chain: bool = False
    schema_version: int = 1


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


async def build_chain_from_record(history_record: HistoryRecord) -> list[HistoryRecord]:
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
    messages.extend(ChatMessage.from_str(content=record.text, role=record.role) for record in chain)
    messages.append(ChatMessage.from_str(content=text, role=MessageRole.USER))
    return messages


async def generate_llm_reply(update: Update, chain: list[HistoryRecord]) -> None:
    llm_ = llm()
    messages = build_llm_messages(update.message.text, chain)
    response = await llm_.achat(messages=messages)
    logging.info(f"LLM use stats: {response.raw['usage']}")

    for i in range(0, len(response.message.content), MAX_MESSAGE_LENGTH):
        reply_text = markdown_to_telegram_html(response.message.content[i:i + MAX_MESSAGE_LENGTH])
        reply_message = await update.message.reply_text(reply_text, parse_mode='HTML')
        await write_history_record(
            chat_id=reply_message.chat_id,
            message_id=reply_message.message_id,
            text=response.message.content,
            reply_chat_id=update.message.chat_id,
            reply_message_id=update.message.message_id,
            role=MessageRole.ASSISTANT,
            is_llm_chain=True,
        )


async def handle_text_chat(update: Update, context: CallbackContext) -> None:
    del context
    message = update.message
    reply_message = message.reply_to_message
    chain = []

    if reply_message:
        history_record = await get_history_record(reply_message.chat_id, reply_message.message_id)
        if history_record:
            chain = await build_chain_from_record(history_record)
            logging.info(f'{len(chain)} messages were added into the context')

    await write_history_record(
        chat_id=message.chat_id,
        message_id=message.message_id,
        text=message.text,
        reply_chat_id=reply_message.chat_id if reply_message else None,
        reply_message_id=reply_message.message_id if reply_message else None,
        role=MessageRole.USER,
        is_llm_chain=True,
    )
    await generate_llm_reply(update, chain)


text_chat_handler = MessageHandler(
    filters.ChatType.PRIVATE & filters.TEXT & (~filters.COMMAND),
    handle_text_chat,
)
