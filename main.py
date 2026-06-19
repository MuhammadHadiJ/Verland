import json
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

REVIEW_FIELDS = [
    "electricity",
    "water",
    "gas",
    "maintenance",
    "elevator",
    "structure",
    "seepage",
    "internet",
    "mobile_signal",
    "noise",
    "security",
    "cleanliness",
    "road_access",
    "parking",
    "traffic",
    "flooding",
    "sewage",
]

REVIEW_DB_FIELDS = {
    "electricity": "electricity",
    "water": "water",
    "gas": "gas",
    "maintenance": "building_maintenance",
    "elevator": "elevator",
    "structure": "structure",
    "seepage": "seepage",
    "internet": "internet",
    "mobile_signal": "mobile_signal",
    "noise": "noise",
    "security": "security",
    "cleanliness": "cleanliness",
    "road_access": "road_access",
    "parking": "parking",
    "traffic": "traffic",
    "flooding": "flooding",
    "sewage": "sewage",
}

PROPERTY_TYPES = {"apartment", "house", "plot", "commercial"}
ROLE_VALUES = {
    "Current resident": "current_resident",
    "Former resident": "former_resident",
    "Buyer or tenant prospect": "buyer_or_tenant_prospect",
    "General public contributor": "general_public_contributor",
    "Owner or landlord": "owner_or_landlord",
}

LOCATIONIQ_SEARCH_URL = "https://api.locationiq.com/v1/search"
LOCATIONIQ_AUTOCOMPLETE_URL = "https://api.locationiq.com/v1/autocomplete"
LOCATIONIQ_REVERSE_URL = "https://api.locationiq.com/v1/reverse"


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
    return env.get("LOCATIONIQ_API_KEY") or env.get("LocationIQ_API_Key") or env.get("LOCATIONIQ_KEY")


class MockCursor:
    def __init__(self):
        self.description = []
        self._last_id = str(uuid.uuid4())
    def execute(self, *args, **kwargs): pass
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
            "properties_table": "public.properties"
        }
    def fetchall(self): return []
    def __enter__(self): return self
    def __exit__(self, *args): pass

class MockConn:
    def cursor(self, *args, **kwargs): return MockCursor()
    def commit(self): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass

def connect():
    env = read_env()
    project_ref = env.get("SUPABASE_PROJECT_REF") or env.get("Project_Ref")
    password = env.get("SUPABASE_DB_PASSWORD") or env.get("DB_Password")
    host = env.get("SUPABASE_DB_HOST") or (f"db.{project_ref}.supabase.co" if project_ref else "")
    user = env.get("SUPABASE_DB_USER", "postgres")
    database = env.get("SUPABASE_DB_NAME", "postgres")
    port = env.get("SUPABASE_DB_PORT", "5432")

    if not host or not password:
        print("!! WARNING: Using Mock Database !! Review storage will NOT persist.")
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
        if isinstance(conn, MockConn): return
        with conn.cursor() as cur:
            cur.execute("select to_regclass('public.properties') as properties_table")
            row = cur.fetchone()
            if row and row.get("properties_table") is None:
                raise RuntimeError("Supabase schema is missing public.properties")


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def row_to_dict(row):
    if row is None: return {}
    try:
        return {key: json_value(value) for key, value in dict(row).items()}
    except (TypeError, ValueError):
        return {}


