import logging
from functools import wraps
from typing import Union, Optional, Callable

from telegram import Update
from telegram.ext import CallbackContext, BaseHandler
from enum import StrEnum

from bot.clients import MongoClient


class Role(StrEnum):
    admin = 'admin'
    user = 'user'


def add_authorization(handler: BaseHandler, role: Optional[Role] = None) -> BaseHandler:
    """mutates handler to check user access"""
    original_callback = handler.callback
    handler.callback = authorize_func(original_callback, required_role=role)
    return handler


def authorize_func(func: Callable[[Update, CallbackContext], ...], required_role: Role = None):
    """decorator for checking user access"""
    @wraps(func)
    async def wrapper(update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        user_role = await find_role(user_id)
        if not user_role or (required_role and user_role != required_role):
            logging.warning(f'Unauthorized access by user_id: {user_id}.')
            await update.message.reply_text(
                f'У вас нет доступа к этому боту. Обратитесь к администратору (user id: {user_id}).')
            return
        return await func(update, context)
    return wrapper


async def find_role(user_id: int) -> Optional[Role]:
    db = MongoClient().get_db()
    users = db['users']
    user = await users.find_one({'id_': user_id})
    return Role(user['role']) if user else None
