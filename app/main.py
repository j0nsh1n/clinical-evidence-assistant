"""FastAPI application entry point for the Clinical Evidence Assistant."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import evidence, history, llm, search, trials

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Provisional, abstract-level clinical evidence analysis for student "
        "researchers. Evidence levels are estimated from the abstract only and "
        "are not medical advice or a substitute for full critical appraisal."
    ),
)

app.include_router(evidence.router)
app.include_router(history.router)
app.include_router(llm.router)
app.include_router(search.router)
app.include_router(trials.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the single-page UI."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "healthy", "version": settings.app_version}
