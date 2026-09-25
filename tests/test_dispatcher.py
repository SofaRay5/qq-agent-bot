import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest

from core.dispatcher import Dispatcher
from core.groupmate import GroupmateCoordinator
from onebot_adapter.client import OneBotClient
from onebot_adapter.event import GroupMessageEvent, HeartbeatEvent, PrivateMessageEvent
from onebot_adapter.message import (
    ImageRef,
    MessageContent,
    content_for_event,
    image_for_reply,
    text_for_reply,
)


class FakeClient:
    def __init__(self) -> None:
        self.private: list[tuple[int, str]] = []
        self.group: list[tuple[int, str]] = []
        self.fail_send = False
        self.send_attempts = 0

    async def send_private_message(self, user_id: int, text: str) -> int | None:
        self.send_attempts += 1
        if self.fail_send:
            raise ConnectionError("private send detail")
        self.private.append((user_id, text))
        return 41

    async def send_group_message(self, group_id: int, text: str) -> int | None:
        self.send_attempts += 1
        if self.fail_send:
            raise ConnectionError("group send detail")
        self.group.append((group_id, text))
        return 42


class FakeCoordinator:
    def __init__(self) -> None:
        self.events: list[PrivateMessageEvent | GroupMessageEvent] = []
        self.sent_ids: list[int | None] = []
        self.started = asyncio.Event()
        self.block = False

    async def handle(
        self,
        event: PrivateMessageEvent | GroupMessageEvent,
        send: Callable[[str], Awaitable[int | None]],
    ) -> None:
        self.events.append(event)
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        self.sent_ids.append(await send("协调器回复"))


async def settle(dispatcher: Dispatcher) -> None:
    await asyncio.gather(*tuple(dispatcher._tasks))


def private_event(data: dict[str, Any]) -> PrivateMessageEvent:
    return PrivateMessageEvent.model_validate(data)


def group_event(data: dict[str, Any]) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate(data)


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        (
            [{"type": "image", "data": {"url": "https://qpic.cn/first", "file_size": "42"}}],
            ImageRef("https://qpic.cn/first", 42),
        ),
        (
            [
                {"type": "text", "data": {"text": "看看"}},
                {"type": "image", "data": {"url": "https://qpic.cn/image", "file_size": 7}},
            ],
            ImageRef("https://qpic.cn/image", 7),
        ),
        ([{"type": "image", "data": "bad"}], ImageRef("", None)),
        (
            [{"type": "image", "data": {"url": "https://qpic.cn/image", "file_size": "²"}}],
            ImageRef("https://qpic.cn/image", None),
        ),
        (
            [
                {
                    "type": "image",
                    "data": {"url": "https://qpic.cn/image", "file_size": "1" * 5000},
                }
            ],
            ImageRef("https://qpic.cn/image", None),
        ),
        (
            [
                {"type": "image", "data": {"type": "flash", "url": "https://qpic.cn/flash"}},
                {"type": "image", "data": {"url": "https://qpic.cn/ordinary", "file_size": "bad"}},
                {"type": "image", "data": {"url": "https://qpic.cn/second"}},
            ],
            ImageRef("https://qpic.cn/ordinary", None),
        ),
    ],
)
def test_private_selects_first_ordinary_image(
    private_message_json: dict[str, Any],
    segments: list[dict[str, Any]],
    expected: ImageRef,
) -> None:
    private_message_json["message"] = segments
    assert image_for_reply(private_event(private_message_json)) == expected


def test_group_image_must_follow_bot_mention(group_message_json: dict[str, Any]) -> None:
    after = "https://multimedia.nt.qq.com.cn/after"
    group_message_json["message"] = [
        {"type": "image", "data": {"url": "https://qpic.cn/before"}},
        {"type": "at", "data": {"qq": "123456"}},
        {"type": "image", "data": {"url": after, "file_size": "42"}},
    ]
    assert image_for_reply(group_event(group_message_json)) == ImageRef(after, 42)
    group_message_json["message"] = [{"type": "image", "data": {"url": after}}]
    assert image_for_reply(group_event(group_message_json)) is None


def test_content_uses_only_segments_after_bot_mention(
    group_message_json: dict[str, Any],
) -> None:
    group_message_json["message"] = [
        {"type": "text", "data": {"text": "ignored"}},
        {"type": "image", "data": {"url": "https://qpic.cn/before"}},
        {"type": "at", "data": {"qq": "123456"}},
        {"type": "reply", "data": {"id": "77"}},
        {"type": "text", "data": {"text": " hello"}},
    ]
    assert content_for_event(group_event(group_message_json)) == MessageContent(
        text="hello", image=None, mentioned=True, reply_to=77
    )


