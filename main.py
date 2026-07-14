import base64
import hashlib
import io
import json
import mimetypes
import os
import secrets
import uuid
from datetime import date, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ENV_PATH = BASE_DIR / ".env"

# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------
# API field name → DB column name
REVIEW_DB_FIELDS = {
    "load_shedding":  "electricity",          # reuses electricity column; renamed at API level
    "water_supply":   "water",                # reuses water column; renamed at API level
    "gas":            "gas",
    "maintenance":    "building_maintenance",
    "elevator":       "elevator",
    "parking":        "parking",
    "standby_power":  "standby_power",
    "noise":          "noise",
    "security":       "security",
    "cleanliness":    "cleanliness",
    "traffic":        "traffic",
    "flooding":       "flooding",
}

REVIEW_FIELDS = list(REVIEW_DB_FIELDS.keys())

PROPERTY_SPECIFIC_FIELDS = [
    "load_shedding", "water_supply", "gas", "maintenance",
    "standby_power", "elevator", "parking",
]
NEIGHBORHOOD_FIELDS = [
    "noise", "security", "cleanliness", "traffic", "flooding",
]

# Fields with only two states (present/not) — "Mostly" prefix never applies
BINARY_FIELDS = {"elevator", "parking"}

PROPERTY_TYPES = {"apartment", "house", "plot", "commercial"}

ROLE_VALUES = {
    "Current resident":             "current_resident",
    "Former resident":              "former_resident",
    "Buyer or tenant prospect":     "buyer_or_tenant_prospect",
    "General public contributor":   "general_public_contributor",
    "Owner or landlord":            "owner_or_landlord",
}

# Major urban cities in Pakistan → default property type = apartment
URBAN_CITIES = {
    "karachi", "lahore", "islamabad", "rawalpindi", "faisalabad",
    "multan", "hyderabad", "peshawar", "quetta", "gujranwala",
    "sialkot", "bahawalpur", "sargodha", "sukkur", "larkana",
}

LOCATIONIQ_SEARCH_URL      = "https://api.locationiq.com/v1/search"
LOCATIONIQ_AUTOCOMPLETE_URL = "https://api.locationiq.com/v1/autocomplete"
LOCATIONIQ_REVERSE_URL     = "https://api.locationiq.com/v1/reverse"

# Neighbourhood spatial radius used for aggregation (metres)
NEIGHBOURHOOD_RADIUS_M = 250

# Coordinates used to bias LocationIQ autocomplete toward each city
CITY_COORDS = {
    "karachi":     (24.8607, 67.0011),
    "lahore":      (31.5204, 74.3587),
    "islamabad":   (33.6844, 73.0479),
    "rawalpindi":  (33.5651, 73.0169),
    "faisalabad":  (31.4504, 73.1350),
    "peshawar":    (34.0150, 71.5805),
    "quetta":      (30.1798, 66.9750),
    "multan":      (30.1575, 71.5249),
}
# Default proximity when no city is selected — Karachi
DEFAULT_PROXIMITY = CITY_COORDS["karachi"]

# ---------------------------------------------------------------------------
# City sub-division aliases
# ---------------------------------------------------------------------------
# LocationIQ/Nominatim frequently tags a Pakistani address's "city" field
# with a sub-city administrative unit — a Town, Tehsil, Cantonment, or Zone —
# rather than the metro city itself. E.g. an address in Karachi's Jamshed
# Town gets city="Jamshed Town" from the geocoder, not "Karachi", because
# that's the literal OSM admin boundary the point falls in. An exact-string
# search for "Karachi" would then miss it entirely. This maps every known
# sub-division of each of the app's 8 supported cities back to its canonical
# city, so searching "Karachi" matches any property tagged with a real
# Karachi sub-area, not just the literal string "Karachi".
#
# Researched against Wikipedia and official provincial government sources
# (2026-07) — sources cited per city below. Deliberately excludes bare,
# non-distinctive names that collide across cities (e.g. plain "Saddar",
# which is a real tehsil name in both Lahore and Quetta, or plain
# "Cantonment") — misattributing a property to the wrong city would be worse
# than the current bug, which just makes one hard to find. Also excludes
# Union Council-level detail everywhere (hundreds per city, no single
# authoritative consolidated source). Pakistani administrative boundaries
# are reorganized periodically — Karachi alone has changed twice since 2001
# — so treat this as a practical aid, not an authoritative map.
CITY_SUBDIVISIONS = {
    # https://en.wikipedia.org/wiki/Administrative_divisions_of_Karachi
    "karachi": [
        # Current districts (renamed 2024; these are the new names)
        "gulshan", "orangi", "nazimabad", "malir", "korangi", "keamari",
        # Towns (2001-2011 system; OSM data still commonly uses these)
        "saddar town", "lyari town", "gulshan town", "jinnah town",
        "jamshed town", "safoora goth town", "sohrab goth town",
        "nazimabad town", "north nazimabad town", "gulberg town",
        "liaquatabad town", "new karachi town", "malir town", "gadap town",
        "ibrahim hyderi town", "model colony town", "shah faisal town",
        "korangi town", "landhi town", "orangi town", "mominabad town",
        "manghopir town", "keamari town", "baldia town",
        "moriro mirbahar town",
    ],
    # https://en.wikipedia.org/wiki/Lahore_District ;
    # https://www.dawn.com/news/1855124 (2024 tehsil reorg, 5->10)
    "lahore": [
        "lahore city", "lahore cantonment", "lahore cantt", "model town",
        "raiwind", "shalimar", "shalamar", "ravi", "wagah", "wagha",
        "nishtar", "nishter", "allama iqbal town", "iqbal town",
        "aziz bhatti", "data ganj bakhsh", "gulberg", "samnabad",
    ],
    # https://en.wikipedia.org/wiki/Islamabad_Capital_Territory ;
    # confirmed against live Nominatim queries — Islamabad addresses
    # typically carry no "city" tag at all, using "municipality" (Zone
    # I-V) and "town"/"village" for hyper-local names instead.
    "islamabad": [
        "zone i", "zone ii", "zone iii", "zone iv", "zone v",
        "rawat", "bhara kahu", "nilore", "tarnol", "sihala", "bani gala",
        "nurpur shahan", "golra", "shah allah ditta",
    ],
    # https://en.wikipedia.org/wiki/Rawalpindi_District ;
    # https://en.wikipedia.org/wiki/Rawalpindi_Cantonment
    "rawalpindi": [
        "gujar khan", "kahuta", "kallar syedan", "taxila",
        "rawalpindi cantonment", "rawalpindi cantt", "chaklala",
        "chaklala cantonment", "westridge",
    ],
    # https://en.wikipedia.org/wiki/Faisalabad_District ;
    # https://faisalabad.punjab.gov.pk/district_profile
    "faisalabad": [
        "faisalabad city", "faisalabad sadar", "jaranwala", "tandlianwala",
        "samundri", "chak jhumra",
    ],
    # https://en.wikipedia.org/wiki/Peshawar_District ; confirmed against
    # live Nominatim query — ordinary in-city Peshawar addresses get
    # city="Peshawar City Tehsil" literally, not "Peshawar".
    "peshawar": [
        "peshawar city tehsil", "peshawar cantonment", "peshawar cantt",
        "badbher", "badhaber", "chamkani", "mathra", "pishtakhara",
        "peshtakhara", "shah alam", "hassan khel",
    ],
    # https://en.wikipedia.org/wiki/Quetta_District ;
    # https://en.wikipedia.org/wiki/List_of_tehsils_of_Balochistan
    "quetta": [
        "chiltan", "zarghoon", "panjpai", "quetta sadar", "quetta saddar",
        "kuchlak", "sariab", "quetta city",
    ],
    # https://en.wikipedia.org/wiki/Multan_District ;
    # https://multan.punjab.gov.pk/district_profile
    "multan": [
        "multan city", "multan sadar", "multan saddar", "shujabad",
        "jalalpur pirwala",
    ],
}


