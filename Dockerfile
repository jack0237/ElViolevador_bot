# ── Stage 1: builder ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools (needed for some yt-dlp / cryptography deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY bot/requirements.txt requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim

# ffmpeg is required by yt-dlp for audio extraction and video merging
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# App code
WORKDIR /app
COPY bot/ ./bot/

# Writable download dir (mount a volume here in production for persistence)
RUN mkdir -p /downloads
VOLUME ["/downloads"]

# Non-root user for security
RUN useradd -M -s /bin/false botuser && chown botuser /downloads
USER botuser

ENV DOWNLOAD_DIR=/downloads \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "bot.main"]
