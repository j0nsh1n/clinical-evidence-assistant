"""Rule-based extraction and provisional evidence scoring.

Every function here is **pure** (text in, structured data out) with no I/O, so it
is fast and trivially unit-testable. This is the auditable baseline of the
feature: an optional LLM pass may later refine human-readable fields, but the
evidence *level* should always remain explainable from these rules.
"""

from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional, Tuple

from app.schemas.evidence import (
    AppraisalChecklist,
    AppraisalSignal,
    AppraisalSignalStatus,
    ClinicalQuestionType,
    EvidenceLevel,
    ReportedStatistic,
    StudyDesign,
    StudyDesignResult,
)

# ---------------------------------------------------------------------------
# Study-design classification
# ---------------------------------------------------------------------------

# Ordered most-specific -> least-specific. The first matching pattern wins, so
# "systematic review and meta-analysis" classifies as a synthesis before the
# generic "review" pattern can fire, and an explicit "randomized controlled
# trial" outranks a bare "randomized".
_DESIGN_PATTERNS: List[Tuple[StudyDesign, float, List[str]]] = [
    (StudyDesign.meta_analysis, 0.95, [r"meta[-\s]?analysis"]),
    (StudyDesign.systematic_review, 0.95, [r"systematic review"]),
    (
        StudyDesign.randomized_controlled_trial,
        0.9,
        [
            r"randomi[sz]ed controlled trial",
            r"\brct\b",
            r"randomi[sz]ed,?\s+double[-\s]?blind",
            r"placebo[-\s]?controlled",
        ],
    ),
    (
        StudyDesign.randomized_controlled_trial,
        0.7,
        [r"randomi[sz]ed", r"double[-\s]?blind", r"\brandomly\s+(?:assigned|allocated)\b"],
    ),
    (
        StudyDesign.cohort,
        0.85,
        [r"prospective cohort", r"retrospective cohort", r"cohort study", r"\bcohort\b"],
    ),
    (StudyDesign.case_control, 0.85, [r"case[-\s]?control"]),
    (StudyDesign.cross_sectional, 0.8, [r"cross[-\s]?sectional", r"prevalence survey"]),
    (StudyDesign.case_series, 0.75, [r"case series"]),
    (StudyDesign.case_report, 0.75, [r"case report", r"\ba case of\b"]),
    (StudyDesign.narrative_review, 0.5, [r"narrative review", r"literature review", r"\breview\b"]),
    (StudyDesign.expert_opinion, 0.4, [r"expert opinion", r"consensus statement", r"\beditorial\b"]),
]


def classify_study_design(text: str) -> StudyDesignResult:
    """Classify the study design from title+abstract text."""
    haystack = (text or "").lower()
    for design, confidence, patterns in _DESIGN_PATTERNS:
        for pattern in patterns:
            match = re.search(pattern, haystack)
            if match:
                return StudyDesignResult(
                    design=design, confidence=confidence, matched_phrase=match.group(0)
                )
    return StudyDesignResult(design=StudyDesign.unclear, confidence=0.0, matched_phrase=None)


# Map authoritative PubMed publication types to a study design. Ordered so that
# synthesis types are checked before the generic "review".
_PUBTYPE_DESIGN: List[Tuple[str, StudyDesign, float]] = [
    ("meta-analysis", StudyDesign.meta_analysis, 0.97),
    ("systematic review", StudyDesign.systematic_review, 0.97),
    ("randomized controlled trial", StudyDesign.randomized_controlled_trial, 0.95),
    ("case reports", StudyDesign.case_report, 0.9),
    ("review", StudyDesign.narrative_review, 0.6),
    ("editorial", StudyDesign.expert_opinion, 0.55),
]


def classify_from_publication_types(pub_types: Optional[List[str]]) -> StudyDesignResult:
    """Classify design from PubMed's own publication-type tags (authoritative)."""
    types_low = [str(p).lower() for p in (pub_types or [])]
    for key, design, confidence in _PUBTYPE_DESIGN:
        if any(key in t for t in types_low):
            return StudyDesignResult(
                design=design, confidence=confidence, matched_phrase=f"PubMed type: {key}"
            )
    return StudyDesignResult(design=StudyDesign.unclear, confidence=0.0, matched_phrase=None)


def classify_study_design_combined(
    text: str, pub_types: Optional[List[str]] = None
) -> StudyDesignResult:
    """Prefer PubMed publication types when they give a confident design;
    otherwise fall back to the text-based classifier."""
    if pub_types:
        by_type = classify_from_publication_types(pub_types)
        if by_type.design != StudyDesign.unclear:
            return by_type
    return classify_study_design(text)


# ---------------------------------------------------------------------------
# Clinical question type
# ---------------------------------------------------------------------------

_QUESTION_PATTERNS: List[Tuple[ClinicalQuestionType, List[str]]] = [
    (ClinicalQuestionType.therapy, [r"treat", r"therap", r"efficacy", r"intervention", r"trial of"]),
    (
        ClinicalQuestionType.diagnosis,
        [r"diagnos", r"sensitivity and specificity", r"screening test", r"accuracy of"],
    ),
    (ClinicalQuestionType.prognosis, [r"prognos", r"survival", r"mortality", r"predict"]),
    (
        ClinicalQuestionType.etiology_harm,
        [r"risk factor", r"associated with", r"\bexposure\b", r"adverse", r"\bharm\b"],
    ),
    (ClinicalQuestionType.prevention, [r"prevent", r"prophylax", r"vaccin", r"screening program"]),
]


