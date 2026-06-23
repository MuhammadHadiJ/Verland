import json
import os
import uuid
from datetime import date, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import psycopg
from psycopg.rows import dict_row


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ENV_PATH = BASE_DIR / ".env"

# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------
# API field name → DB column name
REVIEW_DB_FIELDS = {
    "electricity":   "electricity",
    "water":         "water",
    "gas":           "gas",
    "maintenance":   "building_maintenance",   # API key differs from DB column
    "elevator":      "elevator",
    "structure":     "structure",
    "seepage":       "seepage",
    "internet":      "internet",
    "mobile_signal": "mobile_signal",
    "noise":         "noise",
    "security":      "security",
    "cleanliness":   "cleanliness",
    "road_access":   "road_access",
    "parking":       "parking",
    "traffic":       "traffic",
    "flooding":      "flooding",
    "sewage":        "sewage",
}

REVIEW_FIELDS = list(REVIEW_DB_FIELDS.keys())

PROPERTY_SPECIFIC_FIELDS = [
    "electricity", "water", "gas", "maintenance",
    "elevator", "parking", "internet", "structure", "seepage",
]
NEIGHBORHOOD_FIELDS = [
    "noise", "security", "cleanliness", "road_access",
    "traffic", "flooding", "sewage", "mobile_signal",
]

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

# ---------------------------------------------------------------------------
# Aggregation label map
# ---------------------------------------------------------------------------
LABEL_MAP = {
    "electricity":   {5: "Good",       3: "Fair",       1: "Poor"},
    "water":         {5: "Good",       3: "Fair",       1: "Poor"},
    "gas":           {5: "Good",       3: "Fair",       1: "Poor"},
    "maintenance":   {5: "Good",       3: "Fair",       1: "Poor"},
    "building_maintenance": {5: "Good", 3: "Fair",      1: "Poor"},
    "elevator":      {5: "Present",                     1: "Not Present"},
    "parking":       {5: "Present",                     1: "Not Present"},
    "internet":      {5: "Available",                   1: "Not Available"},
    "structure":     {5: "Good",       3: "Fair",       1: "Poor"},
    "seepage":       {5: "Good",       3: "Fair",       1: "Poor"},
    "cleanliness":   {5: "Good",       3: "Fair",       1: "Poor"},
    "road_access":   {5: "Good",       3: "Fair",       1: "Poor"},
    "mobile_signal": {5: "Good",       3: "Fair",       1: "Poor"},
    "noise":         {5: "Low",        3: "Moderate",   1: "High"},
    "security":      {5: "Safe",       3: "Average",    1: "Unsafe"},
    "traffic":       {5: "Low",        3: "Moderate",   1: "High"},
    "flooding":      {5: "None",       3: "Minor",      1: "Severe"},
    "sewage":        {5: "None",       3: "Occasional", 1: "Frequent"},
}

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------
def read_env():
    values = {}
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


def locationiq_key(env):
    return (
        env.get("LOCATIONIQ_API_KEY")
        or env.get("LocationIQ_API_Key")
        or env.get("LOCATIONIQ_KEY")
    )


