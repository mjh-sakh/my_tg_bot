from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from bot.clients import SQLiteClient

LOCKER_USAGE = 'Usage: /locker [on|off]'


def locker_mode_text(restricted: bool) -> str:
    return 'restricted' if restricted else 'keep going'


async def locker(update: Update, context: CallbackContext) -> None:
    client = SQLiteClient()

    if len(context.args) == 0:
        restricted = client.get_locker_restricted()
        await update.message.reply_text(f'Locker mode: {locker_mode_text(restricted)}.')
        return

    if len(context.args) != 1:
        await update.message.reply_text(LOCKER_USAGE)
        return

    action = context.args[0].strip().lower()
    if action == 'on':
        client.set_locker_restricted(True)
        await update.message.reply_text('Locker mode: restricted.')
        return

    if action == 'off':
        client.set_locker_restricted(False)
        await update.message.reply_text('Locker mode: keep going.')
        return

    await update.message.reply_text(LOCKER_USAGE)


locker_handler = CommandHandler('locker', locker)
