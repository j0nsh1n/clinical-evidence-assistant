"""Retraction check — warn when an article has been retracted.

Two complementary signals, both free and legal:
  1. PubMed/Europe PMC publication-type tags: an article tagged "Retracted
     Publication" has been retracted. (The tag "Retraction of Publication" marks
     the retraction *notice* itself, not a retracted article — it must not match.)
  2. OpenAlex (open, no key), which integrates the Retraction Watch dataset and
     exposes an ``is_retracted`` flag per work, looked up by DOI.

Like the Unpaywall lookup, failures are swallowed (return not-retracted) so the
check never breaks an analysis. The flag is a warning only — it never feeds the
rule-based evidence level.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import httpx

from app.config import get_settings

_BASE = "https://api.openalex.org/works"
_settings = get_settings()


def retracted_in_pub_types(pub_types: Optional[List[str]]) -> bool:
    """True when the publication-type tags say the article was retracted."""
    return any("retracted publication" in str(p).lower() for p in (pub_types or []))


def check_retraction(
    doi: Optional[str], pub_types: Optional[List[str]] = None
) -> Dict[str, object]:
    """Return ``{"is_retracted": bool, "retraction_source": str | None}``."""
    if retracted_in_pub_types(pub_types):
        return {"is_retracted": True, "retraction_source": "publication-type tag"}

    doi_clean = (doi or "").strip().lower()
    if not doi_clean:
        return {"is_retracted": False, "retraction_source": None}
    doi_clean = doi_clean.removeprefix("https://doi.org/").removeprefix("doi:").strip("/")
    try:
        response = httpx.get(
            f"{_BASE}/doi:{doi_clean}",
            params={"mailto": _settings.ncbi_email, "select": "is_retracted"},
            timeout=_settings.ncbi_timeout_seconds,
        )
        if response.status_code != 200:
            return {"is_retracted": False, "retraction_source": None}
        data = response.json()
    except Exception:  # noqa: BLE001 - best-effort; never break an analysis
        return {"is_retracted": False, "retraction_source": None}

    if data.get("is_retracted"):
        return {"is_retracted": True, "retraction_source": "OpenAlex / Retraction Watch"}
    return {"is_retracted": False, "retraction_source": None}
