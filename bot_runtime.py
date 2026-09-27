"""Reusable assembly and lifecycle for one QQ bot connection."""

from collections.abc import Callable, Sequence
from pathlib import Path

from agent.groupmate import GroupmateReply
from agent.vision import VisionDescriber
from config.models import Persona, PrivateSettings, Settings
from core.budget import DailyBudget
from core.dispatcher import Dispatcher
from core.groupmate import GroupmateCoordinator, GroupmateRuntime
from memory.extractor import MemoryCandidate, MemoryExtractor, MemoryOperation
from memory.store import MemoryContext, MemorySource, MemoryStore
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
        on_error: Callable[[str | BaseException], None] | None = None,
    ) -> None:
        private.validate_for_start()
        self._root = root
        self._on_error = on_error
        self._memory = MemoryStore(root / "data" / "memory.db")
        self._memory_available = False
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
            recall=runtime.recall,
            extract=runtime.extract,
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
        vision = (
            VisionDescriber(private.vision_provider(), budget) if private.vision_enabled else None
        )
        extractor = MemoryExtractor(private.memory_provider(), budget)

        async def extract(candidates: tuple[MemoryCandidate, ...]) -> None:
            await self._extract_memories(extractor, candidates)

        return GroupmateRuntime(settings, persona.name, reply, vision, self._recall, extract)

    def _memory_error(self) -> None:
        if self._on_error is not None:
            self._on_error("memory_failed")

    async def _initialize_memory(self) -> None:
        try:
            await self._memory.initialize()
        except Exception:
            self._memory_available = False
            self._memory_error()
        else:
            self._memory_available = True

    async def _recall(self, context: MemoryContext, query: str) -> tuple[str, ...]:
        if not self._memory_available:
            return ()
        try:
            records = await self._memory.recall(context, query)
        except Exception:
            self._memory_error()
            return ()
        return tuple(record.version.content for record in records)

    async def _extract_memories(
        self,
        extractor: MemoryExtractor,
        candidates: tuple[MemoryCandidate, ...],
    ) -> None:
        if not self._memory_available or not candidates:
            return
        merged = _merge_candidates(candidates)
        try:
            existing = await self._memory.list_current(merged.scope)
            operations = await extractor.extract(merged, existing)
            await self._apply_operations(operations)
        except Exception:
            self._memory_error()

    async def _apply_operations(self, operations: Sequence[MemoryOperation]) -> None:
        for operation in operations:
            if operation.action == "create":
                await self._memory.create(
                    operation.scope,
                    operation.kind,
                    operation.content,
                    operation.importance,
                    operation.source,
                    "automatic",
                )
            elif operation.action == "update" and operation.target_id is not None:
                await self._memory.update(
                    operation.target_id,
                    operation.content,
                    operation.importance,
                    operation.source,
                    "automatic",
                )

    async def run(self) -> None:
        """Run until cancelled or the OneBot client stops."""
        await self._initialize_memory()
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


def _merge_candidates(candidates: tuple[MemoryCandidate, ...]) -> MemoryCandidate:
    first = candidates[0]
    text = "\n".join(candidate.text for candidate in candidates)
    excerpt = "\n".join(candidate.source.excerpt for candidate in candidates)[:300]
    last = candidates[-1].source
    return MemoryCandidate(
        scope=first.scope,
        text=text,
        source=MemorySource(last.message_id, last.message_time, excerpt),
        context=tuple(context for candidate in candidates for context in candidate.context),
    )
