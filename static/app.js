const fields = [
  ["electricity", "Electricity reliability"],
  ["water", "Water availability"],
  ["gas", "Gas availability"],
  ["maintenance", "Building maintenance"],
  ["elevator", "Elevator reliability"],
  ["structure", "Structural condition"],
  ["seepage", "Drainage/seepage"],
  ["internet", "Internet quality"],
  ["mobile_signal", "Mobile signal"],
  ["noise", "Street noise"],
  ["security", "Area security"],
  ["cleanliness", "Cleanliness"],
  ["road_access", "Road accessibility"],
];

const categories = [
  ["Property Utilities", ["electricity", "water", "gas"]],
  ["Building Quality", ["maintenance", "elevator", "structure", "seepage"]],
  ["Property Connectivity", ["internet", "mobile_signal"]],
  ["Shared Environment", ["noise", "security", "cleanliness", "road_access"]],
];

const labelByField = Object.fromEntries(fields);
const binaryFields = ["maintenance", "elevator", "structure", "seepage"];
const pakistanCenter = { lat: 30.3753, lng: 69.3451 };
const state = {
  properties: [],
  selectedId: null,
  selectedLocation: null,
  selectedPlace: null,
  googleMap: null,
  googleMarker: null,
};

const propertyList = document.querySelector("#propertyList");
const propertyCount = document.querySelector("#propertyCount");
const detailPanel = document.querySelector("#detailPanel");
const searchForm = document.querySelector("#searchForm");
const searchInput = document.querySelector("#searchInput");
const autocompleteDropdown = document.querySelector("#autocompleteDropdown");
const mapPanel = document.querySelector("#mapPanel");
const selectedPin = document.querySelector("#selectedPin");
const mapStatus = document.querySelector("#mapStatus");
const reviewDialog = document.querySelector("#reviewDialog");
const reviewFormContainer = document.querySelector("#reviewFormContainer");
const closeReviewDialog = document.querySelector("#closeReviewDialog");

closeReviewDialog.addEventListener("click", () => reviewDialog.close());

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  autocompleteDropdown.hidden = true;
  loadProperties();
});

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
      const result = await api(`/api/location-search?q=${encodeURIComponent(query)}`);
      renderAutocomplete(result.places);
    } catch (error) {
      console.error("Autocomplete error:", error);
    }
  }, 300);
});

function renderAutocomplete(places) {
  if (!places.length) {
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
      state.selectedPlace = place;
      selectMapLocation({ lat: Number(place.lat), lng: Number(place.lon || place.lng) });
      if (state.googleMap) {
        state.googleMap.setZoom(18);
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

mapPanel.addEventListener("click", (event) => {
  if (event.target.id === "googleMap" || state.googleMap) return;
  const rect = mapPanel.getBoundingClientRect();
  const x = (event.clientX - rect.left) / rect.width;
  const y = (event.clientY - rect.top) / rect.height;
  const lat = 37.1 - y * 13.5;
  const lng = 60.8 + x * 16.7;
  selectMapLocation({ lat, lng }, { x: event.clientX - rect.left, y: event.clientY - rect.top });
});


async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.error || "Something went wrong");
  }
  return body;
}

async function init() {
  const config = await api("/api/config");
  if (config.googleMapsApiKey) {
    loadGoogleMaps(config.googleMapsApiKey);
  }
  loadProperties();
}

