"""Orchestration: obtain article text -> rule-based extraction -> EvidenceAnalysis.

The route handler stays thin; all business logic lives here and in
:mod:`app.services.evidence_rules`.
"""

from __future__ import annotations

from typing import Dict

from app.schemas.evidence import AnalyzeRequest, EvidenceAnalysis, ExtractionMethod
from app.services import evidence_rules, pubmed_service


def analyze_article(request: AnalyzeRequest) -> EvidenceAnalysis:
    """Resolve the request to article text, then analyze it.

    Raises ``ValueError`` if neither a PMID nor inline abstract text is provided.
    """
    if request.has_inline_text():
        article: Dict = {
            "article_id": request.pmid,
            "source_database": "manual",
            "title": request.title,
            "abstract": request.abstract,
            "abstract_sections": {},
        }
    elif request.pmid:
        article = pubmed_service.fetch_article(request.pmid)
    else:
        raise ValueError("Provide either a 'pmid' or an 'abstract' to analyze.")

    return analyze_text(article)


def analyze_text(article: Dict) -> EvidenceAnalysis:
    """Run the rule pipeline over a normalized article dict."""
    title = article.get("title") or ""
    abstract = article.get("abstract") or ""
    sections = article.get("abstract_sections") or {}
    combined = f"{title}. {abstract}".strip()
    has_abstract = bool(abstract.strip())

    design_result = evidence_rules.classify_study_design(combined)
    question_type = evidence_rules.detect_question_type(combined)
    sample_size = evidence_rules.extract_sample_size(abstract or combined)
    pico = evidence_rules.extract_pico_hints(abstract or combined)
    key_finding = evidence_rules.extract_key_finding(abstract, sections)
    level, label = evidence_rules.map_evidence_level(design_result.design)
    cautions = evidence_rules.build_caution_notes(design_result.design, sample_size, has_abstract)

    # Overall confidence blends design confidence with extraction completeness.
    extractable = (sample_size, key_finding, pico["population"])
    completeness = sum(value is not None for value in extractable) / len(extractable)
    confidence = round(0.7 * design_result.confidence + 0.3 * completeness, 2)

    return EvidenceAnalysis(
        article_id=article.get("article_id"),
        source_database=article.get("source_database", "pubmed"),
        title=article.get("title"),
        abstract=article.get("abstract"),
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
        evidence_level=level,
        evidence_label=label,
        confidence_score=confidence,
        caution_notes=cautions,
        extraction_method=ExtractionMethod.rules,
    )
