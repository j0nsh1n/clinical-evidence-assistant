"""AI status route (the app never starts Ollama — this just reports honestly)."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.llm import LLMStatus
from app.services import llm_service

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/status", response_model=LLMStatus)
def llm_status() -> LLMStatus:
    return LLMStatus(**llm_service.status())
