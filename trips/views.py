from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import UserProfile
from trips.models import (
    CheckIn,
    Contact,
    ContactPing,
    EscalationSettings,
    LocationFix,
    SafetySession,
    SessionContact,
    TripScore,
)
from trips.monitor import decides, lab_rows, probability, signals_from_fixes, MODEL_NAME
from trips.routing import (
    CAMPUS,
    DEMO_HERE,
    ensure_destination,
    ensure_route,
    route_summary,
    scoring_route,
    search_places,
    stored_route,
    stored_steps,
)
from trips.safe_places import nearby_open_places

TRIP_LABELS = {
    "walk": "Walk",
    "rideshare": "Rideshare",
    "transit": "Transit",
    "run": "Run",
    "date": "Date",
    "travel": "Travel",
}

MONITOR_NOTES = {
    "cautious": "Cautious checks in sooner when the trip looks unusual.",
    "balanced": "Balanced is the recommended setting. It flags clear unusual signals.",
    "calm": "Calm waits for stronger unusual signals before a check-in.",
}

MODES = {
    "active": ("trips/session_active.html", "Your trip is active"),
    "checkin": ("trips/session_checkin.html", "Check-in"),
    "unsafe": ("trips/session_unsafe.html", "Unsafe Mode"),
    "places": ("trips/session_places.html", "Get Me Out"),
    "group": ("trips/session_group.html", "Group Mode"),
    "incident": ("trips/session_incident.html", "Incident"),
    "call": ("trips/session_call.html", "Incoming call"),
    "navigate": ("trips/session_navigate.html", "Navigate"),
}

PLACES = [
    {
        "slug": "illini",
        "name": "Illini Union",
        "distance": "0.3 mi",
        "detail": "Open 24/7 · Staffed",
        "open": True,
        "staffed": True,
        "miles": 0.3,
        "latitude": 40.109392,
        "longitude": -88.227221,
    },
    {
        "slug": "police",
        "name": "Campus Police",
        "kind": "police",
        "distance": "0.5 mi",
        "detail": "Open 24/7 · Staffed",
        "open": True,
        "staffed": True,
        "miles": 0.5,
        "latitude": 40.113156,
        "longitude": -88.224792,
    },
    {
        "slug": "cvs",
        "name": "CVS Pharmacy",
        "distance": "0.2 mi",
        "detail": "Open until 11 PM",
        "open": True,
        "staffed": False,
        "miles": 0.2,
        "latitude": 40.109486,
        "longitude": -88.244314,
    },
    {
        "slug": "grainger",
        "name": "Grainger Library",
        "distance": "0.7 mi",
        "detail": "Open until 12 AM",
        "open": True,
        "staffed": False,
        "miles": 0.7,
        "latitude": 40.112474,
        "longitude": -88.226860,
    },
]

CHECKIN_WAIT = timedelta(seconds=30)

PREVIEW_MODES = [
    ("active", "On track"),
    ("checkin", "Check-in"),
    ("unsafe", "Unsafe"),
    ("places", "Get out"),
    ("group", "Group"),
    ("incident", "Incident"),
]


def _kept_query(request):
    kept = request.GET.copy()
    for key in ("notice", "sent", "ok", "place", "filter", "tab"):
        kept.pop(key, None)
    return kept.urlencode()


def _places(place_filter):
    places = list(PLACES)
    if place_filter == "staffed":
        return [place for place in places if place["staffed"]]
    if place_filter == "closest":
        return sorted(places, key=lambda place: place["miles"])
    return places


