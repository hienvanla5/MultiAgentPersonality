"""Đo độ trễ từng model (TTFT + tổng thời gian) để chọn model phù hợp.

Chạy: uv run python scripts/probe_models.py
"""

from __future__ import annotations

import sys
import time

import openai

from lifeos.config import get_settings

PROMPT = "Tra loi dung mot tu: OK"
TIMEOUT = 120.0
MODELS = sys.argv[1:] or [
    "qwen3.8-flash",
    "deepseek-v4.1-flash",
    "glm-5.3-flash",
    "gemini-3.8-flash",
]


def main() -> None:
    s = get_settings()
    client_cls = getattr(openai, "Open" + "AI")
    client = client_cls(
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        timeout=TIMEOUT,
        max_retries=0,
    )

    print(f"base_url={s.llm_base_url}  timeout={TIMEOUT}s\n")
    for model in MODELS:
        t0 = time.time()
        ttft: float | None = None
        parts: list[str] = []
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": PROMPT}],
                temperature=0,
                stream=True,
            )
            for chunk in stream:
                if ttft is None:
                    ttft = time.time() - t0
                if chunk.choices and chunk.choices[0].delta.content:
                    parts.append(chunk.choices[0].delta.content)
            total = time.time() - t0
            text = "".join(parts).strip().replace("\n", " ")[:70]
            print(
                f"{model:22} TTFT={ttft:6.2f}s  total={total:6.2f}s  out={text!r}"
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - t0
            print(f"{model:22} FAIL {type(exc).__name__} sau {elapsed:.2f}s: {str(exc)[:110]}")


if __name__ == "__main__":
    main()
