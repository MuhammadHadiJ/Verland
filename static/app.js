const propertySpecificFields = [
  ["electricity",  "Electricity availability"],
  ["water",        "Water availability"],
  ["gas",          "Gas availability"],
  ["maintenance",  "Maintenance quality"],
  ["elevator",     "Elevator"],
  ["parking",      "Parking"],
  ["internet",     "Fiber Internet"],
  ["structure",    "Building structure"],
  ["seepage",      "Seepage/Dampness"],
];

const neighborhoodFields = [
  ["security",     "Street security"],
  ["noise",        "Noise levels"],
  ["traffic",      "Traffic congestion"],
  ["cleanliness",  "Cleanliness"],
  ["flooding",     "Rain flooding"],
  ["sewage",       "Sewage system"],
  ["road_access",  "Road access"],
  ["mobile_signal","Mobile signal"],
];

const allFields = [...propertySpecificFields, ...neighborhoodFields];
const pakistanCenter = { lat: 30.3753, lng: 69.3451 };

const state = {
  user: null,           // { name, id, email, provider } — set from /api/auth/me
  properties: [],
  selectedId: null,
  selectedLocation: null,
  selectedPlace: null,
  googleMap: null,
  googleMarker: null,
};

const propertyList      = document.querySelector("#propertyList");
const propertyCount     = document.querySelector("#propertyCount");
const detailPanel       = document.querySelector("#detailPanel");
const searchForm        = document.querySelector("#searchForm");
const searchInput       = document.querySelector("#searchInput");
const autocompleteDropdown = document.querySelector("#autocompleteDropdown");
const mapPanel          = document.querySelector("#mapPanel");
const selectedPin       = document.querySelector("#selectedPin");
const mapStatus         = document.querySelector("#mapStatus");
const reviewDialog      = document.querySelector("#reviewDialog");
const reviewFormContainer = document.querySelector("#reviewFormContainer");
const closeReviewDialog = document.querySelector("#closeReviewDialog");

closeReviewDialog.addEventListener("click", () => reviewDialog.close());

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
  const next = THEME_CYCLE[current];
  const isDark = next === "dark" || (next === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
  document.documentElement.setAttribute("data-theme-pref", next);
  localStorage.setItem("theme", next);
  updateThemeButton();
});

updateThemeButton();

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  autocompleteDropdown.hidden = true;
  loadProperties();
});

// ---------------------------------------------------------------------------
// Autocomplete
// ---------------------------------------------------------------------------
let debounceTimer;
searchInput.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  const query = searchInput.value.trim();
  if (query.length < 3) {
    autocompleteDropdown.hidden = true;
    return;
  }
  debounceTimer = setTimeout(async () => {
    try {
      const city = document.querySelector("#cityInput")?.value || "";
      const qs = new URLSearchParams({ q: query, city });
      const result = await api(`/api/location-search?${qs}`);
      renderAutocomplete(result.places);
    } catch (error) {
      console.error("Autocomplete error:", error);
    }
  }, 300);
});

function renderAutocomplete(places) {
  if (!places || !places.length) {
    autocompleteDropdown.hidden = true;
    return;
  }
  autocompleteDropdown.innerHTML = "";
  autocompleteDropdown.hidden = false;

  for (const place of places) {
    const item = document.createElement("button");
    item.className = "autocomplete-item";
    item.type = "button";
    item.innerHTML = `
      <strong>${escapeHtml(place.name)}</strong>
      <span>${escapeHtml(place.display_name)}</span>
    `;
    item.addEventListener("click", () => {
      searchInput.value = place.display_name;
      autocompleteDropdown.hidden = true;
      // Fix #11: always use place.lng (Python always returns "lng" not "lon")
      const lat = Number(place.lat);
      const lng = Number(place.lng);
      selectMapLocation({ lat, lng }).then(() => {
        // Set selectedPlace AFTER selectMapLocation so it isn't cleared
        state.selectedPlace = place;
        renderDetail();
      });
      if (state.googleMap) {
        state.googleMap.flyTo({ center: [lng, lat], zoom: 18 });
      }
    });
    autocompleteDropdown.append(item);
  }
}

