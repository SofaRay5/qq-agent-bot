import asyncio
import sqlite3
from datetime import date
from pathlib import Path

import pytest

import core.budget as budget_module
from config.models import Settings
from core.budget import BudgetUsage, DailyBudget

DEFAULT_SETTINGS = {
    "continuous_window_seconds": 600,
    "window_max_attempts": 5,
    "window_max_replies": 5,
    "daily_model_calls": 50,
    "daily_proactive_calls": 5,
    "daily_vision_calls": 5,
    "proactive_mode": "off",
    "proactive_probability": 0.05,
    "minimum_reply_interval_seconds": 8,
    "send_delay_seconds": 1.5,
    "context_max_messages": 20,
    "context_max_characters": 6000,
}


def settings(**changes: object) -> Settings:
    return Settings.model_validate({**DEFAULT_SETTINGS, **changes})


@pytest.mark.asyncio
async def test_usage_is_zero_before_database_exists(tmp_path: Path) -> None:
    path = tmp_path / "usage.db"
    budget = DailyBudget(settings(), path)

    assert await budget.usage() == BudgetUsage(total=0, proactive=0, vision=0)
    assert not path.exists()


@pytest.mark.asyncio
async def test_usage_reports_current_daily_counts(tmp_path: Path) -> None:
    budget = DailyBudget(settings(), tmp_path / "usage.db")

    assert await budget.reserve("chat") == "ok"
    assert await budget.reserve("proactive") == "ok"
    assert await budget.reserve("vision") == "ok"

    assert await budget.usage() == BudgetUsage(total=3, proactive=1, vision=1)


@pytest.mark.asyncio
async def test_chat_calls_stop_at_total_limit(tmp_path: Path) -> None:
    budget = DailyBudget(
        settings(
            daily_model_calls=2,
            daily_proactive_calls=2,
            daily_vision_calls=2,
        ),
        tmp_path / "usage.db",
    )

    assert await budget.reserve("chat") == "ok"
    assert await budget.reserve("chat") == "ok"
    assert await budget.reserve("chat") == "total"


@pytest.mark.asyncio
async def test_proactive_limit_does_not_consume_denied_total_slot(tmp_path: Path) -> None:
    budget = DailyBudget(
        settings(
            daily_model_calls=3,
            daily_proactive_calls=1,
            daily_vision_calls=3,
        ),
        tmp_path / "usage.db",
    )

    assert await budget.reserve("proactive") == "ok"
    assert await budget.reserve("proactive") == "proactive"
    assert await budget.reserve("chat") == "ok"
    assert await budget.reserve("chat") == "ok"
    assert await budget.reserve("chat") == "total"


@pytest.mark.asyncio
async def test_vision_limit_does_not_consume_denied_total_slot(tmp_path: Path) -> None:
    budget = DailyBudget(
        settings(
            daily_model_calls=3,
            daily_proactive_calls=3,
            daily_vision_calls=1,
        ),
        tmp_path / "usage.db",
    )

    assert await budget.reserve("vision") == "ok"
    assert await budget.reserve("vision") == "vision"
    assert await budget.reserve("chat") == "ok"
    assert await budget.reserve("chat") == "ok"
    assert await budget.reserve("chat") == "total"


@pytest.mark.asyncio
async def test_total_limit_takes_precedence_over_sublimit(tmp_path: Path) -> None:
    budget = DailyBudget(
        settings(
            daily_model_calls=1,
            daily_proactive_calls=1,
            daily_vision_calls=1,
        ),
        tmp_path / "usage.db",
    )

    assert await budget.reserve("proactive") == "ok"
    assert await budget.reserve("proactive") == "total"


@pytest.mark.asyncio
async def test_reservation_survives_provider_failure(tmp_path: Path) -> None:
    budget = DailyBudget(
        settings(
            daily_model_calls=1,
            daily_proactive_calls=1,
            daily_vision_calls=1,
        ),
        tmp_path / "usage.db",
    )

    assert await budget.reserve("chat") == "ok"
    with pytest.raises(ConnectionError):
        raise ConnectionError("provider failed after reservation")

    assert await budget.reserve("chat") == "total"


@pytest.mark.asyncio
async def test_usage_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "usage.db"
    limits = settings(
        daily_model_calls=1,
        daily_proactive_calls=1,
        daily_vision_calls=1,
    )

    assert await DailyBudget(limits, path).reserve("chat") == "ok"
    assert await DailyBudget(limits, path).reserve("chat") == "total"


@pytest.mark.asyncio
async def test_usage_resets_on_next_local_date(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current_day = date(2026, 9, 24)
    monkeypatch.setattr(budget_module, "_today", lambda: current_day)
    budget = DailyBudget(
        settings(
            daily_model_calls=1,
            daily_proactive_calls=1,
            daily_vision_calls=1,
        ),
        tmp_path / "usage.db",
    )
    assert await budget.reserve("chat") == "ok"
    assert await budget.reserve("chat") == "total"

    current_day = date(2026, 9, 25)
    assert await budget.reserve("chat") == "ok"


@pytest.mark.asyncio
async def test_concurrent_instances_cannot_exceed_total(tmp_path: Path) -> None:
    limits = settings(
        daily_model_calls=5,
        daily_proactive_calls=5,
        daily_vision_calls=5,
    )
    path = tmp_path / "usage.db"
    first = DailyBudget(limits, path)
    second = DailyBudget(limits, path)

    results = await asyncio.gather(
        *(budget.reserve("chat") for budget in (first, second, first, second, first, second))
    )

    assert results.count("ok") == 5
    assert results.count("total") == 1


@pytest.mark.asyncio
async def test_database_errors_fail_closed(tmp_path: Path) -> None:
    directory_instead_of_database = tmp_path / "usage.db"
    directory_instead_of_database.mkdir()
    budget = DailyBudget(settings(), directory_instead_of_database)

    with pytest.raises(sqlite3.Error):
        await budget.reserve("chat")
