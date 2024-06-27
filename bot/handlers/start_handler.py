from telegram import Update
from telegram.ext import CommandHandler, CallbackContext


async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("I'm alive, yeah! Do I know you?")


start_handler = CommandHandler('start', start)
