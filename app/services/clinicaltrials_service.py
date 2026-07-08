"""ClinicalTrials.gov retrieval via the public v2 API (no key).

Trial *records* are a different shape from journal articles (status, phase,
enrollment, interventions), so they get their own schema, service, and UI tab
rather than being forced through the article evidence pipeline.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import httpx

from app.config import get_settings
from app.services.errors import ArticleNotFound, SourceError

_BASE = "https://clinicaltrials.gov/api/v2/studies"
_settings = get_settings()
_HEADERS = {"User-Agent": f"ClinicalEvidenceAssistant/1.1 ({_settings.ncbi_email})"}

_PHASE_LABELS = {
    "EARLY_PHASE1": "Early Phase 1",
    "PHASE1": "Phase 1",
    "PHASE2": "Phase 2",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": "",
}


def _get(url: str, params: Optional[Dict] = None) -> dict:
    try:
        response = httpx.get(url, params=params, headers=_HEADERS, timeout=_settings.ncbi_timeout_seconds)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise ArticleNotFound("No ClinicalTrials.gov record for that id.") from exc
        raise SourceError(f"ClinicalTrials.gov request failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - normalize all transport/parse errors
        raise SourceError(f"ClinicalTrials.gov request failed: {exc}") from exc


def _humanize(value) -> Optional[str]:
    text = str(value or "").strip().replace("_", " ").title()
    return text or None


def _join_phases(phases) -> Optional[str]:
    labels = [_PHASE_LABELS.get(str(p).strip().upper(), _humanize(p) or "") for p in phases or []]
    return ", ".join(label for label in labels if label) or None


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_summary(study: dict) -> dict:
    ps = study.get("protocolSection", {}) or {}
    ident = ps.get("identificationModule", {}) or {}
    status = ps.get("statusModule", {}) or {}
    design = ps.get("designModule", {}) or {}
    conditions = (ps.get("conditionsModule", {}) or {}).get("conditions", []) or []
    return {
        "nct_id": str(ident.get("nctId", "")).strip(),
        "title": str(ident.get("briefTitle", "")).strip() or None,
        "status": _humanize(status.get("overallStatus")),
        "phase": _join_phases(design.get("phases")),
        "study_type": _humanize(design.get("studyType")),
        "conditions": [str(c).strip() for c in conditions if str(c).strip()][:8],
        "enrollment": _int_or_none((design.get("enrollmentInfo", {}) or {}).get("count")),
    }


def _parse_record(study: dict) -> dict:
    record = _parse_summary(study)
    ps = study.get("protocolSection", {}) or {}
    status = ps.get("statusModule", {}) or {}
    desc = ps.get("descriptionModule", {}) or {}
    arms = ps.get("armsInterventionsModule", {}) or {}
    sponsor = (ps.get("sponsorCollaboratorsModule", {}) or {}).get("leadSponsor", {}) or {}

    interventions: List[str] = []
    for iv in arms.get("interventions", []) or []:
        name = str(iv.get("name", "")).strip()
        if name:
            itype = _humanize(iv.get("type"))
            interventions.append(f"{itype}: {name}" if itype else name)

    record.update(
        {
            "brief_summary": str(desc.get("briefSummary", "")).strip() or None,
            "interventions": interventions[:10],
            "sponsor": str(sponsor.get("name", "")).strip() or None,
            "start_date": (status.get("startDateStruct", {}) or {}).get("date"),
            "completion_date": (status.get("completionDateStruct", {}) or {}).get("date")
            or (status.get("primaryCompletionDateStruct", {}) or {}).get("date"),
            "url": f"https://clinicaltrials.gov/study/{record['nct_id']}"
            if record["nct_id"]
            else "https://clinicaltrials.gov/",
        }
    )
    return record


def search_trials(query: str, max_results: int = 20) -> List[dict]:
    query = (query or "").strip()
    if not query:
        return []
    data = _get(_BASE, {"query.term": query, "pageSize": min(max_results, 50)})
    results: List[dict] = []
    for study in data.get("studies", []) or []:
        try:
            parsed = _parse_summary(study)
        except (KeyError, TypeError):
            continue
        if parsed["nct_id"]:
            results.append(parsed)
    return results


def fetch_trial(nct_id: str) -> dict:
    nct_id = str(nct_id).strip().upper()
    if not nct_id:
        raise ArticleNotFound("Empty trial id.")
    data = _get(f"{_BASE}/{nct_id}")
    try:
        return _parse_record(data)
    except (KeyError, TypeError) as exc:
        raise SourceError(f"Could not parse ClinicalTrials.gov record {nct_id}: {exc}") from exc
