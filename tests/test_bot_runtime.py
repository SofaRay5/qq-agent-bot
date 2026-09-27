from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import pytest

import bot_runtime as runtime_module
from bot_runtime import BotService
from config.models import Persona, PrivateSettings, ProviderSettings, Settings
from core.groupmate import GroupmateRuntime
from memory.extractor import MemoryCandidate, MemoryOperation
from memory.store import MemoryContext, MemoryScope, MemorySource, MemoryStore


def settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "continuous_window_seconds": 600,
        "window_max_attempts": 5,
        "window_max_replies": 5,
        "daily_model_calls": 50,
        "daily_proactive_calls": 5,
        "daily_vision_calls": 5,
        "proactive_mode": "off",
        "proactive_probability": 0.05,
        "minimum_reply_interval_seconds": 0.0,
        "send_delay_seconds": 0.0,
        "context_max_messages": 20,
        "context_max_characters": 6000,
    }
    return Settings.model_validate({**values, **changes})


def persona(name: str = "小薯") -> Persona:
    return Persona(
        name=name,
        description="",
        personality="",
        scenario="",
        speech_style="",
        identity_response="",
        example_dialogues=[],
    )


def provider(model: str = "chat-model") -> ProviderSettings:
    return ProviderSettings(
        provider="openai_compatible",
        base_url="https://models.example/v1",
        model=model,
        api_key="provider-key",
    )


def private(*, vision: bool = False) -> PrivateSettings:
    return PrivateSettings(
        napcat_ws_url="ws://127.0.0.1:3001/",
        napcat_access_token="napcat-token",
        chat=provider(),
        vision_enabled=vision,
        vision=provider("vision-model") if vision else ProviderSettings(),
    )


class FakeMemoryStore:
    instances: list["FakeMemoryStore"] = []
    fail_initialize = False

    def __init__(self, path: Path) -> None:
        self.path = path
        self.initialized = False
        self.instances.append(self)

    async def initialize(self) -> None:
        if self.fail_initialize:
            raise ValueError("private database detail")
        self.initialized = True


class FakeExtractor:
    instances: list["FakeExtractor"] = []

    def __init__(self, provider_value: ProviderSettings, budget: object) -> None:
        self.provider = provider_value
        self.budget = budget
        self.instances.append(self)

    async def extract(
        self,
        candidate: MemoryCandidate,
        _existing: object,
    ) -> tuple[MemoryOperation, ...]:
        return (
            MemoryOperation(
                action="create",
                scope=candidate.scope,
                kind="preference",
                content="喜欢草莓蛋糕",
                importance=3,
                source=candidate.source,
            ),
        )


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, url: str, token: str, *, on_state: object = None) -> None:
        self.url = url
        self.token = token
        self.on_state = on_state
        self.ran = False
        self.instances.append(self)

    async def run(self, _on_event: object) -> None:
        assert FakeMemoryStore.instances[0].initialized or FakeMemoryStore.fail_initialize
        self.ran = True

    async def get_image_file(self, _file: str) -> str:
        return "cached.jpg"


class FakeReply:
    def __init__(self, persona_value: Persona, provider_value: ProviderSettings, budget: object):
        self.persona = persona_value
        self.provider = provider_value
        self.budget = budget


class FakeVision:
    def __init__(self, provider_value: ProviderSettings, budget: object) -> None:
        self.provider = provider_value
        self.budget = budget


class FakeCoordinator:
    instances: list["FakeCoordinator"] = []

    def __init__(
        self,
        settings_value: Settings,
        persona_name: str,
        reply: FakeReply,
        vision: FakeVision | None,
        **kwargs: object,
    ) -> None:
        self.initial = (settings_value, persona_name, reply, vision)
        self.kwargs = kwargs
        self.replacements: list[GroupmateRuntime] = []
        self.instances.append(self)

    def replace_runtime(self, runtime: GroupmateRuntime) -> None:
        self.replacements.append(runtime)


