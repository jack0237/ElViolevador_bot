"""
Telegram Bot API MCP Server
Exposes Telegram Bot API methods as MCP tools using httpx for HTTP calls.
Bot token is read from the TELEGRAM_BOT_TOKEN environment variable.
"""

import json
import os
import sys
import asyncio
import httpx
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

app = Server("telegram-server")

TELEGRAM_API_BASE = "https://api.telegram.org"


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _get_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN environment variable is not set. "
            "Add it to your .env file or system environment."
        )
    return token


async def _call_api(method: str, params: dict = None, files: dict = None) -> dict:
    """Make a Telegram Bot API request and return the result dict."""
    token = _get_token()
    url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"

    # Strip None values
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}

    async with httpx.AsyncClient(timeout=60) as client:
        if files:
            response = await client.post(url, data=clean_params, files=files)
        else:
            response = await client.post(url, json=clean_params)

    data = response.json()
    if not data.get("ok"):
        raise ValueError(f"Telegram API error: {data.get('description', 'Unknown error')} (code {data.get('error_code')})")
    return data.get("result")


# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions
# ─────────────────────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="tg_get_me",
            description="Get basic info about the bot (username, name, id). Tests that the bot token is valid.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="tg_get_updates",
            description=(
                "Poll for new incoming messages/updates using long-polling. "
                "Returns up to `limit` updates since `offset`. "
                "Useful for reading messages sent to the bot."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "offset": {
                        "type": "integer",
                        "description": "Identifier of the first update to be returned. Pass the last update_id + 1 to skip old updates.",
                    },
                    "limit": {"type": "integer", "description": "Max updates to return (1-100)", "default": 10},
                    "timeout": {"type": "integer", "description": "Seconds to wait for updates (long-polling). 0 = short poll.", "default": 0},
                    "allowed_updates": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of update types to receive. E.g. ['message', 'callback_query']",
                    },
                },
            },
        ),
        types.Tool(
            name="tg_send_message",
            description=(
                "Send a text message to a chat, group, channel, or user. "
                "Supports MarkdownV2 and HTML formatting. Returns the sent Message object."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"], "description": "Target chat ID or @username"},
                    "text": {"type": "string", "description": "Message text (up to 4096 characters)"},
                    "parse_mode": {
                        "type": "string",
                        "description": "Text formatting: 'MarkdownV2', 'HTML', or 'Markdown'",
                        "default": "HTML",
                    },
                    "disable_notification": {"type": "boolean", "description": "Send silently"},
                    "reply_to_message_id": {"type": "integer", "description": "ID of the message to reply to"},
                    "disable_web_page_preview": {"type": "boolean", "description": "Disable link previews"},
                },
                "required": ["chat_id", "text"],
            },
        ),
        types.Tool(
            name="tg_send_photo",
            description=(
                "Send a photo to a chat. Photo can be a URL, a file_id of a previously uploaded photo, "
                "or a local file path."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"], "description": "Target chat ID or @username"},
                    "photo": {"type": "string", "description": "URL, file_id, or local file path of the photo"},
                    "caption": {"type": "string", "description": "Photo caption (up to 1024 characters)"},
                    "parse_mode": {"type": "string", "description": "'HTML', 'MarkdownV2'"},
                    "disable_notification": {"type": "boolean"},
                },
                "required": ["chat_id", "photo"],
            },
        ),
        types.Tool(
            name="tg_send_document",
            description=(
                "Send a file/document to a chat. Accepts URL, file_id, or local file path. "
                "Files up to 50MB via URL/file, larger files need a local Bot API server."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"], "description": "Target chat ID or @username"},
                    "document": {"type": "string", "description": "URL, file_id, or local file path"},
                    "caption": {"type": "string", "description": "Document caption"},
                    "parse_mode": {"type": "string"},
                    "disable_notification": {"type": "boolean"},
                },
                "required": ["chat_id", "document"],
            },
        ),
        types.Tool(
            name="tg_send_video",
            description="Send a video file to a chat. Accepts URL, file_id, or local file path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"]},
                    "video": {"type": "string", "description": "URL, file_id, or local file path of the video"},
                    "caption": {"type": "string"},
                    "duration": {"type": "integer", "description": "Duration in seconds"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "parse_mode": {"type": "string"},
                    "disable_notification": {"type": "boolean"},
                },
                "required": ["chat_id", "video"],
            },
        ),
        types.Tool(
            name="tg_send_audio",
            description="Send an audio file (mp3/m4a/etc) to a chat. Accepts URL, file_id, or local file path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"]},
                    "audio": {"type": "string", "description": "URL, file_id, or local file path of the audio"},
                    "caption": {"type": "string"},
                    "duration": {"type": "integer"},
                    "performer": {"type": "string"},
                    "title": {"type": "string"},
                    "parse_mode": {"type": "string"},
                    "disable_notification": {"type": "boolean"},
                },
                "required": ["chat_id", "audio"],
            },
        ),
        types.Tool(
            name="tg_forward_message",
            description="Forward a message from one chat to another.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"], "description": "Target chat to forward to"},
                    "from_chat_id": {"type": ["string", "integer"], "description": "Source chat"},
                    "message_id": {"type": "integer", "description": "ID of the message to forward"},
                    "disable_notification": {"type": "boolean"},
                },
                "required": ["chat_id", "from_chat_id", "message_id"],
            },
        ),
        types.Tool(
            name="tg_edit_message_text",
            description="Edit the text of a previously sent message.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"]},
                    "message_id": {"type": "integer"},
                    "text": {"type": "string", "description": "New message text"},
                    "parse_mode": {"type": "string", "default": "HTML"},
                    "disable_web_page_preview": {"type": "boolean"},
                },
                "required": ["chat_id", "message_id", "text"],
            },
        ),
        types.Tool(
            name="tg_delete_message",
            description="Delete a message from a chat. Bot must be admin with delete_messages right in groups.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"]},
                    "message_id": {"type": "integer"},
                },
                "required": ["chat_id", "message_id"],
            },
        ),
        types.Tool(
            name="tg_pin_message",
            description="Pin a message in a chat/group/channel. Bot must be admin.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"]},
                    "message_id": {"type": "integer"},
                    "disable_notification": {"type": "boolean", "description": "Pin silently"},
                },
                "required": ["chat_id", "message_id"],
            },
        ),
        types.Tool(
            name="tg_get_chat",
            description="Get detailed information about a chat, group, supergroup, or channel.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"], "description": "Chat ID or @username"},
                },
                "required": ["chat_id"],
            },
        ),
        types.Tool(
            name="tg_kick_chat_member",
            description=(
                "Ban a user from a group, supergroup, or channel. "
                "Set until_date to 0 to ban permanently, otherwise Unix timestamp of unban time."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": ["string", "integer"]},
                    "user_id": {"type": "integer", "description": "Telegram user ID to ban"},
                    "until_date": {
                        "type": "integer",
                        "description": "Unix timestamp when ban expires. 0 = permanent.",
                        "default": 0,
                    },
                    "revoke_messages": {
                        "type": "boolean",
                        "description": "Delete all messages from the user in the chat",
                        "default": False,
                    },
                },
                "required": ["chat_id", "user_id"],
            },
        ),
        types.Tool(
            name="tg_answer_callback_query",
            description=(
                "Answer an inline keyboard callback query. "
                "You must answer within 10 seconds or the button shows 'query expired'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "callback_query_id": {"type": "string", "description": "callback_query_id from the Update"},
                    "text": {"type": "string", "description": "Notification text shown to user (0-200 chars)"},
                    "show_alert": {"type": "boolean", "description": "Show an alert dialog instead of a toast"},
                    "url": {"type": "string", "description": "URL to open when alert is confirmed"},
                    "cache_time": {"type": "integer", "description": "Seconds to cache the answer client-side"},
                },
                "required": ["callback_query_id"],
            },
        ),
        types.Tool(
            name="tg_set_webhook",
            description=(
                "Set or delete a webhook URL for the bot. "
                "Pass an empty `url` string to delete the webhook and switch back to polling."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTPS URL for the webhook. Empty string to remove."},
                    "max_connections": {"type": "integer", "description": "Max simultaneous HTTPS connections (1-100)", "default": 40},
                    "allowed_updates": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of update types to receive",
                    },
                    "drop_pending_updates": {"type": "boolean", "description": "Drop all pending updates on setting"},
                    "secret_token": {"type": "string", "description": "Secret token sent in X-Telegram-Bot-Api-Secret-Token header"},
                },
                "required": ["url"],
            },
        ),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Tool dispatch
