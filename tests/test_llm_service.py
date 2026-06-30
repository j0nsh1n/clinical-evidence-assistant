"""Unit tests for the optional LLM refinement service (no API calls)."""

import pytest

from app.services import llm_service


def test_build_prompt_includes_abstract_and_hints():
    prompt = llm_service._build_prompt(
        {"title": "A trial", "abstract": "Body text here", "study_design": "randomized_controlled_trial"}
    )
    assert "Body text here" in prompt
    assert "A trial" in prompt
    assert "randomized_controlled_trial" in prompt


def test_refine_raises_unavailable_without_key(monkeypatch):
    class _NoKey:
        anthropic_api_key = None
        llm_model = "claude-sonnet-4-6"

    monkeypatch.setattr(llm_service, "_settings", _NoKey())
    with pytest.raises(llm_service.LLMUnavailable):
        llm_service.refine({"abstract": "x"})
