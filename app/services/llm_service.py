"""Optional LLM refinement of the human-readable summary (extraction_method='rules+llm').

Sends the abstract plus the rule-extracted fields to the Anthropic API and asks for a
cleaner plain-language summary, a limitations note, and tidy key points. The evidence
*level* is never asked of the model — it stays rule-based and auditable; the LLM only
rewrites prose, and is told not to invent anything beyond the abstract.

Requires ``ANTHROPIC_API_KEY`` (via config). When unset, callers fall back to the rules
summary. The ``anthropic`` package is imported lazily so the app runs without it.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.config import get_settings

_settings = get_settings()


class LLMUnavailable(RuntimeError):
    """No API key configured, or the anthropic SDK is not installed."""


class LLMError(RuntimeError):
    """The Anthropic API call failed or returned no usable output."""


class LLMSummary(BaseModel):
    """Structured output contract for the refinement call."""

    summary: str = Field(description="2-4 sentence plain-language summary of what the study did and found.")
    limitations: str = Field(description="1-2 sentences on the study's main limitations, appropriately hedged.")
    key_points: List[str] = Field(description="3-6 short 'at a glance' bullet points.")


_SYSTEM = (
    "You are a careful clinical-evidence study aid for students. Summarize ONLY what the "
    "abstract states — never invent results, numbers, populations, or claims that are not "
    "present. Be plain-language and concise. Do NOT assign an evidence level or grade "
    "(that is handled separately by transparent rules). Hedge appropriately. This is a "
    "study aid, not medical advice."
)


def is_configured() -> bool:
    return bool(_settings.anthropic_api_key)


def _build_prompt(article: dict) -> str:
    hints = []
    for label, value in (
        ("Detected design", article.get("study_design")),
        ("Provisional level", article.get("evidence_level")),
        ("Sample size", article.get("sample_size")),
        ("Population", article.get("population")),
        ("Intervention/exposure", article.get("intervention")),
        ("Comparator", article.get("comparator")),
        ("Primary outcome", article.get("primary_outcome")),
    ):
        if value not in (None, ""):
            hints.append(f"- {label}: {value}")
    hint_block = "\n".join(hints) or "- (none extracted)"
    return (
        f"Title: {article.get('title') or 'Untitled'}\n\n"
        f"Rule-based extraction (context only — do not re-grade):\n{hint_block}\n\n"
        f"Abstract:\n{article.get('abstract') or '(no abstract)'}\n\n"
        "Write a faithful key-points summary, a short limitations note, and 3-6 bullet points."
    )


def refine(article: dict) -> dict:
    """Return ``{summary, limitations, key_points}`` refined by the LLM.

    ``article`` carries: title, abstract, study_design, evidence_level, sample_size,
    population, intervention, comparator, primary_outcome.
    """
    if not is_configured():
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set.")
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the package
        raise LLMUnavailable("The 'anthropic' package is not installed.") from exc

    client = anthropic.Anthropic(api_key=_settings.anthropic_api_key)
    try:
        message = client.messages.parse(
            model=_settings.llm_model,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _build_prompt(article)}],
            output_format=LLMSummary,
        )
    except Exception as exc:  # noqa: BLE001 - normalize all SDK/transport errors
        raise LLMError(f"LLM request failed: {exc}") from exc

    parsed: Optional[LLMSummary] = message.parsed_output
    if parsed is None:
        raise LLMError("LLM returned no parseable summary.")
    return {
        "summary": parsed.summary.strip(),
        "limitations": parsed.limitations.strip() or None,
        "key_points": [p.strip() for p in parsed.key_points if p.strip()],
    }
