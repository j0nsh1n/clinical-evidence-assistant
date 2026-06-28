"""PubMed retrieval via NCBI E-utilities (ESearch + EFetch).

Follows the proven Bio.Entrez flow (search -> identifiers, fetch -> records) but
normalizes the output for the evidence pipeline and, unlike a naive parser,
*preserves* structured abstract section labels (BACKGROUND / METHODS / RESULTS /
CONCLUSIONS) which downstream rules use to find the key finding.
"""

from __future__ import annotations

import socket
from typing import Dict, List, Optional, Tuple

from Bio import Entrez

from app.config import get_settings

_settings = get_settings()

# urllib (used by Entrez under the hood) has no default timeout; without this a
# stalled NCBI socket would hang the worker thread indefinitely.
socket.setdefaulttimeout(_settings.ncbi_timeout_seconds)

# NCBI asks every caller to identify themselves; an API key raises rate limits.
Entrez.email = _settings.ncbi_email
if _settings.ncbi_api_key:
    Entrez.api_key = _settings.ncbi_api_key


class PubMedError(RuntimeError):
    """PubMed could not be reached or returned an unusable response."""


class ArticleNotFound(PubMedError):
    """A PMID resolved to no record."""


def search(query: str, max_results: int = 20) -> List[str]:
    """Run ESearch and return a list of PMIDs (most relevant first)."""
    try:
        handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results, sort="relevance")
        record = Entrez.read(handle)
        handle.close()
    except Exception as exc:  # noqa: BLE001 - normalize all transport/parse errors
        raise PubMedError(f"PubMed search failed: {exc}") from exc
    return list(record.get("IdList", []))


def _join_abstract(abstract_text) -> Tuple[str, Dict[str, str]]:
    """Return ``(full_text, {SECTION_LABEL: text})``.

    ``AbstractText`` may be a plain string, a list of strings, or a list of
    Biopython ``StringElement`` objects each carrying a ``Label`` attribute
    (e.g. ``"METHODS"``). We keep both the flat text and the labelled sections.
    """
    sections: Dict[str, str] = {}
    if abstract_text is None:
        return "", sections
    if not isinstance(abstract_text, list):
        return str(abstract_text).strip(), sections

    parts: List[str] = []
    for part in abstract_text:
        text = str(part).strip()
        if not text:
            continue
        attributes = getattr(part, "attributes", {}) or {}
        label = attributes.get("Label")
        if label:
            sections[str(label).strip().upper()] = text
        parts.append(text)
    return " ".join(parts).strip(), sections


def _extract_authors(article: dict) -> List[str]:
    """Full author list as 'Lastname II' strings (CollectiveName as a fallback)."""
    authors: List[str] = []
    for author in article.get("AuthorList", []) or []:
        last = str(author.get("LastName", "")).strip()
        initials = str(author.get("Initials", "")).strip()
        if last:
            authors.append(f"{last} {initials}".strip())
        elif author.get("CollectiveName"):
            authors.append(str(author["CollectiveName"]).strip())
    return authors


def _extract_doi(record: dict, article: dict) -> Optional[str]:
    """DOI from the article's ELocationID, falling back to PubmedData ArticleIdList."""
    for eloc in article.get("ELocationID", []) or []:
        if (getattr(eloc, "attributes", {}) or {}).get("EIdType") == "doi":
            return str(eloc).strip() or None
    for aid in record.get("PubmedData", {}).get("ArticleIdList", []) or []:
        if (getattr(aid, "attributes", {}) or {}).get("IdType") == "doi":
            return str(aid).strip() or None
    return None


def _extract_pub_types(article: dict) -> List[str]:
    """Informative PubMed publication types (drops generic/funding noise)."""
    out: List[str] = []
    for pub_type in article.get("PublicationTypeList", []) or []:
        name = str(pub_type).strip()
        low = name.lower()
        if not name or low == "journal article" or low == "english abstract" or low.startswith("research support"):
            continue
        out.append(name)
    return out


def _extract_keywords(citation: dict) -> List[str]:
    """Author keywords plus MeSH descriptor names, de-duplicated and capped."""
    raw: List[str] = []
    for keyword_list in citation.get("KeywordList", []) or []:
        for keyword in keyword_list:
            raw.append(str(keyword).strip())
    for heading in citation.get("MeshHeadingList", []) or []:
        descriptor = heading.get("DescriptorName")
        if descriptor is not None:
            raw.append(str(descriptor).strip())

    seen: set = set()
    deduped: List[str] = []
    for term in raw:
        key = term.lower()
        if term and key not in seen:
            seen.add(key)
            deduped.append(term)
    return deduped[:10]


