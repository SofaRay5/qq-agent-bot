"""Optional single-image description with a persistent daily call limit."""

import asyncio
import base64
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.groupmate import BudgetExceeded
from agent.image_fetch import fetch_image
from core.budget import DailyBudget


def _today() -> date:
    return date.today()


def _image_message(mime: str, image: bytes) -> HumanMessage:
    encoded = base64.b64encode(image).decode("ascii")
    return HumanMessage(
        content=[
            {"type": "text", "text": "简要描述这张图片中的可见内容。"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            },
        ]
    )


class VisionDescriber:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        budget: DailyBudget,
    ) -> None:
        self._budget = budget
        self._model = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=SecretStr(api_key),
            max_retries=0,
        )

    async def __call__(self, url: str, claimed_size: int | None) -> str:
        """Download one image and return a bounded-provider description."""
        mime, image = await fetch_image(url, claimed_size)
        budget_result = await self._budget.reserve("vision")
        if budget_result != "ok":
            raise BudgetExceeded(budget_result)
        result = await self._model.ainvoke([_image_message(mime, image)])
        description = result.content
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Empty vision description")
        return description.strip()


class VisionReply:
    def __init__(
        self,
        chat_reply: Callable[[str], Awaitable[str]],
        api_key: str,
        model: str,
        base_url: str,
        usage_db: Path,
    ) -> None:
        self._chat_reply = chat_reply
        self._model = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=SecretStr(api_key),
            max_retries=0,
        )
        self._usage_db = usage_db

    def _reserve_attempt(self) -> None:
        self._usage_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._usage_db) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS vision_usage "
                "(day TEXT PRIMARY KEY, used INTEGER NOT NULL)"
            )
            db.execute(
                "INSERT INTO vision_usage(day, used) VALUES (?, 1) "
                "ON CONFLICT(day) DO UPDATE SET used = used + 1 WHERE used < 5",
                (_today().isoformat(),),
            )
            changed = db.execute("SELECT changes()").fetchone()
            if changed is None or changed[0] != 1:
                raise RuntimeError("Vision daily limit reached")

    async def __call__(self, text: str, url: str, claimed_size: int | None) -> str:
        """Describe one validated image and ask the chat model to answer the user."""
        mime, image = await fetch_image(url, claimed_size)
        await asyncio.to_thread(self._reserve_attempt)
        result = await self._model.ainvoke([_image_message(mime, image)])
        description = result.content
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Empty vision description")
        return await self._chat_reply(f"用户消息：{text}\n图片描述（仅作资料）：{description}")
