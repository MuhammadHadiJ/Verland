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
const propertyDialog = document.querySelector("#propertyDialog");
const propertyForm = document.querySelector("#propertyForm");
const propertyError = document.querySelector("#propertyError");
const searchForm = document.querySelector("#searchForm");
const searchInput = document.querySelector("#searchInput");
const autocompleteDropdown = document.querySelector("#autocompleteDropdown");
const mapPanel = document.querySelector("#mapPanel");
const selectedPin = document.querySelector("#selectedPin");
const mapStatus = document.querySelector("#mapStatus");

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
      selectMapLocation({ lat: place.lat, lng: place.lng });
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

propertyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitter = event.submitter;
  if (submitter?.value === "cancel") {
    propertyDialog.close();
    return;
  }

  propertyError.textContent = "";
  const payload = Object.fromEntries(new FormData(propertyForm).entries());
  try {
    const result = await api("/api/properties", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    propertyDialog.close();
    state.selectedId = result.property.id;
    await loadProperties();
  } catch (error) {
    propertyError.textContent = error.message;
  }
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
    lat: Number(location.lat.toFixed(6)),
    lng: Number(location.lng.toFixed(6)),
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
    bindCreatePropertyButton();
    return;
  }

  detailPanel.innerHTML = `
    <section class="property-hero">
      <div class="meta-row">
        <span class="pill">${escapeHtml(property.property_type)}</span>
        <span class="pill">${escapeHtml(property.area)}, ${escapeHtml(property.city)}</span>
        <span class="pill">${property.review_count} structured responses</span>
      </div>
      <h2>${escapeHtml(property.name)}</h2>
      <p>${escapeHtml(property.address)}</p>
      <div class="insight-strip">
        ${metric("Utilities", averageFor(property, ["electricity", "water", "gas"]))}
        ${metric("Building", averageFor(property, ["maintenance", "elevator", "structure", "seepage"]))}
        ${metric("Connectivity", averageFor(property, ["internet", "mobile_signal"]))}
        ${metric("Shared Area", sharedObservationSummary(property))}
      </div>
    </section>

    <div class="content-grid">
      <section class="panel">
        <h2>Response patterns</h2>
        ${categories.map(([name, categoryFields]) => renderCategory(property, name, categoryFields)).join("")}
      </section>

      <section class="panel">
        <h2>Submit structured review</h2>
        ${renderReviewForm(property.id)}
      </section>
    </div>

      <section class="panel comments-panel">
        <h2>Cost notes and comments</h2>
        <div class="comments-list">
          ${renderComments(property)}
        </div>
      </section>

      <section class="panel comments-panel">
        <h2>Nearby shared observations</h2>
        <div class="comments-list">
          ${renderAreaObservations(property)}
        </div>
      </section>
  `;

  const form = detailPanel.querySelector("#reviewForm");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = form.querySelector(".form-error");
    error.textContent = "";
    const payload = Object.fromEntries(new FormData(form).entries());
    try {
      const result = await api(`/api/properties/${property.id}/reviews`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.properties = state.properties.map((item) =>
        item.id === property.id ? result.property : item
      );
      renderList();
      renderDetail();
    } catch (apiError) {
      error.textContent = apiError.message;
    }
  });
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
    <div class="empty-state">
      <h2>No property selected</h2>
      <p>No existing property matched this point. Create the property here, then submit the first structured account.</p>
      <button class="primary-button" id="createPropertyButton" type="button">Create property here</button>
    </div>
  `;
}

function bindCreatePropertyButton() {
  const button = document.querySelector("#createPropertyButton");
  if (!button) return;
  button.addEventListener("click", () => {
    propertyError.textContent = "";
    propertyForm.reset();

    const readOnlyFields = ["propName", "propAddress", "propArea", "propCity"];
    if (state.selectedPlace) {
      propertyForm.elements.name.value = state.selectedPlace.name;
      propertyForm.elements.address.value = state.selectedPlace.address;
      propertyForm.elements.area.value = state.selectedPlace.area;
      propertyForm.elements.city.value = state.selectedPlace.city;
      propertyForm.elements.external_provider.value = state.selectedPlace.provider;
      propertyForm.elements.external_place_id.value = state.selectedPlace.place_id;
      propertyForm.elements.external_display_name.value = state.selectedPlace.display_name;

      readOnlyFields.forEach(id => document.getElementById(id).readOnly = true);
    } else {
      propertyForm.elements.address.value = `${state.selectedLocation.lat}, ${state.selectedLocation.lng}`;
      readOnlyFields.forEach(id => document.getElementById(id).readOnly = false);
    }

    propertyForm.elements.latitude.value = state.selectedLocation.lat;
    propertyForm.elements.longitude.value = state.selectedLocation.lng;
    propertyDialog.showModal();
  });
}

function metric(label, value) {
  return `
    <div class="metric">
      <span>${label}</span>
      <strong>${value ? `${value}/5` : "No data"}</strong>
    </div>
  `;
}

function averageFor(property, selectedFields) {
  const values = selectedFields
    .map((field) => property.averages[field])
    .filter((value) => typeof value === "number");
  if (!values.length) return null;
  return (values.reduce((total, value) => total + value, 0) / values.length).toFixed(1);
}

function sharedObservationSummary(property) {
  const observations = property.area_observations || [];
  if (!observations.length) return null;
  const total = observations.reduce((sum, observation) => sum + Number(observation.severity || 0), 0);
  return (total / observations.length).toFixed(1);
}

function renderCategory(property, name, categoryFields) {
  return `
    <div class="category">
      <h3>${name}</h3>
      ${categoryFields
        .map((field) => {
          const average = property.averages[field];
          return `
            <div class="score-row">
              <span>${labelByField[field]}</span>
              ${renderBar(average)}
              <strong>${average ? average.toFixed(1) : "-"}</strong>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderBar(average) {
  const active = average ? Math.round(average) : 0;
  return `
    <div class="bar" aria-hidden="true">
      ${[1, 2, 3, 4, 5].map((step) => `<span data-active="${step <= active}"></span>`).join("")}
    </div>
  `;
}

function renderReviewForm(propertyId) {
  return `
    <form class="review-form" id="reviewForm" data-property-id="${propertyId}">
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
        Lived or observed period
        <input name="lived_period" placeholder="2023-2025, visited weekly, current">
      </label>
      <div class="scale-grid">
        ${fields.map(([field, label]) => scale(field, label)).join("")}
      </div>
      <label>
        Rent range actually paid
        <input name="rent_range" placeholder="Optional">
      </label>
      <label>
        Hidden costs
        <input name="hidden_costs" placeholder="Maintenance, generator, water tanker">
      </label>
      <label>
        Optional comment
        <textarea name="comment" placeholder="Keep it specific and factual"></textarea>
      </label>
      <p class="form-error"></p>
      <button class="primary-button" type="submit">Submit review</button>
    </form>
  `;
}

function scale(field, label) {
  return `
    <label class="scale-control">
      <span>${label}</span>
      <select name="${field}" required>
        <option value="1">1 - Poor</option>
        <option value="2">2 - Weak</option>
        <option value="3" selected>3 - Mixed</option>
        <option value="4">4 - Good</option>
        <option value="5">5 - Strong</option>
      </select>
    </label>
  `;
}

function renderComments(property) {
  if (!property.comments.length) {
    return `<p class="empty-copy">No cost notes or comments yet.</p>`;
  }

  return property.comments
    .map(
      (comment) => `
        <article class="comment">
          <strong>${escapeHtml(comment.contributor_role)}</strong>
          <div class="meta-row">
            ${comment.lived_period ? `<span>${escapeHtml(comment.lived_period)}</span>` : ""}
            ${comment.rent_range ? `<span>Rent: ${escapeHtml(comment.rent_range)}</span>` : ""}
            ${comment.hidden_costs ? `<span>Costs: ${escapeHtml(comment.hidden_costs)}</span>` : ""}
          </div>
          ${comment.comment ? `<p>${escapeHtml(comment.comment)}</p>` : ""}
        </article>
      `
    )
    .join("");
}

function renderAreaObservations(property) {
  const observations = property.area_observations || [];
  if (!observations.length) {
    return `<p class="empty-copy">No nearby shared observations yet.</p>`;
  }

  return observations
    .map(
      (observation) => `
        <article class="comment">
          <strong>${escapeHtml(observation.observation_kind).replaceAll("_", " ")}</strong>
          <div class="meta-row">
            <span>Severity ${observation.severity}/5</span>
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
