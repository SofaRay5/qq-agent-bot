import asyncio
from typing import Any, cast

import pytest

from core.dispatcher import Dispatcher, echo_reply
from onebot_adapter.client import OneBotClient
from onebot_adapter.event import GroupMessageEvent, HeartbeatEvent, PrivateMessageEvent
from onebot_adapter.message import text_for_reply


class FakeClient:
    def __init__(self) -> None:
        self.private: list[tuple[int, str]] = []
        self.group: list[tuple[int, str]] = []
        self.fail_send = False
        self.send_attempts = 0

    async def send_private_message(self, user_id: int, text: str) -> None:
        self.send_attempts += 1
        if self.fail_send:
            raise ConnectionError("disconnected")
        self.private.append((user_id, text))

    async def send_group_message(self, group_id: int, text: str) -> None:
        self.group.append((group_id, text))


async def settle(dispatcher: Dispatcher) -> None:
    await asyncio.gather(*tuple(dispatcher._tasks))
    await dispatcher.close()


def private_event(data: dict[str, Any]) -> PrivateMessageEvent:
    return PrivateMessageEvent.model_validate(data)


def group_event(data: dict[str, Any]) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate(data)


@pytest.mark.asyncio
async def test_private_echo_and_ignored_events(
    private_message_json: dict[str, Any], heartbeat_json: dict[str, Any]
) -> None:
    client = FakeClient()
    dispatcher = Dispatcher(cast(OneBotClient, client), echo_reply)
    dispatcher.handle_event(private_event(private_message_json))
    dispatcher.handle_event(HeartbeatEvent.model_validate(heartbeat_json))
    own = {**private_message_json, "message_id": 2, "user_id": 123456}
    dispatcher.handle_event(private_event(own))
    blank = {
        **private_message_json,
        "message_id": 3,
        "message": [{"type": "text", "data": {"text": "  "}}],
    }
    dispatcher.handle_event(private_event(blank))
    await settle(dispatcher)
    assert client.private == [(111, "你好")]


@pytest.mark.parametrize("qq", ["123456", 123456])
@pytest.mark.asyncio
async def test_group_mention_uses_only_following_text(
    group_message_json: dict[str, Any], qq: str | int
) -> None:
    group_message_json["message"] = [
        {"type": "text", "data": {"text": "ignored "}},
        {"type": "at", "data": {"qq": qq}},
        {"type": "text", "data": "bad"},
        {"type": "text", "data": {"text": " hi"}},
    ]
    event = group_event(group_message_json)
    assert text_for_reply(event) == "hi"
    client = FakeClient()
    dispatcher = Dispatcher(cast(OneBotClient, client), echo_reply)
    dispatcher.handle_event(event)
    await settle(dispatcher)
    assert client.group == [(999, "hi")]


@pytest.mark.asyncio
async def test_unmentioned_and_at_all_are_ignored(group_message_json: dict[str, Any]) -> None:
    client = FakeClient()
    dispatcher = Dispatcher(cast(OneBotClient, client), echo_reply)
    dispatcher.handle_event(group_event(group_message_json))
    group_message_json["message"] = [
        {"type": "at", "data": {"qq": "all"}},
        {"type": "text", "data": {"text": "hello"}},
    ]
    dispatcher.handle_event(group_event(group_message_json))
    await settle(dispatcher)
    assert client.group == []


@pytest.mark.asyncio
async def test_dedup_window(private_message_json: dict[str, Any]) -> None:
    client = FakeClient()
    dispatcher = Dispatcher(cast(OneBotClient, client), echo_reply)
    event = private_event(private_message_json)
    dispatcher.handle_event(event)
    dispatcher.handle_event(event)
    for message_id in range(2, 1027):
        dispatcher.handle_event(private_event({**private_message_json, "message_id": message_id}))
    dispatcher.handle_event(event)
    await settle(dispatcher)
    assert len(client.private) == 1027


@pytest.mark.asyncio
async def test_reply_failure_sends_one_fallback(private_message_json: dict[str, Any]) -> None:
    async def fail_reply(_text: str) -> str:
        raise TimeoutError

    client = FakeClient()
    dispatcher = Dispatcher(cast(OneBotClient, client), fail_reply)
    dispatcher.handle_event(private_event(private_message_json))
    await settle(dispatcher)
    assert client.private == [(111, "暂时无法回复，请稍后再试")]


@pytest.mark.asyncio
async def test_send_failure_does_not_retry(private_message_json: dict[str, Any]) -> None:
    calls = 0

    async def reply(text: str) -> str:
        nonlocal calls
        calls += 1
        return text

    client = FakeClient()
    client.fail_send = True
    dispatcher = Dispatcher(cast(OneBotClient, client), reply)
    dispatcher.handle_event(private_event(private_message_json))
    await settle(dispatcher)
    assert calls == 1
    assert client.send_attempts == 1
    assert client.private == []


@pytest.mark.asyncio
async def test_close_cancels_pending_reply(private_message_json: dict[str, Any]) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow_reply(_text: str) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return ""

    client = FakeClient()
    dispatcher = Dispatcher(cast(OneBotClient, client), slow_reply)
    dispatcher.handle_event(private_event(private_message_json))
    await started.wait()
    await dispatcher.close()
    assert cancelled.is_set()
    assert client.private == []
