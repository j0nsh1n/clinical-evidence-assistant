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
    app_version: str = "1.1.0"

    # NCBI E-utilities (PubMed). NCBI asks every caller to identify themselves by
    # email; an API key raises the rate limit from 3 to 10 requests/second.
    ncbi_email: str = "anonymous@example.com"
    ncbi_api_key: Optional[str] = None
    ncbi_timeout_seconds: int = 30

    # Optional LLM refinement (Phase 8). Two providers are supported; when none is
    # configured the app falls back to the rules-based summary.
    #   • Ollama    — a local model (free, no API key). Set OLLAMA_MODEL (e.g.
    #                 "llama3.1") after pulling it; it is reached over OLLAMA_HOST.
    #   • Anthropic — the cloud Claude API. Set ANTHROPIC_API_KEY.
    # LLM_PROVIDER selects one: "auto" (default) prefers a local Ollama model, then
    # Anthropic; "ollama" or "anthropic" force that provider.
    llm_provider: str = "auto"

    # Local analysis history (SQLite reading list). Relative to the project root.
    history_db_path: str = "data/history.db"
    anthropic_api_key: Optional[str] = None
    llm_model: str = "claude-sonnet-4-6"
    ollama_host: str = "http://localhost:11434"
    ollama_model: Optional[str] = None
    llm_timeout_seconds: int = 120


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read once per process)."""
    return Settings()
