"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
const hide = (el) => el.classList.add("is-hidden");
const show = (el) => el.classList.remove("is-hidden");
const enc = (s) => encodeURIComponent(String(s == null ? "" : s));

const statusEl = $("#status");
const resultsEl = $("#results");
const resultEl = $("#result");
const compareBar = $("#compare-bar");
let lastAnalysis = null;

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// --- plain-language definitions for the info dots + glossary ---
const GLOSSARY = {
  evidence_level:
    "A provisional A–D grade of how much weight a study's design usually carries (A = High … D = Weak). It reflects design only, read from the abstract — not a full appraisal of the study's quality.",
  study_design:
    "How the study was run (e.g. randomized controlled trial, cohort, case-control). Design is the biggest driver of how much confidence the results warrant.",
  clinical_question:
    "The kind of question the study asks — therapy, diagnosis, prognosis, etiology/harm, prevention, or descriptive. The ideal design depends on the question.",
  sample_size:
    "The number of participants (n). Larger samples usually give more precise, reliable estimates; very small studies can mislead.",
  population: "Who was studied — the participants and their key characteristics (the “P” in PICO).",
  intervention: "The treatment, exposure, or factor under study (the “I” in PICO).",
  comparator: "What the intervention was compared against — placebo, usual care, or another option (the “C” in PICO).",
  outcome: "The main result the study set out to measure (the “O” in PICO).",
  key_finding: "The study's headline result, taken from its conclusion or final sentence.",
  reported_statistics:
    "Effect estimates (hazard/odds/risk ratios) found in the abstract, with 95% confidence intervals and p-values. The plain-language reading comes from fixed templates — no AI touches the numbers. A CI that excludes 1 means statistically significant at the usual threshold; clinical importance is a separate judgement.",
  appraisal_checklist:
    "CASP-style appraisal cues detected by phrase matching in the abstract (and Methods/Results when open-access full text is available). “Mentioned” means the text used that language — not that the study did it well. “Not found” means the available text did not mention it. This checklist never changes the A–D grade.",
  key_points: "A plain-language recap assembled from the fields below — a quick gist, not a substitute for reading the study.",
  confidence:
    "How cleanly THIS TOOL could read the abstract (0–100%) — i.e. how sure the extraction is. It is NOT a measure of how strong or trustworthy the evidence itself is.",
  caution_notes:
    "Honest caveats about over-reading this card — e.g. observational design, unreported sample size, or abstract-only analysis.",
  preprint: "A paper posted before peer review (e.g. medRxiv/bioRxiv). Findings are unverified — treat with extra caution.",
  retracted:
    "This article has been formally retracted (withdrawn) by the journal or authors — its findings should not be relied on. Flagged via PubMed's own tags or the Retraction Watch data in OpenAlex.",
  open_access:
    "A free, legal full-text copy is available (found via Unpaywall or PubMed Central). We never link to pirated copies.",
  full_text:
    "Some fields (sample size, PICO, extra statistics) were read from the article's legal open-access full text, not just the abstract — a fuller picture. Study design is only read from full text when the abstract left it unclear; the A–D grade still follows that design by the fixed table.",
  limitations:
    "Caveats about the study's design or methods that temper its conclusions — shown when you refine the summary with AI.",
};

// --- theme (light / dark / system) ---
const themeButtons = $$(".theme-toggle button");
function markTheme(pref) {
  themeButtons.forEach((b) => b.classList.toggle("on", b.dataset.themeSet === pref));
}
function applyTheme(pref) {
  localStorage.setItem("theme", pref);
  const dark = pref === "dark" || (pref === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  markTheme(pref);
}
themeButtons.forEach((b) => b.addEventListener("click", () => applyTheme(b.dataset.themeSet)));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if ((localStorage.getItem("theme") || "system") === "system") applyTheme("system");
});
markTheme(localStorage.getItem("theme") || "system");

// --- tabs ---
$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const mode = tab.dataset.mode;
    $$(".tab").forEach((t) => t.classList.toggle("is-active", t === tab));
    $$(".mode").forEach((m) => m.classList.toggle("is-hidden", m.dataset.mode !== mode));
    clearOutput();
    if (mode === "library") loadLibrary();
  });
});

// --- example ---
$("#btn-example").addEventListener("click", () => {
  $("#title").value = "A randomized controlled trial of a new inhaled therapy in adults with asthma";
  $("#abstract").value =
    "In this randomized, double-blind, placebo-controlled trial, a total of 512 adults " +
    "with moderate asthma were enrolled and randomized to the inhaled therapy or placebo. " +
    "The primary outcome was the annual rate of asthma exacerbations over 12 months. " +
    "The treatment was generally well tolerated. Compared with placebo, the inhaled therapy " +
    "significantly reduced the annual rate of asthma exacerbations.";
});

// --- search ---
$("#form-search").addEventListener("submit", (e) => {
  e.preventDefault();
  const query = $("#query").value.trim();
  if (!query) return showError("Enter something to search for.");
  runSearch(query, $("#source").value);
});

async function runSearch(query, source) {
  setBusy(true, "Searching…");
  hide(resultsEl);
  hide(compareBar);
  hide(resultEl);
  try {
    const res = await fetch(`/api/search?q=${enc(query)}&source=${enc(source)}`);
    if (!res.ok) throw new HttpError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    renderResults(await res.json(), source);
  } catch (err) {
    showError(friendlyError(err));
  } finally {
    setBusy(false);
  }
}

function renderResults(data, source) {
  hide(statusEl);
  const where = source === "pubmed" ? "PubMed" : "Europe PMC";
  if (!data.results || data.results.length === 0) {
    resultsEl.innerHTML = `<p class="results-empty">No ${where} results for “${escapeHtml(data.query)}”.</p>`;
    show(resultsEl);
    return;
  }
  resultsEl.innerHTML =
    `<div class="results-head">${data.count} result${data.count === 1 ? "" : "s"} from ${where} for “${escapeHtml(data.query)}”</div>` +
    data.results.map(resultRow).join("");
  show(resultsEl);
  $$(".result-row button[data-id]", resultsEl).forEach((btn) => {
    btn.addEventListener("click", () => analyze({ source: btn.dataset.source, article_id: btn.dataset.id }));
  });
}

