"""A labelled benchmark for the rule-based classifier.

Synthetic but realistic abstracts (no real patient data), each tagged with the
*true* study design, evidence level, and stated sample size. ``evaluate()`` runs
the text-only rule engine over them and reports accuracy — the figure quoted in
the README. Includes a few deliberately hard cases (a cohort that never says
"cohort", a survey that never says "cross-sectional", a systematic review whose
abstract mentions "meta-analysis") so the number is honest, not cherry-picked.
"""

from app.schemas.evidence import EvidenceLevel as L
from app.schemas.evidence import StudyDesign as D
from app.services import evidence_rules

BENCHMARK = [
    {"name": "ma_ssri", "design": D.meta_analysis, "level": L.a, "n": 4521,
     "title": "SSRIs for major depression: a systematic review and meta-analysis",
     "abstract": "We conducted a systematic review and meta-analysis of randomized trials evaluating SSRIs for major depressive disorder. A total of 4521 patients were included across 23 trials. SSRIs improved response rates."},
    {"name": "ma_exercise", "design": D.meta_analysis, "level": L.a, "n": 1890,
     "title": "Exercise for depression: a meta-analysis",
     "abstract": "We performed a meta-analysis of randomized trials of structured exercise for depression. Twelve trials with n = 1890 participants were pooled, showing a moderate benefit."},
    {"name": "sr_screening", "design": D.systematic_review, "level": L.a, "n": None,
     "title": "Screening strategies for colorectal cancer: a systematic review",
     "abstract": "This systematic review summarized studies of colorectal cancer screening strategies and their diagnostic yield. No meta-analysis was performed owing to heterogeneity."},
    {"name": "sr_guideline", "design": D.systematic_review, "level": L.a, "n": None,
     "title": "Antibiotic prophylaxis in surgery: a systematic review to inform guidelines",
     "abstract": "A systematic review was undertaken to inform guideline recommendations on perioperative antibiotic prophylaxis."},
    {"name": "rct_statin", "design": D.randomized_controlled_trial, "level": L.b, "n": 1240,
     "title": "A randomized controlled trial of atorvastatin in adults with high LDL cholesterol",
     "abstract": "In this randomized, double-blind, placebo-controlled trial we enrolled 1240 adults with elevated LDL cholesterol. Participants were randomized to atorvastatin or placebo. Atorvastatin reduced major cardiovascular events."},
    {"name": "rct_open_label", "design": D.randomized_controlled_trial, "level": L.b, "n": 300,
     "title": "Open-label trial of a blood-pressure programme",
     "abstract": "Adults with hypertension were randomly assigned to a structured programme or usual care in this open-label trial. A total of 300 participants were enrolled and followed for one year."},
    {"name": "rct_vaccine", "design": D.randomized_controlled_trial, "level": L.b, "n": 1500,
     "title": "A trial of a new vaccine",
     "abstract": "In a double-blind, placebo-controlled trial, 1500 participants were enrolled and received the vaccine or placebo. The vaccine reduced symptomatic infection."},
    {"name": "rct_crossover", "design": D.randomized_controlled_trial, "level": L.b, "n": 48,
     "title": "A randomized crossover trial of two inhalers",
     "abstract": "In this randomized crossover trial, we enrolled 48 patients who received both inhalers in random order with a washout period."},
    {"name": "coh_coffee", "design": D.cohort, "level": L.b, "n": 8000,
     "title": "Coffee consumption and longevity: a prospective cohort study",
     "abstract": "In this prospective cohort study we followed 8000 adults for 10 years to examine the association between coffee consumption and all-cause mortality."},
    {"name": "coh_retro_icu", "design": D.cohort, "level": L.b, "n": 2300,
     "title": "Statin use and ICU outcomes",
     "abstract": "In a retrospective cohort study, 2300 patients were included to examine whether prior statin use was associated with 30-day mortality after ICU admission."},
    {"name": "coh_birth", "design": D.cohort, "level": L.b, "n": 1200,
     "title": "Early-life exposures and childhood asthma",
     "abstract": "This prospective cohort study followed 1200 children from birth to age five to assess risk factors for childhood asthma."},
    {"name": "coh_no_keyword", "design": D.cohort, "level": L.b, "n": 900,
     "title": "Diet and heart disease over a decade",
     "abstract": "We followed 900 adults over 10 years to study the relationship between dietary patterns and incident heart disease."},
    {"name": "cc_smoking", "design": D.case_control, "level": L.c, "n": 450,
     "title": "Smoking and lung cancer: a case-control study",
     "abstract": "In this case-control study we included 450 patients with lung cancer and 450 matched controls to examine smoking as a risk factor."},
    {"name": "cc_diet", "design": D.case_control, "level": L.c, "n": 200,
     "title": "Dietary fibre and colorectal cancer",
     "abstract": "In this case-control study we included 200 cases of colorectal cancer and 400 matched controls, comparing dietary fibre intake."},
    {"name": "cs_burnout", "design": D.cross_sectional, "level": L.c, "n": 500,
     "title": "Burnout among hospital staff",
     "abstract": "In this cross-sectional survey, a total of 500 nurses were included to estimate the prevalence of burnout in tertiary hospitals."},
    {"name": "cs_diabetes", "design": D.cross_sectional, "level": L.c, "n": 1000,
     "title": "Undiagnosed diabetes in primary care",
     "abstract": "In this cross-sectional study, a total of 1000 adults were screened to estimate the prevalence of undiagnosed diabetes."},
    {"name": "cs_survey_only", "design": D.cross_sectional, "level": L.c, "n": None,
     "title": "Attitudes to teleconsultation",
     "abstract": "A survey was conducted among general practitioners to describe attitudes toward teleconsultation."},
    {"name": "ser_surgery", "design": D.case_series, "level": L.d, "n": 12,
     "title": "A novel surgical technique",
     "abstract": "In this case series we included 12 patients who underwent a novel laparoscopic technique, describing outcomes at six months."},
    {"name": "ser_reaction", "design": D.case_series, "level": L.d, "n": None,
     "title": "An unusual drug reaction",
     "abstract": "We describe a case series of eight patients who developed a rare reaction after starting the medication."},
    {"name": "rep_rare", "design": D.case_report, "level": L.d, "n": None,
     "title": "An unusual presentation of disease X",
     "abstract": "We report a case of a rare presentation of disease X in a previously healthy young patient, and discuss the diagnostic work-up."},
    {"name": "rep_cardiac", "design": D.case_report, "level": L.d, "n": None,
     "title": "Acute myocarditis in an athlete",
     "abstract": "We report a case of acute myocarditis in a young athlete, highlighting the diagnostic challenge."},
    {"name": "nr_overview", "design": D.narrative_review, "level": L.d, "n": None,
     "title": "Management of hypertension: an overview",
     "abstract": "This narrative review summarizes current understanding of the management of hypertension and highlights areas of ongoing debate."},
    {"name": "nr_pain", "design": D.narrative_review, "level": L.d, "n": None,
     "title": "Approaches to chronic pain",
     "abstract": "This review discusses current approaches to managing chronic pain across primary and specialist care."},
    {"name": "eo_editorial", "design": D.expert_opinion, "level": L.d, "n": None,
     "title": "The case for earlier screening",
     "abstract": "In this editorial, we argue for earlier screening and outline the policy implications."},
    {"name": "eo_consensus", "design": D.expert_opinion, "level": L.d, "n": None,
     "title": "Expert recommendations on anticoagulation",
     "abstract": "This consensus statement from an expert panel provides recommendations on perioperative anticoagulation."},
    {"name": "un_vague", "design": D.unclear, "level": L.unclear, "n": None,
     "title": "Reflections on patient care",
     "abstract": "This article offers general reflections on improving everyday patient care."},
]


def evaluate() -> dict:
    """Run the text-only rule engine over the benchmark and tally accuracy."""
    rows = []
    design_correct = level_correct = size_correct = size_total = 0
    for item in BENCHMARK:
        text = f"{item['title']}. {item['abstract']}"
        predicted = evidence_rules.classify_study_design(text).design
        level, _ = evidence_rules.map_evidence_level(predicted)
        size = evidence_rules.extract_sample_size(item["abstract"])
        design_ok = predicted == item["design"]
        level_ok = level == item["level"]
        design_correct += design_ok
        level_correct += level_ok
        if item["n"] is not None:
            size_total += 1
            size_correct += size == item["n"]
        rows.append({
            "name": item["name"],
            "expected": item["design"].value,
            "predicted": predicted.value,
            "design_ok": design_ok,
            "level_ok": level_ok,
            "exp_n": item["n"],
            "pred_n": size,
        })
    return {
        "total": len(BENCHMARK),
        "design_correct": design_correct,
        "level_correct": level_correct,
        "size_correct": size_correct,
        "size_total": size_total,
        "rows": rows,
    }
