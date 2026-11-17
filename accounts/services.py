from django.contrib.auth.models import User

from accounts.models import UserProfile
from trips.models import Contact, EscalationSettings, SafetySession

DEMO_USERNAME = "maya"
DEMO_PASSWORD = "byway-demo"


def demo_user():
    user, _created = User.objects.get_or_create(
        username=DEMO_USERNAME,
        defaults={"first_name": "Maya"},
    )
    if not user.first_name:
        user.first_name = "Maya"
    if not user.check_password(DEMO_PASSWORD):
        user.set_password(DEMO_PASSWORD)
    user.save()
    Contact.objects.filter(user__isnull=True).update(user=user)
    SafetySession.objects.filter(user__isnull=True).update(user=user)
    EscalationSettings.objects.filter(user__isnull=True).update(user=user)
    UserProfile.load(user)
    return user
