import logging
from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import SecretStr

import agent.vision as vision_module
from agent.groupmate import BudgetExceeded
from agent.image_fetch import ImageDownloadError
from agent.vision import VisionDescriber
from core.budget import BudgetResult, DailyBudget

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


class FakeBudget:
    def __init__(self, result: BudgetResult = "ok") -> None:
        self.result = result
        self.calls: list[str] = []

    async def reserve(self, kind: str) -> BudgetResult:
        self.calls.append(kind)
        return self.result


async def fake_fetch(_url: str, _size: int | None) -> tuple[str, bytes]:
    return "image/png", PNG


@pytest.mark.asyncio
async def test_vision_describer_returns_caption_without_chat_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeVisionModel(" 一只猫 ")
    budget = FakeBudget()
    created: list[dict[str, object]] = []

    def fake_model(**kwargs: object) -> FakeVisionModel:
        created.append(kwargs)
        return model

    monkeypatch.setattr(vision_module, "ChatOpenAI", fake_model)
    monkeypatch.setattr(vision_module, "fetch_image", fake_fetch)
    describer = VisionDescriber(
        "vision-test-key",
        "vision-model",
        "https://vision.example/v1",
        cast(DailyBudget, budget),
    )

    assert await describer("https://multimedia.nt.qq.com.cn/image", 42) == "一只猫"
    assert budget.calls == ["vision"]
    assert created == [
        {
            "model": "vision-model",
            "base_url": "https://vision.example/v1",
            "api_key": SecretStr("vision-test-key"),
            "max_retries": 0,
        }
    ]
    content = model.calls[0][0].content
    assert content == [
        {"type": "text", "text": "简要描述这张图片中的可见内容。"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,iVBORw0KGgppbWFnZQ=="},
        },
    ]


@pytest.mark.asyncio
async def test_vision_describer_reads_napcat_cached_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "cached.png"
    path.write_bytes(PNG)
    model = FakeVisionModel("一份薯条")
    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    describer = VisionDescriber(
        "key", "model", "https://vision.example/v1", cast(DailyBudget, FakeBudget())
    )

    assert await describer.describe_file(str(path), len(PNG)) == "一份薯条"


@pytest.mark.asyncio
async def test_vision_download_failure_does_not_reserve(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = FakeVisionModel()
    budget = FakeBudget()

    async def fail_fetch(_url: str, _size: int | None) -> tuple[str, bytes]:
        raise ValueError("download failed")

    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    monkeypatch.setattr(vision_module, "fetch_image", fail_fetch)
    describer = VisionDescriber(
        "key", "model", "https://vision.example/v1", cast(DailyBudget, budget)
    )

    with caplog.at_level(logging.ERROR, logger="agent.vision"):
        with pytest.raises(ImageDownloadError, match="Image download failed"):
            await describer("https://multimedia.nt.qq.com.cn/image", None)

    assert "stage=download" in caplog.text
    assert "download failed" not in caplog.text
    assert budget.calls == []
    assert model.calls == []


@pytest.mark.asyncio
async def test_denied_vision_budget_skips_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeVisionModel()
    budget = FakeBudget("vision")
    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    monkeypatch.setattr(vision_module, "fetch_image", fake_fetch)
    describer = VisionDescriber(
        "key", "model", "https://vision.example/v1", cast(DailyBudget, budget)
    )

    with pytest.raises(BudgetExceeded) as caught:
        await describer("https://multimedia.nt.qq.com.cn/image", None)

    assert caught.value.reason == "vision"
    assert budget.calls == ["vision"]
    assert model.calls == []


@pytest.mark.asyncio
async def test_vision_provider_failure_consumes_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeVisionModel(error=ConnectionError("provider failed"))
    budget = FakeBudget()
    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    monkeypatch.setattr(vision_module, "fetch_image", fake_fetch)
    describer = VisionDescriber(
        "key", "model", "https://vision.example/v1", cast(DailyBudget, budget)
    )

    with pytest.raises(ConnectionError, match="provider failed"):
        await describer("https://multimedia.nt.qq.com.cn/image", None)

    assert budget.calls == ["vision"]
    assert len(model.calls) == 1


@pytest.mark.parametrize("caption", ["", "   ", [{"type": "text", "text": "猫"}]])
@pytest.mark.asyncio
async def test_vision_describer_rejects_empty_or_non_text_caption(
    monkeypatch: pytest.MonkeyPatch,
    caption: Any,
) -> None:
    model = FakeVisionModel(caption)
    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    monkeypatch.setattr(vision_module, "fetch_image", fake_fetch)
    describer = VisionDescriber(
        "key", "model", "https://vision.example/v1", cast(DailyBudget, FakeBudget())
    )

    with pytest.raises(ValueError, match="Empty vision description"):
        await describer("https://multimedia.nt.qq.com.cn/image", None)


@pytest.mark.asyncio
async def test_invalid_vision_response_logs_only_safe_shape_metadata(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_output = "sensitive-vision-output"
    model = FakeVisionModel([{"type": "text", "text": secret_output}])
    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    monkeypatch.setattr(vision_module, "fetch_image", fake_fetch)
    describer = VisionDescriber(
        "key", "model", "https://vision.example/v1", cast(DailyBudget, FakeBudget())
    )

    with caplog.at_level(logging.ERROR, logger="agent.vision"):
        with pytest.raises(ValueError, match="Empty vision description"):
            await describer("https://multimedia.nt.qq.com.cn/image", None)

    assert "content_type=list" in caplog.text
    assert secret_output not in caplog.text


@pytest.mark.asyncio
async def test_provider_body_error_logs_only_safe_code_and_type(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_output = "sensitive-provider-message"
    error = ValueError(
        {"code": "vision_error", "type": "invalid_request_error", "message": secret_output}
    )
    model = FakeVisionModel(error=error)
    monkeypatch.setattr(vision_module, "ChatOpenAI", lambda **_kwargs: model)
    monkeypatch.setattr(vision_module, "fetch_image", fake_fetch)
    describer = VisionDescriber(
        "key", "model", "https://vision.example/v1", cast(DailyBudget, FakeBudget())
    )

    with caplog.at_level(logging.ERROR, logger="agent.vision"):
        with pytest.raises(ValueError):
            await describer("https://multimedia.nt.qq.com.cn/image", None)

    assert "code=vision_error" in caplog.text
    assert "type=invalid_request_error" in caplog.text
    assert secret_output not in caplog.text
