"""Print the rule-engine accuracy benchmark.

Usage (from the project root):  python -m scripts.benchmark
"""

from tests.fixtures.benchmark_abstracts import evaluate


def main() -> None:
    report = evaluate()
    print("Rule-based study-design benchmark\n")
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
        print(f"{row['name']:16} {row['expected']:22} {row['predicted']:22} {design}   {level}  {size}")

    total = report["total"]
    sz = report["size_total"]
    print("-" * 80)
    print(f"Design accuracy: {report['design_correct']}/{total} = {100 * report['design_correct'] / total:.0f}%")
    print(f"Level accuracy:  {report['level_correct']}/{total} = {100 * report['level_correct'] / total:.0f}%")
    print(f"Sample size:     {report['size_correct']}/{sz} = {100 * report['size_correct'] / sz:.0f}%")


if __name__ == "__main__":
    main()
