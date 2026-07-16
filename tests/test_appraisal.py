"""CASP-style appraisal signals: design-specific phrase detection, never the grade."""

from app.schemas.evidence import AppraisalSignalStatus, EvidenceLevel, StudyDesign
from app.services import evidence_rules, evidence_service


def test_rct_checklist_detects_core_signals():
    abstract = (
        "In this randomized, double-blind, placebo-controlled trial, 320 patients "
        "were enrolled. Analysis was by intention-to-treat. The hazard ratio was "
        "0.75 (95% CI 0.60-0.90)."
    )
    checklist = evidence_rules.build_appraisal_checklist(
        StudyDesign.randomized_controlled_trial, abstract
    )
    by_id = {s.id: s for s in checklist.signals}
    assert checklist.label.startswith("RCT")
    assert by_id["randomization"].status == AppraisalSignalStatus.mentioned
    assert by_id["blinding"].status == AppraisalSignalStatus.mentioned
    assert "double" in (by_id["blinding"].matched_phrase or "").lower()
    assert by_id["intention_to_treat"].status == AppraisalSignalStatus.mentioned
    assert by_id["effect_precision"].status == AppraisalSignalStatus.mentioned
    assert checklist.mentioned_count >= 4
    assert checklist.total == len(checklist.signals) >= 6


def test_open_label_is_blinding_concern():
    abstract = (
        "This randomized open-label trial assigned adults to drug or usual care."
    )
    checklist = evidence_rules.build_appraisal_checklist(
        StudyDesign.randomized_controlled_trial, abstract
    )
    blinding = next(s for s in checklist.signals if s.id == "blinding")
    assert blinding.status == AppraisalSignalStatus.concern
    assert "open" in (blinding.matched_phrase or "").lower()
    assert checklist.concern_count >= 1


def test_cohort_checklist_uses_observational_cues():
    abstract = (
        "In this prospective cohort of adults we examined smoking exposure. "
        "Outcomes were ascertained from hospital records. Models were adjusted for "
        "age and sex. Median follow-up was 8 years. The adjusted hazard ratio was "
        "1.4 (95% CI 1.1-1.8)."
    )
    checklist = evidence_rules.build_appraisal_checklist(StudyDesign.cohort, abstract)
    by_id = {s.id: s for s in checklist.signals}
    assert checklist.label.startswith("Cohort")
    assert by_id["confounding_adjustment"].status == AppraisalSignalStatus.mentioned
    assert by_id["followup_duration"].status == AppraisalSignalStatus.mentioned
    assert by_id["effect_precision"].status == AppraisalSignalStatus.mentioned
    # RCT-only cues must not appear on the cohort list.
    assert "randomization" not in by_id
    assert "blinding" not in by_id


def test_meta_analysis_checklist_detects_search_and_prisma():
    abstract = (
        "We systematically searched PubMed and Embase. Inclusion criteria were "
        "defined a priori. Risk of bias was assessed with Cochrane tools. "
        "Heterogeneity was summarized with I². Reporting followed PRISMA."
    )
    checklist = evidence_rules.build_appraisal_checklist(
        StudyDesign.meta_analysis, abstract
    )
    by_id = {s.id: s for s in checklist.signals}
    assert by_id["search_strategy"].status == AppraisalSignalStatus.mentioned
    assert by_id["study_quality"].status == AppraisalSignalStatus.mentioned
    assert by_id["heterogeneity"].status == AppraisalSignalStatus.mentioned
    assert by_id["reporting_standard"].status == AppraisalSignalStatus.mentioned


def test_not_found_when_text_silent():
    checklist = evidence_rules.build_appraisal_checklist(
        StudyDesign.randomized_controlled_trial,
        "Adults with asthma received a new inhaler and symptoms improved.",
    )
    by_id = {s.id: s for s in checklist.signals}
    assert by_id["randomization"].status == AppraisalSignalStatus.not_found
    assert by_id["blinding"].status == AppraisalSignalStatus.not_found
    assert by_id["intention_to_treat"].status == AppraisalSignalStatus.not_found
    assert by_id["power_calculation"].status == AppraisalSignalStatus.not_found


def test_full_text_methods_can_supply_signals():
    abstract = "This cohort study examined long-term outcomes after exposure."
    sections = {
        "METHODS": (
            "Exposure was defined from pharmacy records. Outcomes were ascertained "
            "from national registries. Models were adjusted for age, sex, and comorbidity. "
            "Median follow-up was 5 years."
        ),
    }
    checklist = evidence_rules.build_appraisal_checklist(
        StudyDesign.cohort, abstract, sections
    )
    by_id = {s.id: s for s in checklist.signals}
    assert by_id["exposure_defined"].status == AppraisalSignalStatus.mentioned
    assert by_id["outcome_ascertainment"].status == AppraisalSignalStatus.mentioned
    assert by_id["confounding_adjustment"].status == AppraisalSignalStatus.mentioned


def test_service_includes_checklist_without_changing_grade():
    article = {
        "article_id": "MED/1",
        "source_database": "europepmc",
        "title": "A randomized controlled trial of drug X",
        "abstract": (
            "In this randomized, double-blind, placebo-controlled trial, 320 patients "
            "were enrolled. The primary outcome was symptom improvement. "
            "HR 0.80 (95% CI 0.70-0.92)."
        ),
        "abstract_sections": {},
        "publication_types": ["Journal Article"],
        "full_text_sections": {},
    }
    result = evidence_service.analyze_text(article)
    assert result.study_design == StudyDesign.randomized_controlled_trial
    assert result.evidence_level == EvidenceLevel.b
    assert result.appraisal_checklist is not None
    assert result.appraisal_checklist.total >= 6
    assert result.appraisal_checklist.mentioned_count >= 2
    # Grade is still design→map only (RCT → B), independent of signal count.
    level, _ = evidence_rules.map_evidence_level(result.study_design)
    assert result.evidence_level == level


def test_unclear_design_gets_generic_checklist():
    checklist = evidence_rules.build_appraisal_checklist(
        StudyDesign.unclear, "We studied some adults and measured several outcomes."
    )
    assert "generic" in checklist.label.lower() or "unclear" in checklist.label.lower()
    assert checklist.total >= 1
