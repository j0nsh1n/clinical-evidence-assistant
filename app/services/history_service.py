"""SQLite history — every successful analysis is saved as a personal library.

Stdlib ``sqlite3`` with a per-call connection: appropriate for a single-user
local tool (no ORM, no pooling). Source-fetched articles are upserted by
(source, article_id) so re-analyzing (e.g. an AI refine) updates the stored
card without duplicating it; manual/PDF analyses are deduped by a content hash
of title+abstract. User notes always survive an upsert. Save failures are
swallowed — history must never break an analysis.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.config import get_settings
from app.schemas.evidence import EvidenceAnalysis

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  article_id TEXT,
  content_key TEXT,
  title TEXT,
  journal TEXT,
  year TEXT,
  study_design TEXT,
  evidence_level TEXT,
  is_retracted INTEGER NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  analyzed_at TEXT NOT NULL,
  analysis_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_source_article ON history(source, article_id);
CREATE INDEX IF NOT EXISTS idx_history_content_key ON history(content_key);
"""


def _db_path() -> str:
    return get_settings().history_db_path


def _connect() -> sqlite3.Connection:
    path = Path(_db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _content_key(analysis: EvidenceAnalysis) -> Optional[str]:
    """Stable hash for manual/PDF analyses (no article id to upsert on)."""
    if analysis.article_id:
        return None
    raw = f"{analysis.title or ''}|{analysis.abstract or ''}"
    if raw == "|":
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def save(analysis: EvidenceAnalysis) -> Optional[int]:
    """Insert or update the stored card; returns the row id (None on failure)."""
    try:
        with _connect() as conn:
            existing = None
            key = _content_key(analysis)
            if analysis.article_id:
                existing = conn.execute(
                    "SELECT id FROM history WHERE source = ? AND article_id = ?",
                    (analysis.source_database, analysis.article_id),
                ).fetchone()
            elif key:
                existing = conn.execute(
                    "SELECT id FROM history WHERE content_key = ?", (key,)
                ).fetchone()

            values = {
                "source": analysis.source_database,
                "article_id": analysis.article_id,
                "content_key": key,
                "title": analysis.title,
                "journal": analysis.journal,
                "year": analysis.year,
                "study_design": analysis.study_design.value,
                "evidence_level": analysis.evidence_level.value,
                "is_retracted": int(analysis.is_retracted),
                "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "analysis_json": analysis.model_dump_json(),
            }
            if existing:
                conn.execute(
                    "UPDATE history SET " + ", ".join(f"{k} = :{k}" for k in values) + " WHERE id = :id",
                    {**values, "id": existing["id"]},
                )
                return int(existing["id"])
            cursor = conn.execute(
                f"INSERT INTO history ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})",
                values,
            )
            return int(cursor.lastrowid)
    except Exception:  # noqa: BLE001 - history is best-effort; never break analysis
        return None


def list_recent(limit: int = 50) -> List[Dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, source, article_id, title, journal, year, study_design, "
            "evidence_level, is_retracted, notes, analyzed_at "
            "FROM history ORDER BY analyzed_at DESC, id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
    return [dict(row) for row in rows]


def get(history_id: int) -> Optional[Dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM history WHERE id = ?", (history_id,)).fetchone()
    if row is None:
        return None
    entry = dict(row)
    entry["analysis"] = json.loads(entry.pop("analysis_json"))
    return entry


def set_notes(history_id: int, notes: str) -> bool:
    with _connect() as conn:
        cursor = conn.execute("UPDATE history SET notes = ? WHERE id = ?", (notes, history_id))
        return cursor.rowcount > 0


def delete(history_id: int) -> bool:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM history WHERE id = ?", (history_id,))
        return cursor.rowcount > 0