function resultRow(r) {
  const level = r.evidence_level || "unclear";
  const lvlClass = `lvl-${String(level).toLowerCase()}`;
  const levelBadge =
    level !== "unclear" ? `<span class="badge level ${lvlClass}">${escapeHtml(levelWord(level, r.evidence_label))}</span>` : "";
  const flags = [];
  if (r.is_retracted) flags.push(`<span class="badge retracted">Retracted</span>`);
  if (r.is_preprint) flags.push(`<span class="badge preprint">Preprint</span>`);
  if (r.is_open_access) flags.push(`<span class="badge oa">Open access</span>`);
  const types = (r.publication_types || []).slice(0, 2).map((p) => `<span class="badge tiny">${escapeHtml(p)}</span>`).join("");
  const meta = [authorLine(r.authors), [r.journal, r.year].filter(Boolean).join(" · ")]
    .filter(Boolean)
    .map(escapeHtml)
    .join(" — ");
  const href = r.pmid
    ? `https://pubmed.ncbi.nlm.nih.gov/${enc(r.pmid)}/`
    : r.doi
      ? `https://doi.org/${enc(r.doi)}`
      : `https://europepmc.org/article/${escapeHtml(r.article_id || "")}`;
  return `
    <div class="result-row">
      <label class="cmp-check" title="Select to compare">
        <input type="checkbox" class="cmp-box" data-source="${escapeHtml(r.source || "pubmed")}" data-id="${escapeHtml(r.article_id || "")}" aria-label="Select to compare" />
      </label>
      <div class="result-body">
        <a class="result-title" href="${href}" target="_blank" rel="noopener">${escapeHtml(r.title || "Untitled")}</a>
        <div class="result-meta">${meta}</div>
        <div class="result-badges">${levelBadge}${flags.join("")}${types}</div>
      </div>
      <button class="btn primary small" data-source="${escapeHtml(r.source || "pubmed")}" data-id="${escapeHtml(r.article_id || "")}">Analyze</button>
    </div>`;
}

// --- compare selected search results (side-by-side) ---
resultsEl.addEventListener("change", (e) => {
  if (e.target.classList && e.target.classList.contains("cmp-box")) updateCompareBar();
});
$("#cmp-clear").addEventListener("click", () => {
  $$(".cmp-box:checked", resultsEl).forEach((b) => (b.checked = false));
  updateCompareBar();
});
$("#cmp-go").addEventListener("click", runCompare);

function updateCompareBar() {
  const n = $$(".cmp-box:checked", resultsEl).length;
  if (n === 0) return hide(compareBar);
  $("#cmp-count").textContent = n < 2 ? `${n} selected — pick at least 2` : `${n} selected`;
  $("#cmp-go").disabled = n < 2;
  show(compareBar);
}

async function runCompare() {
  const items = $$(".cmp-box:checked", resultsEl).map((b) => ({ source: b.dataset.source, article_id: b.dataset.id }));
  if (items.length < 2) return;
  setBusy(true, `Comparing ${items.length} articles…`);
  hide(resultEl);
  try {
    const res = await fetch("/api/evidence/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    if (!res.ok) throw new HttpError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    renderCompare(await res.json());
  } catch (err) {
    showError(friendlyError(err));
  } finally {
    setBusy(false);
  }
}

function renderCompare(data) {
  hide(statusEl);
  const items = data.analyses || [];
  const rows = [
    ["Evidence level", (a) => cmpLevel(a)],
    ["Study design", (a) => escapeHtml(humanize(a.study_design))],
    ["Clinical question", (a) => escapeHtml(humanize(a.clinical_question_type))],
    ["Sample size", (a) => (a.sample_size != null ? `n = ${Number(a.sample_size).toLocaleString()}` : cmpEmpty())],
    ["Population", (a) => cmpText(a.population)],
    ["Intervention / exposure", (a) => cmpText(a.intervention_or_exposure)],
    ["Comparator", (a) => cmpText(a.comparator)],
    ["Primary outcome", (a) => cmpText(a.primary_outcome)],
    ["Key finding", (a) => cmpText(a.key_finding)],
  ];
  const head = `<tr><th scope="col"></th>${items.map((a) => `<th scope="col">${cmpTitle(a)}</th>`).join("")}</tr>`;
  const body = rows
    .map(([label, fn]) => `<tr><th scope="row">${escapeHtml(label)}</th>${items.map((a) => `<td>${fn(a)}</td>`).join("")}</tr>`)
    .join("");
  resultEl.innerHTML = `
    <h2>Comparing ${items.length} articles</h2>
    <p class="src muted">Provisional, abstract-level estimates — a study aid, not medical advice.</p>
    <div class="compare-wrap">
      <table class="compare-table"><thead>${head}</thead><tbody>${body}</tbody></table>
    </div>`;
  show(resultEl);
  resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function cmpTitle(a) {
  const href =
    a.source_database === "pubmed" && a.article_id
      ? `https://pubmed.ncbi.nlm.nih.gov/${enc(a.article_id)}/`
      : a.source_database === "europepmc" && a.article_id
        ? `https://europepmc.org/article/${escapeHtml(a.article_id)}`
        : a.doi
          ? `https://doi.org/${enc(a.doi)}`
          : null;
  const t = escapeHtml(a.title || "Untitled");
  return href ? `<a href="${href}" target="_blank" rel="noopener">${t}</a>` : t;
}

function cmpLevel(a) {
  const level = a.evidence_level || "unclear";
  if (level === "unclear") return `<span class="badge level lvl-unclear">Unclear</span>`;
  return `<span class="badge level lvl-${String(level).toLowerCase()}">${escapeHtml(levelWord(level, a.evidence_label))}</span>`;
}

function cmpText(v) {
  return v != null && String(v).trim() !== "" ? escapeHtml(v) : cmpEmpty();
}
function cmpEmpty() {
  return `<span class="cmp-empty">not reported</span>`;
}

// --- ClinicalTrials.gov: search list + trial-record card ---
$("#form-trials").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#trial-q").value.trim();
  if (!q) return showError("Enter something to search for.");
  runTrialSearch(q);
});

async function runTrialSearch(query) {
  setBusy(true, "Searching trials…");
  hide(resultsEl);
  hide(compareBar);
  hide(resultEl);
  try {
    const res = await fetch(`/api/trials?q=${enc(query)}`);
    if (!res.ok) throw new HttpError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    renderTrialResults(await res.json());
  } catch (err) {
    showError(friendlyError(err));
  } finally {
    setBusy(false);
  }
}

