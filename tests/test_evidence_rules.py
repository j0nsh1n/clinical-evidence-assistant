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
