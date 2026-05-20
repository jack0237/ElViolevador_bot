# ElViolevador Bot 🤖

A production-ready Telegram bot that downloads videos and audio from 1000+ sites (YouTube, TikTok, Instagram, Twitter/X, SoundCloud, Twitch, Reddit, …) using **yt-dlp** and **python-telegram-bot v20+**.

---

## Features

| Feature | Detail |
| --- | --- |
| Video download | Best quality ≤ 50 MB, sent as Telegram video |
| Audio download | Extracted as **MP3 192 kbps**, sent as Telegram audio |
| URL auto-detect | Paste a bare link — bot triggers download automatically |
| Rate limiting | 3 requests / 60 s per user (sliding window, configurable) |
| User whitelist | Optional `ALLOWED_USERS` env var |
| File auto-cleanup | Temp files deleted immediately after sending |
| Structured logging | Timestamps + log levels via Python `logging` module |
| Async | Fully non-blocking; blocking yt-dlp work runs in thread executor |

---

## Project Structure

```text
ElViolevador_bot/
├── bot/
│   ├── __init__.py
│   ├── config.py          # Env-var settings
│   ├── downloader.py      # Async yt-dlp wrapper
│   ├── rate_limiter.py    # Sliding-window rate limiter
│   ├── handlers.py        # Telegram command & message handlers
│   ├── main.py            # Entry point
│   └── requirements.txt
├── mcp_servers/
│   ├── telegram_server/
│   └── ytdlp_server/
├── .env.example
├── Dockerfile
└── README.md
```

---

## Quick Start (Local)

### Prerequisites

- Python 3.11+
- **ffmpeg** installed and on `PATH` (required for audio extraction and video merging)
  - Windows: `winget install Gyan.FFmpeg` or download from [ffmpeg.org](https://ffmpeg.org)
  - Linux: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`

### 1. Clone and create `.env`

```bash
cp .env.example .env
# Edit .env and set TELEGRAM_BOT_TOKEN
```

### 2. Create and activate virtual environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r bot/requirements.txt
```

### 4. Create the download directory (Windows: use a local path)

```bash
# Linux / macOS
mkdir -p /downloads

# Windows — override DOWNLOAD_DIR in .env instead:
# DOWNLOAD_DIR=C:/Users/YourName/Downloads/bot_tmp
```

### 5. Run the bot

```bash
python -m bot.main
```

---

## Docker Deployment

### Build

```bash
docker build -t elviolevador-bot .
```

### Run

```bash
docker run -d \
  --name elviolevador-bot \
  --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=your_token_here \
  -v $(pwd)/downloads:/downloads \
  elviolevador-bot
```

### Docker Compose (recommended)

```yaml
version: "3.9"
services:
  bot:
    build: .
    restart: unless-stopped
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - ALLOWED_USERS=${ALLOWED_USERS:-}
      - RATE_LIMIT_CALLS=3
      - RATE_LIMIT_PERIOD=60
    volumes:
      - downloads:/downloads
volumes:
  downloads:
```

Save as `docker-compose.yml` then:

```bash
TELEGRAM_BOT_TOKEN=your_token docker compose up -d
```

---

## Environment Variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Token from @BotFather |
| `ALLOWED_USERS` | ❌ | *(everyone)* | CSV of allowed Telegram user IDs |
| `DOWNLOAD_DIR` | ❌ | `/downloads` | Temp file directory |
| `MAX_FILE_BYTES` | ❌ | `52428800` (50 MB) | Hard size ceiling |
| `RATE_LIMIT_CALLS` | ❌ | `3` | Max requests per window |
| `RATE_LIMIT_PERIOD` | ❌ | `60` | Window in seconds |

---

## Bot Commands

| Command | Description |
| --- | --- |
| `/start` | Welcome message + usage guide |
| `/help` | Command reference |
| `/video <url>` | Download video and send to chat |
| `/audio <url>` | Download audio (MP3) and send to chat |
| *(bare URL)* | Auto-detected, treated as `/video` |

---

## Error Handling

| Situation | Bot response |
| --- | --- |
| Invalid URL | "Not a valid URL" message |
| Unsupported site | "Unsupported site" message |
| File > 50 MB | Size and limit shown to user |
| Rate limit exceeded | Retry-after seconds shown |
| Unauthorised user | "Not authorised" message |