def detect_question_type(text: str) -> ClinicalQuestionType:
    """Pick the question type with the most keyword hits (ties favour earlier)."""
    haystack = (text or "").lower()
    best = ClinicalQuestionType.descriptive_other
    best_hits = 0
    for qtype, patterns in _QUESTION_PATTERNS:
        hits = sum(1 for p in patterns if re.search(p, haystack))
        if hits > best_hits:
            best, best_hits = qtype, hits
    return best


# ---------------------------------------------------------------------------
# Sample size
# ---------------------------------------------------------------------------

_NOUNS = r"patients|participants|subjects|individuals|adults|children|cases|women|men|nurses"
_VERBS = r"a total of|included|enrolled|recruited|analy[sz]ed|followed"

_SAMPLE_SIZE_PATTERNS = [
    r"\bn\s*=\s*([\d,]{1,9})",
    rf"\b(?:{_VERBS})\s+([\d,]{{1,9}})\s+(?:{_NOUNS})",
    rf"\b([\d,]{{1,9}})\s+(?:{_NOUNS})\s+were\s+(?:enrolled|included|randomi[sz]ed|recruited)",
]


def extract_sample_size(text: str) -> Optional[int]:
    """Extract a likely total sample size from an abstract.

    Heuristic: collect all candidate counts and return the largest plausible one,
    which is usually the enrolled total rather than a subgroup. Returns ``None``
    when nothing is found.
    """
    haystack = (text or "").lower()
    candidates: List[int] = []
    for pattern in _SAMPLE_SIZE_PATTERNS:
        for match in re.finditer(pattern, haystack):
            raw = match.group(1).replace(",", "")
            if raw.isdigit():
                value = int(raw)
                if 0 < value < 100_000_000:
                    candidates.append(value)
    return max(candidates) if candidates else None


def section_text(sections: Optional[Dict[str, str]], keyword: str) -> Optional[str]:
    """Return the best full-text section whose heading contains ``keyword``.

    Prefers an exact heading match, then the shortest containing match, so
    ``METHODS`` wins over ``STATISTICAL METHODS`` when looking for ``METHOD``.
    """
    if not sections:
        return None
    key = (keyword or "").upper()
    if not key:
        return None
    candidates: List[Tuple[bool, int, str]] = []
    for heading, text in sections.items():
        h = (heading or "").upper()
        if key in h and text:
            candidates.append((h == key, len(h), text))
    if not candidates:
        return None
    # Exact match first (False sorts before True when negated), then shortest heading.
    candidates.sort(key=lambda item: (not item[0], item[1]))
    return candidates[0][2]


class FullTextExtraction(NamedTuple):
    """Abstract-first extraction with optional OA full-text gap-fill."""

    sample_size: Optional[int]
    reported_statistics: List[ReportedStatistic]
    pico: Dict[str, Optional[str]]
    design: StudyDesignResult
    used_full_text: bool


def extract_with_fulltext(
    abstract: str,
    full_text_sections: Optional[Dict[str, str]] = None,
    *,
    title: str = "",
    pub_types: Optional[List[str]] = None,
    max_stats: int = 6,
) -> FullTextExtraction:
    """Abstract-first extraction; OA full text fills gaps only.

    Full text never overrides a sample size, PICO field, or design already found
    from the abstract/publication types. Study design is read from Methods only
    when the abstract path is still ``unclear`` (a deliberate tie-break — the
    grade can change only in that case).
    """
    combined = f"{title}. {abstract}".strip() if title else (abstract or "")
    haystack = abstract or combined
    sample_size = extract_sample_size(haystack)
    reported_statistics = extract_statistics(haystack, max_stats=max_stats)
    pico = extract_pico_hints(haystack)
    design = classify_study_design_combined(combined, pub_types)
    used_full_text = False

    sections = full_text_sections or {}
    if sections:
        methods_text = section_text(sections, "METHOD")
        results_text = section_text(sections, "RESULT")

        # Design tie-break: abstract/pub-type unclear only.
        if design.design == StudyDesign.unclear and methods_text:
            ft_design = classify_study_design(methods_text)
            if ft_design.design != StudyDesign.unclear:
                phrase = ft_design.matched_phrase or "methods"
                design = StudyDesignResult(
                    design=ft_design.design,
                    confidence=ft_design.confidence,
                    matched_phrase=f"full text: {phrase}",
                )
                used_full_text = True

        # PICO: fill missing fields from Methods (never override abstract hits).
        if methods_text:
            ft_pico = extract_pico_hints(methods_text)
            for key, value in ft_pico.items():
                if pico.get(key) is None and value is not None:
                    pico[key] = value
                    used_full_text = True

        if sample_size is None and methods_text:
            ft_n = extract_sample_size(methods_text)
            if ft_n is not None:
                sample_size = ft_n
                used_full_text = True

        if results_text:
            seen = {s.display.strip().lower() for s in reported_statistics}
            for stat in extract_statistics(results_text, max_stats=max_stats):
                if len(reported_statistics) >= max_stats:
                    break
                key = stat.display.strip().lower()
                if key not in seen:
                    reported_statistics.append(stat)
                    seen.add(key)
                    used_full_text = True

    return FullTextExtraction(
        sample_size=sample_size,
        reported_statistics=reported_statistics,
        pico=pico,
        design=design,
        used_full_text=used_full_text,
    )


