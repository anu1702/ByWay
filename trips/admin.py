from django.contrib import admin

from trips.models import Contact, ContactPing, EscalationSettings, LocationFix, SafetySession, TripScore


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "user", "custom_rules", "created_at")
    search_fields = ("name", "phone")


@admin.register(EscalationSettings)
class EscalationSettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "checkin", "share_location", "send_alert")


@admin.register(SafetySession)
class SafetySessionAdmin(admin.ModelAdmin):
    list_display = ("destination", "user", "trip_type", "missed_checkins", "escalated", "marked_safe", "created_at")


@admin.register(ContactPing)
class ContactPingAdmin(admin.ModelAdmin):
    list_display = ("contact", "shared_location", "sent_alert", "created_at")


@admin.register(LocationFix)
class LocationFixAdmin(admin.ModelAdmin):
    list_display = ("session", "latitude", "longitude", "accuracy_meters", "recorded_at")


@admin.register(TripScore)
class TripScoreAdmin(admin.ModelAdmin):
    list_display = ("session", "probability", "anomaly", "model_name", "created_at")
