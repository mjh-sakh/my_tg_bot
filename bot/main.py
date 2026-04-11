import logging
import os

from telegram.ext import Application

logging.basicConfig(level=logging.INFO)

from bot.handlers import start_handler, whoami_handler, create_voice_handler, add_authorization, chat_handler, reply_handler, track_history_handler
from bot.clients import AdaptiveTranscribeClient

if __name__ == '__main__':
    application = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()
    application.add_handler(start_handler)
    application.add_handler(whoami_handler)
    voice_handler = create_voice_handler(AdaptiveTranscribeClient())
    add_authorization(voice_handler)
    application.add_handler(voice_handler)
    add_authorization(chat_handler)
    application.add_handler(chat_handler)
    application.add_handler(track_history_handler, group=1)
    application.add_handler(reply_handler)
    application.run_polling()
