"""Tests for the SQLite history / reading list (service + API; tmp db via conftest)."""

from app.main import app
from app.schemas.evidence import EvidenceAnalysis
from app.services import history_service
from fastapi.testclient import TestClient

client = TestClient(app)


def _analysis(**overrides):
    base = {
        "article_id": "12345",
        "source_database": "pubmed",
        "title": "A trial of X",
        "abstract": "In this randomized controlled trial, 200 patients were enrolled.",
        "study_design": "randomized_controlled_trial",
        "evidence_level": "B",
        "evidence_label": "Moderate",
    }
    base.update(overrides)
    return EvidenceAnalysis(**base)


# --- service ------------------------------------------------------------------


def test_save_and_get_roundtrip():
    row_id = history_service.save(_analysis())
    assert row_id is not None
    entry = history_service.get(row_id)
    assert entry["title"] == "A trial of X"
    assert entry["analysis"]["evidence_level"] == "B"
    assert entry["notes"] == ""


def test_upsert_by_source_and_id_preserves_notes():
    row_id = history_service.save(_analysis())
    history_service.set_notes(row_id, "my appraisal")
    again = history_service.save(_analysis(title="A trial of X (refined)"))
    assert again == row_id
    assert len(history_service.list_recent()) == 1
    entry = history_service.get(row_id)
    assert entry["title"] == "A trial of X (refined)"
    assert entry["notes"] == "my appraisal"


def test_manual_analyses_dedupe_by_content():
    a = history_service.save(_analysis(article_id=None, source_database="manual"))
    b = history_service.save(_analysis(article_id=None, source_database="manual"))
    assert a == b
    c = history_service.save(
        _analysis(article_id=None, source_database="manual", abstract="Different text entirely.")
    )
    assert c != a
    assert len(history_service.list_recent()) == 2


def test_list_recent_orders_newest_first_and_caps_limit():
    for i in range(5):
        history_service.save(_analysis(article_id=str(i), title=f"Study {i}"))
    items = history_service.list_recent(limit=3)
    assert len(items) == 3
    assert items[0]["title"] == "Study 4"


def test_delete_removes_row():
    row_id = history_service.save(_analysis())
    assert history_service.delete(row_id) is True
    assert history_service.get(row_id) is None
    assert history_service.delete(row_id) is False


# --- API ------------------------------------------------------------------------


def test_analyze_saves_to_history_api():
    response = client.post(
        "/api/evidence/analyze",
        json={"title": "An RCT", "abstract": "In this randomized controlled trial, 100 adults were enrolled."},
    )
    assert response.status_code == 200
    data = client.get("/api/history").json()
    assert data["count"] == 1
    item = data["items"][0]
    assert item["title"] == "An RCT"
    assert item["evidence_level"] == "B"

    entry = client.get(f"/api/history/{item['id']}").json()
    assert entry["analysis"]["study_design"] == "randomized_controlled_trial"


def test_notes_patch_and_delete_api():
    client.post("/api/evidence/analyze", json={"title": "T", "abstract": "A cohort study of 50 nurses."})
    item = client.get("/api/history").json()["items"][0]

    assert client.patch(f"/api/history/{item['id']}", json={"notes": "solid methods"}).status_code == 200
    assert client.get(f"/api/history/{item['id']}").json()["notes"] == "solid methods"

    assert client.delete(f"/api/history/{item['id']}").status_code == 200
    assert client.get(f"/api/history/{item['id']}").status_code == 404
    assert client.patch(f"/api/history/{item['id']}", json={"notes": "x"}).status_code == 404
