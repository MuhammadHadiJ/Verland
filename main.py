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


def read_env():
    values = {}
    if not ENV_PATH.exists():
        return values

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        separator = "=" if "=" in line else ":"
        if separator not in line:
            continue
        key, value = line.split(separator, 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def supabase_url(env):
    project_ref = env.get("SUPABASE_PROJECT_REF") or env.get("Project_Ref")
    return env.get("SUPABASE_URL") or (
        f"https://{project_ref}.supabase.co" if project_ref else ""
    )


def locationiq_key(env):
    return env.get("LOCATIONIQ_API_KEY") or env.get("LocationIQ_API_Key") or env.get("LOCATIONIQ_KEY")


def connect():
    env = read_env()
    project_ref = env.get("SUPABASE_PROJECT_REF") or env.get("Project_Ref")
    password = env.get("SUPABASE_DB_PASSWORD") or env.get("DB_Password")
    host = env.get("SUPABASE_DB_HOST") or (f"db.{project_ref}.supabase.co" if project_ref else "")
    user = env.get("SUPABASE_DB_USER", "postgres")
    database = env.get("SUPABASE_DB_NAME", "postgres")
    port = env.get("SUPABASE_DB_PORT", "5432")

    if not host or not password:
        raise RuntimeError("Supabase database env vars are missing")

    return psycopg.connect(
        host=host,
        port=port,
        dbname=database,
        user=user,
        password=password,
        sslmode="require",
        row_factory=dict_row,
    )


def verify_db():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select to_regclass('public.properties') as properties_table")
            row = cur.fetchone()
            if row["properties_table"] is None:
                raise RuntimeError("Supabase schema is missing public.properties")


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def row_to_dict(row):
    return {key: json_value(value) for key, value in dict(row).items()}


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
    return role.replace("_", " ").title()


def property_summary(conn, property_row):
    property_data = row_to_dict(property_row)
    property_id = property_data["id"]

    with conn.cursor() as cur:
        cur.execute(
            """
            select *
            from public.property_reviews
            where property_id = %s
              and visibility = 'public'
              and moderation_status = 'active'
            order by created_at desc
            """,
            (property_id,),
        )
        reviews = cur.fetchall()

        cur.execute(
            """
            select *
            from public.nearby_area_observations(%s, %s, 500)
            limit 20
            """,
            (property_data["latitude"], property_data["longitude"]),
        )
        area_observations = cur.fetchall()

    distributions = {}
    averages = {}
    for api_field, db_field in REVIEW_DB_FIELDS.items():
        buckets = {str(score): 0 for score in range(1, 6)}
        total = 0
        for review in reviews:
            score = review[db_field]
            buckets[str(score)] += 1
            total += score
        distributions[api_field] = buckets
        averages[api_field] = round(total / len(reviews), 2) if reviews else None

    property_data.pop("location", None)
    if "distance_m" in property_data and property_data["distance_m"] is not None:
        property_data["distance_km"] = round(float(property_data.pop("distance_m")) / 1000, 3)

    # Aggregate shared fields from nearby reviews and area observations
    # We use a 500m radius for shared environmental patterns
    shared_fields_map = {
        "noise": "noise",
        "security": "street_security",
        "cleanliness": "cleanliness",
        "road_access": "road_access",
    }

    all_nearby_values = {field: [] for field in shared_fields_map}

    # 1. Include current property reviews
    for review in reviews:
        for field in shared_fields_map:
            if review[field] is not None:
                all_nearby_values[field].append(review[field])

    with conn.cursor() as cur:
        # 2. Fetch nearby property reviews (excluding the current property)
        cur.execute(
            """
            select r.noise, r.security, r.cleanliness, r.road_access
            from public.property_reviews r
            join public.properties p on r.property_id = p.id
            where st_dwithin(p.location, st_setsrid(st_makepoint(%s, %s), 4326)::geography, 500)
              and r.property_id != %s
              and r.visibility = 'public'
              and r.moderation_status = 'active'
            """,
            (property_data["longitude"], property_data["latitude"], property_id),
        )
        for row in cur.fetchall():
            for field in shared_fields_map:
                if row[field] is not None:
                    all_nearby_values[field].append(row[field])

        # 3. Fetch nearby area observations
        cur.execute(
            """
            select observation_kind, severity
            from public.area_observations
            where moderation_status = 'active'
              and st_dwithin(location, st_setsrid(st_makepoint(%s, %s), 4326)::geography, 500)
            """,
            (property_data["longitude"], property_data["latitude"]),
        )
        # Reverse map for observations
        obs_to_field = {v: k for k, v in shared_fields_map.items()}
        for row in cur.fetchall():
            field = obs_to_field.get(row["observation_kind"])
            if field:
                all_nearby_values[field].append(row["severity"])

    # Calculate final stats for shared fields
    for field, values in all_nearby_values.items():
        if values:
            averages[field] = round(sum(values) / len(values), 2)
            buckets = {str(score): 0 for score in range(1, 6)}
            for v in values:
                buckets[str(v)] += 1
            distributions[field] = buckets

    property_data["review_count"] = len(reviews)
    property_data["averages"] = averages
    property_data["distributions"] = distributions
    property_data["area_observations"] = [row_to_dict(row) for row in area_observations]
    property_data["comments"] = [
        {
            "id": str(review["id"]),
            "contributor_role": display_role(review["contributor_role"]),
            "lived_period": review["lived_period"],
            "rent_range": review["rent_range"],
            "hidden_costs": review["hidden_costs"],
            "comment": review["comment"],
            "created_at": json_value(review["created_at"]),
        }
        for review in reviews
        if review["comment"] or review["hidden_costs"] or review["rent_range"]
    ][:12]
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

        if path.startswith("/api/properties/"):
            property_id = path.split("/")[-1]
            self.handle_get_property(property_id)
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/properties":
            self.handle_create_property()
            return

        if path.startswith("/api/properties/") and path.endswith("/reviews"):
            parts = path.split("/")
            self.handle_create_review(parts[3])
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

    def handle_list_properties(self, parsed):
        params = parse_qs(parsed.query)
        query = clean_text(params.get("q", [""])[0], 120).lower()
        city = clean_text(params.get("city", [""])[0], 120).lower()
        lat = params.get("lat", [""])[0]
        lng = params.get("lng", [""])[0]
        radius_km = params.get("radius_km", ["0.075"])[0]

        where = []
        values = []
        if query:
            where.append("(lower(name) like %s or lower(address) like %s or lower(area) like %s or lower(coalesce(external_display_name, '')) like %s)")
            values.extend([f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"])
        if city:
            where.append("lower(city) = %s")
            values.append(city)

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
            values.extend([origin_lng, origin_lat])
            where.append(f"st_dwithin(location, {point}, %s)")
            values.extend([origin_lng, origin_lat, radius_m])
            order_by = "distance_m asc, created_at desc"

        sql = f"select * {distance_select} from public.properties"
        if where:
            sql += " where " + " and ".join(where)
        sql += f" order by {order_by} limit 50"

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, values)
                rows = cur.fetchall()
            self.send_json({"properties": [property_summary(conn, row) for row in rows]})

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

    def handle_create_review(self, property_id):
        try:
            data = validate_review(parse_body(self))
        except ValueError as exc:
            self.send_error_json(str(exc))
            return

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select * from public.properties where id = %s", (property_id,))
                property_row = cur.fetchone()
                if property_row is None:
                    self.send_error_json("Property not found", HTTPStatus.NOT_FOUND)
                    return

                cur.execute(
                    """
                    insert into public.property_reviews
                    (
                      property_id, contributor_role, lived_period, rent_range,
                      hidden_costs, comment, electricity, water, gas,
                      building_maintenance, elevator, structure, seepage,
                      internet, mobile_signal, noise, security,
                      cleanliness, road_access
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        property_id,
                        data["contributor_role"],
                        data["lived_period"],
                        data["rent_range"],
                        data["hidden_costs"],
                        data["comment"],
                        data["electricity"],
                        data["water"],
                        data["gas"],
                        data["maintenance"],
                        data["elevator"],
                        data["structure"],
                        data["seepage"],
                        data["internet"],
                        data["mobile_signal"],
                        data["noise"],
                        data["security"],
                        data["cleanliness"],
                        data["road_access"],
                    ),
                )
            conn.commit()
            self.send_json(
                {"property": property_summary(conn, property_row)}, HTTPStatus.CREATED
            )


def run(host="127.0.0.1", port=8000):
    verify_db()
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Real Estate Reality running at http://{host}:{port} using Supabase")
    server.serve_forever()


if __name__ == "__main__":
    run()
