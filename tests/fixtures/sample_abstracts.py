"""A small labelled fixture set — the seed of an evaluation benchmark.

Abstracts are *synthetic* (no real patient data) but use realistic phrasing.
Each entry records the expected study design, evidence level, and—where the text
states one—the expected sample size. Growing this set is how we measure the
classifier honestly (e.g. "correct design in X of Y abstracts").
"""

from app.schemas.evidence import EvidenceLevel, StudyDesign

SAMPLES = [
    {
        "name": "rct_statin",
        "title": "A randomized controlled trial of atorvastatin in adults with high LDL cholesterol",
        "abstract": (
            "In this randomized, double-blind, placebo-controlled trial we enrolled 1240 "
            "adults with elevated LDL cholesterol. Participants were randomized to "
            "atorvastatin or placebo. The primary outcome was major cardiovascular events "
            "at 24 months. Atorvastatin reduced major cardiovascular events compared with placebo."
        ),
        "expected_design": StudyDesign.randomized_controlled_trial,
        "expected_level": EvidenceLevel.b,
        "expected_sample_size": 1240,
    },
    {
        "name": "meta_analysis_ssri",
        "title": "SSRIs for major depression: a systematic review and meta-analysis",
        "abstract": (
            "We conducted a systematic review and meta-analysis of randomized trials "
            "evaluating SSRIs for major depressive disorder. A total of 4521 patients "
            "were included across 23 trials. SSRIs improved response rates."
        ),
        "expected_design": StudyDesign.meta_analysis,
        "expected_level": EvidenceLevel.a,
        "expected_sample_size": 4521,
    },
    {
        "name": "cohort_coffee",
        "title": "Coffee consumption and longevity: a prospective cohort study",
        "abstract": (
            "In this prospective cohort study we followed 8000 adults for 10 years to "
            "examine the association between coffee consumption and all-cause mortality."
        ),
        "expected_design": StudyDesign.cohort,
        "expected_level": EvidenceLevel.b,
        "expected_sample_size": 8000,
    },
    {
        "name": "case_control_smoking",
        "title": "Smoking and lung cancer: a case-control study",
        "abstract": (
            "In this case-control study we included 450 patients with lung cancer and 450 "
            "matched controls to examine smoking as a risk factor for disease."
        ),
        "expected_design": StudyDesign.case_control,
        "expected_level": EvidenceLevel.c,
        "expected_sample_size": 450,
    },
    {
        "name": "cross_sectional_burnout",
        "title": "Burnout among hospital staff",
        "abstract": (
            "In this cross-sectional survey, a total of 500 nurses were included to "
            "estimate the prevalence of burnout in tertiary hospitals."
        ),
        "expected_design": StudyDesign.cross_sectional,
        "expected_level": EvidenceLevel.c,
        "expected_sample_size": 500,
    },
    {
        "name": "case_report_rare",
        "title": "An unusual presentation of disease X",
        "abstract": (
            "We report a case of a rare presentation of disease X in a previously healthy "
            "young patient, and discuss the diagnostic work-up."
        ),
        "expected_design": StudyDesign.case_report,
        "expected_level": EvidenceLevel.d,
        "expected_sample_size": None,
    },
    {
        "name": "narrative_review_overview",
        "title": "Management of hypertension: an overview",
        "abstract": (
            "This narrative review summarizes current understanding of the management of "
            "hypertension and highlights areas of ongoing debate."
        ),
        "expected_design": StudyDesign.narrative_review,
        "expected_level": EvidenceLevel.d,
        "expected_sample_size": None,
    },
]