def _build_city_aliases():
    """canonical city (lowercase) -> set of every matching city-field string"""
    return {
        canonical: {canonical, *subdivisions}
        for canonical, subdivisions in CITY_SUBDIVISIONS.items()
    }


CITY_ALIASES = _build_city_aliases()

# ---------------------------------------------------------------------------
# Aggregation label map
# ---------------------------------------------------------------------------
LABEL_MAP = {
    "load_shedding":        {5: "Rare",        3: "Moderate",        1: "Frequent"},
    "water_supply":         {5: "Reliable",    3: "Unreliable",      1: "Tanker dependent"},
    "gas":                  {5: "Good",        3: "Fair",            1: "Poor"},
    "maintenance":          {5: "Good",        3: "Fair",            1: "Poor"},
    "building_maintenance": {5: "Good",        3: "Fair",            1: "Poor"},
    "standby_power":        {5: "Generator",   3: "UPS",             1: "None"},
    "elevator":              {5: "Present",                          1: "Stairs"},
    "parking":              {5: "Present",                           1: "None"},
    "noise":                {5: "Low",         3: "Moderate",        1: "High"},
    "security":             {5: "Safe",        3: "Average",         1: "Unsafe"},
    "cleanliness":          {5: "Good",        3: "Fair",            1: "Poor"},
    "traffic":              {5: "Low",         3: "Moderate",        1: "High"},
    "flooding":              {5: "None",       3: "Minor",           1: "Severe"},
}

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------
def read_env():
    # Real environment variables first (how every hosting platform injects
    # secrets) — a local .env file, if present, overrides them for dev.
    values = dict(os.environ)
    if not ENV_PATH.exists():
        return values
    try:
        content = ENV_PATH.read_text(encoding="utf-8")
    except Exception:
        return values
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def supabase_url(env):
    project_ref = env.get("SUPABASE_PROJECT_REF") or env.get("Project_Ref")
    return env.get("SUPABASE_URL") or (
        f"https://{project_ref}.supabase.co" if project_ref else ""
    )


def public_base_url(env):
    """
    The externally-reachable origin this app is served at — used to build
    the OAuth redirect_to URL. Must be set explicitly (not inferred from the
    request's Host header, which a client can spoof) once hosted anywhere
    other than localhost.
    """
    return (env.get("PUBLIC_BASE_URL") or "http://localhost:8000").rstrip("/")


def cookie_secure_suffix(env):
    """`; Secure` once served over HTTPS, nothing on plain local HTTP (browsers
    silently drop Secure cookies set over an insecure origin)."""
    return "; Secure" if public_base_url(env).startswith("https://") else ""


def locationiq_key(env):
    return (
        env.get("LOCATIONIQ_API_KEY")
        or env.get("LocationIQ_API_Key")
        or env.get("LOCATIONIQ_KEY")
    )


def maptiler_key(env):
    return env.get("MAPTILER_API_KEY") or env.get("MAPTILER_KEY") or ""


# ---------------------------------------------------------------------------
# Supabase REST/RPC client
# ---------------------------------------------------------------------------
# Replaces a direct psycopg connection to Postgres. Everything now talks to
# Supabase's PostgREST API over HTTPS instead of raw TCP to port 5432 — that
# means (a) it runs on hosts that only allow outbound HTTP(S), and (b)
# Postgres RLS policies are enforced for real, since PostgREST always
# authenticates as the anon/authenticated role, never a superuser that
# bypasses RLS the way the old direct connection did.
SUPABASE_ANON_KEY_ENV = "SUPABASE_ANON_KEY"


def get_supabase_anon_key(env):
    return env.get(SUPABASE_ANON_KEY_ENV) or env.get("ANON_KEY") or ""


