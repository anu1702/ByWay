from django.conf import settings
from django.db import models


class EscalationSettings(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="escalation",
    )
    checkin = models.BooleanField(default=True)
    share_location = models.BooleanField(default=True)
    send_alert = models.BooleanField(default=True)

    @classmethod
    def load(cls, user):
        settings_row, _created = cls.objects.get_or_create(user=user)
        return settings_row

    def selected_rules(self):
        return _selected_rules(self)


class Contact(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    name = models.CharField(max_length=80)
    phone = models.CharField(max_length=32)
    custom_rules = models.BooleanField(default=False)
    checkin = models.BooleanField(default=True)
    share_location = models.BooleanField(default=True)
    send_alert = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name

    @property
    def initial(self):
        return self.name[:1].upper()

    def selected_rules(self):
        if self.custom_rules:
            return _selected_rules(self)
        if self.user_id is None:
            return ["checkin", "location", "alert"]
        return EscalationSettings.load(self.user).selected_rules()


class SafetySession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    trip_type = models.CharField(max_length=20)
    destination = models.CharField(max_length=120)
    monitoring = models.CharField(max_length=20, default="balanced")
    status = models.CharField(max_length=20, default="active")
    missed_checkins = models.PositiveSmallIntegerField(default=0)
    escalated = models.BooleanField(default=False)
    marked_safe = models.BooleanField(default=False)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    destination_latitude = models.FloatField(null=True, blank=True)
    destination_longitude = models.FloatField(null=True, blank=True)
    route_points = models.TextField(blank=True, default="")
    route_steps = models.TextField(blank=True, default="")
    route_duration_seconds = models.FloatField(null=True, blank=True)
    route_distance_meters = models.FloatField(null=True, blank=True)
    route_started_at = models.DateTimeField(null=True, blank=True)
    route_status = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def open_checkin(self):
        return self.checkins.filter(answered__isnull=True).order_by("-number").first()


class SessionContact(models.Model):
    session = models.ForeignKey(SafetySession, on_delete=models.CASCADE, related_name="members")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="sessions")


class CheckIn(models.Model):
    session = models.ForeignKey(SafetySession, on_delete=models.CASCADE, related_name="checkins")
    number = models.PositiveSmallIntegerField()
    opened_at = models.DateTimeField(auto_now_add=True)
    deadline = models.DateTimeField()
    answered = models.BooleanField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)


class LocationFix(models.Model):
    session = models.ForeignKey(SafetySession, on_delete=models.CASCADE, related_name="fixes")
    latitude = models.FloatField()
    longitude = models.FloatField()
    accuracy_meters = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recorded_at", "id"]


class TripScore(models.Model):
    session = models.ForeignKey(SafetySession, on_delete=models.CASCADE, related_name="scores")
    probability = models.FloatField()
    threshold = models.FloatField()
    anomaly = models.BooleanField()
    route_deviation_miles = models.FloatField()
    stop_minutes = models.FloatField()
    eta_slip_minutes = models.FloatField()
    movement_mph = models.FloatField()
    route_ready = models.BooleanField(default=False)
    model_name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def decision(self):
        return "Check-in" if self.anomaly else "On track"


class ContactPing(models.Model):
    session = models.ForeignKey(SafetySession, on_delete=models.CASCADE, related_name="pings")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="pings")
    shared_location = models.BooleanField(default=False)
    sent_alert = models.BooleanField(default=False)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


def _selected_rules(source):
    selected = []
    if source.checkin:
        selected.append("checkin")
    if source.share_location:
        selected.append("location")
    if source.send_alert:
        selected.append("alert")
    return selected
