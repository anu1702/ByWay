from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import UserProfile
from accounts.services import demo_user


def _safe_next(value):
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/home/"


@require_http_methods(["GET", "POST"])
def login(request):
    if request.user.is_authenticated:
        return redirect("home")
    error = ""
    username = ""
    if request.method == "POST" and request.POST.get("demo") == "1":
        user = demo_user()
        auth_login(request, user)
        return redirect(_safe_next(request.POST.get("next")))
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is None:
            error = "That username and password did not match."
        else:
            auth_login(request, user)
            return redirect(_safe_next(request.POST.get("next")))
    return render(
        request,
        "accounts/login.html",
        {
            "error": error,
            "username": username,
            "next": request.GET.get("next", ""),
        },
    )


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    error = ""
    username = ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if not username or not password:
            error = "Choose a username and a password."
        elif User.objects.filter(username__iexact=username).exists():
            error = "That username is already in use."
        else:
            try:
                validate_password(password, User(username=username))
            except ValidationError as exc:
                error = " ".join(exc.messages)
            else:
                user = User.objects.create_user(username=username, password=password)
                UserProfile.load(user)
                auth_login(request, user)
                return redirect("home")
    return render(
        request,
        "accounts/register.html",
        {"error": error, "username": username},
    )


@login_required
@require_http_methods(["GET"])
def home(request):
    return render(request, "accounts/home.html")


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    profile_row = UserProfile.load(request.user)
    if request.method == "POST":
        monitoring = request.POST.get("monitoring", "balanced")
        audio = request.POST.get("audio", "7")
        location = request.POST.get("location", "30")
        escalation = request.POST.get("escalation", "contacts")
        summary = request.POST.get("summary", "review")
        if monitoring in {"cautious", "balanced", "calm"}:
            profile_row.monitoring = monitoring
        if audio in {"1", "7", "keep"}:
            profile_row.audio = audio
        if location in {"7", "30", "keep"}:
            profile_row.location = location
        if escalation in {"contacts", "ask", "off"}:
            profile_row.escalation = escalation
        if summary in {"review", "off"}:
            profile_row.summary = summary
        profile_row.save()
        return redirect("/profile/?saved=1")
    return render(
        request,
        "accounts/profile.html",
        {
            "monitoring": profile_row.monitoring,
            "audio": profile_row.audio,
            "location": profile_row.location,
            "escalation": profile_row.escalation,
            "summary": profile_row.summary,
            "saved": request.GET.get("saved") == "1",
        },
    )


@login_required
@require_http_methods(["POST"])
def logout_view(request):
    logout(request)
    return redirect("login")
