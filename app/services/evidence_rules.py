"""Rule-based extraction and provisional evidence scoring.

Every function here is **pure** (text in, structured data out) with no I/O, so it
is fast and trivially unit-testable. This is the auditable baseline of the
feature: an optional LLM pass may later refine human-readable fields, but the
evidence *level* should always remain explainable from these rules.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from app.schemas.evidence import (
    ClinicalQuestionType,
    EvidenceLevel,
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
    (StudyDesign.randomized_controlled_trial, 0.7, [r"randomi[sz]ed", r"double[-\s]?blind"]),
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
    design: StudyDesign, sample_size: Optional[int], has_abstract: bool
) -> List[str]:
    """Honest caveats shown alongside the evidence level."""
    notes: List[str] = [
        "Evidence level estimated from the abstract only, not a full critical appraisal."
    ]
    if not has_abstract:
        notes.append("No abstract was available; this classification may be unreliable.")
    if design == StudyDesign.unclear:
        notes.append("Study design could not be confidently identified from the abstract.")
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
