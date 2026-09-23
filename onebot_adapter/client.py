"""OneBot v11 forward WebSocket transport."""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from onebot_adapter.event import (
    GroupMessageEvent,
    HeartbeatEvent,
    PrivateMessageEvent,
    UnknownEvent,
    parse_event,
)

Event = PrivateMessageEvent | GroupMessageEvent | HeartbeatEvent | UnknownEvent
ACTION_TIMEOUT_SECONDS = 10
logger = logging.getLogger(__name__)


class OneBotActionError(Exception):
    """A OneBot action returned a failure response."""


class OneBotClient:
    def __init__(self, ws_url: str, token: str) -> None:
        self.ws_url = ws_url
        self.token = token
        self._ws: ClientConnection | None = None
        self._pending: dict[str, asyncio.Future[dict[str, object]]] = {}

    async def run(self, on_event: Callable[[Event], None]) -> None:
        """Receive events and reconnect after a dropped NapCat connection."""
        async for ws in connect(
            self.ws_url, additional_headers={"Authorization": f"Bearer {self.token}"}
        ):
            self._ws = ws
            try:
                async for raw in ws:
                    self._handle_frame(raw, on_event)
            except ConnectionClosed:
                logger.warning("NapCat connection closed")
            finally:
                self._ws = None
                self._fail_pending()

    def _handle_frame(self, raw: str | bytes, on_event: Callable[[Event], None]) -> None:
        try:
            data: Any = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Ignoring invalid JSON frame")
            return
        if not isinstance(data, dict):
            logger.warning("Ignoring non-object JSON frame")
            return
        echo = data.get("echo")
        if isinstance(echo, str):
            future = self._pending.get(echo)
            if future is not None and not future.done():
                future.set_result(data)
            return
        try:
            event = parse_event(data)
        except ValidationError:
            logger.warning("Ignoring invalid OneBot event")
            return
        on_event(event)

    def _fail_pending(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError("NapCat disconnected"))
        self._pending.clear()

    async def call_action(self, action: str, params: dict[str, object]) -> dict[str, object]:
        """Send an action and wait for the response carrying its unique echo."""
        ws = self._ws
        if ws is None:
            raise ConnectionError("NapCat is disconnected")
        echo = uuid4().hex
        future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        self._pending[echo] = future
        try:
            await ws.send(json.dumps({"action": action, "params": params, "echo": echo}))
            result = await asyncio.wait_for(future, timeout=ACTION_TIMEOUT_SECONDS)
        except ConnectionClosed as exc:
            raise ConnectionError("NapCat disconnected") from exc
        finally:
            self._pending.pop(echo, None)
            if future.done() and not future.cancelled():
                future.exception()
        if result.get("status") != "ok" or result.get("retcode") != 0:
            raise OneBotActionError("NapCat action failed")
        return result

    async def send_private_message(self, user_id: int, text: str) -> None:
        """Send a text segment to a private chat."""
        await self.call_action(
            "send_private_msg",
            {"user_id": user_id, "message": [{"type": "text", "data": {"text": text}}]},
        )

    async def send_group_message(self, group_id: int, text: str) -> None:
        """Send a text segment to a group chat."""
        await self.call_action(
            "send_group_msg",
            {"group_id": group_id, "message": [{"type": "text", "data": {"text": text}}]},
        )
