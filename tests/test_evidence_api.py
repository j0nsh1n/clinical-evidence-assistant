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


def test_index_page_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Clinical Evidence Assistant" in response.text


def test_search_endpoint(monkeypatch):
    from app.schemas.evidence import ArticleSummary, EvidenceLevel, StudyDesign
    from app.services import evidence_service

    def fake_search(query, max_results=20):
        return [
            ArticleSummary(
                pmid="111",
                title="A meta-analysis",
                study_design=StudyDesign.meta_analysis,
                evidence_level=EvidenceLevel.a,
                evidence_label="High",
                publication_types=["Meta-Analysis"],
            )
        ]

    monkeypatch.setattr(evidence_service, "search", fake_search)
    response = client.get("/api/search?q=statins")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["pmid"] == "111"
    assert data["results"][0]["evidence_level"] == "A"


def test_search_requires_query():
    assert client.get("/api/search").status_code == 422


def test_analyze_includes_metadata_and_prefers_pubtype(monkeypatch):
    def fake_fetch(pmid):
        return {
            "article_id": pmid,
            "source_database": "pubmed",
            "title": "Some study",
            "abstract": "We studied 100 adults.",
            "abstract_sections": {},
            "authors": ["Smith J"],
            "journal": "J Tests",
            "year": "2020",
            "citation": "J Tests. 2020;1(1):1-10",
            "doi": "10.1/x",
            "publication_types": ["Meta-Analysis"],
            "keywords": ["asthma"],
        }

    monkeypatch.setattr(pubmed_service, "fetch_article", fake_fetch)
    data = client.get("/api/evidence/article/999").json()
    assert data["authors"] == ["Smith J"]
    assert data["doi"] == "10.1/x"
    assert data["publication_types"] == ["Meta-Analysis"]
    assert data["keywords"] == ["asthma"]
    # design comes from the PubMed publication type, not the (signal-free) text
    assert data["study_design"] == "meta_analysis"
    assert data["evidence_level"] == "A"
