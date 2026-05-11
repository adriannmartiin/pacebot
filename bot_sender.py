"""
bot_sender.py
Envía mensajes al canal de Telegram.
"""

import logging
import asyncio
from telegram import Bot
from telegram.constants import ParseMode
import config

logger = logging.getLogger(__name__)
_bot = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=config.TELEGRAM_TOKEN)
    return _bot


async def _send(text: str):
    bot = get_bot()
    await bot.send_message(
        chat_id    = config.TELEGRAM_CHANNEL,
        text       = text,
        parse_mode = ParseMode.MARKDOWN,
    )


def send_message(text: str):
    """Envío síncrono — llama desde cualquier parte del código."""
    try:
        asyncio.run(_send(text))
        logger.info("Mensaje enviado a Telegram")
    except Exception as e:
        logger.error(f"Error enviando a Telegram: {e}")
