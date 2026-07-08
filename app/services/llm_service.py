"""Optional LLM refinement of the human-readable summary (extraction_method='rules+llm').

Sends the abstract plus the rule-extracted fields to an LLM and asks for a cleaner
plain-language summary, a limitations note, and tidy key points. The evidence *level*
is never asked of the model — it stays rule-based and auditable; the LLM only rewrites
prose, and is told not to invent anything beyond the abstract.

Two providers are supported (see ``provider()``):
  • Ollama    — a local model (free, no API key). Preferred in the default "auto" mode.
  • Anthropic — the cloud Claude API (needs ``ANTHROPIC_API_KEY``).
When neither is configured, callers fall back to the rules summary. The ``anthropic``
package is imported lazily so the app runs without it; Ollama uses ``httpx`` (already a
dependency), so no extra package is required.
"""

from __future__ import annotations

from typing import List, Optional

import httpx
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


def provider() -> Optional[str]:
    """Pick the active LLM provider, honoring ``LLM_PROVIDER``.

    "auto" (the default) prefers a local Ollama model so refinement is free, then
    falls back to Anthropic. "ollama" or "anthropic" force that provider (returning
    None if it isn't configured). None means no provider is available — callers then
    use the rules-based summary.
    """
    pref = (_settings.llm_provider or "auto").strip().lower()
    has_anthropic = bool(_settings.anthropic_api_key)
    has_ollama = bool(_settings.ollama_model)
    if pref == "anthropic":
        return "anthropic" if has_anthropic else None
    if pref == "ollama":
        return "ollama" if has_ollama else None
    # "auto": prefer the local model, then the cloud API.
    if has_ollama:
        return "ollama"
    if has_anthropic:
        return "anthropic"
    return None


def is_configured() -> bool:
    return provider() is not None


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
    """Return ``{summary, limitations, key_points}`` refined by the active LLM.

    ``article`` carries: title, abstract, study_design, evidence_level, sample_size,
    population, intervention, comparator, primary_outcome. Dispatches to the local
    Ollama model or the Anthropic API per ``provider()``.
    """
    parsed: LLMSummary = _structured_call(_SYSTEM, _build_prompt(article), LLMSummary)
    return {
        "summary": parsed.summary.strip(),
        "limitations": parsed.limitations.strip() or None,
        "key_points": [p.strip() for p in parsed.key_points if p.strip()],
    }


# --- generic structured-output dispatch (shared by refine / PICO / ask) ---


def _structured_call(system: str, prompt: str, schema_model, num_ctx: Optional[int] = None):
    """Run one structured-output request on the active provider; returns the parsed model."""
    selected = provider()
    if selected is None:
        raise LLMUnavailable("No LLM provider configured. Set OLLAMA_MODEL or ANTHROPIC_API_KEY.")
    if selected == "ollama":
        return _structured_ollama(system, prompt, schema_model, num_ctx=num_ctx)
    return _structured_anthropic(system, prompt, schema_model)


def _structured_anthropic(system: str, prompt: str, schema_model):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the package
        raise LLMUnavailable("The 'anthropic' package is not installed.") from exc

    client = anthropic.Anthropic(api_key=_settings.anthropic_api_key)
    try:
        message = client.messages.parse(
            model=_settings.llm_model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema_model,
        )
    except Exception as exc:  # noqa: BLE001 - normalize all SDK/transport errors
        raise LLMError(f"LLM request failed: {exc}") from exc

    parsed = message.parsed_output
    if parsed is None:
        raise LLMError("LLM returned no parseable output.")
    return parsed


