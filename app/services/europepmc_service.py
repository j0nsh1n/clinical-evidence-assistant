"""Europe PMC retrieval (REST + JSON).

Europe PMC is a superset of PubMed/MEDLINE that also indexes PMC full text and
medRxiv/bioRxiv preprints, with no API key. We map its records onto the same
dict contract that ``pubmed_service`` produces, so the rest of the pipeline is
source-agnostic.
"""

from __future__ import annotations

import html
import re
from typing import Dict, List, Optional, Tuple

import httpx

from app.config import get_settings
from app.services.errors import ArticleNotFound, SourceError

SOURCE = "europepmc"
_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_settings = get_settings()
_HEADERS = {"User-Agent": f"ClinicalEvidenceAssistant/0.4 ({_settings.ncbi_email})"}

# Generic / funding pub-type strings worth dropping from the displayed list.
_NOISE_TYPES = {"journal article", "research-article", "research support", "english abstract"}


def _get(params: Dict) -> dict:
    try:
        response = httpx.get(
            _BASE, params=params, headers=_HEADERS, timeout=_settings.ncbi_timeout_seconds
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001 - normalize all transport/parse errors
        raise SourceError(f"Europe PMC request failed: {exc}") from exc


def _split_pub_types(raw) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        parts = [str(p) for p in raw]
    else:
        parts = re.split(r"[;,]", str(raw))
    out: List[str] = []
    for part in parts:
        name = part.strip()
        if name and name.lower() not in _NOISE_TYPES and not name.lower().startswith("research support"):
            out.append(name)
    return out


def _authors_from_string(author_string: str) -> List[str]:
    return [a.strip(" .") for a in (author_string or "").split(",") if a.strip(" .")]


def _parse_abstract(raw: Optional[str]) -> Tuple[str, Dict[str, str]]:
    """Return ``(flat_text, {SECTION: text})``; Europe PMC marks sections with <h4>."""
    if not raw:
        return "", {}
    sections: Dict[str, str] = {}
    for label, body in re.findall(r"<h4[^>]*>(.*?)</h4>(.*?)(?=<h4|$)", raw, flags=re.DOTALL | re.IGNORECASE):
        key = _strip_html(label).strip().upper().rstrip(":")
        text = _strip_html(body).strip()
        if key and text:
            sections[key] = text
    return _strip_html(raw), sections


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _build_citation(journal, year, volume, issue, pages) -> Optional[str]:
    locator = year or ""
    if volume:
        locator += f";{volume}"
        if issue:
            locator += f"({issue})"
    if pages:
        locator += f":{pages}"
    pieces = [p for p in (journal, locator) if p]
    return ". ".join(pieces) if pieces else None


def _oa_url(item: dict) -> Optional[str]:
    for url in item.get("fullTextUrlList", {}).get("fullTextUrl", []) or []:
        if str(url.get("availability", "")).lower().startswith("open"):
            link = str(url.get("url", "")).strip()
            if link:
                return link
    return None


def _parse_lite(item: dict) -> dict:
    src = str(item.get("source", "")).strip() or "MED"
    ext_id = str(item.get("id", "")).strip()
    pub_types = _split_pub_types(item.get("pubType"))
    is_preprint = src == "PPR" or any("preprint" in p.lower() for p in pub_types)
    journal = str(item.get("journalTitle", "")).strip() or (None if not is_preprint else "Preprint server")
    return {
        "source": SOURCE,
        "article_id": f"{src}/{ext_id}",
        "pmid": str(item.get("pmid", "")).strip() or None,
        "pmcid": str(item.get("pmcid", "")).strip() or None,
        "doi": str(item.get("doi", "")).strip() or None,
        "title": str(item.get("title", "")).strip() or None,
        "authors": _authors_from_string(item.get("authorString", "")),
        "journal": journal,
        "year": str(item.get("pubYear", "")).strip() or None,
        "publication_types": (["Preprint"] + pub_types) if is_preprint and "Preprint" not in pub_types else pub_types,
        "is_open_access": str(item.get("isOpenAccess", "")).upper() == "Y",
        "is_preprint": is_preprint,
    }


def _parse_core(item: dict) -> dict:
    src = str(item.get("source", "")).strip() or "MED"
    ext_id = str(item.get("id", "")).strip()

    abstract, sections = _parse_abstract(item.get("abstractText"))

    authors: List[str] = []
    for author in item.get("authorList", {}).get("author", []) or []:
        name = str(author.get("fullName", "")).strip()
        if not name:
            name = f"{author.get('lastName', '')} {author.get('initials', '')}".strip()
        if name:
            authors.append(name)
    if not authors:
        authors = _authors_from_string(item.get("authorString", ""))

    journal_info = item.get("journalInfo", {})
    journal = str(journal_info.get("journal", {}).get("title", "")).strip() or None
    year = str(journal_info.get("yearOfPublication", "")).strip() or str(item.get("pubYear", "")).strip() or None
    volume = str(journal_info.get("volume", "")).strip()
    issue = str(journal_info.get("issue", "")).strip()
    pages = str(item.get("pageInfo", "")).strip()

    pub_types = _split_pub_types(item.get("pubTypeList", {}).get("pubType", []))
    is_preprint = src == "PPR" or any("preprint" in p.lower() for p in pub_types)
    if is_preprint and "Preprint" not in pub_types:
        pub_types = ["Preprint"] + pub_types
    if is_preprint and not journal:
        journal = "Preprint (medRxiv/bioRxiv)"

    keywords: List[str] = []
    for keyword in item.get("keywordList", {}).get("keyword", []) or []:
        text = str(keyword).strip()
        if text:
            keywords.append(text)
    for heading in item.get("meshHeadingList", {}).get("meshHeading", []) or []:
        text = str(heading.get("descriptorName", "")).strip()
        if text:
            keywords.append(text)
    seen, deduped = set(), []
    for term in keywords:
        if term.lower() not in seen:
            seen.add(term.lower())
            deduped.append(term)

    return {
        "article_id": f"{src}/{ext_id}",
        "source_database": SOURCE,
        "title": str(item.get("title", "")).strip() or None,
        "abstract": abstract or None,
        "abstract_sections": sections,
        "year": year,
        "authors": authors,
        "journal": journal,
        "citation": _build_citation(journal, year, volume, issue, pages),
        "doi": str(item.get("doi", "")).strip() or None,
        "pmid": str(item.get("pmid", "")).strip() or None,
        "pmcid": str(item.get("pmcid", "")).strip() or None,
        "publication_types": pub_types,
        "keywords": deduped[:10],
        "is_open_access": str(item.get("isOpenAccess", "")).upper() == "Y",
        "oa_url": _oa_url(item),
        "is_preprint": is_preprint,
    }


def search_articles(query: str, max_results: int = 20) -> List[dict]:
    query = (query or "").strip()
    if not query:
        return []
    data = _get(
        {"query": query, "format": "json", "pageSize": min(max_results, 50), "resultType": "lite"}
    )
    results: List[dict] = []
    for item in data.get("resultList", {}).get("result", []) or []:
        try:
            parsed = _parse_lite(item)
        except (KeyError, TypeError):
            continue
        if parsed["article_id"] != "MED/":
            results.append(parsed)
    return results


def fetch_full_text(pmcid: Optional[str], max_chars: int = 24000) -> Optional[str]:
    """Return sectioned plain text of the LEGAL open-access full text for a PMCID, or None.

    Europe PMC serves machine-readable JATS only for the open-access subset, keyed by
    PMCID — the endpoint is ``.../rest/PMC3258128/fullTextXML`` (a single PMCID segment).
    Best-effort: any failure (not in the OA subset, no XML, parse error) returns None.
    """
    pmcid = str(pmcid or "").strip().upper()
    if not pmcid.startswith("PMC"):
        return None
    try:
        response = httpx.get(
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
            headers=_HEADERS,
            timeout=_settings.ncbi_timeout_seconds,
        )
        if response.status_code != 200 or not response.text.strip():
            return None
        import xml.etree.ElementTree as ET

        root = ET.fromstring(response.text)
    except Exception:  # noqa: BLE001 - full text is a bonus; never raise
        return None

    body = root.find(".//body")
    chunks: List[str] = []
    if body is not None:
        top_secs = body.findall("sec")
        if top_secs:
            for sec in top_secs:
                heading = (sec.findtext("title") or "").strip()
                text = re.sub(r"\s+", " ", " ".join(sec.itertext())).strip()
                if text:
                    chunks.append(f"## {heading}\n{text}" if heading else text)
        else:
            text = re.sub(r"\s+", " ", " ".join(body.itertext())).strip()
            if text:
                chunks.append(text)
    full = "\n\n".join(chunks)
    if len(full) < 500:
        return None
    return full[:max_chars]


def fetch_article(article_id: str) -> dict:
    article_id = str(article_id).strip()
    if not article_id:
        raise ArticleNotFound("Empty article id.")
    src, _, ext_id = article_id.partition("/")
    if not ext_id:
        src, ext_id = "MED", src
    data = _get(
        {"query": f"EXT_ID:{ext_id} AND SRC:{src}", "format": "json", "resultType": "core", "pageSize": 1}
    )
    results = data.get("resultList", {}).get("result", []) or []
    if not results:
        raise ArticleNotFound(f"No Europe PMC record for {article_id}.")
    try:
        return _parse_core(results[0])
    except (KeyError, IndexError, TypeError) as exc:
        raise SourceError(f"Could not parse Europe PMC record {article_id}: {exc}") from exc
