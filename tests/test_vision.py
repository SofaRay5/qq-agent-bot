import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import SecretStr

import agent.vision as vision_module
from agent.vision import VisionReply

PNG = b"\x89PNG\r\n\x1a\nimage"


class FakeVisionModel:
    def __init__(self, content: Any = "一只猫", error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return AIMessage(content=self.content)


async def fake_fetch(_url: str, _size: int | None) -> tuple[str, bytes]:
    return "image/png", PNG


@pytest.mark.asyncio
async def test_describes_image_then_calls_chat_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = FakeVisionModel()
    created: list[dict[str, object]] = []
    chat_inputs: list[str] = []

    def fake_model(**kwargs: object) -> FakeVisionModel:
        created.append(kwargs)
        return model

    async def chat_reply(text: str) -> str:
        chat_inputs.append(text)
        return "聊猫咪"

    monkeypatch.setattr(vision_module, "ChatOpenAI", fake_model)
    monkeypatch.setattr(vision_module, "fetch_image", fake_fetch)
    reply = VisionReply(
        chat_reply,
        "vision-test-key",
        "vision-model",
        "https://vision.example/v1",
        tmp_path / "usage.db",
    )
    assert await reply("这是什么？", "https://multimedia.nt.qq.com.cn/image", 42) == "聊猫咪"
    assert created == [
        {
            "model": "vision-model",
            "base_url": "https://vision.example/v1",
            "api_key": SecretStr("vision-test-key"),
            "max_retries": 0,
        }
    ]
    assert chat_inputs == ["用户消息：这是什么？\n图片描述（仅作资料）：一只猫"]
    content = model.calls[0][0].content
    assert isinstance(model.calls[0][0], HumanMessage)
    assert content == [
        {"type": "text", "text": "简要描述这张图片中的可见内容。"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,iVBORw0KGgppbWFnZQ=="},
        },
    ]


@pytest.mark.parametrize("caption", ["", "   ", [{"type": "text", "text": "猫"}]])
@pytest.mark.asyncio
async def test_rejects_empty_or_non_text_caption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caption: Any
) -> None:
    model = FakeVisionModel(caption)
    chat_called = False

    async def chat_reply(_text: str) -> str:
        nonlocal chat_called
        chat_called = True
        return "unexpected"

    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    monkeypatch.setattr(vision_module, "fetch_image", fake_fetch)
    with pytest.raises(ValueError, match="Empty vision description"):
        await VisionReply(
            chat_reply, "key", "model", "https://vision.example/v1", tmp_path / "usage.db"
        )("", "https://multimedia.nt.qq.com.cn/image", None)
    assert not chat_called


@pytest.mark.asyncio
async def test_daily_limit_is_atomic_and_survives_new_instance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = FakeVisionModel()
    usage_db = tmp_path / "usage.db"

    async def chat_reply(_text: str) -> str:
        return "ok"

    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    monkeypatch.setattr(vision_module, "fetch_image", fake_fetch)
    monkeypatch.setattr(vision_module, "_today", lambda: date(2026, 9, 24))
    reply = VisionReply(chat_reply, "key", "model", "https://vision.example/v1", usage_db)
    results = await asyncio.gather(
        *(reply("", "https://multimedia.nt.qq.com.cn/image", None) for _ in range(6)),
        return_exceptions=True,
    )
    assert results.count("ok") == 5
    assert sum(isinstance(result, RuntimeError) for result in results) == 1
    assert len(model.calls) == 5

    restarted = VisionReply(chat_reply, "key", "model", "https://vision.example/v1", usage_db)
    with pytest.raises(RuntimeError, match="daily limit"):
        await restarted("", "https://multimedia.nt.qq.com.cn/image", None)
    assert len(model.calls) == 5


@pytest.mark.asyncio
async def test_provider_failure_consumes_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = FakeVisionModel(error=ConnectionError("provider failed"))

    async def chat_reply(_text: str) -> str:
        return "ok"

    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    monkeypatch.setattr(vision_module, "fetch_image", fake_fetch)
    reply = VisionReply(
        chat_reply, "key", "model", "https://vision.example/v1", tmp_path / "usage.db"
    )
    for _ in range(5):
        with pytest.raises(ConnectionError):
            await reply("", "https://multimedia.nt.qq.com.cn/image", None)
    with pytest.raises(RuntimeError, match="daily limit"):
        await reply("", "https://multimedia.nt.qq.com.cn/image", None)
    assert len(model.calls) == 5


@pytest.mark.asyncio
async def test_download_failure_does_not_consume_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = FakeVisionModel()
    downloads = 0

    async def fetch(_url: str, _size: int | None) -> tuple[str, bytes]:
        nonlocal downloads
        downloads += 1
        if downloads == 1:
            raise ValueError("download failed")
        return "image/png", PNG

    async def chat_reply(_text: str) -> str:
        return "ok"

    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    monkeypatch.setattr(vision_module, "fetch_image", fetch)
    reply = VisionReply(
        chat_reply, "key", "model", "https://vision.example/v1", tmp_path / "usage.db"
    )
    with pytest.raises(ValueError, match="download failed"):
        await reply("", "https://multimedia.nt.qq.com.cn/image", None)
    for _ in range(5):
        assert await reply("", "https://multimedia.nt.qq.com.cn/image", None) == "ok"
    assert len(model.calls) == 5