class SupabaseError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _supabase_request(env, method, path, *, params=None, body=None, bearer=None, prefer=None):
    base = supabase_url(env)
    if not base:
        raise SupabaseError(503, "Supabase URL not configured")
    query = f"?{urlencode(params)}" if params else ""
    url = f"{base}{path}{query}"
    headers = {
        "apikey":        get_supabase_anon_key(env),
        "Authorization": f"Bearer {bearer or get_supabase_anon_key(env)}",
        "Content-Type":  "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return json.loads(raw.decode()) if raw else None
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SupabaseError(exc.code, detail) from exc


def supabase_select(env, table, params=None, bearer=None):
    return _supabase_request(env, "GET", f"/rest/v1/{table}", params=params, bearer=bearer) or []


def supabase_insert(env, table, row, bearer=None):
    result = _supabase_request(
        env, "POST", f"/rest/v1/{table}", body=row, bearer=bearer,
        prefer="return=representation",
    )
    return result[0] if result else None


def supabase_delete(env, table, params, bearer=None):
    return _supabase_request(
        env, "DELETE", f"/rest/v1/{table}", params=params, bearer=bearer,
        prefer="return=representation",
    ) or []


def supabase_rpc(env, fn_name, args, bearer=None):
    return _supabase_request(env, "POST", f"/rest/v1/rpc/{fn_name}", body=args, bearer=bearer) or []


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------
def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def row_to_dict(row):
    if row is None:
        return {}
    try:
        return {k: json_value(v) for k, v in dict(row).items()}
    except (TypeError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def parse_body(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise ValueError("Invalid content length")
    try:
        raw = handler.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON") from exc


def clean_text(value, max_length=240):
    return str(value or "").strip()[:max_length]


def coerce_score(payload, field):
    try:
        value = int(payload[field])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{field} must be 1, 3, or 5")
    if value not in (1, 3, 5):
        raise ValueError(f"{field} must be 1, 3, or 5")
    return value


def coerce_binary_score(payload, field):
    """For binary fields that only accept 1 or 5."""
    try:
        value = int(payload[field])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{field} must be 1 or 5")
    if value not in (1, 5):
        raise ValueError(f"{field} must be 1 or 5")
    return value

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_property(payload):
    property_type = clean_text(payload.get("property_type")).lower()
    if property_type not in PROPERTY_TYPES:
        raise ValueError("property_type must be apartment, house, plot, or commercial")

    data = {
        "name":                     clean_text(payload.get("name"), 160),
        "property_type":            property_type,
        "address":                  clean_text(payload.get("address"), 300),
        "area":                     clean_text(payload.get("area"), 120),
        "city":                     clean_text(payload.get("city"), 120),
        "country":                  "Pakistan",
        "latitude":                 payload.get("latitude"),
        "longitude":                payload.get("longitude"),
        "external_provider":        clean_text(payload.get("external_provider"), 80) or "manual",
        "external_place_id":        clean_text(payload.get("external_place_id"), 180) or None,
        "external_display_name":    clean_text(payload.get("external_display_name"), 300) or None,
        "google_place_id":          clean_text(payload.get("google_place_id"), 180) or None,
        "google_place_name":        clean_text(payload.get("google_place_name"), 180) or None,
        "google_formatted_address": clean_text(payload.get("google_formatted_address"), 300) or None,
    }

    for field in ("name", "address", "area", "city"):
        if not data[field]:
            raise ValueError(f"{field} is required")

    for field in ("latitude", "longitude"):
        if data[field] in ("", None):
            raise ValueError(f"{field} is required")
        try:
            data[field] = float(data[field])
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be a number")

    if not 23.0 <= data["latitude"] <= 38.0 or not 60.0 <= data["longitude"] <= 78.0:
        raise ValueError("Location must be inside Pakistan")

    return data


BINARY_FIELDS = {"elevator", "parking"}


def validate_review(payload):
    role_label = clean_text(payload.get("contributor_role"), 80)
    role = ROLE_VALUES.get(role_label, clean_text(role_label).lower())
    if role not in ROLE_VALUES.values():
        raise ValueError("contributor_role is invalid")

    lived_period = clean_text(payload.get("lived_period"), 120)
    # Only residents and owners are expected to report a period
    _period_required_roles = {"current_resident", "former_resident", "owner_or_landlord"}
    if not lived_period and role in _period_required_roles:
        raise ValueError("Observed period is required for residents and owners")

    data = {
        "contributor_role": role,
        "lived_period":     lived_period,
        "rent_range":       clean_text(payload.get("rent_range"), 120),
        "hidden_costs":     clean_text(payload.get("hidden_costs"), 240),
        "comment":          clean_text(payload.get("comment"), 900),
    }

    for field in REVIEW_FIELDS:
        if field in BINARY_FIELDS:
            data[field] = coerce_binary_score(payload, field)
        else:
            data[field] = coerce_score(payload, field)

    return data


def display_role(role):
    for label, value in ROLE_VALUES.items():
        if value == role:
            return label
    return str(role or "").replace("_", " ").title()


# Fix #9: smart property type guess based on city
def guess_property_type(city: str) -> str:
    """Return 'apartment' for major urban centres, 'house' everywhere else."""
    if city and city.strip().lower() in URBAN_CITIES:
        return "apartment"
    return "house"

# ---------------------------------------------------------------------------
# LocationIQ helpers
# ---------------------------------------------------------------------------
def parse_locationiq_place(place):
    address = place.get("address") or {}
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        # Islamabad in particular usually has no "city" tag at all — Nominatim
        # puts its Zone I-V designation in "municipality" instead.
        or address.get("municipality")
        or address.get("county")
        or ""
    )
    area = (
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("quarter")
        or address.get("state_district")
        or address.get("state")
        or city
        or ""
    )
    name = place.get("namedetails", {}).get("name") or place.get("name")
    display_name = place.get("display_name") or ""
    if not name:
        name = display_name.split(",", 1)[0] if display_name else "Unnamed property"

    lat = float(place["lat"])
    lng = float(place["lon"])   # LocationIQ always returns "lon"

    return {
        "provider":      "locationiq",
        "place_id":      str(place.get("place_id") or place.get("osm_id") or ""),
        "display_name":  display_name,
        "name":          name,
        "address":       display_name,
        "area":          area,
        "city":          city,
        "lat":           lat,
        "lng":           lng,   # Fix #11: always use "lng", never "lon"
        "raw":           place,
    }


def locationiq_search(query, limit=6, proximity=None):
    env = read_env()
    api_key = locationiq_key(env)
    if not api_key:
        raise ValueError("LOCATIONIQ_API_KEY is missing from .env")

    lat, lng = proximity if proximity else DEFAULT_PROXIMITY
    params = {
        "key":            api_key,
        "q":              query,
        "format":         "json",
        "countrycodes":   "pk",
        "addressdetails": 1,
        "namedetails":    1,
        "limit":          limit,
        "lat":            lat,
        "lon":            lng,
    }
    url = f"{LOCATIONIQ_AUTOCOMPLETE_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "RealEstateRealityMVP/0.1"})
    try:
        with urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        fallback_url = f"{LOCATIONIQ_SEARCH_URL}?{urlencode(params)}"
        req = Request(fallback_url, headers={"User-Agent": "RealEstateRealityMVP/0.1"})
        with urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))

    return [parse_locationiq_place(p) for p in payload]

# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def get_dominant_label(counts, field_id):
    """
    Returns "Mostly X" when one option has the clear lead across 2+ reviews.
    Returns the plain label for binary fields or single-review cases.
    Returns None when tied (frontend renders distribution from counts) or no data.
    """
    filtered = {k: v for k, v in counts.items() if v > 0}
    if not filtered:
        return None

    total = sum(filtered.values())
    max_count = max(filtered.values())
    winners = [k for k, v in filtered.items() if v == max_count]
    labels = LABEL_MAP.get(field_id, {})

    if len(winners) > 1:
        # Tied — return None so the frontend renders a distribution from counts
        return None

    label = labels.get(winners[0], str(winners[0]))
    # Binary fields are facts, not majorities — skip "Mostly" prefix entirely
    # Single review — no majority exists yet, just state the label
    if field_id in BINARY_FIELDS or total == 1:
        return label
    return f"Mostly {label}"


