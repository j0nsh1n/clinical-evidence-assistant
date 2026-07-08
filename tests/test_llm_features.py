"""Tests for the AI status endpoint, PICO suggestions, and full-text Q&A (all mocked)."""

import json

import pytest

from app.main import app
from app.services import europepmc_service, llm_service
from fastapi.testclient import TestClient

client = TestClient(app)


def _stub_settings(**overrides):
    class _S:
        llm_provider = "auto"
        anthropic_api_key = None
        llm_model = "claude-sonnet-4-6"
        ollama_host = "http://localhost:11434"
        ollama_model = None
        llm_timeout_seconds = 120

    settings = _S()
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload) if isinstance(payload, dict) else str(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


# --- status -------------------------------------------------------------------


def test_status_no_provider(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings())
    s = llm_service.status()
    assert s["provider"] is None and s["reachable"] is False


def test_status_anthropic_reports_ready(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings(anthropic_api_key="sk-x"))
    s = llm_service.status()
    assert s["provider"] == "anthropic" and s["reachable"] is True and s["model_available"] is True


def test_status_ollama_running_with_model(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings(ollama_model="qwen2.5:14b"))
    monkeypatch.setattr(
        llm_service.httpx, "get", lambda *a, **k: _Resp({"models": [{"name": "qwen2.5:14b"}]})
    )
    s = llm_service.status()
    assert s == {
        "provider": "ollama",
        "model": "qwen2.5:14b",
        "reachable": True,
        "model_available": True,
        "detail": "Local AI ready (qwen2.5:14b).",
    }


def test_status_ollama_running_model_missing(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings(ollama_model="qwen2.5:14b"))
    monkeypatch.setattr(llm_service.httpx, "get", lambda *a, **k: _Resp({"models": [{"name": "gemma3:latest"}]}))
    s = llm_service.status()
    assert s["reachable"] is True and s["model_available"] is False
    assert "not pulled" in s["detail"]


def test_status_ollama_down(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings(ollama_model="qwen2.5:14b"))

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(llm_service.httpx, "get", boom)
    s = llm_service.status()
    assert s["reachable"] is False and "not running" in s["detail"]


def test_status_route(monkeypatch):
    monkeypatch.setattr(
        llm_service,
        "status",
        lambda: {"provider": "ollama", "model": "m", "reachable": False, "model_available": False, "detail": "d"},
    )
    data = client.get("/api/llm/status").json()
    assert data["provider"] == "ollama" and data["reachable"] is False


# --- PICO suggestions -----------------------------------------------------------


def test_suggest_pico_returns_only_requested_nonnull(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings(ollama_model="llama3.1"))
    content = json.dumps(
        {
            "population": "adults with asthma",
            "intervention_or_exposure": None,
            "comparator": "placebo",
            "primary_outcome": "exacerbation rate",
        }
    )
    monkeypatch.setattr(
        llm_service.httpx, "post", lambda *a, **k: _Resp({"message": {"content": content}})
    )
    out = llm_service.suggest_pico("T", "abstract text", ["population", "comparator"])
    assert out == {"population": "adults with asthma", "comparator": "placebo"}


def test_suggest_pico_route_validates_fields():
    response = client.post(
        "/api/evidence/suggest-pico",
        json={"abstract": "text", "fields": ["population", "bogus_field"]},
    )
    assert response.status_code == 422
    assert "bogus_field" in response.json()["detail"]


def test_suggest_pico_route_unconfigured(monkeypatch):
    monkeypatch.setattr(llm_service, "provider", lambda: None)
    response = client.post(
        "/api/evidence/suggest-pico", json={"abstract": "text", "fields": ["population"]}
    )
    assert response.status_code == 422
    assert "No LLM provider" in response.json()["detail"]


def test_suggest_pico_route_happy(monkeypatch):
    monkeypatch.setattr(llm_service, "suggest_pico", lambda t, a, f: {"population": "500 nurses"})
    data = client.post(
        "/api/evidence/suggest-pico", json={"abstract": "text", "fields": ["population"]}
    ).json()
    assert data["suggestions"] == {"population": "500 nurses"}


# --- full text fetch -------------------------------------------------------------

_JATS = """<article>
  <front><article-meta><title-group><article-title>T</article-title></title-group></article-meta></front>
  <body>
    <sec><title>Methods</title><p>{methods}</p></sec>
    <sec><title>Results</title><p>{results}</p></sec>
  </body>
</article>"""


def test_fetch_full_text_parses_sections(monkeypatch):
    xml = _JATS.format(methods="We enrolled 500 adults. " * 20, results="X improved Y. " * 20)
    seen = {}

    def fake_get(url, *a, **k):
        seen["url"] = url
        return _Resp(xml)

    monkeypatch.setattr(europepmc_service.httpx, "get", fake_get)
    text = europepmc_service.fetch_full_text("PMC123")
    assert seen["url"].endswith("/PMC123/fullTextXML")  # single-PMCID-segment endpoint
    assert text.startswith("## Methods")
    assert "## Results" in text
    assert "We enrolled 500 adults" in text


def test_fetch_full_text_requires_pmcid(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no PMCID → must not hit the network")

    monkeypatch.setattr(europepmc_service.httpx, "get", boom)
    assert europepmc_service.fetch_full_text(None) is None
    assert europepmc_service.fetch_full_text("12345") is None  # a PMID is not a PMCID


def test_fetch_full_text_none_on_404_or_short(monkeypatch):
    monkeypatch.setattr(europepmc_service.httpx, "get", lambda *a, **k: _Resp("nope", status=404))
    assert europepmc_service.fetch_full_text("PMC1") is None
    monkeypatch.setattr(
        europepmc_service.httpx, "get", lambda *a, **k: _Resp("<article><body><sec><p>tiny</p></sec></body></article>")
    )
    assert europepmc_service.fetch_full_text("PMC1") is None


def test_fetch_full_text_none_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(europepmc_service.httpx, "get", boom)
    assert europepmc_service.fetch_full_text("PMC1") is None


# --- ask ---------------------------------------------------------------------------


def test_ask_article_raises_num_ctx(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings(ollama_model="qwen3:14b"))
    captured = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs.get("json")
        return _Resp({"message": {"content": json.dumps({"answer": "It was double-blind.", "quotes": ["double-blind"]})}})

    monkeypatch.setattr(llm_service.httpx, "post", fake_post)
    out = llm_service.ask_article("Was it blinded?", "T", "## Methods\nDouble-blind.")
    assert out["answer"] == "It was double-blind."
    assert captured["json"]["options"]["num_ctx"] == 16384


def test_ask_route_falls_back_to_abstract(monkeypatch):
    # No OA full text, but the abstract is present → answer from the abstract, labelled.
    monkeypatch.setattr(europepmc_service, "fetch_full_text", lambda pmcid: None)
    monkeypatch.setattr(
        europepmc_service, "fetch_article", lambda aid: {"title": "T", "pmcid": None, "abstract": "Double-blind RCT."}
    )
    captured = {}

    def fake_ask(q, t, text):
        captured["text"] = text
        return {"answer": "It was double-blind.", "quotes": ["Double-blind"]}

    monkeypatch.setattr(llm_service, "ask_article", fake_ask)
    data = client.post(
        "/api/evidence/ask",
        json={"source": "europepmc", "article_id": "MED/1", "question": "Was it blinded?"},
    ).json()
    assert data["basis"] == "abstract"
    assert captured["text"] == "Double-blind RCT."


def test_ask_route_404_when_no_text_at_all(monkeypatch):
    monkeypatch.setattr(europepmc_service, "fetch_full_text", lambda pmcid: None)
    monkeypatch.setattr(europepmc_service, "fetch_article", lambda aid: {"title": "T", "pmcid": None, "abstract": None})
    response = client.post(
        "/api/evidence/ask",
        json={"source": "europepmc", "article_id": "MED/1", "question": "Was it blinded?"},
    )
    assert response.status_code == 404


def test_ask_route_rejects_other_sources():
    response = client.post(
        "/api/evidence/ask", json={"source": "pubmed", "article_id": "1", "question": "q"}
    )
    assert response.status_code == 422


def test_ask_route_happy_full_text(monkeypatch):
    monkeypatch.setattr(europepmc_service, "fetch_full_text", lambda pmcid: "## Methods\nlots of text")
    monkeypatch.setattr(
        europepmc_service, "fetch_article", lambda aid: {"title": "T", "pmcid": "PMC9", "abstract": "a"}
    )
    monkeypatch.setattr(
        llm_service, "ask_article", lambda q, t, txt: {"answer": "Yes, double-blind.", "quotes": ["double-blind"]}
    )
    data = client.post(
        "/api/evidence/ask",
        json={"source": "europepmc", "article_id": "PMC/PMC9", "question": "Blinded?"},
    ).json()
    assert data["answer"] == "Yes, double-blind."
    assert data["quotes"] == ["double-blind"]
    assert data["basis"] == "full text"
