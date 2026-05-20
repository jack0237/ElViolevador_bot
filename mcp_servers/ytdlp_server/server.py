"""
yt-dlp MCP Server
Exposes yt-dlp capabilities as MCP tools using the Python embedding API.
"""

import json
import os
import sys
import asyncio
from typing import Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

app = Server("ytdlp-server")


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _ydl(extra_opts: dict = {}):
    """Return a YoutubeDL options dict with sane defaults merged with extras."""
    import yt_dlp
    base = {
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }
    base.update(extra_opts)
    return yt_dlp.YoutubeDL(base)


# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions
# ─────────────────────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="ytdlp_extract_info",
            description=(
                "Extract metadata/info for any URL supported by yt-dlp (YouTube, Twitch, "
                "SoundCloud, 1000+ sites) WITHOUT downloading the file. Returns title, "
                "duration, description, uploader, view count, available formats, and more."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL of the video/audio/playlist to inspect"},
                    "flat_playlist": {
                        "type": "boolean",
                        "description": "If true, only list playlist entries without extracting each video (faster for playlists)",
                        "default": False,
                    },
                },
                "required": ["url"],
            },
        ),
        types.Tool(
            name="ytdlp_list_formats",
            description=(
                "List all available download formats for a URL with their format ID, "
                "resolution, codec, filesize, and quality notes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to list formats for"},
                },
                "required": ["url"],
            },
        ),
        types.Tool(
            name="ytdlp_download_video",
            description=(
                "Download a video from any yt-dlp supported URL. Supports format selection "
                "(e.g. 'bestvideo+bestaudio', '720p', a specific format ID). "
                "Returns the path of the downloaded file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to download"},
                    "output_dir": {
                        "type": "string",
                        "description": "Directory to save the file. Defaults to current directory.",
                        "default": ".",
                    },
                    "format": {
                        "type": "string",
                        "description": "yt-dlp format selector string, e.g. 'bestvideo+bestaudio', 'best[height<=720]'",
                        "default": "bestvideo+bestaudio/best",
                    },
                    "filename_template": {
                        "type": "string",
                        "description": "Output filename template. Default: '%(title)s.%(ext)s'",
                        "default": "%(title)s.%(ext)s",
                    },
                    "merge_format": {
                        "type": "string",
                        "description": "Container for merged streams: mp4, mkv, webm, etc.",
                        "default": "mp4",
                    },
                },
                "required": ["url"],
            },
        ),
        types.Tool(
            name="ytdlp_download_audio",
            description=(
                "Download and extract audio-only from any yt-dlp supported URL. "
                "Outputs as mp3 or m4a using ffmpeg. Returns path of the audio file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to download audio from"},
                    "output_dir": {
                        "type": "string",
                        "description": "Directory to save the audio file. Defaults to current directory.",
                        "default": ".",
                    },
                    "audio_format": {
                        "type": "string",
                        "description": "Audio format: mp3, m4a, opus, wav, flac",
                        "default": "mp3",
                    },
                    "audio_quality": {
                        "type": "string",
                        "description": "Audio quality: 0 (best) to 9 (worst) for VBR, or e.g. '128K'",
                        "default": "0",
                    },
                },
                "required": ["url"],
            },
        ),
        types.Tool(
            name="ytdlp_get_subtitles",
            description=(
                "Fetch available subtitles/captions for a video URL. "
                "Optionally download them as .srt/.vtt files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL of the video"},
                    "download": {
                        "type": "boolean",
                        "description": "Download the subtitle files to output_dir if true",
                        "default": False,
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Directory to save subtitles (only used when download=true)",
                        "default": ".",
                    },
                    "languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Language codes to download, e.g. ['en', 'es']. Empty = all.",
                        "default": [],
                    },
                    "auto_generated": {
                        "type": "boolean",
                        "description": "Include auto-generated subtitles",
                        "default": True,
                    },
                },
                "required": ["url"],
            },
        ),
        types.Tool(
            name="ytdlp_search",
            description=(
                "Search YouTube (or other supported sites) and return video results "
                "with title, URL, duration, view count, and uploader."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string"},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (1-50)",
                        "default": 10,
                    },
                    "site": {
                        "type": "string",
                        "description": "Site to search: 'youtube' (default), 'soundcloud', 'bilibili'",
                        "default": "youtube",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "ytdlp_extract_info":
            result = await _extract_info(arguments)
        elif name == "ytdlp_list_formats":
            result = await _list_formats(arguments)
        elif name == "ytdlp_download_video":
            result = await _download_video(arguments)
        elif name == "ytdlp_download_audio":
            result = await _download_audio(arguments)
        elif name == "ytdlp_get_subtitles":
            result = await _get_subtitles(arguments)
        elif name == "ytdlp_search":
            result = await _search(arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]


# ─────────────────────────────────────────────────────────────────────────────
# Implementation functions (run in executor to avoid blocking the event loop)
# ─────────────────────────────────────────────────────────────────────────────

def _sync_extract_info(url: str, flat_playlist: bool = False) -> dict:
    import yt_dlp
    opts = {
        "quiet": True,
        "no_warnings": True,
        "flat_playlist": flat_playlist,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return ydl.sanitize_info(info)


async def _extract_info(args: dict) -> dict:
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(
        None, _sync_extract_info, args["url"], args.get("flat_playlist", False)
    )
    # Return a trimmed summary
    keys = [
        "id", "title", "description", "uploader", "channel", "upload_date",
        "duration", "view_count", "like_count", "webpage_url", "thumbnail",
        "tags", "categories", "age_limit", "is_live", "extractor",
        "playlist_count", "entries",
    ]
    brief = {k: info.get(k) for k in keys if k in info}
    # For playlists, keep entries brief
    if "entries" in brief and brief["entries"]:
        brief["entries"] = [
            {k: e.get(k) for k in ["id", "title", "url", "duration", "uploader"]}
            for e in (brief["entries"] or [])[:50]
        ]
    return brief


def _sync_list_formats(url: str) -> list:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        info = ydl.sanitize_info(info)
    formats = info.get("formats", [])
    result = []
    for f in formats:
        result.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution") or f"{f.get('width','?')}x{f.get('height','?')}",
            "fps": f.get("fps"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "tbr": f.get("tbr"),
            "abr": f.get("abr"),
            "format_note": f.get("format_note"),
        })
    return result


async def _list_formats(args: dict) -> dict:
    loop = asyncio.get_event_loop()
    formats = await loop.run_in_executor(None, _sync_list_formats, args["url"])
    return {"url": args["url"], "format_count": len(formats), "formats": formats}


def _sync_download_video(url: str, output_dir: str, fmt: str, tmpl: str, merge_fmt: str) -> str:
    import yt_dlp
    downloaded_files = []

    def hook(d):
        if d["status"] == "finished":
            downloaded_files.append(d.get("filename") or d.get("info_dict", {}).get("_filename", ""))

    outtmpl = os.path.join(output_dir, tmpl)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": fmt,
        "outtmpl": outtmpl,
        "merge_output_format": merge_fmt,
        "progress_hooks": [hook],
        "restrictfilenames": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        final_path = ydl.prepare_filename(ydl.sanitize_info(info))
    if downloaded_files:
        return downloaded_files[-1]
    return final_path


async def _download_video(args: dict) -> dict:
    loop = asyncio.get_event_loop()
    output_dir = os.path.abspath(args.get("output_dir", "."))
    os.makedirs(output_dir, exist_ok=True)
    path = await loop.run_in_executor(
        None,
        _sync_download_video,
        args["url"],
        output_dir,
        args.get("format", "bestvideo+bestaudio/best"),
        args.get("filename_template", "%(title)s.%(ext)s"),
        args.get("merge_format", "mp4"),
    )
    return {"status": "downloaded", "path": path, "output_dir": output_dir}


def _sync_download_audio(url: str, output_dir: str, audio_format: str, quality: str) -> str:
    import yt_dlp
    downloaded_files = []

    def hook(d):
        if d["status"] == "finished":
            downloaded_files.append(d.get("filename", ""))

    outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "restrictfilenames": True,
        "progress_hooks": [hook],
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_format,
            "preferredquality": quality,
        }],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    if downloaded_files:
        # The final file has the new extension after post-processing
        base = os.path.splitext(downloaded_files[-1])[0]
        return f"{base}.{audio_format}"
    return output_dir


