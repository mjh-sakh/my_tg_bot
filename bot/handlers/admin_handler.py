from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from bot.clients import SQLiteClient
from bot.handlers.security import Role


async def adduser(update: Update, context: CallbackContext) -> None:
    if len(context.args) != 1:
        await update.message.reply_text('Usage: /adduser <telegram_user_id>')
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text('User id must be an integer.')
        return

    SQLiteClient().upsert_user(target_user_id, Role.user.value)
    await update.message.reply_text(f'Authorized user {target_user_id}.')


adduser_handler = CommandHandler('adduser', adduser)