class FakeDispatcher:
    instances: list["FakeDispatcher"] = []

    def __init__(self, client: FakeClient, coordinator: FakeCoordinator) -> None:
        self.client = client
        self.coordinator = coordinator
        self.closed = 0
        self.instances.append(self)

    def handle_event(self, _event: object) -> None:
        pass

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture(autouse=True)
def fake_components(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.instances.clear()
    FakeCoordinator.instances.clear()
    FakeDispatcher.instances.clear()
    FakeMemoryStore.instances.clear()
    FakeMemoryStore.fail_initialize = False
    FakeExtractor.instances.clear()
    monkeypatch.setattr(runtime_module, "OneBotClient", FakeClient)
    monkeypatch.setattr(runtime_module, "GroupmateReply", FakeReply)
    monkeypatch.setattr(runtime_module, "VisionDescriber", FakeVision)
    monkeypatch.setattr(runtime_module, "GroupmateCoordinator", FakeCoordinator)
    monkeypatch.setattr(runtime_module, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(runtime_module, "MemoryStore", FakeMemoryStore)
    monkeypatch.setattr(runtime_module, "MemoryExtractor", FakeExtractor)


@pytest.mark.asyncio
async def test_service_builds_runs_and_closes_existing_components(tmp_path: Path) -> None:
    states: list[str] = []
    service = BotService(tmp_path, private(), settings(), persona(), on_state=states.append)

    await service.run()
    await service.close()

    client = FakeClient.instances[0]
    coordinator = FakeCoordinator.instances[0]
    dispatcher = FakeDispatcher.instances[0]
    assert (client.url, client.token, client.on_state) == (
        "ws://127.0.0.1:3001/",
        "napcat-token",
        states.append,
    )
    assert client.ran
    assert coordinator.initial[1] == "小薯"
    assert coordinator.initial[3] is None
    assert dispatcher.closed == 1


def test_service_update_replaces_only_message_runtime(tmp_path: Path) -> None:
    service = BotService(tmp_path, private(), settings(), persona())
    client = FakeClient.instances[0]
    coordinator = FakeCoordinator.instances[0]
    updated_private = private(vision=True)
    updated_settings = settings(send_delay_seconds=2)

    service.update(updated_settings, persona("新薯"), updated_private)

    assert FakeClient.instances == [client]
    runtime = coordinator.replacements[0]
    assert runtime.settings == updated_settings
    assert runtime.persona_name == "新薯"
    assert cast(FakeReply, runtime.reply).provider == updated_private.chat
    assert cast(FakeVision, runtime.vision).provider == updated_private.vision


@pytest.mark.asyncio
async def test_memory_store_and_provider_are_assembled_and_reused(tmp_path: Path) -> None:
    errors: list[str | BaseException] = []
    initial = private()
    service = BotService(tmp_path, initial, settings(), persona(), on_error=errors.append)

    assert FakeMemoryStore.instances[0].path == tmp_path / "data/memory.db"
    assert FakeExtractor.instances[0].provider == initial.chat
    assert callable(FakeCoordinator.instances[0].kwargs["recall"])
    assert callable(FakeCoordinator.instances[0].kwargs["extract"])

    independent = initial.model_copy(update={"memory": provider("memory-model")})
    service.update(settings(), persona(), independent)

    assert len(FakeMemoryStore.instances) == 1
    assert FakeExtractor.instances[-1].provider == independent.memory
    assert FakeCoordinator.instances[0].replacements[-1].extract is not None

    await service.run()
    assert errors == []


@pytest.mark.asyncio
async def test_memory_initialization_failure_is_safe_and_chat_still_runs(tmp_path: Path) -> None:
    FakeMemoryStore.fail_initialize = True
    errors: list[str | BaseException] = []
    service = BotService(tmp_path, private(), settings(), persona(), on_error=errors.append)

    await service.run()

    assert FakeClient.instances[0].ran
    assert errors == ["memory_failed"]


@pytest.mark.asyncio
async def test_restart_reuses_sqlite_memory_without_cross_scope_leaks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_module, "MemoryStore", MemoryStore)
    source = MemorySource(message_id="10", message_time=20, excerpt="我喜欢草莓蛋糕")
    candidate = MemoryCandidate(
        scope=MemoryScope.private(1),
        text="我喜欢草莓蛋糕",
        source=source,
    )

    first = BotService(tmp_path, private(), settings(), persona())
    await first._initialize_memory()
    extract = cast(
        Callable[[tuple[MemoryCandidate, ...]], Awaitable[None]],
        FakeCoordinator.instances[-1].kwargs["extract"],
    )
    await extract((candidate,))
    await first.close()

    second = BotService(tmp_path, private(), settings(), persona())
    await second._initialize_memory()
    recall = cast(
        Callable[[MemoryContext, str], Awaitable[tuple[str, ...]]],
        FakeCoordinator.instances[-1].kwargs["recall"],
    )

    assert await recall(MemoryContext.private(1), "草莓") == ("喜欢草莓蛋糕",)
    assert await recall(MemoryContext.private(2), "草莓") == ()
    assert await recall(MemoryContext.group(9, 1), "草莓") == ()
    await second.close()
