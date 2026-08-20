renderNav("generate");
renderFooter();

let inspirations = [];
let selectedStyles = [];
let currentGenerationId = null;
let favoritedIds = new Set();
let compareSelection = new Map(); // id -> name, capped at 6
let lastRenderedNames = null; // for "Back to results" after a comparison view
const MAX_COMPARE = 6;

// ---- inspiration chip input ----
const chipInputWrap = document.getElementById("chip-input");
const chipTextInput = document.getElementById("inspiration-text");

function renderChips() {
  chipInputWrap.querySelectorAll(".chip").forEach(c => c.remove());
  inspirations.forEach((val, idx) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `${escapeHtml(val)} <button type="button" aria-label="Remove ${escapeHtml(val)}">&times;</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      inspirations.splice(idx, 1);
      renderChips();
    });
    chipInputWrap.insertBefore(chip, chipTextInput);
  });
}

chipTextInput.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === ",") && chipTextInput.value.trim()) {
    e.preventDefault();
    inspirations.push(chipTextInput.value.trim());
    chipTextInput.value = "";
    renderChips();
  } else if (e.key === "Backspace" && !chipTextInput.value && inspirations.length) {
    inspirations.pop();
    renderChips();
  }
});

// ---- style pills ----
document.querySelectorAll(".style-pill").forEach(btn => {
  btn.addEventListener("click", () => {
    const style = btn.dataset.style;
    btn.classList.toggle("selected");
    if (selectedStyles.includes(style)) {
      selectedStyles = selectedStyles.filter(s => s !== style);
    } else {
      selectedStyles.push(style);
    }
  });
});

// ---- Advanced naming controls (collapsible) ----
const advancedToggle = document.getElementById("advanced-toggle");
const advancedPanel = document.getElementById("advanced-panel");
advancedToggle.addEventListener("click", () => {
  const open = advancedPanel.classList.toggle("open");
  advancedToggle.classList.toggle("open", open);
});

function openAdvancedPanel() {
  advancedPanel.classList.add("open");
  advancedToggle.classList.add("open");
}

// Generic chip-list field, reused for the six multi-value advanced inputs
// (brand personality, competitors, names liked/disliked, words to
// include/avoid). Same interaction pattern as the inspiration chip input.
function createChipList(wrapId, inputId) {
  const wrap = document.getElementById(wrapId);
  const input = document.getElementById(inputId);
  const items = [];

  function render() {
    wrap.querySelectorAll(".chip").forEach(c => c.remove());
    items.forEach((val, idx) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.innerHTML = `${escapeHtml(val)} <button type="button" aria-label="Remove ${escapeHtml(val)}">&times;</button>`;
      chip.querySelector("button").addEventListener("click", () => {
        items.splice(idx, 1);
        render();
      });
      wrap.insertBefore(chip, input);
    });
  }

  input.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === ",") && input.value.trim()) {
      e.preventDefault();
      items.push(input.value.trim());
      input.value = "";
      render();
    } else if (e.key === "Backspace" && !input.value && items.length) {
      items.pop();
      render();
    }
  });

  return {
    items,
    setAll(values) {
      items.length = 0;
      (values || []).forEach(v => v && items.push(v));
      render();
    },
  };
}

const advBrandPersonality = createChipList("adv-brand-personality-chips", "adv-brand-personality-text");
const advCompetitors = createChipList("adv-competitors-chips", "adv-competitors-text");
const advNamesLiked = createChipList("adv-names-liked-chips", "adv-names-liked-text");
const advNamesDisliked = createChipList("adv-names-disliked-chips", "adv-names-disliked-text");
const advWordsInclude = createChipList("adv-words-include-chips", "adv-words-include-text");
const advWordsAvoid = createChipList("adv-words-avoid-chips", "adv-words-avoid-text");

// Reads the advanced panel into the { advanced: {...} } shape the backend
// expects. Empty/untouched fields are simply omitted — the whole "advanced"
// object is optional, matching the backend's validation.
function collectAdvancedFields() {
  const advanced = {};
  const textField = (id, key) => {
    const val = document.getElementById(id).value.trim();
    if (val) advanced[key] = val;
  };
  textField("adv-naming-for", "naming_for");
  textField("adv-target-audience", "target_audience");
  textField("adv-target-market", "target_market");
  textField("adv-naming-language", "naming_language");
  textField("adv-name-length", "name_length");
  textField("adv-name-structure", "name_structure");
  textField("adv-desired-meaning", "desired_meaning");
  textField("adv-brand-story", "brand_story");
  textField("adv-future-expansion", "future_expansion");
  textField("adv-five-year-vision", "five_year_vision");
  textField("adv-domain-preference", "domain_preference");
  textField("adv-trademark-strategy", "trademark_strategy");

  if (advBrandPersonality.items.length) advanced.brand_personality = advBrandPersonality.items;
  if (advCompetitors.items.length) advanced.competitors = advCompetitors.items;
  if (advNamesLiked.items.length) advanced.names_liked = advNamesLiked.items;
  if (advNamesDisliked.items.length) advanced.names_disliked = advNamesDisliked.items;
  if (advWordsInclude.items.length) advanced.words_to_include = advWordsInclude.items;
  if (advWordsAvoid.items.length) advanced.words_to_avoid = advWordsAvoid.items;

  return advanced;
}

// ---- AI Brief Builder (optional helper — does not replace manual form) ----
const briefToggle = document.getElementById("brief-toggle");
const briefPanel = document.getElementById("brief-panel");
const briefBuildBtn = document.getElementById("brief-build-btn");
const briefMsg = document.getElementById("brief-msg");
const briefReview = document.getElementById("brief-review");

const BRIEF_FIELD_LABELS = {
  industry: "Industry",
  target_market: "Target market",
  audience: "Audience",
  positioning: "Positioning",
  personality: "Personality",
  naming_direction: "Naming direction",
  language: "Language",
  expansion: "Expansion",
};

briefToggle.addEventListener("click", () => {
  briefPanel.classList.toggle("open");
});

briefBuildBtn.addEventListener("click", async () => {
  if (!Auth.isLoggedIn()) { window.location.href = "login.html"; return; }
  const description = document.getElementById("brief-input").value.trim();
  briefMsg.classList.remove("show", "error");
  if (!description) {
    briefMsg.textContent = "Describe your idea first.";
    briefMsg.classList.add("show", "error");
    return;
  }

  briefBuildBtn.disabled = true;
  briefBuildBtn.textContent = "Building…";
  try {
    const { brief } = await Api.buildBrief({ description });
    renderBriefReview(brief, description);
  } catch (err) {
    briefMsg.textContent = err.message;
    briefMsg.classList.add("show", "error");
  } finally {
    briefBuildBtn.disabled = false;
    briefBuildBtn.textContent = "Build brief";
  }
});

function renderBriefReview(brief, sourceDescription) {
  briefReview.innerHTML = Object.entries(BRIEF_FIELD_LABELS).map(([key, label]) => `
    <div class="field">
      <label for="brief-field-${key}">${escapeHtml(label)}</label>
      <input type="text" id="brief-field-${key}" value="${escapeHtml(brief[key] || "")}">
    </div>
  `).join("") + `
    <div class="brief-review-actions">
      <button type="button" class="btn btn-primary btn-sm" id="brief-apply-btn">Apply to form</button>
      <button type="button" class="btn btn-ghost btn-sm" id="brief-discard-btn">Discard</button>
    </div>
  `;
  briefReview.classList.add("open");

  document.getElementById("brief-discard-btn").addEventListener("click", () => {
    briefReview.classList.remove("open");
    briefReview.innerHTML = "";
  });

  document.getElementById("brief-apply-btn").addEventListener("click", () => {
    const edited = {};
    Object.keys(BRIEF_FIELD_LABELS).forEach(key => {
      edited[key] = document.getElementById(`brief-field-${key}`).value.trim();
    });

    // Business description: keep the user's own free-form idea as the core
    // description the AI reasons from — it's the most information-dense
    // single field, and the structured brief fields layer on top of it.
    document.getElementById("business_description").value = sourceDescription;
    if (edited.industry && edited.industry !== "Not specified") {
      document.getElementById("industry").value = edited.industry;
    }

    openAdvancedPanel();
    if (edited.target_market && edited.target_market !== "Not specified") {
      document.getElementById("adv-target-market").value = edited.target_market;
    }
    if (edited.audience && edited.audience !== "Not specified") {
      document.getElementById("adv-target-audience").value = edited.audience;
    }
    if (edited.language && edited.language !== "Not specified") {
      document.getElementById("adv-naming-language").value = edited.language;
    }
    if (edited.naming_direction && edited.naming_direction !== "Not specified") {
      const meaningField = document.getElementById("adv-desired-meaning");
      meaningField.value = meaningField.value
        ? `${meaningField.value}; naming direction: ${edited.naming_direction}`
        : `Naming direction: ${edited.naming_direction}`;
    }
    if (edited.expansion && edited.expansion !== "Not specified") {
      document.getElementById("adv-future-expansion").value = edited.expansion;
    }
    if (edited.personality && edited.personality !== "Not specified") {
      const parts = edited.personality.split(/[+,/]/).map(s => s.trim()).filter(Boolean);
      advBrandPersonality.setAll(parts);
    }

    // Positioning often overlaps with the existing style pills (e.g.
    // "Premium + Trusted") — auto-select any pill it matches instead of
    // duplicating a second style concept.
    if (edited.positioning && edited.positioning !== "Not specified") {
      const positioningLower = edited.positioning.toLowerCase();
      document.querySelectorAll(".style-pill").forEach(pill => {
        const style = pill.dataset.style;
        if (positioningLower.includes(style.toLowerCase()) && !selectedStyles.includes(style)) {
          pill.classList.add("selected");
          selectedStyles.push(style);
        }
      });
    }

    briefPanel.classList.remove("open");
    briefReview.classList.remove("open");
    briefMsg.textContent = "Brief applied — review the form below before generating.";
    briefMsg.classList.remove("error");
    briefMsg.classList.add("show", "success");
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function riskBadgeClass(status) {
  if (status === "Low Risk") return "low";
  if (status === "Medium Risk") return "medium";
  if (status === "High Risk") return "high";
  if (status === "Search Failed") return "failed";
  return "review";
}

function domainBadgeClass(status) {
  if (status === "available") return "domain-available";
  if (status === "taken") return "domain-taken";
  return "domain-unavailable";
}

const TRADEMARK_DISCLAIMER = "Automated trademark screening is preliminary and is not legal advice. " +
  "Confirm availability through the relevant official trademark registry and qualified legal counsel " +
  "before adopting a brand.";

// Renders a set of generated names into the existing results area.
// Used both right after a fresh generation and when loading a past
// generation from the Recent Generations panel — same markup either way.
function renderNameCards(names, { headline, meta, disclaimer, generationId }) {
  currentGenerationId = generationId || null;
  compareSelection.clear();
  lastRenderedNames = { names, opts: { headline, meta, disclaimer, generationId } };
  const area = document.getElementById("results-area");

  const domainTlds = ["com", "in", "ai", "io", "co"];

  const cards = names.map(n => {
    const domainBadges = domainTlds
      .filter(t => n.domain_status && n.domain_status[t])
      .map(t => `<span class="badge ${domainBadgeClass(n.domain_status[t])}">.${t} ${n.domain_status[t]}</span>`)
      .join("");

    return `
      <div class="specimen" data-name-id="${n.id}">
        <div class="sp-rank">№ ${String(n.rank).padStart(2, "0")}</div>
        <div class="sp-name">${escapeHtml(n.name)}</div>
        <div class="sp-inspiration">${escapeHtml(n.inspiration_used || "—")}</div>
        <p class="sp-meaning">${escapeHtml(n.meaning || "")}</p>
        <div class="sp-score">Brandability ${Math.round(n.brandability_score || 0)}/100</div>
        <div class="sp-badges">
          <span class="badge ${riskBadgeClass(n.trademark_status)}">${escapeHtml(n.trademark_status)}</span>
          ${domainBadges}
        </div>
        <div class="sp-actions">
          <button class="icon-btn copy-btn" data-name="${escapeHtml(n.name)}">Copy</button>
          <button class="icon-btn fav-btn" data-id="${n.id}">${favoritedIds.has(n.id) ? "★ Saved" : "☆ Save"}</button>
          <button class="icon-btn intel-btn" data-id="${n.id}">Intelligence</button>
          <button class="icon-btn refine-btn" data-id="${n.id}" data-name="${escapeHtml(n.name)}">Refine</button>
          <button class="icon-btn logo-btn" data-id="${n.id}">Logo</button>
        </div>
        <label class="compare-select"><input type="checkbox" class="compare-checkbox" data-id="${n.id}" data-name="${escapeHtml(n.name)}"> Add to comparison</label>
        <div class="intel-panel" id="intel-panel-${n.id}"></div>
        <div class="refine-panel" id="refine-panel-${n.id}"></div>
        <div class="logo-panel" id="logo-panel-${n.id}"></div>
      </div>`;
  }).join("");

  area.innerHTML = `
    <div class="results-head">
      <h2>${escapeHtml(headline)}</h2>
      <span class="results-meta">${escapeHtml(meta)}</span>
    </div>
    <div class="results-grid">${cards}</div>
    <p class="disclaimer">${escapeHtml(disclaimer)}</p>
    <div class="compare-bar" id="compare-bar">
      <span id="compare-bar-text"></span>
      <div>
        <button type="button" class="btn btn-ghost btn-sm" id="compare-clear-btn">Clear</button>
        <button type="button" class="btn btn-primary btn-sm" id="compare-go-btn">Compare selected</button>
      </div>
    </div>
  `;

  area.querySelectorAll(".copy-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(btn.dataset.name);
      const original = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => { btn.textContent = original; }, 1200);
    });
  });

  area.querySelectorAll(".fav-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!Auth.isLoggedIn()) { window.location.href = "login.html"; return; }
      const id = btn.dataset.id;
      try {
        if (favoritedIds.has(id)) {
          // Not tracking favorite row id here for simplicity of the demo UI;
          // full remove flow lives on the Favorites page.
          btn.textContent = "★ Saved";
        } else {
          await Api.addFavorite(id);
          favoritedIds.add(id);
          btn.textContent = "★ Saved";
          btn.classList.add("active");
        }
      } catch (e) {
        alert(e.message);
      }
    });
  });

  area.querySelectorAll(".intel-btn").forEach(btn => {
    btn.addEventListener("click", () => toggleIntelligencePanel(btn));
  });

  area.querySelectorAll(".refine-btn").forEach(btn => {
    btn.addEventListener("click", () => toggleRefinePanel(btn));
  });

  area.querySelectorAll(".logo-btn").forEach(btn => {
    btn.addEventListener("click", () => toggleLogoPanel(btn));
  });

  area.querySelectorAll(".compare-checkbox").forEach(cb => {
    cb.addEventListener("change", () => {
      if (cb.checked) {
        if (compareSelection.size >= MAX_COMPARE) {
          cb.checked = false;
          alert(`You can compare up to ${MAX_COMPARE} names at a time.`);
          return;
        }
        compareSelection.set(cb.dataset.id, cb.dataset.name);
      } else {
        compareSelection.delete(cb.dataset.id);
      }
      updateCompareBar();
    });
  });

  document.getElementById("compare-clear-btn").addEventListener("click", () => {
    compareSelection.clear();
    area.querySelectorAll(".compare-checkbox").forEach(cb => { cb.checked = false; });
    updateCompareBar();
  });

  document.getElementById("compare-go-btn").addEventListener("click", async () => {
    const ids = Array.from(compareSelection.keys());
    const goBtn = document.getElementById("compare-go-btn");
    goBtn.disabled = true;
    goBtn.textContent = "Comparing…";
    try {
      const { names: compared } = await Api.compareNames(ids);
      renderComparisonView(compared);
    } catch (e) {
      alert(e.message);
    } finally {
      goBtn.disabled = false;
      goBtn.textContent = "Compare selected";
    }
  });

  updateCompareBar();
}

function updateCompareBar() {
  const bar = document.getElementById("compare-bar");
  if (!bar) return;
  const count = compareSelection.size;
  bar.classList.toggle("show", count >= 2);
  document.getElementById("compare-bar-text").textContent =
    `${count} name${count === 1 ? "" : "s"} selected for comparison`;
}

// ---- Brand Intelligence (per-name AI heuristic panel) ----
async function toggleIntelligencePanel(btn) {
  const id = btn.dataset.id;
  const panel = document.getElementById(`intel-panel-${id}`);
  if (panel.classList.contains("open")) {
    panel.classList.remove("open");
    return;
  }
  panel.classList.add("open");
  if (panel.dataset.loaded) return; // already fetched — just re-show

  panel.innerHTML = `<p class="intel-rationale">Analyzing name…</p>`;
  try {
    const data = await Api.nameIntelligence(id);
    panel.innerHTML = renderIntelligenceHtml(data);
    panel.dataset.loaded = "1";
  } catch (e) {
    panel.innerHTML = `<p class="intel-rationale">${escapeHtml(e.message)}</p>`;
  }
}

function renderIntelligenceHtml(data) {
  const scores = data.ai_intelligence;
  const scoreLabels = {
    memorability: "Memorability",
    pronunciation: "Pronunciation",
    distinctiveness: "Distinctiveness",
    premium_feel: "Premium feel",
    global_usability: "Global usability",
    domain_potential: "Domain potential",
  };
  const scoreRows = Object.entries(scoreLabels).map(([key, label]) => `
    <div class="intel-score">
      <span class="intel-score-name">${label}</span>
      <span class="intel-score-val">${Math.round(scores[key] ?? 0)}/100</span>
    </div>
  `).join("");

  return `
    <p class="intel-label">${escapeHtml(scores.label)}</p>
    <div class="intel-grid">${scoreRows}</div>
    ${scores.rationale ? `<p class="intel-rationale">${escapeHtml(scores.rationale)}</p>` : ""}
    ${scores.existing_brand_signals ? `<p class="intel-rationale"><strong>Existing brand signals:</strong> ${escapeHtml(scores.existing_brand_signals)}</p>` : ""}
    <div class="intel-real">
      <p class="intel-label">${escapeHtml(data.real_data.label)}</p>
      <div class="intel-score"><span class="intel-score-name">Trademark screening</span><span class="intel-score-val">${escapeHtml(data.real_data.trademark_status)}</span></div>
    </div>
  `;
}

// ---- Name Refinement ----
const REFINE_DIRECTIONS = [
  "More Premium", "More Modern", "More Traditional", "More Indian", "More Global",
  "Shorter", "More Playful", "More Technical", "More Unique",
];

function toggleRefinePanel(btn) {
  const id = btn.dataset.id;
  const panel = document.getElementById(`refine-panel-${id}`);
  if (panel.classList.contains("open")) {
    panel.classList.remove("open");
    return;
  }
  panel.classList.add("open");
  if (!panel.dataset.initialized) {
    renderRefineDirectionPicker(panel, id);
    panel.dataset.initialized = "1";
  }
}

function renderRefineDirectionPicker(panel, nameId) {
  panel.innerHTML = `
    <p class="intel-label">Refine in a direction</p>
    <div class="refine-directions">
      ${REFINE_DIRECTIONS.map(d => `<button type="button" class="refine-direction-btn" data-direction="${escapeHtml(d)}">${escapeHtml(d)}</button>`).join("")}
    </div>
    <div class="refine-results" id="refine-results-${nameId}"></div>
  `;
  panel.querySelectorAll(".refine-direction-btn").forEach(dirBtn => {
    dirBtn.addEventListener("click", () => runRefinement(nameId, dirBtn.dataset.direction, panel));
  });
}

async function runRefinement(nameId, direction, panel) {
  const resultsEl = document.getElementById(`refine-results-${nameId}`);
  resultsEl.innerHTML = `<p class="intel-rationale">Refining this name…</p>`;
  panel.querySelectorAll(".refine-direction-btn").forEach(b => {
    b.disabled = true;
    b.classList.toggle("active", b.dataset.direction === direction);
  });

  try {
    const data = await Api.refineName(nameId, direction);
    resultsEl.innerHTML = data.names.map(n => renderRefineResultHtml(n)).join("")
      + `<p class="disclaimer" style="margin-top:12px;">${escapeHtml(data.trademark_disclaimer)}</p>`;
    resultsEl.querySelectorAll(".copy-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        navigator.clipboard.writeText(btn.dataset.name);
        const original = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(() => { btn.textContent = original; }, 1200);
      });
    });
  } catch (e) {
    resultsEl.innerHTML = `<p class="intel-rationale">${escapeHtml(e.message)}</p>`;
  } finally {
    panel.querySelectorAll(".refine-direction-btn").forEach(b => { b.disabled = false; });
  }
}

function renderRefineResultHtml(n) {
  const domainTlds = ["com", "in", "ai", "io", "co"];
  const domainBadges = domainTlds
    .filter(t => n.domain_status && n.domain_status[t])
    .map(t => `<span class="badge ${domainBadgeClass(n.domain_status[t])}">.${t} ${n.domain_status[t]}</span>`)
    .join("");
  return `
    <div class="refine-result">
      <div class="rr-name">${escapeHtml(n.name)}</div>
      <p class="rr-meaning">${escapeHtml(n.meaning)}</p>
      <p class="rr-why"><strong>Why this refinement:</strong> ${escapeHtml(n.why_refined)}</p>
      <div class="rr-meta">
        <span class="badge ${riskBadgeClass(n.trademark_status)}">${escapeHtml(n.trademark_status)}</span>
        ${domainBadges}
        <span class="rr-score">Brandability ${Math.round(n.brandability_score || 0)}/100 · Inspiration: ${escapeHtml(n.inspiration_used || "None")}</span>
      </div>
      <button type="button" class="icon-btn copy-btn" data-name="${escapeHtml(n.name)}" style="width:100%;">Copy this name</button>
    </div>
  `;
}

// ---- AI Logo Generator ----
const LOGO_TYPES = ["Wordmark", "Lettermark", "Symbol", "Abstract", "Mascot", "Combination"];

function toggleLogoPanel(btn) {
  const id = btn.dataset.id;
  const panel = document.getElementById(`logo-panel-${id}`);
  if (panel.classList.contains("open")) {
    panel.classList.remove("open");
    return;
  }
  panel.classList.add("open");
  if (!panel.dataset.initialized) {
    renderLogoForm(panel, id);
    panel.dataset.initialized = "1";
  }
}

function renderLogoForm(panel, nameId) {
  panel.innerHTML = `
    <p class="intel-label">Generate concept logos</p>
    <div class="refine-directions" id="logo-type-pills-${nameId}">
      ${LOGO_TYPES.map((t, i) => `<button type="button" class="refine-direction-btn logo-type-pill" data-type="${escapeHtml(t)}">${escapeHtml(t)}</button>`).join("")}
    </div>
    <div class="logo-mini-fields mt-24">
      <input type="text" id="logo-style-${nameId}" placeholder="Style (optional) — e.g. minimal, hand-drawn, geometric">
      <input type="text" id="logo-color-${nameId}" placeholder="Color preference (optional) — e.g. deep blue and gold">
    </div>
    <button type="button" class="btn btn-primary btn-sm" id="logo-generate-btn-${nameId}" disabled>Select a logo type first</button>
    <div class="logo-results" id="logo-results-${nameId}"></div>
  `;

  let selectedType = null;
  const genBtn = document.getElementById(`logo-generate-btn-${nameId}`);

  panel.querySelectorAll(".logo-type-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      panel.querySelectorAll(".logo-type-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      selectedType = pill.dataset.type;
      genBtn.disabled = false;
      genBtn.textContent = `Generate ${selectedType} logos`;
    });
  });

  genBtn.addEventListener("click", () => runLogoGeneration(nameId, selectedType, panel));
}

async function runLogoGeneration(nameId, logoType, panel) {
  const resultsEl = document.getElementById(`logo-results-${nameId}`);
  const genBtn = document.getElementById(`logo-generate-btn-${nameId}`);
  const style = document.getElementById(`logo-style-${nameId}`).value.trim();
  const color = document.getElementById(`logo-color-${nameId}`).value.trim();

  resultsEl.innerHTML = `<p class="intel-rationale">Generating logo concepts…</p>`;
  genBtn.disabled = true;
  const originalLabel = genBtn.textContent;
  genBtn.textContent = "Generating…";

  try {
    const data = await Api.generateLogo(nameId, {
      logo_type: logoType,
      style,
      color_preference: color,
    });
    resultsEl.innerHTML = `
      <div class="logo-grid">
        ${data.images.map((src, i) => `
          <div class="logo-thumb">
            <img src="${src}" alt="${escapeHtml(data.name)} logo concept ${i + 1}">
            <a href="${src}" download="${escapeHtml(data.name.replace(/\s+/g, "-").toLowerCase())}-logo-${i + 1}.png">Download</a>
            <button type="button" class="icon-btn save-logo-btn" data-index="${i}" style="width:100%; margin-top:6px;">Save to workspace</button>
          </div>
        `).join("")}
      </div>
      <p class="intel-rationale mt-24">${escapeHtml(data.note)}</p>
    `;
    resultsEl.querySelectorAll(".save-logo-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!Auth.isLoggedIn()) { window.location.href = "login.html"; return; }
        const src = data.images[Number(btn.dataset.index)];
        btn.disabled = true;
        const original = btn.textContent;
        btn.textContent = "Saving…";
        try {
          await Api.addFavorite(nameId, { selected_logo: src });
          btn.textContent = "Saved to workspace";
        } catch (e) {
          btn.textContent = original;
          btn.disabled = false;
          alert(e.message);
        }
      });
    });
  } catch (e) {
    resultsEl.innerHTML = `<p class="intel-rationale">${escapeHtml(e.message)}</p>`;
  } finally {
    genBtn.disabled = false;
    genBtn.textContent = originalLabel;
  }
}

// ---- Name Comparison ----
function renderComparisonView(compared) {
  const area = document.getElementById("results-area");
  const dims = [
    ["Brandability", n => n.brandability_score != null ? `${Math.round(n.brandability_score)}/100` : "—"],
    ["Memorability", n => n.ai_intelligence ? `${Math.round(n.ai_intelligence.memorability)}/100` : "—"],
    ["Pronunciation", n => n.ai_intelligence ? `${Math.round(n.ai_intelligence.pronunciation)}/100` : "—"],
    ["Distinctiveness", n => n.ai_intelligence ? `${Math.round(n.ai_intelligence.distinctiveness)}/100` : "—"],
    ["Global suitability", n => n.ai_intelligence ? `${Math.round(n.ai_intelligence.global_usability)}/100` : "—"],
    ["Trademark risk", n => n.trademark_status || "—"],
    ["Domain (.com)", n => (n.domain_status && n.domain_status.com) || "—"],
  ];

  const rows = dims.map(([label, fn]) => `
    <tr><th>${escapeHtml(label)}</th>${compared.map(n => `<td>${escapeHtml(String(fn(n)))}</td>`).join("")}</tr>
  `).join("");

  const anyIntelError = compared.some(n => n.ai_intelligence_error);

  area.innerHTML = `
    <div class="results-head">
      <h2>Comparing ${compared.length} names</h2>
      <span class="results-meta">Brandability is from generation; other scores are AI-derived heuristic estimates</span>
    </div>
    <div class="card compare-table-wrap">
      <table class="compare-table">
        <thead><tr><th></th>${compared.map(n => `<td class="compare-name-cell">${escapeHtml(n.name)}</td>`).join("")}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    ${anyIntelError ? `<p class="disclaimer">Brand Intelligence wasn't available for one or more names — configure GEMINI_API_KEY on the server to enable it.</p>` : ""}
    <p class="disclaimer">${escapeHtml(TRADEMARK_DISCLAIMER)}</p>
    <button type="button" class="btn btn-ghost btn-sm mt-24" id="back-to-results-btn">← Back to results</button>
  `;

  document.getElementById("back-to-results-btn").addEventListener("click", () => {
    if (lastRenderedNames) {
      renderNameCards(lastRenderedNames.names, lastRenderedNames.opts);
    }
  });
}



function renderResults(data) {
  const j = data.trademark_jurisdiction;
  const jurisdictionNote = j && j.label && j.label !== "Not specified" ? ` · Trademark jurisdiction: ${j.label}` : "";
  renderNameCards(data.names, {
    headline: `Your top ${data.returned_count} names`,
    meta: `pool: ${data.candidate_pool_size} candidates screened${jurisdictionNote}`,
    disclaimer: data.trademark_disclaimer,
    generationId: data.generation_id,
  });
}

function renderHistoryDetail(detail) {
  if (detail.status !== "completed" || !detail.names || !detail.names.length) {
    const area = document.getElementById("results-area");
    const label = detail.status === "failed" ? "This generation failed and has no names to show." : "This generation is still in progress.";
    area.innerHTML = `<div class="state-box"><h3>${escapeHtml(detail.business_description).slice(0, 60)}</h3><p>${label}</p></div>`;
    return;
  }
  const j = detail.trademark_jurisdiction;
  const jurisdictionNote = j && j.label && j.label !== "Not specified" ? ` · Trademark jurisdiction: ${j.label}` : "";
  renderNameCards(detail.names, {
    headline: `${detail.names.length} names from this brief`,
    meta: `${new Date(detail.created_at).toLocaleString()}${jurisdictionNote}`,
    disclaimer: TRADEMARK_DISCLAIMER,
    generationId: detail.id,
  });
}

// ---- Recent Generations ----
async function loadRecentGenerations() {
  const card = document.getElementById("recent-generations-card");
  const list = document.getElementById("recent-gen-list");
  if (!Auth.isLoggedIn()) return;

  try {
    const { generations } = await Api.history();
    if (!generations.length) return; // keep the card hidden — nothing to show yet

    card.style.display = "block";
    list.innerHTML = generations.slice(0, 6).map(g => `
      <button type="button" class="recent-gen-item" data-id="${g.id}">
        <div class="rg-desc">${escapeHtml(g.business_description)}</div>
        <div class="rg-meta">
          <span class="pill-status ${g.status}">${g.status === "completed" ? "Completed" : g.status === "failed" ? "Failed" : "Generating..."}</span>
          <span class="rg-date">${new Date(g.created_at).toLocaleDateString()}</span>
        </div>
      </button>
    `).join("");

    list.querySelectorAll(".recent-gen-item").forEach(item => {
      item.addEventListener("click", async () => {
        list.querySelectorAll(".recent-gen-item").forEach(i => i.classList.remove("active"));
        item.classList.add("active");
        const area = document.getElementById("results-area");
        area.innerHTML = `<div class="state-box"><div class="spinner"></div></div>`;
        try {
          const detail = await Api.historyDetail(item.dataset.id);
          renderHistoryDetail(detail);
        } catch (e) {
          area.innerHTML = `<div class="state-box"><h3>Couldn't load this generation</h3><p>${escapeHtml(e.message)}</p></div>`;
        }
      });
    });
  } catch (e) {
    // Recent Generations is a convenience panel — fail silently and just
    // keep it hidden rather than surfacing an error above the main form.
  }
}

