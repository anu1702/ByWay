import math

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

MODEL_NAME = "logistic-regression-dev-v1"
THRESHOLDS = {
    "cautious": 0.35,
    "balanced": 0.50,
    "calm": 0.70,
}

# Hand-specified examples used only to fit the development model.
# Columns: route deviation miles, stop minutes, ETA slip minutes, movement mph.
_TRAIN_FEATURES = np.array(
    [
        [0.05, 1, 1, 3.0],
        [0.10, 2, 1, 2.8],
        [0.12, 3, 2, 3.1],
        [0.08, 2, 0, 2.4],
        [0.20, 4, 2, 2.6],
        [0.15, 3, 1, 2.5],
        [0.02, 6, 4, 0.4],
        [0.90, 22, 28, 0.2],
        [1.10, 30, 35, 0.1],
        [0.70, 18, 20, 0.3],
        [1.40, 8, 25, 3.2],
        [1.20, 2, 22, 3.4],
        [0.80, 3, 18, 2.9],
        [0.10, 20, 16, 0.0],
        [0.20, 24, 18, 0.1],
    ],
    dtype=float,
)
_TRAIN_LABELS = np.array([0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1])

SAMPLE_CASES = [
    {
        "name": "Normal coffee byway",
        "expected": "On track",
        "features": [0.15, 4, 2, 2.5],
    },
    {
        "name": "Long stop off-route",
        "expected": "Check-in",
        "features": [0.8, 25, 30, 0.1],
    },
    {
        "name": "Late bus wait",
        "expected": "On track for Balanced",
        "features": [0.05, 12, 10, 0.0],
    },
    {
        "name": "Wrong-direction trip",
        "expected": "Check-in",
        "features": [1.2, 1, 20, 3.0],
    },
]

_pipeline = None


def pipeline():
    global _pipeline
    if _pipeline is None:
        model = Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", LogisticRegression()),
            ]
        )
        model.fit(_TRAIN_FEATURES, _TRAIN_LABELS)
        _pipeline = model
    return _pipeline


def probability(features):
    values = [float(value) for value in features]
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError("Four finite signals are required.")
    chance = pipeline().predict_proba([values])[0, 1]
    return float(chance)


def decides(chance, monitoring):
    threshold = THRESHOLDS.get(monitoring, THRESHOLDS["balanced"])
    return chance >= threshold, threshold


def lab_rows():
    rows = []
    for case in SAMPLE_CASES:
        chance = probability(case["features"])
        decisions = {}
        for monitoring in THRESHOLDS:
            anomaly, _threshold = decides(chance, monitoring)
            decisions[monitoring] = "Check-in" if anomaly else "On track"
        rows.append(
            {
                "name": case["name"],
                "expected": case["expected"],
                "probability": chance,
                "decisions": decisions,
            }
        )
    return rows


def haversine_miles(start, end):
    radius_miles = 3958.8
    lat1 = math.radians(start[0])
    lat2 = math.radians(end[0])
    d_lat = lat2 - lat1
    d_lng = math.radians(end[1] - start[1])
    arc = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 2 * radius_miles * math.asin(math.sqrt(arc))


def _local_miles(latitude, longitude, origin_latitude):
    east = math.radians(longitude) * math.cos(math.radians(origin_latitude)) * 3958.8
    north = math.radians(latitude) * 3958.8
    return east, north


def miles_from_path(latitude, longitude, path):
    if len(path) < 2:
        return None
    origin = latitude
    point = _local_miles(latitude, longitude, origin)
    nearest = None
    for start, end in zip(path, path[1:]):
        start_xy = _local_miles(start[0], start[1], origin)
        end_xy = _local_miles(end[0], end[1], origin)
        span_x = end_xy[0] - start_xy[0]
        span_y = end_xy[1] - start_xy[1]
        length_sq = span_x * span_x + span_y * span_y
        if length_sq == 0:
            distance = math.hypot(point[0] - start_xy[0], point[1] - start_xy[1])
        else:
            along = ((point[0] - start_xy[0]) * span_x + (point[1] - start_xy[1]) * span_y) / length_sq
            along = max(0.0, min(1.0, along))
            distance = math.hypot(
                point[0] - (start_xy[0] + along * span_x),
                point[1] - (start_xy[1] + along * span_y),
            )
        if nearest is None or distance < nearest:
            nearest = distance
    return nearest


def remaining_miles(latitude, longitude, path):
    if len(path) < 2:
        return 0.0
    origin = latitude
    point = _local_miles(latitude, longitude, origin)
    best = None
    best_index = 0
    best_along = 0.0
    for index, (start, end) in enumerate(zip(path, path[1:])):
        start_xy = _local_miles(start[0], start[1], origin)
        end_xy = _local_miles(end[0], end[1], origin)
        span_x = end_xy[0] - start_xy[0]
        span_y = end_xy[1] - start_xy[1]
        length_sq = span_x * span_x + span_y * span_y
        if length_sq == 0:
            along = 0.0
            distance = math.hypot(point[0] - start_xy[0], point[1] - start_xy[1])
        else:
            along = ((point[0] - start_xy[0]) * span_x + (point[1] - start_xy[1]) * span_y) / length_sq
            along = max(0.0, min(1.0, along))
            distance = math.hypot(
                point[0] - (start_xy[0] + along * span_x),
                point[1] - (start_xy[1] + along * span_y),
            )
        if best is None or distance < best:
            best = distance
            best_index = index
            best_along = along
    leftover = haversine_miles(path[best_index], path[best_index + 1]) * (1 - best_along)
    for start, end in zip(path[best_index + 1 :], path[best_index + 2 :]):
        leftover += haversine_miles(start, end)
    return leftover


def signals_from_fixes(
    fixes,
    route_points=None,
    route_duration_seconds=None,
    route_distance_meters=None,
    route_started_at=None,
    allowance_miles=0.05,
):
    """Stop time and movement come from saved points. Deviation and arrival slip need a stored route."""
    points = list(fixes)
    if len(points) < 2:
        return None
    previous = points[-2]
    latest = points[-1]
    miles = haversine_miles(
        (previous.latitude, previous.longitude),
        (latest.latitude, latest.longitude),
    )
    elapsed_hours = max((latest.recorded_at - previous.recorded_at).total_seconds(), 1) / 3600
    movement = miles / elapsed_hours
    stopped_from = latest.recorded_at
    for point in reversed(points):
        apart = haversine_miles(
            (point.latitude, point.longitude),
            (latest.latitude, latest.longitude),
        )
        if apart <= 0.02:
            stopped_from = point.recorded_at
        else:
            break
    stop_minutes = (latest.recorded_at - stopped_from).total_seconds() / 60
    deviation = 0.0
    eta_slip = 0.0
    route_ready = bool(route_points) and len(route_points) >= 2
    if route_ready:
        raw = miles_from_path(latest.latitude, latest.longitude, route_points)
        deviation = max(0.0, (raw or 0.0) - allowance_miles)
        if route_duration_seconds and route_distance_meters and route_started_at:
            speed_mph = (route_distance_meters / 1609.34) / (route_duration_seconds / 3600)
            if speed_mph > 0:
                left_hours = remaining_miles(latest.latitude, latest.longitude, route_points) / speed_mph
                used_minutes = (latest.recorded_at - route_started_at).total_seconds() / 60
                eta_slip = max(0.0, used_minutes + left_hours * 60 - route_duration_seconds / 60)
    return {
        "route_deviation_miles": deviation,
        "stop_minutes": stop_minutes,
        "eta_slip_minutes": eta_slip,
        "movement_mph": movement,
        "route_ready": route_ready,
    }