function renderTrialResults(data) {
  hide(statusEl);
  const list = data.results || [];
  if (list.length === 0) {
    resultsEl.innerHTML = `<p class="results-empty">No ClinicalTrials.gov results for “${escapeHtml(data.query)}”.</p>`;
    show(resultsEl);
    return;
  }
  resultsEl.innerHTML =
    `<div class="results-head">${data.count} trial${data.count === 1 ? "" : "s"} for “${escapeHtml(data.query)}”</div>` +
    list.map(trialRow).join("");
  show(resultsEl);
  $$("button[data-nct]", resultsEl).forEach((btn) => btn.addEventListener("click", () => openTrial(btn.dataset.nct)));
}

function trialRow(t) {
  const badges = [t.status, t.phase, t.study_type]
    .filter(Boolean)
    .map((x) => `<span class="badge tiny">${escapeHtml(x)}</span>`)
    .join("");
  const meta = [t.nct_id, (t.conditions || []).slice(0, 3).join(", ")].filter(Boolean).map(escapeHtml).join(" — ");
  return `
    <div class="result-row">
      <div class="result-body">
        <a class="result-title" href="https://clinicaltrials.gov/study/${enc(t.nct_id)}" target="_blank" rel="noopener">${escapeHtml(t.title || t.nct_id)}</a>
        <div class="result-meta">${meta}</div>
        <div class="result-badges">${badges}</div>
      </div>
      <button class="btn primary small" data-nct="${escapeHtml(t.nct_id)}">View</button>
    </div>`;
}

async function openTrial(nct) {
  setBusy(true, "Opening trial record…");
  try {
    const res = await fetch(`/api/trials/${enc(nct)}`);
    if (!res.ok) throw new HttpError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    renderTrial(await res.json());
  } catch (err) {
    showError(friendlyError(err));
  } finally {
    setBusy(false);
  }
}

