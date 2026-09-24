from typing import Any

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from agent import reply as reply_module
from agent.reply import LLMReply


class FakeModel:
    def __init__(self, answers: list[AIMessage]) -> None:
        self.answers = iter(answers)
        self.states: list[dict[str, object]] = []

    async def ainvoke(self, messages: list[dict[str, str]]) -> AIMessage:
        self.states.append({"messages": messages})
        return next(self.answers)


@pytest.mark.asyncio
async def test_reuses_one_model_for_separate_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel([AIMessage(content="你好呀"), AIMessage(content="再见")])
    created: list[dict[str, object]] = []

    def fake_chat_openai(**kwargs: object) -> FakeModel:
        created.append(kwargs)
        return model

    monkeypatch.setattr(reply_module, "ChatOpenAI", fake_chat_openai, raising=False)
    reply = LLMReply("deepseek-test-key")

    assert await reply("你好") == "你好呀"
    assert await reply("再见") == "再见"
    assert created == [
        {
            "model": "deepseek-flash",
            "base_url": "https://api.deepseek.com",
            "api_key": SecretStr("deepseek-test-key"),
            "extra_body": {"thinking": {"type": "disabled"}},
        }
    ]
    assert model.states == [
        {"messages": [{"role": "user", "content": "你好"}]},
        {"messages": [{"role": "user", "content": "再见"}]},
    ]


@pytest.mark.parametrize("content", ["", "   ", [{"type": "text", "text": "hi"}]])
@pytest.mark.asyncio
async def test_rejects_empty_or_non_text_reply(
    monkeypatch: pytest.MonkeyPatch, content: Any
) -> None:
    model = FakeModel([AIMessage(content=content)])
    monkeypatch.setattr(reply_module, "ChatOpenAI", lambda **_kwargs: model, raising=False)
    with pytest.raises(ValueError, match="Empty LLM reply"):
        await LLMReply("deepseek-test-key")("你好")
