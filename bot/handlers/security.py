import logging
import os
from enum import StrEnum
from functools import wraps
from typing import Callable, Optional

from telegram import Update
from telegram.ext import BaseHandler, CallbackContext

from bot.clients import SQLiteClient


class Role(StrEnum):
    admin = 'admin'
    user = 'user'


class Feature(StrEnum):
    voice = 'voice'
    chat = 'chat'

    @classmethod
    def parse(cls, value: str) -> 'Feature':
        normalized = value.strip().lower().replace('-', '_')
        return cls(normalized)


ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))


def add_authorization(
    handler: BaseHandler,
    role: Optional[Role] = None,
    feature: Optional[Feature | str] = None,
) -> BaseHandler:
    """mutates handler to check user access"""
    original_callback = handler.callback
    handler.callback = authorize_func(
        original_callback,
        required_role=role,
        required_feature=feature,
    )
    return handler


def authorize_func(
    func: Callable[[Update, CallbackContext], ...],
    required_role: Optional[Role] = None,
    required_feature: Optional[Feature | str] = None,
):
    """decorator for checking user access"""

    @wraps(func)
    async def wrapper(update: Update, context: CallbackContext):
        user = update.effective_user or update.message.from_user
        user_id = user.id
        user_role = await find_role(user_id)
        if not user_role or not has_required_role(user_role, required_role):
            logging.warning(f'Unauthorized access by user_id: {user_id}.')
            return

        if required_feature and user_role != Role.admin:
            feature_name = normalize_feature_name(required_feature)
            if not await has_feature(user_id, feature_name):
                logging.warning(f'Feature {feature_name} is disabled for user_id: {user_id}.')
                return
        return await func(update, context)

    return wrapper


async def find_role(user_id: int) -> Optional[Role]:
    if ADMIN_ID and user_id == ADMIN_ID:
        return Role.admin
    try:
        role = SQLiteClient().get_user_role(user_id)
    except Exception as e:
        logging.warning(f'Failed to resolve role from SQLite for user_id={user_id}: {e}')
        return None
    return Role(role) if role else None


async def has_feature(user_id: int, feature: Feature | str) -> bool:
    feature_name = normalize_feature_name(feature)
    try:
        return SQLiteClient().has_feature(user_id, feature_name)
    except Exception as e:
        logging.warning(
            f'Failed to resolve feature {feature_name} from SQLite for user_id={user_id}: {e}'
        )
        return False


def has_required_role(user_role: Role, required_role: Optional[Role]) -> bool:
    if required_role is None:
        return True
    if user_role == Role.admin:
        return True
    return user_role == required_role


def normalize_feature_name(feature: Feature | str) -> str:
    return feature.value if isinstance(feature, Feature) else str(feature)
