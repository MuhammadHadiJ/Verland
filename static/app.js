// ---------------------------------------------------------------------------
// Field definitions
// ---------------------------------------------------------------------------
const propertySpecificFields = [
  ["load_shedding",  "Load shedding"],
  ["water_supply",   "Water supply"],
  ["gas",            "Gas availability"],
  ["maintenance",    "Maintenance quality"],
  ["standby_power",  "Standby power (building)"],
  ["elevator",       "Elevator"],
  ["parking",        "Parking"],
];

const neighborhoodFields = [
  ["security",     "Street security"],
  ["noise",        "Background noise"],
  ["traffic",      "Traffic congestion"],
  ["cleanliness",  "Cleanliness"],
  ["flooding",     "Rain flooding"],
];

const allFields = [...propertySpecificFields, ...neighborhoodFields];

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  user:                 null,
  properties:           [],
  selectedId:           null,
  selectedLocation:     null,
  selectedPlace:        null,
  neighbourhoodPreview: null,
};

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------
const detailPanel          = document.querySelector("#detailPanel");
const resultsWrapper       = document.querySelector("#resultsWrapper");
const searchForm           = document.querySelector("#searchForm");
const searchInput          = document.querySelector("#searchInput");
const cityInput            = document.querySelector("#cityInput");
const autocompleteDropdown = document.querySelector("#autocompleteDropdown");
const hero                 = document.querySelector("#hero");
const heroSearchForm       = document.querySelector("#heroSearchForm");
const heroSearchInput      = document.querySelector("#heroSearchInput");
const heroCityInput        = document.querySelector("#heroCityInput");
const heroDropdown         = document.querySelector("#heroAutocompleteDropdown");
const reviewDialog         = document.querySelector("#reviewDialog");
const reviewFormContainer  = document.querySelector("#reviewFormContainer");
const closeReviewDialog    = document.querySelector("#closeReviewDialog");
const confirmDialog        = document.querySelector("#confirmDialog");
const confirmDeleteBtn     = document.querySelector("#confirmDeleteBtn");
const cancelDeleteBtn      = document.querySelector("#cancelDeleteBtn");
const closeConfirmDialog   = document.querySelector("#closeConfirmDialog");
const confirmDeleteError   = document.querySelector("#confirmDeleteError");

// ---------------------------------------------------------------------------
// Hero exit
// ---------------------------------------------------------------------------
let heroExited = false;

function exitHero() {
  if (heroExited) return;
  heroExited = true;
  hero.classList.add("hidden");
  resultsWrapper.classList.add("visible");
}

// ---------------------------------------------------------------------------
// Theme toggle
// ---------------------------------------------------------------------------
const THEME_ICONS = {
  light:  '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
  dark:   '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
  system: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
};
const THEME_CYCLE = { system: "dark", dark: "light", light: "system" };

function updateThemeButton() {
  const pref = document.documentElement.getAttribute("data-theme-pref") || "system";
  document.querySelector("#themeIcon").innerHTML = THEME_ICONS[pref];
  document.querySelector("#themeLabel").textContent = pref.charAt(0).toUpperCase() + pref.slice(1);
}

document.querySelector("#themeToggle").addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme-pref") || "system";
  const next    = THEME_CYCLE[current];
  const isDark  = next === "dark" || (next === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
  document.documentElement.setAttribute("data-theme-pref", next);
  localStorage.setItem("theme", next);
  updateThemeButton();
});

updateThemeButton();

// ---------------------------------------------------------------------------
// Dialog handlers
// ---------------------------------------------------------------------------
closeReviewDialog.addEventListener("click", () => reviewDialog.close());
closeConfirmDialog.addEventListener("click", () => confirmDialog.close());
cancelDeleteBtn.addEventListener("click", () => confirmDialog.close());
confirmDialog.addEventListener("close", () => {
  pendingDeleteId = null;
  confirmDeleteError.textContent = "";
  confirmDeleteBtn.textContent = "Delete";
  confirmDeleteBtn.disabled = false;
});

let pendingDeleteId = null;

confirmDeleteBtn.addEventListener("click", async () => {
  if (!pendingDeleteId) return;
  confirmDeleteBtn.textContent = "Deleting…";
  confirmDeleteBtn.disabled = true;
  confirmDeleteError.textContent = "";
  try {
    const result = await api(`/api/reviews/${pendingDeleteId}`, { method: "DELETE" });
    const saved = result.property;
    state.properties = state.properties.map((p) => p.id === saved.id ? saved : p);
    confirmDialog.close();
    renderDetail();
  } catch (err) {
    confirmDeleteBtn.textContent = "Delete";
    confirmDeleteBtn.disabled = false;
    confirmDeleteError.textContent = err.message;
  }
});

