"""Orchestration: obtain an article -> rule-based extraction -> EvidenceAnalysis.

Sources are pluggable: each source module exposes ``search_articles(query)`` and
``fetch_article(id)`` returning the same dict shape, so the pipeline is
source-agnostic. Route handlers stay thin.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.schemas.evidence import (
    AnalyzeRequest,
    ArticleSummary,
    EvidenceAnalysis,
    ExtractionMethod,
)
from app.services import europepmc_service, evidence_rules, pubmed_service, unpaywall_service

# Pluggable article sources. Each exposes search_articles() and fetch_article().
SOURCES = {
    "pubmed": pubmed_service,
    "europepmc": europepmc_service,
}
DEFAULT_SOURCE = "europepmc"


def analyze_article(request: AnalyzeRequest) -> EvidenceAnalysis:
    """Resolve the request to an article dict, then analyze it."""
    if request.has_inline_text():
        article: Dict = {
            "article_id": request.resolved_id(),
            "source_database": "manual",
            "title": request.title,
            "abstract": request.abstract,
            "abstract_sections": {},
        }
    else:
        article_id = request.resolved_id()
        if not article_id:
            raise ValueError("Provide a 'pmid'/'article_id' or an 'abstract' to analyze.")
        fetcher = SOURCES.get(request.resolved_source())
        if fetcher is None:
            raise ValueError(f"Unknown source '{request.resolved_source()}'.")
        article = fetcher.fetch_article(article_id)

    return analyze_text(article)


def _resolve_open_access(article: Dict) -> Dict[str, Optional[str]]:
    """Use the source's OA info if present, else ask Unpaywall by DOI."""
    is_oa = bool(article.get("is_open_access"))
    oa_url = article.get("oa_url")
    if not oa_url and article.get("doi"):
        found = unpaywall_service.find_open_access(article.get("doi"))
        is_oa = is_oa or found["is_open_access"]
        oa_url = found["oa_url"]
    return {"is_open_access": is_oa, "oa_url": oa_url}


def analyze_text(article: Dict) -> EvidenceAnalysis:
    """Run the rule pipeline over a normalized article dict."""
    title = article.get("title") or ""
    abstract = article.get("abstract") or ""
    sections = article.get("abstract_sections") or {}
    combined = f"{title}. {abstract}".strip()
    has_abstract = bool(abstract.strip())
    pub_types = article.get("publication_types") or []

    design_result = evidence_rules.classify_study_design_combined(combined, pub_types)
    question_type = evidence_rules.detect_question_type(combined)
    sample_size = evidence_rules.extract_sample_size(abstract or combined)
    pico = evidence_rules.extract_pico_hints(abstract or combined)
    key_finding = evidence_rules.extract_key_finding(abstract, sections)
    level, label = evidence_rules.map_evidence_level(design_result.design)
    cautions = evidence_rules.build_caution_notes(design_result.design, sample_size, has_abstract)
    if article.get("is_preprint"):
        cautions.insert(0, "Preprint — not yet peer-reviewed.")

    summary, bullets = evidence_rules.compose_summary(
        study_design=design_result.design,
        evidence_level=level,
        evidence_label=label,
        population=pico["population"],
        intervention_or_exposure=pico["intervention_or_exposure"],
        comparator=pico["comparator"],
        primary_outcome=pico["primary_outcome"],
        sample_size=sample_size,
        key_finding=key_finding,
        has_abstract=has_abstract,
    )

    oa = _resolve_open_access(article)

    extractable = (sample_size, key_finding, pico["population"])
    completeness = sum(value is not None for value in extractable) / len(extractable)
    confidence = round(0.7 * design_result.confidence + 0.3 * completeness, 2)

    return EvidenceAnalysis(
        article_id=article.get("article_id"),
        source_database=article.get("source_database", "pubmed"),
        title=article.get("title"),
        abstract=article.get("abstract"),
        authors=article.get("authors") or [],
        journal=article.get("journal"),
        year=article.get("year"),
        citation=article.get("citation"),
        doi=article.get("doi"),
        publication_types=pub_types,
        keywords=article.get("keywords") or [],
        is_open_access=oa["is_open_access"],
        oa_url=oa["oa_url"],
        is_preprint=bool(article.get("is_preprint")),
        study_design=design_result.design,
        study_design_confidence=design_result.confidence,
        study_design_evidence=design_result.matched_phrase,
        clinical_question_type=question_type,
        population=pico["population"],
        sample_size=sample_size,
        intervention_or_exposure=pico["intervention_or_exposure"],
        comparator=pico["comparator"],
        primary_outcome=pico["primary_outcome"],
        key_finding=key_finding,
        key_points_summary=summary,
        key_points=bullets,
        evidence_level=level,
        evidence_label=label,
        confidence_score=confidence,
        caution_notes=cautions,
        extraction_method=ExtractionMethod.rules,
    )


def search(query: str, source: str = DEFAULT_SOURCE, max_results: int = 20) -> List[ArticleSummary]:
    """Search a source and attach a provisional design/level hint to each result."""
    fetcher = SOURCES.get((source or DEFAULT_SOURCE).lower(), SOURCES[DEFAULT_SOURCE])
    rows = fetcher.search_articles(query, max_results=max_results)
    summaries: List[ArticleSummary] = []
    for row in rows:
        design = evidence_rules.classify_from_publication_types(row.get("publication_types"))
        level, label = evidence_rules.map_evidence_level(design.design)
        summaries.append(
            ArticleSummary(
                source=row.get("source", "pubmed"),
                article_id=row.get("article_id") or row.get("pmid") or "",
                pmid=row.get("pmid"),
                title=row.get("title"),
                authors=row.get("authors") or [],
                journal=row.get("journal"),
                year=row.get("year"),
                publication_types=row.get("publication_types") or [],
                doi=row.get("doi"),
                is_preprint=bool(row.get("is_preprint")),
                is_open_access=bool(row.get("is_open_access")),
                study_design=design.design,
                evidence_level=level,
                evidence_label=label,
            )
        )
    return summaries
