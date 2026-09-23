"""Run the NapCat echo bot."""

import asyncio
import logging
import os
from urllib.parse import urlsplit

from core.dispatcher import Dispatcher, echo_reply
from onebot_adapter.client import OneBotClient


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing {name}")
    return value


async def run() -> None:
    """Validate NapCat settings, then run the echo bot until stopped."""
    ws_url = _required("NAPCAT_WS_URL")
    token = _required("NAPCAT_ACCESS_TOKEN")
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
    client = OneBotClient(ws_url, token)
    dispatcher = Dispatcher(client, echo_reply)
    try:
        await client.run(dispatcher.handle_event)
    finally:
        await dispatcher.close()


def main() -> None:
    """Start the echo bot from the command line."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
