"""
bot/config.py
Centralised configuration loaded from environment variables / .env file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            "Copy .env.example → .env and fill in your values."
        )
    return value


# ── Telegram ─────────────────────────────────────────────────────────────────
BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")

# Optional whitelist: comma-separated Telegram user IDs.
# If empty/unset, the bot is open to everyone.
_raw_allowed = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = (
    {int(uid.strip()) for uid in _raw_allowed.split(",") if uid.strip()}
    if _raw_allowed.strip()
    else set()
)

# ── Downloads ─────────────────────────────────────────────────────────────────
DOWNLOAD_DIR: Path = Path(os.getenv("DOWNLOAD_DIR", "/downloads")).resolve()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Telegram bots can send files up to 50 MB
MAX_FILE_BYTES: int = int(os.getenv("MAX_FILE_BYTES", str(50 * 1024 * 1024)))

# ── Rate limiting ──────────────────────────────────────────────────────────────
# Max number of requests per user within the time window
RATE_LIMIT_CALLS: int = int(os.getenv("RATE_LIMIT_CALLS", "3"))
# Time window in seconds
RATE_LIMIT_PERIOD: int = int(os.getenv("RATE_LIMIT_PERIOD", "60"))
