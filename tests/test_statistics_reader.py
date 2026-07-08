"""Unit tests for the reported-statistics extractor (pure rules, no network)."""

from app.services.evidence_rules import extract_statistics


def test_hr_with_ci_excluding_one_is_significant():
    stats = extract_statistics(
        "Walking reduced mortality (HR 0.75, 95% CI 0.60-0.94) compared with usual care."
    )
    assert len(stats) == 1
    s = stats[0]
    assert s.measure == "HR"
    assert s.value == 0.75
    assert (s.ci_low, s.ci_high) == (0.60, 0.94)
    assert "25% lower" in s.reading
    assert "excludes 1" in s.reading
    assert "clinical importance" in s.reading
    assert s.display == "HR 0.75 (95% CI 0.6–0.94)"


def test_or_with_ci_including_one_not_significant():
    stats = extract_statistics("The odds of remission were higher (OR 1.30; 95% CI 0.90 to 1.87).")
    assert len(stats) == 1
    assert stats[0].measure == "OR"
    assert "30% higher" in stats[0].reading
    assert "includes 1" in stats[0].reading


def test_lowercase_or_word_is_not_a_measure():
    stats = extract_statistics("Patients received the drug or 24 weeks of standard care.")
    assert stats == []


def test_spelled_out_nejm_comma_style():
    stats = extract_statistics(
        "The primary outcome occurred less often with treatment (hazard ratio, 0.68; "
        "95% confidence interval, 0.55 to 0.85; P=0.001)."
    )
    assert len(stats) == 1
    s = stats[0]
    assert s.measure == "HR"
    assert s.label == "hazard ratio"
    assert (s.ci_low, s.ci_high) == (0.55, 0.85)
    assert s.p_value == "=0.001"


def test_spelled_out_with_parenthesized_abbreviation():
    stats = extract_statistics("The adjusted hazard ratio (aHR) 0.81 (95% CI 0.70-0.95) favoured treatment.")
    assert len(stats) == 1
    assert stats[0].label == "adjusted hazard ratio"
    assert stats[0].display.startswith("aHR 0.81")


def test_lancet_middle_dot_decimals():
    stats = extract_statistics("Mortality was lower in the treatment group (RR 0·80, 95% CI 0·65–0·98).")
    assert len(stats) == 1
    assert stats[0].value == 0.80
    assert stats[0].ci_low == 0.65


def test_relative_risk_above_one_reads_higher():
    stats = extract_statistics("Smoking was associated with lung cancer (relative risk 2.5, 95% CI 1.8-3.4).")
    assert len(stats) == 1
    assert stats[0].measure == "RR"
    assert "150% higher" in stats[0].reading


def test_p_value_only_no_ci():
    stats = extract_statistics("Treatment improved survival (HR 0.70, p<0.001).")
    assert len(stats) == 1
    assert stats[0].p_value == "<0.001"
    assert stats[0].ci_low is None
    assert "significant" in stats[0].reading


def test_duplicate_mentions_deduped():
    stats = extract_statistics("The odds ratio (OR) was 1.5 (95% CI 1.1-2.0). This OR 1.5 was robust.")
    assert len(stats) == 1


def test_no_statistics_returns_empty():
    assert extract_statistics("We describe our experience with 12 patients.") == []
    assert extract_statistics("") == []


def test_implausible_values_rejected():
    # a year mistaken for a ratio must not slip through
    assert extract_statistics("HR 2024 was the department code.") == []
