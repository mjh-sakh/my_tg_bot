import json
import logging
import os
from datetime import datetime, timezone
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
    entries, invalid_lines = parse_log_entries(logs)
    if entries:
        message = format_human_log_message(entries, invalid_lines)
    elif logs:
        message = '🪟 Windows locker report\n\n⚠️ Could not parse the uploaded log.\n\nRaw log:\n' + logs
    else:
        message = '🪟 Windows locker report\n\nNo log entries received.'

    if len(message) > LOG_MESSAGE_BUDGET:
        message = message[: LOG_MESSAGE_BUDGET - len(TRUNCATED_SUFFIX)].rstrip() + TRUNCATED_SUFFIX
    return message


def parse_log_entries(logs: str) -> tuple[list[dict[str, Any]], int]:
    entries: list[dict[str, Any]] = []
    invalid_lines = 0
    for line in logs.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get('event'), str):
            entries.append(parsed)
        else:
            invalid_lines += 1
    return entries, invalid_lines


def format_human_log_message(entries: list[dict[str, Any]], invalid_lines: int) -> str:
    lines = ['🪟 Windows locker report', '']
    lines.extend(format_log_summary(entries, invalid_lines))
    lines.append('')
    lines.append('Timeline:')
    lines.extend(f'• {format_entry_time(entry)} — {format_entry(entry)}' for entry in entries)
    return '\n'.join(lines)


def format_log_summary(entries: list[dict[str, Any]], invalid_lines: int) -> list[str]:
    decision = last_event(entries, 'decision')
    lines: list[str] = []

    if decision:
        fields = entry_fields(decision)
        decision_value = str(fields.get('decision', 'unknown'))
        lines.append(f'Status: {format_decision(decision_value)}')
        attempts = fields.get('attempts')
        if attempts is not None:
            lines.append(f'Auth attempts: {attempts}')
        if fields.get('reason'):
            lines.append(f'Reason: {humanize_token(str(fields["reason"]))}')
    elif last_event(entries, 'log_upload_error'):
        lines.append('Status: ⚠️ Previous log upload failed')
    elif last_event(entries, 'service_canceled'):
        lines.append('Status: ⏹️ Service canceled')
    else:
        lines.append('Status: ℹ️ Service activity')

    if last_event(entries, 'shutdown_invoked'):
        lines.append('Shutdown: invoked')
    shutdown_error = last_event(entries, 'shutdown_error')
    if shutdown_error:
        error = entry_fields(shutdown_error).get('error', 'unknown error')
        lines.append(f'Shutdown: failed — {error}')

    lines.append(f'Entries: {len(entries)}')
    if invalid_lines:
        lines.append(f'Ignored unparsable lines: {invalid_lines}')
    return lines


def format_entry(entry: dict[str, Any]) -> str:
    event = str(entry.get('event', 'unknown'))
    fields = entry_fields(entry)

    if event == 'service_boot':
        return append_details('Service booted', fields, preferred=('log_path',))
    if event == 'service_canceled':
        return append_details('Service canceled', fields, preferred=('phase', 'error'))
    if event == 'auth_config_error':
        return append_details('Auth configuration error', fields, preferred=('error',))
    if event == 'auth_attempt':
        attempt = fields.get('attempt')
        max_attempts = fields.get('max_attempts')
        return f'Auth check attempt {attempt}/{max_attempts}' if attempt and max_attempts else 'Auth check attempt'
    if event == 'auth_attempt_failed':
        return append_details('Auth check failed', fields, preferred=('attempt', 'max_attempts', 'reason', 'status', 'error'))
    if event == 'auth_fail_open':
        return append_details('Fail-open after auth checks', fields, preferred=('attempts', 'reason', 'last_status', 'last_error'))
    if event == 'auth_canceled':
        return append_details('Auth check canceled', fields, preferred=('attempt', 'error'))
    if event == 'decision':
        decision = str(fields.get('decision', 'unknown'))
        base = f'Decision: {format_decision(decision)}'
        return append_details(base, fields, preferred=('attempts', 'status', 'payload', 'reason', 'error'), skip=('decision',))
    if event == 'session_disconnect_error':
        return append_details('Could not disconnect active session', fields, preferred=('error',))
    if event == 'log_upload_attempt':
        return 'Uploading logs to Telegram bot'
    if event == 'log_upload_error':
        return append_details('Log upload failed', fields, preferred=('status', 'bytes', 'error', 'skipped'))
    if event == 'log_upload_skipped':
        return append_details('Log upload skipped', fields, preferred=('reason',))
    if event == 'shutdown_invoked':
        return 'Shutdown command invoked'
    if event == 'shutdown_error':
        return append_details('Shutdown failed', fields, preferred=('error',))

    return append_details(humanize_token(event), fields)


def append_details(
    base: str,
    fields: dict[str, Any],
    *,
    preferred: tuple[str, ...] = (),
    skip: tuple[str, ...] = (),
) -> str:
    details = format_fields(fields, preferred=preferred, skip=skip)
    return f'{base} ({details})' if details else base


def format_fields(
    fields: dict[str, Any],
    *,
    preferred: tuple[str, ...] = (),
    skip: tuple[str, ...] = (),
) -> str:
    ordered_keys = [key for key in preferred if key in fields and key not in skip]
    ordered_keys.extend(key for key in fields if key not in ordered_keys and key not in skip)
    return ', '.join(f'{humanize_token(key)}: {format_value(fields[key])}' for key in ordered_keys)


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return 'none'
    return humanize_token(str(value))


def format_decision(decision: str) -> str:
    return {
        'allowed': '✅ keep going',
        'restricted': '🔒 restricted',
        'fail_open': '⚠️ fail-open / keep going',
        'canceled': '⏹️ canceled',
    }.get(decision, humanize_token(decision))


def entry_fields(entry: dict[str, Any]) -> dict[str, Any]:
    fields = entry.get('fields')
    return fields if isinstance(fields, dict) else {}


def last_event(entries: list[dict[str, Any]], event: str) -> dict[str, Any] | None:
    return next((entry for entry in reversed(entries) if entry.get('event') == event), None)


def format_entry_time(entry: dict[str, Any]) -> str:
    raw_time = entry.get('time')
    if not isinstance(raw_time, str):
        return 'unknown time'
    parsed = parse_go_time(raw_time)
    if parsed is None:
        return raw_time
    return parsed.astimezone(timezone.utc).strftime('%H:%M:%S UTC')


def parse_go_time(value: str) -> datetime | None:
    normalized = value.strip()
    if normalized.endswith('Z'):
        normalized = normalized[:-1] + '+00:00'
    if '.' in normalized:
        prefix, suffix = normalized.split('.', 1)
        fraction = suffix
        timezone_part = ''
        for marker in ('+', '-'):
            if marker in suffix:
                fraction, timezone_part = suffix.split(marker, 1)
                timezone_part = marker + timezone_part
                break
        normalized = f'{prefix}.{fraction[:6]}{timezone_part}'
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def humanize_token(value: str) -> str:
    return value.replace('_', ' ')


def parse_admin_id(value: str | None) -> int:
    try:
        return int(value or '0')
    except ValueError:
        LOGGER.warning('Invalid ADMIN_ID value: %r', value)
        return 0
