"""Print the rule-engine accuracy benchmark.

Runs:
  1. Synthetic abstract-only set (``tests/fixtures/benchmark_abstracts.py``)
  2. Real OA article fixtures twice — full-text OFF vs ON — with delta

Usage (from the project root):  python -m scripts.benchmark
"""

from __future__ import annotations

from tests.fixtures.benchmark_abstracts import evaluate as evaluate_synthetic
from tests.fixtures.real_benchmark import evaluate_real_delta


def _pct(correct: int, total: int) -> str:
    if not total:
        return "n/a"
    return f"{correct}/{total} = {100 * correct / total:.0f}%"


def _print_synthetic() -> None:
    report = evaluate_synthetic()
    print("Rule-based study-design benchmark (synthetic abstracts)\n")
    print(f"{'sample':16} {'expected':22} {'predicted':22} design level size")
    print("-" * 80)
    for row in report["rows"]:
        design = "ok  " if row["design_ok"] else "MISS"
        level = "ok  " if row["level_ok"] else "MISS"
        if row["exp_n"] is None:
            size = ""
        else:
            ok = "ok" if row["pred_n"] == row["exp_n"] else "MISS"
            size = f"{row['pred_n']} vs {row['exp_n']} {ok}"
        print(
            f"{row['name']:16} {row['expected']:22} {row['predicted']:22} "
            f"{design}   {level}  {size}"
        )

    total = report["total"]
    sz = report["size_total"]
    print("-" * 80)
    print(f"Design accuracy: {_pct(report['design_correct'], total)}")
    print(f"Level accuracy:  {_pct(report['level_correct'], total)}")
    print(f"Sample size:     {_pct(report['size_correct'], sz)}")


def _print_real_table(title: str, report: dict) -> None:
    print(f"\n{title}\n")
    print(
        f"{'sample':28} {'expected':22} {'predicted':22} design level size"
        f"{'  FT' if report.get('use_full_text') else ''}"
    )
    print("-" * 100)
    for row in report["rows"]:
        design = "ok  " if row["design_ok"] else "MISS"
        level = "ok  " if row["level_ok"] else "MISS"
        if row["exp_n"] is None:
            size = "     —"
        else:
            ok = "ok  " if row["size_ok"] else "MISS"
            size = f"{str(row['pred_n']):>6} vs {row['exp_n']:<6} {ok}"
        ft = "  yes" if row.get("used_full_text") else "   —"
        print(
            f"{row['name']:28} {row['expected']:22} {row['predicted']:22} "
            f"{design}   {level}  {size}"
            f"{ft if report.get('use_full_text') else ''}"
        )

    total = report["total"]
    sz = report["size_total"]
    print("-" * 100)
    print(f"Design accuracy: {_pct(report['design_correct'], total)}")
    print(f"Level accuracy:  {_pct(report['level_correct'], total)}")
    print(f"Sample size:     {_pct(report['size_correct'], sz)}")
    if report.get("use_full_text"):
        print(
            f"used_full_text:  {report['used_full_text_count']}/{total} articles "
            f"filled ≥1 gap from OA full text"
        )


def _print_real() -> None:
    pack = evaluate_real_delta()
    print("\n" + "=" * 80)
    print("Real-article benchmark (cached OA fixtures; offline)")
    print(pack["label_disclaimer"])
    print("=" * 80)

    _print_real_table("Full-text OFF (abstract only)", pack["off"])
    _print_real_table("Full-text ON (abstract-first + Methods/Results fill gaps)", pack["on"])

    d = pack["delta"]
    print("\nDelta (ON − OFF)")
    print("-" * 40)
    print(
        f"Design:      {d['design']:+.1%}  "
        f"(≥0 expected; only unclear→Methods tie-breaks change design)"
    )
    print(f"Level:       {d['level']:+.1%}")
    print(
        f"Sample size: {d['sample_size']:+.1%}  "
        f"(main lever of full-text fallback; PICO also fills from Methods)"
    )


def main() -> None:
    _print_synthetic()
    _print_real()


if __name__ == "__main__":
    main()
