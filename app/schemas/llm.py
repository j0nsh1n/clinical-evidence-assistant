"""Pydantic models for the optional AI endpoints (status, PICO suggestions, Q&A)."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class LLMStatus(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    reachable: bool = False
    model_available: bool = False
    detail: Optional[str] = None


class PicoSuggestRequest(BaseModel):
    title: Optional[str] = None
    abstract: str
    fields: List[str] = Field(description="Which missing PICO fields to suggest.")


class PicoSuggestResponse(BaseModel):
    suggestions: Dict[str, str] = Field(default_factory=dict)


class AskRequest(BaseModel):
    source: str = "europepmc"
    article_id: str
    question: str


class AskResponse(BaseModel):
    answer: str
    quotes: List[str] = Field(default_factory=list)
    basis: str = Field(default="full text", description="What the answer was read from: 'full text' or 'abstract'.")
