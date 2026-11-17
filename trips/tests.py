from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from accounts.services import demo_user
from trips.models import CheckIn, Contact, LocationFix, SafetySession
from trips.monitor import decides, lab_rows, miles_from_path, probability
from trips.routing import DEMO_HERE, directions_from_steps, places_from_payload
from trips.safe_places import is_open, places_from_elements


class MonitorTests(TestCase):
    def test_sample_cases_follow_the_thresholds(self):
        rows = {row["name"]: row for row in lab_rows()}
        coffee = rows["Normal coffee byway"]["probability"]
        bus = rows["Late bus wait"]["probability"]
        stopped = rows["Long stop off-route"]["probability"]
        wrong = rows["Wrong-direction trip"]["probability"]

        self.assertFalse(decides(coffee, "cautious")[0])
        self.assertTrue(decides(bus, "cautious")[0])
        self.assertFalse(decides(bus, "balanced")[0])
        self.assertFalse(decides(bus, "calm")[0])
        self.assertTrue(decides(stopped, "calm")[0])
        self.assertTrue(decides(wrong, "balanced")[0])
        self.assertGreater(bus, coffee)
        self.assertLess(bus, stopped)

    def test_distance_from_a_route(self):
        path = [[40.11, -88.24], [40.11, -88.22]]
        self.assertLess(miles_from_path(40.11, -88.23, path), 0.05)
        self.assertAlmostEqual(miles_from_path(40.1245, -88.23, path), 1.0, delta=0.15)

    def test_bad_signals_are_rejected(self):
        with self.assertRaises(ValueError):
            probability([1, 2, 3])


