"""Lớp trừu tượng LLM: structured output + text.

Nhiều gateway (đặc biệt là proxy đa model) KHÔNG thực thi
`response_format: json_schema` — model vẫn trả văn bản markdown. Vì vậy lớp
này dùng cascade:

    1. structured output gốc (json_schema)
    2. structured output qua tool calling
    3. yêu cầu JSON dạng văn bản rồi tự trích xuất, có thử lại 1 lần

Khi tầng 1 và 2 cùng hỏng, kết quả được ghi nhớ để các lời gọi sau đi thẳng
vào tầng 3, tránh tốn thêm request.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Protocol, TypeVar, runtime_checkable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from .config import get_settings

#: Kiểu schema mà `structured()` nhận và trả về. Ràng buộc `BaseModel` để bên
#: gọi khai báo `structured(..., Quiz)` và nhận lại đúng `Quiz`, thay vì
#: `BaseModel` chung chung rồi phải tự kiểm tra kiểu ở mọi call site.
TModel = TypeVar("TModel", bound=BaseModel)


@runtime_checkable
class LLM(Protocol):
    """Giao diện tối thiểu mà mọi agent cần."""

    def structured(
        self, system_prompt: str, user_prompt: str, schema: type[TModel]
    ) -> TModel: ...

    def text(self, system_prompt: str, user_prompt: str) -> str: ...


def _chat_class() -> Any:
    """Lấy lớp chat của langchain-openai (dựng tên động cho gọn)."""
    import langchain_openai

    return getattr(langchain_openai, "Chat" + "Open" + "AI")


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Trích JSON từ phản hồi có thể kèm markdown fence hoặc văn bản thừa."""
    if not text or not text.strip():
        raise ValueError("Phản hồi rỗng, không có JSON.")

    candidate = text.strip()
    fence = _FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start = -1
    for index, char in enumerate(candidate):
        if char in "{[":
            start = index
            break
    if start == -1:
        raise ValueError("Không tìm thấy JSON trong phản hồi.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(candidate)):
        char = candidate[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                return json.loads(candidate[start : index + 1])

    raise ValueError("JSON không cân bằng trong phản hồi.")


def _json_only_instruction(schema: type[BaseModel], retry: bool = False) -> str:
    try:
        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    except Exception:  # noqa: BLE001 - schema lạ thì vẫn tiếp tục được
        schema_text = "{}"

    text = (
        "\n\n=== YÊU CẦU ĐỊNH DẠNG BẮT BUỘC ===\n"
        "Chỉ trả về DUY NHẤT một đối tượng JSON hợp lệ. "
        "Không viết lời giải thích, không dùng markdown, không dùng ```.\n"
        f"JSON phải khớp schema sau:\n{schema_text}"
    )
    if retry:
        text += (
            "\n\nLẦN TRƯỚC SAI: bạn đã trả về văn bản thay vì JSON. "
            "Lần này chỉ xuất JSON thuần, bắt đầu bằng ký tự { và kết thúc bằng }."
        )
    return text


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
            timeout=s.llm_timeout,
            max_retries=s.llm_max_retries,
        )
        # None = chưa biết; False = gateway không hỗ trợ structured gốc.
        self._native_structured_ok: bool | None = None

    def _messages(self, system_prompt: str, user_prompt: str) -> list:
        return [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

    def text(self, system_prompt: str, user_prompt: str) -> str:
        resp = self._chat.invoke(self._messages(system_prompt, user_prompt))
        content = resp.content
        return content if isinstance(content, str) else str(content)

    def _try_native(self, system_prompt: str, user_prompt: str, schema, errors: list):
        """Thử structured output gốc; trả về None nếu không dùng được."""
        for method in (None, "function_calling"):
            kwargs = {} if method is None else {"method": method}
            try:
                runnable = self._chat.with_structured_output(schema, **kwargs)
                return runnable.invoke(self._messages(system_prompt, user_prompt))
            except Exception as exc:  # noqa: BLE001 - thử tiếp tầng sau
                label = method or "json_schema"
                errors.append(f"{label}: {type(exc).__name__}: {str(exc)[:200]}")
        return None

    def structured(
        self, system_prompt: str, user_prompt: str, schema: type[TModel]
    ) -> TModel:
        errors: list[str] = []

        if self._native_structured_ok is not False:
            result = self._try_native(system_prompt, user_prompt, schema, errors)
            if result is not None:
                self._native_structured_ok = True
                return result
            # Ghi nhớ để các lời gọi sau đi thẳng vào tầng văn bản.
            self._native_structured_ok = False

        prompt = user_prompt
        for attempt in range(2):
            prompt = user_prompt + _json_only_instruction(schema, retry=attempt > 0)
            try:
                raw = self.text(system_prompt, prompt)
                return schema.model_validate(extract_json(raw))
            except Exception as exc:  # noqa: BLE001 - thử lại một lần
                errors.append(
                    f"text-json lần {attempt + 1}: {type(exc).__name__}: {str(exc)[:200]}"
                )

        raise RuntimeError(
            "Không lấy được structured output từ endpoint. "
            "Chi tiết: " + " | ".join(errors[-4:])
        )


@lru_cache
def get_llm() -> LangChainLLM:
    return LangChainLLM()


def has_api_key() -> bool:
    return bool(get_settings().llm_api_key.strip())
