import asyncio
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

import main as bot_main
from agent.groupmate import BudgetExceeded, HistoryMessage, ReplyMode
from config.models import Persona
from main import run

SETTINGS = {
    "continuous_window_seconds": 600,
    "window_max_attempts": 20,
    "window_max_replies": 20,
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
PERSONA = {
    "name": "小薯",
    "description": "private-persona-prose",
    "personality": "",
    "scenario": "",
    "speech_style": "",
    "identity_response": "",
    "example_dialogues": [],
}


def write_examples(root: Path) -> None:
    config = root / "config"
    config.mkdir()
    (config / "settings.example.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
    (config / "persona.example.json").write_text(json.dumps(PERSONA), encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_examples(tmp_path)
    monkeypatch.setattr(bot_main, "ROOT", tmp_path)


def set_base_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAPCAT_WS_URL", "ws://127.0.0.1:1/")
    monkeypatch.setenv("NAPCAT_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-api-key")
    monkeypatch.delenv("VISION_ENABLED", raising=False)


class FakeReply:
    instances: list["FakeReply"] = []

    def __init__(self, persona: Persona, api_key: str, _budget: object) -> None:
        assert persona.name == "小薯"
        assert api_key == "test-api-key"
        self.calls: list[tuple[tuple[HistoryMessage, ...], str, ReplyMode, str]] = []
        self.instances.append(self)

    async def __call__(
        self,
        history: Sequence[HistoryMessage],
        current: str,
        mode: ReplyMode,
        budget_kind: str,
    ) -> str | None:
        self.calls.append((tuple(history), current, mode, budget_kind))
        if "silent-body" in current:
            return None
        if "quota-body" in current:
            raise BudgetExceeded("total")
        return f"答：{mode}"


class FakeVision:
    instances: list["FakeVision"] = []

    def __init__(self, api_key: str, model: str, base_url: str, _budget: object) -> None:
        assert (api_key, model, base_url) == (
            "vision-key",
            "vision-model",
            "https://vision.example/v1",
        )
        self.calls: list[tuple[str, int | None]] = []
        self.instances.append(self)

    async def __call__(self, url: str, size: int | None) -> str:
        self.calls.append((url, size))
        return "一只猫"


class IdleClient:
    constructed = False

    def __init__(self, _url: str, _token: str) -> None:
        type(self).constructed = True

    async def run(self, _on_event: object) -> None:
        pass


@pytest.mark.asyncio
async def test_example_files_are_loaded_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_base_config(monkeypatch)
    FakeReply.instances.clear()
    IdleClient.constructed = False
    monkeypatch.setattr(bot_main, "GroupmateReply", FakeReply, raising=False)
    monkeypatch.setattr(bot_main, "OneBotClient", IdleClient)

    await run()

    assert FakeReply.instances
    assert IdleClient.constructed


@pytest.mark.parametrize("filename", ["settings.json", "persona.json"])
@pytest.mark.asyncio
async def test_malformed_local_file_fails_before_client_construction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, filename: str
) -> None:
    set_base_config(monkeypatch)
    (tmp_path / "config" / filename).write_text("{", encoding="utf-8")
    monkeypatch.setattr(bot_main, "OneBotClient", lambda *_args: pytest.fail("client constructed"))

    with pytest.raises(ValueError, match="Invalid"):
        await run()


@pytest.mark.parametrize("missing", ["NAPCAT_WS_URL", "NAPCAT_ACCESS_TOKEN", "DEEPSEEK_API_KEY"])
@pytest.mark.asyncio
async def test_missing_configuration_fails_before_connect(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    set_base_config(monkeypatch)
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError, match=missing):
        await run()


@pytest.mark.parametrize("missing", ["VISION_API_BASE_URL", "VISION_MODEL", "VISION_API_KEY"])
@pytest.mark.asyncio
async def test_enabled_vision_requires_all_settings_before_connect(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    set_base_config(monkeypatch)
    monkeypatch.setenv("VISION_ENABLED", "1")
    monkeypatch.setenv("VISION_API_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("VISION_MODEL", "vision-model")
    monkeypatch.setenv("VISION_API_KEY", "vision-key")
    monkeypatch.delenv(missing)
    monkeypatch.setattr(bot_main, "OneBotClient", lambda *_args: pytest.fail("client constructed"))
    with pytest.raises(ValueError, match=missing):
        await run()


@pytest.mark.parametrize(
    "url",
    [
        "http://vision.example/v1",
        "https://user:pass@vision.example/v1",
        "https://vision.example/v1?key=secret",
        "https://vision.example/v1#fragment",
        "https://vision.example:bad/v1",
    ],
)
@pytest.mark.asyncio
async def test_rejects_invalid_vision_base_url_before_connect(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    set_base_config(monkeypatch)
    monkeypatch.setenv("VISION_ENABLED", "1")
    monkeypatch.setenv("VISION_API_BASE_URL", url)
    monkeypatch.setenv("VISION_MODEL", "vision-model")
    monkeypatch.setenv("VISION_API_KEY", "vision-key")
    monkeypatch.setattr(bot_main, "OneBotClient", lambda *_args: pytest.fail("client constructed"))
    with pytest.raises(ValueError, match="VISION_API_BASE_URL"):
        await run()


@pytest.mark.asyncio
async def test_rejects_unknown_vision_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    set_base_config(monkeypatch)
    monkeypatch.setenv("VISION_ENABLED", "true")
    with pytest.raises(ValueError, match="VISION_ENABLED"):
        await run()


@pytest.mark.parametrize(
    "url", ["http://localhost/", "ws://localhost/events", "ws://localhost/?token=x"]
)
@pytest.mark.asyncio
async def test_rejects_non_root_websocket_url(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    set_base_config(monkeypatch)
    monkeypatch.setenv("NAPCAT_WS_URL", url)
    with pytest.raises(ValueError, match="NAPCAT_WS_URL"):
        await run()


def group_event(
    base: dict[str, Any], message_id: int, segments: list[dict[str, Any]]
) -> dict[str, Any]:
    return {**base, "message_id": message_id, "message": segments}


@pytest.mark.asyncio
async def test_fake_napcat_combined_groupmate_flow_and_safe_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    private_message_json: dict[str, Any],
    group_message_json: dict[str, Any],
) -> None:
    set_base_config(monkeypatch)
    monkeypatch.setenv("VISION_ENABLED", "1")
    monkeypatch.setenv("VISION_API_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("VISION_MODEL", "vision-model")
    monkeypatch.setenv("VISION_API_KEY", "vision-key")
    monkeypatch.setattr(bot_main, "GroupmateReply", FakeReply, raising=False)
    monkeypatch.setattr(bot_main, "VisionDescriber", FakeVision, raising=False)
    FakeReply.instances.clear()
    FakeVision.instances.clear()
    actions: list[dict[str, Any]] = []
    finished = asyncio.Event()
    image_url = "https://multimedia.nt.qq.com.cn/private-image-url"

    async def wait_for_calls(count: int) -> None:
        async with asyncio.timeout(2):
            while not FakeReply.instances or len(FakeReply.instances[0].calls) < count:
                await asyncio.sleep(0)

    async def fake_napcat(ws: ServerConnection) -> None:
        async def exchange(event: dict[str, Any], message_id: int) -> None:
            await ws.send(json.dumps(event))
            action = json.loads(await asyncio.wait_for(ws.recv(), 2))
            actions.append(action)
            await ws.send(
                json.dumps(
                    {
                        "status": "ok",
                        "retcode": 0,
                        "data": {"message_id": message_id},
                        "echo": action["echo"],
                    }
                )
            )

        private_one = {
            **private_message_json,
            "message_id": 101,
            "message": [{"type": "text", "data": {"text": "private-body-one"}}],
        }
        private_two = {
            **private_message_json,
            "message_id": 102,
            "message": [{"type": "text", "data": {"text": "private-body-two"}}],
        }
        await exchange(private_one, 701)
        await exchange(private_two, 702)
        await exchange(
            group_event(
                group_message_json,
                201,
                [
                    {"type": "at", "data": {"qq": "123456"}},
                    {"type": "text", "data": {"text": "mention-body"}},
                ],
            ),
            703,
        )
        await exchange(
            group_event(
                group_message_json,
                202,
                [{"type": "text", "data": {"text": "sustained-body"}}],
            ),
            704,
        )
        await exchange(
            group_event(
                group_message_json,
                203,
                [
                    {"type": "reply", "data": {"id": "703"}},
                    {"type": "text", "data": {"text": "reply-body"}},
                ],
            ),
            705,
        )
        await exchange(
            group_event(
                group_message_json,
                204,
                [{"type": "text", "data": {"text": "小薯 name-body"}}],
            ),
            706,
        )
        await ws.send(
            json.dumps(
                group_event(
                    group_message_json,
                    205,
                    [{"type": "text", "data": {"text": "silent-body"}}],
                )
            )
        )
        await wait_for_calls(7)
        await exchange(
            group_event(
                group_message_json,
                206,
                [
                    {"type": "text", "data": {"text": "image-body"}},
                    {"type": "image", "data": {"url": image_url, "file_size": "42"}},
                ],
            ),
            707,
        )
        await exchange(
            group_event(
                group_message_json,
                207,
                [{"type": "text", "data": {"text": "小薯 quota-body"}}],
            ),
            708,
        )
        await exchange(
            group_event(
                group_message_json,
                208,
                [{"type": "text", "data": {"text": "recovery-body"}}],
            ),
            709,
        )
        finished.set()
        await ws.wait_closed()

    with caplog.at_level(logging.INFO):
        async with serve(fake_napcat, "127.0.0.1", 0) as server:
            assert server.sockets
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setenv("NAPCAT_WS_URL", f"ws://127.0.0.1:{port}/")
            bot_task = asyncio.create_task(run())
            try:
                await asyncio.wait_for(finished.wait(), 3)
            finally:
                bot_task.cancel()
                await asyncio.gather(bot_task, return_exceptions=True)

    calls = FakeReply.instances[0].calls
    assert len(calls) == 10
    assert calls[1][0][-2].content.endswith("private-body-one")
    assert [call[2] for call in calls[2:6]] == [
        "direct",
        "continue",
        "direct",
        "direct",
    ]
    assert FakeVision.instances[0].calls == [(image_url, 42)]
    assert len(actions) == 9
    assert actions[-2]["params"]["message"][0]["data"]["text"] == (
        "今天的聊天额度用完了，明天再聊吧"
    )
    assert actions[-1]["params"]["message"][0]["data"]["text"] == "答：continue"
    for secret in (
        "test-token",
        "test-api-key",
        "vision-key",
        "private-persona-prose",
        "private-body-one",
        image_url,
    ):
        assert secret not in caplog.text
