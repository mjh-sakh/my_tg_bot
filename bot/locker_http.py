import logging
import os
from typing import Any

from aiohttp import web
from bot.clients import SQLiteClient

LOGGER = logging.getLogger(__name__)

TELEGRAM_BOT_KEY = web.AppKey('telegram_bot', object)
SQLITE_CLIENT_KEY = web.AppKey('sqlite_client', SQLiteClient)
ADMIN_ID_KEY = web.AppKey('admin_id', int)

AUTH_RESTRICTED = 'restricted'
AUTH_KEEP_GOING = 'keep going'
DEFAULT_CLIENT_MAX_SIZE = 256 * 1024
TELEGRAM_MESSAGE_LIMIT = 4096
LOG_MESSAGE_BUDGET = 3800
TRUNCATED_SUFFIX = '\n\n[truncated]'


def create_locker_http_app(
    telegram_bot: Any,
    *,
    sqlite_client: SQLiteClient | None = None,
    admin_id: int | None = None,
    client_max_size: int = DEFAULT_CLIENT_MAX_SIZE,
) -> web.Application:
    app = web.Application(client_max_size=client_max_size)
    app[TELEGRAM_BOT_KEY] = telegram_bot
    app[SQLITE_CLIENT_KEY] = sqlite_client or SQLiteClient()
    app[ADMIN_ID_KEY] = admin_id if admin_id is not None else parse_admin_id(os.getenv('ADMIN_ID'))
    app.router.add_get('/locker/auth', locker_auth)
    app.router.add_post('/locker/logs', locker_logs)
    return app


async def locker_auth(request: web.Request) -> web.Response:
    restricted = request.app[SQLITE_CLIENT_KEY].get_locker_restricted()
    mode = AUTH_RESTRICTED if restricted else AUTH_KEEP_GOING

    try:
        await send_admin_message(request.app, f'Windows locker auth check: {mode}.')
    except Exception:
        LOGGER.warning('Failed to send Windows locker auth notification.', exc_info=True)

    return web.Response(text=mode, content_type='text/plain')


async def locker_logs(request: web.Request) -> web.Response:
    if not request.app[ADMIN_ID_KEY]:
        LOGGER.warning('Cannot forward Windows locker logs because ADMIN_ID is not configured.')
        return web.Response(status=503, text='admin chat is not configured')

    body = await request.read()
    logs = body.decode('utf-8', errors='replace')
    message = format_log_message(logs)

    try:
        await send_admin_message(request.app, message)
    except Exception:
        LOGGER.warning('Failed to forward Windows locker logs to Telegram.', exc_info=True)
        return web.Response(status=502, text='telegram forwarding failed')

    return web.Response(text='ok')


async def send_admin_message(app: web.Application, text: str) -> None:
    admin_id = app[ADMIN_ID_KEY]
    if not admin_id:
        raise RuntimeError('ADMIN_ID is not configured')
    await app[TELEGRAM_BOT_KEY].send_message(chat_id=admin_id, text=text)


def format_log_message(logs: str) -> str:
    content = logs if logs else '(empty body)'
    prefix = 'Windows locker log upload:\n\n'
    budget = min(LOG_MESSAGE_BUDGET, TELEGRAM_MESSAGE_LIMIT - len(prefix) - len(TRUNCATED_SUFFIX))
    if len(content) > budget:
        content = content[:budget].rstrip() + TRUNCATED_SUFFIX
    return prefix + content


def parse_admin_id(value: str | None) -> int:
    try:
        return int(value or '0')
    except ValueError:
        LOGGER.warning('Invalid ADMIN_ID value: %r', value)
        return 0
