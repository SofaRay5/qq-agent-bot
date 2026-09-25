"""In-process bot lifecycle and safe status data."""

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from bot_runtime import BotService
from config.models import Persona, PrivateSettings, Settings
from onebot_adapter.client import ConnectionState

BotState = Literal["stopped", "starting", "connected", "reconnecting", "stopping"]
SAFE_ERROR_CATEGORIES = {
    "authentication_failed",
    "image_failed",
    "model_failed",
    "model_timeout",
    "napcat_disconnected",
}


@dataclass(frozen=True)
class SafeError:
    time: str
    category: str


class SafeErrorBuffer:
    def __init__(self) -> None:
        self._entries: deque[SafeError] = deque(maxlen=20)

    @property
    def entries(self) -> tuple[SafeError, ...]:
        return tuple(self._entries)

    def add(self, value: str | BaseException) -> None:
        if isinstance(value, str):
            category = value if value in SAFE_ERROR_CATEGORIES else "application_error"
        else:
            name = type(value).__name__
            category = name if len(name) <= 64 and name.replace("_", "").isalnum() else "Error"
        self._entries.append(
            SafeError(datetime.now().astimezone().isoformat(timespec="seconds"), category)
        )


class BotManager:
    def __init__(self, root: Path, errors: SafeErrorBuffer | None = None) -> None:
        self._root = root
        self._errors = errors or SafeErrorBuffer()
        self._lock = asyncio.Lock()
        self._service: BotService | None = None
        self._task: asyncio.Task[None] | None = None
        self._state: BotState = "stopped"

    @property
    def state(self) -> BotState:
        return self._state

    @property
    def errors(self) -> tuple[SafeError, ...]:
        return self._errors.entries

    async def start(
        self,
        private: PrivateSettings,
        settings: Settings,
        persona: Persona,
    ) -> None:
        private.validate_for_start()
        async with self._lock:
            if self._task is not None and not self._task.done():
                return
            self._state = "starting"
            try:
                service = BotService(
                    self._root,
                    private,
                    settings,
                    persona,
                    on_state=self._connection_state,
                )
            except Exception as exc:
                self._state = "stopped"
                self._errors.add(exc)
                raise
            self._service = service
            self._task = asyncio.create_task(self._run(service))

    async def _run(self, service: BotService) -> None:
        try:
            await service.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._errors.add(exc)
        finally:
            await service.close()
            if self._service is service:
                self._service = None
                self._task = None
                self._state = "stopped"

    async def stop(self) -> None:
        async with self._lock:
            task = self._task
            service = self._service
            if task is None or service is None:
                self._state = "stopped"
                return
            self._state = "stopping"
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self._service is service:
                await service.close()
                self._service = None
                self._task = None
                self._state = "stopped"

    def update_runtime(
        self,
        private: PrivateSettings,
        settings: Settings,
        persona: Persona,
    ) -> None:
        if self._service is not None:
            self._service.update(settings, persona, private)

    def _connection_state(self, state: ConnectionState) -> None:
        if self._state not in {"stopping", "stopped"}:
            self._state = state
