"""
bot/main.py
Entry point — builds the Application and starts long-polling.
"""

from __future__ import annotations

import logging
import sys

from telegram.ext import ApplicationBuilder

from bot.config import BOT_TOKEN, DOWNLOAD_DIR, MAX_FILE_BYTES, RATE_LIMIT_CALLS, RATE_LIMIT_PERIOD
from bot.handlers import register_handlers

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Reduce noise from httpx / telegram internals
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Starting ElViolevador Bot")
    logger.info(
        "Config: download_dir=%s  max_file=%.0f MB  rate=%d req/%ds",
        DOWNLOAD_DIR,
        MAX_FILE_BYTES / 1_048_576,
        RATE_LIMIT_CALLS,
        RATE_LIMIT_PERIOD,
    )

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    register_handlers(app)

    logger.info("Polling for updates…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
