"""Schedule eligible OneBot messages through the groupmate coordinator."""

import asyncio
import logging

from core.groupmate import GroupmateCoordinator
from onebot_adapter.client import Event, OneBotClient
from onebot_adapter.event import GroupMessageEvent, PrivateMessageEvent

logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(
        self,
        client: OneBotClient,
        coordinator: GroupmateCoordinator,
    ) -> None:
        self.client = client
        self.coordinator = coordinator
        self._seen: dict[int, None] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def handle_event(self, event: Event) -> None:
        """Schedule each unseen message from another account."""
        if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
            return
        if event.user_id == event.self_id:
            return
        if event.message_id in self._seen:
            return
        self._seen[event.message_id] = None
        if len(self._seen) > 1024:
            del self._seen[next(iter(self._seen))]
        task = asyncio.create_task(self._process(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _process(self, event: PrivateMessageEvent | GroupMessageEvent) -> None:
        async def send(text: str) -> int | None:
            if isinstance(event, PrivateMessageEvent):
                return await self.client.send_private_message(event.user_id, text)
            return await self.client.send_group_message(event.group_id, text)

        try:
            await self.coordinator.handle(event, send)
        except Exception as exc:
            logger.error("dispatch failed: %s", type(exc).__name__)

    async def close(self) -> None:
        """Cancel and await outstanding reply tasks during shutdown."""
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.difference_update(tasks)