function renderTrial(t) {
  hide(statusEl);
  const src = [`<a href="${escapeHtml(t.url)}" target="_blank" rel="noopener">${escapeHtml(t.nct_id)} ↗</a>`];
  if (t.status) src.push(`<span class="badge tiny">${escapeHtml(t.status)}</span>`);
  const details = [
    t.sponsor ? detail("Sponsor", escapeHtml(t.sponsor)) : "",
    t.start_date ? detail("Start", escapeHtml(t.start_date)) : "",
    t.completion_date ? detail("Completion", escapeHtml(t.completion_date)) : "",
  ].join("");
  resultEl.innerHTML = `
    <h2>${escapeHtml(t.title || t.nct_id)}</h2>
    <p class="src">${src.join("")}</p>
    <div class="fields">
      ${field("Study type", t.study_type)}
      ${field("Phase", t.phase)}
      ${field("Enrollment", t.enrollment != null ? `${Number(t.enrollment).toLocaleString()} participants` : null, null, true)}
      ${field("Status", t.status)}
    </div>
    ${block("Summary", t.brief_summary)}
    ${trialList("Conditions", t.conditions)}
    ${trialList("Interventions", t.interventions)}
    ${details ? `<div class="block"><div class="label">Trial details</div><div class="details-list">${details}</div></div>` : ""}
    <p class="trial-note">Trial records describe planned or ongoing studies registered on ClinicalTrials.gov — they are not journal articles and are not graded on the A–D evidence scale.</p>`;
  show(resultEl);
  resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function trialList(label, items) {
  const list = (items || []).filter((x) => x && String(x).trim());
  if (!list.length) return "";
  return `<div class="block"><div class="label">${escapeHtml(label)}</div><ul class="trial-ul">${list
    .map((x) => `<li>${escapeHtml(x)}</li>`)
    .join("")}</ul></div>`;
}

// --- analyze (PMID form, text form, or a search result) ---
$("#form-pmid").addEventListener("submit", (e) => {
  e.preventDefault();
  const pmid = $("#pmid").value.trim();
  if (!pmid) return showError("Enter a PubMed ID (PMID) to analyze.");
  analyze({ pmid });
});

$("#form-text").addEventListener("submit", (e) => {
  e.preventDefault();
  const abstract = $("#abstract").value.trim();
  if (!abstract) return showError("Paste an abstract to analyze.");
  analyze({ title: $("#title").value.trim() || null, abstract });
});

// --- library (saved analyses + notes) ---
const libraryListEl = $("#library-list");

async function loadLibrary() {
  libraryListEl.innerHTML = `<p class="results-empty">Loading…</p>`;
  try {
    const res = await fetch("/api/history");
    if (!res.ok) throw new HttpError(res.status, res.statusText);
    const data = await res.json();
    if (!data.items.length) {
      libraryListEl.innerHTML = `<p class="results-empty">Nothing saved yet — analyze an article and it will appear here.</p>`;
      return;
    }
    libraryListEl.innerHTML = data.items.map(libraryRow).join("");
    $$("button[data-open]", libraryListEl).forEach((b) =>
      b.addEventListener("click", () => openFromLibrary(b.dataset.open))
    );
    $$("button[data-del]", libraryListEl).forEach((b) =>
      b.addEventListener("click", async () => {
        if (!confirm("Remove this saved analysis (and its notes)?")) return;
        await fetch(`/api/history/${enc(b.dataset.del)}`, { method: "DELETE" });
        loadLibrary();
      })
    );
  } catch (err) {
    libraryListEl.innerHTML = `<p class="results-empty">${escapeHtml(friendlyError(err))}</p>`;
  }
}

function libraryRow(item) {
  const level = item.evidence_level || "unclear";
  const lvlClass = `lvl-${String(level).toLowerCase()}`;
  const badges = [];
  if (level !== "unclear") badges.push(`<span class="badge level ${lvlClass}">${escapeHtml(level)}</span>`);
  if (item.is_retracted) badges.push(`<span class="badge retracted">Retracted</span>`);
  if (item.notes && item.notes.trim()) badges.push(`<span class="badge tiny">✎ notes</span>`);
  const meta = [humanize(item.study_design), [item.journal, item.year].filter(Boolean).join(" · "),
    (item.analyzed_at || "").slice(0, 10)]
    .filter(Boolean)
    .map(escapeHtml)
    .join(" — ");
  return `
    <div class="result-row">
      <div class="result-body">
        <span class="result-title">${escapeHtml(item.title || "Untitled analysis")}</span>
        <div class="result-meta">${meta}</div>
        <div class="result-badges">${badges.join("")}</div>
      </div>
      <div class="lib-actions">
        <button class="btn primary small" data-open="${item.id}">Open</button>
        <button class="btn ghost small" data-del="${item.id}">Delete</button>
      </div>
    </div>`;
}

async function openFromLibrary(id) {
  setBusy(true, "Opening saved analysis…");
  try {
    const res = await fetch(`/api/history/${enc(id)}`);
    if (!res.ok) throw new HttpError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    const entry = await res.json();
    render(entry.analysis);
    attachNotesEditor(entry.id, entry.notes);
  } catch (err) {
    showError(friendlyError(err));
  } finally {
    setBusy(false);
  }
}

function attachNotesEditor(id, notes) {
  const div = document.createElement("div");
  div.className = "block notes-block";
  div.innerHTML = `
    <div class="label">My appraisal notes</div>
    <textarea id="notes-text" rows="4" placeholder="Why do I trust or doubt this study? How does it fit my question?"></textarea>
    <div class="row end">
      <span class="notes-saved is-hidden" id="notes-saved">Saved ✓</span>
      <button class="btn ghost small" id="btn-save-notes" type="button">Save notes</button>
    </div>`;
  resultEl.appendChild(div);
  $("#notes-text").value = notes || "";
  $("#btn-save-notes").addEventListener("click", async () => {
    const res = await fetch(`/api/history/${enc(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes: $("#notes-text").value }),
    });
    if (res.ok) {
      show($("#notes-saved"));
      setTimeout(() => hide($("#notes-saved")), 2000);
    }
  });
}

// --- PDF drop-in (paste tab) ---
const dropzone = $("#dropzone");
const pdfInput = $("#pdf-input");
if (dropzone) {
  dropzone.addEventListener("click", () => pdfInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      pdfInput.click();
    }
  });
  ["dragover", "dragenter"].forEach((t) =>
    dropzone.addEventListener(t, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragging");
    })
  );
  ["dragleave", "drop"].forEach((t) =>
    dropzone.addEventListener(t, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragging");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) analyzePdf(file);
  });
  pdfInput.addEventListener("change", () => {
    if (pdfInput.files[0]) {
      analyzePdf(pdfInput.files[0]);
      pdfInput.value = "";
    }
  });
}

async function analyzePdf(file) {
  if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf")
    return showError("That doesn't look like a PDF file.");
  setBusy(true, `Reading ${file.name}…`);
  try {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/evidence/analyze-pdf", { method: "POST", body: fd });
    if (!res.ok) throw new HttpError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    render(await res.json());
  } catch (err) {
    showError(friendlyError(err));
  } finally {
    setBusy(false);
  }
}

async function analyze(payload, busyMsg) {
  setBusy(true, busyMsg || "Analyzing…");
  try {
    const res = await fetch("/api/evidence/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new HttpError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    render(await res.json());
  } catch (err) {
    showError(friendlyError(err));
  } finally {
    setBusy(false);
  }
}

function friendlyError(err) {
  if (err instanceof HttpError) {
    if (err.status === 404) return "No article found for that id. Check it and try again.";
    if (err.status === 502) return "Couldn't reach the source right now. Try again, or paste the abstract instead.";
    if (err.status === 422) return err.message || "Provide an article or an abstract to analyze.";
    return `Request failed (${err.status}): ${err.message}`;
  }
  return "Network error — is the server running? Try again.";
}

// --- render the evidence card ---
function render(d) {
  hide(statusEl);
  lastAnalysis = d;
  const level = d.evidence_level || "unclear";
  const lvlClass = `lvl-${String(level).toLowerCase()}`;
  const conf = Math.round((d.confidence_score || 0) * 100);
  const letter = level === "unclear" ? "—" : escapeHtml(level);

  const src = [];
  src.push(sourceLink(d));
  const jy = [d.journal, d.year].filter(Boolean).join(" · ");
  if (jy) src.push(`<span>${escapeHtml(jy)}</span>`);
  if (d.is_retracted) src.push(`<span class="badge retracted">Retracted</span>${info("retracted")}`);
  if (d.is_preprint) src.push(`<span class="badge preprint">Preprint</span>${info("preprint")}`);
  if (d.oa_url) src.push(`<a class="badge oa" href="${escapeHtml(d.oa_url)}" target="_blank" rel="noopener">Free full text ↗</a>`);
  if (d.used_full_text) src.push(`<span class="badge fulltext">Read from full text</span>${info("full_text")}`);

  resultEl.innerHTML = `
    <h2>${escapeHtml(d.title || "Untitled article")}</h2>
    <p class="src">${src.join("")}</p>

    <div class="card-tools" role="group" aria-label="Export">
      <button id="exp-md" class="btn ghost small" type="button">Copy as Markdown</button>
      <button id="exp-bib" class="btn ghost small" type="button">BibTeX</button>
      <button id="exp-ris" class="btn ghost small" type="button">RIS</button>
    </div>

    <div class="ev-row">
      <div class="ev-tile ${lvlClass}"><span class="ev-letter">${letter}</span></div>
      <div class="ev-meta">
        <div class="e1">Evidence level ${info("evidence_level")}</div>
        <div class="e2">${escapeHtml(levelWord(level, d.evidence_label))}</div>
      </div>
      <div class="ev-chips">
        <span class="badge"><span class="k">Design</span> ${escapeHtml(humanize(d.study_design))} ${info("study_design")}</span>
        <span class="badge"><span class="k">Question</span> ${escapeHtml(humanize(d.clinical_question_type))} ${info("clinical_question")}</span>
      </div>
    </div>

    ${whyGrade(d)}

    ${keyPoints(d)}
    ${refineControl(d)}
    <div id="ask-panel"></div>

    <div class="fields">
      ${field("Sample size", d.sample_size != null ? `n = ${Number(d.sample_size).toLocaleString()}` : null, "sample_size", true)}
      ${field("Population", d.population, "population")}
      ${field("Intervention / exposure", d.intervention_or_exposure, "intervention")}
      ${field("Comparator", d.comparator, "comparator")}
    </div>

    ${block("Key finding", d.key_finding, "key_finding")}
    ${reportedStats(d)}
    ${block("Primary outcome", d.primary_outcome, "outcome")}
    ${appraisalChecklist(d)}
    ${block("Limitations", d.limitations, "limitations")}
    ${articleDetails(d)}

    ${
      d.caution_notes && d.caution_notes.length
        ? `<div class="block"><div class="label">Cautions ${info("caution_notes")}</div>
             <ul class="cautions">${d.caution_notes
               .map((c) => `<li class="${/^RETRACTED/.test(c) ? "retracted-note" : /preprint/i.test(c) ? "preprint-note" : ""}">${escapeHtml(c)}</li>`)
               .join("")}</ul></div>`
        : ""
    }

    <div class="block">
      <div class="label">Confidence ${info("confidence")} <span class="muted">(${escapeHtml(d.extraction_method || "rules")} estimate)</span></div>
      <div class="confidence"><span class="bar"><i style="width:${conf}%"></i></span><span class="pct">${conf}%</span></div>
    </div>

    ${glossary()}
  `;
  show(resultEl);
  const refineBtn = $("#btn-refine", resultEl);
  if (refineBtn) refineBtn.addEventListener("click", refineWithAI);
  wireExport(d);
  enhanceWithAi(d);
  resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// --- export / cite (all client-side, from the current card) ---
function wireExport(d) {
  const md = $("#exp-md", resultEl);
  const bib = $("#exp-bib", resultEl);
  const ris = $("#exp-ris", resultEl);
  if (md) md.addEventListener("click", (e) => copyText(toMarkdown(d), e.currentTarget));
  if (bib) bib.addEventListener("click", () => downloadText(toBibtex(d), `${citationKey(d)}.bib`, "application/x-bibtex"));
  if (ris) ris.addEventListener("click", () => downloadText(toRis(d), `${citationKey(d)}.ris`, "application/x-research-info-systems"));
}

function citationKey(d) {
  const first = d.authors && d.authors[0] ? String(d.authors[0]).split(/[\s,]/)[0] : "anon";
  return `${first}${d.year || "nd"}`.replace(/[^A-Za-z0-9]/g, "") || "citation";
}

function toMarkdown(d) {
  const L = [`# ${d.title || "Untitled article"}`];
  const meta = [authorLine(d.authors), [d.journal, d.year].filter(Boolean).join(" · "), d.doi ? `doi:${d.doi}` : ""].filter(Boolean);
  if (meta.length) L.push("", meta.join(" — "));
  L.push("", `**Evidence level:** ${levelWord(d.evidence_level, d.evidence_label)}`);
  L.push(`**Study design:** ${humanize(d.study_design)}`);
  L.push(`**Clinical question:** ${humanize(d.clinical_question_type)}`);
  if (d.sample_size != null) L.push(`**Sample size:** n = ${d.sample_size}`);
  if (d.population) L.push(`**Population:** ${d.population}`);
  if (d.intervention_or_exposure) L.push(`**Intervention / exposure:** ${d.intervention_or_exposure}`);
  if (d.comparator) L.push(`**Comparator:** ${d.comparator}`);
  if (d.primary_outcome) L.push(`**Primary outcome:** ${d.primary_outcome}`);
  if (d.key_finding) L.push("", `**Key finding:** ${d.key_finding}`);
  if (d.key_points_summary) L.push("", d.key_points_summary);
  (d.key_points || []).forEach((b) => L.push(`- ${b}`));
  if (d.reported_statistics && d.reported_statistics.length) {
    L.push("", "**Reported statistics:**");
    d.reported_statistics.forEach((s) => L.push(`- ${s.display} — ${s.reading}`));
  }
  if (d.appraisal_checklist && d.appraisal_checklist.signals && d.appraisal_checklist.signals.length) {
    const ac = d.appraisal_checklist;
    L.push(
      "",
      `**Appraisal signals (${ac.label || "CASP-style"}):** ` +
        `${ac.mentioned_count || 0} mentioned` +
        (ac.concern_count ? `, ${ac.concern_count} concern` : "") +
        ` of ${ac.total || ac.signals.length}`
    );
    ac.signals.forEach((s) => {
      const st = s.status || "not_found";
      const phrase = s.matched_phrase ? ` (“${s.matched_phrase}”)` : "";
      L.push(`- [${st}] ${s.question}${phrase}`);
    });
  }
  if (d.limitations) L.push("", `**Limitations:** ${d.limitations}`);
  if (d.caution_notes && d.caution_notes.length) {
    L.push("", "**Cautions:**");
    d.caution_notes.forEach((c) => L.push(`- ${c}`));
  }
  L.push("", `*Provisional, rule-based estimate (${d.extraction_method || "rules"}) — a study aid, not medical advice.*`);
  return L.join("\n");
}

function toBibtex(d) {
  const f = [];
  if (d.title) f.push(`  title = {${d.title}}`);
  if (d.authors && d.authors.length) f.push(`  author = {${d.authors.join(" and ")}}`);
  if (d.journal) f.push(`  journal = {${d.journal}}`);
  if (d.year) f.push(`  year = {${d.year}}`);
  if (d.doi) f.push(`  doi = {${d.doi}}`);
  return `@article{${citationKey(d)},\n${f.join(",\n")}\n}\n`;
}

function toRis(d) {
  const L = ["TY  - JOUR"];
  (d.authors || []).forEach((a) => L.push(`AU  - ${a}`));
  if (d.title) L.push(`TI  - ${d.title}`);
  if (d.journal) L.push(`JO  - ${d.journal}`);
  if (d.year) L.push(`PY  - ${d.year}`);
  if (d.doi) L.push(`DO  - ${d.doi}`);
  L.push("ER  - ");
  return L.join("\n") + "\n";
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const prev = btn.textContent;
    btn.textContent = "Copied ✓";
    setTimeout(() => (btn.textContent = prev), 1500);
  } catch {
    showError("Couldn't copy to the clipboard.");
  }
}

function downloadText(text, filename, type) {
  const blob = new Blob([text], { type: type || "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// --- "Why this grade?" transparency trail ---
function whyGrade(d) {
  const phrase = d.study_design_evidence;
  const hasAbstract = d.abstract && d.abstract.trim();
  if (!phrase && !hasAbstract) return "";
  const fromPubType = !!phrase && /^PubMed type:/i.test(phrase);
  const fromFullText = !!phrase && /^full text:/i.test(phrase);
  const conf = Math.round((d.study_design_confidence || 0) * 100);
  const cueLabel = (() => {
    if (!phrase) return "no design cue found";
    if (fromPubType || fromFullText) return phrase;
    return `“${phrase}”`;
  })();
  const chain = [
    `<span class="why-cue">${escapeHtml(cueLabel)}</span>`,
    `<span class="why-step">${escapeHtml(humanize(d.study_design))}</span>`,
    `<span class="why-step">Level ${escapeHtml(levelWord(d.evidence_level, d.evidence_label))}</span>`,
  ].join(`<span class="why-arrow" aria-hidden="true">→</span>`);
  const barePhrase = fromFullText
    ? String(phrase).replace(/^full text:\s*/i, "")
    : phrase;
  const inAbstract =
    !!barePhrase &&
    !fromPubType &&
    !fromFullText &&
    !!hasAbstract &&
    d.abstract.toLowerCase().includes(String(barePhrase).toLowerCase());
  const note = fromPubType
    ? "The design comes from PubMed's own publication-type tag — the most reliable signal — and maps to the level by the fixed A–D table (see the glossary below)."
    : fromFullText
      ? `The abstract left the design unclear; this cue was found in the open-access full text (Methods) and triggered classification (pattern confidence ${conf}%). The design maps to the level by the fixed A–D table (see the glossary below).`
      : phrase
        ? `This phrase${inAbstract ? " (highlighted below)" : ", found in the title"} triggered the design classification (pattern confidence ${conf}%); the design maps to the level by the fixed A–D table (see the glossary below).`
        : "No design phrase was recognized, so the design and level are unclear — try finding the design cues in the abstract yourself.";
  const abstractHtml = hasAbstract
    ? `<div class="why-abstract"><div class="label">Abstract${inAbstract ? " — design cue highlighted" : ""}</div><p>${highlightPhrase(d.abstract, inAbstract ? phrase : null)}</p></div>`
    : "";
  return `<details class="why-grade"><summary>Why this grade?</summary><p class="why-chain">${chain}</p><p class="why-note">${note}</p>${abstractHtml}</details>`;
}

function highlightPhrase(text, phrase) {
  const t = String(text);
  if (!phrase) return escapeHtml(t);
  const i = t.toLowerCase().indexOf(String(phrase).toLowerCase());
  if (i < 0) return escapeHtml(t);
  return (
    escapeHtml(t.slice(0, i)) +
    `<mark>${escapeHtml(t.slice(i, i + phrase.length))}</mark>` +
    escapeHtml(t.slice(i + phrase.length))
  );
}

function refineControl(d) {
  if (d.extraction_method === "rules+llm") {
    return `<p class="ai-tag">Summary refined by AI · ${escapeHtml(d.extraction_method)}</p>`;
  }
  return `<div class="refine-row"><button id="btn-refine" class="btn ghost small" type="button">Refine with AI</button><span class="refine-hint" id="refine-hint">Rewrites the summary and limitations with a local model (Ollama) or Claude — set OLLAMA_MODEL or ANTHROPIC_API_KEY in .env.</span></div>`;
}

// --- AI status + optional AI features on the card ---
let aiStatusCache = null;
let aiStatusAt = 0;

async function getAiStatus(force) {
  if (!force && aiStatusCache && Date.now() - aiStatusAt < 30000) return aiStatusCache;
  try {
    const res = await fetch("/api/llm/status");
    aiStatusCache = res.ok ? await res.json() : null;
  } catch {
    aiStatusCache = null;
  }
  aiStatusAt = Date.now();
  return aiStatusCache;
}

const AI_READY_HINTS = {
  ollama: (s) => `Local AI ready (${s.model}) — rewrites the summary and limitations; the grade stays rule-based.`,
  anthropic: (s) => `Claude API ready (${s.model}) — rewrites the summary and limitations; the grade stays rule-based.`,
};

async function enhanceWithAi(d) {
  const status = await getAiStatus();
  if (lastAnalysis !== d) return; // a newer card replaced this one while we fetched
  const hint = $("#refine-hint");
  const refineBtn = $("#btn-refine");
  if (!status || !status.provider) return; // keep the static set-up hint

  const usable = status.reachable && status.model_available;
  if (hint) {
    hint.textContent = usable ? AI_READY_HINTS[status.provider](status) : status.detail || "";
  }
  if (refineBtn) refineBtn.disabled = !usable;
  if (!usable) return;

  // PICO suggestion button for fields the rules could not extract.
  const missing = [
    ["population", d.population],
    ["intervention_or_exposure", d.intervention_or_exposure],
    ["comparator", d.comparator],
    ["primary_outcome", d.primary_outcome],
  ]
    .filter(([, v]) => v == null || String(v).trim() === "")
    .map(([k]) => k);
  const fieldsEl = $(".fields", resultEl);
  if (missing.length && fieldsEl && d.abstract && d.abstract.trim() && !$("#btn-pico")) {
    const wrap = document.createElement("div");
    wrap.className = "pico-suggest-row";
    wrap.innerHTML = `<button id="btn-pico" class="btn ghost small" type="button">✨ Suggest missing PICO with AI</button><span class="refine-hint">Labeled hints only — the rule-based fields above stay as extracted.</span>`;
    fieldsEl.after(wrap);
    $("#btn-pico").addEventListener("click", () => suggestPico(d, missing, wrap));
  }

  // "Ask this article" — Europe PMC full text when available, else the abstract.
  const askHost = $("#ask-panel");
  if (askHost && d.source_database === "europepmc" && d.article_id) {
    askHost.innerHTML = `
      <details class="ask-panel">
        <summary>Ask this article (AI)</summary>
        <div class="row ask-row">
          <input id="ask-q" type="text" placeholder="e.g. How was the control group handled?" autocomplete="off" />
          <button id="btn-ask" class="btn primary small" type="button">Ask</button>
        </div>
        <div id="ask-answers"></div>
        <p class="hint">Answered by ${
          status.provider === "ollama" ? "your local model" : "Claude"
        } from the article's legal open-access full text when available, otherwise its abstract — each answer says which, with quotes to verify. Not medical advice.</p>
      </details>`;
    const askBtn = $("#btn-ask");
    const askGo = () => askArticle(d, askBtn);
    askBtn.addEventListener("click", askGo);
    $("#ask-q").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        askGo();
      }
    });
  }
}

async function suggestPico(d, missing, wrap) {
  const btn = $("#btn-pico");
  btn.disabled = true;
  btn.textContent = "Asking the model…";
  try {
    const res = await fetch("/api/evidence/suggest-pico", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: d.title || null, abstract: d.abstract, fields: missing }),
    });
    if (!res.ok) throw new HttpError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    const data = await res.json();
    const names = {
      population: "Population",
      intervention_or_exposure: "Intervention / exposure",
      comparator: "Comparator",
      primary_outcome: "Primary outcome",
    };
    const entries = Object.entries(data.suggestions || {});
    wrap.innerHTML = entries.length
      ? `<div class="ai-suggest"><div class="label">✨ AI-suggested (not from rules — verify in the abstract)</div><ul>${entries
          .map(([k, v]) => `<li><b>${names[k]}:</b> ${escapeHtml(v)}</li>`)
          .join("")}</ul></div>`
      : `<div class="ai-suggest"><div class="label">✨ AI suggestions</div><p class="muted">The model also found nothing it could support from the abstract.</p></div>`;
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "✨ Suggest missing PICO with AI";
    showError(friendlyError(err));
  }
}

