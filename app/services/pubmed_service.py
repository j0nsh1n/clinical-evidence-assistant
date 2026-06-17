"""PubMed retrieval via NCBI E-utilities (ESearch + EFetch).

Follows the proven Bio.Entrez flow (search -> identifiers, fetch -> records) but
normalizes the output for the evidence pipeline and, unlike a naive parser,
*preserves* structured abstract section labels (BACKGROUND / METHODS / RESULTS /
CONCLUSIONS) which downstream rules use to find the key finding.
"""

from __future__ import annotations

import socket
from typing import Dict, List, Tuple

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


def _parse_record(record: dict) -> dict:
    citation = record["MedlineCitation"]
    article = citation["Article"]

    pmid = str(citation["PMID"])
    title = str(article.get("ArticleTitle", "")).strip()

    abstract, sections = _join_abstract(article.get("Abstract", {}).get("AbstractText"))

    pub_date = article.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
    year = str(pub_date.get("Year", "")).strip() or None

    authors: List[str] = []
    for author in article.get("AuthorList", [])[:8]:
        last = author.get("LastName", "")
        initials = author.get("Initials", "")
        if last:
            authors.append(f"{last} {initials}".strip())

    journal = str(article.get("Journal", {}).get("Title", "")).strip() or None

    return {
        "article_id": pmid,
        "source_database": "pubmed",
        "title": title or None,
        "abstract": abstract or None,
        "abstract_sections": sections,
        "year": year,
        "authors": authors,
        "journal": journal,
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
    return _parse_record(items[0])
