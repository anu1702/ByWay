# Byway

Byway is a personal safety companion for a trip you choose to share. You pick a destination and the contacts for that trip. If the trip looks unusual, Byway asks you to check in. You decide what happens next. Two missed check-ins save your latest location and a ping for the contacts whose rules allow it.

Byway does not call or text anyone. Call 911 only opens your phone's dialer.

## Features

- Accounts, with separate contacts, escalation rules, and trips.
- A safety session for a walk, rideshare, transit trip, run, date, or other travel. Monitoring is Cautious, Balanced, or Calm.
- A destination search, a road route, and turn-by-turn directions on the live trip.
- Open, staffed places near you, ranked by staffing, distance, and ease of commute. You pick the place.
- A logistic regression monitor (`logistic-regression-dev-v1`) that scores the trip and opens a check-in when the score crosses your monitoring level.
- Model Lab, which runs the same model on four sample trips.
- A JSON score for a trip, and a JSON export of a trip.

## Requirements

Python 3.11. Dependencies are listed in `requirements.txt` (Django 5.2 and scikit-learn).

## Install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment variables

These are optional for local development. The defaults are for this machine only.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | a development-only key | Django secret key. Set this before any real deployment. |
| `DJANGO_DEBUG` | `true` | `true` or `false` |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` | Comma-separated hosts |

Do not commit a `.env` file. The database file `db.sqlite3` is also ignored.

## Database

Byway uses SQLite. `migrate` creates `db.sqlite3` in the project folder.

```bash
python manage.py migrate
```

## Run

```bash
python manage.py runserver 127.0.0.1:8001
```

Open http://127.0.0.1:8001/ and choose **Use demo mode**, or sign in as `maya` / `byway-demo`. Create an account if you want an empty one.

The running demo treats **401 W Springfield Ave, Urbana** as your current location, so a trip can start without browser GPS. Place search, the road route, and the open-place list need a network connection. They use OpenStreetMap.

## AI

The monitor is documented in `README_AI.md`.

- Start a safety session. Byway scores new location points on its own and opens a check-in when the score crosses the level you chose.
- Open **Profile**, then **Model Lab**, and run the sample cases. That page shows the model's probabilities and does not start a trip.

## Tests

```bash
python manage.py test
```
