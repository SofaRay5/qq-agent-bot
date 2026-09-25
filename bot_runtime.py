"""Reusable assembly and lifecycle for one QQ bot connection."""

from collections.abc import Callable
from pathlib import Path

from agent.groupmate import GroupmateReply
from agent.vision import VisionDescriber
from config.models import Persona, PrivateSettings, Settings
from core.budget import DailyBudget
from core.dispatcher import Dispatcher
from core.groupmate import GroupmateCoordinator, GroupmateRuntime
from onebot_adapter.client import ConnectionState, OneBotClient


class BotService:
    def __init__(
        self,
        root: Path,
        private: PrivateSettings,
        settings: Settings,
        persona: Persona,
        *,
        on_state: Callable[[ConnectionState], None] | None = None,
    ) -> None:
        private.validate_for_start()
        self._root = root
        self._client = OneBotClient(
            private.napcat_ws_url,
            private.napcat_access_token,
            on_state=on_state,
        )
        runtime = self._build_runtime(settings, persona, private)
        self._coordinator = GroupmateCoordinator(
            runtime.settings,
            runtime.persona_name,
            runtime.reply,
            runtime.vision,
            resolve_image=self._client.get_image_file,
        )
        self._dispatcher = Dispatcher(self._client, self._coordinator)
        self._closed = False

    def _build_runtime(
        self,
        settings: Settings,
        persona: Persona,
        private: PrivateSettings,
    ) -> GroupmateRuntime:
        budget = DailyBudget(settings, self._root / "data" / "model_usage.db")
        reply = GroupmateReply(persona, private.chat, budget)
        vision = VisionDescriber(private.vision, budget) if private.vision_enabled else None
        return GroupmateRuntime(settings, persona.name, reply, vision)

    async def run(self) -> None:
        """Run until cancelled or the OneBot client stops."""
        try:
            await self._client.run(self._dispatcher.handle_event)
        finally:
            await self.close()

    def update(
        self,
        settings: Settings,
        persona: Persona,
        private: PrivateSettings,
    ) -> None:
        """Replace only per-message runtime values; keep the connection and context."""
        private.validate_for_start()
        self._coordinator.replace_runtime(self._build_runtime(settings, persona, private))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._dispatcher.close()
