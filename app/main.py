"""FastAPI application entry point for the Clinical Evidence Assistant."""

from __future__ import annotations

from fastapi import FastAPI

from app.config import get_settings
from app.routers import evidence

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


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "healthy", "version": settings.app_version}
