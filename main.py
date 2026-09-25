"""Run the NapCat LLM bot."""

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from agent.reply import LLMReply
from agent.vision import VisionReply
from core.dispatcher import Dispatcher
from onebot_adapter.client import OneBotClient

ROOT = Path(__file__).resolve().parent


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing {name}")
    return value


def _validated_vision_url() -> str:
    value = _required("VISION_API_BASE_URL")
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError as exc:
        raise ValueError("Invalid VISION_API_BASE_URL") from exc
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Invalid VISION_API_BASE_URL")
    return value


async def run() -> None:
    """Validate settings, then run the LLM bot until stopped."""
    ws_url = _required("NAPCAT_WS_URL")
    token = _required("NAPCAT_ACCESS_TOKEN")
    api_key = _required("DEEPSEEK_API_KEY")
    vision_enabled = os.environ.get("VISION_ENABLED", "0")
    if vision_enabled not in {"0", "1"}:
        raise ValueError("VISION_ENABLED must be 0 or 1")
    vision_settings = None
    if vision_enabled == "1":
        vision_settings = (
            _required("VISION_API_KEY"),
            _required("VISION_MODEL"),
            _validated_vision_url(),
        )
    parts = urlsplit(ws_url)
    if (
        parts.scheme not in {"ws", "wss"}
        or not parts.netloc
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise ValueError("NAPCAT_WS_URL must point to a root ws:// or wss:// endpoint")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    client = OneBotClient(ws_url, token)
    chat_reply = LLMReply(api_key)
    vision_reply = None
    if vision_settings is not None:
        vision_key, vision_model, vision_url = vision_settings
        vision_reply = VisionReply(
            chat_reply,
            vision_key,
            vision_model,
            vision_url,
            ROOT / "data" / "vision_usage.db",
        )
    dispatcher = Dispatcher(client, chat_reply, vision_reply=vision_reply)
    try:
        await client.run(dispatcher.handle_event)
    finally:
        await dispatcher.close()


def main() -> None:
    """Start the LLM bot from the command line."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