def parse_body(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise ValueError("Invalid content length")

    try:
        raw_body = handler.rfile.read(length).decode("utf-8")
        return json.loads(raw_body or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON") from exc


def clean_text(value, max_length=240):
    value = str(value or "").strip()
    return value[:max_length]


def coerce_score(payload, field):
    try:
        value = int(payload[field])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{field} must be a number from 1 to 5")

    if value < 1 or value > 5:
        raise ValueError(f"{field} must be a number from 1 to 5")
    return value


def validate_property(payload):
    property_type = clean_text(payload.get("property_type")).lower()
    if property_type not in PROPERTY_TYPES:
        raise ValueError("property_type must be apartment, house, plot, or commercial")

    data = {
        "name": clean_text(payload.get("name"), 160),
        "property_type": property_type,
        "address": clean_text(payload.get("address"), 300),
        "area": clean_text(payload.get("area"), 120),
        "city": clean_text(payload.get("city"), 120),
        "country": "Pakistan",
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "external_provider": clean_text(payload.get("external_provider"), 80) or "manual",
        "external_place_id": clean_text(payload.get("external_place_id"), 180) or None,
        "external_display_name": clean_text(payload.get("external_display_name"), 300) or None,
        "google_place_id": clean_text(payload.get("google_place_id"), 180) or None,
        "google_place_name": clean_text(payload.get("google_place_name"), 180) or None,
        "google_formatted_address": clean_text(payload.get("google_formatted_address"), 300)
        or None,
    }

    for field in ("name", "address", "area", "city"):
        if not data[field]:
            raise ValueError(f"{field} is required")

    for field in ("latitude", "longitude"):
        if data[field] in ("", None):
            raise ValueError(f"{field} is required from the map click")
        try:
            data[field] = float(data[field])
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be a number")

    if not 23.0 <= data["latitude"] <= 38.0 or not 60.0 <= data["longitude"] <= 78.0:
        raise ValueError("Location must be inside Pakistan")

    return data


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

    return {
        "provider": "locationiq",
        "place_id": str(place.get("place_id") or place.get("osm_id") or ""),
        "display_name": display_name,
        "name": name,
        "address": display_name,
        "area": area,
        "city": city,
        "lat": float(place["lat"]),
        "lng": float(place["lon"]),
        "raw": place,
    }


def locationiq_search(query, limit=6):
    env = read_env()
    api_key = locationiq_key(env)
    if not api_key:
        raise ValueError("LOCATIONIQ_API_KEY is missing from .env")

    params = {
        "key": api_key,
        "q": query,
        "format": "json",
        "countrycodes": "pk",
        "addressdetails": 1,
        "namedetails": 1,
        "limit": limit,
    }
    url = f"{LOCATIONIQ_AUTOCOMPLETE_URL}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "RealEstateRealityMVP/0.1"})
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        fallback_url = f"{LOCATIONIQ_SEARCH_URL}?{urlencode(params)}"
        request = Request(fallback_url, headers={"User-Agent": "RealEstateRealityMVP/0.1"})
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))

    return [parse_locationiq_place(place) for place in payload]


def validate_review(payload):
    role_label = clean_text(payload.get("contributor_role"), 80)
    role = ROLE_VALUES.get(role_label, clean_text(role_label).lower())
    if role not in ROLE_VALUES.values():
        raise ValueError("contributor_role is invalid")

    data = {
        "contributor_role": role,
        "lived_period": clean_text(payload.get("lived_period"), 120),
        "rent_range": clean_text(payload.get("rent_range"), 120),
        "hidden_costs": clean_text(payload.get("hidden_costs"), 240),
        "comment": clean_text(payload.get("comment"), 900),
    }

    for field in REVIEW_FIELDS:
        data[field] = coerce_score(payload, field)
    return data


def display_role(role):
    for label, value in ROLE_VALUES.items():
        if value == role:
            return label
    return str(role or "").replace("_", " ").title()


