"""Persistent daily limits for provider calls."""

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from config.models import Settings

BudgetKind = Literal["chat", "proactive", "vision", "memory"]
BudgetResult = Literal["ok", "total", "proactive", "vision", "memory"]


@dataclass(frozen=True)
class BudgetUsage:
    total: int
    proactive: int
    vision: int
    memory: int = 0


def _today() -> date:
    return date.today()


class DailyBudget:
    def __init__(self, settings: Settings, db_path: Path) -> None:
        self._settings = settings
        self._db_path = db_path

    async def reserve(self, kind: BudgetKind) -> BudgetResult:
        """Atomically reserve one provider call from today's limits."""
        return await asyncio.to_thread(self._reserve_sync, kind)

    async def usage(self) -> BudgetUsage:
        """Read today's persisted counters without reserving a call."""
        return await asyncio.to_thread(self._usage_sync)

    def _usage_sync(self) -> BudgetUsage:
        if not self._db_path.exists():
            return BudgetUsage(0, 0, 0, 0)
        with sqlite3.connect(self._db_path) as db:
            _ensure_schema(db)
            row = db.execute(
                "SELECT total, proactive, vision, memory FROM model_usage WHERE day=?",
                (_today().isoformat(),),
            ).fetchone()
        return BudgetUsage(*row) if row is not None else BudgetUsage(0, 0, 0, 0)

    def _reserve_sync(self, kind: BudgetKind) -> BudgetResult:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        proactive = int(kind == "proactive")
        vision = int(kind == "vision")
        memory = int(kind == "memory")
        day = _today().isoformat()

        with sqlite3.connect(self._db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            _ensure_schema(db)
            db.execute(
                "INSERT OR IGNORE INTO model_usage"
                "(day, total, proactive, vision, memory) VALUES (?, 0, 0, 0, 0)",
                (day,),
            )
            updated = db.execute(
                "UPDATE model_usage "
                "SET total=total+1, proactive=proactive+?, vision=vision+?, memory=memory+? "
                "WHERE day=? AND total<? "
                "AND (?=0 OR proactive<?) AND (?=0 OR vision<?) "
                "AND (?=0 OR memory<?)",
                (
                    proactive,
                    vision,
                    memory,
                    day,
                    self._settings.daily_model_calls,
                    proactive,
                    self._settings.daily_proactive_calls,
                    vision,
                    self._settings.daily_vision_calls,
                    memory,
                    self._settings.daily_memory_calls,
                ),
            )
            if updated.rowcount == 1:
                return "ok"

            row = db.execute(
                "SELECT total, proactive, vision, memory FROM model_usage WHERE day=?",
                (day,),
            ).fetchone()
            if row is None:
                raise sqlite3.DatabaseError("Missing daily usage row")
            total, used_proactive, used_vision, used_memory = row
            if total >= self._settings.daily_model_calls:
                return "total"
            if kind == "proactive" and used_proactive >= self._settings.daily_proactive_calls:
                return "proactive"
            if kind == "vision" and used_vision >= self._settings.daily_vision_calls:
                return "vision"
            if kind == "memory" and used_memory >= self._settings.daily_memory_calls:
                return "memory"
            raise sqlite3.DatabaseError("Daily usage update failed")


def _ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS model_usage "
        "(day TEXT PRIMARY KEY, total INTEGER NOT NULL, "
        "proactive INTEGER NOT NULL, vision INTEGER NOT NULL, "
        "memory INTEGER NOT NULL DEFAULT 0)"
    )
    columns = {row[1] for row in db.execute("PRAGMA table_info(model_usage)")}
    if "memory" not in columns:
        db.execute("ALTER TABLE model_usage ADD COLUMN memory INTEGER NOT NULL DEFAULT 0")
