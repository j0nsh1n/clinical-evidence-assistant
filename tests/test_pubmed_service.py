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


def test_parse_summary_extracts_fields():
    docsum = {
        "Id": "123",
        "Title": "A trial of X.",
        "AuthorList": ["Smith J", "Doe A"],
        "FullJournalName": "Journal of Tests",
        "Source": "J Tests",
        "PubDate": "2020 Jan 15",
        "PubTypeList": ["Journal Article", "Randomized Controlled Trial"],
        "DOI": "10.1000/xyz",
    }
    row = pubmed_service._parse_summary(docsum)
    assert row["pmid"] == "123"
    assert row["year"] == "2020"
    assert row["authors"] == ["Smith J", "Doe A"]
    assert row["journal"] == "Journal of Tests"
    assert "Randomized Controlled Trial" in row["publication_types"]
    assert "Journal Article" not in row["publication_types"]
    assert row["doi"] == "10.1000/xyz"


def test_search_articles_empty_query_returns_empty():
    assert pubmed_service.search_articles("   ") == []


def test_search_articles_pipeline(monkeypatch):
    monkeypatch.setattr(pubmed_service, "search", lambda q, max_results=20: ["111", "222"])
    monkeypatch.setattr(pubmed_service.Entrez, "esummary", lambda **kw: _Handle())
    monkeypatch.setattr(
        pubmed_service.Entrez,
        "read",
        lambda handle: [
            {"Id": "111", "Title": "A", "PubTypeList": ["Meta-Analysis"], "PubDate": "2019"},
            {"Id": "222", "Title": "B", "PubTypeList": ["Journal Article"], "PubDate": "2021"},
        ],
    )
    rows = pubmed_service.search_articles("anything")
    assert [r["pmid"] for r in rows] == ["111", "222"]
    assert rows[0]["publication_types"] == ["Meta-Analysis"]
    assert rows[1]["publication_types"] == []