async function askArticle(d, btn) {
  const q = $("#ask-q").value.trim();
  if (!q) return;
  const answers = $("#ask-answers");
  btn.disabled = true;
  answers.insertAdjacentHTML(
    "beforeend",
    `<div class="ask-item pending"><p class="ask-q">${escapeHtml(q)}</p><p class="ask-a muted"><span class="spinner"></span>Reading the full text…</p></div>`
  );
  const item = answers.lastElementChild;
  try {
    const res = await fetch("/api/evidence/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: d.source_database, article_id: d.article_id, question: q }),
    });
    if (!res.ok) throw new HttpError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    const data = await res.json();
    item.classList.remove("pending");
    const basis = data.basis === "abstract" ? "from the abstract only" : "from the full text";
    item.querySelector(".ask-a").outerHTML =
      `<p class="ask-a">${escapeHtml(data.answer)}</p>` +
      (data.quotes && data.quotes.length
        ? `<ul class="ask-quotes">${data.quotes.map((s) => `<li>“${escapeHtml(s)}”</li>`).join("")}</ul>`
        : "") +
      `<p class="ask-basis muted">Answered ${basis}.</p>`;
    $("#ask-q").value = "";
  } catch (err) {
    item.querySelector(".ask-a").outerHTML = `<p class="ask-a error-text">${escapeHtml(friendlyError(err))}</p>`;
  } finally {
    btn.disabled = false;
  }
}

