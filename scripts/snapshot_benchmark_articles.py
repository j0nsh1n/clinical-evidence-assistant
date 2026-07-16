"""One-shot: live-fetch OA Europe PMC articles + full-text sections for the
real-article benchmark fixtures.

Run once from the project root (network required), then commit the JSON under
``tests/fixtures/real_articles/``. The benchmark itself never hits the network.

Usage:
    python -m scripts.snapshot_benchmark_articles
    python -m scripts.snapshot_benchmark_articles --pmcid PMC1234567 --name rct_example
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from app.services import europepmc_service

OUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real_articles"

# Deliberate mix: RCTs (n often only in Methods), cohorts, meta-analyses,
# observational, and some where the abstract already states n.
_SEARCH_QUERIES: List[tuple[str, str]] = [
    # (fixture name prefix, Europe PMC query)
    ("rct", 'OPEN_ACCESS:y AND HAS_FT:y AND ("randomized controlled trial" OR RCT) AND (HAS_ABSTRACT:y)'),
    ("rct2", 'OPEN_ACCESS:y AND HAS_FT:y AND "randomly assigned" AND patients AND HAS_ABSTRACT:y'),
    ("cohort", 'OPEN_ACCESS:y AND HAS_FT:y AND "prospective cohort" AND HAS_ABSTRACT:y'),
    ("cohort2", 'OPEN_ACCESS:y AND HAS_FT:y AND "retrospective cohort" AND HAS_ABSTRACT:y'),
    ("meta", 'OPEN_ACCESS:y AND HAS_FT:y AND "meta-analysis" AND HAS_ABSTRACT:y'),
    ("sr", 'OPEN_ACCESS:y AND HAS_FT:y AND "systematic review" AND HAS_ABSTRACT:y AND NOT meta-analysis'),
    ("case_control", 'OPEN_ACCESS:y AND HAS_FT:y AND "case-control" AND HAS_ABSTRACT:y'),
    ("cross_sec", 'OPEN_ACCESS:y AND HAS_FT:y AND "cross-sectional" AND HAS_ABSTRACT:y'),
    ("obs", 'OPEN_ACCESS:y AND HAS_FT:y AND observational AND (cohort OR "case control") AND HAS_ABSTRACT:y'),
]

# Keys kept in the committed snapshot (stable, no transient OA URLs required).
_KEEP_KEYS = (
    "article_id",
    "source_database",
    "title",
    "abstract",
    "abstract_sections",
    "year",
    "authors",
    "journal",
    "citation",
    "doi",
    "pmid",
    "pmcid",
    "publication_types",
    "keywords",
    "is_open_access",
    "is_preprint",
    "full_text_sections",
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:60]


def _has_methods_results(sections: Dict[str, str]) -> bool:
    headings = " ".join(sections.keys()).upper()
    return "METHOD" in headings and "RESULT" in headings


def _normalize_article(article: dict) -> dict:
    out = {k: article.get(k) for k in _KEEP_KEYS}
    out["full_text_sections"] = article.get("full_text_sections") or {}
    return out


def _write_fixture(name: str, article: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{_slug(name)}.json"
    path.write_text(json.dumps(article, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def snapshot_one(article_id: str, name: str) -> Optional[Path]:
    article = europepmc_service.fetch_article(article_id)
    sections = article.get("full_text_sections") or {}
    if not (article.get("abstract") or "").strip():
        print(f"  skip {article_id}: no abstract")
        return None
    if not sections or not _has_methods_results(sections):
        print(f"  skip {article_id}: missing Methods/Results sections "
              f"(got {list(sections.keys())[:8]})")
        return None
    normalized = _normalize_article(article)
    path = _write_fixture(name, normalized)
    print(f"  wrote {path.name}  ({article.get('pmcid')})  "
          f"sections={list(sections.keys())[:6]}")
    return path


def discover_and_snapshot(target: int = 25) -> List[Path]:
    written: List[Path] = []
    seen_pmcids: Set[str] = set()
    # Resume: already-snapshotted PMCIDs
    if OUT_DIR.exists():
        for path in OUT_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            pmcid = data.get("pmcid")
            if pmcid:
                seen_pmcids.add(pmcid)
            written.append(path)

    per_query = max(4, (target // len(_SEARCH_QUERIES)) + 2)
    for prefix, query in _SEARCH_QUERIES:
        if len(written) >= target and len([p for p in written if p.exists()]) >= target:
            # Count unique fixtures in OUT_DIR
            n_files = len(list(OUT_DIR.glob("*.json"))) if OUT_DIR.exists() else 0
            if n_files >= target:
                break
        print(f"\nsearch: {prefix}")
        try:
            hits = europepmc_service.search_articles(query, max_results=min(40, per_query * 3))
        except Exception as exc:  # noqa: BLE001
            print(f"  search failed: {exc}")
            continue
        count_for_prefix = 0
        for hit in hits:
            n_files = len(list(OUT_DIR.glob("*.json"))) if OUT_DIR.exists() else 0
            if n_files >= target:
                break
            if count_for_prefix >= per_query:
                break
            pmcid = hit.get("pmcid")
            article_id = hit.get("article_id")
            if not pmcid or not article_id or not hit.get("is_open_access"):
                continue
            if pmcid in seen_pmcids:
                continue
            # Prefer MEDLINE records
            if not str(article_id).startswith("MED/"):
                continue
            name = f"{prefix}_{pmcid.replace('PMC', '')}"
            try:
                path = snapshot_one(article_id, name)
            except Exception as exc:  # noqa: BLE001
                print(f"  fetch failed {article_id}: {exc}")
                time.sleep(0.4)
                continue
            if path is not None:
                seen_pmcids.add(pmcid)
                written.append(path)
                count_for_prefix += 1
            time.sleep(0.35)  # be polite to Europe PMC
    return written


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pmcid", help="Snapshot a single PMCID (e.g. PMC1234567)")
    parser.add_argument("--article-id", help="Snapshot a single Europe PMC id (e.g. MED/123)")
    parser.add_argument("--name", help="Fixture base name when snapshotting one article")
    parser.add_argument("--target", type=int, default=25, help="How many fixtures to aim for")
    args = parser.parse_args(argv)

    if args.pmcid or args.article_id:
        article_id = args.article_id
        if not article_id and args.pmcid:
            # Resolve PMCID -> MEDLINE id via search
            pmc = args.pmcid if args.pmcid.upper().startswith("PMC") else f"PMC{args.pmcid}"
            hits = europepmc_service.search_articles(f"PMCID:{pmc}", max_results=5)
            if not hits:
                print(f"No hits for {pmc}", file=sys.stderr)
                return 1
            article_id = hits[0]["article_id"]
        name = args.name or f"manual_{_slug(args.pmcid or article_id or 'article')}"
        path = snapshot_one(article_id, name)
        return 0 if path else 1

    paths = discover_and_snapshot(target=args.target)
    n = len(list(OUT_DIR.glob("*.json"))) if OUT_DIR.exists() else 0
    print(f"\nDone. {n} fixtures in {OUT_DIR}")
    if n < args.target:
        print(f"Warning: only {n}/{args.target} fixtures — re-run or add --pmcid manually.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
