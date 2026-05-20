# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r bot/requirements.txt

# Run the bot (requires .env with TELEGRAM_BOT_TOKEN set)
python -m bot.main

# Test MCP servers
python mcp_servers/ytdlp_server/server.py --test
python mcp_servers/telegram_server/server.py --test

# Docker
docker build -t elviolevador-bot .
docker run -d --name elviolevador-bot --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -v $(pwd)/downloads:/downloads \
  elviolevador-bot
```

No test suite or linter is configured.

## Architecture

The bot is a single-process async Python app using **python-telegram-bot v20+** with long-polling. All blocking I/O (yt-dlp, gallery-dl, ffmpeg) runs in a thread executor via `loop.run_in_executor(None, ...)` to keep the event loop free.

### Request flow

```
Telegram update → handlers.py
  → _check_access()   # ALLOWED_USERS whitelist
  → _check_rate()     # RateLimiter.check(user_id)
  → _download_and_send()
      → download_video()    (yt-dlp, async wrapper)
          on UnsupportedURLError →
      → download_images()   (3-tier fallback)
          1. gallery-dl subprocess
          2. yt-dlp writethumbnail
          3. og:image/twitter:image HTML scraper
  → _send_video() / _send_photos() / _send_audio()
  → cleanup() / cleanup_many()   # always in finally
```

### Module responsibilities

| File | Role |
|------|------|
| `bot/config.py` | Loads `.env` at import time; exposes typed constants. Fails fast with a clear message if `TELEGRAM_BOT_TOKEN` is missing. |
| `bot/main.py` | Builds `Application`, calls `register_handlers()`, starts `run_polling()`. |
| `bot/handlers.py` | All Telegram callbacks. `register_handlers()` wires them. `_download_and_send()` tries video first, then images. |
| `bot/downloader.py` | All download logic. Public API: `download_video()`, `download_audio()`, `download_images()`. Custom exceptions: `InvalidURLError`, `UnsupportedURLError`, `FileTooLargeError`. |
| `bot/rate_limiter.py` | Sliding-window limiter using a per-user `deque[float]` protected by an `asyncio.Lock`. Module-level singleton `limiter` is imported by handlers. |
| `mcp_servers/ytdlp_server/server.py` | Optional MCP server exposing yt-dlp as tools for Claude Code. |
| `mcp_servers/telegram_server/server.py` | Optional MCP server exposing Telegram Bot API actions for Claude Code. |

### Key implementation details

- **Video format selection**: `bestvideo[filesize<MAX]+bestaudio[filesize<MAX]/best[filesize<MAX]/bestvideo+bestaudio/best` — preference ordering ensures the size check happens before downloading, with unconstrained fallbacks.
- **Image download fallback chain**: gallery-dl runs as a subprocess (`python -m gallery_dl`) into an isolated temp subdirectory, then files are moved with a `uid_NNNN` prefix. yt-dlp thumbnail uses `writethumbnail` + `FFmpegThumbnailsConvertor`. The og:image scraper uses httpx with a browser User-Agent.
- **Short URL resolution**: Before running gallery-dl, `_resolve_url()` follows redirects with `httpx` so gallery-dl's site-specific extractors see the canonical URL (e.g. `vm.tiktok.com` → full TikTok URL).
- **Temp file lifecycle**: Every code path that creates files wraps cleanup in a `finally` block. `cleanup()` and `cleanup_many()` silently ignore missing files.
- **Media groups**: Telegram limits media groups to 10. `_send_photos()` batches in chunks of 10 and keeps file handles open only within the `try/finally` block.
- **MCP config**: `mcp_config.json` at the project root wires both MCP servers for use in Claude Code. The `cwd` paths are absolute and Windows-specific — update if the repo is moved.

## Environment variables

| Variable | Default | Notes |
|----------|---------|-------|
| `TELEGRAM_BOT_TOKEN` | required | From @BotFather |
| `ALLOWED_USERS` | *(everyone)* | CSV of Telegram user IDs |
| `DOWNLOAD_DIR` | `/downloads` | Use a local path on Windows, e.g. `C:/Users/…/Downloads/bot_tmp` |
| `MAX_FILE_BYTES` | `52428800` | 50 MB Telegram bot limit |
| `RATE_LIMIT_CALLS` | `3` | Requests per window |
| `RATE_LIMIT_PERIOD` | `60` | Window in seconds |

## External dependencies

- **ffmpeg** must be on `PATH` — required for audio extraction (`FFmpegExtractAudio`) and video merging. Without it, audio downloads and merged video formats will fail silently or with a yt-dlp error.
- **gallery-dl** is invoked as a subprocess (`python -m gallery_dl`), not imported, so it must be installed in the same virtualenv.
