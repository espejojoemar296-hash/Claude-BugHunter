"""Optional Telegram notifications for CBH; credentials stay outside the repository."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path


def config_path():
    return Path(os.environ.get(
        "CBH_TELEGRAM_CONFIG",
        str(Path.home() / ".config/claude-bughunter/telegram.json"),
    )).expanduser()


def _api(token, method, payload=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=12) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Telegram API rejected the request")
    return result.get("result", [])


def validate_token(token):
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", str(token).strip()):
        raise ValueError("The bot token format is invalid")
    return str(token).strip()


def get_chats(token):
    updates = _api(validate_token(token), "getUpdates")
    chats = {}
    for update in updates:
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        if chat.get("id") is not None:
            chats[str(chat["id"])] = {
                "id": str(chat["id"]),
                "type": str(chat.get("type") or ""),
                "name": str(chat.get("title") or chat.get("first_name") or "Telegram chat"),
                "username": str(chat.get("username") or ""),
            }
    return list(chats.values())


def configure(token, chat_id):
    token = validate_token(token)
    chat_id = str(chat_id).strip()
    if not re.fullmatch(r"-?\d+", chat_id):
        raise ValueError("Chat ID must be a numeric Telegram chat ID")
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"token": token, "chat_id": chat_id}) + "\n",
        encoding="utf-8",
    )
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def load_config():
    path = config_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        token = validate_token(data.get("token", ""))
        chat_id = str(data.get("chat_id", "")).strip()
        if not re.fullmatch(r"-?\d+", chat_id):
            return None
        return {"token": token, "chat_id": chat_id}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def send_message(message, config=None):
    config = config or load_config()
    if not config:
        return False
    _api(config["token"], "sendMessage", {
        "chat_id": config["chat_id"],
        "text": str(message)[:4000],
        "disable_web_page_preview": "true",
    })
    return True
