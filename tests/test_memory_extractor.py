import json
from collections.abc import Sequence
from typing import Literal

import pytest
from langchain_core.messages import AIMessage, BaseMessage

import memory.extractor as extractor_module
from config.models import ProviderSettings
from core.budget import BudgetKind, BudgetResult
from memory.extractor import MemoryCandidate, MemoryExtractor, should_extract
from memory.store import MemoryRecord, MemoryScope, MemorySource, MemoryVersion


class FakeBudget:
    def __init__(self, result: BudgetResult = "ok") -> None:
        self.result = result
        self.calls: list[BudgetKind] = []

    async def reserve(self, kind: BudgetKind) -> BudgetResult:
        self.calls.append(kind)
        return self.result


class FakeModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[Sequence[BaseMessage]] = []

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> AIMessage:
        self.calls.append(messages)
        return AIMessage(content=self.content)


def provider() -> ProviderSettings:
    return ProviderSettings(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        api_key="secret",
    )


def candidate(text: str = "我喜欢草莓蛋糕") -> MemoryCandidate:
    return MemoryCandidate(
        scope=MemoryScope.private(1),
        text=text,
        source=MemorySource(message_id="10", message_time=20, excerpt=text),
    )


def existing(
    content: str = "我住在芝加哥",
    scope: MemoryScope | None = None,
    item_id: int = 7,
) -> MemoryRecord:
    actual_scope = scope or MemoryScope.private(1)
    source = MemorySource(message_id="1", message_time=2, excerpt=content)
    version = MemoryVersion(item_id, 1, True, content, 3, source, "automatic", "2026-01-01")
    return MemoryRecord(item_id, actual_scope, "fact", "2026-01-01", version)


def build_extractor(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    budget_result: BudgetResult = "ok",
) -> tuple[MemoryExtractor, FakeModel, FakeBudget, dict[str, object]]:
    model = FakeModel(content)
    budget = FakeBudget(budget_result)
    kwargs: dict[str, object] = {}

    def fake_model(**values: object) -> FakeModel:
        kwargs.update(values)
        return model

    monkeypatch.setattr(extractor_module, "ChatOpenAI", fake_model)
    return MemoryExtractor(provider(), budget), model, budget, kwargs


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "[图片]",
        "[image]",
        "你好",
        "暂时无法回复，请稍后再试",
        "我的密码是 hunter2",
        "API Token: secret-value",
        "验证码 123456",
        "身份证号 11010519491231002X",
        "银行卡 6222021234567890123",
        "我的地址是南京路88号3栋201室",
    ],
)
def test_local_filter_rejects_unsafe_or_useless_text(text: str) -> None:
    assert not should_extract(text)


@pytest.mark.parametrize(
    "text",
    [
        "我住在芝加哥",
        "我喜欢草莓蛋糕",
        "我不是学生了，现在是设计师",
        "之前说错了，我现在住在纽约",
        "记住我喝咖啡不加糖",
        "我们群约定每周六晚上一起打游戏",
    ],
)
def test_local_filter_keeps_stable_memory_candidates(text: str) -> None:
    assert should_extract(text)


@pytest.mark.parametrize(
    ("payload", "expected_action"),
    [
        ({"operations": [{"action": "ignore"}]}, None),
        (
            {
                "operations": [
                    {
                        "action": "create",
                        "kind": "preference",
                        "content": "喜欢草莓蛋糕",
                        "importance": 3,
                    }
                ]
            },
            "create",
        ),
        (
            {
                "operations": [
                    {"action": "update", "target_id": 7, "content": "我住在纽约", "importance": 4}
                ]
            },
            "update",
        ),
    ],
)
async def test_accepts_strict_memory_operations(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    expected_action: Literal["create", "update"] | None,
) -> None:
    extractor, model, budget, kwargs = build_extractor(
        monkeypatch, json.dumps(payload, ensure_ascii=False)
    )

    operations = await extractor.extract(candidate("之前说错了，我现在住在纽约"), (existing(),))

    assert [operation.action for operation in operations] == (
        [] if expected_action is None else [expected_action]
    )
    assert budget.calls == ["memory"]
    assert len(model.calls) == 1
    assert kwargs["max_retries"] == 0
    assert kwargs["model_kwargs"] == {"response_format": {"type": "json_object"}}


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        '{"operations":[],"extra":true}',
        '{"operations":[{"action":"other"}]}',
        '{"operations":[{"action":"ignore","extra":true}]}',
        json.dumps(
            {
                "operations": [
                    {"action": "create", "kind": "fact", "content": str(index), "importance": 1}
                    for index in range(4)
                ]
            }
        ),
        json.dumps(
            {
                "operations": [
                    {"action": "create", "kind": "fact", "content": "字" * 501, "importance": 1}
                ]
            }
        ),
        json.dumps(
            {
                "operations": [
                    {
                        "action": "create",
                        "kind": "fact",
                        "content": "安全内容",
                        "importance": 1,
                        "excerpt": "字" * 301,
                    }
                ]
            }
        ),
        '{"operations":[{"action":"update","target_id":999,"content":"新内容","importance":2}]}',
        '{"operations":[{"action":"create","kind":"fact","content":"我的密码是 abc","importance":2}]}',
    ],
)
async def test_rejects_invalid_model_protocol(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> None:
    extractor, _, budget, _ = build_extractor(monkeypatch, content)

    with pytest.raises(ValueError, match="Invalid memory extraction"):
        await extractor.extract(candidate(), (existing(),))

    assert budget.calls == ["memory"]


async def test_rejects_duplicates_and_cross_scope_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = {
        "operations": [
            {"action": "create", "kind": "fact", "content": "我住在芝加哥", "importance": 2}
        ]
    }
    extractor, _, _, _ = build_extractor(monkeypatch, json.dumps(duplicate, ensure_ascii=False))
    with pytest.raises(ValueError, match="Invalid memory extraction"):
        await extractor.extract(candidate(), (existing(),))

    update = {
        "operations": [
            {"action": "update", "target_id": 7, "content": "群内事实", "importance": 2}
        ]
    }
    extractor, _, _, _ = build_extractor(monkeypatch, json.dumps(update, ensure_ascii=False))
    with pytest.raises(ValueError, match="Invalid memory extraction"):
        await extractor.extract(
            candidate(),
            (existing(scope=MemoryScope.group_user(9, 1)),),
        )


async def test_denied_budget_and_local_rejection_skip_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = '{"operations":[{"action":"ignore"}]}'
    denied, denied_model, denied_budget, _ = build_extractor(monkeypatch, payload, "memory")
    assert await denied.extract(candidate(), ()) == ()
    assert denied_budget.calls == ["memory"]
    assert denied_model.calls == []

    rejected, rejected_model, rejected_budget, _ = build_extractor(monkeypatch, payload)
    assert await rejected.extract(candidate("你好"), ()) == ()
    assert rejected_budget.calls == []
    assert rejected_model.calls == []
