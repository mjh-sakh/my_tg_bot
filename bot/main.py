import asyncio
import logging
import os
import signal

from aiohttp import web
from telegram.ext import Application

logging.basicConfig(level=logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)
LOGGER = logging.getLogger(__name__)

from bot.clients import AdaptiveTranscribeClient, SQLiteClient
from bot.handlers import (
    Feature,
    Role,
    add_authorization,
    adduser_handler,
    create_voice_handler,
    disablefeature_handler,
    enablefeature_handler,
    features_handler,
    locker_command_handler,
    start_handler,
    text_chat_handler,
    whoami_handler,
)
from bot.locker_http import create_locker_http_app


TELEGRAM_API_TIMEOUT_SECONDS = 30


def build_application() -> Application:
    application = (
        Application.builder()
        .token(os.getenv('TELEGRAM_TOKEN'))
        .connect_timeout(TELEGRAM_API_TIMEOUT_SECONDS)
        .read_timeout(TELEGRAM_API_TIMEOUT_SECONDS)
        .write_timeout(TELEGRAM_API_TIMEOUT_SECONDS)
        .pool_timeout(TELEGRAM_API_TIMEOUT_SECONDS)
        .get_updates_connect_timeout(TELEGRAM_API_TIMEOUT_SECONDS)
        .get_updates_read_timeout(TELEGRAM_API_TIMEOUT_SECONDS)
        .get_updates_write_timeout(TELEGRAM_API_TIMEOUT_SECONDS)
        .get_updates_pool_timeout(TELEGRAM_API_TIMEOUT_SECONDS)
        .build()
    )
    application.add_handler(start_handler)
    application.add_handler(whoami_handler)

    for admin_handler in (
        adduser_handler,
        enablefeature_handler,
        disablefeature_handler,
        features_handler,
        locker_command_handler,
    ):
        add_authorization(admin_handler, Role.admin)
        application.add_handler(admin_handler)

    voice_handler = create_voice_handler(AdaptiveTranscribeClient())
    add_authorization(voice_handler)
    application.add_handler(voice_handler)

    add_authorization(text_chat_handler, feature=Feature.chat)
    application.add_handler(text_chat_handler)
    return application


async def main() -> None:
    SQLiteClient().init_db()

    application = build_application()
    http_host = '0.0.0.0'
    http_port = 8080
    admin_id = parse_int(os.getenv('ADMIN_ID'), default=0)
    locker_http_app = create_locker_http_app(application.bot, admin_id=admin_id)
    runner = web.AppRunner(locker_http_app)
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)

    app_started = False
    polling_started = False
    runner_started = False

    async with application:
        try:
            await application.start()
            app_started = True

            if application.updater is None:
                raise RuntimeError('Telegram application has no updater for polling.')
            await application.updater.start_polling()
            polling_started = True

            await runner.setup()
            runner_started = True
            site = web.TCPSite(runner, http_host, http_port)
            await site.start()
            LOGGER.info('Locker HTTP API listening on %s:%s', http_host, http_port)

            await stop_event.wait()
        finally:
            if runner_started:
                await runner.cleanup()
            if polling_started and application.updater is not None:
                await application.updater.stop()
            if app_started:
                await application.stop()


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda _signum, _frame: stop_event.set())


def parse_int(value: str | None, *, default: int) -> int:
    try:
        return int(value or str(default))
    except ValueError:
        return default


if __name__ == '__main__':
    asyncio.run(main())
