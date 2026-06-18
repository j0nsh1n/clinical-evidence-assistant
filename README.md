# Clinical Evidence Assistant

A small FastAPI service that takes a clinical research article (by PubMed ID or by
pasted abstract), extracts key study details, and assigns a **provisional**
evidence level — to help students interpret study design, findings, and evidence
strength from PubMed abstracts.

> ⚠️ **Not medical advice.** Evidence levels are estimated from the *abstract
> only* using transparent rules, not a full critical appraisal. Output is a
> study aid, not a clinical or diagnostic tool.

---

## Feature spec (Phase 1)

**Input** — one article, supplied as either:
- a PubMed `pmid` (the abstract is fetched via NCBI E-utilities), or
- `title` + `abstract` text directly.

**Output** — a structured `EvidenceAnalysis` (JSON): study design, clinical
question type, population, sample size, PICO hints, key finding, a provisional
A/B/C/D evidence level with a human label, a confidence score, caution notes, and
the extraction method used.

**MVP** — single-article, abstract-based, rule-driven analysis behind one
endpoint, with graceful handling of missing abstracts and unknown designs.

**Out of scope (for now)** — full-text PDF reasoning, perfect medical
interpretation, diagnosis/treatment support, and bulk analysis. An optional LLM
refinement pass and a multi-article comparison view are planned later.

---

## Architecture

```
clinical-evidence-assistant/
├── app/
│   ├── main.py                  # FastAPI app + /health
│   ├── config.py                # settings (NCBI email/key) via pydantic-settings
│   ├── routers/
│   │   └── evidence.py          # POST /api/evidence/analyze, GET /api/evidence/article/{pmid}
│   ├── schemas/
│   │   └── evidence.py          # Pydantic data model (the stable contract)
│   └── services/
│       ├── pubmed_service.py    # ESearch/EFetch, normalize + preserve abstract sections
│       ├── evidence_rules.py    # pure functions: design, sample size, PICO, mapping, cautions
│       └── evidence_service.py  # orchestration: fetch -> extract -> assemble
└── tests/
    ├── fixtures/sample_abstracts.py   # labelled eval seed (synthetic)
    ├── test_evidence_rules.py
    └── test_evidence_api.py
```

Design principle: **thin routes, logic in services, rules pure and testable.**
Both the rule-based path and a future LLM path produce the same
`EvidenceAnalysis`; only `extraction_method` (`"rules"` vs `"rules+llm"`)
differs, so they stay interchangeable.

---

## Evidence-level mapping

The provisional level is derived from detected study design (Oxford-style):

| Study design                         | Level | Label    |
| ------------------------------------ | :---: | -------- |
| Systematic review / meta-analysis    |   A   | High     |
| Randomized controlled trial / cohort |   B   | Moderate |
| Case-control / cross-sectional       |   C   | Lower    |
| Case series/report, narrative review, expert opinion | D | Weak |
| Could not classify                   |   —   | Unclear  |

Every result also carries explicit `caution_notes` (e.g. *"Observational design
limits causal inference"*, *"Sample size was not clearly reported"*).

---

## Quickstart

```bash
# from the project root
python -m venv .venv
.venv\Scripts\activate          # Windows (PowerShell: .venv\Scripts\Activate.ps1)
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt

cp .env.example .env            # then set NCBI_EMAIL (required by NCBI)

uvicorn app.main:app --reload
# open http://127.0.0.1:8000/docs  for interactive API docs
```

### Try it

```bash
# Analyze pasted text (no network needed)
curl -X POST http://127.0.0.1:8000/api/evidence/analyze \
  -H "Content-Type: application/json" \
  -d '{"title":"An RCT of drug X","abstract":"In this randomized, double-blind, placebo-controlled trial, 320 patients were enrolled..."}'

# Analyze a real PubMed article by PMID
curl http://127.0.0.1:8000/api/evidence/article/33301246
```

## Tests

```bash
pytest                       # full suite (rules + API; API mocks PubMed, no network)
pytest tests/test_evidence_rules.py   # just the pure rule engine
```

---

## Roadmap

- [x] **Phase 1** — Scope + data model (`schemas/evidence.py`, this README)
- [x] **Phase 2** — Backend skeleton (router / services)
- [x] **Phase 3** — PubMed retrieval (`pubmed_service.py`)
- [x] **Phase 4** — Rule-based extraction (design, sample size, PICO hints, key finding)
- [x] **Phase 5** — Provisional evidence scoring + caution notes
- [x] **Phase 6** — Frontend evidence card (`app/static/`: PMID + paste modes, color-coded badges, cautions, loading/error states)
- [x] **Phase 7** — Unit + integration tests (ongoing: grow the eval set)
- [ ] **Phase 8** — Optional LLM refinement of summaries/limitations (`extraction_method="rules+llm"`)
- [ ] **Phase 9** — Multi-article comparison + portfolio polish

### Next up
1. Grow `tests/fixtures/sample_abstracts.py` into a 15–30 abstract benchmark with a
   measured accuracy figure.
2. Optional LLM refinement of the summary / limitations (Phase 8), tagged
   `extraction_method="rules+llm"`.
3. Multi-article comparison view (Phase 9).