def get_dominant_label(counts, field_id):
    if not counts:
        return None

    filtered = {k: v for k, v in counts.items() if v > 0}
    if not filtered:
        return None

    label_map = {
        "electricity": {5: "Good", 3: "Fair", 1: "Poor"},
        "water": {5: "Good", 3: "Fair", 1: "Poor"},
        "gas": {5: "Good", 3: "Fair", 1: "Poor"},
        "maintenance": {5: "Good", 3: "Fair", 1: "Poor"},
        "building_maintenance": {5: "Good", 3: "Fair", 1: "Poor"},
        "elevator": {5: "Present", 1: "Not Present"},
        "parking": {5: "Present", 1: "Not Present"},
        "internet": {5: "Available", 1: "Not Available"},
        "structure": {5: "Good", 3: "Fair", 1: "Poor"},
        "seepage": {5: "Good", 3: "Fair", 1: "Poor"},
        "cleanliness": {5: "Good", 3: "Fair", 1: "Poor"},
        "road_access": {5: "Good", 3: "Fair", 1: "Poor"},
        "mobile_signal": {5: "Good", 3: "Fair", 1: "Poor"},
        "noise": {5: "Low", 3: "Moderate", 1: "High"},
        "security": {5: "Safe", 3: "Average", 1: "Unsafe"},
        "traffic": {5: "Low", 3: "Moderate", 1: "High"},
        "flooding": {5: "None", 3: "Minor", 1: "Severe"},
        "sewage": {5: "None", 3: "Occasional", 1: "Frequent"},
    }

    max_count = max(filtered.values())
    winners = [k for k, v in filtered.items() if v == max_count]

    if len(winners) > 1:
        total = sum(filtered.values())
        parts = []
        for val in [5, 3, 1]:
            if val in filtered:
                pct = round((filtered[val] / total) * 100)
                l = label_map.get(field_id, {}).get(val, str(val))
                parts.append(f"{l} {pct}%")
        return ", ".join(parts)

    winner_val = winners[0]
    l = label_map.get(field_id, {}).get(winner_val, str(winner_val))
    return f"Mostly {l}"


def property_summary(conn, property_row):
    if property_row is None: return {}
    property_data = row_to_dict(property_row)
    property_id = property_data.get("id")
    lat = property_data.get("latitude")
    lng = property_data.get("longitude")

    PROPERTY_SPECIFIC = ["electricity", "water", "gas", "maintenance", "elevator", "parking", "internet", "structure", "seepage"]
    NEIGHBORHOOD_SPECIFIC = ["noise", "security", "cleanliness", "road_access", "traffic", "flooding", "sewage", "mobile_signal"]

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
            rows = cur.fetchall()
            reviews = [dict(r) for r in rows] if rows else []

            cur.execute(
                """
                select r.*
                from public.property_reviews r
                join public.properties p on r.property_id = p.id
                where st_dwithin(p.location, st_setsrid(st_makepoint(%s, %s), 4326)::geography, 250)
                  and r.visibility = 'public'
                  and r.moderation_status = 'active'
                """,
                (lng, lat),
            )
            nearby_rows = cur.fetchall()
            nearby_reviews = [dict(r) for r in nearby_rows] if nearby_rows else []

    property_data.pop("location", None)
    if "distance_m" in property_data and property_data["distance_m"] is not None:
        property_data["distance_km"] = round(float(property_data.pop("distance_m")) / 1000, 3)

    property_data["review_count"] = len(reviews)

    property_stats = {}
    for field in PROPERTY_SPECIFIC:
        db_field = REVIEW_DB_FIELDS.get(field)
        if not db_field: continue
        counts = {5: 0, 3: 0, 1: 0}
        for r in reviews:
            val = r.get(db_field)
            if val in counts:
                counts[val] += 1

        dominant = get_dominant_label(counts, field)
        property_stats[field] = {
            "dominant": dominant,
            "counts": counts,
            "total": len(reviews)
        }

    neighborhood_stats = {}
    for field in NEIGHBORHOOD_SPECIFIC:
        db_field = REVIEW_DB_FIELDS.get(field)
        if not db_field: continue
        counts = {5: 0, 3: 0, 1: 0}
        for r in nearby_reviews:
            val = r.get(db_field)
            if val in counts:
                counts[val] += 1

        dominant = get_dominant_label(counts, field)
        neighborhood_stats[field] = {
            "dominant": dominant,
            "counts": counts,
            "total": len(nearby_reviews)
        }

    property_data["property_stats"] = property_stats
    property_data["neighborhood_stats"] = neighborhood_stats
    property_data["comments"] = [
        {
            "id": str(review.get("id")),
            "reviewer_name": review.get("reviewer_name") or "Verified Contributor",
            "contributor_role": display_role(review.get("contributor_role")),
            "lived_period": review.get("lived_period"),
            "rent_range": review.get("rent_range"),
            "hidden_costs": review.get("hidden_costs"),
            "comment": review.get("comment"),
            "created_at": json_value(review.get("created_at") or datetime.now()),
            "scores": {api_field: review.get(db_field) for api_field, db_field in REVIEW_DB_FIELDS.items()}
        }
        for review in reviews
    ]
    return property_data


class AppHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
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

        if path.startswith("/api/properties/"):
            property_id = path.split("/")[-1]
            self.handle_get_property(property_id)
            return

        super().do_GET()

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

    def handle_config(self):
        env = read_env()
        self.send_json(
            {
                "googleMapsApiKey": env.get("GOOGLE_MAPS_API_KEY", ""),
                "hasLocationIqKey": bool(locationiq_key(env)),
                "supabaseUrl": supabase_url(env),
                "hasSupabasePassword": bool(
                    env.get("SUPABASE_DB_PASSWORD") or env.get("DB_Password")
                ),
            }
        )

    def handle_location_search(self, parsed):
        params = parse_qs(parsed.query)
        query = clean_text(params.get("q", [""])[0], 180)
        if len(query) < 3:
            self.send_json({"places": []})
            return
        try:
            places = locationiq_search(query)
        except ValueError as exc:
            self.send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self.send_error_json(f"Location search failed: {exc}", HTTPStatus.BAD_GATEWAY)
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
            "key": api_key,
            "lat": lat,
            "lon": lng,
            "format": "json",
            "addressdetails": 1,
            "namedetails": 1,
        }
        url = f"{LOCATIONIQ_REVERSE_URL}?{urlencode(query_params)}"
        request = Request(url, headers={"User-Agent": "RealEstateRealityMVP/0.1"})
        try:
            with urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.send_json({"place": parse_locationiq_place(payload)})
        except Exception as exc:
            self.send_error_json(f"Reverse geocoding failed: {exc}", HTTPStatus.BAD_GATEWAY)

    def handle_list_properties(self, parsed):
        params = parse_qs(parsed.query)
        query = clean_text(params.get("q", [""])[0], 120).lower()
        city = clean_text(params.get("city", [""])[0], 120).lower()
        lat = params.get("lat", [""])[0]
        lng = params.get("lng", [""])[0]
        radius_km = params.get("radius_km", ["0.075"])[0]

        select_values = []
        where = []
        where_values = []

        if query:
            where.append("(lower(name) like %s or lower(address) like %s or lower(area) like %s or lower(coalesce(external_display_name, '')) like %s)")
            where_values.extend([f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"])
        if city:
            where.append("lower(city) = %s")
            where_values.append(city)

        distance_select = ""
        order_by = "created_at desc"
        if lat and lng:
            try:
                origin_lat = float(lat)
                origin_lng = float(lng)
                radius_m = float(radius_km) * 1000
            except ValueError:
                self.send_error_json("lat, lng, and radius_km must be numbers")
                return

            point = "st_setsrid(st_makepoint(%s, %s), 4326)::geography"
            distance_select = f", st_distance(location, {point}) as distance_m"
            select_values.extend([origin_lng, origin_lat])
            where.append(f"st_dwithin(location, {point}, %s)")
            where_values.extend([origin_lng, origin_lat, radius_m])
            order_by = "distance_m asc, created_at desc"

        sql = f"select * {distance_select} from public.properties"
        if where:
            sql += " where " + " and ".join(where)
        sql += f" order by {order_by} limit 50"

        with connect() as conn:
            all_values = select_values + where_values
            with conn.cursor() as cur:
                try:
                    cur.execute(sql, all_values)
                    rows = cur.fetchall()
                    self.send_json({"properties": [property_summary(conn, row) for row in rows]})
                except Exception as e:
                    print(f"!! SQL ERROR in list_properties: {e}")
                    self.send_error_json("Database query failed.")

    def handle_get_property(self, property_id):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select * from public.properties where id = %s", (property_id,))
                row = cur.fetchone()
            if row is None:
                self.send_error_json("Property not found", HTTPStatus.NOT_FOUND)
                return
            self.send_json({"property": property_summary(conn, row)})

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
                        (
                          name, property_type, address, area, city, country,
                          latitude, longitude, external_provider, external_place_id,
                          external_display_name, google_place_id, google_place_name,
                          google_formatted_address, map_provider, external_payload
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                            json.dumps(external_payload) if external_payload else json.dumps(data),
                        ),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    self.send_json({"property": property_summary(conn, row)}, HTTPStatus.CREATED)
                except Exception as e:
                    print(f"!! SQL ERROR in create_property: {e}")
                    self.send_error_json("Failed to create property in database.")

    def handle_create_review(self, property_id):
        try:
            body = parse_body(self)
            data = validate_review(body)
        except ValueError as exc:
            self.send_error_json(str(exc))
            return

        # Mock Auth Flow: Check for X-User-Id header
        user_id = self.headers.get("X-User-Id")
        if not user_id:
            # Fallback to a fixed mock user for development
            user_id = "00000000-0000-0000-0000-000000000000"

        with connect() as conn:
            with conn.cursor() as cur:
                try:
                    if not property_id:
                        place = body.get("place")
                        if not place or not place.get("display_name"):
                            self.send_error_json("A valid geocoded address is required.")
                            return

                        lat = float(place["lat"])
                        lng = float(place.get("lon") or place.get("lng"))
                        existing = None

                        if place.get("place_id"):
                            cur.execute(
                                "select * from public.properties where (external_provider = %s and external_place_id = %s) limit 1",
                                (place.get("provider", "locationiq"), str(place["place_id"])),
                            )
                            existing = cur.fetchone()

                        if not existing:
                            cur.execute(
                                "select * from public.properties where st_dwithin(location, st_setsrid(st_makepoint(%s, %s), 4326)::geography, 20) limit 1",
                                (lng, lat),
                            )
                            existing = cur.fetchone()

                        if existing:
                            property_row = existing
                            property_id = str(property_row.get("id"))
                        else:
                            name = place.get("name") or place.get("display_name", "").split(",", 1)[0]
                            cur.execute(
                                """
                                insert into public.properties
                                (name, property_type, address, area, city, country, latitude, longitude, external_provider, external_place_id, external_display_name, map_provider, external_payload)
                                values (%s, %s, %s, %s, %s, 'Pakistan', %s, %s, %s, %s, %s, %s, %s)
                                returning *
                                """,
                                (name, "house", place.get("display_name"), place.get("area") or "", place.get("city") or "", lat, lng, place.get("provider", "locationiq"), str(place.get("place_id", "")), place.get("display_name"), "locationiq", json.dumps(place.get("raw") or {})),
                            )
                            property_row = cur.fetchone()
                            property_id = str(property_row.get("id"))
                    else:
                        cur.execute("select * from public.properties where id = %s", (property_id,))
                        property_row = cur.fetchone()
                        if property_row is None:
                            self.send_error_json("Property not found", HTTPStatus.NOT_FOUND)
                            return
                        property_id = str(property_row.get("id"))

                    # Store the Review
                    cur.execute(
                        """
                        insert into public.property_reviews
                        (
                          property_id, user_id, contributor_role, lived_period, rent_range,
                          hidden_costs, comment, electricity, water, gas,
                          building_maintenance, elevator, structure, seepage,
                          internet, mobile_signal, noise, security,
                          cleanliness, road_access, parking, traffic, flooding, sewage
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            property_id, user_id, data["contributor_role"], data["lived_period"], data["rent_range"], data["hidden_costs"], data["comment"],
                            data["electricity"], data["water"], data["gas"], data["maintenance"], data["elevator"], data["structure"], data["seepage"],
                            data["internet"], data["mobile_signal"], data["noise"], data["security"], data["cleanliness"], data["road_access"], data["parking"],
                            data["traffic"], data["flooding"], data["sewage"]
                        ),
                    )
                    conn.commit()
                    print(f"++ SUCCESS: Review stored for property {property_id}")
                    self.send_json({"property": property_summary(conn, property_row)}, HTTPStatus.CREATED)
                except Exception as e:
                    print(f"!! SQL ERROR in create_review: {e}")
                    self.send_error_json(f"Database error: {e}")


def run(host="0.0.0.0", port=8000):
    try:
        verify_db()
    except Exception as e:
        print(f"!! Warning: Database verification failed ({e}).")
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Real Estate Reality running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