function refineWithAI() {
  const d = lastAnalysis;
  if (!d) return;
  const fromSource = (d.source_database === "pubmed" || d.source_database === "europepmc") && d.article_id;
  const payload = fromSource
    ? { source: d.source_database, article_id: d.article_id, use_llm: true }
    : { title: d.title || null, abstract: d.abstract || null, use_llm: true };
  analyze(payload, "Refining with AI…");
}

function sourceLink(d) {
  if (d.source_database === "pubmed" && d.article_id)
    return `<a href="https://pubmed.ncbi.nlm.nih.gov/${enc(d.article_id)}/" target="_blank" rel="noopener">PMID ${escapeHtml(d.article_id)} ↗</a>`;
  if (d.source_database === "europepmc" && d.article_id)
    return `<a href="https://europepmc.org/article/${escapeHtml(d.article_id)}" target="_blank" rel="noopener">Europe PMC ↗</a>`;
  if (d.doi) return `<a href="https://doi.org/${enc(d.doi)}" target="_blank" rel="noopener">View article ↗</a>`;
  if (d.source_database === "pdf") return "PDF upload (read locally)";
  return escapeHtml(d.source_database || "manual input");
}

function keyPoints(d) {
  const hasSummary = d.key_points_summary && d.key_points_summary.trim();
  const bullets = d.key_points || [];
  if (!hasSummary && bullets.length === 0) return "";
  return `
    <div class="keypoints">
      <div class="label">Key points ${info("key_points")}</div>
      ${hasSummary ? `<p class="kp-summary">${escapeHtml(d.key_points_summary)}</p>` : ""}
      ${bullets.length ? `<ul>${bullets.map((b) => `<li>${kpBullet(b)}</li>`).join("")}</ul>` : ""}
    </div>`;
}