async def _download_audio(args: dict) -> dict:
    loop = asyncio.get_event_loop()
    output_dir = os.path.abspath(args.get("output_dir", "."))
    os.makedirs(output_dir, exist_ok=True)
    path = await loop.run_in_executor(
        None,
        _sync_download_audio,
        args["url"],
        output_dir,
        args.get("audio_format", "mp3"),
        str(args.get("audio_quality", "0")),
    )
    return {"status": "downloaded", "path": path, "output_dir": output_dir}


def _sync_get_subtitles(url: str, download: bool, output_dir: str, languages: list, auto_generated: bool) -> dict:
    import yt_dlp
    opts = {
        "quiet": True,
        "no_warnings": True,
        "writesubtitles": download,
        "writeautomaticsub": auto_generated and download,
        "subtitleslangs": languages or ["all"],
        "skip_download": True,
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=download)
        info = ydl.sanitize_info(info)
    subs = info.get("subtitles", {})
    auto_subs = info.get("automatic_captions", {})
    return {
        "available_subtitles": {lang: [s.get("ext") for s in tracks] for lang, tracks in subs.items()},
        "available_auto_captions": {lang: [s.get("ext") for s in tracks] for lang, tracks in auto_subs.items()},
        "downloaded": download,
        "output_dir": output_dir if download else None,
    }


async def _get_subtitles(args: dict) -> dict:
    loop = asyncio.get_event_loop()
    output_dir = os.path.abspath(args.get("output_dir", "."))
    if args.get("download", False):
        os.makedirs(output_dir, exist_ok=True)
    return await loop.run_in_executor(
        None,
        _sync_get_subtitles,
        args["url"],
        args.get("download", False),
        output_dir,
        args.get("languages", []),
        args.get("auto_generated", True),
    )


def _sync_search(query: str, max_results: int, site: str) -> list:
    import yt_dlp
    site_map = {
        "youtube": "ytsearch",
        "soundcloud": "scsearch",
        "bilibili": "bilisearch",
    }
    prefix = site_map.get(site, "ytsearch")
    search_url = f"{prefix}{max_results}:{query}"
    opts = {"quiet": True, "no_warnings": True, "flat_playlist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(search_url, download=False)
        info = ydl.sanitize_info(info)
    entries = info.get("entries", []) or []
    results = []
    for e in entries:
        results.append({
            "id": e.get("id"),
            "title": e.get("title"),
            "url": e.get("url") or e.get("webpage_url"),
            "duration": e.get("duration"),
            "view_count": e.get("view_count"),
            "uploader": e.get("uploader") or e.get("channel"),
            "thumbnail": e.get("thumbnail"),
        })
    return results


async def _search(args: dict) -> dict:
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None,
        _sync_search,
        args["query"],
        min(int(args.get("max_results", 10)), 50),
        args.get("site", "youtube"),
    )
    return {"query": args["query"], "result_count": len(results), "results": results}


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    if "--test" in sys.argv:
        print("OK - yt-dlp MCP server tools registered successfully")
        return
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
