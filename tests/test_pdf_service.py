"""Tests for the PDF drop-in: slicing heuristics, pypdf integration, API route."""

import io

import pytest

from app.main import app
from app.services import pdf_service
from fastapi.testclient import TestClient

client = TestClient(app)


# --- pure slicing heuristics -------------------------------------------------


def test_slice_abstract_after_heading_until_introduction():
    text = (
        "Effect of X on Y: a randomized trial\n"
        "J Example, A Author\n"
        "Abstract\n"
        "In this randomized controlled trial, 200 patients were enrolled. X improved Y.\n"
        "Introduction: Y is a major problem worldwide."
    )
    result = pdf_service.slice_title_and_abstract(text)
    assert result["title"] == "Effect of X on Y: a randomized trial"
    assert "200 patients were enrolled" in result["abstract"]
    assert "major problem" not in result["abstract"]


def test_slice_structured_abstract_keeps_background():
    # 'Background:' inside a structured abstract must NOT end the slice.
    text = (
        "A big study title line for the paper\n"
        "Abstract\n"
        "Background: Y is common. Methods: We enrolled 500 adults. Results: X helped. "
        "Conclusions: X works.\n"
        "Keywords: X; Y; trials"
    )
    result = pdf_service.slice_title_and_abstract(text)
    assert "Methods: We enrolled 500 adults" in result["abstract"]
    assert "trials" not in result["abstract"]


def test_slice_without_abstract_heading_falls_back_to_first_text():
    text = "Case report: an unusual presentation\nWe describe a 34-year-old patient with rare findings."
    result = pdf_service.slice_title_and_abstract(text)
    assert result["abstract"].startswith("Case report")


def test_slice_empty_text():
    assert pdf_service.slice_title_and_abstract("") == {"title": None, "abstract": ""}


# --- pypdf integration over a real generated PDF ------------------------------


def _make_pdf(text_lines):
    """Build a minimal one-page PDF with real text content."""
    lines = "".join(f"({line}) Tj 0 -14 Td " for line in text_lines)
    stream = f"BT /F1 11 Tf 50 750 Td {lines}ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()
    )
    return out.getvalue()


_PDF_LINES = [
    "A randomized trial of thing X in adults",
    "Abstract",
    "In this randomized controlled trial, 320 patients were enrolled",
    "and followed for 12 weeks. Thing X reduced symptoms significantly",
    "compared with placebo, with a hazard ratio of 0.72, 95% CI 0.58-0.90.",
    "Introduction",
    "Thing X has a long history of investigation.",
]


def test_extract_from_real_pdf_bytes():
    result = pdf_service.extract_title_and_abstract(_make_pdf(_PDF_LINES))
    assert result["title"] == "A randomized trial of thing X in adults"
    assert "320 patients were enrolled" in result["abstract"]
    assert "long history" not in result["abstract"]


def test_extract_rejects_non_pdf():
    with pytest.raises(ValueError, match="Could not read"):
        pdf_service.extract_title_and_abstract(b"this is not a pdf at all")


def test_extract_rejects_textless_pdf():
    with pytest.raises(ValueError, match="scanned image"):
        pdf_service.extract_title_and_abstract(_make_pdf(["tiny"]))


# --- API route ----------------------------------------------------------------


def test_analyze_pdf_endpoint():
    pdf = _make_pdf(_PDF_LINES)
    response = client.post(
        "/api/evidence/analyze-pdf", files={"file": ("paper.pdf", pdf, "application/pdf")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source_database"] == "pdf"
    assert data["study_design"] == "randomized_controlled_trial"
    assert data["evidence_level"] == "B"
    assert data["sample_size"] == 320
    # the statistics reader runs over the extracted abstract too
    assert data["reported_statistics"][0]["measure"] == "HR"


def test_analyze_pdf_endpoint_rejects_bad_file():
    response = client.post(
        "/api/evidence/analyze-pdf", files={"file": ("junk.pdf", b"junk bytes", "application/pdf")}
    )
    assert response.status_code == 422
    assert "Could not read" in response.json()["detail"]
