"""Bounded in-memory coordination for AI groupmate behavior."""

import asyncio
import logging
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from agent.groupmate import (
    BudgetExceeded,
    ChatBudgetKind,
    GroupmateReply,
    HistoryMessage,
    ReplyMode,
)
from agent.image_fetch import ImageDownloadError
from agent.vision import VisionDescriber
from config.models import Settings
from onebot_adapter.event import GroupMessageEvent, PrivateMessageEvent
from onebot_adapter.message import MessageContent, content_for_event

MODEL_TIMEOUT_SECONDS = 30.0
FALLBACK_REPLY = "暂时无法回复，请稍后再试"
TOTAL_BUDGET_REPLY = "今天的聊天额度用完了，明天再聊吧"
VISION_BUDGET_REPLY = "今天暂时不能识图了"
VISION_DISABLED_REPLY = "识图尚未开启"
logger = logging.getLogger(__name__)

Send = Callable[[str], Awaitable[int | None]]
ResolveImage = Callable[[str], Awaitable[str]]


@dataclass
class SessionState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    history: deque[HistoryMessage] = field(default_factory=deque)
    active_until: float = 0.0
    attempts: int = 0
    replies: int = 0
    last_sent_at: float | None = None
    sent_message_ids: deque[int] = field(default_factory=lambda: deque(maxlen=100))


@dataclass(frozen=True)
class GroupmateRuntime:
    settings: Settings
    persona_name: str
    reply: GroupmateReply
    vision: VisionDescriber | None


