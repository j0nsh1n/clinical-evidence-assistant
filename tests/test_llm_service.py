"""Unit tests for the optional LLM refinement service (no real API/network calls)."""

import json

import pytest

from app.services import llm_service


def _stub_settings(**overrides):
    """A minimal stand-in for Settings with all LLM-related attributes present."""

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
    """Stand-in for an httpx.Response (Ollama /api/chat)."""

    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_build_prompt_includes_abstract_and_hints():
    prompt = llm_service._build_prompt(
        {"title": "A trial", "abstract": "Body text here", "study_design": "randomized_controlled_trial"}
    )
    assert "Body text here" in prompt
    assert "A trial" in prompt
    assert "randomized_controlled_trial" in prompt


def test_refine_raises_unavailable_without_provider(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings())
    assert llm_service.is_configured() is False
    with pytest.raises(llm_service.LLMUnavailable):
        llm_service.refine({"abstract": "x"})


# --- provider selection -----------------------------------------------------


def test_provider_auto_prefers_local_ollama(monkeypatch):
    # Both configured; "auto" should pick the free local model.
    monkeypatch.setattr(
        llm_service, "_settings", _stub_settings(anthropic_api_key="sk-test", ollama_model="llama3.1")
    )
    assert llm_service.provider() == "ollama"


def test_provider_auto_falls_back_to_anthropic(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings(anthropic_api_key="sk-test"))
    assert llm_service.provider() == "anthropic"


def test_provider_forced_ollama_requires_model(monkeypatch):
    # Forced to ollama but no model pulled → unavailable (won't silently use the key).
    monkeypatch.setattr(
        llm_service, "_settings", _stub_settings(llm_provider="ollama", anthropic_api_key="sk-test")
    )
    assert llm_service.provider() is None


def test_provider_forced_anthropic_ignores_ollama(monkeypatch):
    monkeypatch.setattr(
        llm_service,
        "_settings",
        _stub_settings(llm_provider="anthropic", anthropic_api_key="sk-test", ollama_model="llama3.1"),
    )
    assert llm_service.provider() == "anthropic"


# --- local Ollama refinement ------------------------------------------------


def test_refine_ollama_parses_structured_output(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings(ollama_model="llama3.1"))
    content = json.dumps(
        {"summary": "A clear summary.", "limitations": "Small sample.", "key_points": ["one", "two", "  "]}
    )
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _Resp({"message": {"role": "assistant", "content": content}})

    monkeypatch.setattr(llm_service.httpx, "post", fake_post)
    result = llm_service.refine({"title": "t", "abstract": "a"})

    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["model"] == "llama3.1"
    assert captured["json"]["stream"] is False
    assert "format" in captured["json"]  # structured-output JSON schema is sent
    assert result["summary"] == "A clear summary."
    assert result["limitations"] == "Small sample."
    assert result["key_points"] == ["one", "two"]  # blank bullet dropped


def test_refine_ollama_network_error_raises_llmerror(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings(ollama_model="llama3.1"))

    def boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(llm_service.httpx, "post", boom)
    with pytest.raises(llm_service.LLMError):
        llm_service.refine({"abstract": "x"})


def test_refine_ollama_bad_json_raises_llmerror(monkeypatch):
    monkeypatch.setattr(llm_service, "_settings", _stub_settings(ollama_model="llama3.1"))
    monkeypatch.setattr(
        llm_service.httpx, "post", lambda *a, **k: _Resp({"message": {"content": "not json"}})
    )
    with pytest.raises(llm_service.LLMError):
        llm_service.refine({"abstract": "x"})
