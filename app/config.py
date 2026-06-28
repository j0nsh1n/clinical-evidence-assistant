"""Application configuration, loaded from environment variables / a .env file."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Clinical Evidence Assistant"
    app_version: str = "0.3.0"

    # NCBI E-utilities (PubMed). NCBI asks every caller to identify themselves by
    # email; an API key raises the rate limit from 3 to 10 requests/second.
    ncbi_email: str = "anonymous@example.com"
    ncbi_api_key: Optional[str] = None
    ncbi_timeout_seconds: int = 30


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read once per process)."""
    return Settings()
