"""Unit tests for the Europe PMC source (no network; _get is monkeypatched)."""

import pytest

from app.services import europepmc_service

_LITE = {
    "source": "MED",
    "id": "23440795",
    "pmid": "23440795",
    "doi": "10.1002/x",
    "title": "Statins for primary prevention",
    "authorString": "Taylor F, Huffman MD, Macedo AF.",
    "journalTitle": "Lancet",
    "pubYear": "2013",
    "pubType": "Meta-Analysis; Journal Article",
    "isOpenAccess": "N",
}


def test_parse_lite_maps_fields():
    row = europepmc_service._parse_lite(_LITE)
    assert row["source"] == "europepmc"
    assert row["article_id"] == "MED/23440795"
    assert row["pmid"] == "23440795"
    assert row["authors"][0] == "Taylor F"
    assert "Meta-Analysis" in row["publication_types"]
    assert "Journal Article" not in row["publication_types"]
    assert row["is_preprint"] is False


def test_parse_lite_flags_preprint():
    row = europepmc_service._parse_lite({"source": "PPR", "id": "9", "title": "t", "pubType": "Preprint"})
    assert row["is_preprint"] is True
    assert "Preprint" in row["publication_types"]


def test_parse_abstract_extracts_sections():
    text, sections = europepmc_service._parse_abstract(
        "<h4>METHODS</h4>We did X.<h4>CONCLUSIONS</h4>It worked."
    )
    assert sections["METHODS"] == "We did X."
    assert sections["CONCLUSIONS"] == "It worked."
    assert "We did X." in text and "It worked." in text


def test_search_articles(monkeypatch):
    monkeypatch.setattr(europepmc_service, "_get", lambda params: {"resultList": {"result": [_LITE]}})
    rows = europepmc_service.search_articles("statins")
    assert rows[0]["article_id"] == "MED/23440795"


def test_fetch_article_core(monkeypatch):
    core = {
        "source": "MED",
        "id": "23440795",
        "pmid": "23440795",
        "doi": "10.1/x",
        "title": "T",
        "abstractText": "<h4>CONCLUSIONS</h4>It helps.",
        "authorList": {"author": [{"fullName": "Taylor F"}]},
        "journalInfo": {"journal": {"title": "Lancet"}, "yearOfPublication": "2013", "volume": "381"},
        "pubTypeList": {"pubType": ["Meta-Analysis"]},
        "isOpenAccess": "Y",
        "fullTextUrlList": {"fullTextUrl": [{"availability": "Open access", "url": "https://oa/x"}]},
    }
    monkeypatch.setattr(europepmc_service, "_get", lambda params: {"resultList": {"result": [core]}})
    article = europepmc_service.fetch_article("MED/23440795")
    assert article["source_database"] == "europepmc"
    assert article["abstract_sections"]["CONCLUSIONS"] == "It helps."
    assert article["is_open_access"] is True
    assert article["oa_url"] == "https://oa/x"
    assert article["publication_types"] == ["Meta-Analysis"]
    assert article["citation"].startswith("Lancet. 2013")


def test_fetch_article_not_found(monkeypatch):
    monkeypatch.setattr(europepmc_service, "_get", lambda params: {"resultList": {"result": []}})
    with pytest.raises(europepmc_service.ArticleNotFound):
        europepmc_service.fetch_article("MED/999")


class _FakeResp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


_FULLTEXT_XML = (
    "<article><body>"
    "<sec><title>Methods</title><p>A total of 512 adults were enrolled.</p></sec>"
    "<sec><title>Results</title><p>The hazard ratio was 0.75 (95% CI 0.60-0.90).</p></sec>"
    "</body></article>"
)


def test_fetch_full_text_sections_parses_jats(monkeypatch):
    monkeypatch.setattr(europepmc_service.httpx, "get", lambda *a, **k: _FakeResp(200, _FULLTEXT_XML))
    sections = europepmc_service.fetch_full_text_sections("PMC123")
    assert "512 adults" in sections["METHODS"]
    assert "hazard ratio" in sections["RESULTS"]


def test_fetch_full_text_sections_non_pmc_returns_empty():
    assert europepmc_service.fetch_full_text_sections("MED/1") == {}
