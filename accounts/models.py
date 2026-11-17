from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    monitoring = models.CharField(max_length=20, default="balanced")
    audio = models.CharField(max_length=10, default="7")
    location = models.CharField(max_length=10, default="30")
    escalation = models.CharField(max_length=20, default="contacts")
    summary = models.CharField(max_length=20, default="review")

    @classmethod
    def load(cls, user):
        profile, _created = cls.objects.get_or_create(user=user)
        return profile
