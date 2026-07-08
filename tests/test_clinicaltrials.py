"""Tests for the ClinicalTrials.gov service + routes (the v2 API is monkeypatched)."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import clinicaltrials_service

client = TestClient(app)

_SEARCH = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT01", "briefTitle": "A trial of X in asthma"},
                "statusModule": {"overallStatus": "RECRUITING"},
                "designModule": {
                    "studyType": "INTERVENTIONAL",
                    "phases": ["PHASE2", "PHASE3"],
                    "enrollmentInfo": {"count": 300},
                },
                "conditionsModule": {"conditions": ["Asthma"]},
            }
        }
    ]
}

_RECORD = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT01", "briefTitle": "A trial of X in asthma"},
        "statusModule": {
            "overallStatus": "COMPLETED",
            "startDateStruct": {"date": "2020-01"},
            "completionDateStruct": {"date": "2022-06"},
        },
        "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE3"], "enrollmentInfo": {"count": 300}},
        "conditionsModule": {"conditions": ["Asthma"]},
        "descriptionModule": {"briefSummary": "This study evaluates X in adults with asthma."},
        "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "Drug X"}]},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Acme"}},
    }
}


def test_trials_search(monkeypatch):
    monkeypatch.setattr(clinicaltrials_service, "_get", lambda url, params=None: _SEARCH)
    data = client.get("/api/trials?q=asthma").json()
    assert data["count"] == 1
    row = data["results"][0]
    assert row["nct_id"] == "NCT01"
    assert row["status"] == "Recruiting"
    assert row["phase"] == "Phase 2, Phase 3"
    assert row["study_type"] == "Interventional"
    assert row["enrollment"] == 300


def test_trials_search_requires_query():
    assert client.get("/api/trials").status_code == 422


def test_trial_record(monkeypatch):
    monkeypatch.setattr(clinicaltrials_service, "_get", lambda url, params=None: _RECORD)
    data = client.get("/api/trials/NCT01").json()
    assert data["nct_id"] == "NCT01"
    assert data["status"] == "Completed"
    assert data["phase"] == "Phase 3"
    assert data["brief_summary"].startswith("This study evaluates X")
    assert data["interventions"] == ["Drug: Drug X"]
    assert data["sponsor"] == "Acme"
    assert data["completion_date"] == "2022-06"
    assert data["url"].endswith("/study/NCT01")


def test_trial_record_not_found(monkeypatch):
    """A 404 from the API becomes a 404 (not a 502) — exercises the real _get mapping."""
    import httpx

    def fake_get(url, params=None, headers=None, timeout=None):
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(clinicaltrials_service.httpx, "get", fake_get)
    assert client.get("/api/trials/NCT404").status_code == 404