// ---- Generation-in-progress animation ----
// This is a client-side pacing animation, not a live progress feed from the
// backend (the API is a single request/response, not a stream). It never
// asserts that an individual stage — e.g. trademark screening — has actually
// completed; it only paces through the conceptual stages of the pipeline
// while the request is in flight.
const GENERATION_STAGES = [
  "Understanding your business",
  "Exploring naming concepts",
  "Generating candidates",
  "Filtering duplicates",
  "Ranking names",
  "Screening brand risks",
  "Building your shortlist",
];

function startGenerationAnimation() {
  const area = document.getElementById("results-area");
  area.innerHTML = `
    <div class="state-box">
      <div class="spinner"></div>
      <h3>Generating and screening names…</h3>
      <p>This runs the full pipeline: generation, filtering, trademark and domain screening.</p>
      <ol class="gen-stages" id="gen-stages">
        ${GENERATION_STAGES.map(s => `<li class="gen-stage"><span class="gs-dot"></span>${escapeHtml(s)}</li>`).join("")}
      </ol>
    </div>`;

  const stageEls = area.querySelectorAll(".gen-stage");
  let idx = 0;
  const setStage = (i) => {
    stageEls.forEach((el, j) => {
      el.classList.toggle("done", j < i);
      el.classList.toggle("active", j === i);
    });
  };
  setStage(0);

  const interval = setInterval(() => {
    idx = Math.min(idx + 1, stageEls.length - 1);
    setStage(idx);
    if (idx === stageEls.length - 1) clearInterval(interval);
  }, 1100);

  return () => clearInterval(interval);
}



document.getElementById("generate-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!Auth.isLoggedIn()) {
    window.location.href = "login.html";
    return;
  }

  const businessDescription = document.getElementById("business_description").value.trim();
  const msg = document.getElementById("form-msg");
  msg.classList.remove("show", "error");

  if (!businessDescription) {
    msg.textContent = "Business description is required.";
    msg.classList.add("show", "error");
    return;
  }

  const btn = document.getElementById("generate-btn");
  btn.disabled = true;
  btn.textContent = "Generating…";

  const stopAnimation = startGenerationAnimation();

  try {
    const data = await Api.generate({
      business_description: businessDescription,
      industry: document.getElementById("industry").value.trim(),
      inspirations,
      style_tags: selectedStyles,
      advanced: collectAdvancedFields(),
    });
    stopAnimation();
    renderResults(data);
    loadRecentGenerations();
  } catch (err) {
    stopAnimation();
    const area = document.getElementById("results-area");
    area.innerHTML = `<div class="state-box"><h3>Generation failed</h3><p>${escapeHtml(err.message)}</p></div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate 25 names";
  }
});

loadRecentGenerations();