detailPanel.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-action='delete-start']");
  if (!btn) return;
  pendingDeleteId = btn.dataset.reviewId;
  confirmDeleteError.textContent = "";
  confirmDeleteBtn.textContent = "Delete";
  confirmDeleteBtn.disabled = false;
  confirmDialog.showModal();
});

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json" };
  const response = await fetch(path, { headers, ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Something went wrong");
  return body;
}

// ---------------------------------------------------------------------------
// Autocomplete — shared setup
// ---------------------------------------------------------------------------
function setupAutocomplete(inputEl, dropdownEl, getCityValue, onSelect) {
  let timer;

  inputEl.addEventListener("input", () => {
    clearTimeout(timer);
    const q = inputEl.value.trim();
    if (q.length < 3) { dropdownEl.hidden = true; return; }
    timer = setTimeout(async () => {
      try {
        const city = getCityValue();
        const result = await api(`/api/location-search?${new URLSearchParams({ q, city })}`);
        renderDropdown(result.places, dropdownEl, onSelect);
      } catch {}
    }, 300);
  });

  document.addEventListener("click", (e) => {
    if (!inputEl.closest("form").contains(e.target)) dropdownEl.hidden = true;
  });
}

function renderDropdown(places, dropdownEl, onSelect) {
  if (!places?.length) { dropdownEl.hidden = true; return; }
  dropdownEl.innerHTML = "";
  dropdownEl.hidden = false;

  for (const place of places) {
    const btn = document.createElement("button");
    btn.className = "autocomplete-item";
    btn.type = "button";
    btn.innerHTML = `<strong>${escapeHtml(place.name)}</strong><span>${escapeHtml(place.display_name)}</span>`;
    btn.addEventListener("click", () => { dropdownEl.hidden = true; onSelect(place); });
    dropdownEl.append(btn);
  }
}

// Hero autocomplete
setupAutocomplete(
  heroSearchInput,
  heroDropdown,
  () => heroCityInput.value,
  (place) => {
    heroSearchInput.value = place.display_name;
    searchInput.value     = place.display_name;
    cityInput.value       = heroCityInput.value;
    exitHero();
    selectLocation({ lat: Number(place.lat), lng: Number(place.lng) }).then(() => {
      state.selectedPlace = place;
      renderDetail();
    });
  }
);

// Header autocomplete
setupAutocomplete(
  searchInput,
  autocompleteDropdown,
  () => cityInput.value,
  (place) => {
    searchInput.value = place.display_name;
    autocompleteDropdown.hidden = true;
    selectLocation({ lat: Number(place.lat), lng: Number(place.lng) }).then(() => {
      state.selectedPlace = place;
      renderDetail();
    });
  }
);

// ---------------------------------------------------------------------------
// Hero form submit
// ---------------------------------------------------------------------------
heroSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  heroDropdown.hidden = true;
  searchInput.value   = heroSearchInput.value;
  cityInput.value     = heroCityInput.value;
  exitHero();
  loadProperties();
});

// Popular city chips
document.querySelectorAll(".city-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const city = chip.dataset.city;
    heroCityInput.value = city;
    cityInput.value     = city;
    heroSearchInput.value = "";
    searchInput.value     = "";
    exitHero();
    loadProperties();
  });
});

// Header form submit
searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  autocompleteDropdown.hidden = true;
  state.selectedLocation = null;
  state.selectedPlace    = null;
  state.selectedId       = null;
  state.neighbourhoodPreview = null;
  loadProperties();
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
async function init() {
  try {
    const me = await api("/api/auth/me");
    state.user = me;
  } catch (_) {
    state.user = null;
  }
  renderHeaderAuth();

  // Restore pre-auth state after OAuth redirect
  const saved = localStorage.getItem("preAuthState");
  if (saved) {
    localStorage.removeItem("preAuthState");
    if (window.location.search.includes("restore=1")) {
      window.history.replaceState({}, "", "/");
    }
    try {
      const s = JSON.parse(saved);
      if (s.selectedLocation) {
        state.selectedLocation = s.selectedLocation;
        state.selectedPlace    = s.selectedPlace || null;
        state.selectedId       = s.selectedId    || null;
        if (s.query) {
          searchInput.value     = s.query;
          heroSearchInput.value = s.query;
        }
        exitHero();
        await loadProperties();
        renderDetail();
        return;
      }
    } catch (_) {}
  }
}