function kpBullet(b) {
  const i = String(b).indexOf(":");
  if (i > 0) return `<b>${escapeHtml(b.slice(0, i + 1))}</b> ${escapeHtml(b.slice(i + 1).trim())}`;
  return escapeHtml(b);
}

function reportedStats(d) {
  const stats = d.reported_statistics || [];
  if (!stats.length) return "";
  const rows = stats
    .map(
      (s) =>
        `<div class="stat-row"><span class="stat-val">${escapeHtml(s.display)}</span>` +
        `<span class="stat-label muted">${escapeHtml(s.label)}</span>` +
        `<p class="stat-read">${escapeHtml(s.reading)}</p></div>`
    )
    .join("");
  return `<div class="block"><div class="label">Reported statistics ${info("reported_statistics")}</div><div class="stats">${rows}</div></div>`;
}

function appraisalStatusLabel(status) {
  if (status === "mentioned") return "Mentioned";
  if (status === "concern") return "Concern";
  return "Not found";
}

function appraisalChecklist(d) {
  const ac = d.appraisal_checklist;
  if (!ac || !ac.signals || !ac.signals.length) return "";
  const rows = ac.signals
    .map((s) => {
      const st = s.status || "not_found";
      const phrase = s.matched_phrase
        ? `<span class="appr-phrase muted">“${escapeHtml(s.matched_phrase)}”</span>`
        : "";
      const note = s.note ? `<p class="appr-note muted">${escapeHtml(s.note)}</p>` : "";
      return (
        `<div class="appr-row status-${escapeHtml(st)}">` +
        `<span class="appr-badge">${escapeHtml(appraisalStatusLabel(st))}</span>` +
        `<div class="appr-body"><div class="appr-q">${escapeHtml(s.question)} ${phrase}</div>${note}</div>` +
        `</div>`
      );
    })
    .join("");
  const summary =
    `${ac.mentioned_count || 0} mentioned` +
    (ac.concern_count ? ` · ${ac.concern_count} concern` : "") +
    ` · ${ac.total || ac.signals.length} cues`;
  return (
    `<details class="appraisal-checklist">` +
    `<summary>Appraisal signals <span class="muted">(${escapeHtml(ac.label || "CASP-style")})</span> ${info("appraisal_checklist")}` +
    `<span class="appr-summary muted">${escapeHtml(summary)}</span></summary>` +
    `<p class="appr-disclaimer muted">Phrase detection only — not a full critical appraisal, and it does not change the A–D grade. “Not found” means the available text did not mention the cue.</p>` +
    `<div class="appr-list">${rows}</div></details>`
  );
}

