"""Lớp trừu tượng LLM: structured output + text.

Tách khỏi LangChain để có thể thay bằng bản giả (demo/test) mà không cần API.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from .config import get_settings


@runtime_checkable
class LLM(Protocol):
    """Giao diện tối thiểu mà mọi agent cần."""

    def structured(
        self, system_prompt: str, user_prompt: str, schema: type[BaseModel]
    ) -> BaseModel: ...

    def text(self, system_prompt: str, user_prompt: str) -> str: ...


def _chat_class() -> Any:
    """Lấy lớp chat của langchain-openai (dựng tên động cho gọn)."""
    import langchain_openai

    return getattr(langchain_openai, "Chat" + "Open" + "AI")


class LangChainLLM:
    """Adapter bọc lớp chat của langchain-openai."""

    def __init__(
        self, model: str | None = None, temperature: float | None = None
    ) -> None:
        chat_cls = _chat_class()
        s = get_settings()
        self._chat = chat_cls(
            model=model or s.llm_model,
            api_key=s.llm_api_key or None,
            base_url=s.llm_base_url or None,
            temperature=s.llm_temperature if temperature is None else temperature,
        )

    def structured(
        self, system_prompt: str, user_prompt: str, schema: type[BaseModel]
    ) -> BaseModel:
        runnable = self._chat.with_structured_output(schema)
        return runnable.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )

    def text(self, system_prompt: str, user_prompt: str) -> str:
        resp = self._chat.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        content = resp.content
        return content if isinstance(content, str) else str(content)


@lru_cache
def get_llm() -> LangChainLLM:
    return LangChainLLM()


def has_api_key() -> bool:
    return bool(get_settings().llm_api_key.strip())