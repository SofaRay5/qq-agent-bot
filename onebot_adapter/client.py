"""OneBot v11 forward WebSocket transport."""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any, Literal
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
ConnectionState = Literal["connected", "reconnecting", "stopped"]
ACTION_TIMEOUT_SECONDS = 10
logger = logging.getLogger(__name__)


class OneBotActionError(Exception):
    """A OneBot action returned a failure response."""


class OneBotClient:
    def __init__(
        self,
        ws_url: str,
        token: str,
        *,
        on_state: Callable[[ConnectionState], None] | None = None,
    ) -> None:
        self.ws_url = ws_url
        self.token = token
        self._on_state = on_state
        self._ws: ClientConnection | None = None
        self._pending: dict[str, asyncio.Future[dict[str, object]]] = {}

    async def run(self, on_event: Callable[[Event], None]) -> None:
        """Receive events and reconnect after a dropped NapCat connection."""
        try:
            async for ws in connect(
                self.ws_url, additional_headers={"Authorization": f"Bearer {self.token}"}
            ):
                self._ws = ws
                self._notify_state("connected")
                try:
                    async for raw in ws:
                        self._handle_frame(raw, on_event)
                except ConnectionClosed:
                    logger.warning("NapCat connection closed")
                finally:
                    self._ws = None
                    self._fail_pending()
                    self._notify_state("reconnecting")
        finally:
            self._ws = None
            self._fail_pending()
            self._notify_state("stopped")

    def _notify_state(self, state: ConnectionState) -> None:
        if self._on_state is not None:
            self._on_state(state)

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

        async def send_and_wait() -> dict[str, object]:
            await ws.send(json.dumps({"action": action, "params": params, "echo": echo}))
            return await future

        try:
            result = await asyncio.wait_for(send_and_wait(), timeout=ACTION_TIMEOUT_SECONDS)
        except ConnectionClosed as exc:
            raise ConnectionError("NapCat disconnected") from exc
        finally:
            self._pending.pop(echo, None)
            if not future.done():
                future.cancel()
            if future.done() and not future.cancelled():
                future.exception()
        if result.get("status") != "ok" or result.get("retcode") != 0:
            raise OneBotActionError("NapCat action failed")
        return result

    async def send_private_message(self, user_id: int, text: str) -> int | None:
        """Send a private text message and return NapCat's integer message ID."""
        result = await self.call_action(
            "send_private_msg",
            {"user_id": user_id, "message": [{"type": "text", "data": {"text": text}}]},
        )
        return _message_id(result)

    async def send_group_message(self, group_id: int, text: str) -> int | None:
        """Send a group text message and return NapCat's integer message ID."""
        result = await self.call_action(
            "send_group_msg",
            {"group_id": group_id, "message": [{"type": "text", "data": {"text": text}}]},
        )
        return _message_id(result)

    async def get_image_file(self, file: str) -> str:
        """Ask NapCat to materialize one received image in its local cache."""
        result = await self.call_action("get_image", {"file": file})
        data = result.get("data")
        path = data.get("file") if isinstance(data, dict) else None
        if not isinstance(path, str) or not path:
            raise OneBotActionError("NapCat returned no image file")
        return path


def _message_id(result: dict[str, object]) -> int | None:
    data = result.get("data")
    if not isinstance(data, dict):
        return None
    value = data.get("message_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None
