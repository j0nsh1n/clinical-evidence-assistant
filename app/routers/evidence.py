"""Evidence analysis API routes (thin handlers; logic lives in services)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.evidence import AnalyzeRequest, EvidenceAnalysis
from app.services import evidence_service
from app.services.pubmed_service import ArticleNotFound, PubMedError

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


@router.post("/analyze", response_model=EvidenceAnalysis)
def analyze(request: AnalyzeRequest) -> EvidenceAnalysis:
    """Analyze one article (by PMID or by supplied title/abstract text)."""
    try:
        return evidence_service.analyze_article(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ArticleNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PubMedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/article/{pmid}", response_model=EvidenceAnalysis)
def analyze_pmid(pmid: str) -> EvidenceAnalysis:
    """Convenience GET wrapper to analyze a single PubMed article by PMID."""
    return analyze(AnalyzeRequest(pmid=pmid))
