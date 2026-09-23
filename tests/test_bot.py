import asyncio
import json
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from main import run


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
    with pytest.raises(ValueError, match="NAPCAT_WS_URL"):
        await run()


@pytest.mark.asyncio
async def test_private_echo_round_trip_and_secret_stays_out_of_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    private_message_json: dict[str, Any],
) -> None:
    message = "private-message-body"
    private_message_json["message"] = [{"type": "text", "data": {"text": message}}]
    private_message_json["raw_message"] = message
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
        bot_task = asyncio.create_task(run())
        try:
            await asyncio.wait_for(seen_action.wait(), 2)
            assert auth_headers == ["Bearer test-token"]
            assert len(actions) == 1
            assert actions[0]["action"] == "send_private_msg"
            assert actions[0]["params"] == {
                "user_id": 111,
                "message": [{"type": "text", "data": {"text": message}}],
            }
            assert "test-token" not in caplog.text
            assert message not in caplog.text
        finally:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_group_only_replies_after_bot_mention(
    monkeypatch: pytest.MonkeyPatch, group_message_json: dict[str, Any]
) -> None:
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
        bot_task = asyncio.create_task(run())
        try:
            await asyncio.wait_for(sent.wait(), 2)
            assert len(actions) == 1
            assert actions[0]["action"] == "send_group_msg"
            assert actions[0]["params"] == {
                "group_id": 999,
                "message": [{"type": "text", "data": {"text": "hello"}}],
            }
        finally:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)