def _structured_ollama(system: str, prompt: str, schema_model, num_ctx: Optional[int] = None):
    """Call a local Ollama model using its structured-output ``format`` option.

    Ollama accepts a JSON schema in ``format`` and returns the assistant message as a
    JSON string matching it (see the Ollama API docs, /api/chat). ``num_ctx`` raises
    the context window for long inputs (full-text Q&A) — Ollama's default is small.
    """
    options: dict = {"temperature": 0.2}
    if num_ctx:
        options["num_ctx"] = num_ctx
    try:
        response = httpx.post(
            f"{_settings.ollama_host.rstrip('/')}/api/chat",
            json={
                "model": _settings.ollama_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "format": schema_model.model_json_schema(),
                "stream": False,
                "options": options,
            },
            timeout=_settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        content = (response.json().get("message") or {}).get("content") or ""
    except Exception as exc:  # noqa: BLE001 - normalize all transport/HTTP errors
        raise LLMError(f"Ollama request failed: {exc}") from exc

    try:
        return schema_model.model_validate_json(content)
    except Exception as exc:  # noqa: BLE001 - empty or non-conforming JSON from the model
        raise LLMError(f"Ollama returned no parseable output: {exc}") from exc


# --- provider status (for the UI's honest AI hints) ---


def status() -> dict:
    """Report the active provider and, for Ollama, live reachability.

    The app never starts Ollama itself — the user runs it only when wanted — so
    the UI uses this to say "start Ollama to enable AI" instead of failing late.
    """
    selected = provider()
    if selected is None:
        return {
            "provider": None,
            "model": None,
            "reachable": False,
            "model_available": False,
            "detail": "No AI configured. Set OLLAMA_MODEL (local) or ANTHROPIC_API_KEY in .env.",
        }
    if selected == "anthropic":
        return {
            "provider": "anthropic",
            "model": _settings.llm_model,
            "reachable": True,
            "model_available": True,
            "detail": f"Anthropic API ({_settings.llm_model}) configured.",
        }
    model = _settings.ollama_model
    try:
        response = httpx.get(f"{_settings.ollama_host.rstrip('/')}/api/tags", timeout=2)
        response.raise_for_status()
        names = [str(m.get("name", "")) for m in response.json().get("models", [])]
    except Exception:  # noqa: BLE001 - server down or unreachable
        return {
            "provider": "ollama",
            "model": model,
            "reachable": False,
            "model_available": False,
            "detail": "Ollama is not running — start it (ollama serve, or the Ollama app) to enable AI features.",
        }
    available = any(n == model or n.split(":")[0] == model for n in names)
    return {
        "provider": "ollama",
        "model": model,
        "reachable": True,
        "model_available": available,
        "detail": (
            f"Local AI ready ({model})."
            if available
            else f"Ollama is running but '{model}' is not pulled (ollama pull {model})."
        ),
    }


# --- PICO suggestions for fields the rules could not extract ---

_PICO_SYSTEM = (
    "You extract PICO elements from a clinical abstract for a student. Use ONLY wording "
    "supported by the abstract — never invent or embellish. Keep each phrase under 12 "
    "words. If an element is genuinely not reported, set it to null. This is a study "
    "aid, not medical advice."
)


class PICOSuggestions(BaseModel):
    """Structured output for AI-suggested PICO fields (labeled hints, never the rules)."""

    population: Optional[str] = Field(default=None, description="Who was studied, or null.")
    intervention_or_exposure: Optional[str] = Field(default=None, description="Treatment/exposure, or null.")
    comparator: Optional[str] = Field(default=None, description="What it was compared against, or null.")
    primary_outcome: Optional[str] = Field(default=None, description="Main measured outcome, or null.")


PICO_FIELDS = ("population", "intervention_or_exposure", "comparator", "primary_outcome")


def suggest_pico(title: Optional[str], abstract: str, fields: List[str]) -> dict:
    """Return AI-suggested phrases for the requested missing PICO fields only."""
    wanted = [f for f in fields if f in PICO_FIELDS]
    if not wanted:
        return {}
    prompt = (
        f"Title: {title or 'Untitled'}\n\nAbstract:\n{abstract}\n\n"
        f"Suggest a concise phrase for each of these fields the rule-based reader "
        f"could not find: {', '.join(wanted)}. Null anything not reported."
    )
    parsed: PICOSuggestions = _structured_call(_PICO_SYSTEM, prompt, PICOSuggestions)
    out = {}
    for field_name in wanted:
        value = (getattr(parsed, field_name) or "").strip()
        if value:
            out[field_name] = value
    return out


# --- "Ask this article" Q&A over legal open-access full text ---

_ASK_SYSTEM = (
    "You answer a student's question about ONE clinical article using ONLY the article "
    "text provided. Quote 1-3 short verbatim snippets that support your answer. If the "
    "article does not address the question, say so plainly. Do not use outside knowledge, "
    "do not speculate, and do not give medical advice."
)


class ArticleAnswer(BaseModel):
    """Structured output for full-text Q&A."""

    answer: str = Field(description="Direct plain-language answer grounded in the article text.")
    quotes: List[str] = Field(
        default_factory=list, description="1-3 short verbatim supporting snippets from the article."
    )


def ask_article(question: str, title: Optional[str], article_text: str) -> dict:
    """Answer a question from open-access full text; returns {answer, quotes}."""
    prompt = (
        f"Article title: {title or 'Untitled'}\n\nArticle text:\n{article_text}\n\n"
        f"Question: {question}"
    )
    parsed: ArticleAnswer = _structured_call(_ASK_SYSTEM, prompt, ArticleAnswer, num_ctx=16384)
    return {
        "answer": parsed.answer.strip(),
        "quotes": [q.strip() for q in parsed.quotes if q.strip()][:3],
    }
