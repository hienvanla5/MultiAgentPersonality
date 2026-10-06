"""Chẩn đoán kết nối LLM theo từng tầng, có timeout ngắn.

Chạy: uv run python scripts/diagnose_llm.py
Mục đích: chỉ ra chính xác tầng nào treo (DNS / TCP / TLS / HTTP / chat / structured).
"""

from __future__ import annotations

import socket
import sys
import time
from urllib.parse import urlparse

from lifeos.config import get_settings

TIMEOUT = 20.0


def _step(name: str) -> None:
    print(f"\n=== {name} ===")


def main() -> int:
    s = get_settings()

    _step("1. Cau hinh da resolve tu .env")
    key = s.llm_api_key.strip()
    print(f"  model       : {s.llm_model}")
    print(f"  base_url    : {s.llm_base_url}")
    print(f"  temperature : {s.llm_temperature}")
    print(f"  api_key     : {'CO' if key else 'TRONG'} (do dai {len(key)})")
    if not key:
        print("  -> .env chua duoc doc hoac key rong. Dung lai.")
        return 1

    parsed = urlparse(s.llm_base_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    print(f"  host/port   : {host}:{port}")

    _step("2. DNS")
    t0 = time.time()
    try:
        ip = socket.gethostbyname(host)
        print(f"  OK  {ip}  ({time.time() - t0:.2f}s)")
    except Exception as exc:
        print(f"  FAIL {type(exc).__name__}: {exc}  ({time.time() - t0:.2f}s)")
        return 1

    _step("3. TCP handshake")
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT):
            print(f"  OK  ({time.time() - t0:.2f}s)")
    except Exception as exc:
        print(f"  FAIL {type(exc).__name__}: {exc}  ({time.time() - t0:.2f}s)")
        print("  -> Mang/endpoint khong ket noi duoc. Day la nguyen nhan treo.")
        return 1

    _step("4. HTTP GET /models")
    import httpx

    url = s.llm_base_url.rstrip("/") + "/models"
    t0 = time.time()
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {key}"})
        print(f"  status {r.status_code}  ({time.time() - t0:.2f}s)")
        if r.status_code == 200:
            try:
                ids = [m.get("id") for m in r.json().get("data", [])][:20]
                print(f"  model kha dung: {ids}")
                if s.llm_model not in ids:
                    print(f"  !! '{s.llm_model}' KHONG co trong danh sach tren.")
            except Exception as exc:
                print(f"  (khong parse duoc JSON: {exc})")
        else:
            print(f"  body: {r.text[:300]}")
    except Exception as exc:
        print(f"  FAIL {type(exc).__name__}: {exc}  ({time.time() - t0:.2f}s)")

    _step("5. Chat completion (SDK openai, max_retries=0)")
    from openai import OpenAI

    t0 = time.time()
    try:
        client = OpenAI(
            api_key=key, base_url=s.llm_base_url, timeout=TIMEOUT, max_retries=0
        )
        resp = client.chat.completions.create(
            model=s.llm_model,
            messages=[{"role": "user", "content": "Tra loi dung mot tu: OK"}],
            temperature=0,
        )
        print(f"  OK  ({time.time() - t0:.2f}s)")
        print(f"  content: {resp.choices[0].message.content!r}")
    except Exception as exc:
        print(f"  FAIL {type(exc).__name__}: {exc}  ({time.time() - t0:.2f}s)")
        print("  -> Day la nguyen nhan treo cua agent.")

    _step("6. Structured output (nhu agent dung)")
    from pydantic import BaseModel

    import langchain_openai

    class Probe(BaseModel):
        ok: bool = True
        note: str = ""

    chat_cls = getattr(langchain_openai, "Chat" + "Open" + "AI")
    t0 = time.time()
    try:
        chat = chat_cls(
            model=s.llm_model,
            api_key=key,
            base_url=s.llm_base_url,
            temperature=0,
            timeout=TIMEOUT,
            max_retries=0,
        )
        runnable = chat.with_structured_output(Probe)
        out = runnable.invoke("Tra ve ok=true va note='ok'.")
        print(f"  OK  ({time.time() - t0:.2f}s) -> {out!r}")
    except Exception as exc:
        print(f"  FAIL {type(exc).__name__}: {exc}  ({time.time() - t0:.2f}s)")
        print("  -> Endpoint khong ho tro tool/json_schema o tang goc.")

    _step("7. Cascade ma agent thuc dung (LangChainLLM.structured)")
    from lifeos.llm import LangChainLLM

    t0 = time.time()
    try:
        llm = LangChainLLM(model=s.llm_model, temperature=0)
        out = llm.structured(
            "Ban chi tra ve JSON dung schema.",
            "Tra ve ok=true va note='ok'.",
            Probe,
        )
        route = (
            "structured goc"
            if llm._native_structured_ok
            else "du phong text+JSON"
        )
        print(f"  OK  ({time.time() - t0:.2f}s) -> {out!r}")
        print(f"  duong di: {route}")
    except Exception as exc:
        print(f"  FAIL {type(exc).__name__}: {str(exc)[:250]}  ({time.time() - t0:.2f}s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())