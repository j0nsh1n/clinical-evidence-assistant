"""Unit tests for the pure rule engine (no network, no I/O)."""

import pytest

from app.schemas.evidence import ClinicalQuestionType, EvidenceLevel, StudyDesign
from app.services import evidence_rules
from tests.fixtures.sample_abstracts import SAMPLES

_WITH_SIZE = [s for s in SAMPLES if s["expected_sample_size"] is not None]


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["name"] for s in SAMPLES])
def test_study_design_classification(sample):
    text = f"{sample['title']}. {sample['abstract']}"
    result = evidence_rules.classify_study_design(text)
    assert result.design == sample["expected_design"]
    assert result.matched_phrase, "classifier should record the phrase it matched"
    assert 0.0 < result.confidence <= 1.0


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["name"] for s in SAMPLES])
def test_evidence_level_mapping(sample):
    level, label = evidence_rules.map_evidence_level(sample["expected_design"])
    assert level == sample["expected_level"]
    assert label and label != "Unclear"


@pytest.mark.parametrize("sample", _WITH_SIZE, ids=[s["name"] for s in _WITH_SIZE])
def test_sample_size_extraction(sample):
    assert evidence_rules.extract_sample_size(sample["abstract"]) == sample["expected_sample_size"]


def test_unclear_when_no_design_signal():
    result = evidence_rules.classify_study_design(
        "This paper offers general thoughts on healthy living."
    )
    assert result.design == StudyDesign.unclear
    assert result.confidence == 0.0
    assert evidence_rules.map_evidence_level(result.design)[0] == EvidenceLevel.unclear


def test_synthesis_outranks_generic_review():
    # "systematic review and meta-analysis" must not fall through to narrative_review
    result = evidence_rules.classify_study_design("a systematic review and meta-analysis of trials")
    assert result.design == StudyDesign.meta_analysis


def test_sample_size_none_when_absent():
    assert evidence_rules.extract_sample_size("No counts are mentioned here at all.") is None


def test_question_type_detection_therapy():
    qtype = evidence_rules.detect_question_type("A trial of a new therapy to treat the disease.")
    assert qtype == ClinicalQuestionType.therapy


def test_caution_notes_always_disclaim_and_flag_observational():
    notes = evidence_rules.build_caution_notes(StudyDesign.cohort, sample_size=None, has_abstract=True)
    assert any("abstract only" in note for note in notes)
    assert any("causal inference" in note for note in notes)


def test_key_finding_prefers_conclusion_section():
    finding = evidence_rules.extract_key_finding(
        "Background text. Results text.",
        sections={"CONCLUSIONS": "The treatment was effective."},
    )
    assert finding == "The treatment was effective."


def test_pico_extracts_concise_distinct_phrases():
    hints = evidence_rules.extract_pico_hints(
        "In this trial, a total of 512 adults with moderate asthma were enrolled and "
        "randomized to the inhaled therapy or placebo. The primary outcome was the annual "
        "rate of asthma exacerbations over 12 months."
    )
    assert hints["population"] == "512 adults with moderate asthma"
    assert hints["intervention_or_exposure"] == "the inhaled therapy"
    assert hints["comparator"] == "placebo"
    assert hints["primary_outcome"] == "the annual rate of asthma exacerbations over 12 months"
    # The fields must not all collapse to the same sentence (the old behaviour).
    assert len({hints["population"], hints["intervention_or_exposure"], hints["comparator"]}) == 3


def test_pico_population_without_count():
    hints = evidence_rules.extract_pico_hints("Adults with type 2 diabetes were followed for five years.")
    assert hints["population"] == "Adults with type 2 diabetes"


def test_pico_returns_none_when_absent():
    hints = evidence_rules.extract_pico_hints("This document contains no structured clinical content.")
    assert hints["population"] is None
    assert hints["intervention_or_exposure"] is None
    assert hints["comparator"] is None
    assert hints["primary_outcome"] is None


def test_pico_risk_factor_exposure_excludes_leading_verb():
    hints = evidence_rules.extract_pico_hints(
        "We included 450 patients with lung cancer to examine smoking as a risk factor."
    )
    assert hints["intervention_or_exposure"] == "smoking"


def test_pico_population_at_end_of_text():
    hints = evidence_rules.extract_pico_hints("We enrolled 88 adults with chronic pain")
    assert hints["population"] == "88 adults with chronic pain"


def test_classify_from_publication_types_rct():
    result = evidence_rules.classify_from_publication_types(
        ["Journal Article", "Randomized Controlled Trial"]
    )
    assert result.design == StudyDesign.randomized_controlled_trial
    assert result.confidence >= 0.9


def test_classify_from_publication_types_synthesis_beats_review():
    result = evidence_rules.classify_from_publication_types(["Systematic Review", "Review"])
    assert result.design == StudyDesign.systematic_review


def test_combined_prefers_publication_type_over_text():
    # Text reads "cohort", but PubMed tags it an RCT -> trust the authoritative tag.
    result = evidence_rules.classify_study_design_combined(
        "a prospective cohort of patients", ["Randomized Controlled Trial"]
    )
    assert result.design == StudyDesign.randomized_controlled_trial


def test_combined_falls_back_to_text_when_pubtype_uninformative():
    result = evidence_rules.classify_study_design_combined(
        "a prospective cohort study of adults", ["Journal Article"]
    )
    assert result.design == StudyDesign.cohort


def test_compose_summary_sentence_and_bullets():
    summary, bullets = evidence_rules.compose_summary(
        study_design=StudyDesign.randomized_controlled_trial,
        evidence_level=EvidenceLevel.b,
        evidence_label="Moderate",
        population="512 adults with asthma",
        intervention_or_exposure="the inhaled therapy",
        comparator="placebo",
        primary_outcome="annual exacerbation rate",
        sample_size=512,
        key_finding="It reduced exacerbations",
        has_abstract=True,
    )
    assert "Randomized controlled trial (B · Moderate)" in summary
    assert "comparing the inhaled therapy with placebo" in summary
    assert any(b.startswith("Design:") for b in bullets)
    assert any("n = 512" in b for b in bullets)
    assert any(b.startswith("Compared:") for b in bullets)


def test_compose_summary_none_without_abstract():
    summary, _ = evidence_rules.compose_summary(
        study_design=StudyDesign.unclear,
        evidence_level=EvidenceLevel.unclear,
        evidence_label="Unclear",
        population=None,
        intervention_or_exposure=None,
        comparator=None,
        primary_outcome=None,
        sample_size=None,
        key_finding=None,
        has_abstract=False,
    )
    assert summary is None
