import logging
import os

from telegram.ext import Application

logging.basicConfig(level=logging.INFO)

from bot.handlers import (
    Feature,
    Role,
    add_authorization,
    adduser_handler,
    chat_handler,
    create_voice_handler,
    disablefeature_handler,
    enablefeature_handler,
    features_handler,
    reply_handler,
    start_handler,
    track_history_handler,
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
    add_authorization(voice_handler, feature=Feature.voice)
    application.add_handler(voice_handler)

    # add_authorization(chat_handler, feature=Feature.chat)
    # application.add_handler(chat_handler)
    application.add_handler(track_history_handler, group=1)
    # add_authorization(reply_handler, feature=Feature.chat)
    # application.add_handler(reply_handler)
    application.run_polling()