def aggregate_field(reviews, api_field):
    """Build counts dict for a single field across a list of review dicts."""
    db_field = REVIEW_DB_FIELDS.get(api_field)
    if not db_field:
        return None
    counts = {5: 0, 3: 0, 1: 0}
    for r in reviews:
        val = r.get(db_field)
        if val in counts:
            counts[val] += 1
    return counts

# ---------------------------------------------------------------------------
# Property summary — Fix #13: no more N+1 queries
# ---------------------------------------------------------------------------
def property_summary(env, property_row, reviews_by_id=None, nearby_reviews_by_id=None, bearer=None):
    """
    Build the full property dict with stats and comments.

    When called from list view, reviews_by_id and nearby_reviews_by_id are
    pre-fetched dicts keyed by property_id (batch mode — no extra requests).
    When called for a single property, fetches its own data via RPC calls.
    """
    if property_row is None:
        return {}

    property_data = row_to_dict(property_row)
    property_id = property_data.get("id")
    lat = property_data.get("latitude")
    lng = property_data.get("longitude")

    property_data.pop("location", None)
    if property_data.get("distance_m") is not None:
        property_data["distance_km"] = round(
            float(property_data.pop("distance_m")) / 1000, 3
        )
    else:
        property_data.pop("distance_m", None)

    # Fetch reviews if not pre-supplied (single property page)
    if reviews_by_id is None:
        reviews = []
        nearby_reviews = []
        if property_id and lat is not None and lng is not None:
            try:
                reviews = supabase_rpc(
                    env, "batch_reviews_for_properties",
                    {"property_ids": [property_id]}, bearer=bearer,
                )
                nearby_reviews = supabase_rpc(
                    env, "nearby_property_reviews",
                    {"lat": lat, "lng": lng, "radius_m": NEIGHBOURHOOD_RADIUS_M},
                    bearer=bearer,
                )
            except SupabaseError as e:
                print(f"!! Supabase ERROR in property_summary: {e}")
    else:
        reviews        = reviews_by_id.get(property_id, [])
        nearby_reviews = nearby_reviews_by_id.get(property_id, [])

    property_data["review_count"] = len(reviews)

    # Aggregate property-specific fields
    property_stats = {}
    for field in PROPERTY_SPECIFIC_FIELDS:
        counts = aggregate_field(reviews, field)
        if counts is None:
            continue
        field_total = sum(counts.values())
        if field_total == 0:
            continue
        property_stats[field] = {
            "dominant": get_dominant_label(counts, field),
            "counts":   counts,
            "total":    field_total,
        }

    # Aggregate neighbourhood fields
    neighborhood_stats = {}
    for field in NEIGHBORHOOD_FIELDS:
        counts = aggregate_field(nearby_reviews, field)
        if counts is None:
            continue
        field_total = sum(counts.values())
        if field_total == 0:
            continue
        neighborhood_stats[field] = {
            "dominant": get_dominant_label(counts, field),
            "counts":   counts,
            "total":    field_total,
        }

    property_data["property_stats"]    = property_stats
    property_data["neighborhood_stats"] = neighborhood_stats
    property_data["comments"] = [
        {
            "id":               str(r.get("id")),
            "reviewer_id":      str(r.get("user_id")) if r.get("user_id") else None,
            "reviewer_name":    r.get("reviewer_name") or "Verified Contributor",
            "contributor_role": display_role(r.get("contributor_role")),
            "lived_period":     r.get("lived_period"),
            "rent_range":       r.get("rent_range"),
            "hidden_costs":     r.get("hidden_costs"),
            "comment":          r.get("comment"),
            "created_at":       json_value(r.get("created_at") or datetime.now()),
            "scores": {
                api_field: r.get(db_col)
                for api_field, db_col in REVIEW_DB_FIELDS.items()
            },
        }
        for r in reviews
    ]
    return property_data

# ---------------------------------------------------------------------------
# Batch-fetch helpers (Fix #13 — used by list endpoint)
# ---------------------------------------------------------------------------
def batch_fetch_reviews(env, property_ids, lat_lng_by_id, bearer=None):
    """
    Returns (reviews_by_id, nearby_reviews_by_id) dicts.
    Fires exactly 2 RPC calls regardless of how many properties are in the list.
    """
    if not property_ids:
        return {}, {}

    id_list = list(property_ids)

    try:
        all_reviews = supabase_rpc(
            env, "batch_reviews_for_properties", {"property_ids": id_list}, bearer=bearer
        )
    except SupabaseError as e:
        print(f"!! Supabase ERROR in batch_fetch_reviews (reviews): {e}")
        all_reviews = []

    nearby_by_id = {pid: [] for pid in id_list}
    if lat_lng_by_id:
        anchors = [
            {"id": pid, "lat": lat, "lng": lng}
            for pid, (lat, lng) in lat_lng_by_id.items()
        ]
        try:
            nearby_rows = supabase_rpc(
                env, "batch_nearby_reviews",
                {"anchors": anchors, "radius_m": NEIGHBOURHOOD_RADIUS_M},
                bearer=bearer,
            )
        except SupabaseError as e:
            print(f"!! Supabase ERROR in batch_fetch_reviews (nearby): {e}")
            nearby_rows = []
        for row in nearby_rows:
            anchor = str(row.pop("anchor_id"))
            nearby_by_id.setdefault(anchor, []).append(row)

    reviews_by_id = {pid: [] for pid in id_list}
    for r in all_reviews:
        pid = str(r.get("property_id"))
        reviews_by_id.setdefault(pid, []).append(r)

    return reviews_by_id, nearby_by_id

