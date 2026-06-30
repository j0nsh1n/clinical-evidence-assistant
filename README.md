# Clinical Evidence Assistant

A FastAPI web app that lets you **search the clinical literature** (Europe PMC or
PubMed), open any article, and get a **provisional** evidence level plus structured
study details and a plain-language summary — to help students interpret study
design, findings, and evidence strength. You can also analyze an article by PubMed
ID or by pasting an abstract. Includes **dark mode** and in-card **definitions** for
every metric.

> ⚠️ **Not medical advice.** Evidence levels are estimated from the *abstract
> only* using transparent rules, not a full critical appraisal. Output is a
> study aid, not a clinical or diagnostic tool.

---

## What it does

**Input** — a **search query** (Europe PMC or PubMed), or one article supplied as:
- a PubMed `pmid` / source `article_id` (abstract + metadata fetched live), or
- `title` + `abstract` text directly.

**Output** — a structured `EvidenceAnalysis` (JSON): study design, clinical
question type, population, sample size, PICO hints, key finding, a **plain-language
key-points summary**, a provisional A/B/C/D evidence level, a confidence score,
caution notes, and article metadata (authors, journal, citation, DOI, publication
types, MeSH topics, **open-access link**, **preprint flag**). Search returns
lightweight summaries, each with an evidence-level hint from its publication type.

**Sources** — **Europe PMC** (default; a superset of PubMed that also indexes
medRxiv/bioRxiv preprints and PMC full text) and **PubMed**. **Unpaywall** adds a
legal open-access full-text link by DOI when one exists (no piracy).

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
│   ├── main.py                  # FastAPI app + /health + serves the web UI
│   ├── config.py                # settings (NCBI email/key) via pydantic-settings
│   ├── routers/
│   │   ├── evidence.py          # POST /api/evidence/analyze, GET /api/evidence/article/{pmid}
│   │   └── search.py            # GET /api/search?q=...
│   ├── schemas/
│   │   └── evidence.py          # Pydantic models (the stable contract)
│   ├── services/
│   │   ├── pubmed_service.py    # PubMed (Entrez ESearch/EFetch/ESummary)
│   │   ├── europepmc_service.py # Europe PMC (REST) — articles + preprints + OA
│   │   ├── unpaywall_service.py # legal open-access full-text lookup by DOI
│   │   ├── evidence_rules.py    # pure rules: design (text + pub-type), PICO, mapping, cautions, summary
│   │   ├── evidence_service.py  # orchestration: source dispatch -> extract -> assemble
│   │   └── errors.py            # shared source exceptions
│   └── static/                  # web UI: Heimr theme, dark mode, metric definitions (index/style/app)
├── tests/                       # 72 tests (rules, PubMed, Europe PMC, Unpaywall, API; network mocked)
└── scripts/benchmark.py         # accuracy benchmark over a labelled abstract set
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
# open http://127.0.0.1:8000/      for the web app  (/docs for the API)
```

### Try it

```bash
# Analyze pasted text (no network needed)
curl -X POST http://127.0.0.1:8000/api/evidence/analyze \
  -H "Content-Type: application/json" \
  -d '{"title":"An RCT of drug X","abstract":"In this randomized, double-blind, placebo-controlled trial, 320 patients were enrolled..."}'

# Analyze a real PubMed article by PMID
curl http://127.0.0.1:8000/api/evidence/article/23440795

# Search Europe PMC (default) — summaries with evidence-level hints
curl "http://127.0.0.1:8000/api/search?q=statins+cardiovascular+mortality"

# Analyze a Europe PMC article (source + article_id)
curl -X POST http://127.0.0.1:8000/api/evidence/analyze \
  -H "Content-Type: application/json" \
  -d '{"source":"europepmc","article_id":"MED/23440795"}'
```

## Tests

```bash
pytest                       # full suite (rules + API; API mocks PubMed, no network)
pytest tests/test_evidence_rules.py   # just the pure rule engine
```

---

## Benchmark

The rule engine is measured against a labelled set of **26 synthetic abstracts**
(`tests/fixtures/benchmark_abstracts.py`), including deliberately hard cases (a
systematic review whose abstract mentions "meta-analysis", a cohort that never
says "cohort", a survey that never says "cross-sectional"):

| Metric | Result |
| --- | --- |
| Study-design accuracy | **23 / 26 (88%)** |
| Evidence-level accuracy | **24 / 26 (92%)** |
| Sample-size extraction | **15 / 15 (100%)** |

Run it with `python -m scripts.benchmark`. On real PubMed / Europe PMC articles,
publication-type tags push design accuracy higher still.

---

## Roadmap

Shipped in **1.0**:
- [x] Schema, service layer, rule engine, evidence scoring, tests
- [x] PubMed + **Europe PMC** sources (pluggable dispatch) with **preprint** support
- [x] **Unpaywall** legal open-access full-text links
- [x] Rule-based **key-points summary**; publication-type-aware design classification
- [x] Web UI ("Heimr"): **dark mode** (system + toggle), source selector, **metric definitions + glossary**
- [x] **Accuracy benchmark** — 26 labelled abstracts (88% design / 92% level / 100% sample-size)

Planned:
- [ ] Optional **LLM refinement** of summaries/limitations (`extraction_method="rules+llm"`)
- [ ] **ClinicalTrials.gov** trial-record tab
- [ ] **Multi-article comparison** view
