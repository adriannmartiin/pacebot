"""
listener.py
Proceso independiente para recibir comandos de Telegram.
Se ejecuta separado del scheduler principal.
"""

import asyncio
import logging
import os

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/listener.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

from telegram.ext import Application, CommandHandler
import config
from commands import (
    cmd_status, cmd_scan48, cmd_hoy, cmd_stats, cmd_proximas
)


async def main():
    logger.info("Iniciando listener de comandos...")

    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("scan48",   cmd_scan48))
    app.add_handler(CommandHandler("hoy",      cmd_hoy))
    app.add_handler(CommandHandler("stats",    cmd_stats))
    app.add_handler(CommandHandler("proximas", cmd_proximas))

    logger.info("Comandos registrados: /status /scan48 /hoy /stats /proximas")
    logger.info("Esperando comandos...")

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()  # esperar indefinidamente


if __name__ == "__main__":
    asyncio.run(main())
