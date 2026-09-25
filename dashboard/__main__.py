"""One-command local dashboard entry point."""

import asyncio
import logging
import webbrowser
from pathlib import Path

from aiohttp import web

from dashboard.app import create_app
from dashboard.runtime import BotManager

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/"
ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger("dashboard")


async def run() -> None:
    manager = BotManager(ROOT)
    runner = web.AppRunner(create_app(ROOT, manager))
    try:
        await runner.setup()
        site = web.TCPSite(runner, HOST, PORT)
        await site.start()
        webbrowser.open(URL)
        await asyncio.Event().wait()
    finally:
        await manager.stop()
        await runner.cleanup()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run())
    except OSError as exc:
        LOGGER.error("dashboard failed: %s", type(exc).__name__)


if __name__ == "__main__":
    main()