document.addEventListener("click", (event) => {
  if (!searchForm.contains(event.target)) {
    autocompleteDropdown.hidden = true;
  }
});

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------
mapPanel.addEventListener("click", async (event) => {
  if (event.target.id === "googleMap" || state.googleMap) return;
  const rect = mapPanel.getBoundingClientRect();
  const x = (event.clientX - rect.left) / rect.width;
  const y = (event.clientY - rect.top) / rect.height;
  const lat = 37.1 - y * 13.5;
  const lng = 60.8 + x * 16.7;

  searchInput.value = "";
  await selectMapLocation(
    { lat, lng },
    { x: event.clientX - rect.left, y: event.clientY - rect.top }
  );

  try {
    const result = await api(`/api/location-reverse?lat=${lat}&lng=${lng}`);
    if (result.place) {
      state.selectedPlace = result.place;
      renderDetail();
    }
  } catch (err) {
    console.warn("Reverse geocoding failed", err);
  }
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
// Init — restore session from server, then load data
// ---------------------------------------------------------------------------
async function init() {
  // Check if the user has an active session (real Supabase auth)
  try {
    const me = await api("/api/auth/me");
    state.user = me;  // { id, email, name, provider }
  } catch (_) {
    state.user = null;
  }

  // Load map if a MapTiler key is configured
  try {
    const config = await api("/api/config");
    if (config.maptilerApiKey) {
      loadMapTiler(config.maptilerApiKey);
    }
  } catch (_) {}

  // Restore pre-auth state if we just came back from an OAuth redirect.
  // Uses localStorage (survives cross-origin navigations unlike sessionStorage).
  const saved = localStorage.getItem("preAuthState");
  if (saved) {
    localStorage.removeItem("preAuthState");
    // Clean ?restore=1 from the URL without causing another page load
    if (window.location.search.includes("restore=1")) {
      window.history.replaceState({}, "", "/");
    }
    try {
      const s = JSON.parse(saved);
      if (s.selectedLocation) {
        state.selectedLocation = s.selectedLocation;
        state.selectedPlace    = s.selectedPlace || null;
        state.selectedId       = s.selectedId    || null;
        if (s.query) searchInput.value = s.query;
        mapStatus.textContent = `${s.selectedLocation.lat}, ${s.selectedLocation.lng}`;
      }
    } catch (_) {}
  }

  await loadProperties();
  renderList();
  renderDetail();
}

function loadMapTiler(apiKey) {
  maptilersdk.config.apiKey = apiKey;
  document.querySelector("#fallbackMap").hidden = true;

  state.googleMap = new maptilersdk.Map({
    container: "googleMap",
    style: maptilersdk.MapStyle.HYBRID,
    center: [pakistanCenter.lng, pakistanCenter.lat],
    zoom: 5,
    navigationControl: false,
    geolocateControl: false,
    maptilerLogoControl: false,
    attributionControl: { compact: true },
  });

  state.googleMap.on("click", async (event) => {
    const lat = event.lngLat.lat;
    const lng = event.lngLat.lng;
    searchInput.value = "";
    await selectMapLocation({ lat, lng });
    try {
      const result = await api(`/api/location-reverse?lat=${lat}&lng=${lng}`);
      if (result.place) {
        state.selectedPlace = result.place;
        renderDetail();
      }
    } catch (err) {
      console.warn("Reverse geocoding failed", err);
    }
  });
}

async function selectMapLocation(location, fallbackPoint = null) {
  const newLat = Number(Number(location.lat).toFixed(6));
  const newLng = Number(Number(location.lng).toFixed(6));

  // Only clear selectedPlace if the location actually changed
  const locationChanged =
    !state.selectedLocation ||
    state.selectedLocation.lat !== newLat ||
    state.selectedLocation.lng !== newLng;

  state.selectedLocation = { lat: newLat, lng: newLng };

  if (locationChanged) {
    state.selectedId = null;
    // selectedPlace is cleared here; it will be set by the caller (autocomplete
    // click or reverse geocode) once the place is resolved
    state.selectedPlace = null;
  }

  mapStatus.textContent = `${newLat}, ${newLng}`;
  moveSelectedPin(fallbackPoint);
  await loadProperties();
  renderDetail();
}

function moveSelectedPin(fallbackPoint) {
  if (state.googleMap) {
    const { lat, lng } = state.selectedLocation;
    if (!state.googleMarker) {
      state.googleMarker = new maptilersdk.Marker({ color: "#991b1b" })
        .setLngLat([lng, lat])
        .addTo(state.googleMap);
    } else {
      state.googleMarker.setLngLat([lng, lat]);
    }
    state.googleMap.flyTo({ center: [lng, lat] });
    return;
  }
  selectedPin.hidden = false;
  if (fallbackPoint) {
    selectedPin.style.left = `${fallbackPoint.x}px`;
    selectedPin.style.top  = `${fallbackPoint.y}px`;
  }
}

async function loadProperties() {
  const formData = new FormData(searchForm);
  const query = (formData.get("q") || "").trim();
  const city  = (formData.get("city") || "").trim();

  // Never show the whole DB unprompted.
  // Only fetch if the user has pinned a location OR typed a real search query.
  if (!state.selectedLocation && !query && !city) {
    state.properties = [];
    renderList();
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
    if (!selectionStillValid && state.properties.length) {
      state.selectedId = state.properties[0].id;
    }
    renderList();
    renderDetail();
  } catch (err) {
    console.error("Failed to load properties", err);
  }
}

// ---------------------------------------------------------------------------
// Render: sidebar list
// ---------------------------------------------------------------------------
function renderList() {
  propertyCount.textContent = String(state.properties.length);
  propertyList.innerHTML = "";

  if (!state.properties.length) {
    propertyList.innerHTML = `
      <p class="empty-copy">
        ${state.selectedLocation
          ? "No exact property near this point yet."
          : "Click the exact real estate on the map."}
      </p>
    `;
    return;
  }

  for (const property of state.properties) {
    const button = document.createElement("button");
    button.className = "property-item";
    button.type = "button";
    button.setAttribute("aria-current", String(property.id === state.selectedId));
    // Fix #8: "reviews" not "accounts"
    const reviewWord = property.review_count === 1 ? "review" : "reviews";
    button.innerHTML = `
      <strong>${escapeHtml(property.name)}</strong>
      <span>${escapeHtml(property.address)}</span>
      <span class="meta-row">
        <span class="pill">${escapeHtml(property.property_type)}</span>
        <span class="pill">${escapeHtml(property.area)}, ${escapeHtml(property.city)}</span>
        <span class="pill">${property.review_count} ${reviewWord}</span>
        ${property.distance_km == null ? "" : `<span class="pill">${property.distance_km} km away</span>`}
      </span>
    `;
    button.addEventListener("click", () => {
      state.selectedId = property.id;
      renderList();
      renderDetail();
    });
    propertyList.append(button);
  }
}

// ---------------------------------------------------------------------------
// Render: detail panel
// ---------------------------------------------------------------------------
function renderDetail() {
  const property = state.properties.find((p) => p.id === state.selectedId);
  if (!property) {
    detailPanel.innerHTML = renderMapEmptyState();
    bindDetailEvents(null);
    return;
  }

  // Fix #8: "reviews" not "accounts"
  const reviewWord = property.review_count === 1 ? "review" : "reviews";

  detailPanel.innerHTML = `
    <header class="sticky-property-header">
      <div class="header-content">
        <div class="header-meta">
          <h2>${escapeHtml(property.name)}</h2>
          <p>${escapeHtml(property.address)}</p>
        </div>
        <div class="header-actions">
          ${renderAuthActions()}
        </div>
      </div>
    </header>

    <div class="property-page-content">
      <div class="meta-row" style="margin-bottom: 24px;">
        <span class="pill">${escapeHtml(property.property_type)}</span>
        <span class="pill">${escapeHtml(property.area)}, ${escapeHtml(property.city)}</span>
        <span class="pill">${property.review_count} individual ${reviewWord}</span>
      </div>

      <section class="aggregation-section">
        <div class="aggregation-grid">
          <div class="aggregation-panel">
            <h3>Property Conditions</h3>
            <div class="stats-list">
              ${renderStats(property.property_stats, propertySpecificFields)}
            </div>
          </div>
          <div class="aggregation-panel">
            <h3>Neighborhood Conditions</h3>
            <div class="stats-list">
              ${renderStats(property.neighborhood_stats, neighborhoodFields)}
            </div>
          </div>
        </div>
      </section>

      <section class="panel" style="margin-top: 32px">
        <h3>Individual Experiences</h3>
        <div class="comments-list">
          ${renderComments(property)}
        </div>
      </section>
    </div>
  `;

  bindDetailEvents(property.id);
}

function renderAuthActions() {
  if (state.user) {
    return `
      <button class="primary-button" id="openReviewButton">Add Review</button>
      <span class="user-badge">${escapeHtml(state.user.name)}</span>
      <button class="secondary-button" id="signOutBtn">Sign out</button>
    `;
  }
  return `
    <button class="secondary-button" id="signInGoogle">
      Sign in with Google
    </button>
  `;
}

function bindDetailEvents(propertyId) {
  setTimeout(() => {
    if (state.user) {
      const btn = document.querySelector("#openReviewButton");
      if (btn) btn.addEventListener("click", () => openReviewPopup(propertyId));
      const out = document.querySelector("#signOutBtn");
      if (out) out.addEventListener("click", handleSignOut);
    } else {
      const sig = document.querySelector("#signInGoogle");
      if (sig) sig.addEventListener("click", () => {
        // Save current search state so we can restore it after OAuth redirect.
        // localStorage persists across the Google OAuth navigation (sessionStorage doesn't).
        const saveState = {
          query:            searchInput.value,
          selectedLocation: state.selectedLocation,
          selectedPlace:    state.selectedPlace,
          selectedId:       state.selectedId,
        };
        localStorage.setItem("preAuthState", JSON.stringify(saveState));
        window.location.href = "/api/auth/signin?provider=google";
      });
    }
  }, 50);
}

async function handleSignOut() {
  try { await api("/api/auth/signout"); } catch (_) {}
  state.user = null;
  renderDetail();
  renderList();
}

// ---------------------------------------------------------------------------
// Render: aggregated stats
// ---------------------------------------------------------------------------
function renderStats(stats, fields) {
  if (!stats) return '<p class="empty-copy">No data available.</p>';

  const html = fields.map(([key, label]) => {
    const s = stats[key];
    if (!s || s.total === 0) return "";

    let valueHtml;
    if (s.dominant) {
      // Clear winner — render as a single colored label
      const dataValue = s.dominant.startsWith("Mostly ")
        ? s.dominant.replace("Mostly ", "").toLowerCase()
        : s.dominant.toLowerCase();
      valueHtml = `
        <span class="stat-dominant" data-field="${key}" data-value="${dataValue}">
          ${escapeHtml(s.dominant)}
        </span>`;
    } else {
      // Tied — render a row of colored count pills from raw counts
      const parts = ["5", "3", "1"]
        .filter(v => s.counts[v] > 0)
        .map(v => {
          const lbl = formatScore(key, Number(v));
          const pct = Math.round((s.counts[v] / s.total) * 100);
          const variant = v === "5" ? "good" : v === "1" ? "poor" : "";
          return `<span class="dist-pill" data-variant="${variant}">${escapeHtml(lbl)} ${pct}%</span>`;
        })
        .join("");
      valueHtml = `<span class="dist-row">${parts}</span>`;
    }

    return `
      <div class="stat-row">
        <span class="stat-label">${label}</span>
        <div class="stat-value-container">
          ${valueHtml}
          <span class="stat-count">${s.total} ${s.total === 1 ? "review" : "reviews"}</span>
        </div>
      </div>
    `;
  }).join("");

  return html || '<p class="empty-copy">Insufficient data for this section.</p>';
}

// ---------------------------------------------------------------------------
// Review form
// ---------------------------------------------------------------------------
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
        hiddenInput.value = btn.dataset.value;
      });
    });
  });

  reviewDialog.showModal();
}

