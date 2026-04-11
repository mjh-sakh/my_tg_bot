from telegram import Update
from telegram.ext import CommandHandler, CallbackContext


async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("I'm alive, yeah! Do I know you?")


async def whoami(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    await update.message.reply_text(f"Your Telegram user id is: {user.id}")


start_handler = CommandHandler('start', start)
whoami_handler = CommandHandler('whoami', whoami)
