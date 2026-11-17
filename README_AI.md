# Byway AI

## Model

`logistic-regression-dev-v1` is a scikit-learn `Pipeline`: `StandardScaler` then `LogisticRegression`.

It is fit in memory, when the process starts, on 15 hand-specified trips. The four Model Lab trips are not in that fit. There is no measured accuracy, precision, or recall for this model. Model Lab shows the probabilities the pipeline actually returns.

Features, in order:

1. Route deviation in miles.
2. Stop duration in minutes.
3. ETA slip in minutes.
4. Movement in miles per hour.

A check-in opens when the anomaly probability reaches the monitoring threshold:

- Cautious: 0.35
- Balanced: 0.50
- Calm: 0.70

This model stays local. It does not call a hosted AI API, so a trip's location is not sent to an outside model.

## Why this model

The decision is a yes-or-no check-in from four numeric signals. Logistic regression is small, runs on CPU, and returns a probability the monitoring levels can share. A hosted language model would add cost and would send location-related data off the machine for a decision that does not need generated text.

## Workflow

1. The live trip posts a location to `/sessions/<id>/location/`. This demo sends 401 W Springfield Ave, Urbana, rather than asking the browser for GPS.
2. Updates with accuracy worse than 100 meters are ignored.
3. Saved points are read about every 20 seconds.
4. Stop time and movement are computed from those points.
5. If you picked a place from the search, Byway already has its pin. Otherwise the first accepted point looks up the destination. That same update asks for a road route. The request sends the start point and destination to the routing service. Later points stay in Byway.
6. Deviation is the distance from the latest point to that route, after a small allowance that is wider for a rideshare. Arrival slip compares the time already used plus the time left on the route with the original estimate.
7. If no route is found, those two signals stay at 0.
8. The pipeline returns a probability.
9. The score is saved. If it crosses the trip's threshold, Byway opens a check-in.

The same pipeline scores the Model Lab cases. That page does not open a check-in.

`GET /sessions/<id>/score.json` returns the current score without opening a check-in. It asks for two location updates first.

## Limits

- If the routing service is unavailable, deviation and arrival slip stay at 0. A stop can still move the score. On the current fit, 25 minutes in one place with no route is about 0.45, so Cautious checks in and Balanced stays on track.
- The live map uses the demo start above. Updates stop when the browser tab closes.
- The training examples were written by hand. They are not a record of real trips.
- Closing the browser tab ends location updates.
- A phone text is not sent. Pings are stored in Byway.

## If scoring fails

Missing location updates return a message and leave the trip on track. A bad feature vector returns an error and does not open a check-in. The model itself stays on this machine. The route request can fail, and then scoring continues from stop time and movement.
