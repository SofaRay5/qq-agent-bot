import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import cast

import pytest

import core.groupmate as groupmate_module
from agent.groupmate import BudgetExceeded, GroupmateReply, HistoryMessage, ReplyMode
from agent.image_fetch import ImageDownloadError
from agent.vision import VisionDescriber
from config.models import Settings
from core.groupmate import GroupmateCoordinator, GroupmateRuntime
from onebot_adapter.event import GroupMessageEvent, PrivateMessageEvent


def settings(**changes: object) -> Settings:
    values = {
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


def private_event(
    text: str,
    *,
    user_id: int = 111,
    message_id: int = 1,
    image: bool = False,
) -> PrivateMessageEvent:
    message: list[dict[str, object]] = []
    if text:
        message.append({"type": "text", "data": {"text": text}})
    if image:
        message.append(
            {
                "type": "image",
                "data": {"url": "https://qpic.cn/image", "file_size": "42"},
            }
        )
    return PrivateMessageEvent.model_validate(
        {
            "time": 1,
            "self_id": 123456,
            "post_type": "message",
            "message_type": "private",
            "sub_type": "friend",
            "message_id": message_id,
            "user_id": user_id,
            "message": message,
            "raw_message": text,
            "font": 0,
            "sender": {"user_id": user_id, "nickname": "小明"},
        }
    )


def group_event(
    text: str,
    *,
    group_id: int = 999,
    user_id: int = 111,
    message_id: int = 1,
    mention: bool = False,
    reply_to: object | None = None,
    image: bool = False,
) -> GroupMessageEvent:
    message: list[dict[str, object]] = []
    if reply_to is not None:
        message.append({"type": "reply", "data": {"id": reply_to}})
    if mention:
        message.append({"type": "at", "data": {"qq": "123456"}})
    if text:
        message.append({"type": "text", "data": {"text": text}})
    if image:
        message.append(
            {
                "type": "image",
                "data": {"url": "https://qpic.cn/image", "file_size": "42"},
            }
        )
    return GroupMessageEvent.model_validate(
        {
            "time": 1,
            "self_id": 123456,
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": message_id,
            "group_id": group_id,
            "user_id": user_id,
            "message": message,
            "raw_message": text,
            "font": 0,
            "sender": {"user_id": user_id, "nickname": "小明", "card": "群名片"},
        }
    )


@dataclass(frozen=True)
class ReplyCall:
    history: tuple[HistoryMessage, ...]
    current: str
    mode: ReplyMode
    budget_kind: str


class FakeReply:
    def __init__(self, responses: list[str | None | BaseException] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[ReplyCall] = []

    async def __call__(
        self,
        history: Sequence[HistoryMessage],
        current: str,
        mode: ReplyMode,
        budget_kind: str,
    ) -> str | None:
        self.calls.append(ReplyCall(tuple(history), current, mode, budget_kind))
        response = self.responses.pop(0) if self.responses else "回复"
        if isinstance(response, BaseException):
            raise response
        return response


class BlockingReply(FakeReply):
    def __init__(self, blocked_text: str) -> None:
        super().__init__()
        self.blocked_text = blocked_text
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(
        self,
        history: Sequence[HistoryMessage],
        current: str,
        mode: ReplyMode,
        budget_kind: str,
    ) -> str | None:
        self.calls.append(ReplyCall(tuple(history), current, mode, budget_kind))
        if self.blocked_text in current:
            self.started.set()
            await self.release.wait()
        return f"答:{current}"


class FakeVision:
    def __init__(self, responses: list[str | BaseException] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[tuple[str, int | None]] = []

    async def __call__(self, url: str, size: int | None) -> str:
        self.calls.append((url, size))
        response = self.responses.pop(0) if self.responses else "一张图片"
        if isinstance(response, BaseException):
            raise response
        return response

    async def describe_file(self, path: str, size: int | None) -> str:
        return await self(path, size)


class Clock:
    def __init__(self) -> None:
        self.value = 100.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class SendRecorder:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.next_id = 100
        self.fail_once = False

    async def __call__(self, text: str) -> int | None:
        if self.fail_once:
            self.fail_once = False
            raise ConnectionError("send failed")
        self.messages.append(text)
        self.next_id += 1
        return self.next_id


def coordinator(
    reply: FakeReply,
    *,
    config: Settings | None = None,
    vision: FakeVision | None = None,
    clock: Clock | None = None,
    random_value: Callable[[], float] = lambda: 0.0,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    resolve_image: Callable[[str], Awaitable[str]] | None = None,
) -> GroupmateCoordinator:
    active_clock = clock or Clock()
    return GroupmateCoordinator(
        config or settings(),
        "小薯",
        cast(GroupmateReply, reply),
        cast(VisionDescriber | None, vision),
        resolve_image=resolve_image,
        now=active_clock.now,
        random_value=random_value,
        sleep=sleep or active_clock.sleep,
    )


@pytest.mark.asyncio
async def test_failed_image_url_falls_back_to_napcat_cache() -> None:
    vision = FakeVision([ImageDownloadError(), "一份薯条"])
    resolved: list[str] = []

    async def resolve_image(file: str) -> str:
        resolved.append(file)
        return "/tmp/cached.jpg"

    bot = coordinator(FakeReply(["这是薯条"]), vision=vision, resolve_image=resolve_image)
    event = private_event("", image=True)
    event.message[0]["data"]["file"] = "cached.jpg"
    send = SendRecorder()

    await bot.handle(event, send)

    assert resolved == ["cached.jpg"]
    assert vision.calls == [
        ("https://qpic.cn/image", 42),
        ("/tmp/cached.jpg", 42),
    ]
    assert send.messages == ["这是薯条"]


@pytest.mark.asyncio
async def test_private_mention_name_and_inactive_group_triggers() -> None:
    reply = FakeReply()
    send = SendRecorder()
    bot = coordinator(reply)

    await bot.handle(private_event("你好"), send)
    await bot.handle(group_event("@后的内容", mention=True, group_id=1), send)
    await bot.handle(group_event("  小薯，你怎么看", group_id=2), send)
    await bot.handle(group_event("普通消息", group_id=3), send)

    assert [(call.mode, call.current) for call in reply.calls] == [
        ("direct", "[小明/111] 你好"),
        ("direct", "[群名片/111] @后的内容"),
        ("direct", "[群名片/111] 小薯，你怎么看"),
    ]


@pytest.mark.asyncio
async def test_only_recent_same_group_bot_message_id_triggers_reply() -> None:
    reply = FakeReply()
    send = SendRecorder()
    bot = coordinator(reply)

    await bot.handle(group_event("开始", mention=True, group_id=1), send)
    await bot.handle(group_event("回复机器人", reply_to=101, group_id=1), send)
    await bot.handle(group_event("回复别群", reply_to=101, group_id=2), send)
    await bot.handle(group_event("坏回复", reply_to="bad", group_id=3), send)

    assert [call.mode for call in reply.calls] == ["direct", "direct"]


@pytest.mark.asyncio
async def test_private_and_group_histories_are_isolated() -> None:
    reply = FakeReply()
    send = SendRecorder()
    bot = coordinator(reply)

    await bot.handle(private_event("甲一", user_id=1), send)
    await bot.handle(private_event("乙一", user_id=2), send)
    await bot.handle(private_event("甲二", user_id=1), send)
    assert reply.calls[1].history == ()
    assert [item.content for item in reply.calls[2].history] == ["[小明/1] 甲一", "回复"]

    await bot.handle(group_event("群一", mention=True, group_id=10), send)
    await bot.handle(group_event("群二", mention=True, group_id=20), send)
    await bot.handle(group_event("继续群一", group_id=10), send)
    assert reply.calls[4].history == ()
    assert [item.content for item in reply.calls[5].history] == [
        "[群名片/111] 群一",
        "回复",
    ]


@pytest.mark.asyncio
async def test_window_resets_expires_and_uses_continue_mode() -> None:
    clock = Clock()
    reply = FakeReply()
    send = SendRecorder()
    bot = coordinator(reply, clock=clock)

    await bot.handle(group_event("首次", mention=True), send)
    await bot.handle(group_event("持续"), send)
    assert reply.calls[1].mode == "continue"
    assert reply.calls[1].history

    await bot.handle(group_event("小薯，新话题"), send)
    assert reply.calls[2].mode == "direct"
    assert reply.calls[2].history == ()

    clock.value += 601
    await bot.handle(group_event("已经过期"), send)
    assert len(reply.calls) == 3


@pytest.mark.asyncio
async def test_silence_and_provider_failure_exhaust_window_attempts() -> None:
    reply = FakeReply([None, ConnectionError("provider failed"), "不应调用"])
    send = SendRecorder()
    bot = coordinator(
        reply,
        config=settings(window_max_attempts=2, window_max_replies=2),
    )

    await bot.handle(group_event("开始", mention=True), send)
    await bot.handle(group_event("第二次"), send)
    await bot.handle(group_event("第三次"), send)

    assert len(reply.calls) == 2
    assert send.messages == []


@pytest.mark.asyncio
async def test_successful_reply_limit_closes_window() -> None:
    reply = FakeReply()
    send = SendRecorder()
    bot = coordinator(
        reply,
        config=settings(window_max_attempts=5, window_max_replies=1),
    )

    await bot.handle(group_event("开始", mention=True), send)
    await bot.handle(group_event("不会继续"), send)

    assert len(reply.calls) == 1


@pytest.mark.asyncio
async def test_failed_send_does_not_consume_reply_count() -> None:
    reply = FakeReply(["第一次", "第二次"])
    send = SendRecorder()
    send.fail_once = True
    bot = coordinator(
        reply,
        config=settings(window_max_attempts=2, window_max_replies=1),
    )

    with pytest.raises(ConnectionError, match="send failed"):
        await bot.handle(group_event("开始", mention=True), send)
    await bot.handle(group_event("继续"), send)

    assert send.messages == ["第二次"]


@pytest.mark.asyncio
async def test_context_is_bounded_by_message_count() -> None:
    reply = FakeReply(["答一", "答二", "答三"])
    bot = coordinator(reply, config=settings(context_max_messages=2))
    send = SendRecorder()

    await bot.handle(private_event("问题一"), send)
    await bot.handle(private_event("问题二"), send)
    await bot.handle(private_event("问题三"), send)

    assert [item.content for item in reply.calls[2].history] == ["[小明/111] 问题二", "答二"]


@pytest.mark.asyncio
async def test_context_truncates_one_oversized_message() -> None:
    reply = FakeReply(["答", "再答"])
    bot = coordinator(reply, config=settings(context_max_characters=500))
    send = SendRecorder()

    await bot.handle(private_event("字" * 700), send)
    await bot.handle(private_event("下一条"), send)

    assert len(reply.calls[0].current) == 500
    assert reply.calls[1].history == (HistoryMessage("assistant", "答"),)


@pytest.mark.asyncio
async def test_explicit_trigger_waits_for_cooldown_and_send_delay() -> None:
    clock = Clock()
    reply = FakeReply()
    bot = coordinator(
        reply,
        config=settings(minimum_reply_interval_seconds=8, send_delay_seconds=1.5),
        clock=clock,
    )
    send = SendRecorder()

    await bot.handle(group_event("第一次", mention=True), send)
    await bot.handle(group_event("小薯，第二次"), send)

    assert clock.sleeps == [1.5, 8.0, 1.5]
    assert len(reply.calls) == 2


@pytest.mark.asyncio
async def test_ordinary_window_message_skips_during_cooldown() -> None:
    clock = Clock()
    reply = FakeReply()
    bot = coordinator(
        reply,
        config=settings(minimum_reply_interval_seconds=8, send_delay_seconds=1.5),
        clock=clock,
    )
    send = SendRecorder()

    await bot.handle(group_event("开始", mention=True), send)
    await bot.handle(group_event("冷却中的普通消息"), send)

    assert len(reply.calls) == 1


@pytest.mark.parametrize(
    ("mode", "random_number", "expected_mode"),
    [
        ("off", 0.0, None),
        ("random", 0.01, "random"),
        ("random", 0.9, None),
        ("topic", 0.9, "topic"),
        ("both", 0.01, "topic"),
        ("both", 0.9, None),
    ],
)
@pytest.mark.asyncio
async def test_proactive_modes(
    mode: str,
    random_number: float,
    expected_mode: str | None,
) -> None:
    reply = FakeReply()
    bot = coordinator(
        reply,
        config=settings(proactive_mode=mode),
        random_value=lambda: random_number,
    )

    await bot.handle(group_event("普通群消息"), SendRecorder())

    assert [call.mode for call in reply.calls] == ([] if expected_mode is None else [expected_mode])
    if expected_mode is not None:
        assert reply.calls[0].budget_kind == "proactive"


@pytest.mark.asyncio
async def test_same_group_is_ordered_while_other_group_proceeds() -> None:
    reply = BlockingReply("阻塞")
    bot = coordinator(reply)
    send = SendRecorder()

    first = asyncio.create_task(bot.handle(group_event("小薯，阻塞", group_id=1), send))
    await reply.started.wait()
    later = asyncio.create_task(bot.handle(group_event("小薯，后到", group_id=1), send))
    other = asyncio.create_task(bot.handle(group_event("小薯，另一群", group_id=2), send))
    await other

    assert [call.current for call in reply.calls] == [
        "[群名片/111] 小薯，阻塞",
        "[群名片/111] 小薯，另一群",
    ]

    reply.release.set()
    await asyncio.gather(first, later)
    assert send.messages == [
        "答:[群名片/111] 小薯，另一群",
        "答:[群名片/111] 小薯，阻塞",
        "答:[群名片/111] 小薯，后到",
    ]


@pytest.mark.asyncio
async def test_runtime_swap_finishes_old_request_then_preserves_history() -> None:
    old_reply = BlockingReply("第一条")
    new_reply = FakeReply()
    bot = coordinator(old_reply)
    send = SendRecorder()

    first = asyncio.create_task(bot.handle(private_event("第一条", message_id=1), send))
    await old_reply.started.wait()
    bot.replace_runtime(
        GroupmateRuntime(settings(), "小薯", cast(GroupmateReply, new_reply), None)
    )
    old_reply.release.set()
    await first
    await bot.handle(private_event("第二条", message_id=2), send)

    assert len(old_reply.calls) == 1
    assert len(new_reply.calls) == 1
    assert [item.content for item in new_reply.calls[0].history] == [
        "[小明/111] 第一条",
        "答:[小明/111] 第一条",
    ]


@pytest.mark.asyncio
async def test_runtime_swap_applies_new_settings_and_persona_name() -> None:
    clock = Clock()
    new_reply = FakeReply()
    bot = coordinator(FakeReply(), clock=clock)
    bot.replace_runtime(
        GroupmateRuntime(
            settings(send_delay_seconds=2),
            "新薯",
            cast(GroupmateReply, new_reply),
            None,
        )
    )

    await bot.handle(group_event("新薯，聊聊", group_id=9), SendRecorder())

    assert [call.mode for call in new_reply.calls] == ["direct"]
    assert clock.sleeps == [2]


@pytest.mark.asyncio
async def test_cancellation_during_model_releases_session_lock() -> None:
    reply = BlockingReply("阻塞")
    bot = coordinator(reply)
    send = SendRecorder()
    task = asyncio.create_task(bot.handle(group_event("小薯，阻塞"), send))
    await reply.started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await bot.handle(group_event("小薯，恢复"), send)

    assert send.messages == ["答:[群名片/111] 小薯，恢复"]


class BlockingSleep:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.enabled = True

    async def __call__(self, _seconds: float) -> None:
        if self.enabled:
            self.started.set()
            await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_cancellation_during_send_delay_has_no_late_send() -> None:
    delay = BlockingSleep()
    reply = FakeReply()
    bot = coordinator(reply, config=settings(send_delay_seconds=1), sleep=delay)
    send = SendRecorder()
    task = asyncio.create_task(bot.handle(group_event("小薯，阻塞发送"), send))
    await delay.started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert send.messages == []

    delay.enabled = False
    await bot.handle(group_event("小薯，恢复"), send)
    assert send.messages == ["回复"]


@pytest.mark.asyncio
async def test_model_timeout_does_not_include_human_delays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = BlockingReply("永远阻塞")
    monkeypatch.setattr(groupmate_module, "MODEL_TIMEOUT_SECONDS", 0.01)
    clock = Clock()
    bot = coordinator(reply, clock=clock)
    send = SendRecorder()

    await bot.handle(group_event("小薯，永远阻塞"), send)

    assert send.messages == ["暂时无法回复，请稍后再试"]
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_active_group_image_uses_vision_but_inactive_image_does_not() -> None:
    reply = FakeReply(["开始回复", "图片回复"])
    vision = FakeVision(["猫咪"])
    bot = coordinator(reply, vision=vision)
    send = SendRecorder()

    await bot.handle(group_event("开始", mention=True, group_id=1), send)
    await bot.handle(group_event("", image=True, group_id=1), send)
    await bot.handle(group_event("", image=True, group_id=2), send)

    assert vision.calls == [("https://qpic.cn/image", 42)]
    assert "图片描述：猫咪" in reply.calls[1].current
    assert len(reply.calls) == 2


@pytest.mark.asyncio
async def test_disabled_vision_only_notifies_eligible_images() -> None:
    reply = FakeReply()
    bot = coordinator(reply)
    send = SendRecorder()

    await bot.handle(group_event("", mention=True, image=True, group_id=1), send)
    await bot.handle(group_event("", image=True, group_id=1), send)
    await bot.handle(group_event("", image=True, group_id=2), send)

    assert send.messages == ["识图尚未开启", "识图尚未开启"]
    assert reply.calls == []


@pytest.mark.asyncio
async def test_proactive_image_stays_silent_when_vision_is_disabled() -> None:
    reply = FakeReply()
    bot = coordinator(reply, config=settings(proactive_mode="topic"))
    send = SendRecorder()

    await bot.handle(group_event("", image=True), send)

    assert send.messages == []
    assert reply.calls == []


@pytest.mark.asyncio
async def test_budget_messages_are_only_sent_for_explicit_triggers() -> None:
    reply = FakeReply(["开始", BudgetExceeded("total"), BudgetExceeded("total")])
    bot = coordinator(reply)
    send = SendRecorder()

    await bot.handle(group_event("开始", mention=True, group_id=1), send)
    await bot.handle(group_event("普通持续", group_id=1), send)
    await bot.handle(group_event("小薯，明确触发", group_id=1), send)

    assert send.messages == ["开始", "今天的聊天额度用完了，明天再聊吧"]


@pytest.mark.asyncio
async def test_vision_quota_has_specific_explicit_message() -> None:
    vision = FakeVision([BudgetExceeded("vision")])
    bot = coordinator(FakeReply(), vision=vision)
    send = SendRecorder()

    await bot.handle(group_event("", mention=True, image=True), send)

    assert send.messages == ["今天暂时不能识图了"]


@pytest.mark.asyncio
async def test_explicit_failure_falls_back_and_next_message_still_works() -> None:
    reply = FakeReply([RuntimeError("database unavailable"), "恢复回复"])
    bot = coordinator(reply)
    send = SendRecorder()

    await bot.handle(group_event("开始", mention=True), send)
    await bot.handle(group_event("继续"), send)

    assert send.messages == ["暂时无法回复，请稍后再试", "恢复回复"]


@pytest.mark.asyncio
async def test_failure_logs_only_error_class_and_session_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_body = "不应进入日志的私聊正文"
    provider_detail = "不应进入日志的服务商详情"
    bot = coordinator(FakeReply([RuntimeError(provider_detail)]))

    with caplog.at_level(logging.ERROR, logger="core.groupmate"):
        await bot.handle(private_event(private_body), SendRecorder())

    assert "RuntimeError" in caplog.text
    assert "private" in caplog.text
    assert "stage=reply" in caplog.text
    assert private_body not in caplog.text
    assert provider_detail not in caplog.text


@pytest.mark.asyncio
async def test_vision_failure_log_identifies_stage_without_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider_detail = "不应进入日志的识图错误详情"
    bot = coordinator(
        FakeReply(),
        vision=FakeVision([ValueError(provider_detail)]),
    )

    with caplog.at_level(logging.ERROR, logger="core.groupmate"):
        await bot.handle(private_event("", image=True), SendRecorder())

    assert "ValueError" in caplog.text
    assert "stage=vision" in caplog.text
    assert provider_detail not in caplog.text
