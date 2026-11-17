import json
import re
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trips.monitor import haversine_miles
from trips.routing import CAMPUS, USER_AGENT, _context

# Higher means a better place to head for when you feel unsafe.
# A mile of extra walking costs 40 points, so a close staffed store can beat a distant station.
CATEGORIES = {
    "police": (100, "Police"),
    "hospital": (92, "Hospital"),
    "fire_station": (78, "Fire station"),
    "clinic": (70, "Clinic"),
    "pharmacy": (62, "Pharmacy"),
    "library": (58, "Library"),
    "fuel": (48, "Gas station"),
    "convenience": (45, "Convenience store"),
}
ASSUMED_OPEN = {"police", "hospital", "fire_station"}
MILE_COST = 40
SEARCH_METERS = 4000
RESULT_LIMIT = 6
ENDPOINTS = (
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
DAY_INDEX = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
DAY_SPLIT = re.compile(r",\s*(?=(?:Mo|Tu|We|Th|Fr|Sa|Su)\b)")
DAY_RULE = re.compile(
    r"^(?P<days>(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:\s*[-,]\s*(?:Mo|Tu|We|Th|Fr|Sa|Su))*)\s*(?P<rest>.*)$"
)
TIME_RANGE = re.compile(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")


def is_open(spec, moment):
    if spec is None or not str(spec).strip():
        return None
    text = re.sub(r'"[^"]*"', " ", str(spec)).strip()
    if text.lower().replace(" ", "") in {"24/7", "00:00-24:00", "mo-su00:00-24:00"}:
        return True
    rules = []
    for chunk in text.split(";"):
        rules.extend(part.strip() for part in DAY_SPLIT.split(chunk) if part.strip())
    understood = False
    for rule in rules:
        parsed = _parse_rule(rule)
        if parsed is None:
            continue
        understood = True
        if _covers(parsed, moment):
            return True
    if not understood:
        return None
    return False


def places_from_elements(elements, latitude, longitude, moment):
    found = []
    for element in elements or []:
        place = _place_from_element(element, latitude, longitude, moment)
        if place is not None:
            found.append(place)
    return _best(found)


def nearby_open_places(latitude, longitude, moment):
    elements = _overpass(latitude, longitude)
    if elements is None:
        if haversine_miles((latitude, longitude), CAMPUS) > 15:
            return {"places": [], "fallback": True}
        from trips.views import PLACES

        backup = []
        for place in PLACES:
            kind = place.get("kind")
            if kind not in CATEGORIES:
                continue
            open_now = is_open(place.get("opening_hours"), moment)
            assumed = False
            if open_now is None and kind in ASSUMED_OPEN:
                open_now = True
                assumed = True
            if open_now is not True:
                continue
            miles = haversine_miles((latitude, longitude), (place["latitude"], place["longitude"]))
            weight, label = CATEGORIES[kind]
            backup.append(_row(place["name"], label, place["latitude"], place["longitude"], miles, weight, assumed))
        return {"places": _best(backup), "fallback": True}
    return {"places": places_from_elements(elements, latitude, longitude, moment), "fallback": False}


def _overpass(latitude, longitude):
    query = f"""
[out:json][timeout:8];
(
  node["amenity"~"^(police|hospital|clinic|pharmacy|library|fire_station|fuel)$"](around:{SEARCH_METERS},{latitude},{longitude});
  way["amenity"~"^(police|hospital|clinic|pharmacy|library|fire_station|fuel)$"](around:{SEARCH_METERS},{latitude},{longitude});
  node["shop"="convenience"](around:{SEARCH_METERS},{latitude},{longitude});
  way["shop"="convenience"](around:{SEARCH_METERS},{latitude},{longitude});
);
out center tags;
"""
    data = urlencode({"data": query}).encode()
    for endpoint in ENDPOINTS:
        request = Request(
            endpoint,
            data=data,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=8, context=_context()) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
            continue
        elements = payload.get("elements") if isinstance(payload, dict) else None
        if isinstance(elements, list):
            return elements
    return None


def _place_from_element(element, latitude, longitude, moment):
    if not isinstance(element, dict):
        return None
    tags = element.get("tags") or {}
    kind = tags.get("amenity")
    if tags.get("shop") == "convenience":
        kind = "convenience"
    if kind not in CATEGORIES:
        return None
    point = _point(element)
    if point is None:
        return None
    open_now = is_open(tags.get("opening_hours"), moment)
    assumed = False
    if open_now is None and kind in ASSUMED_OPEN:
        open_now = True
        assumed = True
    if open_now is not True:
        return None
    weight, label = CATEGORIES[kind]
    name = (tags.get("name") or tags.get("brand") or label).strip()
    if not name:
        return None
    miles = haversine_miles((latitude, longitude), point)
    return _row(name, label, point[0], point[1], miles, weight, assumed)


def _row(name, label, latitude, longitude, miles, weight, assumed):
    hours = "Usually staffed around the clock" if assumed else "Open now"
    return {
        "name": name[:120],
        "label": f"{label} · {hours} · {_miles(miles)}",
        "latitude": latitude,
        "longitude": longitude,
        "miles": miles,
        "score": weight - miles * MILE_COST,
    }


def _best(places):
    unique = []
    for place in sorted(places, key=lambda item: (-item["score"], item["miles"], item["name"])):
        if any(
            saved["name"].lower() == place["name"].lower()
            and haversine_miles((saved["latitude"], saved["longitude"]), (place["latitude"], place["longitude"])) < 0.05
            for saved in unique
        ):
            continue
        unique.append(place)
        if len(unique) >= RESULT_LIMIT:
            break
    return unique


def _point(element):
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def _miles(miles):
    if miles < 0.1:
        return "under 0.1 mi"
    return f"{miles:.1f} mi"


def _parse_rule(rule):
    closed = bool(re.search(r"\b(off|closed)\b", rule, re.I))
    text = re.sub(r"\b(off|closed)\b", " ", rule, flags=re.I).strip()
    match = DAY_RULE.match(text)
    if match:
        try:
            days = set(_day_list(match.group("days")))
        except KeyError:
            return None
        rest = match.group("rest")
    elif re.search(r"\d{1,2}:\d{2}", text):
        days = set(range(7))
        rest = text
    else:
        return None
    if closed and not TIME_RANGE.search(rest):
        return {"days": days, "ranges": [], "closed": True}
    ranges = []
    for start, end in TIME_RANGE.findall(rest):
        try:
            ranges.append(_range(start, end))
        except ValueError:
            return None
    if not ranges:
        return None
    return {"days": days, "ranges": ranges, "closed": False}


def _covers(parsed, moment):
    if parsed["closed"]:
        return False
    minute = moment.hour * 60 + moment.minute
    today = moment.weekday()
    yesterday = (today - 1) % 7
    for start, end in parsed["ranges"]:
        if end > start:
            if today in parsed["days"] and start <= minute < end:
                return True
        elif today in parsed["days"] and minute >= start:
            return True
        elif yesterday in parsed["days"] and minute < end:
            return True
    return False


def _day_list(token):
    days = []
    for part in token.split(","):
        part = part.strip()
        if "-" in part:
            start, end = [piece.strip() for piece in part.split("-", 1)]
            first, last = DAY_INDEX[start], DAY_INDEX[end]
            if first <= last:
                days.extend(range(first, last + 1))
            else:
                days.extend(list(range(first, 7)) + list(range(0, last + 1)))
        else:
            days.append(DAY_INDEX[part])
    return days


def _range(start, end):
    start_minutes = _minutes(start)
    end_minutes = _minutes(end)
    if end_minutes == 0 and start_minutes > 0:
        end_minutes = 24 * 60
    if not (0 <= start_minutes <= 24 * 60 and 0 <= end_minutes <= 24 * 60):
        raise ValueError
    return start_minutes, end_minutes


def _minutes(token):
    hour, minute = [int(part) for part in token.split(":", 1)]
    if hour == 24 and minute == 0:
        return 24 * 60
    if hour > 24 or minute > 59 or hour < 0 or minute < 0:
        raise ValueError
    return hour * 60 + minute