# ─────────────────────────────────────────────────────────────────────────────

async def _send_file_tool(api_method: str, file_field: str, args: dict) -> dict:
    """Generic handler for send_photo, send_document, send_video, send_audio."""
    file_value = args[file_field]
    params = {k: v for k, v in args.items() if k != file_field}

    if os.path.isfile(file_value):
        # Upload local file
        with open(file_value, "rb") as f:
            file_bytes = f.read()
        filename = os.path.basename(file_value)
        files = {file_field: (filename, file_bytes)}
        return await _call_api(api_method, params, files=files)
    else:
        # URL or file_id
        params[file_field] = file_value
        return await _call_api(api_method, params)


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "tg_get_me":
            result = await _call_api("getMe")

        elif name == "tg_get_updates":
            result = await _call_api("getUpdates", {
                "offset": arguments.get("offset"),
                "limit": arguments.get("limit", 10),
                "timeout": arguments.get("timeout", 0),
                "allowed_updates": arguments.get("allowed_updates"),
            })

        elif name == "tg_send_message":
            result = await _call_api("sendMessage", {
                "chat_id": arguments["chat_id"],
                "text": arguments["text"],
                "parse_mode": arguments.get("parse_mode", "HTML"),
                "disable_notification": arguments.get("disable_notification"),
                "reply_to_message_id": arguments.get("reply_to_message_id"),
                "disable_web_page_preview": arguments.get("disable_web_page_preview"),
            })

        elif name == "tg_send_photo":
            result = await _send_file_tool("sendPhoto", "photo", arguments)

        elif name == "tg_send_document":
            result = await _send_file_tool("sendDocument", "document", arguments)

        elif name == "tg_send_video":
            result = await _send_file_tool("sendVideo", "video", arguments)

        elif name == "tg_send_audio":
            result = await _send_file_tool("sendAudio", "audio", arguments)

        elif name == "tg_forward_message":
            result = await _call_api("forwardMessage", {
                "chat_id": arguments["chat_id"],
                "from_chat_id": arguments["from_chat_id"],
                "message_id": arguments["message_id"],
                "disable_notification": arguments.get("disable_notification"),
            })

        elif name == "tg_edit_message_text":
            result = await _call_api("editMessageText", {
                "chat_id": arguments["chat_id"],
                "message_id": arguments["message_id"],
                "text": arguments["text"],
                "parse_mode": arguments.get("parse_mode", "HTML"),
                "disable_web_page_preview": arguments.get("disable_web_page_preview"),
            })

        elif name == "tg_delete_message":
            result = await _call_api("deleteMessage", {
                "chat_id": arguments["chat_id"],
                "message_id": arguments["message_id"],
            })

        elif name == "tg_pin_message":
            result = await _call_api("pinChatMessage", {
                "chat_id": arguments["chat_id"],
                "message_id": arguments["message_id"],
                "disable_notification": arguments.get("disable_notification"),
            })

        elif name == "tg_get_chat":
            result = await _call_api("getChat", {"chat_id": arguments["chat_id"]})

        elif name == "tg_kick_chat_member":
            result = await _call_api("banChatMember", {
                "chat_id": arguments["chat_id"],
                "user_id": arguments["user_id"],
                "until_date": arguments.get("until_date", 0),
                "revoke_messages": arguments.get("revoke_messages", False),
            })

        elif name == "tg_answer_callback_query":
            result = await _call_api("answerCallbackQuery", {
                "callback_query_id": arguments["callback_query_id"],
                "text": arguments.get("text"),
                "show_alert": arguments.get("show_alert"),
                "url": arguments.get("url"),
                "cache_time": arguments.get("cache_time"),
            })

        elif name == "tg_set_webhook":
            result = await _call_api("setWebhook", {
                "url": arguments["url"],
                "max_connections": arguments.get("max_connections", 40),
                "allowed_updates": arguments.get("allowed_updates"),
                "drop_pending_updates": arguments.get("drop_pending_updates"),
                "secret_token": arguments.get("secret_token"),
            })

        else:
            result = {"error": f"Unknown tool: {name}"}

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    if "--test" in sys.argv:
        try:
            token = _get_token()
            print(f"OK - Telegram MCP server ready (token present: ...{token[-6:]})")
        except ValueError as e:
            print(f"WARNING - {e}")
        return

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
