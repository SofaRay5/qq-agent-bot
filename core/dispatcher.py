"""Route eligible QQ messages to a plain-text reply function."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from onebot_adapter.client import Event, OneBotActionError, OneBotClient
from onebot_adapter.event import GroupMessageEvent, PrivateMessageEvent
from onebot_adapter.message import text_for_reply

logger = logging.getLogger(__name__)
FALLBACK_REPLY = "暂时无法回复，请稍后再试"


async def echo_reply(text: str) -> str:
    """Return text unchanged for the NapCat echo acceptance stage."""
    return text


class Dispatcher:
    def __init__(self, client: OneBotClient, reply: Callable[[str], Awaitable[str]]) -> None:
        self.client = client
        self.reply = reply
        self._seen: dict[int, None] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def handle_event(self, event: Event) -> None:
        """Schedule one reply for each eligible, unseen message."""
        if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
            return
        if event.user_id == event.self_id:
            return
        text = text_for_reply(event)
        if text is None or event.message_id in self._seen:
            return
        self._seen[event.message_id] = None
        if len(self._seen) > 1024:
            del self._seen[next(iter(self._seen))]
        task = asyncio.create_task(self._process(event, text))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _process(self, event: PrivateMessageEvent | GroupMessageEvent, text: str) -> None:
        try:
            answer = await asyncio.wait_for(self.reply(text), timeout=30)
        except Exception as exc:
            logger.error("reply failed: %s", type(exc).__name__)
            answer = FALLBACK_REPLY
        try:
            if isinstance(event, PrivateMessageEvent):
                await self.client.send_private_message(event.user_id, answer)
            else:
                await self.client.send_group_message(event.group_id, answer)
        except (ConnectionError, TimeoutError, OneBotActionError) as exc:
            logger.error("send failed: %s", type(exc).__name__)

    async def close(self) -> None:
        """Cancel and await outstanding reply tasks during shutdown."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