def _build_citation(article: dict, journal: Optional[str], year: Optional[str]) -> Optional[str]:
    """A compact citation string, e.g. 'Lancet. 2004;364(9435):685-696'."""
    issue = article.get("Journal", {}).get("JournalIssue", {})
    volume = str(issue.get("Volume", "")).strip()
    number = str(issue.get("Issue", "")).strip()
    pages = str(article.get("Pagination", {}).get("MedlinePgn", "")).strip()

    locator = year or ""
    if volume:
        locator += f";{volume}"
        if number:
            locator += f"({number})"
    if pages:
        locator += f":{pages}"

    pieces = [piece for piece in (journal, locator) if piece]
    return ". ".join(pieces) if pieces else None


def _parse_record(record: dict) -> dict:
    citation = record["MedlineCitation"]
    article = citation["Article"]

    pmid = str(citation["PMID"])
    title = str(article.get("ArticleTitle", "")).strip()

    abstract, sections = _join_abstract(article.get("Abstract", {}).get("AbstractText"))

    pub_date = article.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
    year = str(pub_date.get("Year", "")).strip() or None
    journal = str(article.get("Journal", {}).get("Title", "")).strip() or None

    return {
        "article_id": pmid,
        "source_database": "pubmed",
        "title": title or None,
        "abstract": abstract or None,
        "abstract_sections": sections,
        "year": year,
        "authors": _extract_authors(article),
        "journal": journal,
        "citation": _build_citation(article, journal, year),
        "doi": _extract_doi(record, article),
        "publication_types": _extract_pub_types(article),
        "keywords": _extract_keywords(citation),
    }


def fetch_article(pmid: str) -> dict:
    """Fetch and normalize a single article by PMID.

    Raises :class:`ArticleNotFound` if the PMID has no record, or
    :class:`PubMedError` on any transport/parse failure. An article that exists
    but has no abstract is returned with ``abstract=None`` (handled gracefully
    downstream) rather than raising.
    """
    pmid = str(pmid).strip()
    if not pmid:
        raise ArticleNotFound("Empty PMID.")
    try:
        handle = Entrez.efetch(db="pubmed", id=pmid, rettype="xml", retmode="xml")
        records = Entrez.read(handle)
        handle.close()
    except Exception as exc:  # noqa: BLE001 - normalize all transport/parse errors
        raise PubMedError(f"Failed to fetch PMID {pmid}: {exc}") from exc

    items = records.get("PubmedArticle", []) if isinstance(records, dict) else []
    if not items:
        raise ArticleNotFound(f"No PubMed record for PMID {pmid}.")
    try:
        return _parse_record(items[0])
    except (KeyError, IndexError, TypeError) as exc:
        raise PubMedError(f"Could not parse PubMed record for PMID {pmid}: {exc}") from exc


def _parse_summary(docsum: dict) -> dict:
    """Normalize one ESummary DocSum into a lightweight result row."""
    pubdate = str(docsum.get("PubDate", "")).strip()
    year = pubdate.split(" ")[0][:4] if pubdate else None
    if year and not year.isdigit():
        year = None

    pub_types = [
        str(p).strip()
        for p in docsum.get("PubTypeList", []) or []
        if str(p).strip() and str(p).strip().lower() != "journal article"
    ]
    authors = [str(a).strip() for a in docsum.get("AuthorList", []) or [] if str(a).strip()]
    journal = str(docsum.get("FullJournalName", "") or docsum.get("Source", "")).strip() or None

    return {
        "pmid": str(docsum.get("Id", "")).strip(),
        "title": str(docsum.get("Title", "")).strip() or None,
        "authors": authors,
        "journal": journal,
        "year": year,
        "publication_types": pub_types,
        "doi": str(docsum.get("DOI", "")).strip() or None,
    }


def search_articles(query: str, max_results: int = 20) -> List[dict]:
    """Search PubMed and return lightweight summaries (ESearch -> ESummary).

    Uses ESummary rather than a full EFetch so a results list stays fast; the
    full abstract + metadata are fetched only when a single article is analyzed.
    """
    query = (query or "").strip()
    if not query:
        return []
    pmids = search(query, max_results=max_results)
    if not pmids:
        return []
    try:
        handle = Entrez.esummary(db="pubmed", id=",".join(pmids), retmode="xml")
        summaries = Entrez.read(handle)
        handle.close()
    except Exception as exc:  # noqa: BLE001 - normalize all transport/parse errors
        raise PubMedError(f"PubMed summary fetch failed: {exc}") from exc

    results: List[dict] = []
    for docsum in summaries:
        try:
            parsed = _parse_summary(docsum)
        except (KeyError, IndexError, TypeError):
            continue
        if parsed["pmid"]:
            results.append(parsed)
    return results
