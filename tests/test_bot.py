import asyncio
import json
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

import main as bot_main
from main import run


class FakeReply:
    def __init__(self, api_key: str) -> None:
        assert api_key == "test-api-key"

    async def __call__(self, text: str) -> str:
        return f"答：{text}"


class IdleClient:
    def __init__(self, _url: str, _token: str) -> None:
        pass

    async def run(self, _on_event: object) -> None:
        pass


def set_base_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAPCAT_WS_URL", "ws://127.0.0.1:1/")
    monkeypatch.setenv("NAPCAT_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-api-key")


@pytest.mark.asyncio
async def test_vision_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    set_base_config(monkeypatch)
    monkeypatch.delenv("VISION_ENABLED", raising=False)
    monkeypatch.setattr(bot_main, "LLMReply", FakeReply)
    monkeypatch.setattr(bot_main, "OneBotClient", IdleClient)
    monkeypatch.setattr(
        bot_main,
        "VisionReply",
        lambda *_args: pytest.fail("disabled vision must not be constructed"),
        raising=False,
    )
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
    monkeypatch.setattr(bot_main, "OneBotClient", lambda *_args: pytest.fail("connected"))
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
    monkeypatch.setattr(bot_main, "OneBotClient", lambda *_args: pytest.fail("connected"))
    with pytest.raises(ValueError, match="VISION_API_BASE_URL"):
        await run()


@pytest.mark.asyncio
async def test_rejects_unknown_vision_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    set_base_config(monkeypatch)
    monkeypatch.setenv("VISION_ENABLED", "true")
    monkeypatch.setattr(bot_main, "OneBotClient", lambda *_args: pytest.fail("connected"))
    with pytest.raises(ValueError, match="VISION_ENABLED"):
        await run()


@pytest.mark.parametrize("missing", ["NAPCAT_WS_URL", "NAPCAT_ACCESS_TOKEN"])
@pytest.mark.asyncio
async def test_missing_configuration_fails_before_connect(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.setenv("NAPCAT_WS_URL", "ws://127.0.0.1:1/")
    monkeypatch.setenv("NAPCAT_ACCESS_TOKEN", "test-token")
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError, match=missing):
        await run()


@pytest.mark.parametrize(
    "url",
    ["http://localhost/", "ws://localhost/events", "ws://localhost/?token=x", "ws://localhost/#x"],
)
@pytest.mark.asyncio
async def test_rejects_non_root_websocket_url(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("NAPCAT_WS_URL", url)
    monkeypatch.setenv("NAPCAT_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-api-key")
    with pytest.raises(ValueError, match="NAPCAT_WS_URL"):
        await run()


@pytest.mark.asyncio
async def test_missing_deepseek_key_fails_before_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAPCAT_WS_URL", "ws://127.0.0.1:1/")
    monkeypatch.setenv("NAPCAT_ACCESS_TOKEN", "test-token")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        await asyncio.wait_for(run(), timeout=0.2)


@pytest.mark.asyncio
async def test_private_generated_reply_and_secret_stays_out_of_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    private_message_json: dict[str, Any],
) -> None:
    message = "private-message-body"
    private_message_json["message"] = [{"type": "text", "data": {"text": message}}]
    private_message_json["raw_message"] = message
    monkeypatch.setattr(bot_main, "LLMReply", FakeReply, raising=False)
    seen_action = asyncio.Event()
    actions: list[dict[str, Any]] = []
    auth_headers: list[str | None] = []

    async def fake_napcat(ws: ServerConnection) -> None:
        assert ws.request is not None
        auth_headers.append(ws.request.headers.get("Authorization"))
        await ws.send(json.dumps(private_message_json))
        action = json.loads(await asyncio.wait_for(ws.recv(), 2))
        actions.append(action)
        response = {"status": "ok", "retcode": 0, "data": {}, "echo": action["echo"]}
        await ws.send(json.dumps(response))
        seen_action.set()
        await ws.wait_closed()

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("NAPCAT_WS_URL", f"ws://127.0.0.1:{port}/")
        monkeypatch.setenv("NAPCAT_ACCESS_TOKEN", "test-token")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-api-key")
        bot_task = asyncio.create_task(run())
        try:
            await asyncio.wait_for(seen_action.wait(), 2)
            assert auth_headers == ["Bearer test-token"]
            assert len(actions) == 1
            assert actions[0]["action"] == "send_private_msg"
            assert actions[0]["params"] == {
                "user_id": 111,
                "message": [{"type": "text", "data": {"text": f"答：{message}"}}],
            }
            assert "test-token" not in caplog.text
            assert "test-api-key" not in caplog.text
            assert message not in caplog.text
        finally:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_group_only_replies_after_bot_mention(
    monkeypatch: pytest.MonkeyPatch, group_message_json: dict[str, Any]
) -> None:
    monkeypatch.setattr(bot_main, "LLMReply", FakeReply, raising=False)
    sent = asyncio.Event()
    actions: list[dict[str, Any]] = []

    async def fake_napcat(ws: ServerConnection) -> None:
        await ws.send(json.dumps(group_message_json))
        mentioned = {**group_message_json, "message_id": 3}
        mentioned["message"] = [
            {"type": "text", "data": {"text": "ignore"}},
            {"type": "at", "data": {"qq": "123456"}},
            {"type": "text", "data": {"text": " hello"}},
        ]
        await ws.send(json.dumps(mentioned))
        action = json.loads(await asyncio.wait_for(ws.recv(), 2))
        actions.append(action)
        response = {"status": "ok", "retcode": 0, "data": {}, "echo": action["echo"]}
        await ws.send(json.dumps(response))
        sent.set()
        await ws.wait_closed()

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("NAPCAT_WS_URL", f"ws://127.0.0.1:{port}/")
        monkeypatch.setenv("NAPCAT_ACCESS_TOKEN", "test-token")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-api-key")
        bot_task = asyncio.create_task(run())
        try:
            await asyncio.wait_for(sent.wait(), 2)
            assert len(actions) == 1
            assert actions[0]["action"] == "send_group_msg"
            assert actions[0]["params"] == {
                "group_id": 999,
                "message": [{"type": "text", "data": {"text": "答：hello"}}],
            }
        finally:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)


