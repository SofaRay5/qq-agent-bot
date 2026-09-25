import asyncio
import json
from time import monotonic
from typing import Any, cast

import pytest
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.server import ServerConnection, serve

from onebot_adapter import client as client_module
from onebot_adapter.client import Event, OneBotActionError, OneBotClient
from onebot_adapter.event import HeartbeatEvent, PrivateMessageEvent


async def test_interleaved_events_and_out_of_order_actions(
    heartbeat_json: dict[str, Any], private_message_json: dict[str, Any]
) -> None:
    events: list[Event] = []
    heartbeat_seen = asyncio.Event()
    private_seen = asyncio.Event()

    def on_event(event: Event) -> None:
        events.append(event)
        if isinstance(event, HeartbeatEvent):
            heartbeat_seen.set()
        if isinstance(event, PrivateMessageEvent):
            private_seen.set()

    async def fake_napcat(ws: ServerConnection) -> None:
        await ws.send(json.dumps(heartbeat_json))
        first = json.loads(await ws.recv())
        second = json.loads(await ws.recv())
        await ws.send(
            json.dumps({"status": "ok", "retcode": 0, "data": {"n": 2}, "echo": second["echo"]})
        )
        await ws.send(json.dumps(private_message_json))
        await ws.send(
            json.dumps({"status": "ok", "retcode": 0, "data": {"n": 1}, "echo": first["echo"]})
        )

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        client = OneBotClient(f"ws://127.0.0.1:{port}/", "test-token")
        runner = asyncio.create_task(client.run(on_event))
        try:
            await asyncio.wait_for(heartbeat_seen.wait(), 2)
            first = asyncio.create_task(client.call_action("get_login_info", {}))
            second = asyncio.create_task(client.call_action("get_status", {}))
            first_result, second_result = await asyncio.wait_for(asyncio.gather(first, second), 2)
            await asyncio.wait_for(private_seen.wait(), 2)
            assert first_result["data"] == {"n": 1}
            assert second_result["data"] == {"n": 2}
            assert [type(event) for event in events] == [HeartbeatEvent, PrivateMessageEvent]
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)


async def test_action_times_out_without_a_response(
    monkeypatch: pytest.MonkeyPatch, heartbeat_json: dict[str, Any]
) -> None:
    monkeypatch.setattr(client_module, "ACTION_TIMEOUT_SECONDS", 0.02, raising=False)
    ready = asyncio.Event()

    async def fake_napcat(ws: ServerConnection) -> None:
        await ws.send(json.dumps(heartbeat_json))
        await ws.recv()
        await ws.wait_closed()

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        client = OneBotClient(f"ws://127.0.0.1:{port}/", "test-token")
        runner = asyncio.create_task(client.run(lambda event: ready.set()))
        try:
            await asyncio.wait_for(ready.wait(), 2)
            started = monotonic()
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(client.call_action("get_status", {}), 1)
            assert monotonic() - started < 0.5
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)


async def test_action_timeout_includes_blocked_send(monkeypatch: pytest.MonkeyPatch) -> None:
    class BlockingSocket:
        async def send(self, _payload: str) -> None:
            await asyncio.Event().wait()

    monkeypatch.setattr(client_module, "ACTION_TIMEOUT_SECONDS", 0.02, raising=False)
    client = OneBotClient("ws://127.0.0.1:3001/", "test-token")
    client._ws = cast(ClientConnection, BlockingSocket())

    action = asyncio.create_task(client.call_action("get_status", {}))
    try:
        await asyncio.sleep(0.1)
        assert action.done()
        with pytest.raises(TimeoutError):
            action.result()
        assert not client._pending
    finally:
        action.cancel()
        await asyncio.gather(action, return_exceptions=True)


async def test_disconnect_fails_a_pending_action(heartbeat_json: dict[str, Any]) -> None:
    ready = asyncio.Event()

    async def fake_napcat(ws: ServerConnection) -> None:
        await ws.send(json.dumps(heartbeat_json))
        await ws.recv()
        await ws.close()

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        client = OneBotClient(f"ws://127.0.0.1:{port}/", "test-token")
        runner = asyncio.create_task(client.run(lambda event: ready.set()))
        try:
            await asyncio.wait_for(ready.wait(), 2)
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(client.call_action("get_status", {}), 1)
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)


