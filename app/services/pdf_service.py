"""PDF drop-in — extract analyzable text from a user-supplied article PDF.

The user often has a paper only as a PDF (e.g. emailed for coursework). This
module pulls the text of the first few pages locally with ``pypdf`` (nothing is
uploaded anywhere) and heuristically slices out the title and abstract so the
normal rule pipeline can run. Extraction from PDFs is inherently messy; the
result is best-effort and the usual caution notes still apply. Scanned/image
PDFs have no text layer and are rejected with a clear message (no OCR).
"""

from __future__ import annotations

import io
import re
from typing import Dict, Optional

_MAX_PAGES = 4
_MAX_ABSTRACT_CHARS = 3500

# Headings that end an abstract when they start a line below it. Line-anchored so
# prose like "after the introduction of the vaccine" cannot cut the slice short.
# ('Background:' is deliberately absent — it opens many structured abstracts.)
_END_HEADINGS = re.compile(
    r"(?im)^\s*(?:1\.?\s*)?(?:introduction|keywords|key\s*words|index\s+terms|abbreviations)\b[:.]?"
)
_ABSTRACT_LINE = re.compile(r"(?im)^\s*abstract\b\s*[:.\-–]?[ \t]*")
_ABSTRACT_ANYWHERE = re.compile(r"\babstract\b\s*[:.\-–]?\s*", re.IGNORECASE)


def slice_title_and_abstract(text: str) -> Dict[str, Optional[str]]:
    """Heuristically split raw first-pages text into a title guess and abstract.

    Pure function (testable without PDFs). The abstract is the text after an
    'Abstract' heading up to the next major heading; without such a heading we
    fall back to the first chunk of text — the design rules still work over it.
    """
    cleaned = re.sub(r"[ \t]+", " ", text or "").strip()
    if not cleaned:
        return {"title": None, "abstract": ""}

    # Title guess: first non-trivial line (PDF text keeps line breaks).
    title = None
    for line in (l.strip() for l in cleaned.splitlines()):
        if len(line) >= 15 and not _ABSTRACT_ANYWHERE.match(line):
            title = line[:250]
            break

    heading = _ABSTRACT_LINE.search(cleaned) or _ABSTRACT_ANYWHERE.search(cleaned)
    if heading:
        after = cleaned[heading.end() :]
        end = _END_HEADINGS.search(after)
        abstract = after[: end.start()] if end else after
    else:
        abstract = cleaned
    abstract = re.sub(r"\s+", " ", abstract).strip()
    return {"title": title, "abstract": abstract[:_MAX_ABSTRACT_CHARS]}


def extract_title_and_abstract(pdf_bytes: bytes) -> Dict[str, Optional[str]]:
    """Read a PDF and return ``{"title", "abstract"}`` for analysis.

    Raises ``ValueError`` with a user-facing message when the file is not a
    readable text PDF (encrypted, corrupt, or scanned images without text).
    """
    from pypdf import PdfReader  # imported lazily like the anthropic SDK

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted:
            try:
                reader.decrypt("")  # some PDFs are "encrypted" with an empty password
            except Exception as exc:  # noqa: BLE001
                raise ValueError("This PDF is password-protected and cannot be read.") from exc
        pages = reader.pages[:_MAX_PAGES]
        text = "\n".join((page.extract_text() or "") for page in pages)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt or unsupported PDFs
        raise ValueError("Could not read this file as a PDF.") from exc

    if len(re.sub(r"\s", "", text)) < 200:
        raise ValueError(
            "No selectable text found in this PDF — it may be a scanned image. "
            "Try pasting the abstract instead."
        )

    result = slice_title_and_abstract(text)
    # Prefer embedded metadata title when it looks like a real title.
    try:
        meta_title = (reader.metadata.title or "").strip() if reader.metadata else ""
    except Exception:  # noqa: BLE001 - metadata parsing can fail on odd PDFs
        meta_title = ""
    if len(meta_title) >= 15 and not meta_title.lower().endswith((".doc", ".docx", ".tex", ".dvi")):
        result["title"] = meta_title[:250]
    return result