# ---------------------------------------------------------------------------
# PICO hints — targeted phrase extraction
# ---------------------------------------------------------------------------
# Each field has an ordered list of regex patterns; the first match wins and its
# first capturing group is returned as a concise phrase. A trailing look-ahead
# stops the captured phrase at a natural boundary (a clause verb, conjunction, or
# punctuation) instead of swallowing the rest of the sentence. When nothing
# matches we return None ("not reported") rather than a vague guess.

# Population nouns shared across the population patterns.
_POP = (
    r"patients|adults|children|participants|subjects|individuals|"
    r"women|men|infants|neonates|nurses|people"
)

# Clause boundaries that end a population phrase.
_POP_END = (
    r"(?=\s+(?:were|was|underwent|received|enrolled|for|in|over|during|and|to|"
    r"are|is|will|had)\b|[.,;:]|$)"
)

_POPULATION_PATTERNS: List[str] = [
    rf"(\d[\d,]{{0,8}}\s+(?:{_POP})(?:\s+(?:with|aged|who\s+had)\s+[^.,;:]+?)?){_POP_END}",
    rf"((?:{_POP})\s+(?:with|aged|who\s+had)\s+[^.,;:]+?){_POP_END}",
    rf"(\d[\d,]{{0,8}}\s+(?:{_POP}))\b",
]

_INTERVENTION_PATTERNS: List[str] = [
    r"(?:randomi[sz]ed|assigned|allocated)\s+to\s+(?:receive\s+)?([^.,;:]+?)"
    r"(?=\s+(?:or|versus|vs\.?|compared|and)\b|[.,;:])",
    r"(?:treated with|received|to receive|underwent)\s+([^.,;:]+?)"
    r"(?=\s+(?:or|versus|vs\.?|compared|and|for)\b|[.,;:])",
    r"(?:association between|exposure to|effect of|efficacy of|impact of|safety of)\s+([^.,;:]+?)"
    r"(?=\s+(?:and|on|in|versus|vs\.?)\b|[.,;:])",
    r"(\w+)\s+as\s+a\s+risk\s+factor",
]

_COMPARATOR_PATTERNS: List[str] = [
    r"(?:versus|vs\.?|compared\s+(?:with|to)|relative to)\s+([^.,;:]+?)"
    r"(?=\s+(?:in|for|at|over|during|among|on)\b|[.,;:]|$)",
    r"\bor\s+(placebo|controls?|standard care|usual care|sham(?:\s+\w+)?|no treatment)\b",
    r"(\d[\d,]{0,8}\s+matched controls|matched controls|placebo|standard care|usual care|control group|sham)",
]

_OUTCOME_PATTERNS: List[str] = [
    r"primary (?:outcome|endpoint|end\s?point)s?\s+(?:measures?\s+)?(?:was|were|is|are|:)\s+([^.;]+?)(?=[.;]|$)",
    r"primary (?:outcome|endpoint)\s+(?:of|:)\s+([^.;]+?)(?=[.;]|$)",
]


def _first_capture(text: str, patterns: List[str]) -> Optional[str]:
    """Return the first pattern's captured phrase (whitespace-cleaned), or None."""
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            phrase = (match.group(1) if match.groups() else match.group(0)).strip(" ,.;:")
            phrase = re.sub(r"\s+", " ", phrase)
            if phrase:
                return phrase
    return None


def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]


def extract_pico_hints(text: str) -> Dict[str, Optional[str]]:
    """Extract a concise phrase for each PICO field (or None when not found)."""
    normalized = re.sub(r"\s+", " ", text or "")
    return {
        "population": _first_capture(normalized, _POPULATION_PATTERNS),
        "intervention_or_exposure": _first_capture(normalized, _INTERVENTION_PATTERNS),
        "comparator": _first_capture(normalized, _COMPARATOR_PATTERNS),
        "primary_outcome": _first_capture(normalized, _OUTCOME_PATTERNS),
    }


