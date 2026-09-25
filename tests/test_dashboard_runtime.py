import asyncio
from pathlib import Path

import pytest

import dashboard.runtime as runtime_module
from config.models import Persona, PrivateSettings, ProviderSettings, Settings
from dashboard.runtime import BotManager, SafeErrorBuffer


def settings() -> Settings:
    return Settings(
        continuous_window_seconds=600,
        window_max_attempts=5,
        window_max_replies=5,
        daily_model_calls=50,
        daily_proactive_calls=5,
        daily_vision_calls=5,
        proactive_mode="off",
        proactive_probability=0.05,
        minimum_reply_interval_seconds=0,
        send_delay_seconds=0,
        context_max_messages=20,
        context_max_characters=6000,
    )


def persona() -> Persona:
    return Persona(
        name="小薯",
        description="",
        personality="",
        scenario="",
        speech_style="",
        identity_response="",
        example_dialogues=[],
    )


def private() -> PrivateSettings:
    return PrivateSettings(
        napcat_ws_url="ws://127.0.0.1:3001/",
        napcat_access_token="napcat-token",
        chat=ProviderSettings(
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="deepseek-flash",
            api_key="provider-key",
        ),
    )


class FakeService:
    instances: list["FakeService"] = []

    def __init__(self, *_args: object, on_state: object = None) -> None:
        self.on_state = on_state
        self.started = asyncio.Event()
        self.closed = 0
        self.updates: list[tuple[Settings, Persona, PrivateSettings]] = []
        self.instances.append(self)

    async def run(self) -> None:
        self.started.set()
        await asyncio.Event().wait()

    async def close(self) -> None:
        self.closed += 1

    def update(
        self, settings_value: Settings, persona_value: Persona, private_value: PrivateSettings
    ) -> None:
        self.updates.append((settings_value, persona_value, private_value))


@pytest.fixture(autouse=True)
def fake_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeService.instances.clear()
    monkeypatch.setattr(runtime_module, "BotService", FakeService)


@pytest.mark.asyncio
async def test_concurrent_start_and_stop_create_and_close_one_service(tmp_path: Path) -> None:
    manager = BotManager(tmp_path)

    await asyncio.gather(*(manager.start(private(), settings(), persona()) for _ in range(4)))
    service = FakeService.instances[0]
    await service.started.wait()

    assert len(FakeService.instances) == 1
    assert manager.state == "starting"

    await asyncio.gather(manager.stop(), manager.stop())

    assert service.closed == 1
    assert str(manager.state) == "stopped"


@pytest.mark.asyncio
async def test_connection_callback_and_runtime_update_use_running_service(tmp_path: Path) -> None:
    manager = BotManager(tmp_path)
    await manager.start(private(), settings(), persona())
    service = FakeService.instances[0]
    await service.started.wait()

    assert callable(service.on_state)
    service.on_state("connected")
    assert manager.state == "connected"
    service.on_state("reconnecting")
    assert str(manager.state) == "reconnecting"

    manager.update_runtime(private(), settings(), persona())
    assert len(service.updates) == 1
    await manager.stop()


@pytest.mark.asyncio
async def test_invalid_start_never_constructs_service(tmp_path: Path) -> None:
    manager = BotManager(tmp_path)

    with pytest.raises(ValueError, match="Missing private settings"):
        await manager.start(PrivateSettings(), settings(), persona())

    assert FakeService.instances == []
    assert manager.state == "stopped"


def test_safe_error_buffer_is_bounded_and_never_keeps_exception_message() -> None:
    errors = SafeErrorBuffer()
    for index in range(25):
        errors.add("model_timeout" if index % 2 else ValueError("private-message-secret"))

    entries = errors.entries
    assert len(entries) == 20
    assert {entry.category for entry in entries} == {"model_timeout", "ValueError"}
    assert "private-message-secret" not in repr(entries)