function loadGoogleMaps(apiKey) {
  window.initGoogleMap = () => {
    state.googleMap = new google.maps.Map(document.querySelector("#googleMap"), {
      center: pakistanCenter,
      zoom: 5,
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: false,
    });

    state.googleMap.addListener("click", (event) => {
      selectMapLocation({
        lat: event.latLng.lat(),
        lng: event.latLng.lng(),
      });
    });
  };

  const script = document.createElement("script");
  script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&callback=initGoogleMap`;
  script.async = true;
  script.defer = true;
  document.head.append(script);
}

async function selectMapLocation(location, fallbackPoint = null) {
  state.selectedLocation = {
    lat: Number(Number(location.lat).toFixed(6)),
    lng: Number(Number(location.lng).toFixed(6)),
  };
  if (!state.selectedPlace || state.selectedPlace.lat !== state.selectedLocation.lat || state.selectedPlace.lng !== state.selectedLocation.lng) {
    state.selectedPlace = null;
  }
  state.selectedId = null;
  mapStatus.textContent = `${state.selectedLocation.lat}, ${state.selectedLocation.lng}`;
  moveSelectedPin(fallbackPoint);
  await loadProperties();
  renderDetail();
}

function moveSelectedPin(fallbackPoint) {
  if (state.googleMap) {
    if (!state.googleMarker) {
      state.googleMarker = new google.maps.Marker({ map: state.googleMap });
    }
    state.googleMarker.setPosition(state.selectedLocation);
    state.googleMap.panTo(state.selectedLocation);
    return;
  }

  selectedPin.hidden = false;
  if (fallbackPoint) {
    selectedPin.style.left = `${fallbackPoint.x}px`;
    selectedPin.style.top = `${fallbackPoint.y}px`;
  }
}

async function loadProperties() {
  const params = new URLSearchParams(new FormData(searchForm));
  if (state.selectedLocation) {
    params.set("lat", state.selectedLocation.lat);
    params.set("lng", state.selectedLocation.lng);
    params.set("radius_km", "0.075");
  }

  const result = await api(`/api/properties?${params.toString()}`);
  state.properties = result.properties;
  if (!state.selectedId && state.properties.length) {
    state.selectedId = state.properties[0].id;
  }
  renderList();
  renderDetail();
}

function renderList() {
  propertyCount.textContent = String(state.properties.length);
  propertyList.innerHTML = "";

  if (!state.properties.length) {
    propertyList.innerHTML = `
      <p class="empty-copy">
        ${state.selectedLocation ? "No exact property near this point yet." : "Click the exact real estate on the map."}
      </p>
    `;
    return;
  }

  for (const property of state.properties) {
    const button = document.createElement("button");
    button.className = "property-item";
    button.type = "button";
    button.setAttribute("aria-current", String(property.id === state.selectedId));
    button.innerHTML = `
      <strong>${escapeHtml(property.name)}</strong>
      <span>${escapeHtml(property.address)}</span>
      <span class="meta-row">
        <span class="pill">${escapeHtml(property.property_type)}</span>
        <span class="pill">${escapeHtml(property.area)}, ${escapeHtml(property.city)}</span>
        <span class="pill">${property.review_count} responses</span>
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

function renderDetail() {
  const property = state.properties.find((item) => item.id === state.selectedId);
  if (!property) {
    detailPanel.innerHTML = renderMapEmptyState();
    const btn = detailPanel.querySelector("#openReviewButton");
    if (btn) {
      btn.addEventListener("click", () => openReviewPopup(null));
    }
    return;
  }

  detailPanel.innerHTML = `
    <section class="property-hero">
      <div class="meta-row">
        <span class="pill">${escapeHtml(property.property_type)}</span>
        <span class="pill">${escapeHtml(property.area)}, ${escapeHtml(property.city)}</span>
        <span class="pill">${property.review_count} individual ${property.review_count === 1 ? 'account' : 'accounts'}</span>
      </div>
      <h2>${escapeHtml(property.name)}</h2>
      <p>${escapeHtml(property.address)}</p>
      <div class="property-actions">
        <button class="primary-button" id="openReviewButton">Add your review</button>
      </div>
    </section>

    <div class="content-grid full-width">
      <section class="panel">
        <h2>Ground Truth Accounts</h2>
        <div class="comments-list">
          ${renderComments(property)}
        </div>
      </section>

      <section class="panel">
        <h2>Nearby shared observations</h2>
        <div class="comments-list">
          ${renderAreaObservations(property)}
        </div>
      </section>
    </div>
  `;

  document.querySelector("#openReviewButton").addEventListener("click", () => openReviewPopup(property.id));
}

function openReviewPopup(propertyId) {
  reviewFormContainer.innerHTML = renderReviewForm(propertyId);
  const form = reviewFormContainer.querySelector("#reviewForm");
  form.addEventListener("submit", (event) => {
    handleReviewSubmit(event, propertyId);
    reviewDialog.close();
  });

  // Initialize segmented controls
  reviewFormContainer.querySelectorAll(".segmented-control").forEach(control => {
    const hiddenInput = control.querySelector("input[type='hidden']");
    control.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        control.querySelectorAll("button").forEach(b => b.dataset.active = "false");
        btn.dataset.active = "true";
        hiddenInput.value = btn.dataset.value;
      });
    });
  });

  reviewDialog.showModal();
}

