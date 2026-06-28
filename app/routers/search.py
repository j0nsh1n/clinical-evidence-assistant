"""PubMed search route (thin handler; logic lives in services)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.evidence import SearchResponse
from app.services import evidence_service
from app.services.pubmed_service import PubMedError

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="Search terms."),
    source: str = Query("europepmc", description="Source: 'europepmc' or 'pubmed'."),
    max_results: int = Query(20, ge=1, le=50, description="Maximum number of results."),
) -> SearchResponse:
    """Search a source and return article summaries, each with an evidence-level hint."""
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Provide a non-empty search query.")
    try:
        results = evidence_service.search(query, source=source, max_results=max_results)
    except PubMedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SearchResponse(query=query, count=len(results), results=results)