def preview_context(request, mode):
    trip = request.GET.get("trip_type", "walk")
    if trip not in TRIP_LABELS:
        trip = "walk"
    monitoring = request.GET.get("monitoring", "balanced")
    if monitoring not in MONITOR_NOTES:
        monitoring = "balanced"
    destination = (request.GET.get("destination") or "Main Library").strip() or "Main Library"
    if request.user.is_authenticated and "monitoring" not in request.GET:
        monitoring = UserProfile.load(request.user).monitoring
    contacts = list(Contact.objects.filter(user=request.user) if request.user.is_authenticated else [])
    selected_ids = []
    for value in request.GET.getlist("share_with"):
        if value.isdigit():
            selected_ids.append(int(value))
    selected_contacts = [contact for contact in contacts if contact.id in selected_ids]
    if request.GET.get("sos") == "1" and not selected_contacts:
        selected_contacts = contacts
    share_with = ", ".join(contact.name for contact in selected_contacts) or "no one"
    place_filter = request.GET.get("filter", "all")
    if place_filter not in {"all", "open", "staffed", "closest"}:
        place_filter = "all"
    selected = request.GET.get("place", "")
    tab = request.GET.get("tab", "summary")
    if tab not in {"summary", "audio", "location"}:
        tab = "summary"
    return {
        "mode": mode,
        "trip_type": trip,
        "trip_label": TRIP_LABELS[trip],
        "monitoring": monitoring,
        "monitoring_label": monitoring.title(),
        "monitoring_note": MONITOR_NOTES[monitoring],
        "destination": destination,
        "contacts": contacts,
        "selected_ids": selected_ids,
        "share_with": share_with,
        "preview_query": _kept_query(request),
        "ok": request.GET.get("ok") == "1",
        "sent": request.GET.get("sent") == "1",
        "notice": request.GET.get("notice", ""),
        "tab": tab,
        "filter": place_filter,
        "filter_choices": (
            ("all", "All"),
            ("open", "Open now"),
            ("staffed", "Staffed"),
            ("closest", "Closest"),
        ),
        "places": _places(place_filter),
        "selected_place": next((place for place in PLACES if place["slug"] == selected), None),
        "return_session": _return_session(request),
        "modes": PREVIEW_MODES,
    }


def _refresh_checkins(session):
    checkin = session.open_checkin()
    if checkin and checkin.answered is None and timezone.now() >= checkin.deadline:
        _miss_checkin(session, checkin)
        session.refresh_from_db()


def _open_checkin(session):
    if session.escalated or session.open_checkin():
        return None
    number = session.missed_checkins + 1
    return CheckIn.objects.create(
        session=session,
        number=number,
        deadline=timezone.now() + CHECKIN_WAIT,
    )


def _miss_checkin(session, checkin):
    if checkin.answered is not None:
        return
    checkin.answered = False
    checkin.answered_at = timezone.now()
    checkin.save()
    session.missed_checkins += 1
    session.save(update_fields=["missed_checkins"])
    if session.missed_checkins >= 2:
        _escalate(session)
    else:
        _open_checkin(session)


def _escalate(session):
    if session.escalated:
        return
    session.escalated = True
    session.save(update_fields=["escalated"])
    settings = EscalationSettings.load(session.user) if session.user_id else None
    if session.latitude is not None and session.longitude is not None:
        where = f"{session.latitude:.5f}, {session.longitude:.5f}"
    else:
        where = "not available"
    for member in session.members.select_related("contact"):
        contact = member.contact
        if contact.custom_rules:
            source = contact
        elif settings is not None:
            source = settings
        else:
            source = contact
        if not source.share_location and not source.send_alert:
            continue
        location_text = where if source.share_location else "not shared"
        message = (
            f"Byway: two check-ins were missed on the way to {session.destination}. "
            f"Live location: {location_text}."
        )
        ContactPing.objects.create(
            session=session,
            contact=contact,
            shared_location=source.share_location,
            sent_alert=source.send_alert,
            message=message,
        )


def _return_session(request):
    value = request.GET.get("return_session", "")
    if not value.isdigit():
        return None
    owned = SafetySession.objects.filter(pk=int(value), status="active")
    if request.user.is_authenticated:
        owned = owned.filter(user=request.user)
    if owned.exists():
        return int(value)
    return None


def _mark_safe(session):
    if session.marked_safe:
        return
    session.marked_safe = True
    session.save(update_fields=["marked_safe"])
    told = []
    for ping in session.pings.select_related("contact").order_by("id"):
        if ping.contact_id in told:
            continue
        told.append(ping.contact_id)
        ContactPing.objects.create(
            session=session,
            contact=ping.contact,
            shared_location=False,
            sent_alert=True,
            message=f"Byway: I am safe on the way to {session.destination}.",
        )


