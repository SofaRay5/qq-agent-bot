"""Optional single-image description with a persistent daily call limit."""

import base64

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.groupmate import BudgetExceeded
from agent.image_fetch import fetch_image
from core.budget import DailyBudget


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