// ---------------------------------------------------------------------------
// Auth rendering
// ---------------------------------------------------------------------------
function getInitials(name) {
  return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("");
}

function avatarHtml(user, cssClass) {
  if (user.avatar_url) {
    return `<img src="${escapeHtml(user.avatar_url)}" class="${cssClass}" alt="${escapeHtml(user.name || user.email)}" title="${escapeHtml(user.name || user.email)}" referrerpolicy="no-referrer">`;
  }
  return `<span class="${cssClass}" title="${escapeHtml(user.name || user.email)}">${escapeHtml(getInitials(user.name || user.email))}</span>`;
}

function renderHeaderAuth() {
  const slot = document.querySelector("#headerAuth");
  if (slot) {
    if (state.user) {
      slot.innerHTML = `
        ${avatarHtml(state.user, "user-avatar")}
        <button class="text-button" id="headerSignOut">Sign out</button>
      `;
      slot.querySelector("#headerSignOut").addEventListener("click", handleSignOut);
    } else {
      slot.innerHTML = `<button class="secondary-button" id="headerSignIn">Sign in</button>`;
      slot.querySelector("#headerSignIn").addEventListener("click", doSignIn);
    }
  }

  const heroSlot = document.querySelector("#heroAuth");
  if (heroSlot) {
    if (state.user) {
      heroSlot.innerHTML = `
        ${avatarHtml(state.user, "hero-avatar")}
        <button class="hero-signout" id="heroSignOut">Sign out</button>
      `;
      heroSlot.querySelector("#heroSignOut").addEventListener("click", handleSignOut);
    } else {
      heroSlot.innerHTML = `<button class="hero-sign-in" id="heroSignIn">Sign in</button>`;
      heroSlot.querySelector("#heroSignIn").addEventListener("click", doSignIn);
    }
  }
}

function doSignIn() {
  const saveState = {
    query:            searchInput.value,
    selectedLocation: state.selectedLocation,
    selectedPlace:    state.selectedPlace,
    selectedId:       state.selectedId,
  };
  localStorage.setItem("preAuthState", JSON.stringify(saveState));
  window.location.href = "/api/auth/signin?provider=google";
}

async function handleSignOut() {
  try { await api("/api/auth/signout"); } catch (_) {}
  state.user = null;
  renderHeaderAuth();
  renderDetail();
}

// ---------------------------------------------------------------------------
// Location selection (no map)
// ---------------------------------------------------------------------------
async function selectLocation(location) {
  const newLat = Number(Number(location.lat).toFixed(6));
  const newLng = Number(Number(location.lng).toFixed(6));

  const locationChanged =
    !state.selectedLocation ||
    state.selectedLocation.lat !== newLat ||
    state.selectedLocation.lng !== newLng;

  state.selectedLocation = { lat: newLat, lng: newLng };

  if (locationChanged) {
    state.selectedId           = null;
    state.selectedPlace        = null;
    state.neighbourhoodPreview = null;
  }

  await loadProperties();

  if (!state.selectedId) {
    try {
      state.neighbourhoodPreview = await api(
        `/api/neighbourhood-preview?lat=${newLat}&lng=${newLng}`
      );
    } catch (_) {
      state.neighbourhoodPreview = null;
    }
  }
}

// ---------------------------------------------------------------------------
// Load properties
// ---------------------------------------------------------------------------
async function loadProperties() {
  const formData = new FormData(searchForm);
  const query    = (formData.get("q") || "").trim();
  const city     = (formData.get("city") || "").trim();

  if (!state.selectedLocation && !query && !city) {
    state.properties = [];
    renderDetail();
    return;
  }

  const params = new URLSearchParams(formData);
  if (state.selectedLocation) {
    params.set("lat",       state.selectedLocation.lat);
    params.set("lng",       state.selectedLocation.lng);
    params.set("radius_km", "0.075");
  }

  try {
    const result = await api(`/api/properties?${params.toString()}`);
    state.properties = result.properties;

    const selectionStillValid = state.selectedId &&
      state.properties.find((p) => p.id === state.selectedId);

    if (!selectionStillValid) {
      // Auto-select only when there's exactly one result
      state.selectedId = state.properties.length === 1 ? state.properties[0].id : null;
    }

    renderDetail();
  } catch (err) {
    console.error("Failed to load properties", err);
  }
}