@pytest.mark.parametrize("failure", [TimeoutError, ValueError])
@pytest.mark.asyncio
async def test_reply_failure_falls_back_then_next_message_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    private_message_json: dict[str, Any],
    failure: type[Exception],
) -> None:
    class FailingOnceReply:
        def __init__(self, api_key: str) -> None:
            assert api_key == "test-api-key"
            self.calls = 0

        async def __call__(self, text: str) -> str:
            self.calls += 1
            if self.calls == 1:
                raise failure("Empty LLM reply")
            return f"答：{text}"

    monkeypatch.setattr(bot_main, "LLMReply", FailingOnceReply, raising=False)
    finished = asyncio.Event()
    actions: list[dict[str, Any]] = []

    async def fake_napcat(ws: ServerConnection) -> None:
        for message_id, body in [(1, "first"), (2, "second")]:
            event = {
                **private_message_json,
                "message_id": message_id,
                "message": [{"type": "text", "data": {"text": body}}],
            }
            await ws.send(json.dumps(event))
            action = json.loads(await asyncio.wait_for(ws.recv(), 2))
            actions.append(action)
            response = {"status": "ok", "retcode": 0, "data": {}, "echo": action["echo"]}
            await ws.send(json.dumps(response))
        finished.set()
        await ws.wait_closed()

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("NAPCAT_WS_URL", f"ws://127.0.0.1:{port}/")
        monkeypatch.setenv("NAPCAT_ACCESS_TOKEN", "test-token")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-api-key")
        bot_task = asyncio.create_task(run())
        try:
            await asyncio.wait_for(finished.wait(), 2)
            assert [action["params"]["message"][0]["data"]["text"] for action in actions] == [
                "暂时无法回复，请稍后再试",
                "答：second",
            ]
        finally:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_enabled_vision_replies_to_private_and_group_images(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    private_message_json: dict[str, Any],
    group_message_json: dict[str, Any],
) -> None:
    image_url = "https://multimedia.nt.qq.com.cn/image?signed=private-value"
    message_body = "secret-image-question"
    vision_calls: list[tuple[str, str, int | None]] = []

    class FakeVisionReply:
        def __init__(
            self,
            chat_reply: FakeReply,
            api_key: str,
            model: str,
            base_url: str,
            usage_db: object,
        ) -> None:
            assert isinstance(chat_reply, FakeReply)
            assert (api_key, model, base_url) == (
                "vision-key",
                "vision-model",
                "https://vision.example/v1",
            )

        async def __call__(self, text: str, url: str, size: int | None) -> str:
            vision_calls.append((text, url, size))
            return f"图答：{text or '无文字'}"

    monkeypatch.setattr(bot_main, "LLMReply", FakeReply)
    monkeypatch.setattr(bot_main, "VisionReply", FakeVisionReply, raising=False)
    finished = asyncio.Event()
    actions: list[dict[str, Any]] = []
    private_message_json["message"] = [
        {"type": "text", "data": {"text": message_body}},
        {"type": "image", "data": {"url": image_url, "file_size": "42"}},
    ]
    group_message_json["message"] = [
        {"type": "at", "data": {"qq": "123456"}},
        {"type": "image", "data": {"url": image_url}},
    ]

    async def fake_napcat(ws: ServerConnection) -> None:
        for event in (private_message_json, group_message_json):
            await ws.send(json.dumps(event))
            action = json.loads(await asyncio.wait_for(ws.recv(), 2))
            actions.append(action)
            await ws.send(
                json.dumps({"status": "ok", "retcode": 0, "data": {}, "echo": action["echo"]})
            )
        finished.set()
        await ws.wait_closed()

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        set_base_config(monkeypatch)
        monkeypatch.setenv("NAPCAT_WS_URL", f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/")
        monkeypatch.setenv("VISION_ENABLED", "1")
        monkeypatch.setenv("VISION_API_BASE_URL", "https://vision.example/v1")
        monkeypatch.setenv("VISION_MODEL", "vision-model")
        monkeypatch.setenv("VISION_API_KEY", "vision-key")
        bot_task = asyncio.create_task(run())
        try:
            await asyncio.wait_for(finished.wait(), 2)
            assert vision_calls == [
                (message_body, image_url, 42),
                ("", image_url, None),
            ]
            assert [action["action"] for action in actions] == [
                "send_private_msg",
                "send_group_msg",
            ]
            assert [action["params"]["message"][0]["data"]["text"] for action in actions] == [
                f"图答：{message_body}",
                "图答：无文字",
            ]
            for secret in (image_url, message_body, "test-token", "test-api-key", "vision-key"):
                assert secret not in caplog.text
        finally:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_vision_failure_does_not_break_later_text_reply(
    monkeypatch: pytest.MonkeyPatch, private_message_json: dict[str, Any]
) -> None:
    class FailingVisionReply:
        def __init__(self, *_args: object) -> None:
            pass

        async def __call__(self, _text: str, _url: str, _size: int | None) -> str:
            raise ValueError("bad image")

    monkeypatch.setattr(bot_main, "LLMReply", FakeReply)
    monkeypatch.setattr(bot_main, "VisionReply", FailingVisionReply, raising=False)
    finished = asyncio.Event()
    actions: list[dict[str, Any]] = []

    async def fake_napcat(ws: ServerConnection) -> None:
        image_event = {
            **private_message_json,
            "message_id": 10,
            "message": [
                {
                    "type": "image",
                    "data": {"url": "https://multimedia.nt.qq.com.cn/bad"},
                }
            ],
        }
        text_event = {
            **private_message_json,
            "message_id": 11,
            "message": [{"type": "text", "data": {"text": "still works"}}],
        }
        for event in (image_event, text_event):
            await ws.send(json.dumps(event))
            action = json.loads(await asyncio.wait_for(ws.recv(), 2))
            actions.append(action)
            await ws.send(
                json.dumps({"status": "ok", "retcode": 0, "data": {}, "echo": action["echo"]})
            )
        finished.set()
        await ws.wait_closed()

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        set_base_config(monkeypatch)
        monkeypatch.setenv("NAPCAT_WS_URL", f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/")
        monkeypatch.setenv("VISION_ENABLED", "1")
        monkeypatch.setenv("VISION_API_BASE_URL", "https://vision.example/v1")
        monkeypatch.setenv("VISION_MODEL", "vision-model")
        monkeypatch.setenv("VISION_API_KEY", "vision-key")
        bot_task = asyncio.create_task(run())
        try:
            await asyncio.wait_for(finished.wait(), 2)
            assert [action["params"]["message"][0]["data"]["text"] for action in actions] == [
                "暂时无法回复，请稍后再试",
                "答：still works",
            ]
        finally:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)
