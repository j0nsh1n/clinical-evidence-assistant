"""Regression guard on synthetic + real-article benchmarks (thresholds below measured)."""

from pathlib import Path

from tests.fixtures.benchmark_abstracts import BENCHMARK, evaluate
from tests.fixtures.real_benchmark import (
    FIXTURES_DIR,
    REAL_BENCHMARK,
    evaluate_real,
    evaluate_real_delta,
    load_fixture,
)


def test_benchmark_has_enough_samples():
    assert len(BENCHMARK) >= 20


def test_benchmark_design_accuracy():
    report = evaluate()
    assert report["design_correct"] / report["total"] >= 0.80


def test_benchmark_level_accuracy():
    report = evaluate()
    assert report["level_correct"] / report["total"] >= 0.85


def test_benchmark_sample_size_accuracy():
    report = evaluate()
    assert report["size_correct"] / report["size_total"] >= 0.90


# ---------------------------------------------------------------------------
# Real-article harness
# ---------------------------------------------------------------------------


def test_real_benchmark_has_enough_samples():
    assert len(REAL_BENCHMARK) >= 20


def test_real_benchmark_every_label_has_fixture():
    for item in REAL_BENCHMARK:
        path = FIXTURES_DIR / f"{item['fixture']}.json"
        assert path.is_file(), f"missing fixture for {item['name']}: {path}"
        article = load_fixture(item["fixture"])
        assert (article.get("abstract") or "").strip(), f"{item['name']}: empty abstract"
        sections = article.get("full_text_sections") or {}
        headings = " ".join(sections.keys()).upper()
        assert "METHOD" in headings, f"{item['name']}: no Methods-like section"
        assert "RESULT" in headings, f"{item['name']}: no Results-like section"


def test_real_benchmark_harness_runs_off_and_on():
    pack = evaluate_real_delta()
    assert pack["off"]["total"] == len(REAL_BENCHMARK)
    assert pack["on"]["total"] == len(REAL_BENCHMARK)
    assert "design" in pack["delta"]
    assert "sample_size" in pack["delta"]
    # Design/level change only via unclear→Methods tie-breaks (never override a clear
    # abstract design). Current fixtures have no unclear abstracts, so delta is 0;
    # if a fixture gains a tie-break, design/level delta must not go negative.
    assert pack["delta"]["design"] >= 0.0
    assert pack["delta"]["level"] >= 0.0


def test_real_benchmark_floors_fulltext_on():
    """Floors sit below current measured accuracy so Phase-2 gains are visible."""
    report = evaluate_real(use_full_text=True)
    assert report["design_correct"] / report["total"] >= 0.50
    assert report["level_correct"] / report["total"] >= 0.50
    if report["size_total"]:
        # Real Methods prose is hard for abstract-tuned regex; floor is low on purpose.
        assert report["size_correct"] / report["size_total"] >= 0.15


def test_real_benchmark_floors_fulltext_off():
    report = evaluate_real(use_full_text=False)
    assert report["design_correct"] / report["total"] >= 0.50
    if report["size_total"]:
        assert report["size_correct"] / report["size_total"] >= 0.10


def test_extract_with_fulltext_shared_by_service_path():
    """Service and benchmark share extract_with_fulltext (no drift)."""
    from app.services import evidence_rules, evidence_service

    # Prefer a fixture known to have Methods sample-size text.
    stem = "cohort_13274967"
    article = load_fixture(stem)
    via_helper = evidence_rules.extract_with_fulltext(
        article.get("abstract") or "",
        article.get("full_text_sections") or {},
        title=article.get("title") or "",
        pub_types=article.get("publication_types") or [],
    )
    via_service = evidence_service.analyze_text(article)
    assert via_service.sample_size == via_helper.sample_size
    assert via_service.used_full_text == via_helper.used_full_text
    assert via_service.study_design == via_helper.design.design
    assert via_service.population == via_helper.pico["population"]
