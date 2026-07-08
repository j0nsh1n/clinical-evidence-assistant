"""ClinicalTrials.gov search + record routes (separate from the article pipeline)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.trials import TrialRecord, TrialSearchResponse, TrialSummary
from app.services import clinicaltrials_service
from app.services.errors import ArticleNotFound, SourceError

router = APIRouter(prefix="/api/trials", tags=["trials"])


@router.get("", response_model=TrialSearchResponse)
def search_trials(
    q: str = Query(..., min_length=1, description="Search terms."),
    max_results: int = Query(20, ge=1, le=50, description="Maximum number of results."),
) -> TrialSearchResponse:
    """Search ClinicalTrials.gov and return lightweight trial summaries."""
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Provide a non-empty search query.")
    try:
        rows = clinicaltrials_service.search_trials(query, max_results=max_results)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TrialSearchResponse(query=query, count=len(rows), results=[TrialSummary(**r) for r in rows])


@router.get("/{nct_id}", response_model=TrialRecord)
def get_trial(nct_id: str) -> TrialRecord:
    """Fetch one trial record by NCT id."""
    try:
        record = clinicaltrials_service.fetch_trial(nct_id)
    except ArticleNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TrialRecord(**record)
