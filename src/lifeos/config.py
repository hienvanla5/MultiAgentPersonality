"""Cấu hình ứng dụng, đọc từ biến môi trường (.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.4
    # Timeout mỗi lời gọi (giây). Model suy luận có thể cần 60-180s.
    llm_timeout: float = 120.0
    # 0 = không thử lại, để lỗi trả về ngay thay vì treo im lặng.
    llm_max_retries: int = 0

    db_path: str = "data/lifeos.db"
    chroma_path: str = "data/chroma"

    @property
    def db_file(self) -> Path:
        return Path(self.db_path)

    @property
    def chroma_dir(self) -> Path:
        return Path(self.chroma_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()