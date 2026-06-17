"""API tests using FastAPI's TestClient. PubMed is monkeypatched (no network)."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import pubmed_service

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_analyze_inline_abstract():
    payload = {
        "title": "A randomized controlled trial of drug X",
        "abstract": (
            "In this randomized, double-blind, placebo-controlled trial, 320 patients "
            "were enrolled. The primary outcome was symptom improvement at 12 weeks."
        ),
    }
    response = client.post("/api/evidence/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["study_design"] == "randomized_controlled_trial"
    assert data["evidence_level"] == "B"
    assert data["evidence_label"] == "Moderate"
    assert data["sample_size"] == 320
    assert data["extraction_method"] == "rules"
    assert any("abstract only" in note for note in data["caution_notes"])


def test_analyze_pmid_uses_pubmed_service(monkeypatch):
    def fake_fetch(pmid):
        return {
            "article_id": pmid,
            "source_database": "pubmed",
            "title": "Coffee and longevity: a prospective cohort study",
            "abstract": (
                "In this prospective cohort study we followed 8000 adults for 10 years "
                "to examine all-cause mortality."
            ),
            "abstract_sections": {},
        }

    monkeypatch.setattr(pubmed_service, "fetch_article", fake_fetch)
    response = client.get("/api/evidence/article/12345")
    assert response.status_code == 200
    data = response.json()
    assert data["article_id"] == "12345"
    assert data["study_design"] == "cohort"
    assert data["evidence_level"] == "B"
    assert data["sample_size"] == 8000


def test_analyze_missing_input_returns_422():
    response = client.post("/api/evidence/analyze", json={})
    assert response.status_code == 422


def test_analyze_pmid_not_found_returns_404(monkeypatch):
    def fake_fetch(pmid):
        raise pubmed_service.ArticleNotFound("nope")

    monkeypatch.setattr(pubmed_service, "fetch_article", fake_fetch)
    response = client.get("/api/evidence/article/000")
    assert response.status_code == 404