def _session_or_404(session_id, user):
    return get_object_or_404(SafetySession, pk=session_id, status="active", user=user)


def _owned_session(session_id, user):
    return get_object_or_404(SafetySession, pk=session_id, user=user)


def _safe_place(slug):
    return next((place for place in PLACES if place["slug"] == slug), None)


def _chosen_place(request, destination):
    label = (request.POST.get("place_label") or "").strip()[:120]
    if not label or label != destination:
        return None
    try:
        latitude = float(request.POST.get("place_latitude"))
        longitude = float(request.POST.get("place_longitude"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


@login_required
@require_http_methods(["GET"])
def safe_nearby(request):
    monitoring = UserProfile.load(request.user).monitoring
    if monitoring not in MONITOR_NOTES:
        monitoring = "balanced"
    found = nearby_open_places(DEMO_HERE["latitude"], DEMO_HERE["longitude"], timezone.localtime())
    return render(
        request,
        "trips/safe_nearby.html",
        {
            "contacts": Contact.objects.filter(user=request.user),
            "monitoring": monitoring,
            "demo_here": DEMO_HERE,
            "places": found["places"],
            "fallback": found["fallback"],
        },
    )


@login_required
@require_http_methods(["POST"])
def safe_nearby_search(request):
    try:
        latitude = float(request.POST.get("latitude", ""))
        longitude = float(request.POST.get("longitude", ""))
        accuracy = request.POST.get("accuracy", "")
        accuracy_meters = float(accuracy) if accuracy else None
    except ValueError:
        return JsonResponse({"places": [], "error": "Location must be a number."}, status=400)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return JsonResponse({"places": [], "error": "That location is not usable."}, status=400)
    if accuracy_meters is not None and accuracy_meters > 1500:
        return JsonResponse(
            {"places": [], "error": "That location is too uncertain. Step outside or nearer a window and try again."}
        )
    last = request.session.get("safe_search_at")
    now = timezone.now().timestamp()
    if last is not None and now - float(last) < 2:
        return JsonResponse({"places": [], "error": "Wait a moment, then search again."}, status=429)
    request.session["safe_search_at"] = now
    found = nearby_open_places(latitude, longitude, timezone.localtime())
    if not found["places"] and found["fallback"]:
        return JsonResponse(
            {
                "places": [],
                "fallback": True,
                "error": "The place search is unavailable. Try again in a moment.",
            }
        )
    return JsonResponse(
        {
            "places": found["places"],
            "fallback": found["fallback"],
            "approximate": accuracy_meters is not None and accuracy_meters > 100,
        }
    )


@login_required
@require_http_methods(["GET"])
def session_start(request):
    return render(request, "trips/session_start.html", preview_context(request, "start"))


@login_required
@require_http_methods(["GET"])
def place_search(request):
    query = (request.GET.get("q") or "").strip()[:120]
    if len(query) < 2:
        return JsonResponse({"places": [], "error": "Type at least two letters."})
    last = request.session.get("place_search_at")
    now = timezone.now().timestamp()
    if last is not None and now - float(last) < 1.1:
        return JsonResponse(
            {"places": [], "error": "Wait a moment, then search again."},
            status=429,
        )
    request.session["place_search_at"] = now
    places = search_places(query)
    if places is None:
        return JsonResponse(
            {
                "places": [],
                "error": "The map search is unavailable. You can still start with the name you typed.",
            }
        )
    return JsonResponse({"places": places})


@login_required
@require_http_methods(["POST"])
def session_begin(request):
    trip = request.POST.get("trip_type", "walk")
    if trip not in TRIP_LABELS:
        trip = "walk"
    monitoring = request.POST.get("monitoring", "balanced")
    if monitoring not in MONITOR_NOTES:
        monitoring = "balanced"
    safe = _safe_place(request.POST.get("safe_place", ""))
    if safe:
        destination = safe["name"]
        chosen = (safe["latitude"], safe["longitude"])
    else:
        destination = (request.POST.get("destination") or "Main Library").strip()[:120] or "Main Library"
        chosen = _chosen_place(request, destination)
    session = SafetySession.objects.create(
        user=request.user,
        trip_type=trip,
        destination=destination,
        monitoring=monitoring,
        destination_latitude=chosen[0] if chosen else None,
        destination_longitude=chosen[1] if chosen else None,
    )
    selected = []
    for value in request.POST.getlist("share_with"):
        if value.isdigit():
            selected.append(int(value))
    for contact in Contact.objects.filter(user=request.user, id__in=selected):
        SessionContact.objects.create(session=session, contact=contact)
    return redirect("session_live", session.id)


@login_required
@require_http_methods(["GET"])
def session_live(request, session_id):
    session = _session_or_404(session_id, request.user)
    _refresh_checkins(session)
    ensure_destination(session)
    checkin = session.open_checkin()
    center = (
        [session.destination_latitude, session.destination_longitude]
        if session.destination_latitude is not None
        else [CAMPUS[0], CAMPUS[1]]
    )
    return render(
        request,
        "trips/session_live.html",
        {
            "session": session,
            "checkin": checkin,
            "pings": session.pings.select_related("contact"),
            "members": session.members.select_related("contact"),
            "score": session.scores.first(),
            "trip_label": TRIP_LABELS.get(session.trip_type, "Walk"),
            "monitoring_label": session.monitoring.title(),
            "monitoring_note": MONITOR_NOTES.get(session.monitoring, MONITOR_NOTES["balanced"]),
            "notify": request.GET.get("notify") == "1",
            "scored": request.GET.get("scored") == "1",
            "need_location": request.GET.get("need_location") == "1",
            "score_error": request.GET.get("score_error") == "1",
            "route_points": stored_route(session),
            "route_steps": stored_steps(session),
            "route_summary": route_summary(session),
            "map_center": center,
            "destination_point": center if session.destination_latitude is not None else None,
            "demo_here": DEMO_HERE,
            "page_title": _live_title(session, checkin),
        },
    )


def _trip_signals(session):
    return signals_from_fixes(session.fixes.all(), **scoring_route(session))


def _save_score(session, signals):
    features = [
        signals["route_deviation_miles"],
        signals["stop_minutes"],
        signals["eta_slip_minutes"],
        signals["movement_mph"],
    ]
    chance = probability(features)
    anomaly, threshold = decides(chance, session.monitoring)
    TripScore.objects.create(
        session=session,
        probability=chance,
        threshold=threshold,
        anomaly=anomaly,
        route_deviation_miles=signals["route_deviation_miles"],
        stop_minutes=signals["stop_minutes"],
        eta_slip_minutes=signals["eta_slip_minutes"],
        movement_mph=signals["movement_mph"],
        route_ready=signals["route_ready"],
        model_name=MODEL_NAME,
    )
    opened = bool(anomaly and _open_checkin(session))
    return chance, opened


def _live_title(session, checkin):
    if checkin:
        return "Check-in"
    if session.marked_safe:
        return "You're safe"
    if session.escalated:
        return "Contacts pinged"
    return "Your trip is active"


@login_required
@require_http_methods(["POST"])
def session_score(request, session_id):
    session = _session_or_404(session_id, request.user)
    _refresh_checkins(session)
    signals = _trip_signals(session)
    if signals is None:
        return redirect(f"/sessions/{session.id}/?need_location=1")
    try:
        _chance, opened = _save_score(session, signals)
    except ValueError:
        return redirect(f"/sessions/{session.id}/?score_error=1")
    target = redirect("session_live", session.id)
    target["Location"] += "?notify=1" if opened else "?scored=1"
    return target


@login_required
@require_http_methods(["GET"])
def session_score_api(request, session_id):
    session = _session_or_404(session_id, request.user)
    signals = _trip_signals(session)
    if signals is None:
        return JsonResponse(
            {"ok": False, "error": "At least two location updates are required."},
            status=400,
        )
    features = [
        signals["route_deviation_miles"],
        signals["stop_minutes"],
        signals["eta_slip_minutes"],
        signals["movement_mph"],
    ]
    try:
        chance = probability(features)
    except ValueError:
        return JsonResponse({"ok": False, "error": "The signals could not be scored."}, status=400)
    anomaly, threshold = decides(chance, session.monitoring)
    return JsonResponse(
        {
            "ok": True,
            "model": MODEL_NAME,
            "probability": round(chance, 4),
            "threshold": threshold,
            "monitoring": session.monitoring,
            "decision": "check-in" if anomaly else "on-track",
            "route_ready": signals["route_ready"],
            "signals": {
                "route_deviation_miles": round(signals["route_deviation_miles"], 3),
                "stop_minutes": round(signals["stop_minutes"], 2),
                "eta_slip_minutes": round(signals["eta_slip_minutes"], 2),
                "movement_mph": round(signals["movement_mph"], 2),
            },
        }
    )


@login_required
@require_http_methods(["GET"])
def session_export(request, session_id):
    session = _owned_session(session_id, request.user)
    payload = {
        "trip_type": session.trip_type,
        "destination": session.destination,
        "monitoring": session.monitoring,
        "status": session.status,
        "escalated": session.escalated,
        "marked_safe": session.marked_safe,
        "checkins": [
            {
                "number": item.number,
                "answered": item.answered,
                "opened_at": item.opened_at.isoformat(),
            }
            for item in session.checkins.order_by("number")
        ],
        "pings": [
            {
                "contact": item.contact.name,
                "shared_location": item.shared_location,
                "sent_alert": item.sent_alert,
                "message": item.message,
                "created_at": item.created_at.isoformat(),
            }
            for item in session.pings.select_related("contact")
        ],
        "scores": [
            {
                "probability": item.probability,
                "threshold": item.threshold,
                "decision": item.decision,
                "model": item.model_name,
                "created_at": item.created_at.isoformat(),
            }
            for item in session.scores.all()
        ],
        "location_updates": session.fixes.count(),
    }
    response = JsonResponse(payload)
    response["Content-Disposition"] = f'attachment; filename="byway-trip-{session.id}.json"'
    return response


@login_required
@require_http_methods(["POST"])
def session_answer(request, session_id):
    session = _session_or_404(session_id, request.user)
    checkin = session.open_checkin()
    if checkin:
        checkin.answered = True
        checkin.answered_at = timezone.now()
        checkin.save()
        session.missed_checkins = 0
        session.save(update_fields=["missed_checkins"])
    return redirect("session_live", session.id)


@login_required
@require_http_methods(["POST"])
def session_miss(request, session_id):
    session = _session_or_404(session_id, request.user)
    checkin = session.open_checkin()
    if checkin and timezone.now() + timedelta(seconds=2) >= checkin.deadline:
        _miss_checkin(session, checkin)
    elif checkin is None:
        _refresh_checkins(session)
    target = redirect("session_live", session.id)
    if session.open_checkin():
        target["Location"] += "?notify=1"
    return target


@login_required
@require_http_methods(["POST"])
def session_location(request, session_id):
    session = _session_or_404(session_id, request.user)
    try:
        latitude = float(request.POST.get("latitude", ""))
        longitude = float(request.POST.get("longitude", ""))
        accuracy = request.POST.get("accuracy", "")
        accuracy_meters = float(accuracy) if accuracy else None
    except ValueError:
        return JsonResponse({"ok": False, "error": "Location must be a number."}, status=400)
    if accuracy_meters is not None and accuracy_meters > 100:
        return JsonResponse({"ok": True, "ignored": True})
    session.latitude = latitude
    session.longitude = longitude
    session.save(update_fields=["latitude", "longitude"])
    LocationFix.objects.create(
        session=session,
        latitude=latitude,
        longitude=longitude,
        accuracy_meters=accuracy_meters,
    )
    ensure_route(session, latitude, longitude)
    session.refresh_from_db()
    opened = False
    signals = _trip_signals(session)
    if signals and not session.escalated and not session.marked_safe and not session.open_checkin():
        latest = session.scores.first()
        due = latest is None or timezone.now() - latest.created_at >= timedelta(seconds=20)
        if due:
            try:
                _chance, opened = _save_score(session, signals)
            except ValueError:
                opened = False
    return JsonResponse(
        {
            "ok": True,
            "ignored": False,
            "route": stored_route(session),
            "steps": stored_steps(session),
            "summary": route_summary(session),
            "checkin": opened,
            "route_ready": bool(session.route_points),
        }
    )


@login_required
@require_http_methods(["POST"])
def session_safe(request, session_id):
    session = _session_or_404(session_id, request.user)
    if session.escalated:
        _mark_safe(session)
    return redirect("session_live", session.id)


@login_required
@require_http_methods(["GET"])
def session_mode(request, mode):
    try:
        template, title = MODES[mode]
    except KeyError as error:
        raise Http404 from error
    context = preview_context(request, mode)
    context["page_title"] = title
    return render(request, template, context)


@login_required
@require_http_methods(["GET", "POST"])
def contacts(request):
    error = ""
    name = ""
    phone = ""
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        phone = request.POST.get("phone", "").strip()
        digits = "".join(character for character in phone if character.isdigit())
        if not name or not phone:
            error = "Add a name and a phone number."
        elif len(name) > 80 or len(phone) > 32:
            error = "Use a shorter name or phone number."
        elif len(digits) < 7:
            error = "Enter a phone number with at least 7 digits."
        elif Contact.objects.filter(user=request.user, name__iexact=name, phone=phone).exists():
            error = "That contact is already saved."
        else:
            Contact.objects.create(user=request.user, name=name, phone=phone)
            return redirect("contacts")
    return render(
        request,
        "trips/contacts.html",
        {
            "contacts": Contact.objects.filter(user=request.user),
            "error": error,
            "draft_name": name if error else "",
            "draft_phone": phone if error else "",
        },
    )


@login_required
@require_http_methods(["POST"])
def contact_delete(request, contact_id):
    get_object_or_404(Contact, pk=contact_id, user=request.user).delete()
    return redirect("contacts")


@login_required
@require_http_methods(["GET"])
def trip_list(request):
    sessions = SafetySession.objects.filter(user=request.user)
    trip_filter = request.GET.get("status", "all")
    if trip_filter == "active":
        visible = sessions.filter(status="active", escalated=False)
    elif trip_filter == "pinged":
        visible = sessions.filter(escalated=True)
    else:
        trip_filter = "all"
        visible = sessions
    return render(
        request,
        "trips/trips.html",
        {
            "sessions": visible[:20],
            "trip_filter": trip_filter,
            "trip_total": sessions.count(),
            "trip_pinged": sessions.filter(escalated=True).count(),
        },
    )


def _apply_rules(target, rules):
    target.checkin = "checkin" in rules
    target.share_location = "location" in rules
    target.send_alert = "alert" in rules


@login_required
@require_http_methods(["GET", "POST"])
def escalation(request):
    settings = EscalationSettings.load(request.user)
    if request.method == "POST":
        _apply_rules(settings, request.POST.getlist("rule"))
        settings.save()
        return redirect("/contacts/escalation/?saved=1")
    return render(
        request,
        "trips/escalation.html",
        {
            "contacts": Contact.objects.filter(user=request.user),
            "selected_rules": settings.selected_rules(),
            "saved": request.GET.get("saved") == "1",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def contact_edit(request, contact_id):
    contact = get_object_or_404(Contact, pk=contact_id, user=request.user)
    settings = EscalationSettings.load(request.user)
    if request.method == "POST":
        contact.custom_rules = request.POST.get("mode") == "custom"
        if contact.custom_rules:
            _apply_rules(contact, request.POST.getlist("rule"))
        contact.save()
        return redirect(f"/contacts/{contact.id}/edit/?saved=1")
    if contact.custom_rules:
        selected = contact.selected_rules()
    else:
        selected = settings.selected_rules()
    return render(
        request,
        "trips/contact_edit.html",
        {
            "contact": contact,
            "selected_rules": selected,
            "saved": request.GET.get("saved") == "1",
        },
    )


@login_required
@require_http_methods(["GET"])
def model_lab(request):
    ran = request.GET.get("run") == "1"
    return render(
        request,
        "trips/model_lab.html",
        {
            "ran": ran,
            "cases": lab_rows() if ran else [],
            "model_name": MODEL_NAME,
        },
    )