async function handleReviewSubmit(event, propertyId) {
  event.preventDefault();
  const form = event.target;
  const error = form.querySelector(".form-error");
  error.textContent = "";
  const payload = Object.fromEntries(new FormData(form).entries());

  if (!propertyId) {
    // Inject selected location metadata for automatic property creation
    payload.location = state.selectedLocation;
    if (state.selectedPlace) {
      payload.place = state.selectedPlace;
    }
  }

  try {
    const url = propertyId ? `/api/properties/${propertyId}/reviews` : "/api/properties/new/reviews";
    const result = await api(url, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (!propertyId) {
      state.selectedId = result.property.id;
      await loadProperties();
    } else {
      state.properties = state.properties.map((item) =>
        item.id === propertyId ? result.property : item
      );
      renderList();
      renderDetail();
    }
  } catch (apiError) {
    error.textContent = apiError.message;
  }
}

function renderMapEmptyState() {
  if (!state.selectedLocation) {
    return `
      <div class="empty-state">
        <h2>Start with the map</h2>
        <p>Click the exact building, house, plot, or commercial property to view accounts tied to that real estate.</p>
      </div>
    `;
  }

  return `
    <section class="property-hero">
      <div class="meta-row">
        <span class="pill">New location</span>
      </div>
      <h2>${state.selectedPlace ? escapeHtml(state.selectedPlace.name) : "Selected Location"}</h2>
      <p>${state.selectedPlace ? escapeHtml(state.selectedPlace.display_name) : `${state.selectedLocation.lat}, ${state.selectedLocation.lng}`}</p>
      <div class="property-actions">
        <button class="primary-button" id="openReviewButton">Add first account</button>
      </div>
    </section>

    <div class="content-grid">
      <section class="panel">
        <h2>No accounts yet</h2>
        <p class="empty-copy">We apologize, but no one has added an account for this specific property yet. You can be the first to help others by adding your observation.</p>
      </section>
    </div>
  `;
}


function renderReviewForm(propertyId) {
  return `
    <form class="review-form" id="reviewForm" data-property-id="${propertyId}">
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
          <input name="lived_period" placeholder="e.g. 2023-2025, current" required>
        </label>
      </div>

      <div class="scale-grid">
        ${fields.map(([field, label]) => scale(field, label)).join("")}
      </div>

      <div class="form-grid" style="margin-top: 16px">
        <label>
          Rent range paid
          <input name="rent_range" placeholder="Optional">
        </label>
        <label>
          Hidden costs
          <input name="hidden_costs" placeholder="e.g. Tankers, maintenance">
        </label>
      </div>

      <label class="wide">
        Optional comment
        <textarea name="comment" placeholder="Keep it specific and factual"></textarea>
      </label>

      <p class="form-error"></p>
      <button class="primary-button" type="submit">Submit review</button>
    </form>
  `;
}

function scale(field, label) {
  let options = [
    { label: "Good", value: "5", variant: "good" },
    { label: "Fair", value: "3", variant: "" },
    { label: "Poor", value: "1", variant: "poor" },
  ];

  if (field === "elevator") {
    options = [
      { label: "Elevator", value: "5", variant: "good" },
      { label: "Stairs", value: "1", variant: "poor" },
    ];
  }

  const defaultValue = field === "elevator" ? "1" : "5";

  return `
    <div class="scale-control">
      <span>${label}</span>
      <div class="segmented-control" data-field="${field}">
        <input type="hidden" name="${field}" value="${defaultValue}" required>
        ${options
          .map(
            (opt) => `
          <button type="button"
            data-value="${opt.value}"
            data-variant="${opt.variant}"
            data-active="${opt.value === defaultValue ? "true" : "false"}">
            ${opt.label}
          </button>
        `
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderComments(property) {
  if (!property.comments.length) {
    return `<p class="empty-copy">No reviews yet for this property.</p>`;
  }

  return property.comments
    .map(
      (comment) => `
        <article class="comment">
          <div class="comment-header">
            <strong>${escapeHtml(comment.contributor_role)}</strong>
            <span class="comment-date">${new Date(comment.created_at).toLocaleDateString()}</span>
          </div>
          <div class="meta-row">
            ${comment.lived_period ? `<span>Period: ${escapeHtml(comment.lived_period)}</span>` : ""}
            ${comment.rent_range ? `<span>Rent: ${escapeHtml(comment.rent_range)}</span>` : ""}
            ${comment.hidden_costs ? `<span>Hidden Costs: ${escapeHtml(comment.hidden_costs)}</span>` : ""}
          </div>

          <div class="comment-scores-grid">
            ${categories.map(([catName, fields]) => `
              <div class="comment-cat">
                <h4>${catName}</h4>
                <div class="scores-list">
                  ${fields.map(f => `
                    <div class="score-line">
                      <span>${labelByField[f]}</span>
                      <strong>${formatScore(f, comment.scores[f])}</strong>
                    </div>
                  `).join("")}
                </div>
              </div>
            `).join("")}
          </div>

          ${comment.comment ? `<p class="comment-text">"${escapeHtml(comment.comment)}"</p>` : ""}
        </article>
      `
    )
    .join("");
}

function formatScore(field, value) {
  if (field === "elevator") return value === 5 ? "Elevator" : "Stairs";
  if (value >= 4) return "Good";
  if (value >= 2) return "Fair";
  return "Poor";
}

function renderAreaObservations(property) {
  const observations = property.area_observations || [];
  if (!observations.length) {
    return `<p class="empty-copy">No nearby shared observations yet.</p>`;
  }

  const getSeverityLabel = (v) => {
    if (v >= 4) return "Low Impact";
    if (v >= 2) return "Moderate";
    return "High Impact";
  };

  return observations
    .map(
      (observation) => `
        <article class="comment">
          <strong>${escapeHtml(observation.observation_kind).replaceAll("_", " ")}</strong>
          <div class="meta-row">
            <span class="pill">${getSeverityLabel(observation.severity)}</span>
            <span>${Math.round(observation.distance_m)} m away</span>
          </div>
          ${observation.note ? `<p>${escapeHtml(observation.note)}</p>` : ""}
        </article>
      `
    )
    .join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

init();
