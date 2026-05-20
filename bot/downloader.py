"""
bot/downloader.py
Async yt-dlp (video/audio) + gallery-dl (images) wrapper.
Enforces URL validation, 50 MB size limit, and automatic temp-file cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import yt_dlp

from bot.config import (
    DOWNLOAD_DIR,
    MAX_FILE_BYTES,
    YOUTUBE_COOKIES_BROWSER,
    YOUTUBE_COOKIES_FILE,
)

logger = logging.getLogger(__name__)

# ── Silent yt-dlp logger ──────────────────────────────────────────────────────

class _YtdlpLogger:
    """Routes yt-dlp output to Python logging."""

    def debug(self, msg: str) -> None:    logger.debug("[yt-dlp] %s", msg)    # noqa: E704
    def info(self, msg: str) -> None:     logger.debug("[yt-dlp] %s", msg)    # noqa: E704
    def warning(self, msg: str) -> None:  logger.info("[yt-dlp] %s", msg)     # noqa: E704
    def error(self, msg: str) -> None:    logger.warning("[yt-dlp] %s", msg)  # noqa: E704


# ── Custom exceptions ─────────────────────────────────────────────────────────

class DownloadError(Exception):
    """Base class for all downloader errors."""


class InvalidURLError(DownloadError):
    """The supplied string is not a valid URL."""


class UnsupportedURLError(DownloadError):
    """No downloader could handle this URL / platform."""


class FileTooLargeError(DownloadError):
    """The downloaded file exceeds the Telegram bot size limit."""

    def __init__(self, size_bytes: int, limit_bytes: int) -> None:
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"File is {size_bytes / 1_048_576:.1f} MB, "
            f"exceeding the {limit_bytes / 1_048_576:.0f} MB limit."
        )


# ── URL validation ────────────────────────────────────────────────────────────

_URL_RE = re.compile(
    r"^https?://"
    r"(?:[A-Za-z0-9\-]+\.)+[A-Za-z]{2,}"
    r"(?::\d+)?"
    r"(?:[/?#]\S*)?$",
    re.IGNORECASE,
)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}


def validate_url(url: str) -> None:
    """Raise :class:`InvalidURLError` if *url* is not a valid HTTP(S) URL."""
    if not _URL_RE.match(url.strip()):
        raise InvalidURLError(f"Not a valid URL: {url!r}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_ytdlp_error(msg: str) -> str:
    for prefix in ("ERROR: ", "error: "):
        if msg.startswith(prefix):
            return msg[len(prefix):]
    return msg


_UNSUPPORTED_PHRASES = (
    "no suitable extractor",
    "unsupported url",
    "no extractor found",
    "ie key",
)


def _is_unsupported_error(msg: str) -> bool:
    lower = msg.lower()
    return any(p in lower for p in _UNSUPPORTED_PHRASES)


def _cookie_opts() -> dict:
    """Return yt-dlp cookie options from config, or {} if none configured."""
    if YOUTUBE_COOKIES_FILE:
        path = Path(YOUTUBE_COOKIES_FILE)
        if path.exists():
            return {"cookiefile": str(path)}
        logger.warning("YOUTUBE_COOKIES_FILE '%s' not found — proceeding without cookies", YOUTUBE_COOKIES_FILE)
    elif YOUTUBE_COOKIES_BROWSER:
        return {"cookiesfrombrowser": (YOUTUBE_COOKIES_BROWSER,)}
    return {}


def _check_size(path: Path) -> None:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        cleanup(path)
        raise FileTooLargeError(size, MAX_FILE_BYTES)


def cleanup(path: Path) -> None:
    """Delete a downloaded file, silently ignoring missing files."""
    try:
        if path and path.exists():
            path.unlink()
            logger.debug("Deleted temp file: %s", path)
    except OSError as exc:
        logger.warning("Failed to delete %s: %s", path, exc)


def cleanup_many(paths: list[Path]) -> None:
    """Delete multiple downloaded files."""
    for p in paths:
        cleanup(p)


# ── Sync video worker ─────────────────────────────────────────────────────────

def _sync_download_video(url: str, out_dir: Path) -> Path:
    """Download best video ≤ 50 MB and return its path."""
    uid = uuid.uuid4().hex
    outtmpl = str(out_dir / f"{uid}_%(title).80s.%(ext)s")

    downloaded: list[str] = []

    def _hook(d: dict) -> None:
        if d["status"] == "finished":
            downloaded.append(d.get("filename", ""))

    opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": _YtdlpLogger(),
        "format": (
            f"bestvideo[filesize<{MAX_FILE_BYTES}]+bestaudio[filesize<{MAX_FILE_BYTES}]"
            f"/best[filesize<{MAX_FILE_BYTES}]"
            "/bestvideo+bestaudio/best"
        ),
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "restrictfilenames": True,
        "noplaylist": True,
        "progress_hooks": [_hook],
        **_cookie_opts(),
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            final = Path(ydl.prepare_filename(ydl.sanitize_info(info)))
    except yt_dlp.utils.DownloadError as exc:
        clean = _clean_ytdlp_error(str(exc))
        if _is_unsupported_error(clean):
            raise UnsupportedURLError(clean) from exc
        raise DownloadError(clean) from exc

    if downloaded:
        candidate = Path(downloaded[-1])
        for p in (candidate, candidate.with_suffix(".mp4")):
            if p.exists():
                final = p
                break

    if not final.exists():
        matches = sorted(out_dir.glob(f"{uid}_*"))
        if not matches:
            raise DownloadError("Download finished but output file not found.")
        final = matches[0]

    return final


# ── Sync audio worker ─────────────────────────────────────────────────────────

def _sync_download_audio(url: str, out_dir: Path) -> Path:
    """Download and extract audio as mp3, return its path."""
    uid = uuid.uuid4().hex
    outtmpl = str(out_dir / f"{uid}_%(title).80s.%(ext)s")

    downloaded: list[str] = []

    def _hook(d: dict) -> None:
        if d["status"] == "finished":
            downloaded.append(d.get("filename", ""))

    opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": _YtdlpLogger(),
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "restrictfilenames": True,
        "noplaylist": True,
        "progress_hooks": [_hook],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        **_cookie_opts(),
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        clean = _clean_ytdlp_error(str(exc))
        if _is_unsupported_error(clean):
            raise UnsupportedURLError(clean) from exc
        raise DownloadError(clean) from exc

    if downloaded:
        base = Path(downloaded[-1]).with_suffix(".mp3")
        if base.exists():
            return base

    matches = sorted(out_dir.glob(f"{uid}_*.mp3"))
    if not matches:
        raise DownloadError("Audio extraction finished but .mp3 file not found.")
    return matches[0]


# ── Image download: gallery-dl (primary) ──────────────────────────────────────

def _resolve_url(url: str) -> str:
    """
    Follow HTTP redirects and return the canonical URL.

    This is critical for short-link services (vm.tiktok.com, vt.tiktok.com,
    t.co, youtu.be, etc.) because gallery-dl's extractors match on the
    *final* URL pattern, not the redirect chain.
    """
    try:
        with httpx.Client(
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA},
        ) as client:
            resp = client.head(url)
            final = str(resp.url)
            if final != url:
                logger.info("Resolved short URL: %s → %s", url, final)
            return final
    except Exception as exc:
        logger.debug("URL resolution failed (%s), using original: %s", exc, url)
        return url


def _gallery_dl_download(url: str, out_dir: Path, uid: str) -> list[Path]:
    """
    Use gallery-dl to download images from any supported platform.

    gallery-dl has native support for TikTok, Instagram, Twitter/X,
    Reddit, Pinterest, Pixiv, DeviantArt, and 200+ other sites.

    Downloads into an isolated temp subdirectory then returns the image
    files moved to *out_dir* with a *uid* prefix.
    """
    # Resolve short URLs (vm.tiktok.com, t.co, youtu.be …) to canonical form
    # so gallery-dl's site-specific extractors can recognise the URL.
    resolved = _resolve_url(url)

    temp_dir = out_dir / f"_gdl_{uid}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "gallery_dl",
        "--dest", str(temp_dir),
        # Pass a browser User-Agent so CDNs don't reject the request
        "-o", f"user-agent={_BROWSER_UA}",
        # Limit retries to keep response time reasonable
        "-o", "retries=2",
        resolved,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        # Always log at INFO so failures are visible without DEBUG mode
        combined = (result.stdout + result.stderr).strip()
        if combined:
            logger.info("gallery-dl [exit %d]: %s", result.returncode, combined[:400])
        else:
            logger.info("gallery-dl [exit %d]: no output", result.returncode)
    except subprocess.TimeoutExpired:
        logger.warning("gallery-dl timed out for %s", url)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return []
    except FileNotFoundError:
        logger.warning("gallery-dl not found — skipping")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return []

    # Collect all image files from the (possibly nested) temp dir
    all_files = sorted(temp_dir.rglob("*"))
    image_files = [f for f in all_files if f.is_file() and f.suffix.lower() in _IMAGE_EXTS]

    if not image_files:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return []

    # Move to out_dir with uid prefix so we can track them
    result_paths: list[Path] = []
    for i, src in enumerate(image_files):
        dest = out_dir / f"{uid}_{i:04d}{src.suffix.lower()}"
        shutil.move(str(src), dest)
        result_paths.append(dest)

    shutil.rmtree(temp_dir, ignore_errors=True)
    logger.info("gallery-dl: downloaded %d image(s) for %s", len(result_paths), url)
    return result_paths



# ── Image download: yt-dlp thumbnail fallback ─────────────────────────────────

def _ytdlp_thumbnail_download(url: str, out_dir: Path, uid: str) -> list[Path]:
    """
    Try to get an image via yt-dlp's writethumbnail.
    Works for platforms like YouTube (thumbnail), SoundCloud, etc.
    """
    outtmpl = str(out_dir / f"{uid}_%(title).80s.%(ext)s")
    thumbnail_url: str | None = None

    opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": _YtdlpLogger(),
        "format": "best",
        "outtmpl": outtmpl,
        "restrictfilenames": True,
        "noplaylist": True,
        "writethumbnail": True,
        "postprocessors": [
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
        ],
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            info = ydl.sanitize_info(info or {})
            thumbnail_url = (info or {}).get("thumbnail")
    except yt_dlp.utils.DownloadError:
        pass

    image_files = [
        p for p in sorted(out_dir.glob(f"{uid}_*"))
        if p.suffix.lower() in _IMAGE_EXTS
    ]
    if image_files:
        # Remove non-image sidecars
        for f in sorted(out_dir.glob(f"{uid}_*")):
            if f not in image_files:
                try:
                    f.unlink()
                except OSError:
                    pass
        return image_files

    if thumbnail_url:
        try:
            path = _fetch_image_url(thumbnail_url, out_dir, uid, "thumb")
            return [path]
        except UnsupportedURLError:
            pass

    return []


# ── Image download: og:image HTML scraper (last resort) ───────────────────────

_OG_RE = re.compile(
    r'<meta[^>]+(?:property=["\']og:image["\']|name=["\']twitter:image["\'])[^>]+'
    r'content=["\']([^"\'<>]+)["\']'
    r'|'
    r'<meta[^>]+content=["\']([^"\'<>]+)["\'][^>]+'
    r'(?:property=["\']og:image["\']|name=["\']twitter:image["\'])',
    re.IGNORECASE,
)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def _scrape_og_image(url: str) -> str | None:
    """Fetch page HTML and extract og:image / twitter:image. Returns URL or None."""
    try:
        with httpx.Client(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"},
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPError as exc:
        logger.debug("og:image page fetch failed for %s: %s", url, exc)
        return None

    m = _OG_RE.search(html)
    if m:
        img = (m.group(1) or m.group(2) or "").strip().replace("&amp;", "&")
        if img:
            logger.info("og:image found: %s", img)
            return img
    return None


def _fetch_image_url(image_url: str, out_dir: Path, uid: str, label: str) -> Path:
    """Download a direct image URL to out_dir and return the local Path."""
    ext = image_url.split("?")[0].rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "webp", "gif", "avif"}:
        ext = "jpg"
    dest = out_dir / f"{uid}_{label}.{ext}"
    try:
        with httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA},
        ) as client:
            resp = client.get(image_url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
    except httpx.HTTPError as exc:
        raise UnsupportedURLError(f"Could not download image: {exc}") from exc
    return dest


# ── Sync image orchestrator ───────────────────────────────────────────────────

def _sync_download_images(url: str, out_dir: Path) -> list[Path]:
    """
    Download image(s) from a URL using a 3-tier fallback chain:

    1. gallery-dl  — native support for TikTok, Instagram, Twitter/X, etc.
    2. yt-dlp      — thumbnail extraction for YouTube/SoundCloud/etc.
    3. og:image    — HTML meta-tag scraper for any remaining site.
    """
    uid = uuid.uuid4().hex

    # Tier 1: gallery-dl
    paths = _gallery_dl_download(url, out_dir, uid)
    if paths:
        return paths

    # Tier 2: yt-dlp thumbnail
    logger.info("gallery-dl found nothing, trying yt-dlp thumbnail for %s", url)
    paths = _ytdlp_thumbnail_download(url, out_dir, uid)
    if paths:
        return paths

    # Tier 3: og:image scraper
    logger.info("Trying og:image scraper for %s", url)
    og_url = _scrape_og_image(url)
    if og_url:
        path = _fetch_image_url(og_url, out_dir, uid, "og_image")
        return [path]

    raise UnsupportedURLError(
        "No image could be found for this URL. "
        "The platform may not be supported or may require login."
    )


# ── Sync playlist worker ──────────────────────────────────────────────────────

def _sync_download_playlist(url: str, out_dir: Path, max_videos: int) -> list[Path]:
    """Download up to *max_videos* entries from a playlist and return their paths."""
    uid = uuid.uuid4().hex
    outtmpl = str(out_dir / f"{uid}_%(playlist_index)03d_%(title).60s.%(ext)s")

    downloaded: list[str] = []

    def _hook(d: dict) -> None:
        if d["status"] == "finished":
            downloaded.append(d.get("filename", ""))

    opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": _YtdlpLogger(),
        "format": (
            f"bestvideo[filesize<{MAX_FILE_BYTES}]+bestaudio[filesize<{MAX_FILE_BYTES}]"
            f"/best[filesize<{MAX_FILE_BYTES}]"
            "/bestvideo+bestaudio/best"
        ),
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "restrictfilenames": True,
        "noplaylist": False,
        "playlistend": max_videos,
        "progress_hooks": [_hook],
        **_cookie_opts(),
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        clean = _clean_ytdlp_error(str(exc))
        if _is_unsupported_error(clean):
            raise UnsupportedURLError(clean) from exc
        raise DownloadError(clean) from exc

    paths = sorted(out_dir.glob(f"{uid}_*"))
    if not paths:
        raise DownloadError("Playlist download finished but no output files were found.")
    return paths


# ── Public async API ──────────────────────────────────────────────────────────

async def download_video(url: str) -> Path:
    """Validate *url*, download the best video (≤ 50 MB), return its path."""
    validate_url(url)
    logger.info("Starting video download: %s", url)
    loop = asyncio.get_event_loop()
    path: Path = await loop.run_in_executor(None, _sync_download_video, url, DOWNLOAD_DIR)
    _check_size(path)
    logger.info("Video ready: %s (%.1f MB)", path.name, path.stat().st_size / 1_048_576)
    return path


async def download_audio(url: str) -> Path:
    """Validate *url*, download audio as mp3, return its path."""
    validate_url(url)
    logger.info("Starting audio download: %s", url)
    loop = asyncio.get_event_loop()
    path: Path = await loop.run_in_executor(None, _sync_download_audio, url, DOWNLOAD_DIR)
    _check_size(path)
    logger.info("Audio ready: %s (%.1f MB)", path.name, path.stat().st_size / 1_048_576)
    return path


async def download_playlist(url: str, max_videos: int = 10) -> list[Path]:
    """Download up to *max_videos* from a playlist URL. Returns paths of valid files."""
    validate_url(url)
    logger.info("Starting playlist download: %s (max %d videos)", url, max_videos)
    loop = asyncio.get_event_loop()
    paths: list[Path] = await loop.run_in_executor(
        None, _sync_download_playlist, url, DOWNLOAD_DIR, max_videos
    )
    valid: list[Path] = []
    for p in paths:
        try:
            _check_size(p)
            valid.append(p)
        except FileTooLargeError:
            logger.warning("Skipping oversized playlist video: %s", p.name)
            cleanup(p)
    if not valid:
        raise DownloadError("All playlist videos exceeded the 50 MB Telegram limit.")
    logger.info("Playlist ready: %d video(s)", len(valid))
    return valid


async def download_images(url: str) -> list[Path]:
    """
    Validate *url*, download image(s) using gallery-dl → yt-dlp → og:image
    fallback chain, and return a list of local Paths.

    For carousel posts this may return multiple images.
    All returned files must be cleaned up by the caller.
    """
    validate_url(url)
    logger.info("Starting image download: %s", url)
    loop = asyncio.get_event_loop()
    paths: list[Path] = await loop.run_in_executor(
        None, _sync_download_images, url, DOWNLOAD_DIR
    )
    # Check each image fits within the limit (skip oversized ones)
    valid: list[Path] = []
    for p in paths:
        try:
            _check_size(p)
            valid.append(p)
        except FileTooLargeError:
            logger.warning("Skipping oversized image: %s", p.name)
            cleanup(p)
    if not valid:
        raise FileTooLargeError(0, MAX_FILE_BYTES)
    logger.info("Images ready: %d file(s)", len(valid))
    return valid
