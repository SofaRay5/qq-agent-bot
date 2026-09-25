"""Persistent daily limits for provider calls."""

import asyncio
import sqlite3
from datetime import date
from pathlib import Path
from typing import Literal

from config.models import Settings

BudgetKind = Literal["chat", "proactive", "vision"]
BudgetResult = Literal["ok", "total", "proactive", "vision"]


def _today() -> date:
    return date.today()


class DailyBudget:
    def __init__(self, settings: Settings, db_path: Path) -> None:
        self._settings = settings
        self._db_path = db_path

    async def reserve(self, kind: BudgetKind) -> BudgetResult:
        """Atomically reserve one provider call from today's limits."""
        return await asyncio.to_thread(self._reserve_sync, kind)

    def _reserve_sync(self, kind: BudgetKind) -> BudgetResult:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        proactive = int(kind == "proactive")
        vision = int(kind == "vision")
        day = _today().isoformat()

        with sqlite3.connect(self._db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS model_usage "
                "(day TEXT PRIMARY KEY, total INTEGER NOT NULL, "
                "proactive INTEGER NOT NULL, vision INTEGER NOT NULL)"
            )
            db.execute(
                "INSERT OR IGNORE INTO model_usage VALUES (?, 0, 0, 0)",
                (day,),
            )
            updated = db.execute(
                "UPDATE model_usage "
                "SET total=total+1, proactive=proactive+?, vision=vision+? "
                "WHERE day=? AND total<? "
                "AND (?=0 OR proactive<?) AND (?=0 OR vision<?)",
                (
                    proactive,
                    vision,
                    day,
                    self._settings.daily_model_calls,
                    proactive,
                    self._settings.daily_proactive_calls,
                    vision,
                    self._settings.daily_vision_calls,
                ),
            )
            if updated.rowcount == 1:
                return "ok"

            row = db.execute(
                "SELECT total, proactive, vision FROM model_usage WHERE day=?",
                (day,),
            ).fetchone()
            if row is None:
                raise sqlite3.DatabaseError("Missing daily usage row")
            total, used_proactive, used_vision = row
            if total >= self._settings.daily_model_calls:
                return "total"
            if kind == "proactive" and used_proactive >= self._settings.daily_proactive_calls:
                return "proactive"
            if kind == "vision" and used_vision >= self._settings.daily_vision_calls:
                return "vision"
            raise sqlite3.DatabaseError("Daily usage update failed")
