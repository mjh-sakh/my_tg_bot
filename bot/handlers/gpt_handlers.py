import logging
import os
from pathlib import Path
from typing import Optional
import re

from llama_index.core.base.llms.types import ChatMessage, MessageRole
from llama_index.llms.openai_like import OpenAILike
from llama_index.llms.openrouter import OpenRouter
from pydantic import BaseModel
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, CallbackContext, filters

from bot.clients import MongoClient

MAX_MESSAGE_LENGTH = 4096
DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'meta-llama/llama-3-70b-instruct')
SYSTEM_PROMPT = Path('bot', 'handlers', 'prompts', 'helpful_assistant_prompt.txt').read_text()


class HistoryRecord(BaseModel):
    id_: int
    text: str
    reply_id: Optional[int] = None
    role: MessageRole
    is_llm_chain: bool = False
    schema_version: int = 1


def llm(model: str = DEFAULT_MODEL, **kwargs) -> OpenAILike:
    params = dict(
        api_key=os.getenv('OPENROUTER_KEY'),
        max_tokens=256,
        context_window=4096,
        model=model
    ) | kwargs
    return OpenRouter(**params)


def remove_command_string(message: str) -> str:
    """Checks if the message has a command and returns the rest of the message"""
    return re.sub(r'^/\w+\s*', '', message)


def markdown_to_telegram_html(markdown_text):
    # Convert bold
    markdown_text = re.sub(r'\*\*(.*?)\*\*|\*(.*?)\*', r'<b>\1\2</b>', markdown_text)
    # Convert italic
    markdown_text = re.sub(r'__(.*?)__|_(.*?)_', r'<i>\1\2</i>', markdown_text)
    # Convert strikethrough
    markdown_text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', markdown_text)
    # Convert inline code
    markdown_text = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', markdown_text)
    # Convert code blocks
    markdown_text = re.sub(r'```([\s\S]+?)```', r'<pre>\1</pre>', markdown_text)
    # Convert links
    markdown_text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', markdown_text)
    return markdown_text


async def ask_gpt(update: Update, context: CallbackContext):
    llm_ = llm()
    messages = []
    system_prompt = ChatMessage.from_str(content=SYSTEM_PROMPT, role=MessageRole.SYSTEM)
    messages.append(system_prompt)
    if 'chain' in context.__dict__:
        messages.extend(ChatMessage.from_str(content=record.text, role=record.role) for record in context.chain)
    text_only = remove_command_string(update.message.text)
    last_message = ChatMessage.from_str(
        content=text_only,
        role=MessageRole.USER,
    )
    messages.append(last_message)
    response = await llm_.achat(messages=messages)
    logging.info(f"LLM use stats: {response.raw['usage']}")
    for i in range(0, len(response.message.content), MAX_MESSAGE_LENGTH):
        reply_text = response.message.content[i:i + MAX_MESSAGE_LENGTH]
        reply_text = markdown_to_telegram_html(reply_text)
        reply_message = await update.message.reply_text(reply_text, parse_mode='HTML')
        await write_history_record(
            id_=reply_message.message_id,
            text=response.message.content,
            reply_id=update.message.message_id,
            role=MessageRole.ASSISTANT,
            is_llm_chain=True,
        )


async def write_history_record(**kwargs) -> None:
    record = HistoryRecord(**kwargs)
    db = MongoClient().get_db()
    collection = db['history']
    await collection.insert_one(record.dict())


async def get_history_record(message_id: int) -> Optional[HistoryRecord]:
    db = MongoClient().get_db()
    collection = db['history']
    record = await collection.find_one({'id_': message_id})
    return HistoryRecord(**record) if record else None


async def record_history(update: Update, context: CallbackContext):
    message = update.message
    if reply_message := message.reply_to_message:
        reply_id = reply_message.message_id
        history_record = await get_history_record(reply_id)
        is_llm_chain = history_record.is_llm_chain if history_record else False
    else:
        reply_id = None
        is_llm_chain = False
    await write_history_record(
        id_=message.message_id,
        text=message.text,
        reply_id=reply_id,
        role=MessageRole.USER,
        is_llm_chain=is_llm_chain,
    )


async def direct_reply(update: Update, context: CallbackContext):
    reply_message = update.message.reply_to_message
    history_record = await get_history_record(reply_message.message_id)
    if history_record and history_record.is_llm_chain:
        chain = []
        while history_record:
            chain.append(history_record)
            history_record = await get_history_record(history_record.reply_id)
        chain.reverse()
        context.chain = chain
        logging.info(f'{len(chain)} messages were added into the context')
        await ask_gpt(update, context)


chat_handler = CommandHandler('chat', ask_gpt)
track_history_handler = MessageHandler(filters.TEXT, record_history, block=False)
reply_handler = MessageHandler(filters.REPLY & (~filters.COMMAND) & filters.TEXT, direct_reply)