async def test_failed_action_response_raises(heartbeat_json: dict[str, Any]) -> None:
    ready = asyncio.Event()

    async def fake_napcat(ws: ServerConnection) -> None:
        await ws.send(json.dumps(heartbeat_json))
        sent = json.loads(await ws.recv())
        await ws.send(
            json.dumps({"status": "failed", "retcode": 1404, "data": None, "echo": sent["echo"]})
        )

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        client = OneBotClient(f"ws://127.0.0.1:{port}/", "test-token")
        runner = asyncio.create_task(client.run(lambda event: ready.set()))
        try:
            await asyncio.wait_for(ready.wait(), 2)
            with pytest.raises(OneBotActionError):
                await asyncio.wait_for(client.call_action("get_status", {}), 1)
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)


async def test_bad_frames_are_skipped_and_client_reconnects(
    heartbeat_json: dict[str, Any], private_message_json: dict[str, Any]
) -> None:
    seen: list[Event] = []
    private_seen = asyncio.Event()
    connections = 0

    def on_event(event: Event) -> None:
        seen.append(event)
        if isinstance(event, PrivateMessageEvent):
            private_seen.set()

    async def fake_napcat(ws: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        if connections == 1:
            await ws.send("{bad json")
            await ws.send("[]")
            incomplete = dict(private_message_json)
            del incomplete["message_id"]
            await ws.send(json.dumps(incomplete))
            await ws.send(json.dumps(heartbeat_json))
        else:
            await ws.send(json.dumps(private_message_json))
            await ws.wait_closed()

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        client = OneBotClient(f"ws://127.0.0.1:{port}/", "test-token")
        runner = asyncio.create_task(client.run(on_event))
        try:
            await asyncio.wait_for(private_seen.wait(), 2)
            assert connections >= 2
            assert [type(event) for event in seen] == [HeartbeatEvent, PrivateMessageEvent]
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)


async def test_send_helpers_use_text_segments(heartbeat_json: dict[str, Any]) -> None:
    ready = asyncio.Event()
    sent: list[dict[str, Any]] = []

    async def fake_napcat(ws: ServerConnection) -> None:
        await ws.send(json.dumps(heartbeat_json))
        for _ in range(2):
            action = json.loads(await ws.recv())
            sent.append(action)
            await ws.send(
                json.dumps(
                    {
                        "status": "ok",
                        "retcode": 0,
                        "data": {"message_id": 41},
                        "echo": action["echo"],
                    }
                )
            )
        await ws.wait_closed()

    async with serve(fake_napcat, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        client = OneBotClient(f"ws://127.0.0.1:{port}/", "test-token")
        runner = asyncio.create_task(client.run(lambda event: ready.set()))
        try:
            await asyncio.wait_for(ready.wait(), 2)
            private_id = await asyncio.wait_for(client.send_private_message(111, "你好"), 1)
            group_id = await asyncio.wait_for(client.send_group_message(999, "hi"), 1)
            assert private_id == 41
            assert group_id == 41
            assert [(action["action"], action["params"]) for action in sent] == [
                (
                    "send_private_msg",
                    {"user_id": 111, "message": [{"type": "text", "data": {"text": "你好"}}]},
                ),
                (
                    "send_group_msg",
                    {"group_id": 999, "message": [{"type": "text", "data": {"text": "hi"}}]},
                ),
            ]
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"message_id": True},
        {"message_id": "41"},
    ],
)
async def test_send_helpers_ignore_invalid_message_ids(
    monkeypatch: pytest.MonkeyPatch,
    data: object,
) -> None:
    client = OneBotClient("ws://127.0.0.1:3001/", "test-token")

    async def call_action(_action: str, _params: dict[str, object]) -> dict[str, object]:
        return {"status": "ok", "retcode": 0, "data": data}

    monkeypatch.setattr(client, "call_action", call_action)

    assert await client.send_private_message(111, "你好") is None
    assert await client.send_group_message(999, "你好") is None
