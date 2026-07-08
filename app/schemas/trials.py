"""Pydantic models for ClinicalTrials.gov records (a separate shape from articles)."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class TrialSummary(BaseModel):
    """One row in a trials search list."""

    nct_id: str
    title: Optional[str] = None
    status: Optional[str] = None
    phase: Optional[str] = None
    study_type: Optional[str] = None
    conditions: List[str] = Field(default_factory=list)
    enrollment: Optional[int] = None


class TrialSearchResponse(BaseModel):
    query: str
    count: int
    results: List[TrialSummary] = Field(default_factory=list)


class TrialRecord(TrialSummary):
    """A full trial record for the trial-detail card."""

    brief_summary: Optional[str] = None
    interventions: List[str] = Field(default_factory=list)
    sponsor: Optional[str] = None
    start_date: Optional[str] = None
    completion_date: Optional[str] = None
    url: str
