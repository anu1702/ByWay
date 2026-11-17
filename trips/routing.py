import json
import ssl
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "Byway/1.0 (INFO 490 personal safety app)"
CAMPUS = (40.1106, -88.2272)
DEMO_HERE = {
    "label": "401 W Springfield Ave, Urbana",
    "latitude": 40.1121759,
    "longitude": -88.2120219,
}

PROFILES = {
    "walk": "foot",
    "run": "foot",
    "date": "foot",
    "rideshare": "driving",
    "travel": "driving",
    "transit": "foot",
}

ALLOWANCE_MILES = {
    "walk": 0.05,
    "run": 0.05,
    "date": 0.05,
    "transit": 0.10,
    "rideshare": 0.20,
    "travel": 0.20,
}


def _context():
    context = ssl.create_default_context()
    bundle = Path("/etc/ssl/cert.pem")
    if bundle.is_file():
        try:
            context.load_verify_locations(bundle)
        except OSError:
            pass
    return context


def _get_json(url):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=8, context=_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None


def places_from_payload(payload, limit=5):
    places = []
    if not isinstance(payload, list):
        return places
    for item in payload:
        if len(places) >= limit:
            break
        if not isinstance(item, dict):
            continue
        try:
            latitude = float(item["lat"])
            longitude = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        full = (item.get("display_name") or "").strip()
        name = (item.get("name") or "").strip() or full.split(",")[0].strip()
        if not name or not full:
            continue
        places.append(
            {
                "name": name[:120],
                "label": full[:180],
                "latitude": latitude,
                "longitude": longitude,
            }
        )
    return places


def search_places(query, limit=5):
    text = query.strip()[:120]
    if len(text) < 2:
        return []
    params = {"q": text, "format": "jsonv2", "limit": limit}
    if "," not in text:
        params["viewbox"] = "-88.40,40.20,-88.10,40.00"
        params["bounded"] = 1
    url = "https://nominatim.openstreetmap.org/search?" + urlencode(params)
    payload = _get_json(url)
    if payload is None:
        return None
    return places_from_payload(payload, limit)


def geocode(destination):
    query = destination if "," in destination else f"{destination}, Champaign, Illinois"
    url = "https://nominatim.openstreetmap.org/search?" + urlencode(
        {"q": query, "format": "jsonv2", "limit": 1}
    )
    payload = _get_json(url)
    found = places_from_payload(payload, 1)
    if not found:
        return None
    return found[0]["latitude"], found[0]["longitude"]


def directions_from_steps(steps, destination_name=""):
    directions = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        text = _instruction(step, destination_name)
        if not text:
            continue
        directions.append({"text": text, "distance": _step_distance(step.get("distance"))})
    return directions


def driving_route(start, end, profile, destination_name=""):
    url = (
        "https://router.project-osrm.org/route/v1/"
        f"{profile}/{start[1]},{start[0]};{end[1]},{end[0]}"
        "?overview=full&geometries=geojson&steps=true"
    )
    payload = _get_json(url)
    if not payload or payload.get("code") != "Ok":
        return None
    try:
        leg = payload["routes"][0]
        coordinates = leg["geometry"]["coordinates"]
        points = [[lat, lng] for lng, lat in coordinates]
        if len(points) < 2:
            return None
        steps = leg["legs"][0]["steps"]
        return {
            "points": points,
            "duration_seconds": float(leg["duration"]),
            "distance_meters": float(leg["distance"]),
            "steps": directions_from_steps(steps, destination_name),
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _instruction(step, destination_name):
    maneuver = step.get("maneuver") or {}
    kind = maneuver.get("type") or ""
    modifier = (maneuver.get("modifier") or "").replace("-", " ")
    name = (step.get("name") or "").strip()
    onto = f" onto {name}" if name else ""
    turns = {
        "uturn": "Make a U-turn",
        "sharp right": "Turn sharp right",
        "right": "Turn right",
        "slight right": "Bear right",
        "straight": "Continue straight",
        "slight left": "Bear left",
        "left": "Turn left",
        "sharp left": "Turn sharp left",
    }
    if kind == "depart":
        if modifier and name:
            return f"Head {modifier} on {name}"
        if modifier:
            return f"Head {modifier}"
        return f"Start on {name}" if name else "Start"
    if kind == "arrive":
        return f"Arrive at {destination_name}" if destination_name else "Arrive"
    if kind == "new name" and name:
        return f"Continue onto {name}"
    if kind in {"continue", "merge"} and name:
        return f"Continue on {name}"
    if kind in {"turn", "end of road", "fork"}:
        return f"{turns.get(modifier, 'Continue')}{onto}"
    if kind in {"roundabout", "rotary", "exit roundabout"}:
        return f"Take the roundabout{onto}"
    if name:
        return f"Continue on {name}"
    return ""


def _step_distance(meters):
    try:
        meters = float(meters)
    except (TypeError, ValueError):
        return ""
    if meters < 30:
        return ""
    miles = meters / 1609.34
    if miles < 0.1:
        feet = int(round(meters * 3.28084 / 10.0) * 10)
        return f"{feet} ft"
    return f"{miles:.1f} mi"


def ensure_destination(session, remember_failure=False):
    if session.destination_latitude is not None and session.destination_longitude is not None:
        return session.destination_latitude, session.destination_longitude
    if session.route_status == "unavailable":
        return None
    found = geocode(session.destination)
    if found is None:
        if remember_failure:
            session.route_status = "unavailable"
            session.save(update_fields=["route_status"])
        return None
    session.destination_latitude, session.destination_longitude = found
    session.save(update_fields=["destination_latitude", "destination_longitude"])
    return found


def ensure_route(session, latitude, longitude):
    if session.route_points:
        return True
    if session.route_status == "unavailable":
        return False
    destination = ensure_destination(session, remember_failure=True)
    if destination is None:
        return False
    profile = PROFILES.get(session.trip_type, "foot")
    route = driving_route((latitude, longitude), destination, profile, session.destination)
    if route is None:
        session.route_status = "unavailable"
        session.save(update_fields=["route_status"])
        return False
    from django.utils import timezone

    session.route_points = json.dumps(route["points"])
    session.route_steps = json.dumps(route["steps"])
    session.route_duration_seconds = route["duration_seconds"]
    session.route_distance_meters = route["distance_meters"]
    session.route_started_at = timezone.now()
    session.route_status = "ready"
    session.save(
        update_fields=[
            "route_points",
            "route_steps",
            "route_duration_seconds",
            "route_distance_meters",
            "route_started_at",
            "route_status",
        ]
    )
    return True


def stored_steps(session):
    if not session.route_steps:
        return []
    try:
        steps = json.loads(session.route_steps)
    except json.JSONDecodeError:
        return []
    return steps if isinstance(steps, list) else []


def route_summary(session):
    if not session.route_distance_meters or not session.route_duration_seconds:
        return ""
    minutes = max(1, round(session.route_duration_seconds / 60))
    miles = session.route_distance_meters / 1609.34
    return f"{minutes} min · {miles:.1f} mi"


def stored_route(session):
    if not session.route_points:
        return []
    try:
        points = json.loads(session.route_points)
    except json.JSONDecodeError:
        return []
    return points


def scoring_route(session):
    return {
        "route_points": stored_route(session),
        "route_duration_seconds": session.route_duration_seconds,
        "route_distance_meters": session.route_distance_meters,
        "route_started_at": session.route_started_at,
        "allowance_miles": ALLOWANCE_MILES.get(session.trip_type, 0.05),
    }
