from django.urls import path

from trips import views

urlpatterns = [
    path("contacts/", views.contacts, name="contacts"),
    path("contacts/escalation/", views.escalation, name="escalation"),
    path("contacts/<int:contact_id>/edit/", views.contact_edit, name="contact_edit"),
    path("contacts/<int:contact_id>/delete/", views.contact_delete, name="contact_delete"),
    path("trips/", views.trip_list, name="trips"),
    path("model-lab/", views.model_lab, name="model_lab"),
    path("sessions/new/", views.session_start, name="session_start"),
    path("sessions/safe-nearby/", views.safe_nearby, name="safe_nearby"),
    path("sessions/safe-nearby/search/", views.safe_nearby_search, name="safe_nearby_search"),
    path("sessions/places/", views.place_search, name="place_search"),
    path("sessions/start/", views.session_begin, name="session_begin"),
    path("sessions/<int:session_id>/", views.session_live, name="session_live"),
    path("sessions/<int:session_id>/score/", views.session_score, name="session_score"),
    path("sessions/<int:session_id>/score.json", views.session_score_api, name="session_score_api"),
    path("sessions/<int:session_id>/export.json", views.session_export, name="session_export"),
    path("sessions/<int:session_id>/answer/", views.session_answer, name="session_answer"),
    path("sessions/<int:session_id>/demo-checkin/", views.session_demo_checkin, name="session_demo_checkin"),
    path("sessions/<int:session_id>/miss/", views.session_miss, name="session_miss"),
    path("sessions/<int:session_id>/location/", views.session_location, name="session_location"),
    path("sessions/<int:session_id>/safe/", views.session_safe, name="session_safe"),
    path("sessions/group/invite/", views.group_invite, name="group_invite"),
    path("sessions/<slug:mode>/", views.session_mode, name="session_mode"),
]
