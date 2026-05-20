"""
bot/handlers.py
Telegram command and message handlers using python-telegram-bot v20+ async API.
"""

from __future__ import annotations

import logging
from pathlib import Path

from telegram import InputMediaPhoto, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import ALLOWED_USERS
from bot.downloader import (
    DownloadError,
    FileTooLargeError,
    InvalidURLError,
    UnsupportedURLError,
    cleanup,
    cleanup_many,
    download_audio,
    download_images,
    download_video,
)
from bot.rate_limiter import RateLimitExceeded, limiter

logger = logging.getLogger(__name__)

# ── Shared helpers ────────────────────────────────────────────────────────────

async def _check_access(update: Update) -> bool:
    user = update.effective_user
    if ALLOWED_USERS and user.id not in ALLOWED_USERS:
        logger.warning("Blocked unauthorised user %s (%d)", user.username, user.id)
        await update.message.reply_text("⛔ You are not authorised to use this bot.")
        return False
    return True


async def _check_rate(update: Update) -> bool:
    user = update.effective_user
    try:
        await limiter.check(user.id)
        return True
    except RateLimitExceeded as exc:
        logger.info("Rate-limited user %s (%d). Retry in %.0fs", user.username, user.id, exc.retry_after)
        await update.message.reply_text(
            f"⏳ Slow down! You can send another request in *{exc.retry_after:.0f}s*.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return False


async def _send_video(update: Update, path: Path) -> None:
    await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
    with path.open("rb") as fh:
        await update.message.reply_video(
            video=fh,
            caption=f"🎬 `{path.name}`",
            parse_mode=ParseMode.MARKDOWN,
            supports_streaming=True,
        )


async def _send_photos(update: Update, paths: list[Path]) -> None:
    """Send one or more images. Multiple images are sent as a Telegram media group."""
    await update.message.chat.send_action(ChatAction.UPLOAD_PHOTO)

    if len(paths) == 1:
        with paths[0].open("rb") as fh:
            await update.message.reply_photo(
                photo=fh,
                caption=f"🖼 `{paths[0].name}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    # Multiple images — send as media group (max 10 per Telegram group)
    for batch_start in range(0, len(paths), 10):
        batch = paths[batch_start:batch_start + 10]
        media_group = []
        handles = []
        try:
            for i, p in enumerate(batch):
                fh = p.open("rb")
                handles.append(fh)
                caption = f"🖼 {batch_start + i + 1}/{len(paths)}" if i == 0 else None
                media_group.append(InputMediaPhoto(media=fh, caption=caption))
            await update.message.reply_media_group(media=media_group)
        finally:
            for fh in handles:
                fh.close()


async def _send_audio(update: Update, path: Path) -> None:
    await update.message.chat.send_action(ChatAction.UPLOAD_VOICE)
    with path.open("rb") as fh:
        await update.message.reply_audio(
            audio=fh,
            caption=f"🎵 `{path.name}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _handle_download_error(update: Update, exc: Exception) -> None:
    if isinstance(exc, InvalidURLError):
        msg = "❌ That doesn't look like a valid URL. Please send a full https:// link."
    elif isinstance(exc, UnsupportedURLError):
        msg = "❌ Unsupported site or the URL could not be resolved. Check the link and try again."
    elif isinstance(exc, FileTooLargeError):
        mb = exc.size_bytes / 1_048_576
        limit = exc.limit_bytes / 1_048_576
        msg = f"❌ File is *{mb:.1f} MB* — exceeds the *{limit:.0f} MB* Telegram bot limit."
    elif isinstance(exc, DownloadError):
        msg = f"❌ Download failed: {exc}"
    else:
        msg = "❌ An unexpected error occurred. Please try again later."
    logger.exception("Download error for user %s: %s", update.effective_user.id, exc)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ── Video+image combined download helper ──────────────────────────────────────

async def _download_and_send(update: Update, url: str, status_msg) -> None:
    """
    Try video first; if the URL is unsupported by yt-dlp, fall back to
    gallery-dl image download (handles TikTok photos, Instagram posts, etc.).
    """
    paths: list[Path] = []
    video_path: Path | None = None
    try:
        # Attempt 1: video
        try:
            video_path = await download_video(url)
            await _send_video(update, video_path)
            return
        except UnsupportedURLError:
            logger.info("Video failed, trying image download for %s", url)
            await status_msg.edit_text("🖼 Looks like a photo — downloading image…")

        # Attempt 2: images via gallery-dl → yt-dlp thumbnail → og:image
        paths = await download_images(url)
        await _send_photos(update, paths)

    finally:
        if video_path:
            cleanup(video_path)
        if paths:
            cleanup_many(paths)


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info("/start from %s (%d)", user.username, user.id)
    await update.message.reply_text(
        f"👋 *Hello, {user.first_name}!*\n\n"
        "I can download videos, audio, *and images* from YouTube, Instagram, "
        "TikTok, Twitter/X, Reddit, SoundCloud, Twitch, and 1000+ other sites.\n\n"
        "📋 *Commands:*\n"
        "• `/video <url>` — Download video\n"
        "• `/audio <url>` — Download audio as MP3\n"
        "• Just paste a URL — I'll auto-detect video or photo\n\n"
        "⚠️ Max file size: *50 MB* (Telegram limit)\n"
        "⏱ Rate limit: *3 requests per 60 seconds*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *ElViolevador Bot — Help*\n\n"
        "*Commands:*\n"
        "`/start` — Welcome message\n"
        "`/help` — This message\n"
        "`/video <url>` — Download video (falls back to image if needed)\n"
        "`/audio <url>` — Download audio (MP3)\n\n"
        "*Supported sites:* YouTube, TikTok, Instagram, Twitter/X, "
        "Reddit, SoundCloud, Twitch, Pinterest, and 1000+ more.\n\n"
        "*Photo carousels* (TikTok, Instagram) are sent as a media group.\n\n"
        "*Limitations:*\n"
        "• Files > 50 MB cannot be delivered\n"
        "• 3 requests per 60 s per user",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    if not await _check_rate(update):
        return

    if not context.args:
        await update.message.reply_text("Usage: `/video <url>`", parse_mode=ParseMode.MARKDOWN)
        return

    url = context.args[0]
    logger.info("/video %s from user %d", url, update.effective_user.id)
    status_msg = await update.message.reply_text("⏬ Downloading…")
    try:
        await _download_and_send(update, url, status_msg)
    except Exception as exc:
        await _handle_download_error(update, exc)
    finally:
        await status_msg.delete()


async def cmd_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    if not await _check_rate(update):
        return

    if not context.args:
        await update.message.reply_text("Usage: `/audio <url>`", parse_mode=ParseMode.MARKDOWN)
        return

    url = context.args[0]
    logger.info("/audio %s from user %d", url, update.effective_user.id)
    status_msg = await update.message.reply_text("⏬ Extracting audio…")
    path: Path | None = None
    try:
        path = await download_audio(url)
        await _send_audio(update, path)
    except Exception as exc:
        await _handle_download_error(update, exc)
    finally:
        await status_msg.delete()
        if path:
            cleanup(path)


async def msg_url_autodetect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detect bare URL in chat and auto-download (video first, then images)."""
    if not await _check_access(update):
        return
    if not await _check_rate(update):
        return

    url = update.message.text.strip()
    logger.info("Auto-detect URL %s from user %d", url, update.effective_user.id)
    status_msg = await update.message.reply_text("🔍 URL detected — downloading…")
    try:
        await _download_and_send(update, url, status_msg)
    except Exception as exc:
        await _handle_download_error(update, exc)
    finally:
        await status_msg.delete()


# ── Handler registration ──────────────────────────────────────────────────────

def register_handlers(app: Application) -> None:
    """Attach all handlers to the application."""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("video", cmd_video))
    app.add_handler(CommandHandler("audio", cmd_audio))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(r"https?://\S+"),
            msg_url_autodetect,
        )
    )
