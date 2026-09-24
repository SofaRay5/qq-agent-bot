"""One-turn text replies through DeepSeek's OpenAI-compatible API."""

from langchain_openai import ChatOpenAI
from pydantic import SecretStr


class LLMReply:
    def __init__(self, api_key: str) -> None:
        self._model = ChatOpenAI(
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            api_key=SecretStr(api_key),
            extra_body={"thinking": {"type": "disabled"}},
        )

    async def __call__(self, text: str) -> str:
        """Generate one text reply without conversation history."""
        result = await self._model.ainvoke([{"role": "user", "content": text}])
        content = result.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty LLM reply")
        return content
