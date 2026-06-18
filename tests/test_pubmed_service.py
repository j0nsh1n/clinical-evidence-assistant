"""Unit tests for the PubMed layer (no network; Entrez is monkeypatched)."""

import pytest

from app.services import pubmed_service
from app.services.pubmed_service import ArticleNotFound, PubMedError


class _Handle:
    """Stand-in for an Entrez handle."""

    def close(self):
        pass


def test_join_abstract_plain_string():
    text, sections = pubmed_service._join_abstract("A flat abstract.")
    assert text == "A flat abstract."
    assert sections == {}


def test_join_abstract_none():
    text, sections = pubmed_service._join_abstract(None)
    assert text == ""
    assert sections == {}


def test_join_abstract_preserves_section_labels():
    class _Labeled(str):
        pass

    background = _Labeled("Background here.")
    background.attributes = {"Label": "BACKGROUND"}
    methods = _Labeled("We did X.")
    methods.attributes = {"Label": "METHODS"}

    text, sections = pubmed_service._join_abstract([background, methods])
    assert text == "Background here. We did X."
    assert sections == {"BACKGROUND": "Background here.", "METHODS": "We did X."}


def test_fetch_article_empty_pmid_raises_not_found():
    with pytest.raises(ArticleNotFound):
        pubmed_service.fetch_article("   ")


def test_fetch_article_no_record_raises_not_found(monkeypatch):
    monkeypatch.setattr(pubmed_service.Entrez, "efetch", lambda **kw: _Handle())
    monkeypatch.setattr(pubmed_service.Entrez, "read", lambda handle: {"PubmedArticle": []})
    with pytest.raises(ArticleNotFound):
        pubmed_service.fetch_article("123")


def test_fetch_article_malformed_record_raises_pubmed_error(monkeypatch):
    # A PubmedArticle missing MedlineCitation -> _parse_record KeyError, which
    # must surface as a PubMedError (502), not an uncaught 500.
    monkeypatch.setattr(pubmed_service.Entrez, "efetch", lambda **kw: _Handle())
    monkeypatch.setattr(pubmed_service.Entrez, "read", lambda handle: {"PubmedArticle": [{}]})
    with pytest.raises(PubMedError):
        pubmed_service.fetch_article("123")


def test_fetch_article_transport_error_raises_pubmed_error(monkeypatch):
    def boom(**kw):
        raise OSError("connection reset")

    monkeypatch.setattr(pubmed_service.Entrez, "efetch", boom)
    with pytest.raises(PubMedError):
        pubmed_service.fetch_article("123")
