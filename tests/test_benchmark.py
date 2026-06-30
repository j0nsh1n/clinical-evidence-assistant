"""Regression guard on the rule-engine benchmark (thresholds below measured)."""

from tests.fixtures.benchmark_abstracts import BENCHMARK, evaluate


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
