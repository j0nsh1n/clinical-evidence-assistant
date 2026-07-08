"""Pydantic models for the analysis history / reading list."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.evidence import EvidenceAnalysis


class HistoryListItem(BaseModel):
    """One row in the library list (no full analysis payload)."""

    id: int
    source: str
    article_id: Optional[str] = None
    title: Optional[str] = None
    journal: Optional[str] = None
    year: Optional[str] = None
    study_design: Optional[str] = None
    evidence_level: Optional[str] = None
    is_retracted: bool = False
    notes: str = ""
    analyzed_at: str


class HistoryList(BaseModel):
    count: int
    items: List[HistoryListItem] = Field(default_factory=list)


class HistoryEntry(BaseModel):
    """A stored analysis re-openable as a full evidence card."""

    id: int
    notes: str = ""
    analyzed_at: str
    analysis: EvidenceAnalysis


class NotesUpdate(BaseModel):
    notes: str = ""
