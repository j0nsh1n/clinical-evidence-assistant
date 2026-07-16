"""Open-access full text fills facts the abstract omits (sample size, extra stats,
PICO, design tie-breaks) without overriding abstract hits. Sources are not called —
the article dict, including ``full_text_sections``, is built directly."""

from app.schemas.evidence import EvidenceLevel, StudyDesign
from app.services import evidence_rules, evidence_service


def _article(abstract, full_text_sections=None, title=None, pub_types=None):
    return {
        "article_id": "MED/1",
        "source_database": "europepmc",
        "title": title or "A prospective cohort study of an inhaled therapy in adults",
        "abstract": abstract,
        "abstract_sections": {},
        "publication_types": pub_types or ["Journal Article"],
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


def test_extract_with_fulltext_pure_helper_matches_service():
    sections = {
        "METHODS": "A total of 512 adults with moderate asthma were enrolled.",
        "RESULTS": "The adjusted hazard ratio was 0.75 (95% CI 0.60-0.90; p=0.01).",
    }
    abstract = (
        "This prospective cohort study followed adults with moderate asthma "
        "to assess exacerbation rates."
    )
    extraction = evidence_rules.extract_with_fulltext(abstract, sections)
    assert extraction.sample_size == 512
    assert extraction.used_full_text is True
    assert len(extraction.reported_statistics) >= 1

    result = evidence_service.analyze_text(_article(abstract, sections))
    assert result.sample_size == extraction.sample_size
    assert result.used_full_text == extraction.used_full_text
    assert result.study_design == extraction.design.design
    assert result.population == extraction.pico["population"]


def test_section_text_prefers_exact_over_substring():
    sections = {
        "STATISTICAL METHODS": "noise n = 3",
        "METHODS": "A total of 99 patients were enrolled.",
    }
    text = evidence_rules.section_text(sections, "METHOD")
    assert text is not None
    assert "99 patients" in text


# ---------------------------------------------------------------------------
# Phase 2: PICO from Methods + design tie-breaks when abstract is unclear
# ---------------------------------------------------------------------------


def test_full_text_fills_missing_pico_fields():
    article = _article(
        "This prospective cohort study assessed treatment effects on exacerbations.",
        {
            "METHODS": (
                "A total of 512 adults with moderate asthma were randomized to the "
                "inhaled therapy or placebo. The primary outcome was the annual rate "
                "of asthma exacerbations over 12 months."
            ),
        },
        title="Treatment effects in asthma",
    )
    result = evidence_service.analyze_text(article)
    assert result.population == "512 adults with moderate asthma"
    assert result.intervention_or_exposure == "the inhaled therapy"
    assert result.comparator == "placebo"
    assert result.primary_outcome is not None
    assert "exacerbation" in result.primary_outcome.lower()
    assert result.used_full_text is True
    # design still from abstract ("prospective cohort") — not overridden
    assert result.study_design == StudyDesign.cohort


def test_abstract_pico_is_not_overridden_by_full_text():
    article = _article(
        "In this cohort study, 200 adults with asthma received the inhaled therapy "
        "or placebo. The primary outcome was exacerbation rate.",
        {
            "METHODS": (
                "We enrolled 512 children with eczema randomized to cream or usual care. "
                "Primary outcome was itch score."
            ),
        },
    )
    result = evidence_service.analyze_text(article)
    assert result.population == "200 adults with asthma"
    assert result.intervention_or_exposure == "the inhaled therapy"
    assert result.comparator == "placebo"
    assert "exacerbation" in (result.primary_outcome or "").lower()
    # Abstract already complete for these fields; Methods must not replace them.
    assert "children" not in (result.population or "").lower()
    assert "cream" not in (result.intervention_or_exposure or "").lower()


def test_design_tiebreak_from_methods_when_abstract_unclear():
    article = _article(
        "We studied outcomes after a new intervention in adults with asthma.",
        {
            "METHODS": (
                "This was a prospective cohort study. A total of 400 adults with "
                "asthma were enrolled and followed for 12 months."
            ),
        },
        title="Outcomes after a new intervention",
        pub_types=["Journal Article"],
    )
    result = evidence_service.analyze_text(article)
    assert result.study_design == StudyDesign.cohort
    assert result.evidence_level == EvidenceLevel.b
    assert result.study_design_evidence is not None
    assert result.study_design_evidence.lower().startswith("full text:")
    assert result.sample_size == 400
    assert result.used_full_text is True


def test_clear_abstract_design_is_not_overridden_by_methods():
    """Full text must not reclassify when the abstract already has a design cue."""
    article = _article(
        "This case-control study examined risk factors for hospitalisation.",
        {
            "METHODS": (
                "Participants were randomly assigned to intervention or control "
                "in a randomized controlled trial."
            ),
        },
        title="Risk factors for hospitalisation",
    )
    result = evidence_service.analyze_text(article)
    assert result.study_design == StudyDesign.case_control
    assert result.evidence_level == EvidenceLevel.c
    assert result.study_design_evidence is not None
    assert not result.study_design_evidence.lower().startswith("full text:")


def test_design_stays_unclear_when_methods_also_silent():
    article = _article(
        "We studied outcomes in adults with asthma after an intervention.",
        {"METHODS": "Adults with asthma attended clinic visits for 12 months."},
        title="Outcomes in asthma",
    )
    result = evidence_service.analyze_text(article)
    assert result.study_design == StudyDesign.unclear
    assert result.evidence_level == EvidenceLevel.unclear
