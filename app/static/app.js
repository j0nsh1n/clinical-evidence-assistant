"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

const statusEl = $("#status");
const resultEl = $("#result");

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// --- tab switching ---
$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const mode = tab.dataset.mode;
    $$(".tab").forEach((t) => t.classList.toggle("is-active", t === tab));
    $$(".mode").forEach((m) => m.classList.toggle("is-hidden", m.dataset.mode !== mode));
    clearOutput();
  });
});

// --- example filler ---
$("#btn-example").addEventListener("click", () => {
  $("#title").value =
    "A randomized controlled trial of a new inhaled therapy in adults with asthma";
  $("#abstract").value =
    "In this randomized, double-blind, placebo-controlled trial, a total of 512 adults " +
    "with moderate asthma were enrolled and randomized to the inhaled therapy or placebo. " +
    "The primary outcome was the annual rate of asthma exacerbations over 12 months. " +
    "The treatment was generally well tolerated. Compared with placebo, the inhaled therapy " +
    "significantly reduced the annual rate of asthma exacerbations.";
});

// --- form submits ---
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

async function analyze(payload) {
  setLoading(true);
  try {
    const res = await fetch("/api/evidence/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new HttpError(res.status, body.detail || res.statusText);
    }
    render(await res.json());
  } catch (err) {
    showError(friendlyError(err));
  } finally {
    setLoading(false);
  }
}

function friendlyError(err) {
  if (err instanceof HttpError) {
    if (err.status === 404)
      return "No PubMed article found for that PMID. Check the number and try again.";
    if (err.status === 502)
      return "Couldn't reach PubMed right now. Try again, or paste the abstract instead.";
    if (err.status === 422) return err.message || "Provide a PMID or an abstract to analyze.";
    return `Analysis failed (${err.status}): ${err.message}`;
  }
  return "Network error — is the server running? Try again.";
}

// --- rendering ---
function render(d) {
  statusEl.classList.add("is-hidden");
  const level = d.evidence_level || "unclear";
  const conf = Math.round((d.confidence_score || 0) * 100);

  const source =
    d.source_database === "pubmed" && d.article_id
      ? `<a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(d.article_id)}/" target="_blank" rel="noopener">PMID ${escapeHtml(d.article_id)} ↗</a>`
      : escapeHtml(d.source_database || "manual input");

  resultEl.innerHTML = `
    <h2>${escapeHtml(d.title || "Untitled article")}</h2>
    <p class="src">${source}</p>

    <div class="badges">
      <span class="badge level level-${escapeHtml(level)}">Evidence level ${escapeHtml(levelLabel(level, d.evidence_label))}</span>
      <span class="badge"><span class="k">Design</span> ${escapeHtml(humanize(d.study_design))}</span>
      <span class="badge"><span class="k">Question</span> ${escapeHtml(humanize(d.clinical_question_type))}</span>
    </div>

    <div class="fields">
      ${field("Sample size", d.sample_size != null ? `n = ${d.sample_size}` : null)}
      ${field("Population", d.population)}
      ${field("Intervention / exposure", d.intervention_or_exposure)}
      ${field("Comparator", d.comparator)}
    </div>

    ${block("Key finding", d.key_finding)}
    ${block("Primary outcome", d.primary_outcome)}

    ${
      d.caution_notes && d.caution_notes.length
        ? `<div class="block">
             <div class="label">Cautions</div>
             <ul class="cautions">${d.caution_notes.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>
           </div>`
        : ""
    }

    <div class="block">
      <div class="label">Confidence (${escapeHtml(d.extraction_method || "rules")} estimate)</div>
      <div class="confidence">
        <span class="bar"><i style="width:${conf}%"></i></span>
        <span class="pct">${conf}%</span>
      </div>
    </div>
  `;
  resultEl.classList.remove("is-hidden");
}

function field(label, value) {
  const hasValue = value != null && String(value).trim() !== "";
  const inner = hasValue
    ? `<div class="value">${escapeHtml(value)}</div>`
    : `<div class="value empty">not reported</div>`;
  return `<div class="field"><div class="label">${label}</div>${inner}</div>`;
}

function block(label, value) {
  if (value == null || String(value).trim() === "") return "";
  return `<div class="block"><div class="label">${label}</div><p>${escapeHtml(value)}</p></div>`;
}

function levelLabel(level, label) {
  if (level === "unclear") return "Unclear";
  return label ? `${level} · ${label}` : level;
}

function humanize(s) {
  if (!s) return "—";
  return String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// --- status helpers ---
function setLoading(on) {
  $$("button.primary").forEach((b) => (b.disabled = on));
  if (on) {
    resultEl.classList.add("is-hidden");
    statusEl.className = "status loading";
    statusEl.innerHTML = `<span class="spinner"></span>Analyzing abstract…`;
    statusEl.classList.remove("is-hidden");
  }
}

function showError(msg) {
  resultEl.classList.add("is-hidden");
  statusEl.className = "status error";
  statusEl.textContent = msg;
  statusEl.classList.remove("is-hidden");
}

function clearOutput() {
  statusEl.classList.add("is-hidden");
  resultEl.classList.add("is-hidden");
}