async function handleReviewSubmit(event, propertyId) {
  event.preventDefault();
  const form  = event.target;
  const error = form.querySelector(".form-error");
  error.textContent = "";
  const payload = Object.fromEntries(new FormData(form).entries());

  if (!propertyId) {
    if (state.selectedPlace) {
      payload.place = state.selectedPlace;
    } else if (state.selectedLocation) {
      // Fallback: raw coordinate click with no geocoded address.
      // This will create a "Property at lat, lng" entry which is not ideal,
      // but it's only reached when reverse geocoding failed entirely.
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
    const url = propertyId
      ? `/api/properties/${propertyId}/reviews`
      : "/api/properties/new/reviews";
    const result = await api(url, {
      method: "POST",
      body:   JSON.stringify(payload),
    });

    reviewDialog.close();

    const savedProperty = result.property;

    if (!propertyId) {
      // New property was created (or matched). Inject it directly into state
      // so it shows up immediately without depending on the spatial radius
      // search to find it (which can miss due to coordinate rounding).
      const alreadyInList = state.properties.find((p) => p.id === savedProperty.id);
      if (!alreadyInList) {
        state.properties = [savedProperty, ...state.properties];
      } else {
        state.properties = state.properties.map((p) =>
          p.id === savedProperty.id ? savedProperty : p
        );
      }
      state.selectedId = savedProperty.id;

      // Also update selectedLocation to the property's actual stored coordinates
      // so subsequent spatial searches find it reliably.
      state.selectedLocation = {
        lat: Number(Number(savedProperty.latitude).toFixed(6)),
        lng: Number(Number(savedProperty.longitude).toFixed(6)),
      };
      mapStatus.textContent = `${state.selectedLocation.lat}, ${state.selectedLocation.lng}`;

      renderList();
      renderDetail();

      // Then do a background reload at a wider radius to pick up any nearby
      // properties that should also appear, without blocking the UI.
      loadPropertiesBackground();
    } else {
      state.properties = state.properties.map((p) =>
        p.id === propertyId ? savedProperty : p
      );
      renderList();
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

// Background reload — refreshes the property list without resetting selectedId
async function loadPropertiesBackground() {
  if (!state.selectedLocation) return; // nothing to sync without a pinned location

  const params = new URLSearchParams(new FormData(searchForm));
  params.set("lat",       state.selectedLocation.lat);
  params.set("lng",       state.selectedLocation.lng);
  params.set("radius_km", "0.075");

  try {
    const result = await api(`/api/properties?${params.toString()}`);
    const currentId = state.selectedId;
    const serverById = Object.fromEntries(result.properties.map((p) => [p.id, p]));
    state.properties = state.properties.map((p) => serverById[p.id] || p);
    for (const p of result.properties) {
      if (!state.properties.find((s) => s.id === p.id)) {
        state.properties.push(p);
      }
    }
    state.selectedId = currentId;
    renderList();
    renderDetail();
  } catch (_) {
    // silent — UI already shows the review
  }
}

// ---------------------------------------------------------------------------
// Render: empty state when no property selected
// ---------------------------------------------------------------------------
function renderMapEmptyState() {
  if (!state.selectedLocation) {
    return `
      <div class="empty-state">
        <h2>Property discovery is search-first</h2>
        <p>Start by searching for a specific property or area above to view real-world insights.</p>
      </div>
    `;
  }

  const name    = state.selectedPlace ? state.selectedPlace.name : "Selected Location";
  const address = state.selectedPlace
    ? state.selectedPlace.display_name
    : `${state.selectedLocation.lat}, ${state.selectedLocation.lng}`;

  return `
    <header class="sticky-property-header">
      <div class="header-content">
        <div class="header-meta">
          <h2>${escapeHtml(name)}</h2>
          <p>${escapeHtml(address)}</p>
        </div>
        <div class="header-actions">
          ${renderAuthActions()}
        </div>
      </div>
    </header>

    <div class="property-page-content">
      <div class="meta-row" style="margin-bottom: 24px;">
        <span class="pill">New location</span>
      </div>
      <div class="panel">
        <h3>No experiences shared here yet</h3>
        <p class="empty-copy">No one has reviewed this specific property yet. Sign in and be the first to share your observation.</p>
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Review form builder
// ---------------------------------------------------------------------------
function renderReviewForm(propertyId) {
  return `
    <form class="review-form" id="reviewForm" data-property-id="${propertyId ?? ''}">
      <div class="form-grid">
        <label>
          Contributor role
          <select name="contributor_role" required>
            <option value="Current resident">Current resident</option>
            <option value="Former resident">Former resident</option>
            <option value="Buyer or tenant prospect">Buyer or tenant prospect</option>
            <option value="General public contributor">General public contributor</option>
            <option value="Owner or landlord">Owner or landlord</option>
          </select>
        </label>
        <label>
          Observed period
          <input name="lived_period" placeholder="e.g. 2023–2025, or current" required>
        </label>
      </div>

      <div class="review-section">
        <h4>Property Conditions</h4>
        <div class="scale-grid">
          ${propertySpecificFields.map(([field, label]) => scale(field, label)).join("")}
        </div>
      </div>

      <div class="review-section">
        <h4>Neighborhood Conditions</h4>
        <div class="scale-grid">
          ${neighborhoodFields.map(([field, label]) => scale(field, label)).join("")}
        </div>
      </div>

      <div class="form-grid" style="margin-top: 16px">
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
      <div style="display:flex; gap:12px; justify-content:flex-end; margin-top:12px;">
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

  if (field === "noise") {
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
  } else if (field === "internet") {
    options = [
      { label: "Available", value: "5", variant: "good" },
      { label: "None",      value: "1", variant: "poor" },
    ];
  } else if (field === "flooding") {
    options = [
      { label: "None",   value: "5", variant: "good" },
      { label: "Minor",  value: "3", variant: "" },
      { label: "Severe", value: "1", variant: "poor" },
    ];
  } else if (field === "sewage") {
    options = [
      { label: "None",      value: "5", variant: "good" },
      { label: "Occasional",value: "3", variant: "" },
      { label: "Frequent",  value: "1", variant: "poor" },
    ];
  }

  // Binary fields default to not-present; ternary default to 5 (best condition)
  const defaultValue =
    field === "elevator" || field === "parking" ? "1" : "5";

  return `
    <div class="scale-control">
      <span>${label}</span>
      <div class="segmented-control" data-field="${field}">
        <input type="hidden" name="${field}" value="${defaultValue}">
        ${options.map((opt) => `
          <button type="button"
            data-value="${opt.value}"
            data-variant="${opt.variant}"
            data-active="${opt.value === defaultValue ? "true" : "false"}">
            ${opt.label}
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Render: individual review cards
// ---------------------------------------------------------------------------
function renderComments(property) {
  if (!property.comments || !property.comments.length) {
    return `<p class="empty-copy">No experiences shared for this property yet.</p>`;
  }

  return property.comments.map((comment) => `
    <article class="comment">
      <div class="comment-header">
        <strong>${escapeHtml(comment.reviewer_name)}</strong>
        <span class="comment-date">${new Date(comment.created_at).toLocaleDateString()}</span>
      </div>
      <div class="meta-row" style="margin-bottom:4px;">
        <span class="pill">${escapeHtml(comment.contributor_role)}</span>
        ${comment.lived_period ? `<span class="pill">Period: ${escapeHtml(comment.lived_period)}</span>` : ""}
        ${comment.rent_range  ? `<span class="pill">Rent: ${escapeHtml(comment.rent_range)}</span>`  : ""}
        ${comment.hidden_costs ? `<span class="pill">Hidden: ${escapeHtml(comment.hidden_costs)}</span>` : ""}
      </div>

      <div class="comment-scores-list">
        ${allFields.map(([f, label]) => `
          <div class="score-pill" data-value="${comment.scores[f]}">
            ${label}: <strong>${formatScore(f, comment.scores[f])}</strong>
          </div>
        `).join("")}
      </div>

      ${comment.comment
        ? `<p class="comment-text">"${escapeHtml(comment.comment)}"</p>`
        : ""}
    </article>
  `).join("");
}

function formatScore(field, value) {
  if (field === "elevator")  return value === 5 ? "Present"   : "Stairs";
  if (field === "parking")   return value === 5 ? "Present"   : "None";
  if (field === "internet")  return value === 5 ? "Available" : "None";
  if (field === "flooding") {
    if (value >= 4) return "None";
    if (value >= 2) return "Minor";
    return "Severe";
  }
  if (field === "sewage") {
    if (value >= 4) return "None";
    if (value >= 2) return "Occasional";
    return "Frequent";
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
  if (value >= 4) return "Good";
  if (value >= 2) return "Fair";
  return "Poor";
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
// Boot
// ---------------------------------------------------------------------------
init();
