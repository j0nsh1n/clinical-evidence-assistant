"""Open-access full text fills facts the abstract omits (sample size, extra stats)
without changing the rule-based grade. Sources are not called — the article dict,
including ``full_text_sections``, is built directly."""

from app.services import evidence_service


def _article(abstract, full_text_sections=None):
    return {
        "article_id": "MED/1",
        "source_database": "europepmc",
        "title": "A prospective cohort study of an inhaled therapy in adults",
        "abstract": abstract,
        "abstract_sections": {},
        "publication_types": ["Journal Article"],
        "full_text_sections": full_text_sections or {},
    }


def test_full_text_fills_missing_sample_size_and_stats():
    article = _article(
        "This prospective cohort study followed adults with moderate asthma to assess exacerbation rates.",
        {
            "METHODS": "A total of 512 adults with moderate asthma were enrolled.",
            "RESULTS": "The adjusted hazard ratio was 0.75 (95% CI 0.60-0.90; p=0.01).",
        },
    )
    result = evidence_service.analyze_text(article)
    assert result.sample_size == 512
    assert result.used_full_text is True
    assert len(result.reported_statistics) >= 1
    assert any("full text" in note.lower() for note in result.caution_notes)
    # the grade still comes from the abstract-detected design (cohort -> B)
    assert result.evidence_level.value == "B"


def test_abstract_sample_size_is_not_overridden_by_full_text():
    article = _article(
        "In this cohort study, a total of 200 patients were enrolled and followed.",
        {"METHODS": "We screened 5000 people and enrolled 512."},
    )
    result = evidence_service.analyze_text(article)
    assert result.sample_size == 200  # abstract wins; no Results section -> no stats added
    assert result.used_full_text is False


def test_no_full_text_leaves_flag_false():
    article = _article("In this cohort study, a total of 200 patients were enrolled.")
    result = evidence_service.analyze_text(article)
    assert result.used_full_text is False
