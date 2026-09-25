"""Run the NapCat LLM bot."""

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from bot_runtime import BotService
from config.models import PrivateSettings, ProviderSettings, load_persona, load_settings

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
    vision_provider = ProviderSettings()
    if vision_enabled == "1":
        vision_provider = ProviderSettings(
            provider="openai_compatible",
            base_url=_validated_vision_url(),
            model=_required("VISION_MODEL"),
            api_key=_required("VISION_API_KEY"),
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
    private = PrivateSettings(
        napcat_ws_url=ws_url,
        napcat_access_token=token,
        chat=ProviderSettings(
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="deepseek-flash",
            api_key=api_key,
        ),
        vision_enabled=vision_enabled == "1",
        vision=vision_provider,
    )
    await BotService(ROOT, private, settings, persona).run()


def main() -> None:
    """Start the LLM bot from the command line."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
