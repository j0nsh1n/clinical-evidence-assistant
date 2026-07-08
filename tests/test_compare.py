"""Tests for the multi-article comparison endpoint (sources monkeypatched)."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import europepmc_service

client = TestClient(app)


def _fake_article(article_id):
    designs = {
        "MED/1": ("A systematic review and meta-analysis of statins", "systematic_review"),
        "MED/2": ("A randomized controlled trial of statins", "trial"),
    }
    title, _ = designs.get(article_id, ("Untitled", ""))
    abstract = (
        "This systematic review and meta-analysis pooled 12 trials."
        if article_id == "MED/1"
        else "In this randomized controlled trial, 500 adults were enrolled."
    )
    return {
        "article_id": article_id,
        "source_database": "europepmc",
        "title": title,
        "abstract": abstract,
        "abstract_sections": {},
    }


def test_compare_returns_one_analysis_per_item(monkeypatch):
    monkeypatch.setattr(europepmc_service, "fetch_article", _fake_article)
    payload = {"items": [{"source": "europepmc", "article_id": "MED/1"}, {"source": "europepmc", "article_id": "MED/2"}]}
    response = client.post("/api/evidence/compare", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert data["analyses"][0]["study_design"] in {"systematic_review", "meta_analysis"}
    assert data["analyses"][0]["evidence_level"] == "A"
    assert data["analyses"][1]["study_design"] == "randomized_controlled_trial"
    assert data["analyses"][1]["evidence_level"] == "B"


def test_compare_empty_returns_422():
    assert client.post("/api/evidence/compare", json={"items": []}).status_code == 422
