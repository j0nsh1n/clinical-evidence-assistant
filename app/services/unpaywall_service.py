"""Unpaywall lookup — find a *legal* open-access copy of an article by DOI.

Given a DOI, Unpaywall returns whether a free, lawful full-text version exists
(publisher OA, an accepted manuscript in a repository, PMC, etc.) and the best
link to it. This is how we surface "free copies of paywalled articles" without
touching anything pirated. Failures are swallowed (return not-OA) so a lookup
never breaks an analysis.
"""

from __future__ import annotations

from typing import Dict, Optional

import httpx

from app.config import get_settings

_BASE = "https://api.unpaywall.org/v2"
_settings = get_settings()


def find_open_access(doi: Optional[str]) -> Dict[str, Optional[str]]:
    """Return ``{"is_open_access": bool, "oa_url": str | None}`` for a DOI."""
    result: Dict[str, Optional[str]] = {"is_open_access": False, "oa_url": None}
    doi = (doi or "").strip().lower()
    if not doi:
        return result
    doi = doi.removeprefix("https://doi.org/").removeprefix("doi:").strip("/")
    try:
        response = httpx.get(
            f"{_BASE}/{doi}",
            params={"email": _settings.ncbi_email},
            timeout=_settings.ncbi_timeout_seconds,
        )
        if response.status_code != 200:
            return result
        data = response.json()
    except Exception:  # noqa: BLE001 - OA lookup is best-effort; never raise
        return result

    if data.get("is_oa"):
        best = data.get("best_oa_location") or {}
        result["is_open_access"] = True
        result["oa_url"] = best.get("url_for_pdf") or best.get("url") or data.get("doi_url")
    return result