class GroupmateCoordinator:
    def __init__(
        self,
        settings: Settings,
        persona_name: str,
        reply: GroupmateReply,
        vision: VisionDescriber | None,
        *,
        resolve_image: ResolveImage | None = None,
        now: Callable[[], float] = time.monotonic,
        random_value: Callable[[], float] = random.random,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._runtime = GroupmateRuntime(settings, persona_name, reply, vision)
        self._resolve_image = resolve_image
        self._now = now
        self._random_value = random_value
        self._sleep = sleep
        self._states: dict[tuple[str, int], SessionState] = {}

    async def handle(
        self,
        event: PrivateMessageEvent | GroupMessageEvent,
        send: Send,
    ) -> None:
        """Process one message without allowing failures to mix session state."""
        runtime = self._runtime
        state = self._state_for(event)
        async with state.lock:
            await self._handle_locked(runtime, state, event, send)

    def replace_runtime(self, runtime: GroupmateRuntime) -> None:
        """Use a new immutable configuration snapshot for later messages."""
        self._runtime = runtime

    def _state_for(self, event: PrivateMessageEvent | GroupMessageEvent) -> SessionState:
        key = (
            ("private", event.user_id)
            if isinstance(event, PrivateMessageEvent)
            else ("group", event.group_id)
        )
        return self._states.setdefault(key, SessionState())

    def _deactivate(self, state: SessionState) -> None:
        state.history.clear()
        state.active_until = 0.0
        state.attempts = 0
        state.replies = 0

    def _active(self, runtime: GroupmateRuntime, state: SessionState, now: float) -> bool:
        if state.active_until <= now:
            if state.active_until:
                self._deactivate(state)
            return False
        if (
            state.attempts >= runtime.settings.window_max_attempts
            or state.replies >= runtime.settings.window_max_replies
        ):
            self._deactivate(state)
            return False
        return True

    def _is_explicit(
        self,
        runtime: GroupmateRuntime,
        state: SessionState,
        event: PrivateMessageEvent | GroupMessageEvent,
        content: MessageContent,
    ) -> bool:
        if isinstance(event, PrivateMessageEvent):
            return True
        named = content.text is not None and content.text.lstrip().startswith(runtime.persona_name)
        replied = content.reply_to is not None and content.reply_to in state.sent_message_ids
        return content.mentioned or named or replied

    def _proactive_mode(self, runtime: GroupmateRuntime) -> ReplyMode | None:
        mode = runtime.settings.proactive_mode
        if mode == "off":
            return None
        if mode in {"random", "both"}:
            if self._random_value() >= runtime.settings.proactive_probability:
                return None
            return "random" if mode == "random" else "topic"
        return "topic"

    def _label(self, event: PrivateMessageEvent | GroupMessageEvent) -> str:
        if isinstance(event, GroupMessageEvent):
            name = event.sender.card or event.sender.nickname or str(event.user_id)
        else:
            name = event.sender.nickname or str(event.user_id)
        return f"[{name}/{event.user_id}]"

    def _current(
        self,
        runtime: GroupmateRuntime,
        event: PrivateMessageEvent | GroupMessageEvent,
        content: MessageContent,
        caption: str | None = None,
    ) -> str:
        body = content.text or ("[图片]" if content.image is not None else "")
        if caption is not None:
            body = f"{content.text or ''}\n图片描述：{caption}".strip()
        return f"{self._label(event)} {body}"[: runtime.settings.context_max_characters]

    def _remember(
        self,
        runtime: GroupmateRuntime,
        state: SessionState,
        role: str,
        content: str,
    ) -> None:
        history = HistoryMessage("user" if role == "user" else "assistant", content)
        state.history.append(history)
        while (
            len(state.history) > runtime.settings.context_max_messages
            or sum(len(item.content) for item in state.history)
            > runtime.settings.context_max_characters
        ):
            state.history.popleft()

    async def _send(
        self,
        runtime: GroupmateRuntime,
        state: SessionState,
        event: PrivateMessageEvent | GroupMessageEvent,
        send: Send,
        text: str,
        *,
        remember: bool,
        count_window_reply: bool,
        delayed: bool,
    ) -> None:
        if delayed and runtime.settings.send_delay_seconds:
            await self._sleep(runtime.settings.send_delay_seconds)
        message_id = await send(text)
        state.last_sent_at = self._now()
        if remember:
            self._remember(runtime, state, "assistant", text)
        if count_window_reply:
            state.replies += 1
        if isinstance(event, GroupMessageEvent) and message_id is not None:
            state.sent_message_ids.append(message_id)

    async def _handle_locked(
        self,
        runtime: GroupmateRuntime,
        state: SessionState,
        event: PrivateMessageEvent | GroupMessageEvent,
        send: Send,
    ) -> None:
        content = content_for_event(event)
        if content.text is None and content.image is None:
            return

        now = self._now()
        is_group = isinstance(event, GroupMessageEvent)
        explicit = self._is_explicit(runtime, state, event, content)
        active = is_group and self._active(runtime, state, now)
        remember = not is_group
        count_window = False
        mode: ReplyMode
        budget_kind: ChatBudgetKind

        if is_group and explicit:
            self._deactivate(state)
            state.active_until = now + runtime.settings.continuous_window_seconds
            active = True
            remember = True
            count_window = True
            mode = "direct"
            budget_kind = "chat"
        elif active:
            remember = True
            count_window = True
            mode = "continue"
            budget_kind = "chat"
        elif is_group:
            proactive_mode = self._proactive_mode(runtime)
            if proactive_mode is None:
                return
            mode = proactive_mode
            budget_kind = "proactive"
        else:
            mode = "direct"
            budget_kind = "chat"

        current = self._current(runtime, event, content)
        if state.last_sent_at is not None:
            remaining = (
                state.last_sent_at + runtime.settings.minimum_reply_interval_seconds - self._now()
            )
            if remaining > 0:
                if explicit:
                    await self._sleep(remaining)
                else:
                    if remember:
                        self._remember(runtime, state, "user", current)
                    return

        if content.image is not None and runtime.vision is None:
            if not remember:
                return
            self._remember(runtime, state, "user", current)
            await self._send(
                runtime,
                state,
                event,
                send,
                VISION_DISABLED_REPLY,
                remember=remember,
                count_window_reply=count_window,
                delayed=False,
            )
            return

        if count_window:
            state.attempts += 1

        stage = "vision" if content.image is not None else "reply"
        try:
            if content.image is not None:
                assert runtime.vision is not None
                try:
                    caption = await asyncio.wait_for(
                        runtime.vision(content.image.url, content.image.file_size),
                        timeout=MODEL_TIMEOUT_SECONDS,
                    )
                except ImageDownloadError:
                    if self._resolve_image is None or not content.image.file:
                        raise
                    path = await self._resolve_image(content.image.file)
                    caption = await asyncio.wait_for(
                        runtime.vision.describe_file(path, content.image.file_size),
                        timeout=MODEL_TIMEOUT_SECONDS,
                    )
                current = self._current(runtime, event, content, caption)
                stage = "reply"
            answer = await asyncio.wait_for(
                runtime.reply(tuple(state.history), current, mode, budget_kind),
                timeout=MODEL_TIMEOUT_SECONDS,
            )
        except BudgetExceeded as exc:
            if remember:
                self._remember(runtime, state, "user", current)
            if not explicit:
                return
            message = VISION_BUDGET_REPLY if exc.reason == "vision" else TOTAL_BUDGET_REPLY
            await self._send(
                runtime,
                state,
                event,
                send,
                message,
                remember=remember,
                count_window_reply=count_window,
                delayed=False,
            )
            return
        except Exception as exc:
            session_type = "group" if is_group else "private"
            logger.error(
                "groupmate failed: %s session=%s stage=%s",
                type(exc).__name__,
                session_type,
                stage,
            )
            if remember:
                self._remember(runtime, state, "user", current)
            if explicit:
                await self._send(
                    runtime,
                    state,
                    event,
                    send,
                    FALLBACK_REPLY,
                    remember=remember,
                    count_window_reply=count_window,
                    delayed=False,
                )
            return

        if remember:
            self._remember(runtime, state, "user", current)
        if answer is None:
            return
        await self._send(
            runtime,
            state,
            event,
            send,
            answer,
            remember=remember,
            count_window_reply=count_window,
            delayed=True,
        )
