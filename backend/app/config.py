"""Application configuration.

All settings are read from environment variables (or prod.env in local dev).
Only GEMINI_API_KEY is strictly required; everything else has a sensible default
so the local and Cloud Run environments differ only by their env vars.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root is two levels up from backend/app/config.py. Loading prod.env by
# absolute path means the backend finds it no matter which directory you run from
# (repo root, backend/, or inside Docker where real env vars take over anyway).
_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT / "prod.env", _ROOT / ".env", "prod.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Gemini ---
    gemini_api_key: str = ""

    # --- Models ---
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768
    generation_model: str = "gemini-2.5-flash"

    # --- Retrieval ---
    top_k: int = 5
    # Cosine-distance ceiling; results farther than this count as "no evidence".
    max_distance: float = 0.65

    # --- Database ---
    database_url: str = "postgresql://cloudops:cloudops@localhost:5432/cloudops"

    # --- App ---
    log_level: str = "INFO"

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