def test_content_keeps_unmentioned_group_image(group_message_json: dict[str, Any]) -> None:
    group_message_json["message"] = [
        {"type": "text", "data": {"text": " 看图 "}},
        {"type": "image", "data": {"url": "https://qpic.cn/image", "file_size": "42"}},
    ]
    event = group_event(group_message_json)
    assert content_for_event(event) == MessageContent(
        text="看图",
        image=ImageRef("https://qpic.cn/image", 42),
        mentioned=False,
        reply_to=None,
    )
    assert text_for_reply(event) is None
    assert image_for_reply(event) is None


@pytest.mark.parametrize(
    ("reply_data", "expected"),
    [
        ({"id": 88}, 88),
        ({"id": "99"}, 99),
        ({"id": True}, None),
        ({"id": "-1"}, None),
        ({"id": "not-a-number"}, None),
        ({}, None),
        ("bad", None),
    ],
)
def test_content_parses_only_valid_reply_ids(
    group_message_json: dict[str, Any],
    reply_data: object,
    expected: int | None,
) -> None:
    group_message_json["message"] = [
        {"type": "reply", "data": reply_data},
        {"type": "text", "data": {"text": "回复别人的消息"}},
    ]
    assert content_for_event(group_event(group_message_json)).reply_to == expected


def test_private_content_exposes_plain_text(private_message_json: dict[str, Any]) -> None:
    assert content_for_event(private_event(private_message_json)) == MessageContent(
        text="你好", image=None, mentioned=False, reply_to=None
    )


@pytest.mark.asyncio
async def test_dispatcher_selects_send_helper_and_returns_message_id(
    private_message_json: dict[str, Any],
    group_message_json: dict[str, Any],
) -> None:
    client = FakeClient()
    coordinator = FakeCoordinator()
    dispatcher = Dispatcher(cast(OneBotClient, client), cast(GroupmateCoordinator, coordinator))
    dispatcher.handle_event(private_event(private_message_json))
    dispatcher.handle_event(group_event(group_message_json))
    await settle(dispatcher)

    assert client.private == [(111, "协调器回复")]
    assert client.group == [(999, "协调器回复")]
    assert coordinator.sent_ids == [41, 42]


@pytest.mark.asyncio
async def test_dispatcher_ignores_non_messages_self_messages_and_duplicates(
    private_message_json: dict[str, Any],
    heartbeat_json: dict[str, Any],
) -> None:
    coordinator = FakeCoordinator()
    dispatcher = Dispatcher(
        cast(OneBotClient, FakeClient()), cast(GroupmateCoordinator, coordinator)
    )
    event = private_event(private_message_json)
    dispatcher.handle_event(HeartbeatEvent.model_validate(heartbeat_json))
    dispatcher.handle_event(private_event({**private_message_json, "user_id": 123456}))
    dispatcher.handle_event(event)
    dispatcher.handle_event(event)
    await settle(dispatcher)

    assert coordinator.events == [event]


@pytest.mark.asyncio
async def test_dispatcher_keeps_1024_message_dedup_window(
    private_message_json: dict[str, Any],
) -> None:
    coordinator = FakeCoordinator()
    dispatcher = Dispatcher(
        cast(OneBotClient, FakeClient()), cast(GroupmateCoordinator, coordinator)
    )
    first = private_event(private_message_json)
    dispatcher.handle_event(first)
    for message_id in range(2, 1027):
        dispatcher.handle_event(private_event({**private_message_json, "message_id": message_id}))
    dispatcher.handle_event(first)
    await settle(dispatcher)

    assert len(coordinator.events) == 1027


@pytest.mark.asyncio
async def test_dispatcher_isolates_send_failure_without_retry_or_detail(
    private_message_json: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeClient()
    client.fail_send = True
    dispatcher = Dispatcher(
        cast(OneBotClient, client), cast(GroupmateCoordinator, FakeCoordinator())
    )
    with caplog.at_level(logging.ERROR, logger="core.dispatcher"):
        dispatcher.handle_event(private_event(private_message_json))
        await settle(dispatcher)

    assert client.send_attempts == 1
    assert "ConnectionError" in caplog.text
    assert "private send detail" not in caplog.text


@pytest.mark.asyncio
async def test_close_cancels_and_awaits_coordinator(
    private_message_json: dict[str, Any],
) -> None:
    coordinator = FakeCoordinator()
    coordinator.block = True
    dispatcher = Dispatcher(
        cast(OneBotClient, FakeClient()), cast(GroupmateCoordinator, coordinator)
    )
    dispatcher.handle_event(private_event(private_message_json))
    await coordinator.started.wait()
    await dispatcher.close()

    assert not dispatcher._tasks
