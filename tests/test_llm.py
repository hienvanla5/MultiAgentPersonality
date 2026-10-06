"""Test trích JSON và cascade structured output (không gọi mạng)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from lifeos.llm import LangChainLLM, extract_json


class Out(BaseModel):
    value: int = 0
    label: str = ""


# --- extract_json ---


def test_extract_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_from_markdown_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_from_fence_without_language():
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_with_surrounding_prose():
    text = 'Đây là kết quả:\n{"a": 1, "b": [2, 3]}\nHy vọng hữu ích!'
    assert extract_json(text) == {"a": 1, "b": [2, 3]}


def test_extract_nested_with_brace_inside_string():
    text = 'x {"a": {"b": "}"}, "c": 2} y'
    assert extract_json(text) == {"a": {"b": "}"}, "c": 2}


def test_extract_array():
    assert extract_json("Kết quả: [1, 2, 3]") == [1, 2, 3]


def test_extract_empty_raises():
    with pytest.raises(ValueError):
        extract_json("   ")


def test_extract_without_json_raises():
    with pytest.raises(ValueError):
        extract_json("không có json ở đây cả")


# --- cascade dự phòng ---


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Runnable:
    def __init__(self, schema, payload: dict) -> None:
        self._schema = schema
        self._payload = payload

    def invoke(self, messages):
        return self._schema.model_validate(self._payload)


class FakeChat:
    """Chat giả: điều khiển được structured gốc hỏng/không hỏng."""

    def __init__(self, native_ok: bool, text_replies: list[str]) -> None:
        self.native_ok = native_ok
        self.text_replies = list(text_replies)
        self.native_attempts = 0
        self.text_calls = 0

    def with_structured_output(self, schema, **kwargs):
        self.native_attempts += 1
        if not self.native_ok:
            raise ValueError("response_format json_schema không được hỗ trợ")
        return _Runnable(schema, {"value": 1, "label": "native"})

    def invoke(self, messages):
        self.text_calls += 1
        reply = self.text_replies.pop(0) if self.text_replies else ""
        return _Msg(reply)


def _llm_with(chat: FakeChat) -> LangChainLLM:
    llm = LangChainLLM.__new__(LangChainLLM)
    llm._chat = chat
    llm._native_structured_ok = None
    return llm


def test_native_success_skips_fallback():
    chat = FakeChat(native_ok=True, text_replies=[])
    llm = _llm_with(chat)

    out = llm.structured("sys", "user", Out)

    assert out.label == "native"
    assert chat.text_calls == 0
    assert llm._native_structured_ok is True


def test_cascade_falls_back_to_text_json():
    chat = FakeChat(
        native_ok=False,
        text_replies=['Kết quả:\n```json\n{"value": 7, "label": "text"}\n```'],
    )
    llm = _llm_with(chat)

    out = llm.structured("sys", "user", Out)

    assert out.value == 7
    assert out.label == "text"
    # Thử json_schema rồi function_calling, cả hai đều hỏng
    assert chat.native_attempts == 2
    assert chat.text_calls == 1
    assert llm._native_structured_ok is False


def test_sticky_downgrade_avoids_repeat_native_calls():
    chat = FakeChat(native_ok=False, text_replies=['{"value": 1}', '{"value": 2}'])
    llm = _llm_with(chat)

    llm.structured("s", "u", Out)
    assert chat.native_attempts == 2

    llm.structured("s", "u", Out)
    # Lần hai đi thẳng vào dự phòng, không thử native nữa
    assert chat.native_attempts == 2
    assert chat.text_calls == 2


def test_retry_after_non_json_reply():
    chat = FakeChat(
        native_ok=False,
        text_replies=["Xin chào, đây là câu trả lời dài dòng.", '{"value": 9}'],
    )
    llm = _llm_with(chat)

    out = llm.structured("s", "u", Out)

    assert out.value == 9
    assert chat.text_calls == 2


def test_raises_when_never_valid():
    chat = FakeChat(native_ok=False, text_replies=["không json", "vẫn không json"])
    llm = _llm_with(chat)

    with pytest.raises(RuntimeError):
        llm.structured("s", "u", Out)