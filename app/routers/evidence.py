"""Evidence analysis API routes (thin handlers; logic lives in services)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile

from app.schemas.evidence import (
    AnalyzeRequest,
    CompareRequest,
    CompareResponse,
    EvidenceAnalysis,
)
from app.schemas.llm import AskRequest, AskResponse, PicoSuggestRequest, PicoSuggestResponse
from app.services import europepmc_service, evidence_service, history_service, llm_service, pdf_service
from app.services.errors import ArticleNotFound, SourceError
from app.services.pubmed_service import PubMedError

router = APIRouter(prefix="/api/evidence", tags=["evidence"])

_MAX_PDF_BYTES = 15 * 1024 * 1024


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


@router.post("/compare", response_model=CompareResponse)
def compare(request: CompareRequest) -> CompareResponse:
    """Analyze several selected articles for a side-by-side comparison."""
    if not request.items:
        raise HTTPException(status_code=422, detail="Select at least one article to compare.")
    try:
        analyses = evidence_service.compare(request.items)
    except ArticleNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PubMedError, SourceError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return CompareResponse(count=len(analyses), analyses=analyses)


@router.post("/analyze-pdf", response_model=EvidenceAnalysis)
async def analyze_pdf(file: UploadFile) -> EvidenceAnalysis:
    """Analyze an article from an uploaded PDF (read locally; nothing leaves the machine)."""
    pdf_bytes = await file.read()
    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise HTTPException(status_code=422, detail="PDF is too large (15 MB limit).")
    try:
        extracted = pdf_service.extract_title_and_abstract(pdf_bytes)
        analysis = evidence_service.analyze_text(
            {
                "article_id": None,
                "source_database": "pdf",
                "title": extracted["title"],
                "abstract": extracted["abstract"],
                "abstract_sections": {},
            }
        )
        history_service.save(analysis)  # best-effort; never raises
        return analysis
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/suggest-pico", response_model=PicoSuggestResponse)
def suggest_pico(request: PicoSuggestRequest) -> PicoSuggestResponse:
    """AI-suggested phrases for PICO fields the rules marked 'not reported' (labeled hints)."""
    if not request.abstract.strip():
        raise HTTPException(status_code=422, detail="An abstract is required.")
    unknown = [f for f in request.fields if f not in llm_service.PICO_FIELDS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown PICO fields: {', '.join(unknown)}.")
    try:
        suggestions = llm_service.suggest_pico(request.title, request.abstract, request.fields)
    except llm_service.LLMUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except llm_service.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return PicoSuggestResponse(suggestions=suggestions)


@router.post("/ask", response_model=AskResponse)
def ask_article(request: AskRequest) -> AskResponse:
    """Q&A over a Europe PMC article — its legal open-access full text if available,
    otherwise its abstract (clearly labelled which)."""
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="Ask a question.")
    if request.source != "europepmc":
        raise HTTPException(status_code=422, detail="AI Q&A works for Europe PMC articles.")
    try:
        article = europepmc_service.fetch_article(request.article_id)
    except ArticleNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    text = europepmc_service.fetch_full_text(article.get("pmcid"))
    basis = "full text"
    if not text:
        text = article.get("abstract")
        basis = "abstract"
    if not text:
        raise HTTPException(status_code=404, detail="This article has no full text or abstract to answer from.")
    try:
        result = llm_service.ask_article(request.question, article.get("title"), text)
    except llm_service.LLMUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except llm_service.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AskResponse(basis=basis, **result)


@router.get("/article/{pmid}", response_model=EvidenceAnalysis)
def analyze_pmid(pmid: str) -> EvidenceAnalysis:
    """Convenience GET wrapper to analyze a single PubMed article by PMID."""
    return analyze(AnalyzeRequest(pmid=pmid))