function articleDetails(d) {
  const rows = [];
  if (d.authors && d.authors.length) rows.push(detail("Authors", escapeHtml(authorLine(d.authors))));
  if (d.citation) rows.push(detail("Citation", escapeHtml(d.citation)));
  else if (d.journal || d.year) rows.push(detail("Journal", escapeHtml([d.journal, d.year].filter(Boolean).join(" · "))));
  if (d.doi)
    rows.push(detail("DOI", `<a href="https://doi.org/${enc(d.doi)}" target="_blank" rel="noopener">${escapeHtml(d.doi)}</a>`));
  rows.push(
    detail(
      `Open access ${info("open_access")}`,
      d.oa_url
        ? `<a href="${escapeHtml(d.oa_url)}" target="_blank" rel="noopener">Yes — free full text ↗</a>`
        : "Not found"
    )
  );
  if (d.publication_types && d.publication_types.length)
    rows.push(detail("PubMed type", d.publication_types.map((p) => `<span class="badge tiny">${escapeHtml(p)}</span>`).join(" ")));
  if (d.keywords && d.keywords.length) rows.push(detail("Topics", escapeHtml(d.keywords.join(", "))));
  if (rows.length === 0) return "";
  return `<div class="block"><div class="label">Article details</div><div class="details-list">${rows.join("")}</div></div>`;
}

function detail(label, valueHtml) {
  return `<div class="detail"><span class="detail-k">${label}</span><span class="detail-v">${valueHtml}</span></div>`;
}

function field(label, value, term, mono) {
  const has = value != null && String(value).trim() !== "";
  const inner = has
    ? `<div class="value${mono ? " mono" : ""}">${escapeHtml(value)}</div>`
    : `<div class="value empty">not reported</div>`;
  return `<div class="field"><div class="label">${escapeHtml(label)} ${term ? info(term) : ""}</div>${inner}</div>`;
}

function block(label, value, term) {
  if (value == null || String(value).trim() === "") return "";
  return `<div class="block"><div class="label">${escapeHtml(label)} ${term ? info(term) : ""}</div><p>${escapeHtml(value)}</p></div>`;
}

function glossary() {
  const order = [
    ["evidence_level", "Evidence level"],
    ["study_design", "Study design"],
    ["clinical_question", "Clinical question"],
    ["sample_size", "Sample size"],
    ["population", "Population (PICO)"],
    ["intervention", "Intervention / exposure"],
    ["comparator", "Comparator"],
    ["outcome", "Primary outcome"],
    ["key_finding", "Key finding"],
    ["reported_statistics", "Reported statistics"],
    ["appraisal_checklist", "Appraisal signals"],
    ["confidence", "Confidence"],
    ["caution_notes", "Cautions"],
    ["limitations", "Limitations"],
    ["preprint", "Preprint"],
    ["retracted", "Retracted"],
    ["open_access", "Open access"],
    ["full_text", "Full text used"],
  ];
  const map =
    `<div class="gl-item"><dt>The A–D scale</dt><dd>A (High): systematic review / meta-analysis. ` +
    `B (Moderate): randomized trial or cohort. C (Lower): case-control or cross-sectional. ` +
    `D (Weak): case report/series, narrative review, or expert opinion.</dd></div>`;
  const items = order.map(([t, n]) => `<div class="gl-item"><dt>${escapeHtml(n)}</dt><dd>${escapeHtml(GLOSSARY[t])}</dd></div>`).join("");
  return `<details class="glossary"><summary>How to read this card</summary><dl>${map}${items}</dl></details>`;
}

function info(term) {
  return `<button class="info" type="button" data-term="${term}" aria-label="What this means">i</button>`;
}

// --- tooltip popover for the info dots ---
let tipEl = null;
let tipFor = null;
function getTip() {
  if (!tipEl) {
    tipEl = document.createElement("div");
    tipEl.className = "tip";
    tipEl.setAttribute("role", "tooltip");
    document.body.appendChild(tipEl);
  }
  return tipEl;
}
function showTip(btn) {
  const t = getTip();
  t.textContent = GLOSSARY[btn.dataset.term] || "";
  t.style.display = "block";
  const r = btn.getBoundingClientRect();
  t.style.top = `${r.bottom + window.scrollY + 6}px`;
  t.style.left = `${r.left + window.scrollX}px`;
  const overflow = r.left + t.offsetWidth - (window.innerWidth - 12);
  if (overflow > 0) t.style.left = `${Math.max(8, r.left + window.scrollX - overflow)}px`;
  tipFor = btn.dataset.term;
}
function hideTip() {
  if (tipEl) tipEl.style.display = "none";
  tipFor = null;
}
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".info");
  if (btn) {
    e.preventDefault();
    if (tipFor === btn.dataset.term) hideTip();
    else showTip(btn);
    return;
  }
  if (!e.target.closest(".tip")) hideTip();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") hideTip();
});
window.addEventListener("resize", hideTip);
window.addEventListener("scroll", hideTip, true);

// --- small helpers ---
function levelWord(level, label) {
  if (!level || level === "unclear") return "Unclear";
  return label ? `${level} · ${label}` : level;
}
function authorLine(authors) {
  if (!authors || authors.length === 0) return "";
  if (authors.length <= 3) return authors.join(", ");
  return authors.slice(0, 3).join(", ") + ", et al.";
}
function humanize(s) {
  if (!s) return "—";
  return String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// --- status helpers ---
function setBusy(on, msg) {
  $$("button.primary").forEach((b) => (b.disabled = on));
  if (on) {
    hide(resultEl);
    statusEl.className = "status loading";
    statusEl.innerHTML = `<span class="spinner"></span>${escapeHtml(msg || "Working…")}`;
    show(statusEl);
  }
}
function showError(msg) {
  hide(resultEl);
  statusEl.className = "status error";
  statusEl.textContent = msg;
  show(statusEl);
}
function clearOutput() {
  hide(statusEl);
  hide(resultsEl);
  hide(resultEl);
  hide(compareBar);
  hideTip();
}