# ---------------------------------------------------------------------------
# Mock DB (fallback when no credentials)
# ---------------------------------------------------------------------------
class MockCursor:
    def __init__(self):
        self.description = []
        self._last_id = str(uuid.uuid4())

    def execute(self, *args, **kwargs):
        pass

    def fetchone(self):
        return {
            "id": self._last_id,
            "name": "Mock Property",
            "property_type": "house",
            "address": "123 Mock Street",
            "area": "Mock Area",
            "city": "Mock City",
            "latitude": 30.3753,
            "longitude": 69.3451,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockConn:
    def cursor(self, *args, **kwargs):
        return MockCursor()

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------
def connect():
    env = read_env()
    project_ref = env.get("SUPABASE_PROJECT_REF") or env.get("Project_Ref")
    password     = env.get("SUPABASE_DB_PASSWORD") or env.get("DB_Password")
    host         = env.get("SUPABASE_DB_HOST") or (
        f"db.{project_ref}.supabase.co" if project_ref else ""
    )
    user         = env.get("SUPABASE_DB_USER", "postgres")
    database     = env.get("SUPABASE_DB_NAME", "postgres")
    port         = env.get("SUPABASE_DB_PORT", "5432")

    if not host or not password:
        print("!! WARNING: Using Mock Database — reviews will NOT persist.")
        return MockConn()

    try:
        return psycopg.connect(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
            sslmode="require",
            row_factory=dict_row,
        )
    except Exception as e:
        print(f"!! CRITICAL: Connection to Supabase failed: {e}")
        return MockConn()


def verify_db():
    with connect() as conn:
        if isinstance(conn, MockConn):
            return
        with conn.cursor() as cur:
            cur.execute(
                "select to_regclass('public.properties') as tbl"
            )
            row = cur.fetchone()
            if row and row.get("tbl") is None:
                raise RuntimeError("Schema missing: public.properties not found")


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


BINARY_FIELDS = {"elevator", "internet", "parking"}


def validate_review(payload):
    role_label = clean_text(payload.get("contributor_role"), 80)
    role = ROLE_VALUES.get(role_label, clean_text(role_label).lower())
    if role not in ROLE_VALUES.values():
        raise ValueError("contributor_role is invalid")

    # Fix #10: server-side validation for lived_period
    lived_period = clean_text(payload.get("lived_period"), 120)
    if not lived_period:
        raise ValueError("lived_period (observed period) is required")

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


def locationiq_search(query, limit=6):
    env = read_env()
    api_key = locationiq_key(env)
    if not api_key:
        raise ValueError("LOCATIONIQ_API_KEY is missing from .env")

    params = {
        "key":          api_key,
        "q":            query,
        "format":       "json",
        "countrycodes": "pk",
        "addressdetails": 1,
        "namedetails":  1,
        "limit":        limit,
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
    Returns "Mostly X" when one option has the clear lead.
    Returns a percentage breakdown string when tied.
    Returns None when no data.
    """
    filtered = {k: v for k, v in counts.items() if v > 0}
    if not filtered:
        return None

    max_count = max(filtered.values())
    winners = [k for k, v in filtered.items() if v == max_count]

    labels = LABEL_MAP.get(field_id, {})

    if len(winners) > 1:
        total = sum(filtered.values())
        parts = []
        for val in (5, 3, 1):
            if val in filtered:
                pct = round((filtered[val] / total) * 100)
                parts.append(f"{labels.get(val, str(val))} {pct}%")
        return ", ".join(parts)

    label = labels.get(winners[0], str(winners[0]))
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
def property_summary(conn, property_row, reviews_by_id=None, nearby_reviews_by_id=None):
    """
    Build the full property dict with stats and comments.

    When called from list view, reviews_by_id and nearby_reviews_by_id are
    pre-fetched dicts keyed by property_id (batch mode — no extra queries).
    When called for a single property, fetches its own data (2 queries only).
    """
    if property_row is None:
        return {}

    property_data = row_to_dict(property_row)
    property_id = property_data.get("id")
    lat = property_data.get("latitude")
    lng = property_data.get("longitude")

    property_data.pop("location", None)
    if "distance_m" in property_data and property_data["distance_m"] is not None:
        property_data["distance_km"] = round(
            float(property_data.pop("distance_m")) / 1000, 3
        )

    # Fetch reviews if not pre-supplied (single property page)
    if reviews_by_id is None:
        reviews = []
        nearby_reviews = []
        if property_id and lat is not None and lng is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select r.*, pr.display_name as reviewer_name
                    from public.property_reviews r
                    left join public.profiles pr on r.user_id = pr.id
                    where r.property_id = %s
                      and r.visibility = 'public'
                      and r.moderation_status = 'active'
                    order by r.created_at desc
                    """,
                    (property_id,),
                )
                reviews = [dict(row) for row in (cur.fetchall() or [])]

                cur.execute(
                    """
                    select r.*
                    from public.property_reviews r
                    join public.properties p on r.property_id = p.id
                    where st_dwithin(
                            p.location,
                            st_setsrid(st_makepoint(%s, %s), 4326)::geography,
                            %s
                          )
                      and r.visibility = 'public'
                      and r.moderation_status = 'active'
                    """,
                    (lng, lat, NEIGHBOURHOOD_RADIUS_M),
                )
                nearby_reviews = [dict(row) for row in (cur.fetchall() or [])]
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
        property_stats[field] = {
            "dominant": get_dominant_label(counts, field),
            "counts":   counts,
            "total":    len(reviews),
        }

    # Aggregate neighbourhood fields
    neighborhood_stats = {}
    for field in NEIGHBORHOOD_FIELDS:
        counts = aggregate_field(nearby_reviews, field)
        if counts is None:
            continue
        neighborhood_stats[field] = {
            "dominant": get_dominant_label(counts, field),
            "counts":   counts,
            "total":    len(nearby_reviews),
        }

    property_data["property_stats"]    = property_stats
    property_data["neighborhood_stats"] = neighborhood_stats
    property_data["comments"] = [
        {
            "id":               str(r.get("id")),
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
def batch_fetch_reviews(conn, property_ids, lat_lng_by_id):
    """
    Returns (reviews_by_id, nearby_reviews_by_id) dicts.
    Fires exactly 2 SQL queries regardless of how many properties are in the list.
    """
    if not property_ids or isinstance(conn, MockConn):
        return {}, {}

    id_list = list(property_ids)

    with conn.cursor() as cur:
        # All reviews for the listed properties (with reviewer names)
        cur.execute(
            """
            select r.*, pr.display_name as reviewer_name
            from public.property_reviews r
            left join public.profiles pr on r.user_id = pr.id
            where r.property_id = any(%s)
              and r.visibility = 'public'
              and r.moderation_status = 'active'
            order by r.created_at desc
            """,
            (id_list,),
        )
        all_reviews = [dict(row) for row in (cur.fetchall() or [])]

        # All nearby reviews — one spatial query that covers all bounding boxes
        # Strategy: union the individual nearby queries using a single lateral join
        # We build the query dynamically with the property coords
        nearby_by_id = {pid: [] for pid in id_list}

        if lat_lng_by_id:
            # Fetch nearby reviews for every property in one query using
            # a VALUES list as a reference table
            values_rows = ", ".join(
                f"('{pid}'::uuid, {lng}, {lat})"
                for pid, (lat, lng) in lat_lng_by_id.items()
            )
            cur.execute(
                f"""
                select ref.anchor_id, r.*
                from (values {values_rows}) as ref(anchor_id, ref_lng, ref_lat)
                join public.property_reviews r
                  on true
                join public.properties p on r.property_id = p.id
                where st_dwithin(
                        p.location,
                        st_setsrid(st_makepoint(ref.ref_lng, ref.ref_lat), 4326)::geography,
                        {NEIGHBOURHOOD_RADIUS_M}
                      )
                  and r.visibility = 'public'
                  and r.moderation_status = 'active'
                """
            )
            for row in (cur.fetchall() or []):
                r = dict(row)
                anchor = str(r.pop("anchor_id"))
                nearby_by_id.setdefault(anchor, []).append(r)

    reviews_by_id = {pid: [] for pid in id_list}
    for r in all_reviews:
        pid = str(r.get("property_id"))
        reviews_by_id.setdefault(pid, []).append(r)

    return reviews_by_id, nearby_by_id

# ---------------------------------------------------------------------------
# Auth helpers (Supabase Auth via PKCE / server-side session cookie)
# ---------------------------------------------------------------------------
SUPABASE_ANON_KEY_ENV = "SUPABASE_ANON_KEY"

def get_supabase_anon_key(env):
    return env.get(SUPABASE_ANON_KEY_ENV) or env.get("ANON_KEY") or ""


def exchange_code_for_session(env, code, code_verifier=None):
    """
    Exchange an OAuth code for a Supabase session.
    Returns the session dict on success, raises on failure.
    """
    base = supabase_url(env)
    if not base:
        raise ValueError("Supabase URL not configured")

    payload = {
        "grant_type":    "authorization_code",
        "code":          code,
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier

    data = json.dumps(payload).encode()
    req = Request(
        f"{base}/auth/v1/token?grant_type=authorization_code",
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
# HTTP Handler
# ---------------------------------------------------------------------------
class AppHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js":  "application/javascript",
        ".css": "text/css",
    }

    def translate_path(self, path):
        parsed = urlparse(path)
        requested = parsed.path
        if requested == "/":
            return str(STATIC_DIR / "index.html")
        return str(STATIC_DIR / requested.lstrip("/"))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload, status=HTTPStatus.OK):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
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
        if path.startswith("/api/properties/"):
            property_id = path.split("/")[-1]
            self.handle_get_property(property_id)
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/auth/session":
            self.handle_auth_session()
            return
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

    # ------------------------------------------------------------------
    # Auth endpoints (Fix #1 / Phase 3)
    # ------------------------------------------------------------------
    def handle_auth_signin(self, parsed):
        """Redirect the browser to Supabase OAuth for Google."""
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

        oauth_params = urlencode({
            "provider":    provider,
            "redirect_to": "http://localhost:8000/api/auth/callback",
        })
        supabase_oauth_url = f"{base}/auth/v1/authorize?{oauth_params}"

        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", supabase_oauth_url)
        self.end_headers()

    def handle_auth_callback(self, parsed):
        """
        Supabase redirects here after OAuth. It always sends tokens as a URL
        fragment (#access_token=...&refresh_token=...) which the server cannot
        read — fragments are never sent in HTTP requests.

        Strategy: serve a tiny HTML page that reads the fragment in JS and
        immediately POSTs the tokens to /api/auth/session, which sets HttpOnly
        cookies and redirects to /.
        """
        html = b"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Signing in...</title></head>
<body>
<script>
(function () {
  var hash = window.location.hash.slice(1);
  if (!hash) { window.location.replace("/"); return; }
  var params = {};
  hash.split("&").forEach(function(part) {
    var kv = part.split("=");
    params[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || "");
  });
  var access  = params["access_token"];
  var refresh = params["refresh_token"];
  if (!access) { window.location.replace("/"); return; }
  fetch("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ access_token: access, refresh_token: refresh || "" })
  }).then(function(r) {
    if (r.ok) {
      // Check if there is saved pre-auth state to restore
      var saved = localStorage.getItem("preAuthState");
      if (saved) {
        window.location.replace("/?restore=1");
      } else {
        window.location.replace("/");
      }
    } else {
      window.location.replace("/");
    }
  }).catch(function() { window.location.replace("/"); });
})();
</script>
<p>Completing sign in...</p>
</body>
</html>"""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def handle_auth_session(self):
        """
        Receives { access_token, refresh_token } from the callback page JS
        and stores them as HttpOnly cookies.
        """
        try:
            body = parse_body(self)
        except ValueError as exc:
            self.send_error_json(str(exc))
            return

        access_token  = str(body.get("access_token",  "") or "").strip()
        refresh_token = str(body.get("refresh_token", "") or "").strip()

        if not access_token:
            self.send_error_json("access_token is required")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Set-Cookie",
            f"sb_access_token={access_token}; Path=/; HttpOnly; SameSite=Lax"
        )
        if refresh_token:
            self.send_header(
                "Set-Cookie",
                f"sb_refresh_token={refresh_token}; Path=/; HttpOnly; SameSite=Lax"
            )
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def handle_auth_me(self):
        """Return the current user from session cookie, or 401."""
        access_token, _ = parse_session_cookie(self)
        if not access_token:
            self.send_error_json("Not authenticated", HTTPStatus.UNAUTHORIZED)
            return

        env = read_env()
        user = get_user_from_token(env, access_token)
        if not user:
            self.send_error_json("Session expired", HTTPStatus.UNAUTHORIZED)
            return

        self.send_json({
            "id":       user.get("id"),
            "email":    user.get("email"),
            "name":     (
                user.get("user_metadata", {}).get("full_name")
                or user.get("user_metadata", {}).get("name")
                or user.get("email", "").split("@")[0]
            ),
            "provider": user.get("app_metadata", {}).get("provider", "google"),
        })

    def handle_auth_signout(self):
        """Clear session cookies."""
        self.send_response(HTTPStatus.OK)
        self.send_header("Set-Cookie", "sb_access_token=; Path=/; Max-Age=0; HttpOnly")
        self.send_header("Set-Cookie", "sb_refresh_token=; Path=/; Max-Age=0; HttpOnly")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _get_authenticated_user_id(self):
        """
        Returns the authenticated user_id string, or None if not signed in.
        Reads from session cookie (real auth) with no fallback to mock headers.
        """
        access_token, _ = parse_session_cookie(self)
        if not access_token:
            return None
        env = read_env()
        user = get_user_from_token(env, access_token)
        return user.get("id") if user else None

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    def handle_config(self):
        env = read_env()
        self.send_json({
            "hasLocationIqKey":      bool(locationiq_key(env)),
            "supabaseUrl":           supabase_url(env),
            "hasSupabasePassword":   bool(
                env.get("SUPABASE_DB_PASSWORD") or env.get("DB_Password")
            ),
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
        try:
            places = locationiq_search(query)
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

        select_extra = ""
        select_values = []
        where, where_values = [], []

        if query:
            where.append(
                "(lower(name) like %s or lower(address) like %s "
                "or lower(area) like %s "
                "or lower(coalesce(external_display_name, '')) like %s)"
            )
            where_values.extend([f"%{query}%"] * 4)
        if city:
            where.append("lower(city) = %s")
            where_values.append(city)

        order_by = "created_at desc"
        if lat and lng:
            try:
                origin_lat = float(lat)
                origin_lng = float(lng)
                radius_m   = float(radius_km) * 1000
            except ValueError:
                self.send_error_json("lat, lng, and radius_km must be numbers")
                return

            point = "st_setsrid(st_makepoint(%s, %s), 4326)::geography"
            select_extra = f", st_distance(location, {point}) as distance_m"
            select_values.extend([origin_lng, origin_lat])
            where.append(f"st_dwithin(location, {point}, %s)")
            where_values.extend([origin_lng, origin_lat, radius_m])
            order_by = "distance_m asc, created_at desc"

        sql = f"select *{select_extra} from public.properties"
        if where:
            sql += " where " + " and ".join(where)
        sql += f" order by {order_by} limit 50"

        with connect() as conn:
            all_values = select_values + where_values
            with conn.cursor() as cur:
                try:
                    cur.execute(sql, all_values)
                    rows = cur.fetchall() or []
                except Exception as e:
                    print(f"!! SQL ERROR in list_properties: {e}")
                    self.send_error_json("Database query failed.")
                    return

            if not rows:
                self.send_json({"properties": []})
                return

            # Batch-fetch all reviews in 2 queries
            property_ids   = [str(r["id"]) for r in rows]
            lat_lng_by_id  = {
                str(r["id"]): (r["latitude"], r["longitude"])
                for r in rows
                if r.get("latitude") is not None and r.get("longitude") is not None
            }
            reviews_by_id, nearby_by_id = batch_fetch_reviews(
                conn, property_ids, lat_lng_by_id
            )

            self.send_json({
                "properties": [
                    property_summary(conn, row, reviews_by_id, nearby_by_id)
                    for row in rows
                ]
            })

    # ------------------------------------------------------------------
    # Single property
    # ------------------------------------------------------------------
    def handle_get_property(self, property_id):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select * from public.properties where id = %s",
                    (property_id,),
                )
                row = cur.fetchone()
            if row is None:
                self.send_error_json("Property not found", HTTPStatus.NOT_FOUND)
                return
            self.send_json({"property": property_summary(conn, row)})

    # ------------------------------------------------------------------
    # Create property
    # ------------------------------------------------------------------
    def handle_create_property(self):
        try:
            body = parse_body(self)
            data = validate_property(body)
            external_payload = body.get("external_payload")
        except ValueError as exc:
            self.send_error_json(str(exc))
            return

        with connect() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        insert into public.properties
                        (name, property_type, address, area, city, country,
                         latitude, longitude, external_provider, external_place_id,
                         external_display_name, google_place_id, google_place_name,
                         google_formatted_address, map_provider, external_payload)
                        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        returning *
                        """,
                        (
                            data["name"],
                            data["property_type"],
                            data["address"],
                            data["area"],
                            data["city"],
                            data["country"],
                            data["latitude"],
                            data["longitude"],
                            data["external_provider"],
                            data["external_place_id"],
                            data["external_display_name"],
                            data["google_place_id"],
                            data["google_place_name"],
                            data["google_formatted_address"],
                            data["external_provider"],
                            json.dumps(external_payload) if external_payload
                            else json.dumps(data),
                        ),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    self.send_json(
                        {"property": property_summary(conn, row)},
                        HTTPStatus.CREATED,
                    )
                except Exception as e:
                    print(f"!! SQL ERROR in create_property: {e}")
                    self.send_error_json("Failed to create property in database.")

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

        with connect() as conn:
            with conn.cursor() as cur:
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
                        existing = None

                        if place.get("place_id"):
                            cur.execute(
                                """
                                select * from public.properties
                                where external_provider = %s
                                  and external_place_id = %s
                                limit 1
                                """,
                                (
                                    place.get("provider", "locationiq"),
                                    str(place["place_id"]),
                                ),
                            )
                            existing = cur.fetchone()

                        if not existing:
                            cur.execute(
                                """
                                select * from public.properties
                                where st_dwithin(
                                    location,
                                    st_setsrid(st_makepoint(%s, %s), 4326)::geography,
                                    20
                                )
                                limit 1
                                """,
                                (lng, lat),
                            )
                            existing = cur.fetchone()

                        if existing:
                            property_row = existing
                            property_id  = str(property_row.get("id"))
                        else:
                            name = (
                                place.get("name")
                                or place.get("display_name", "").split(",", 1)[0]
                            )
                            # Fix #9: guess property type from city
                            ptype = guess_property_type(place.get("city", ""))
                            cur.execute(
                                """
                                insert into public.properties
                                (name, property_type, address, area, city, country,
                                 latitude, longitude, external_provider,
                                 external_place_id, external_display_name,
                                 map_provider, external_payload)
                                values (%s,%s,%s,%s,%s,'Pakistan',%s,%s,%s,%s,%s,%s,%s)
                                returning *
                                """,
                                (
                                    name,
                                    ptype,
                                    place.get("display_name"),
                                    place.get("area") or "",
                                    place.get("city") or "",
                                    lat,
                                    lng,
                                    place.get("provider", "locationiq"),
                                    str(place.get("place_id", "")),
                                    place.get("display_name"),
                                    "locationiq",
                                    json.dumps(place.get("raw") or {}),
                                ),
                            )
                            property_row = cur.fetchone()
                            property_id  = str(property_row.get("id"))
                    else:
                        cur.execute(
                            "select * from public.properties where id = %s",
                            (property_id,),
                        )
                        property_row = cur.fetchone()
                        if property_row is None:
                            self.send_error_json(
                                "Property not found", HTTPStatus.NOT_FOUND
                            )
                            return
                        property_id = str(property_row.get("id"))

                    cur.execute(
                        """
                        insert into public.property_reviews
                        (property_id, user_id, contributor_role, lived_period,
                         rent_range, hidden_costs, comment,
                         electricity, water, gas, building_maintenance,
                         elevator, structure, seepage, internet, mobile_signal,
                         noise, security, cleanliness, road_access, parking,
                         traffic, flooding, sewage)
                        values (%s,%s,%s,%s,%s,%s,%s,
                                %s,%s,%s,%s,%s,%s,%s,%s,%s,
                                %s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            property_id,
                            user_id,
                            data["contributor_role"],
                            data["lived_period"],
                            data["rent_range"],
                            data["hidden_costs"],
                            data["comment"],
                            data["electricity"],
                            data["water"],
                            data["gas"],
                            data["maintenance"],   # mapped to building_maintenance col
                            data["elevator"],
                            data["structure"],
                            data["seepage"],
                            data["internet"],
                            data["mobile_signal"],
                            data["noise"],
                            data["security"],
                            data["cleanliness"],
                            data["road_access"],
                            data["parking"],
                            data["traffic"],
                            data["flooding"],
                            data["sewage"],
                        ),
                    )
                    conn.commit()
                    print(f"++ Review saved: property {property_id}, user {user_id}")
                    self.send_json(
                        {"property": property_summary(conn, property_row)},
                        HTTPStatus.CREATED,
                    )
                except Exception as e:
                    print(f"!! SQL ERROR in create_review: {e}")
                    self.send_error_json(f"Database error: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run(host="0.0.0.0", port=8000):
    try:
        verify_db()
    except Exception as e:
        print(f"!! Warning: DB verification failed ({e}).")
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Real Estate Reality running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
