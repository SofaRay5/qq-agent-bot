import asyncio
from typing import Any, cast

import pytest

from core.dispatcher import Dispatcher, echo_reply
from onebot_adapter.client import OneBotClient
from onebot_adapter.event import GroupMessageEvent, HeartbeatEvent, PrivateMessageEvent
from onebot_adapter.message import ImageRef, image_for_reply, text_for_reply


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


@pytest.mark.asyncio
async def test_image_only_reports_vision_disabled(
    private_message_json: dict[str, Any], group_message_json: dict[str, Any]
) -> None:
    image = {"type": "image", "data": {"url": "https://qpic.cn/image"}}
    private_message_json["message"] = [image]
    group_message_json["message"] = [
        {"type": "at", "data": {"qq": "123456"}},
        image,
    ]
    client = FakeClient()
    dispatcher = Dispatcher(cast(OneBotClient, client), echo_reply)
    dispatcher.handle_event(private_event(private_message_json))
    dispatcher.handle_event(group_event(group_message_json))
    await settle(dispatcher)
    assert client.private == [(111, "识图尚未开启")]
    assert client.group == [(999, "识图尚未开启")]


@pytest.mark.asyncio
async def test_image_uses_vision_reply_with_optional_text(
    private_message_json: dict[str, Any],
) -> None:
    calls: list[tuple[str, str, int | None]] = []

    async def vision_reply(text: str, url: str, size: int | None) -> str:
        calls.append((text, url, size))
        return "看到了"

    private_message_json["message"] = [
        {"type": "text", "data": {"text": " 这是什么？ "}},
        {"type": "image", "data": {"url": "https://qpic.cn/image", "file_size": "42"}},
    ]
    client = FakeClient()
    dispatcher = Dispatcher(cast(OneBotClient, client), echo_reply, vision_reply=vision_reply)
    dispatcher.handle_event(private_event(private_message_json))
    await settle(dispatcher)
    assert calls == [("这是什么？", "https://qpic.cn/image", 42)]
    assert client.private == [(111, "看到了")]


@pytest.mark.asyncio
async def test_image_only_passes_empty_text_to_vision(private_message_json: dict[str, Any]) -> None:
    calls: list[tuple[str, str, int | None]] = []

    async def vision_reply(text: str, url: str, size: int | None) -> str:
        calls.append((text, url, size))
        return "图片"

    private_message_json["message"] = [{"type": "image", "data": {"url": "https://qpic.cn/image"}}]
    client = FakeClient()
    dispatcher = Dispatcher(cast(OneBotClient, client), echo_reply, vision_reply=vision_reply)
    dispatcher.handle_event(private_event(private_message_json))
    await settle(dispatcher)
    assert calls == [("", "https://qpic.cn/image", None)]


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
