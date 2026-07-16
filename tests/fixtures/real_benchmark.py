"""Real-article benchmark: labelled OA fixtures + offline evaluation.

**Labelling note (please spot-check):**
Ground-truth ``design``, ``level``, and ``n`` were assigned by reading each
article's abstract and Methods/Results sections in the committed fixtures —
**not** by running the extractor and copying its output (that would be circular).
Labels are **agent-labelled**; humans should verify a sample before treating
accuracy figures as definitive.

Fixtures live in ``tests/fixtures/real_articles/*.json`` (snapshotted once via
``python -m scripts.snapshot_benchmark_articles``). Evaluation never hits the
network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.schemas.evidence import EvidenceLevel as L
from app.schemas.evidence import StudyDesign as D
from app.services import evidence_rules

FIXTURES_DIR = Path(__file__).resolve().parent / "real_articles"

# ---------------------------------------------------------------------------
# Ground truth (agent-labelled — please spot-check)
# ---------------------------------------------------------------------------
# Each entry: fixture stem, true design, true evidence level, true sample size
# (primary analysis / randomized N for primary studies; pooled patient total for
# meta-analyses when clearly stated; None when no single defensible N).

REAL_BENCHMARK: List[Dict[str, Any]] = [
    # --- RCTs (mix of abstract-stated n and methods-only / hard cases) ---
    {
        "name": "rct_12854330",
        "fixture": "rct_12854330",
        "design": D.randomized_controlled_trial,
        "level": L.b,
        # Abstract: "seventy informal elderly caregivers"
        "n": 70,
        "label_note": "agent-labelled; n from abstract ('seventy caregivers')",
    },
    {
        "name": "rct_12953620",
        "fixture": "rct_12953620",
        "design": D.randomized_controlled_trial,
        "level": L.b,
        "n": 540,
        "label_note": "agent-labelled; n=540 in abstract (abstract-wins case)",
    },
    {
        "name": "rct_13166402",
        "fixture": "rct_13166402",
        "design": D.randomized_controlled_trial,
        "level": L.b,
        # 32 patients randomized (Results); Methods has staff n=1 noise
        "n": 32,
        "label_note": "agent-labelled; n=32 patients randomized (Results)",
    },
    {
        "name": "rct_13242114",
        "fixture": "rct_13242114",
        "design": D.randomized_controlled_trial,
        "level": L.b,
        "n": 150,
        "label_note": "agent-labelled; n=150 in abstract",
    },
    {
        "name": "rct2_13001902",
        "fixture": "rct2_13001902",
        "design": D.randomized_controlled_trial,
        "level": L.b,
        # CheckMate 743: 303 + 302 randomly assigned (Results); abstract n=242 is subgroup
        "n": 605,
        "label_note": "agent-labelled; full randomized N=605 (not abstract subgroup 242)",
    },
    {
        "name": "rct2_13102176",
        "fixture": "rct2_13102176",
        "design": D.randomized_controlled_trial,
        "level": L.b,
        "n": 2716,
        "label_note": "agent-labelled; n=2716 original 2x2 randomization (abstract)",
    },
    {
        "name": "rct2_13193497",
        "fixture": "rct2_13193497",
        "design": D.randomized_controlled_trial,
        "level": L.b,
        # This paper's analysis sample (ER+/HER2-); full STO-3 trial was 1780
        "n": 559,
        "label_note": "agent-labelled; analysis sample 559 (full trial 1780 in Methods)",
    },
    {
        "name": "rct2_13269254",
        "fixture": "rct2_13269254",
        "design": D.randomized_controlled_trial,
        "level": L.b,
        "n": 65,
        "label_note": "agent-labelled; n=65 in abstract",
    },
    {
        "name": "rct_n_methods_13180360",
        "fixture": "rct_n_methods_13180360",
        "design": D.randomized_controlled_trial,
        "level": L.b,
        "n": 120,
        "label_note": "agent-labelled; 120 patients randomized (abstract phrasing may miss)",
    },
    {
        "name": "rct_n_methods_13230313",
        "fixture": "rct_n_methods_13230313",
        "design": D.randomized_controlled_trial,
        "level": L.b,
        "n": 30,
        "label_note": "agent-labelled; 30 children randomized",
    },
    # --- Cohorts ---
    {
        "name": "cohort_13274967",
        "fixture": "cohort_13274967",
        "design": D.cohort,
        "level": L.b,
        # Abstract analytic cohort; Methods also states 1785 invited
        "n": 1315,
        "label_note": "agent-labelled; n=1315 students in abstract analytic description",
    },
    {
        "name": "cohort_prim_13277771",
        "fixture": "cohort_prim_13277771",
        "design": D.cohort,
        "level": L.b,
        "n": 204,
        "label_note": "agent-labelled; 204 in final analysis (abstract Results)",
    },
    {
        "name": "cohort_prim_13182103",
        "fixture": "cohort_prim_13182103",
        "design": D.cohort,
        "level": L.b,
        "n": 91,
        "label_note": "agent-labelled; analytic cohort 91 (156 eligible in Methods)",
    },
    {
        "name": "cohort_prim2_13264298",
        "fixture": "cohort_prim2_13264298",
        "design": D.cohort,
        "level": L.b,
        "n": 120,
        "label_note": "agent-labelled; 120 children total (60/60 after PSM language)",
    },
    {
        "name": "cohort_prim2_13138432",
        "fixture": "cohort_prim2_13138432",
        "design": D.cohort,
        "level": L.b,
        "n": 74,
        "label_note": "agent-labelled; 37+37 treated groups in abstract",
    },
    # --- Case-control ---
    {
        "name": "cc_prim_13285908",
        "fixture": "cc_prim_13285908",
        "design": D.case_control,
        "level": L.c,
        "n": 400,
        "label_note": "agent-labelled; 100 cases + 300 controls",
    },
    {
        "name": "cc_prim_13261379",
        "fixture": "cc_prim_13261379",
        "design": D.case_control,
        "level": L.c,
        "n": 111,
        "label_note": "agent-labelled; 37 cases + 74 controls",
    },
    {
        "name": "cc_prim_13099021",
        "fixture": "cc_prim_13099021",
        "design": D.case_control,
        "level": L.c,
        "n": 88,
        "label_note": "agent-labelled; 44+44 matched groups (Results)",
    },
    # --- Cross-sectional ---
    {
        "name": "xs_prim_13242764",
        "fixture": "xs_prim_13242764",
        "design": D.cross_sectional,
        "level": L.c,
        "n": 2661,
        "label_note": "agent-labelled; 2661 with complete data (not 7335 screened)",
    },
    # --- Meta-analyses / systematic reviews ---
    {
        "name": "meta_13274556",
        "fixture": "meta_13274556",
        "design": D.meta_analysis,
        "level": L.a,
        "n": 575,
        "label_note": "agent-labelled; n=575 in abstract",
    },
    {
        "name": "meta_13282062",
        "fixture": "meta_13282062",
        "design": D.meta_analysis,
        "level": L.a,
        "n": 467,
        "label_note": "agent-labelled; 467 patients in abstract",
    },
    {
        "name": "meta_13251348",
        "fixture": "meta_13251348",
        "design": D.meta_analysis,
        "level": L.a,
        "n": None,
        "label_note": "agent-labelled; 19 studies, no single pooled patient N stated",
    },
    {
        "name": "cohort2_13242139",
        "fixture": "cohort2_13242139",
        "design": D.meta_analysis,
        "level": L.a,
        "n": None,
        "label_note": "agent-labelled; SR+MA of prediction models",
    },
    {
        "name": "cohort2_13260012",
        "fixture": "cohort2_13260012",
        "design": D.meta_analysis,
        "level": L.a,
        # Abstract/title: meta-analysis with 16,539 patients
        "n": 16539,
        "label_note": "agent-labelled; pooled n=16539; pub-type may say systematic review only",
    },
    {
        "name": "case_control_13204818",
        "fixture": "case_control_13204818",
        "design": D.meta_analysis,
        "level": L.a,
        "n": None,
        "label_note": "agent-labelled; SR+MA (pub-type Review can mislead classifier)",
    },
    {
        "name": "cohort_13233427",
        "fixture": "cohort_13233427",
        "design": D.meta_analysis,
        "level": L.a,
        "n": 2397,
        "label_note": "agent-labelled; SR+MA; abstract n=2397",
    },
]

LABEL_DISCLAIMER = (
    "Labels are agent-labelled from fixture text — please spot-check before "
    "treating accuracy as definitive."
)


def load_fixture(stem: str) -> dict:
    path = FIXTURES_DIR / f"{stem}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing real-article fixture: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _predict(
    article: dict, *, use_full_text: bool
) -> tuple[D, L, Optional[int], bool]:
    title = article.get("title") or ""
    abstract = article.get("abstract") or ""
    combined = f"{title}. {abstract}".strip()
    pub_types = article.get("publication_types") or []

    if use_full_text:
        extraction = evidence_rules.extract_with_fulltext(
            abstract,
            article.get("full_text_sections") or {},
            title=title,
            pub_types=pub_types,
        )
        design = extraction.design.design
        sample_size = extraction.sample_size
        used = extraction.used_full_text
    else:
        design = evidence_rules.classify_study_design_combined(
            combined, pub_types
        ).design
        sample_size = evidence_rules.extract_sample_size(abstract or combined)
        used = False

    level, _ = evidence_rules.map_evidence_level(design)
    return design, level, sample_size, used


def evaluate_real(*, use_full_text: bool = True) -> dict:
    """Run the same pure extractors the service uses over labelled fixtures."""
    rows: List[dict] = []
    design_correct = level_correct = size_correct = size_total = 0
    used_ft_count = 0

    for item in REAL_BENCHMARK:
        article = load_fixture(item["fixture"])
        predicted, level, size, used_ft = _predict(article, use_full_text=use_full_text)
        if used_ft:
            used_ft_count += 1

        design_ok = predicted == item["design"]
        level_ok = level == item["level"]
        design_correct += design_ok
        level_correct += level_ok

        size_ok: Optional[bool] = None
        if item["n"] is not None:
            size_total += 1
            size_ok = size == item["n"]
            size_correct += bool(size_ok)

        rows.append(
            {
                "name": item["name"],
                "expected": item["design"].value,
                "predicted": predicted.value,
                "design_ok": design_ok,
                "level_ok": level_ok,
                "exp_n": item["n"],
                "pred_n": size,
                "size_ok": size_ok,
                "used_full_text": used_ft,
            }
        )

    total = len(REAL_BENCHMARK)
    return {
        "total": total,
        "design_correct": design_correct,
        "level_correct": level_correct,
        "size_correct": size_correct,
        "size_total": size_total,
        "used_full_text_count": used_ft_count,
        "use_full_text": use_full_text,
        "rows": rows,
        "label_disclaimer": LABEL_DISCLAIMER,
    }


def evaluate_real_delta() -> dict:
    """Full-text OFF vs ON, plus per-metric delta (ON − OFF)."""
    off = evaluate_real(use_full_text=False)
    on = evaluate_real(use_full_text=True)

    def _rate(correct: int, total: int) -> float:
        return (correct / total) if total else 0.0

    return {
        "off": off,
        "on": on,
        "delta": {
            "design": _rate(on["design_correct"], on["total"])
            - _rate(off["design_correct"], off["total"]),
            "level": _rate(on["level_correct"], on["total"])
            - _rate(off["level_correct"], off["total"]),
            "sample_size": _rate(on["size_correct"], on["size_total"])
            - _rate(off["size_correct"], off["size_total"]),
        },
        "label_disclaimer": LABEL_DISCLAIMER,
    }