def extract_key_finding(abstract: str, sections: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Best-effort one-line takeaway: the conclusion section, else the last sentence."""
    if sections:
        for key in ("CONCLUSIONS", "CONCLUSION", "INTERPRETATION", "DISCUSSION"):
            if sections.get(key):
                return sections[key]
    sentences = _split_sentences(abstract)
    return sentences[-1] if sentences else None


# ---------------------------------------------------------------------------
# Reported statistics — effect sizes, confidence intervals, p-values
# ---------------------------------------------------------------------------
# Deterministic extraction + fixed-template readings; no model ever touches the
# numbers. Two measure patterns: spelled-out names are case-insensitive, but
# abbreviations are case-SENSITIVE so the word "or" never matches "OR".

_STAT_NOUNS = {
    "HR": ("hazard ratio", "rate of the outcome"),
    "OR": ("odds ratio", "odds of the outcome"),
    "RR": ("risk ratio", "risk of the outcome"),
    "IRR": ("incidence rate ratio", "incidence rate of the outcome"),
}

# A ratio value, allowing the Lancet-style middle-dot decimal (0·75).
_NUM = r"\d+(?:[.·]\d+)?"

_SPELLED_MEASURE_RE = re.compile(
    r"\b(?P<adj>adjusted\s+)?(?P<name>hazard ratio|odds ratio|risk ratio|relative risk|"
    r"incidence rate ratio|rate ratio)s?\b"
    r"(?:\s*\((?:a?(?:HR|OR|RR)|IRR)\))?"  # e.g. "hazard ratio (HR) 0.75"
    rf"[\s,:=]*(?:of|was|were)?[\s,:=]*[\[\(]?\s*(?P<value>{_NUM})",
    re.IGNORECASE,
)
_ABBREV_MEASURE_RE = re.compile(
    rf"\b(?P<abbr>a?(?:HR|OR|RR)|IRR)\b\s*[,:=]?\s*[\[\(]?\s*(?P<value>{_NUM})"
)
_CI_RE = re.compile(
    rf"95\s*%\s*(?:CI|confidence interval)[\s:,=]*\(?\s*(?P<low>{_NUM})\s*"
    rf"(?:to|through|[-–—−,])\s*(?P<high>{_NUM})",
    re.IGNORECASE,
)
_P_RE = re.compile(rf"\bP\s*(?P<cmp>[<=>])\s*(?P<p>{_NUM})", re.IGNORECASE)

_SPELLED_TO_KEY = {
    "hazard ratio": "HR",
    "odds ratio": "OR",
    "risk ratio": "RR",
    "relative risk": "RR",
    "incidence rate ratio": "IRR",
    "rate ratio": "IRR",
}


def _to_float(raw: str) -> float:
    return float(raw.replace("·", "."))


def _stat_reading(
    key: str,
    value: float,
    ci_low: Optional[float],
    ci_high: Optional[float],
    p_value: Optional[str],
) -> str:
    noun = _STAT_NOUNS[key][1]
    if value < 1:
        direction = f"about {round((1 - value) * 100)}% lower {noun}"
    elif value > 1:
        direction = f"about {round((value - 1) * 100)}% higher {noun}"
    else:
        direction = f"no difference in the {noun}"
    parts = [f"Suggests {direction} in the studied group"]
    if ci_low is not None and ci_high is not None:
        if ci_low <= 1.0 <= ci_high:
            parts.append(
                "but the 95% CI includes 1, so the result is not statistically "
                "significant at the usual threshold (could be chance)"
            )
        else:
            parts.append(
                "the 95% CI excludes 1, so the result is statistically "
                "significant at the usual threshold"
            )
    elif p_value:
        try:
            significant = float(p_value.lstrip("<=>")) <= 0.05 and not p_value.startswith(">")
        except ValueError:
            significant = False
        parts.append(
            "reported as statistically significant (p" + p_value + ")"
            if significant
            else "not statistically significant as reported (p" + p_value + ")"
        )
    parts.append("statistical significance is not the same as clinical importance")
    return "; ".join(parts) + "."


def extract_statistics(text: str, max_stats: int = 6) -> List[ReportedStatistic]:
    """Find ratio effect estimates (HR/OR/RR/IRR) with nearby 95% CIs / p-values."""
    haystack = re.sub(r"\s+", " ", text or "")
    found: List[ReportedStatistic] = []
    seen: set = set()

    matches = []
    for match in _SPELLED_MEASURE_RE.finditer(haystack):
        key = _SPELLED_TO_KEY[match.group("name").lower()]
        adjusted = bool(match.group("adj"))
        matches.append((match, key, adjusted))
    for match in _ABBREV_MEASURE_RE.finditer(haystack):
        abbr = match.group("abbr")
        adjusted = abbr.startswith("a") and abbr != "IRR"
        matches.append((match, abbr.lstrip("a") if adjusted else abbr, adjusted))
    matches.sort(key=lambda item: item[0].start())

    for match, key, adjusted in matches:
        value = _to_float(match.group("value"))
        if not 0.01 <= value <= 50:
            continue
        window = haystack[match.end() : match.end() + 90]
        ci = _CI_RE.search(window)
        ci_low = _to_float(ci.group("low")) if ci else None
        ci_high = _to_float(ci.group("high")) if ci else None
        p_match = _P_RE.search(haystack[match.end() : match.end() + 140])
        p_value = f"{p_match.group('cmp')}{p_match.group('p').replace(chr(0xB7), '.')}" if p_match else None

        dedupe_key = (key, adjusted, value)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        label = ("adjusted " if adjusted else "") + _STAT_NOUNS[key][0]
        display = ("a" if adjusted else "") + key + f" {value:g}"
        if ci_low is not None:
            display += f" (95% CI {ci_low:g}–{ci_high:g}"
            display += f"; p{p_value})" if p_value else ")"
        elif p_value:
            display += f" (p{p_value})"
        found.append(
            ReportedStatistic(
                measure=key,
                label=label,
                value=value,
                ci_low=ci_low,
                ci_high=ci_high,
                p_value=p_value,
                display=display,
                reading=_stat_reading(key, value, ci_low, ci_high, p_value),
            )
        )
        if len(found) >= max_stats:
            break
    return found


# ---------------------------------------------------------------------------
# Evidence-level mapping
# ---------------------------------------------------------------------------

_EVIDENCE_MAP: Dict[StudyDesign, Tuple[EvidenceLevel, str]] = {
    StudyDesign.systematic_review: (EvidenceLevel.a, "High"),
    StudyDesign.meta_analysis: (EvidenceLevel.a, "High"),
    StudyDesign.randomized_controlled_trial: (EvidenceLevel.b, "Moderate"),
    StudyDesign.cohort: (EvidenceLevel.b, "Moderate"),
    StudyDesign.case_control: (EvidenceLevel.c, "Lower"),
    StudyDesign.cross_sectional: (EvidenceLevel.c, "Lower"),
    StudyDesign.case_series: (EvidenceLevel.d, "Weak"),
    StudyDesign.case_report: (EvidenceLevel.d, "Weak"),
    StudyDesign.narrative_review: (EvidenceLevel.d, "Weak"),
    StudyDesign.expert_opinion: (EvidenceLevel.d, "Weak"),
    StudyDesign.unclear: (EvidenceLevel.unclear, "Unclear"),
}


def map_evidence_level(design: StudyDesign) -> Tuple[EvidenceLevel, str]:
    """Map a study design to a provisional (level, human label) pair."""
    return _EVIDENCE_MAP.get(design, (EvidenceLevel.unclear, "Unclear"))


# ---------------------------------------------------------------------------
# CASP-style appraisal signals (phrase detection only — never the grade)
# ---------------------------------------------------------------------------
# Each signal: (id, question, positive patterns, concern patterns, note).
# First positive match → mentioned; else first concern match → concern;
# else not_found. Patterns are case-insensitive regexes.

_SignalSpec = Tuple[str, str, List[str], List[str], str]

_SHARED_EFFECT_PRECISION: _SignalSpec = (
    "effect_precision",
    "Is the estimate of effect reported with a confidence interval?",
    [r"95\s*%\s*(?:CI|confidence interval)", r"confidence interval"],
    [],
    "Precision (e.g. a 95% CI) helps judge whether a result could be chance.",
)

_SHARED_CONFOUNDING: _SignalSpec = (
    "confounding_adjustment",
    "Did the authors adjust for confounding?",
    [
        r"adjust(?:ed|ing)\s+for",
        r"multivari(?:ate|able)",
        r"propensity\s+score",
        r"cox\s+(?:proportional\s+)?hazard",
    ],
    [],
    "Observational associations can be driven by other differences between groups.",
)

_SHARED_ATTRITION: _SignalSpec = (
    "attrition_followup",
    "Is loss to follow-up or completion of the study described?",
    [
        r"lost to follow[-\s]?up",
        r"\battrition\b",
        r"dropout|drop[-\s]?out",
        r"completed the (?:study|trial|follow[-\s]?up)",
        r"follow[-\s]?up (?:rate|complete|was complete)",
    ],
    [],
    "Uneven losses can bias results if those who leave differ from those who stay.",
)

_RCT_SIGNALS: List[_SignalSpec] = [
    (
        "randomization",
        "Was assignment to groups randomized?",
        [
            r"randomi[sz]ed",
            r"randomly\s+(?:assigned|allocated)",
            r"\brandomi[sz]ation\b",
        ],
        [],
        "Random assignment is the key strength of a trial for causal questions.",
    ),
    (
        "allocation_concealment",
        "Was allocation concealed before assignment?",
        [
            r"allocation\s+conceal",
            r"sealed\s+(?:opaque\s+)?envelope",
            r"central(?:ized)?\s+randomi[sz]ation",
            r"interactive\s+voice\s+response",
        ],
        [],
        "Concealment stops recruiters from influencing who gets which arm.",
    ),
    (
        "blinding",
        "Were participants or assessors blinded to treatment?",
        [
            r"double[-\s]?blind",
            r"single[-\s]?blind",
            r"triple[-\s]?blind",
            r"\bblinded\b",
            r"\bmask(?:ed|ing)\b",
        ],
        [r"open[-\s]?label", r"\bunblinded\b", r"not\s+blinded"],
        "Blinding reduces expectation bias; open-label designs need more caution.",
    ),
    (
        "intention_to_treat",
        "Were participants analyzed in the groups to which they were assigned (ITT)?",
        [
            r"intention[-\s]?to[-\s]?treat",
            r"\bITT\b",
            r"as[-\s]?randomized",
        ],
        [r"per[-\s]?protocol\s+(?:analysis|population|set)"],
        "ITT preserves the benefits of randomization when people switch or drop out.",
    ),
    (
        "power_calculation",
        "Was a sample-size or power calculation reported?",
        [
            r"power\s+(?:calculation|analysis|ed\s+to)",
            r"sample[-\s]?size\s+(?:calculation|estimate|determination)",
            r"powered\s+to\s+detect",
        ],
        [],
        "An a priori power plan helps judge whether the study was big enough.",
    ),
    (
        "baseline_similarity",
        "Were baseline characteristics of the groups compared?",
        [
            r"baseline\s+characteristics",
            r"similar\s+at\s+baseline",
            r"groups\s+were\s+well\s+balanced",
            r"table\s*1",
        ],
        [],
        "Large baseline imbalances can undermine the randomization story.",
    ),
    _SHARED_ATTRITION,
    _SHARED_EFFECT_PRECISION,
]

_COHORT_SIGNALS: List[_SignalSpec] = [
    (
        "exposure_defined",
        "Is the exposure or cohort clearly defined?",
        [
            r"expos(?:ure|ed)\s+(?:was|were|defined|classified|assessed)",
            r"cohort\s+(?:of|included|compris)",
            r"eligible\s+(?:patients|participants|adults)",
        ],
        [],
        "A clear exposure definition makes the comparison interpretable.",
    ),
    (
        "outcome_ascertainment",
        "Is how outcomes were measured or ascertained described?",
        [
            r"outcome(?:s)?\s+(?:was|were)\s+(?:ascertained|assessed|defined|validated)",
            r"ascertain(?:ed|ment)",
            r"adjudicat(?:ed|ion)",
            r"validated\s+(?:against|using|by)",
        ],
        [],
        "Weak outcome measurement can invent or hide associations.",
    ),
    (
        "followup_duration",
        "Is the length of follow-up reported?",
        [
            r"follow(?:ed|[\s-]?up)\s+(?:for|over|of)\s+\d",
            r"median\s+follow[-\s]?up",
            r"mean\s+follow[-\s]?up",
            r"during\s+\d+\s+(?:years?|months?)\s+of\s+follow",
        ],
        [],
        "Too-short follow-up can miss late outcomes.",
    ),
    _SHARED_CONFOUNDING,
    _SHARED_ATTRITION,
    _SHARED_EFFECT_PRECISION,
]

_CASE_CONTROL_SIGNALS: List[_SignalSpec] = [
    (
        "case_definition",
        "Are cases clearly defined?",
        [
            r"cases?\s+(?:were|was)\s+(?:defined|identified|diagnosed|selected)",
            r"case\s+definition",
            r"incident\s+cases",
        ],
        [],
        "A sharp case definition reduces misclassification.",
    ),
    (
        "control_selection",
        "Is how controls were selected described?",
        [
            r"controls?\s+(?:were|was)\s+(?:selected|matched|chosen|recruited)",
            r"matched\s+controls?",
            r"control\s+group",
            r"\bcases?\s+and\s+controls?\b",
        ],
        [],
        "Controls should represent the population that produced the cases.",
    ),
    (
        "exposure_measurement",
        "Is exposure measurement described for cases and controls?",
        [
            r"expos(?:ure|ed)\s+(?:was|were|assessed|measured|ascertained)",
            r"self[-\s]?reported",
            r"questionnaire",
            r"interview(?:ed|s)?",
        ],
        [],
        "Recall and measurement bias are classic case-control threats.",
    ),
    _SHARED_CONFOUNDING,
    _SHARED_EFFECT_PRECISION,
]

_CROSS_SECTIONAL_SIGNALS: List[_SignalSpec] = [
    (
        "sampling_method",
        "Is the sampling or recruitment method described?",
        [
            r"random\s+sample",
            r"convenience\s+sample",
            r"consecutive\s+(?:patients|participants|subjects)",
            r"recruit(?:ed|ment)",
            r"sampling\s+(?:frame|method|strategy)",
        ],
        [],
        "Who was invited (and who wasn't) shapes how far results travel.",
    ),
    (
        "response_rate",
        "Is a response or participation rate reported?",
        [
            r"response\s+rate",
            r"participation\s+rate",
            r"response\s+of\s+\d",
            r"\d+\s*%\s+(?:responded|participat)",
        ],
        [],
        "Low response can make the sample unlike the target population.",
    ),
    (
        "outcome_measure",
        "Are the outcome measures defined?",
        [
            r"measur(?:ed|es?|ing)\s+(?:using|with|by)",
            r"assessed\s+(?:using|with|by)",
            r"validated\s+(?:scale|instrument|questionnaire|tool)",
            r"diagnostic\s+criteria",
        ],
        [],
        "Cross-sectional snapshots depend entirely on how things were measured.",
    ),
    _SHARED_CONFOUNDING,
    _SHARED_EFFECT_PRECISION,
]

_SYNTHESIS_SIGNALS: List[_SignalSpec] = [
    (
        "search_strategy",
        "Was a systematic literature search described?",
        [
            r"search(?:ed)?\s+(?:PubMed|MEDLINE|Embase|Cochrane|Scopus|Web of Science)",
            r"systematic(?:ally)?\s+search",
            r"database(?:s)?\s+(?:were\s+)?search",
            r"literature\s+search",
        ],
        [],
        "A transparent search is the backbone of a systematic review.",
    ),
    (
        "inclusion_criteria",
        "Are inclusion/eligibility criteria stated?",
        [
            r"inclusion\s+criteria",
            r"eligibility\s+criteria",
            r"inclusion\s+and\s+exclusion",
            r"studies\s+were\s+(?:included|eligible)\s+if",
        ],
        [],
        "Clear eligibility stops the review from cherry-picking studies.",
    ),
    (
        "study_quality",
        "Was risk of bias or study quality assessed?",
        [
            r"risk\s+of\s+bias",
            r"quality\s+assessment",
            r"critical\s+appraisal",
            r"Cochrane\s+(?:risk\s+of\s+bias|RoB)",
            r"Newcastle[-\s]?Ottawa",
            r"GRADE",
        ],
        [],
        "Pooling weak studies without noting bias can overstate certainty.",
    ),
    (
        "heterogeneity",
        "Is between-study heterogeneity considered?",
        [
            r"heterogeneity",
            r"\bI\s*[²2]\b",
            r"random[-\s]?effects",
            r"fixed[-\s]?effect",
        ],
        [],
        "High heterogeneity means a single pooled number may mislead.",
    ),
    (
        "reporting_standard",
        "Is a reporting standard (e.g. PRISMA) mentioned?",
        [r"\bPRISMA\b", r"MOOSE\b", r"registered\s+(?:in\s+)?PROSPERO"],
        [],
        "Reporting checklists make methods more transparent and reproducible.",
    ),
    _SHARED_EFFECT_PRECISION,
]

_GENERIC_SIGNALS: List[_SignalSpec] = [
    (
        "methods_described",
        "Are methods described enough to understand what was done?",
        [
            r"\bmethods?\b",
            r"we\s+(?:included|enrolled|studied|analyzed|analysed)",
            r"participants?\s+were",
        ],
        [],
        "Without a clear methods sketch, design and bias are hard to judge.",
    ),
    _SHARED_EFFECT_PRECISION,
]

_CHECKLIST_BY_DESIGN: Dict[StudyDesign, Tuple[str, List[_SignalSpec]]] = {
    StudyDesign.randomized_controlled_trial: ("RCT (CASP-style)", _RCT_SIGNALS),
    StudyDesign.cohort: ("Cohort (CASP-style)", _COHORT_SIGNALS),
    StudyDesign.case_control: ("Case-control (CASP-style)", _CASE_CONTROL_SIGNALS),
    StudyDesign.cross_sectional: ("Cross-sectional (CASP-style)", _CROSS_SECTIONAL_SIGNALS),
    StudyDesign.systematic_review: ("Systematic review (CASP-style)", _SYNTHESIS_SIGNALS),
    StudyDesign.meta_analysis: ("Meta-analysis (CASP-style)", _SYNTHESIS_SIGNALS),
    StudyDesign.case_series: ("Descriptive (generic signals)", _GENERIC_SIGNALS),
    StudyDesign.case_report: ("Descriptive (generic signals)", _GENERIC_SIGNALS),
    StudyDesign.narrative_review: ("Narrative review (generic signals)", _GENERIC_SIGNALS),
    StudyDesign.expert_opinion: ("Expert opinion (generic signals)", _GENERIC_SIGNALS),
    StudyDesign.unclear: ("Unclear design (generic signals)", _GENERIC_SIGNALS),
}


def _first_match(haystack: str, patterns: List[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, haystack, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _eval_signal(haystack: str, spec: _SignalSpec) -> AppraisalSignal:
    signal_id, question, positive, concern, note = spec
    hit = _first_match(haystack, positive)
    if hit:
        return AppraisalSignal(
            id=signal_id,
            question=question,
            status=AppraisalSignalStatus.mentioned,
            matched_phrase=hit,
            note=note,
        )
    worry = _first_match(haystack, concern)
    if worry:
        return AppraisalSignal(
            id=signal_id,
            question=question,
            status=AppraisalSignalStatus.concern,
            matched_phrase=worry,
            note=note,
        )
    return AppraisalSignal(
        id=signal_id,
        question=question,
        status=AppraisalSignalStatus.not_found,
        matched_phrase=None,
        note=note,
    )


def appraisal_text(
    abstract: str,
    full_text_sections: Optional[Dict[str, str]] = None,
    *,
    title: str = "",
) -> str:
    """Build the haystack used for appraisal signals (abstract + Methods/Results)."""
    parts: List[str] = []
    if title:
        parts.append(title)
    if abstract:
        parts.append(abstract)
    sections = full_text_sections or {}
    for keyword in ("METHOD", "RESULT"):
        section = section_text(sections, keyword)
        if section:
            parts.append(section)
    return "\n".join(parts)


def build_appraisal_checklist(
    design: StudyDesign,
    abstract: str,
    full_text_sections: Optional[Dict[str, str]] = None,
    *,
    title: str = "",
) -> AppraisalChecklist:
    """Detect design-specific CASP-style appraisal phrases. Never sets the grade.

    Status is phrase detection only: ``mentioned``, ``concern``, or ``not_found``.
    Absence of a phrase is not proof the study lacked that feature — only that the
    available text did not mention it.
    """
    label, specs = _CHECKLIST_BY_DESIGN.get(
        design, ("Unclear design (generic signals)", _GENERIC_SIGNALS)
    )
    haystack = appraisal_text(abstract or "", full_text_sections, title=title)
    signals = [_eval_signal(haystack, spec) for spec in specs]
    mentioned = sum(1 for s in signals if s.status == AppraisalSignalStatus.mentioned)
    concerns = sum(1 for s in signals if s.status == AppraisalSignalStatus.concern)
    return AppraisalChecklist(
        design=design,
        label=label,
        signals=signals,
        mentioned_count=mentioned,
        concern_count=concerns,
        total=len(signals),
    )


# ---------------------------------------------------------------------------
# Caution notes
# ---------------------------------------------------------------------------

_OBSERVATIONAL = {StudyDesign.cohort, StudyDesign.case_control, StudyDesign.cross_sectional}
_WEAK = {
    StudyDesign.case_series,
    StudyDesign.case_report,
    StudyDesign.narrative_review,
    StudyDesign.expert_opinion,
}


def build_caution_notes(
    design: StudyDesign,
    sample_size: Optional[int],
    has_abstract: bool,
    used_full_text: bool = False,
) -> List[str]:
    """Honest caveats shown alongside the evidence level."""
    scope = "the abstract and open-access full text" if used_full_text else "the abstract only"
    notes: List[str] = [
        f"Evidence level estimated from {scope}, not a full critical appraisal."
    ]
    if not has_abstract:
        notes.append("No abstract was available; this classification may be unreliable.")
    if design == StudyDesign.unclear:
        scope_design = (
            "the abstract or open-access full text"
            if used_full_text
            else "the abstract"
        )
        notes.append(
            f"Study design could not be confidently identified from {scope_design}."
        )
    if design in _OBSERVATIONAL:
        notes.append("Observational design limits causal inference.")
    if design in _WEAK:
        notes.append("This design sits low on common evidence hierarchies.")
    if design == StudyDesign.narrative_review:
        notes.append("A narrative review is not equivalent to a systematic review.")
    if sample_size is None and design not in _WEAK and has_abstract:
        notes.append("Sample size was not clearly reported in the abstract.")
    elif sample_size is not None and sample_size < 50:
        notes.append(f"Small reported sample size (n={sample_size}) may limit precision.")
    return notes


# ---------------------------------------------------------------------------
# Key-points summary (deterministic synthesis of the extracted fields)
# ---------------------------------------------------------------------------


def _first_sentence(text: str, max_len: int = 220) -> str:
    """First sentence of ``text``, truncated, so the summary stays short."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    sentence = parts[0] if parts else (text or "").strip()
    if len(sentence) > max_len:
        sentence = sentence[:max_len].rsplit(" ", 1)[0] + "…"
    return sentence


def compose_summary(
    *,
    study_design: StudyDesign,
    evidence_level: EvidenceLevel,
    evidence_label: str,
    population: Optional[str],
    intervention_or_exposure: Optional[str],
    comparator: Optional[str],
    primary_outcome: Optional[str],
    sample_size: Optional[int],
    key_finding: Optional[str],
    has_abstract: bool,
) -> Tuple[Optional[str], List[str]]:
    """Compose a short plain-language summary and an 'at a glance' bullet list.

    Purely a synthesis of the already-extracted fields — no new interpretation —
    so it stays explainable (extraction_method='rules').
    """
    design_name = (
        study_design.value.replace("_", " ") if study_design != StudyDesign.unclear else None
    )
    grade = (
        f"{evidence_level.value} · {evidence_label}"
        if evidence_level != EvidenceLevel.unclear
        else None
    )
    finding = _first_sentence(key_finding) if key_finding else None

    bullets: List[str] = []
    if design_name:
        bullets.append(f"Design: {design_name}" + (f" (level {grade})" if grade else ""))
    if sample_size is not None:
        bullets.append(f"Sample size: n = {sample_size:,}")
    if population:
        bullets.append(f"Population: {population}")
    if intervention_or_exposure and comparator:
        bullets.append(f"Compared: {intervention_or_exposure} vs {comparator}")
    elif intervention_or_exposure:
        bullets.append(f"Intervention/exposure: {intervention_or_exposure}")
    if primary_outcome:
        bullets.append(f"Outcome: {primary_outcome}")
    if finding:
        bullets.append(f"Finding: {finding}")

    if not has_abstract or (not design_name and not population and not key_finding):
        return None, bullets

    head = (design_name[0].upper() + design_name[1:]) if design_name else "Study"
    if grade:
        head += f" ({grade})"
    clause = head
    if population:
        clause += f" in {population}"
    if sample_size is not None:
        clause += f" (n = {sample_size:,})"
    if intervention_or_exposure and comparator:
        clause += f", comparing {intervention_or_exposure} with {comparator}"
    elif intervention_or_exposure:
        clause += f", examining {intervention_or_exposure}"

    sentences = [clause.rstrip(".") + "."]
    if primary_outcome:
        sentences.append(f"Primary outcome: {primary_outcome.rstrip('.')}.")
    if finding:
        sentences.append(finding.rstrip(".") + ".")
    return " ".join(sentences), bullets
