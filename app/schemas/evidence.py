"""Pydantic data models for the clinical evidence analysis feature.

This module is the *stable contract* between the extraction pipeline and the
API/UI. Both the rule-based extractor and any future LLM-assisted extractor must
produce an :class:`EvidenceAnalysis`; only ``extraction_method`` distinguishes
them. Designing this schema first (per the project plan) keeps the rule-based and
LLM paths interchangeable later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class StudyDesign(str, Enum):
    """Recognised study designs, ordered loosely from strongest to weakest."""

    systematic_review = "systematic_review"
    meta_analysis = "meta_analysis"
    randomized_controlled_trial = "randomized_controlled_trial"
    cohort = "cohort"
    case_control = "case_control"
    cross_sectional = "cross_sectional"
    case_series = "case_series"
    case_report = "case_report"
    narrative_review = "narrative_review"
    expert_opinion = "expert_opinion"
    unclear = "unclear"


class EvidenceLevel(str, Enum):
    """Provisional evidence level (Oxford-style A/B/C/D + unclear)."""

    a = "A"  # High
    b = "B"  # Moderate
    c = "C"  # Lower
    d = "D"  # Weak
    unclear = "unclear"


class ClinicalQuestionType(str, Enum):
    therapy = "therapy"
    diagnosis = "diagnosis"
    prognosis = "prognosis"
    etiology_harm = "etiology_harm"
    prevention = "prevention"
    descriptive_other = "descriptive_other"


class ExtractionMethod(str, Enum):
    rules = "rules"
    rules_llm = "rules+llm"


class AnalyzeRequest(BaseModel):
    """Input to the analyzer.

    Supply either a ``pmid`` (the abstract is fetched from PubMed) or pass
    ``title`` / ``abstract`` text directly (useful for testing and for articles
    already held by the caller).
    """

    source: Optional[str] = Field(default=None, description="Article source: 'pubmed' or 'europepmc'.")
    article_id: Optional[str] = Field(default=None, description="Source-native article id to fetch.")
    pmid: Optional[str] = Field(default=None, description="PubMed ID (shorthand for source='pubmed').")
    title: Optional[str] = Field(default=None, description="Article title, if supplying text directly.")
    abstract: Optional[str] = Field(default=None, description="Abstract text, if supplying text directly.")

    def has_inline_text(self) -> bool:
        return bool(self.abstract and self.abstract.strip())

    def resolved_source(self) -> str:
        return (self.source or "pubmed").strip().lower()

    def resolved_id(self) -> Optional[str]:
        return self.article_id or self.pmid


class StudyDesignResult(BaseModel):
    """Output of the study-design classifier, with a transparency trail."""

    design: StudyDesign = StudyDesign.unclear
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    matched_phrase: Optional[str] = Field(
        default=None,
        description="The phrase that triggered the classification (for debugging/transparency).",
    )


class EvidenceAnalysis(BaseModel):
    """The full structured result returned to the API/UI."""

    # --- provenance ---
    article_id: Optional[str] = None
    source_database: str = "pubmed"
    title: Optional[str] = None
    abstract: Optional[str] = None

    # --- article metadata ---
    authors: List[str] = Field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[str] = None
    citation: Optional[str] = None
    doi: Optional[str] = None
    publication_types: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    is_open_access: bool = False
    oa_url: Optional[str] = None
    is_preprint: bool = False

    # --- structured extraction ---
    study_design: StudyDesign = StudyDesign.unclear
    study_design_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    study_design_evidence: Optional[str] = Field(
        default=None, description="Matched phrase that drove the study-design call."
    )
    clinical_question_type: ClinicalQuestionType = ClinicalQuestionType.descriptive_other
    population: Optional[str] = None
    sample_size: Optional[int] = None
    intervention_or_exposure: Optional[str] = None
    comparator: Optional[str] = None
    primary_outcome: Optional[str] = None
    key_finding: Optional[str] = None
    limitations: Optional[str] = None
    key_points_summary: Optional[str] = None
    key_points: List[str] = Field(default_factory=list)

    # --- provisional scoring ---
    evidence_level: EvidenceLevel = EvidenceLevel.unclear
    evidence_label: str = "Unclear"
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    caution_notes: List[str] = Field(default_factory=list)

    # --- meta ---
    extraction_method: ExtractionMethod = ExtractionMethod.rules
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ArticleSummary(BaseModel):
    """One row in a search result list (lightweight; no abstract).

    Carries a *provisional* design/level hint derived cheaply from PubMed
    publication types, so the list conveys evidence strength at a glance without
    a full per-article analysis.
    """

    source: str = "pubmed"
    article_id: str
    pmid: Optional[str] = None
    title: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[str] = None
    publication_types: List[str] = Field(default_factory=list)
    doi: Optional[str] = None
    is_preprint: bool = False
    is_open_access: bool = False
    study_design: StudyDesign = StudyDesign.unclear
    evidence_level: EvidenceLevel = EvidenceLevel.unclear
    evidence_label: str = "Unclear"


class SearchResponse(BaseModel):
    query: str
    count: int
    results: List[ArticleSummary] = Field(default_factory=list)
