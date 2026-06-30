"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
const hide = (el) => el.classList.add("is-hidden");
const show = (el) => el.classList.remove("is-hidden");
const enc = (s) => encodeURIComponent(String(s == null ? "" : s));

const statusEl = $("#status");
const resultsEl = $("#results");
const resultEl = $("#result");
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
  key_points: "A plain-language recap assembled from the fields below — a quick gist, not a substitute for reading the study.",
  confidence:
    "How cleanly THIS TOOL could read the abstract (0–100%) — i.e. how sure the extraction is. It is NOT a measure of how strong or trustworthy the evidence itself is.",
  caution_notes:
    "Honest caveats about over-reading this card — e.g. observational design, unreported sample size, or abstract-only analysis.",
  preprint: "A paper posted before peer review (e.g. medRxiv/bioRxiv). Findings are unverified — treat with extra caution.",
  open_access:
    "A free, legal full-text copy is available (found via Unpaywall or PubMed Central). We never link to pirated copies.",
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
      <div class="result-body">
        <a class="result-title" href="${href}" target="_blank" rel="noopener">${escapeHtml(r.title || "Untitled")}</a>
        <div class="result-meta">${meta}</div>
        <div class="result-badges">${levelBadge}${flags.join("")}${types}</div>
      </div>
      <button class="btn primary small" data-source="${escapeHtml(r.source || "pubmed")}" data-id="${escapeHtml(r.article_id || "")}">Analyze</button>
    </div>`;
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
  if (d.is_preprint) src.push(`<span class="badge preprint">Preprint</span>${info("preprint")}`);
  if (d.oa_url) src.push(`<a class="badge oa" href="${escapeHtml(d.oa_url)}" target="_blank" rel="noopener">Free full text ↗</a>`);

  resultEl.innerHTML = `
    <h2>${escapeHtml(d.title || "Untitled article")}</h2>
    <p class="src">${src.join("")}</p>

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

    ${keyPoints(d)}
    ${refineControl(d)}

    <div class="fields">
      ${field("Sample size", d.sample_size != null ? `n = ${Number(d.sample_size).toLocaleString()}` : null, "sample_size", true)}
      ${field("Population", d.population, "population")}
      ${field("Intervention / exposure", d.intervention_or_exposure, "intervention")}
      ${field("Comparator", d.comparator, "comparator")}
    </div>

    ${block("Key finding", d.key_finding, "key_finding")}
    ${block("Primary outcome", d.primary_outcome, "outcome")}
    ${block("Limitations", d.limitations, "limitations")}
    ${articleDetails(d)}

    ${
      d.caution_notes && d.caution_notes.length
        ? `<div class="block"><div class="label">Cautions ${info("caution_notes")}</div>
             <ul class="cautions">${d.caution_notes
               .map((c) => `<li class="${/preprint/i.test(c) ? "preprint-note" : ""}">${escapeHtml(c)}</li>`)
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
  resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function refineControl(d) {
  if (d.extraction_method === "rules+llm") {
    return `<p class="ai-tag">Summary refined by AI · ${escapeHtml(d.extraction_method)}</p>`;
  }
  return `<div class="refine-row"><button id="btn-refine" class="btn ghost small" type="button">Refine with AI</button><span class="refine-hint">Rewrites the summary and limitations with Claude (needs an API key in .env).</span></div>`;
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
  return `<div class="field"><div class="label">${escapeHtml(label)} ${info(term)}</div>${inner}</div>`;
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
    ["confidence", "Confidence"],
    ["caution_notes", "Cautions"],
    ["limitations", "Limitations"],
    ["preprint", "Preprint"],
    ["open_access", "Open access"],
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
  hideTip();
}
