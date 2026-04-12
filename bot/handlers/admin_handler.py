from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from bot.clients import SQLiteClient
from bot.handlers.security import Feature, Role


async def adduser(update: Update, context: CallbackContext) -> None:
    if len(context.args) != 1:
        await update.message.reply_text('Usage: /adduser <telegram_user_id>')
        return

    try:
        target_user_id = parse_user_id(context.args[0])
    except ValueError:
        await update.message.reply_text('User id must be an integer.')
        return

    SQLiteClient().upsert_user(target_user_id, Role.user.value)
    await update.message.reply_text(f'Authorized user {target_user_id}.')


async def enablefeature(update: Update, context: CallbackContext) -> None:
    if len(context.args) != 2:
        await update.message.reply_text(
            f'Usage: /enablefeature <telegram_user_id> <feature>. Features: {supported_features_text()}'
        )
        return

    try:
        target_user_id = parse_user_id(context.args[0])
    except ValueError:
        await update.message.reply_text('User id must be an integer.')
        return

    try:
        feature = Feature.parse(context.args[1])
    except ValueError:
        await update.message.reply_text(f'Unknown feature. Supported features: {supported_features_text()}')
        return

    client = SQLiteClient()
    if not client.get_user_role(target_user_id):
        await update.message.reply_text(
            f'User {target_user_id} is not authorized yet. Add them first with /adduser.'
        )
        return

    client.enable_feature(target_user_id, feature.value)
    await update.message.reply_text(f'Enabled feature {feature.value} for user {target_user_id}.')


async def disablefeature(update: Update, context: CallbackContext) -> None:
    if len(context.args) != 2:
        await update.message.reply_text(
            f'Usage: /disablefeature <telegram_user_id> <feature>. Features: {supported_features_text()}'
        )
        return

    try:
        target_user_id = parse_user_id(context.args[0])
    except ValueError:
        await update.message.reply_text('User id must be an integer.')
        return

    try:
        feature = Feature.parse(context.args[1])
    except ValueError:
        await update.message.reply_text(f'Unknown feature. Supported features: {supported_features_text()}')
        return

    client = SQLiteClient()
    if not client.get_user_role(target_user_id):
        await update.message.reply_text(
            f'User {target_user_id} is not authorized yet. Add them first with /adduser.'
        )
        return

    client.disable_feature(target_user_id, feature.value)
    await update.message.reply_text(f'Disabled feature {feature.value} for user {target_user_id}.')


async def features(update: Update, context: CallbackContext) -> None:
    if len(context.args) != 1:
        await update.message.reply_text('Usage: /features <telegram_user_id>')
        return

    try:
        target_user_id = parse_user_id(context.args[0])
    except ValueError:
        await update.message.reply_text('User id must be an integer.')
        return

    client = SQLiteClient()
    if not client.get_user_role(target_user_id):
        await update.message.reply_text(
            f'User {target_user_id} is not authorized yet. Add them first with /adduser.'
        )
        return

    enabled_features = client.list_features(target_user_id)
    if not enabled_features:
        await update.message.reply_text(f'User {target_user_id} has no enabled features.')
        return

    await update.message.reply_text(
        f'Enabled features for user {target_user_id}: {", ".join(enabled_features)}.'
    )


def parse_user_id(value: str) -> int:
    return int(value)


def supported_features_text() -> str:
    return ', '.join(feature.value for feature in Feature)


adduser_handler = CommandHandler('adduser', adduser)
enablefeature_handler = CommandHandler('enablefeature', enablefeature)
disablefeature_handler = CommandHandler('disablefeature', disablefeature)
features_handler = CommandHandler('features', features)