class AccountAccessTests(TestCase):
    def test_home_requires_sign_in(self):
        response = self.client.get("/home/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/?next=", response.url)

    def test_demo_mode_keeps_existing_contacts(self):
        Contact.objects.create(name="Sam Ellis", phone="3125550198")
        response = self.client.post("/", {"demo": "1"})
        self.assertRedirects(response, "/home/")
        self.assertEqual(Contact.objects.get(name="Sam Ellis").user.username, "maya")

    def test_one_account_cannot_open_another_trip(self):
        owner = User.objects.create_user("owner", password="byway-owner-pass")
        other = User.objects.create_user("other", password="byway-other-pass")
        session = SafetySession.objects.create(
            user=owner,
            trip_type="walk",
            destination="Main Library",
            monitoring="cautious",
        )
        self.client.force_login(other)
        response = self.client.get(f"/sessions/{session.id}/")
        self.assertEqual(response.status_code, 404)

    def test_score_needs_two_location_updates(self):
        user = demo_user()
        self.client.force_login(user)
        session = SafetySession.objects.create(
            user=user,
            trip_type="walk",
            destination="Main Library",
            monitoring="cautious",
        )
        response = self.client.get(f"/sessions/{session.id}/score.json")
        self.assertEqual(response.status_code, 400)

    def test_a_long_stop_can_open_a_check_in(self):
        user = demo_user()
        self.client.force_login(user)
        session = SafetySession.objects.create(
            user=user,
            trip_type="walk",
            destination="Main Library",
            monitoring="cautious",
        )
        earlier = timezone.now() - timedelta(minutes=25)
        first = LocationFix.objects.create(session=session, latitude=40.11, longitude=-88.22)
        LocationFix.objects.filter(pk=first.pk).update(recorded_at=earlier)
        LocationFix.objects.create(session=session, latitude=40.11, longitude=-88.22)
        response = self.client.post(f"/sessions/{session.id}/score/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("notify=1", response.url)
        self.assertEqual(session.checkins.count(), 1)
        self.assertTrue(session.scores.filter(anomaly=True).exists())


class PlaceSearchTests(TestCase):
    def test_place_results_keep_a_name_and_pin(self):
        places = places_from_payload(
            [
                {
                    "lat": "40.1",
                    "lon": "-88.2",
                    "name": "Main Library",
                    "display_name": "Main Library, Urbana",
                },
                {"lat": "nope", "lon": "-88.2", "name": "Bad"},
                "skip",
            ]
        )
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0]["name"], "Main Library")
        self.assertAlmostEqual(places[0]["latitude"], 40.1)

    def test_a_chosen_place_is_saved_on_the_trip(self):
        user = demo_user()
        self.client.force_login(user)
        response = self.client.post(
            "/sessions/start/",
            {
                "trip_type": "walk",
                "destination": "Main Library",
                "monitoring": "balanced",
                "place_label": "Main Library",
                "place_latitude": "40.1047",
                "place_longitude": "-88.2290",
            },
        )
        self.assertEqual(response.status_code, 302)
        session = SafetySession.objects.latest("id")
        self.assertAlmostEqual(session.destination_latitude, 40.1047)
        self.assertAlmostEqual(session.destination_longitude, -88.229)

    def test_a_place_label_must_match_the_destination(self):
        user = demo_user()
        self.client.force_login(user)
        self.client.post(
            "/sessions/start/",
            {
                "trip_type": "walk",
                "destination": "Main Library",
                "monitoring": "balanced",
                "place_label": "Somewhere else",
                "place_latitude": "40.1047",
                "place_longitude": "-88.2290",
            },
        )
        session = SafetySession.objects.latest("id")
        self.assertIsNone(session.destination_latitude)

    def test_a_safe_place_sets_the_destination(self):
        user = demo_user()
        self.client.force_login(user)
        response = self.client.post(
            "/sessions/start/",
            {
                "trip_type": "walk",
                "destination": "Main Library",
                "monitoring": "balanced",
                "safe_place": "police",
                "place_label": "Main Library",
                "place_latitude": "1",
                "place_longitude": "2",
            },
        )
        self.assertEqual(response.status_code, 302)
        session = SafetySession.objects.latest("id")
        self.assertEqual(session.destination, "Campus Police")
        self.assertAlmostEqual(session.destination_latitude, 40.113156)
        self.assertAlmostEqual(session.destination_longitude, -88.224792)

    def test_place_search_returns_matches(self):
        user = demo_user()
        self.client.force_login(user)
        found = [
            {
                "name": "Main Library",
                "label": "Main Library, Urbana",
                "latitude": 40.1,
                "longitude": -88.2,
            }
        ]
        with patch("trips.views.search_places", return_value=found):
            response = self.client.get("/sessions/places/", {"q": "library"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["places"][0]["name"], "Main Library")


class OpenPlaceTests(TestCase):
    def test_opening_hours_use_the_current_moment(self):
        chicago = ZoneInfo("America/Chicago")
        monday_evening = datetime(2026, 11, 16, 18, 34, tzinfo=chicago)
        sunday_evening = datetime(2026, 11, 15, 18, 0, tzinfo=chicago)
        saturday_night = datetime(2026, 11, 21, 1, 0, tzinfo=chicago)
        self.assertTrue(is_open("24/7", monday_evening))
        self.assertFalse(is_open("Mo-Fr 09:00-17:00", monday_evening))
        self.assertTrue(is_open("Mo-Fr 09:00-20:00; Sa 09:00-18:00; Su closed", monday_evening))
        self.assertFalse(is_open("Mo-Fr 08:00-12:30, 13:00-20:00", monday_evening.replace(hour=12, minute=45)))
        self.assertTrue(is_open("Mo-Fr 08:00-12:30, 13:00-20:00", monday_evening.replace(hour=13, minute=15)))
        self.assertTrue(is_open("Mo-Th 08:00-24:00; Fr 08:00-18:00; Sa 10:00-17:00, Su 13:00-24:00", sunday_evening))
        self.assertTrue(is_open("Fr 22:00-02:00", saturday_night))
        self.assertIsNone(is_open("", monday_evening))
        self.assertIsNone(is_open("ask at the desk", monday_evening))

    def test_a_close_open_store_beats_a_distant_station(self):
        moment = datetime(2026, 11, 16, 18, 34, tzinfo=ZoneInfo("America/Chicago"))
        places = places_from_elements(
            [
                {
                    "lat": 40.128,
                    "lon": -88.2272,
                    "tags": {"amenity": "police", "name": "Far Station"},
                },
                {
                    "lat": 40.112,
                    "lon": -88.2272,
                    "tags": {"amenity": "pharmacy", "name": "Near Pharmacy", "opening_hours": "Mo-Fr 09:00-20:00"},
                },
                {
                    "lat": 40.111,
                    "lon": -88.2272,
                    "tags": {"amenity": "clinic", "name": "Closed Clinic", "opening_hours": "Mo-Fr 09:00-17:00"},
                },
            ],
            40.1106,
            -88.2272,
            moment,
        )
        self.assertEqual([place["name"] for place in places], ["Near Pharmacy", "Far Station"])

    def test_turn_instructions_name_the_street_and_the_arrival(self):
        steps = directions_from_steps(
            [
                {
                    "distance": 180,
                    "name": "West Springfield Avenue",
                    "maneuver": {"type": "depart", "modifier": "east"},
                },
                {
                    "distance": 90,
                    "name": "South Vine Street",
                    "maneuver": {"type": "turn", "modifier": "right"},
                },
                {"distance": 0, "name": "", "maneuver": {"type": "arrive"}},
            ],
            "Urbana Police Department",
        )
        self.assertEqual(steps[0]["text"], "Head east on West Springfield Avenue")
        self.assertEqual(steps[1]["text"], "Turn right onto South Vine Street")
        self.assertEqual(steps[2]["text"], "Arrive at Urbana Police Department")
        self.assertTrue(steps[0]["distance"].endswith("mi"))
        self.assertTrue(steps[1]["distance"].endswith("ft"))

    def test_suggestions_start_from_the_demo_address(self):
        self.client.force_login(demo_user())
        found = {
            "places": [
                {
                    "name": "Campus Police",
                    "label": "Police · Open now · 0.2 mi",
                    "latitude": 40.113156,
                    "longitude": -88.224792,
                    "miles": 0.2,
                    "score": 90,
                }
            ],
            "fallback": False,
        }
        with patch("trips.views.nearby_open_places", return_value=found) as search:
            response = self.client.get("/sessions/safe-nearby/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "401 W Springfield Ave, Urbana")
        self.assertContains(response, "Campus Police")
        latitude, longitude, _moment = search.call_args[0]
        self.assertAlmostEqual(latitude, DEMO_HERE["latitude"])
        self.assertAlmostEqual(longitude, DEMO_HERE["longitude"])

    def test_safe_search_requires_a_location(self):
        self.client.force_login(demo_user())
        response = self.client.post("/sessions/safe-nearby/search/", {"latitude": "nope"})
        self.assertEqual(response.status_code, 400)


class GroupInviteTests(TestCase):
    def test_group_mode_invites_before_the_outing(self):
        self.client.force_login(demo_user())
        home = self.client.get("/home/")
        self.assertContains(home, 'href="/sessions/group/invite/"')

        page = self.client.get("/sessions/group/invite/")
        self.assertContains(page, "Invite your group")
        self.assertContains(page, "Priya")
        self.assertContains(page, "Open the outing")
        self.assertContains(page, "A phone text is not sent yet.")

        sent = self.client.post("/sessions/group/invite/", {"name": "Priya"}, follow=True)
        self.assertContains(sent, "Invite saved.")
        self.assertContains(sent, "Invited")

        outing = self.client.get("/sessions/group/")
        self.assertContains(outing, "Girls Night Out")
        self.assertContains(outing, "group-map")

    def test_a_check_in_offers_the_four_next_steps(self):
        user = demo_user()
        self.client.force_login(user)
        session = SafetySession.objects.create(
            user=user,
            trip_type="walk",
            destination="Main Library",
            monitoring="balanced",
        )
        CheckIn.objects.create(
            session=session,
            number=1,
            deadline=timezone.now() + timedelta(minutes=1),
        )
        page = self.client.get(f"/sessions/{session.id}/")
        self.assertContains(page, "I’m Okay")
        self.assertContains(page, "Keep Monitoring")
        self.assertContains(page, "Get Me Out")
        self.assertContains(page, "Activate Unsafe Mode")
        sent = self.client.post(f"/sessions/{session.id}/answer/", {"next": "unsafe"})
        self.assertEqual(sent.status_code, 302)
        self.assertIn("/sessions/unsafe/", sent.url)
        self.assertIn(f"return_session={session.id}", sent.url)
        CheckIn.objects.create(
            session=session,
            number=2,
            deadline=timezone.now() + timedelta(minutes=1),
        )
        places = self.client.post(f"/sessions/{session.id}/answer/", {"next": "places"})
        self.assertEqual(places.status_code, 302)
        self.assertIn("/sessions/safe-nearby/", places.url)
        self.assertIn(f"return_session={session.id}", places.url)
        self.assertIsNone(session.open_checkin())

    def test_demo_button_opens_a_check_in(self):
        user = demo_user()
        self.client.force_login(user)
        session = SafetySession.objects.create(
            user=user,
            trip_type="walk",
            destination="Main Library",
            monitoring="balanced",
        )
        response = self.client.post(f"/sessions/{session.id}/demo-checkin/", follow=True)
        self.assertContains(response, "Are you okay?")
        self.assertContains(response, "Sample signals for this demo.")
        self.assertContains(response, "Activate Unsafe Mode")
        self.assertIsNotNone(session.open_checkin())