# ---------------------------------------------------------------------------
# Auth helpers (Supabase Auth via PKCE / server-side session cookie)
# ---------------------------------------------------------------------------
def generate_pkce_pair():
    """
    RFC 7636 PKCE pair: a random verifier, and its SHA-256 challenge
    (base64url, no padding) — matches the exact derivation Supabase's own
    auth-js client uses, verified against its source rather than guessed.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def exchange_pkce_code(env, auth_code, code_verifier):
    """
    Exchange a PKCE auth code + its verifier for a Supabase session.
    Returns the session dict on success, raises on failure.

    Endpoint/body shape (grant_type=pkce, auth_code + code_verifier keys) is
    not documented in Supabase's prose docs — confirmed directly against
    auth-js's _exchangeCodeForSession in GoTrueClient.ts to avoid guessing
    at an API contract that would silently break sign-in if wrong.
    """
    base = supabase_url(env)
    if not base:
        raise ValueError("Supabase URL not configured")

    data = json.dumps({
        "auth_code":     auth_code,
        "code_verifier": code_verifier,
    }).encode()
    req = Request(
        f"{base}/auth/v1/token?grant_type=pkce",
        data=data,
        headers={
            "Content-Type": "application/json",
            "apikey":       get_supabase_anon_key(env),
        },
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def refresh_session(env, refresh_token):
    """
    Exchange a refresh token for a new Supabase session.
    Returns the session dict on success, raises on failure.
    """
    base = supabase_url(env)
    if not base:
        raise ValueError("Supabase URL not configured")

    data = json.dumps({"refresh_token": refresh_token}).encode()
    req = Request(
        f"{base}/auth/v1/token?grant_type=refresh_token",
        data=data,
        headers={
            "Content-Type": "application/json",
            "apikey":       get_supabase_anon_key(env),
        },
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def get_user_from_token(env, access_token):
    """Validate a JWT and return the user dict, or None if invalid."""
    base = supabase_url(env)
    if not base or not access_token:
        return None
    req = Request(
        f"{base}/auth/v1/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey":        get_supabase_anon_key(env),
        },
    )
    try:
        with urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def parse_session_cookie(handler):
    """Return (access_token, refresh_token) from the session cookie, or (None, None)."""
    cookie_header = handler.headers.get("Cookie", "")
    tokens = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            tokens[k.strip()] = v.strip()
    return tokens.get("sb_access_token"), tokens.get("sb_refresh_token")

# ---------------------------------------------------------------------------
# Static file resolution (shared by both transports below)
# ---------------------------------------------------------------------------
def resolve_static_path(path):
    parsed = urlparse(path)
    requested = parsed.path
    static_root = STATIC_DIR.resolve()
    candidate = (STATIC_DIR / requested.lstrip("/")).resolve()
    within_static = candidate == static_root or static_root in candidate.parents
    # SPA fallback: any non-API route without a matching static file
    # (e.g. /property/<id>, /search) gets the app shell so client-side
    # routing can take over on direct load / hard refresh.
    if requested != "/" and within_static and candidate.is_file():
        return candidate
    return STATIC_DIR / "index.html"


STATIC_CONTENT_TYPES = {
    ".html": "text/html",
    ".js":   "application/javascript",
    ".css":  "text/css",
    ".json": "application/json",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
}


def guess_static_content_type(path):
    return (
        STATIC_CONTENT_TYPES.get(path.suffix.lower())
        or mimetypes.guess_type(str(path))[0]
        or "application/octet-stream"
    )


# ---------------------------------------------------------------------------
# Request handling — routing + all /api/* logic, written against a small
# request/response surface (self.path, self.headers, self.rfile, self.wfile,
# send_response/send_header/end_headers/serve_static) rather than any one
# transport. Two concrete transports implement that surface below:
# AppHandler (a real socket, via http.server — used by `python3 main.py`
# locally or on any host that allows a long-running process) and
# WSGIHandler (a WSGI environ — used by hosts that only allow WSGI web apps,
# e.g. PythonAnywhere's free tier, which has no "always-on task" option).
# ---------------------------------------------------------------------------
class RequestHandlerMixin:
    def send_json(self, payload, status=HTTPStatus.OK):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        # Set by _resolve_session() when an expired access token was
        # transparently renewed via the refresh token during this request.
        for cookie in getattr(self, "_pending_set_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def send_error_json(self, message, status=HTTPStatus.BAD_REQUEST):
        self.send_json({"error": message}, status)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/properties":
            self.handle_list_properties(parsed)
            return
        if path == "/api/config":
            self.handle_config()
            return
        if path == "/api/location-search":
            self.handle_location_search(parsed)
            return
        if path == "/api/location-reverse":
            self.handle_location_reverse(parsed)
            return
        if path == "/api/auth/signin":
            self.handle_auth_signin(parsed)
            return
        if path == "/api/auth/callback":
            self.handle_auth_callback(parsed)
            return
        if path == "/api/auth/me":
            self.handle_auth_me()
            return
        if path == "/api/auth/signout":
            self.handle_auth_signout()
            return
        if path == "/api/neighbourhood-preview":
            self.handle_neighbourhood_preview(parsed)
            return
        if path.startswith("/api/properties/"):
            property_id = path.split("/")[-1]
            self.handle_get_property(property_id)
            return

        self.serve_static()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/properties/new/reviews":
            self.handle_create_review(None)
            return
        if path.startswith("/api/properties/") and path.endswith("/reviews"):
            parts = path.split("/")
            self.handle_create_review(parts[3])
            return
        if path == "/api/properties":
            self.handle_create_property()
            return

        self.send_error_json("Not found", HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/api/reviews/"):
            review_id = path.split("/")[-1]
            self.handle_delete_review(review_id)
            return

        self.send_error_json("Not found", HTTPStatus.NOT_FOUND)

    def handle_delete_review(self, review_id):
        user_id = self._get_authenticated_user_id()
        if not user_id:
            self.send_error_json("Sign in to delete a review", HTTPStatus.UNAUTHORIZED)
            return
        try:
            review_id = str(uuid.UUID(review_id))
        except (ValueError, AttributeError):
            self.send_error_json("Invalid review ID", HTTPStatus.BAD_REQUEST)
            return

        access_token, _ = parse_session_cookie(self)
        env = read_env()
        try:
            # RLS scopes this delete to rows owned by the caller, so an empty
            # result means "not found" or "not yours" — indistinguishable
            # from the delete alone. Only pay for the extra lookup on that
            # path, to tell the two apart for the response.
            deleted = supabase_delete(
                env, "property_reviews",
                {"id": f"eq.{review_id}", "select": "id,property_id"},
                bearer=access_token,
            )
            if not deleted:
                still_exists = supabase_select(
                    env, "property_reviews", {"id": f"eq.{review_id}", "limit": "1"}
                )
                if still_exists:
                    self.send_error_json("Not your review", HTTPStatus.FORBIDDEN)
                else:
                    self.send_error_json("Review not found", HTTPStatus.NOT_FOUND)
                return

            property_id = str(deleted[0]["property_id"])
            prop_matches = supabase_select(
                env, "properties", {"id": f"eq.{property_id}", "limit": "1"}
            )
            prop_row = prop_matches[0] if prop_matches else None
            if prop_row:
                summary = property_summary(env, prop_row, bearer=access_token)
                self.send_json({"property": summary})
            else:
                self.send_json({"ok": True})
        except SupabaseError as exc:
            self.send_error_json(f"Delete failed: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    # ------------------------------------------------------------------
    # Auth endpoints (Fix #1 / Phase 3)
    # ------------------------------------------------------------------
    def handle_auth_signin(self, parsed):
        """
        Redirect the browser to Supabase OAuth for Google, using PKCE —
        the code_verifier lives only in a short-lived HttpOnly cookie on
        this server, never in anything the browser's JS or URL bar can see.
        """
        env = read_env()
        base = supabase_url(env)
        if not base:
            self.send_error_json("Supabase not configured", HTTPStatus.SERVICE_UNAVAILABLE)
            return

        params = parse_qs(parsed.query)
        provider = params.get("provider", ["google"])[0].lower()
        if provider not in ("google",):
            self.send_error_json("Unsupported provider", HTTPStatus.BAD_REQUEST)
            return

        verifier, challenge = generate_pkce_pair()
        oauth_params = urlencode({
            "provider":              provider,
            "redirect_to":           f"{public_base_url(env)}/api/auth/callback",
            "code_challenge":        challenge,
            "code_challenge_method": "s256",
        })
        supabase_oauth_url = f"{base}/auth/v1/authorize?{oauth_params}"

        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", supabase_oauth_url)
        self.send_header(
            "Set-Cookie",
            f"sb_pkce_verifier={verifier}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age=600{cookie_secure_suffix(env)}"
        )
        self.end_headers()

    def handle_auth_callback(self, parsed):
        """
        Supabase redirects here after OAuth with the auth code as a query
        param (?code=...) — unlike the old implicit flow, the PKCE code is
        useless without the verifier cookie that never leaves this server,
        so the access/refresh tokens never appear in the browser's URL bar
        or history at all, not even momentarily.
        """
        env = read_env()
        secure = cookie_secure_suffix(env)
        code = parse_qs(parsed.query).get("code", [None])[0]

        verifier = None
        for part in self.headers.get("Cookie", "").split(";"):
            part = part.strip()
            if part.startswith("sb_pkce_verifier="):
                verifier = part.split("=", 1)[1]
                break

        access_token = refresh_token = None
        if code and verifier:
            try:
                session = exchange_pkce_code(env, code, verifier)
                access_token  = session.get("access_token")
                refresh_token = session.get("refresh_token")
            except Exception as e:
                print(f"!! OAuth code exchange failed: {e}")

        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", "/?restore=1" if access_token else "/")
        if access_token:
            self.send_header(
                "Set-Cookie",
                f"sb_access_token={access_token}; Path=/; HttpOnly; SameSite=Lax{secure}"
            )
        if refresh_token:
            self.send_header(
                "Set-Cookie",
                f"sb_refresh_token={refresh_token}; Path=/; HttpOnly; SameSite=Lax{secure}"
            )
        self.send_header("Set-Cookie", f"sb_pkce_verifier=; Path=/; Max-Age=0; HttpOnly{secure}")
        self.end_headers()

    def handle_auth_me(self):
        """Return the current user from session cookie, or 401."""
        user = self._resolve_session()
        if not user:
            self.send_error_json("Session expired", HTTPStatus.UNAUTHORIZED)
            return

        meta = user.get("user_metadata") or {}
        self.send_json({
            "id":         user.get("id"),
            "email":      user.get("email"),
            "name":       (
                meta.get("full_name")
                or meta.get("name")
                or user.get("email", "").split("@")[0]
            ),
            "provider":   user.get("app_metadata", {}).get("provider", "google"),
            "avatar_url": meta.get("avatar_url") or meta.get("picture") or None,
        })

    def handle_auth_signout(self):
        """Clear session cookies."""
        secure = cookie_secure_suffix(read_env())
        self.send_response(HTTPStatus.OK)
        self.send_header("Set-Cookie", f"sb_access_token=; Path=/; Max-Age=0; HttpOnly{secure}")
        self.send_header("Set-Cookie", f"sb_refresh_token=; Path=/; Max-Age=0; HttpOnly{secure}")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _get_authenticated_user_id(self):
        """
        Returns the authenticated user_id string, or None if not signed in.
        Reads from session cookie (real auth) with no fallback to mock headers.
        """
        user = self._resolve_session()
        return user.get("id") if user else None

    def _resolve_session(self):
        """
        Returns the authenticated user dict, or None.

        A Supabase access token is a short-lived JWT (~1hr default) — without
        this, every session would silently die mid-use with a generic "sign
        in" error despite a valid refresh token sitting right in the cookie.
        On an expired access token, transparently exchanges the refresh
        token for a new session and queues the renewed cookies to go out
        with whatever response send_json() ends up sending for this request.
        """
        access_token, refresh_token = parse_session_cookie(self)
        if not access_token:
            return None

        env = read_env()
        user = get_user_from_token(env, access_token)
        if user:
            return user

        if not refresh_token:
            return None
        try:
            session = refresh_session(env, refresh_token)
        except Exception:
            return None

        new_access = session.get("access_token")
        if not new_access:
            return None
        user = get_user_from_token(env, new_access)
        if not user:
            return None

        new_refresh = session.get("refresh_token", refresh_token)
        secure = cookie_secure_suffix(env)
        self._pending_set_cookies = [
            f"sb_access_token={new_access}; Path=/; HttpOnly; SameSite=Lax{secure}",
            f"sb_refresh_token={new_refresh}; Path=/; HttpOnly; SameSite=Lax{secure}",
        ]
        return user

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    def handle_config(self):
        env = read_env()
        self.send_json({
            "hasLocationIqKey": bool(locationiq_key(env)),
            "supabaseUrl":      supabase_url(env),
            "hasSupabaseKey":   bool(get_supabase_anon_key(env)),
            "maptilerApiKey":   maptiler_key(env),
        })

    # ------------------------------------------------------------------
    # Location endpoints
    # ------------------------------------------------------------------
    def handle_location_search(self, parsed):
        params = parse_qs(parsed.query)
        query = clean_text(params.get("q", [""])[0], 180)
        if len(query) < 3:
            self.send_json({"places": []})
            return
        city = clean_text(params.get("city", [""])[0], 50).lower()
        proximity = CITY_COORDS.get(city) or DEFAULT_PROXIMITY
        try:
            places = locationiq_search(query, proximity=proximity)
        except ValueError as exc:
            self.send_error_json(str(exc))
            return
        except Exception as exc:
            self.send_error_json(
                f"Location search failed: {exc}", HTTPStatus.BAD_GATEWAY
            )
            return
        self.send_json({"places": places})

    def handle_location_reverse(self, parsed):
        params = parse_qs(parsed.query)
        lat = params.get("lat", [""])[0]
        lng = params.get("lng", [""])[0]
        if not lat or not lng:
            self.send_error_json("lat and lng are required")
            return

        env = read_env()
        api_key = locationiq_key(env)
        if not api_key:
            self.send_error_json("LOCATIONIQ_API_KEY is missing from .env")
            return

        query_params = {
            "key":          api_key,
            "lat":          lat,
            "lon":          lng,
            "format":       "json",
            "addressdetails": 1,
            "namedetails":  1,
        }
        url = f"{LOCATIONIQ_REVERSE_URL}?{urlencode(query_params)}"
        req = Request(url, headers={"User-Agent": "RealEstateRealityMVP/0.1"})
        try:
            with urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.send_json({"place": parse_locationiq_place(payload)})
        except Exception as exc:
            self.send_error_json(
                f"Reverse geocoding failed: {exc}", HTTPStatus.BAD_GATEWAY
            )

    # ------------------------------------------------------------------
    # Property list — Fix #13: batch queries
    # ------------------------------------------------------------------
    def handle_list_properties(self, parsed):
        params     = parse_qs(parsed.query)
        query      = clean_text(params.get("q",    [""])[0], 120).lower()
        city       = clean_text(params.get("city", [""])[0], 120).lower()
        lat        = params.get("lat",       [""])[0]
        lng        = params.get("lng",       [""])[0]
        radius_km  = params.get("radius_km", ["0.075"])[0]

        rpc_args = {
            "search_query": query or None,
            "city_aliases": list(CITY_ALIASES.get(city, {city})) if city else None,
            "origin_lat":   None,
            "origin_lng":   None,
            "radius_m":     None,
        }
        if lat and lng:
            try:
                rpc_args["origin_lat"] = float(lat)
                rpc_args["origin_lng"] = float(lng)
                rpc_args["radius_m"]   = float(radius_km) * 1000
            except ValueError:
                self.send_error_json("lat, lng, and radius_km must be numbers")
                return

        env = read_env()
        try:
            rows = supabase_rpc(env, "search_properties", rpc_args)
        except SupabaseError as e:
            print(f"!! Supabase ERROR in list_properties: {e}")
            self.send_error_json("Database query failed.")
            return

        if not rows:
            self.send_json({"properties": []})
            return

        # Batch-fetch all reviews in 2 RPC calls
        property_ids  = [str(r["id"]) for r in rows]
        lat_lng_by_id = {
            str(r["id"]): (r["latitude"], r["longitude"])
            for r in rows
            if r.get("latitude") is not None and r.get("longitude") is not None
        }
        reviews_by_id, nearby_by_id = batch_fetch_reviews(env, property_ids, lat_lng_by_id)

        self.send_json({
            "properties": [
                property_summary(env, row, reviews_by_id, nearby_by_id)
                for row in rows
            ]
        })

    # ------------------------------------------------------------------
    # Single property
    # ------------------------------------------------------------------
    def handle_get_property(self, property_id):
        env = read_env()
        try:
            matches = supabase_select(
                env, "properties", {"id": f"eq.{property_id}", "limit": "1"}
            )
        except SupabaseError as e:
            self.send_error_json(f"Database query failed: {e}", HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if not matches:
            self.send_error_json("Property not found", HTTPStatus.NOT_FOUND)
            return
        self.send_json({"property": property_summary(env, matches[0])})

    # ------------------------------------------------------------------
    # Neighbourhood preview (for unregistered map locations)
    # ------------------------------------------------------------------
    def handle_neighbourhood_preview(self, parsed):
        params = parse_qs(parsed.query)
        try:
            lat = float(params.get("lat", [None])[0])
            lng = float(params.get("lng", [None])[0])
        except (TypeError, ValueError):
            self.send_error_json("lat and lng are required numbers")
            return

        env = read_env()
        try:
            nearby_reviews = supabase_rpc(
                env, "nearby_property_reviews",
                {"lat": lat, "lng": lng, "radius_m": NEIGHBOURHOOD_RADIUS_M},
            )
        except SupabaseError as e:
            self.send_error_json(f"Database query failed: {e}", HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        neighborhood_stats = {}
        for field in NEIGHBORHOOD_FIELDS:
            counts = aggregate_field(nearby_reviews, field)
            if counts is None:
                continue
            field_total = sum(counts.values())
            if field_total == 0:
                continue
            neighborhood_stats[field] = {
                "dominant": get_dominant_label(counts, field),
                "counts":   counts,
                "total":    field_total,
            }

        self.send_json({
            "review_count": len(nearby_reviews),
            "neighborhood_stats": neighborhood_stats,
        })

    # ------------------------------------------------------------------
    # Create property — now requires sign-in (previously unauthenticated;
    # RLS's "created_by = auth.uid()" insert check never actually ran
    # because the old connection used the postgres superuser role, which
    # bypasses RLS entirely).
    # ------------------------------------------------------------------
    def handle_create_property(self):
        try:
            body = parse_body(self)
            data = validate_property(body)
        except ValueError as exc:
            self.send_error_json(str(exc))
            return

        user_id = self._get_authenticated_user_id()
        if not user_id:
            self.send_error_json(
                "Sign in with Google to add a property.", HTTPStatus.UNAUTHORIZED
            )
            return

        access_token, _ = parse_session_cookie(self)
        env = read_env()
        row = {
            **data,
            "map_provider":     data["external_provider"],
            "external_payload": body.get("external_payload") or data,
            "created_by":       user_id,
        }
        try:
            created = supabase_insert(env, "properties", row, bearer=access_token)
        except SupabaseError as e:
            print(f"!! Supabase ERROR in create_property: {e}")
            self.send_error_json("Failed to create property in database.")
            return

        self.send_json(
            {"property": property_summary(env, created, bearer=access_token)},
            HTTPStatus.CREATED,
        )

    # ------------------------------------------------------------------
    # Create review — Fix #1: real auth, Fix #9: smart property type
    # ------------------------------------------------------------------
    def handle_create_review(self, property_id):
        try:
            body = parse_body(self)
            data = validate_review(body)
        except ValueError as exc:
            self.send_error_json(str(exc))
            return

        # Real auth — no mock fallback
        user_id = self._get_authenticated_user_id()
        if not user_id:
            self.send_error_json(
                "Sign in with Google to submit a review.",
                HTTPStatus.UNAUTHORIZED,
            )
            return

        access_token, _ = parse_session_cookie(self)
        env = read_env()

        try:
            if not property_id:
                place = body.get("place")
                if not place or not place.get("display_name"):
                    self.send_error_json(
                        "A valid geocoded address is required."
                    )
                    return

                lat = float(place["lat"])
                lng = float(place.get("lng") or place.get("lon"))
                existing_row = None

                if place.get("place_id"):
                    matches = supabase_select(
                        env, "properties",
                        {
                            "external_provider": f"eq.{place.get('provider', 'locationiq')}",
                            "external_place_id": f"eq.{place['place_id']}",
                            "limit": "1",
                        },
                        bearer=access_token,
                    )
                    existing_row = matches[0] if matches else None

                if not existing_row:
                    nearby = supabase_rpc(
                        env, "find_property_by_location",
                        {"lat": lat, "lng": lng, "radius_m": 20},
                        bearer=access_token,
                    )
                    existing_row = nearby[0] if nearby else None

                if existing_row:
                    property_row = existing_row
                    property_id  = str(property_row.get("id"))
                else:
                    name = (
                        place.get("name")
                        or place.get("display_name", "").split(",", 1)[0]
                    )
                    # Fix #9: guess property type from city
                    ptype = guess_property_type(place.get("city", ""))
                    new_property = {
                        "name":                  name,
                        "property_type":         ptype,
                        "address":               place.get("display_name"),
                        "area":                  place.get("area") or "",
                        "city":                  place.get("city") or "",
                        "country":               "Pakistan",
                        "latitude":              lat,
                        "longitude":             lng,
                        "external_provider":     place.get("provider", "locationiq"),
                        "external_place_id":     str(place.get("place_id", "")),
                        "external_display_name": place.get("display_name"),
                        "map_provider":          "locationiq",
                        "external_payload":      place.get("raw") or {},
                        "created_by":            user_id,
                    }
                    property_row = supabase_insert(
                        env, "properties", new_property, bearer=access_token
                    )
                    property_id  = str(property_row.get("id"))
            else:
                matches = supabase_select(
                    env, "properties", {"id": f"eq.{property_id}", "limit": "1"},
                    bearer=access_token,
                )
                property_row = matches[0] if matches else None
                if property_row is None:
                    self.send_error_json(
                        "Property not found", HTTPStatus.NOT_FOUND
                    )
                    return
                property_id = str(property_row.get("id"))

            review_row = {
                "property_id":          property_id,
                "user_id":              user_id,
                "contributor_role":     data["contributor_role"],
                "lived_period":         data["lived_period"],
                "rent_range":           data["rent_range"],
                "hidden_costs":         data["hidden_costs"],
                "comment":              data["comment"],
                "electricity":          data["load_shedding"],    # → electricity column
                "water":                data["water_supply"],     # → water column
                "gas":                  data["gas"],
                "building_maintenance": data["maintenance"],      # → building_maintenance column
                "elevator":             data["elevator"],
                "parking":              data["parking"],
                "standby_power":        data["standby_power"],
                "noise":                data["noise"],
                "security":             data["security"],
                "cleanliness":          data["cleanliness"],
                "traffic":              data["traffic"],
                "flooding":             data["flooding"],
            }
            supabase_insert(env, "property_reviews", review_row, bearer=access_token)
            print(f"++ Review saved: property {property_id}, user {user_id}")
            self.send_json(
                {"property": property_summary(env, property_row, bearer=access_token)},
                HTTPStatus.CREATED,
            )
        except SupabaseError as e:
            print(f"!! SQL ERROR in create_review: {e}")
            self.send_error_json(f"Database error: {e}")


# ---------------------------------------------------------------------------
# Transport 1: real socket, via http.server (local dev / any host that
# allows a long-running process to bind its own port).
# ---------------------------------------------------------------------------
class AppHandler(RequestHandlerMixin, SimpleHTTPRequestHandler):
    # Without this, SimpleHTTPRequestHandler falls back to the system's
    # mimetypes database, which disagreed with WSGIHandler's explicit
    # STATIC_CONTENT_TYPES on .js (text/javascript vs application/javascript)
    # depending on Python/OS version -- harmless to browsers either way, but
    # keeps both transports serving identical headers for the same file.
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        **STATIC_CONTENT_TYPES,
    }

    def translate_path(self, path):
        return str(resolve_static_path(path))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def serve_static(self):
        # Bypass RequestHandlerMixin in the MRO (super() here would hit
        # RequestHandlerMixin.do_GET again, not the file-serving one) and go
        # straight to SimpleHTTPRequestHandler's real static-file handler.
        SimpleHTTPRequestHandler.do_GET(self)


# ---------------------------------------------------------------------------
# Transport 2: WSGI, for hosts that only allow a WSGI web app rather than a
# custom always-on process (e.g. PythonAnywhere's free tier). Drives the
# exact same RequestHandlerMixin routing/handler code as AppHandler; only
# the request-in/response-out plumbing differs.
# ---------------------------------------------------------------------------
class _WSGIHeaders:
    """Minimal `.get(key, default)` shim over a WSGI environ, matching the
    subset of the http.client.HTTPMessage interface this app's handler
    methods actually use (parse_body's Content-Length, cookie parsing)."""

    def __init__(self, environ):
        self._environ = environ

    def get(self, key, default=None):
        key = key.upper().replace("-", "_")
        if key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            return self._environ.get(key, default)
        return self._environ.get(f"HTTP_{key}", default)


class WSGIHandler(RequestHandlerMixin):
    def __init__(self, environ):
        query = environ.get("QUERY_STRING", "")
        self.path = environ.get("PATH_INFO", "/") + (f"?{query}" if query else "")
        self.headers = _WSGIHeaders(environ)
        self.rfile = environ.get("wsgi.input")
        self.wfile = io.BytesIO()
        self.command = environ.get("REQUEST_METHOD", "GET")
        self._status = HTTPStatus.OK
        self._response_headers = []

    def send_response(self, status, message=None):
        self._status = status

    def send_header(self, key, value):
        self._response_headers.append((key, str(value)))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")

    def serve_static(self):
        file_path = resolve_static_path(self.path)
        try:
            data = file_path.read_bytes()
        except OSError:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", guess_static_content_type(file_path))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self):
        if self.command == "GET":
            self.do_GET()
        elif self.command == "POST":
            self.do_POST()
        elif self.command == "DELETE":
            self.do_DELETE()
        else:
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Content-Length", "0")
            self.end_headers()
        return self._status, self._response_headers, self.wfile.getvalue()


def application(environ, start_response):
    """WSGI entry point — point a WSGI host's config at `main.application`."""
    handler = WSGIHandler(environ)
    status, headers, body = handler.dispatch()
    status_line = (
        f"{status.value} {status.phrase}" if isinstance(status, HTTPStatus) else str(status)
    )
    start_response(status_line, headers)
    return [body]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run(host="0.0.0.0", port=None):
    # Most hosting platforms assign the port dynamically via $PORT and expect
    # the app to bind to whatever they provide, not a hardcoded value.
    if port is None:
        port = int(os.environ.get("PORT", 8000))

    env = read_env()
    if not supabase_url(env) or not get_supabase_anon_key(env):
        print("!! WARNING: SUPABASE_URL / SUPABASE_ANON_KEY not set — API calls will fail.")

    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Real Estate Reality running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
