"""Run the NapCat LLM bot."""

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from agent.groupmate import GroupmateReply
from agent.vision import VisionDescriber
from config.models import load_persona, load_settings
from core.budget import DailyBudget
from core.dispatcher import Dispatcher
from core.groupmate import GroupmateCoordinator
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
    settings = load_settings(ROOT)
    persona = load_persona(ROOT)
    budget = DailyBudget(settings, ROOT / "data" / "model_usage.db")
    reply = GroupmateReply(persona, api_key, budget)
    vision = None
    if vision_settings is not None:
        vision_key, vision_model, vision_url = vision_settings
        vision = VisionDescriber(vision_key, vision_model, vision_url, budget)
    coordinator = GroupmateCoordinator(settings, persona.name, reply, vision)
    client = OneBotClient(ws_url, token)
    dispatcher = Dispatcher(client, coordinator)
    try:
        await client.run(dispatcher.handle_event)
    finally:
        await dispatcher.close()


def main() -> None:
    """Start the LLM bot from the command line."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
