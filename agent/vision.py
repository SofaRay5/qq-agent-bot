"""Optional single-image description with a persistent daily call limit."""

import asyncio
import base64
import logging

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.groupmate import BudgetExceeded
from agent.image_fetch import ImageDownloadError, fetch_image, read_image_file
from core.budget import DailyBudget

logger = logging.getLogger(__name__)


def _safe_error_label(value: object) -> str:
    text = str(value)
    return (
        text if len(text) <= 64 and text.replace("_", "").replace("-", "").isalnum() else "unknown"
    )


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
        try:
            mime, image = await fetch_image(url, claimed_size)
        except Exception as exc:
            source = "http" if url.startswith(("http://", "https://")) else "other"
            logger.error("vision failed: stage=download source=%s length=%d", source, len(url))
            raise ImageDownloadError("Image download failed") from exc
        return await self._describe(mime, image)

    async def describe_file(self, path: str, claimed_size: int | None) -> str:
        """Describe one bounded local file materialized by NapCat."""
        mime, image = await asyncio.to_thread(read_image_file, path, claimed_size)
        return await self._describe(mime, image)

    async def _describe(self, mime: str, image: bytes) -> str:
        budget_result = await self._budget.reserve("vision")
        if budget_result != "ok":
            raise BudgetExceeded(budget_result)
        try:
            result = await self._model.ainvoke([_image_message(mime, image)])
        except ValueError as exc:
            detail = exc.args[0] if exc.args and isinstance(exc.args[0], dict) else {}
            logger.error(
                "vision provider error: code=%s type=%s",
                _safe_error_label(detail.get("code")),
                _safe_error_label(detail.get("type")),
            )
            raise
        description = result.content
        if not isinstance(description, str) or not description.strip():
            logger.error(
                "invalid vision response: content_type=%s empty=%s",
                type(description).__name__,
                isinstance(description, str) and not description.strip(),
            )
            raise ValueError("Empty vision description")
        return description.strip()
