import logging
import os

from telegram.ext import Application

logging.basicConfig(level=logging.INFO)

from bot.handlers import (
    Feature,
    Role,
    add_authorization,
    adduser_handler,
    create_voice_handler,
    disablefeature_handler,
    enablefeature_handler,
    features_handler,
    start_handler,
    text_chat_handler,
    whoami_handler,
)
from bot.clients import AdaptiveTranscribeClient, SQLiteClient

if __name__ == '__main__':
    SQLiteClient().init_db()
    application = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()
    application.add_handler(start_handler)
    application.add_handler(whoami_handler)

    for admin_handler in (
        adduser_handler,
        enablefeature_handler,
        disablefeature_handler,
        features_handler,
    ):
        add_authorization(admin_handler, Role.admin)
        application.add_handler(admin_handler)

    voice_handler = create_voice_handler(AdaptiveTranscribeClient())
    add_authorization(voice_handler)
    application.add_handler(voice_handler)

    add_authorization(text_chat_handler, feature=Feature.chat)
    application.add_handler(text_chat_handler)
    application.run_polling()
