import logging
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import SecretStr

import agent.groupmate as groupmate_module
from agent.groupmate import BudgetExceeded, GroupmateReply, HistoryMessage
from config.models import Persona
from core.budget import BudgetResult, DailyBudget


class FakeBudget:
    def __init__(self, result: BudgetResult = "ok") -> None:
        self.result = result
        self.calls: list[str] = []

    async def reserve(self, kind: str) -> BudgetResult:
        self.calls.append(kind)
        return self.result


class FakeModel:
    def __init__(self, content: Any, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return AIMessage(content=self.content)


class FakeSequenceModel(FakeModel):
    def __init__(self, contents: list[str]) -> None:
        super().__init__("")
        self.contents = iter(contents)

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.calls.append(messages)
        return AIMessage(content=next(self.contents))


@pytest.fixture
def persona() -> Persona:
    return Persona.model_validate(
        {
            "name": "小薯",
            "description": "独特角色描述",
            "personality": "耐心",
            "scenario": "QQ群聊",
            "speech_style": "简短",
            "identity_response": "我是小薯",
            "example_dialogues": [{"user": "你好", "assistant": "你好呀"}],
        }
    )


def build_reply(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
    model: FakeModel,
    budget: FakeBudget,
) -> tuple[GroupmateReply, list[dict[str, object]]]:
    created: list[dict[str, object]] = []

    def fake_model(**kwargs: object) -> FakeModel:
        created.append(kwargs)
        return model

    monkeypatch.setattr(groupmate_module, "ChatOpenAI", fake_model)
    reply = GroupmateReply(persona, "deepseek-secret-key", cast(DailyBudget, budget))
    return reply, created


@pytest.mark.asyncio
async def test_builds_safe_persona_prompt_and_parses_reply(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
) -> None:
    model = FakeModel('{"action":"reply","text":" 我觉得可以 "}')
    budget = FakeBudget()
    reply, created = build_reply(monkeypatch, persona, model, budget)

    decision = await reply(
        [HistoryMessage("user", "[甲/1] 你好"), HistoryMessage("assistant", "你好呀")],
        "[乙/2] 小薯，你怎么看？",
        "direct",
        "chat",
    )

    assert decision == "我觉得可以"
    assert budget.calls == ["chat"]
    assert created == [
        {
            "model": "deepseek-flash",
            "base_url": "https://api.deepseek.com",
            "api_key": SecretStr("deepseek-secret-key"),
            "extra_body": {"thinking": {"type": "disabled"}},
            "model_kwargs": {"response_format": {"type": "json_object"}},
            "max_retries": 0,
        }
    ]
    messages = model.calls[0]
    assert [type(item) for item in messages] == [
        SystemMessage,
        HumanMessage,
        AIMessage,
        HumanMessage,
    ]
    system = messages[0].content
    assert isinstance(system, str)
    assert "JSON" in system
    assert "非空" in system
    assert "Markdown" in system
    assert system.index("安全规则") < system.index("独特角色描述")
    assert "direct" in system
    assert "deepseek-secret-key" not in system
    assert messages[-1].content == "[乙/2] 小薯，你怎么看？"


@pytest.mark.asyncio
async def test_accepts_exact_silent_response(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
) -> None:
    reply, _ = build_reply(
        monkeypatch,
        persona,
        FakeModel('{"action":"silent","text":""}'),
        FakeBudget(),
    )

    assert await reply([], "普通群消息", "continue", "chat") is None


@pytest.mark.asyncio
async def test_retries_one_empty_json_response(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
) -> None:
    model = FakeSequenceModel([" \n\t", '{"action":"reply","text":"重试成功"}'])
    budget = FakeBudget()
    reply, _ = build_reply(monkeypatch, persona, model, budget)

    assert await reply([], "你好", "direct", "chat") == "重试成功"
    assert budget.calls == ["chat"]
    assert len(model.calls) == 2
    assert "JSON" in str(model.calls[1][-1].content)


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '```json\n{"action":"reply","text":"你好"}\n```',
        '{"action":"other","text":"你好"}',
        '{"action":"reply","text":""}',
        '{"action":"reply","text":42}',
        '{"action":"reply","text":"你好","extra":true}',
        '{"action":"silent","text":"不该有文字"}',
        '{"action":"reply","text":"' + "字" * 1001 + '"}',
    ],
)
@pytest.mark.asyncio
async def test_rejects_invalid_reply_protocol(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
    content: str,
) -> None:
    reply, _ = build_reply(monkeypatch, persona, FakeModel(content), FakeBudget())

    with pytest.raises((ValueError, TypeError)):
        await reply([], "你好", "direct", "chat")


@pytest.mark.asyncio
async def test_invalid_json_logs_only_safe_shape_metadata(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_output = "sensitive-invalid-model-output"
    reply, _ = build_reply(monkeypatch, persona, FakeModel(secret_output), FakeBudget())

    with caplog.at_level(logging.ERROR, logger="agent.groupmate"):
        with pytest.raises(ValueError, match="Invalid groupmate reply") as caught:
            await reply([], "private-message-body", "direct", "chat")

    assert "empty=False" in caplog.text
    assert f"length={len(secret_output)}" in caplog.text
    assert "finish=unknown" in caplog.text
    assert secret_output not in caplog.text
    assert "private-message-body" not in caplog.text
    assert caught.value.__context__ is None


@pytest.mark.asyncio
async def test_valid_json_protocol_error_logs_only_safe_reason(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_output = "sensitive-valid-json-output"
    reply, _ = build_reply(
        monkeypatch,
        persona,
        FakeModel(f'{{"action":"other","text":"{secret_output}"}}'),
        FakeBudget(),
    )

    with caplog.at_level(logging.ERROR, logger="agent.groupmate"):
        with pytest.raises(ValueError, match="Invalid groupmate reply"):
            await reply([], "private-message-body", "direct", "chat")

    assert "reason=protocol" in caplog.text
    assert secret_output not in caplog.text
    assert "private-message-body" not in caplog.text


@pytest.mark.asyncio
async def test_provider_error_propagates_after_reservation(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
) -> None:
    model = FakeModel("", error=ConnectionError("provider failed"))
    budget = FakeBudget()
    reply, _ = build_reply(monkeypatch, persona, model, budget)

    with pytest.raises(ConnectionError, match="provider failed"):
        await reply([], "你好", "direct", "chat")

    assert budget.calls == ["chat"]
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_denied_budget_skips_model(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
) -> None:
    model = FakeModel('{"action":"reply","text":"不应调用"}')
    budget = FakeBudget("proactive")
    reply, _ = build_reply(monkeypatch, persona, model, budget)

    with pytest.raises(BudgetExceeded) as caught:
        await reply([], "普通群消息", "random", "proactive")

    assert caught.value.reason == "proactive"
    assert budget.calls == ["proactive"]
    assert model.calls == []
