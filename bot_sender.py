"""
bot_sender.py
Gestiona envío de mensajes y listener de comandos.
"""

import logging
import asyncio
import threading
from telegram import Bot
from telegram.ext import Application, CommandHandler
from telegram.constants import ParseMode
import config

logger = logging.getLogger(__name__)
_bot  = None
_loop = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=config.TELEGRAM_TOKEN)
    return _bot


def _get_loop():
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        t = threading.Thread(target=_loop.run_forever, daemon=True)
        t.start()
    return _loop


async def _send_async(text: str):
    bot = get_bot()
    await bot.send_message(
        chat_id    = config.TELEGRAM_CHANNEL,
        text       = text,
        parse_mode = ParseMode.MARKDOWN,
    )


def send_message(text: str):
    """Envia un mensaje al canal."""
    try:
        asyncio.run_coroutine_threadsafe(
            _send_async(text), _get_loop()
        ).result(timeout=15)
        logger.info("Mensaje enviado")
    except Exception as e:
        logger.error(f"Error enviando mensaje: {e}")


def start_command_listener():
    """Arranca el listener de comandos en un thread separado."""
    from commands import (
        cmd_status, cmd_scan48, cmd_hoy, cmd_stats, cmd_proximas
    )

    async def _run_app():
        app = (
            Application.builder()
            .token(config.TELEGRAM_TOKEN)
            .build()
        )
        app.add_handler(CommandHandler("status",   cmd_status))
        app.add_handler(CommandHandler("scan48",   cmd_scan48))
        app.add_handler(CommandHandler("hoy",      cmd_hoy))
        app.add_handler(CommandHandler("stats",    cmd_stats))
        app.add_handler(CommandHandler("proximas", cmd_proximas))
        logger.info("Comandos: /status /scan48 /hoy /stats /proximas")
        await app.run_polling(stop_signals=None)

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_app())
        except Exception as e:
            logger.error(f"Error listener: {e}")

    t = threading.Thread(target=_run, daemon=True, name="cmd-listener")
    t.start()
    logger.info("Listener de comandos iniciado")