async function loadPropertiesBackground() {
  if (!state.selectedLocation) return;
  const params = new URLSearchParams(new FormData(searchForm));
  params.set("lat",       state.selectedLocation.lat);
  params.set("lng",       state.selectedLocation.lng);
  params.set("radius_km", "0.075");

  try {
    const result    = await api(`/api/properties?${params.toString()}`);
    const currentId = state.selectedId;
    const byId      = Object.fromEntries(result.properties.map((p) => [p.id, p]));
    state.properties = state.properties.map((p) => byId[p.id] || p);
    for (const p of result.properties) {
      if (!state.properties.find((s) => s.id === p.id)) state.properties.push(p);
    }
    state.selectedId = currentId;
    renderDetail();
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// Render: master results function
// ---------------------------------------------------------------------------
function renderDetail() {
  const property = state.properties.find((p) => p.id === state.selectedId);

  if (property) {
    detailPanel.innerHTML = renderPropertyDetail(property);
    bindDetailEvents(property.id);
    return;
  }

  if (state.properties.length > 1) {
    detailPanel.innerHTML = renderPropertyList();
    return;
  }

  if (state.selectedLocation || state.properties.length === 0 && (searchInput.value.trim() || cityInput.value)) {
    detailPanel.innerHTML = renderEmptyLocationState();
    bindDetailEvents(null);
    return;
  }

  detailPanel.innerHTML = "";
}

function renderPropertyList() {
  const reviewWord = (n) => `${n} ${n === 1 ? "review" : "reviews"}`;
  const cards = state.properties.map((p) => `
    <button class="property-card" data-id="${escapeHtml(p.id)}" type="button">
      <div class="property-card-body">
        <span class="property-card-name">${escapeHtml(p.name)}</span>
        <span class="property-card-addr">${escapeHtml(p.address)}</span>
        <div class="property-card-meta">
          <span class="pill">${escapeHtml(p.property_type)}</span>
          <span class="pill">${escapeHtml(p.area)}, ${escapeHtml(p.city)}</span>
          <span class="pill">${reviewWord(p.review_count)}</span>
          ${p.distance_km != null ? `<span class="pill">${p.distance_km} km away</span>` : ""}
        </div>
      </div>
      <svg class="property-card-arrow" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
    </button>
  `).join("");

  return `
    <p class="results-count">${state.properties.length} properties found</p>
    <div class="property-cards">${cards}</div>
  `;
}

function renderPropertyDetail(property) {
  const reviewWord    = property.review_count === 1 ? "review" : "reviews";
  const hasMultiple   = state.properties.length > 1;
  const propStatsHtml = statsHaveData(property.property_stats, propertySpecificFields)
    ? renderStats(property.property_stats, propertySpecificFields)
    : `<p class="stats-col-empty">No data yet</p>`;
  const neighStatsHtml = statsHaveData(property.neighborhood_stats, neighborhoodFields)
    ? renderStats(property.neighborhood_stats, neighborhoodFields)
    : `<p class="stats-col-empty">No data yet</p>`;

  return `
    ${hasMultiple ? `
    <div class="detail-back-row">
      <button class="back-btn" id="backToListBtn" type="button">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
        All results
      </button>
    </div>` : ""}

    <div class="detail-title-row">
      <div class="detail-title">
        <h2>${escapeHtml(property.name)}</h2>
        <p>${escapeHtml(property.address)}</p>
      </div>
      <div class="detail-actions">
        ${renderAuthActions()}
      </div>
    </div>

    <div class="property-meta-row">
      <span class="pill">${escapeHtml(property.property_type)}</span>
      <span class="pill">${escapeHtml(property.area)}, ${escapeHtml(property.city)}</span>
      <span class="pill">${property.review_count} ${reviewWord}</span>
    </div>

    <div class="stats-columns">
      <div class="stats-col">
        <div class="stats-col-header">
          <span class="stats-col-title">Property Conditions</span>
        </div>
        <div class="stats-col-body">${propStatsHtml}</div>
      </div>
      <div class="stats-col">
        <div class="stats-col-header">
          <span class="stats-col-title">Neighbourhood</span>
        </div>
        <div class="stats-col-body">${neighStatsHtml}</div>
      </div>
    </div>

    <div class="experiences-section">
      <div class="experiences-heading">Individual Experiences</div>
      <div class="comments-list">
        ${renderComments(property)}
      </div>
    </div>
  `;
}

function renderEmptyLocationState() {
  const name    = state.selectedPlace ? state.selectedPlace.name : null;
  const address = state.selectedPlace
    ? state.selectedPlace.display_name
    : state.selectedLocation
    ? `${state.selectedLocation.lat}, ${state.selectedLocation.lng}`
    : null;

  if (!state.selectedLocation && !searchInput.value.trim() && !cityInput.value) {
    return "";
  }

  const preview    = state.neighbourhoodPreview;
  const hasNeigh   = preview && statsHaveData(preview.neighborhood_stats, neighborhoodFields);
  const neighHtml  = hasNeigh
    ? renderStats(preview.neighborhood_stats, neighborhoodFields)
    : "";

  const noPropertyMsg = state.properties.length === 0 && !state.selectedLocation
    ? "No properties matched your search. Try a different area or city."
    : "No property on record at this exact address.";

  const nearbyNote = hasNeigh
    ? `But <strong>${preview.review_count} ${preview.review_count === 1 ? "review" : "reviews"}</strong> exist within 250 m — add yours to build a record for this specific address.`
    : "Be the first to share your experience here.";

  return `
    ${name ? `
    <div class="detail-title-row" style="margin-bottom:16px;">
      <div class="detail-title">
        <h2>${escapeHtml(name)}</h2>
        ${address ? `<p>${escapeHtml(address)}</p>` : ""}
      </div>
      <div class="detail-actions">${renderAuthActions()}</div>
    </div>
    <div class="property-meta-row"><span class="pill">New location</span></div>
    ` : ""}

    <p class="empty-copy" style="margin-bottom:16px;">${noPropertyMsg} ${nearbyNote}</p>

    ${hasNeigh ? `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
      <div class="stats-col">
        <div class="stats-col-header"><span class="stats-col-title">Neighbourhood</span></div>
        <div class="stats-col-body">${neighHtml}</div>
      </div>
    </div>` : ""}
  `;
}

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------
function renderAuthActions() {
  if (state.user) {
    return `<button class="primary-button" id="openReviewButton">Add Review</button>`;
  }
  return `<button class="secondary-button" id="signInGoogle">Sign in to review</button>`;
}

function bindDetailEvents(propertyId) {
  setTimeout(() => {
    const backToList = document.querySelector("#backToListBtn");
    if (backToList) {
      backToList.addEventListener("click", () => {
        state.selectedId = null;
        detailPanel.innerHTML = renderPropertyList();
        bindListEvents();
      });
    }

    if (state.user) {
      const btn = document.querySelector("#openReviewButton");
      if (btn) btn.addEventListener("click", () => openReviewPopup(propertyId));
    } else {
      const sig = document.querySelector("#signInGoogle");
      if (sig) sig.addEventListener("click", doSignIn);
    }
  }, 50);
}

function bindListEvents() {
  setTimeout(() => {
    document.querySelectorAll(".property-card").forEach((card) => {
      card.addEventListener("click", () => {
        state.selectedId = card.dataset.id;
        const property = state.properties.find((p) => p.id === state.selectedId);
        if (property) {
          detailPanel.innerHTML = renderPropertyDetail(property);
          bindDetailEvents(property.id);
          detailPanel.scrollTop = 0;
        }
      });
    });
  }, 50);
}

// ---------------------------------------------------------------------------
// Stats rendering — field-label-first agg rows
// ---------------------------------------------------------------------------
function statsHaveData(stats, fields) {
  if (!stats) return false;
  return fields.some(([key]) => stats[key] && stats[key].total > 0);
}

function statSentiment(field, dataValue) {
  const GOOD = new Set(["good", "safe", "low", "present", "rare", "reliable", "generator"]);
  const BAD  = new Set(["poor", "unsafe", "high", "stairs", "not present", "frequent", "tanker dependent"]);
  if (GOOD.has(dataValue)) return "good";
  if (BAD.has(dataValue))  return "bad";
  if (field === "flooding"      && dataValue === "none") return "good";
  if (field === "standby_power" && dataValue === "none") return "bad";
  if ((field === "elevator" || field === "parking") && dataValue === "none") return "bad";
  return "neutral";
}

function renderStats(stats, fields) {
  if (!stats) return renderStatsEmpty();

  const rows = fields.map(([key, label]) => {
    const s = stats[key];
    if (!s || s.total === 0) return "";

    if (s.dominant) {
      const dataValue = s.dominant.startsWith("Mostly ")
        ? s.dominant.replace("Mostly ", "").toLowerCase()
        : s.dominant.toLowerCase();
      const maxCount  = Math.max(...["5","3","1"].map(v => s.counts[v] || 0));
      const pct       = s.total > 0 ? Math.round(maxCount / s.total * 100) : 0;
      const sentiment = statSentiment(key, dataValue);
      return `
        <div class="agg-row">
          <span class="agg-field">${escapeHtml(label)}</span>
          <div class="agg-bar-track">
            <div class="agg-bar-fill" data-sentiment="${sentiment}" style="width:${pct}%"></div>
          </div>
          <span class="agg-value" data-sentiment="${sentiment}">${escapeHtml(s.dominant)}</span>
        </div>`;
    } else {
      const pills = ["5","3","1"].filter(v => s.counts[v] > 0).map(v => {
        const lbl     = formatScore(key, Number(v));
        const pct     = Math.round((s.counts[v] / s.total) * 100);
        const variant = v === "5" ? "good" : v === "1" ? "poor" : "";
        return `<span class="dist-pill" data-variant="${variant}">${escapeHtml(lbl)} ${pct}%</span>`;
      }).join("");
      return `
        <div class="agg-row is-tied">
          <span class="agg-field">${escapeHtml(label)}</span>
          <div class="agg-pills">${pills}</div>
        </div>`;
    }
  }).join("");

  return rows || renderStatsEmpty();
}

function renderStatsEmpty() {
  return `<p class="stats-col-empty">No data yet</p>`;
}

// ---------------------------------------------------------------------------
// Review cards
// ---------------------------------------------------------------------------
function renderComments(property) {
  if (!property.comments || !property.comments.length) {
    return `<p class="empty-copy">No experiences shared for this property yet.</p>`;
  }

  const TRASH = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>`;

  return property.comments.map((comment) => {
    const isOwn       = state.user && comment.reviewer_id === state.user.id;
    const propScores  = propertySpecificFields.map(([f, label]) => scorePillHtml(f, label, comment.scores[f])).join("");
    const neighScores = neighborhoodFields.map(([f, label])     => scorePillHtml(f, label, comment.scores[f])).join("");

    return `
    <article class="comment-card" data-review-id="${escapeHtml(comment.id)}">
      <div class="comment-header">
        <div class="comment-identity">
          <strong class="comment-reviewer">${escapeHtml(comment.reviewer_name)}</strong>
          <span class="comment-role-badge">${escapeHtml(comment.contributor_role)}</span>
        </div>
        <div class="comment-meta-right">
          <span class="comment-date">${new Date(comment.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span>
          ${isOwn ? `<button class="delete-btn" data-action="delete-start" data-review-id="${escapeHtml(comment.id)}" aria-label="Delete review" title="Delete review">${TRASH}</button>` : ""}
        </div>
      </div>

      ${(comment.lived_period || comment.rent_range || comment.hidden_costs) ? `
      <div class="meta-row">
        ${comment.lived_period  ? `<span class="pill">Period: ${escapeHtml(comment.lived_period)}</span>` : ""}
        ${comment.rent_range    ? `<span class="pill">Rent: ${escapeHtml(comment.rent_range)}</span>` : ""}
        ${comment.hidden_costs  ? `<span class="pill">Hidden costs: ${escapeHtml(comment.hidden_costs)}</span>` : ""}
      </div>` : ""}

      <div class="comment-scores">
        <div class="scores-group">
          <span class="scores-group-label">Property</span>
          <div class="scores-grid">${propScores}</div>
        </div>
        <div class="scores-group">
          <span class="scores-group-label">Neighbourhood</span>
          <div class="scores-grid">${neighScores}</div>
        </div>
      </div>

      ${comment.comment ? `<blockquote class="comment-text">${escapeHtml(comment.comment)}</blockquote>` : ""}
    </article>
  `;
  }).join("");
}

function scorePillHtml(field, label, value) {
  if (value === null || value === undefined) return "";
  return `
    <div class="score-pill" data-value="${value}" data-field="${field}">
      <span class="score-label">${escapeHtml(label)}</span>
      <strong class="score-value">${escapeHtml(formatScore(field, value))}</strong>
    </div>
  `;
}

function formatScore(field, value) {
  if (field === "load_shedding") {
    if (value >= 4) return "Rare";
    if (value >= 2) return "Moderate";
    return "Frequent";
  }
  if (field === "water_supply") {
    if (value >= 4) return "Reliable";
    if (value >= 2) return "Unreliable";
    return "Tanker dependent";
  }
  if (field === "standby_power") {
    if (value >= 4) return "Generator";
    if (value >= 2) return "UPS";
    return "None";
  }
  if (field === "elevator") return value === 5 ? "Present" : "Stairs";
  if (field === "parking")  return value === 5 ? "Present" : "None";
  if (field === "flooding") {
    if (value >= 4) return "None";
    if (value >= 2) return "Minor";
    return "Severe";
  }
  if (field === "noise") {
    if (value >= 4) return "Low";
    if (value >= 2) return "Moderate";
    return "High";
  }
  if (field === "security") {
    if (value >= 4) return "Safe";
    if (value >= 2) return "Average";
    return "Unsafe";
  }
  if (field === "traffic") {
    if (value >= 4) return "Low";
    if (value >= 2) return "Moderate";
    return "High";
  }
  if (value >= 4) return "Good";
  if (value >= 2) return "Fair";
  return "Poor";
}

// ---------------------------------------------------------------------------
// Review form
// ---------------------------------------------------------------------------
const PERIOD_REQUIRED_ROLES = new Set(["Current resident", "Former resident", "Owner or landlord"]);

function openReviewPopup(propertyId) {
  reviewFormContainer.innerHTML = renderReviewForm(propertyId);
  const form = reviewFormContainer.querySelector("#reviewForm");
  form.addEventListener("submit", (event) => handleReviewSubmit(event, propertyId));

  reviewFormContainer.querySelectorAll(".segmented-control").forEach((control) => {
    const hiddenInput = control.querySelector("input[type='hidden']");
    control.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        control.querySelectorAll("button").forEach((b) => (b.dataset.active = "false"));
        btn.dataset.active = "true";
        hiddenInput.value  = btn.dataset.value;
      });
    });
  });

  const roleSelect  = form.querySelector("[name='contributor_role']");
  const periodInput = form.querySelector("#periodInput");
  const periodMark  = form.querySelector("#periodRequiredMark");

  roleSelect.addEventListener("change", () => {
    const requires = PERIOD_REQUIRED_ROLES.has(roleSelect.value);
    periodInput.required    = requires;
    periodInput.placeholder = requires ? "e.g. 2023–2025 (required)" : "e.g. 2023–2025 (optional)";
    periodMark.textContent  = requires ? "*" : "";
  });

  reviewDialog.showModal();
}

async function handleReviewSubmit(event, propertyId) {
  event.preventDefault();
  const form    = event.target;
  const error   = form.querySelector(".form-error");
  error.textContent = "";
  const payload = Object.fromEntries(new FormData(form).entries());

  const allReviewFields = [...propertySpecificFields, ...neighborhoodFields].map(([f]) => f);
  const unselected      = allReviewFields.filter(f => !payload[f]);
  if (unselected.length > 0) {
    error.textContent = "Please make a selection for every property and neighbourhood field.";
    return;
  }

  if (!propertyId) {
    if (state.selectedPlace) {
      payload.place = state.selectedPlace;
    } else if (state.selectedLocation) {
      payload.place = {
        lat:          state.selectedLocation.lat,
        lng:          state.selectedLocation.lng,
        display_name: `Property at ${state.selectedLocation.lat}, ${state.selectedLocation.lng}`,
        name:         `Property at ${state.selectedLocation.lat}, ${state.selectedLocation.lng}`,
        area:         "Manual selection",
        city:         "",
        provider:     "manual",
        raw:          {},
      };
    } else {
      error.textContent = "No location selected.";
      return;
    }
  }

  try {
    const url    = propertyId ? `/api/properties/${propertyId}/reviews` : "/api/properties/new/reviews";
    const result = await api(url, { method: "POST", body: JSON.stringify(payload) });
    reviewDialog.close();

    const savedProperty = result.property;
    if (!propertyId) {
      const alreadyInList = state.properties.find((p) => p.id === savedProperty.id);
      if (!alreadyInList) {
        state.properties = [savedProperty, ...state.properties];
      } else {
        state.properties = state.properties.map((p) => p.id === savedProperty.id ? savedProperty : p);
      }
      state.selectedId       = savedProperty.id;
      state.selectedLocation = {
        lat: Number(Number(savedProperty.latitude).toFixed(6)),
        lng: Number(Number(savedProperty.longitude).toFixed(6)),
      };
      renderDetail();
      loadPropertiesBackground();
    } else {
      state.properties = state.properties.map((p) => p.id === propertyId ? savedProperty : p);
      renderDetail();
    }
  } catch (apiError) {
    if (apiError.message.includes("Sign in")) {
      error.textContent = apiError.message;
      setTimeout(() => reviewDialog.close(), 1800);
    } else {
      error.textContent = apiError.message;
    }
  }
}

function renderReviewForm(propertyId) {
  return `
    <form class="review-form" id="reviewForm" data-property-id="${propertyId ?? ''}">
      <div class="form-grid">
        <label>
          Contributor role
          <select name="contributor_role" required>
            <option value="" disabled selected>Select your role</option>
            <option value="Current resident">Current resident</option>
            <option value="Former resident">Former resident</option>
            <option value="Buyer or tenant prospect">Buyer or tenant prospect</option>
            <option value="General public contributor">General public contributor</option>
            <option value="Owner or landlord">Owner or landlord</option>
          </select>
        </label>
        <label id="periodLabel">
          Observed period <span id="periodRequiredMark"></span>
          <input name="lived_period" id="periodInput" placeholder="e.g. 2023–2025 (optional)">
        </label>
      </div>

      <div class="review-section">
        <h4>Property Conditions</h4>
        <div class="scale-grid">
          ${propertySpecificFields.map(([field, label]) => scale(field, label)).join("")}
        </div>
      </div>

      <div class="review-section">
        <h4>Neighbourhood Conditions</h4>
        <div class="scale-grid">
          ${neighborhoodFields.map(([field, label]) => scale(field, label)).join("")}
        </div>
      </div>

      <div class="form-grid" style="margin-top:16px">
        <label>
          Rent range paid
          <input name="rent_range" placeholder="Optional">
        </label>
        <label>
          Hidden costs
          <input name="hidden_costs" placeholder="e.g. water tankers, generator">
        </label>
      </div>

      <label class="wide">
        Optional comment
        <textarea name="comment" placeholder="Keep it specific and factual"></textarea>
      </label>

      <p class="form-error"></p>
      <div style="display:flex;gap:12px;justify-content:flex-end;margin-top:12px;">
        <button class="primary-button" type="submit">Submit Review</button>
      </div>
    </form>
  `;
}

function scale(field, label) {
  let options = [
    { label: "Good",  value: "5", variant: "good" },
    { label: "Fair",  value: "3", variant: "" },
    { label: "Poor",  value: "1", variant: "poor" },
  ];

  if (field === "load_shedding") {
    options = [
      { label: "Rare",     value: "5", variant: "good" },
      { label: "Moderate", value: "3", variant: "" },
      { label: "Frequent", value: "1", variant: "poor" },
    ];
  } else if (field === "water_supply") {
    options = [
      { label: "Reliable",         value: "5", variant: "good" },
      { label: "Unreliable",       value: "3", variant: "" },
      { label: "Tanker dependent", value: "1", variant: "poor" },
    ];
  } else if (field === "standby_power") {
    options = [
      { label: "Generator", value: "5", variant: "good" },
      { label: "UPS",       value: "3", variant: "" },
      { label: "None",      value: "1", variant: "poor" },
    ];
  } else if (field === "noise") {
    options = [
      { label: "Low",      value: "5", variant: "good" },
      { label: "Moderate", value: "3", variant: "" },
      { label: "High",     value: "1", variant: "poor" },
    ];
  } else if (field === "security") {
    options = [
      { label: "Safe",    value: "5", variant: "good" },
      { label: "Average", value: "3", variant: "" },
      { label: "Unsafe",  value: "1", variant: "poor" },
    ];
  } else if (field === "elevator") {
    options = [
      { label: "Present", value: "5", variant: "good" },
      { label: "Stairs",  value: "1", variant: "poor" },
    ];
  } else if (field === "parking") {
    options = [
      { label: "Present", value: "5", variant: "good" },
      { label: "None",    value: "1", variant: "poor" },
    ];
  } else if (field === "flooding") {
    options = [
      { label: "None",   value: "5", variant: "good" },
      { label: "Minor",  value: "3", variant: "" },
      { label: "Severe", value: "1", variant: "poor" },
    ];
  }

  return `
    <div class="scale-control">
      <span>${label}</span>
      <div class="segmented-control" data-field="${field}">
        <input type="hidden" name="${field}" value="">
        ${options.map((opt) => `
          <button type="button" data-value="${opt.value}" data-variant="${opt.variant}" data-active="false">
            ${opt.label}
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&",  "&amp;")
    .replaceAll("<",  "&lt;")
    .replaceAll(">",  "&gt;")
    .replaceAll('"',  "&quot;")
    .replaceAll("'",  "&#039;");
}

// ---------------------------------------------------------------------------
// After render, bind list-card clicks
// ---------------------------------------------------------------------------
detailPanel.addEventListener("click", (event) => {
  const card = event.target.closest(".property-card");
  if (!card) return;
  state.selectedId = card.dataset.id;
  const property = state.properties.find((p) => p.id === state.selectedId);
  if (property) {
    detailPanel.innerHTML = renderPropertyDetail(property);
    bindDetailEvents(property.id);
    detailPanel.scrollTop = 0;
  }
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
init();
