# Segment Predictor

A Streamlit application that predicts cycling segment times on any Strava segment using a physics-based model, real weather forecasts, and a CP/W' fatigue model. It also finds the optimal power-pacing strategy across variable terrain to deliver your fastest possible time.

---

## What it does

Given a Strava segment and an athlete's power curve, the app answers two questions:

1. **How long will this segment take?** Under current or forecast weather, at the rider's sustainable power for the segment's duration.
2. **How should I pace it?** Per-section power targets that extract the most out of the rider's anaerobic work capacity (W') given the actual gradient profile.

It also surfaces the best segments in a region for a given day's conditions — ranked by how close the rider can get to the KOM/QOM given the forecast wind.

---

## Features

### Daily Planner
Ranks every segment in the selected region for any day in the next 7 days. Factors in:
- Weather forecast at segment location (temperature, wind speed, wind direction, precipitation)
- Segment bearing vs. wind direction → computed tailwind component
- Athlete's sustainable power for the expected segment duration
- Air density at segment elevation

Returns segments ordered by "% of KOM" — the estimated ratio of the rider's time to the current leaderboard best.

### Segment Simulator
Deep-dive view for a single segment:
- Physics-based time estimate with full conditions breakdown
- **Even-power model** — constant watts across variable terrain, calibrated to target ~97.5% W' depletion
- **Optimized pacing model** — per-section power allocation that surges steep pitches and eases flats
- 7-day forecast rollout: optimized time predicted for each of the next 8 days
- Side-by-side power and speed profiles

### Favorites (signed-in users)
Star segments across any region. The Favorites tab re-simulates each favorite against today's weather and ranks them by best time-vs-KOM ratio.

### Segment Requests
Users can submit Strava segment IDs to be added to the database. Requests queue in Supabase; an admin pipeline processes them.

### Excluded Segments
Admin tool for flagging segments with bad GPS or other data quality issues so they never appear in results.

### Feedback
In-app form for bug reports, feature requests, and data issues. Stored in Supabase.

---

## Architecture

### Tech stack
- **Frontend & runtime**: Streamlit (Python)
- **Segment + leaderboard data**: SQLite (`segments.db`, bundled with the app, ~13 MB)
- **User auth, favorites, analytics, segment/feedback requests**: Supabase
- **Weather**: OpenWeatherMap free tier (5-day/3-hour forecast + geocoding)
- **Elevation cleaning**: Open-Meteo elevation API (no key required) + SciPy Gaussian filtering
- **Strava data ingestion**: separate `Segment_Pull.py` pipeline (not invoked at runtime)

### Data inventory

The bundled `segments.db` currently contains:

| Table | Row count | What it holds |
|---|---:|---|
| `segments` | **3,448** | Segment metadata: name, distance, avg/max grade, elevation gain, start/end coordinates, polyline |
| `clean_seg_points` | **67,580** | Cleaned elevation profile points (avg 19.6 per segment, range 2–393) |
| `leaderboard` | 27,157 | Current KOM times and athlete info |
| `leaderboard_qom` | 28,567 | Current QOM times |
| `clean_seg_qa` | 3,448 | Quality metrics for each cleaned elevation profile |

**Coverage**: 3,448 segments across 30 US states and 4 countries. Top states: WA (732), CA (422), CO (334), NC (330), UT (211), PA (205), OR (188). Segment lengths range from 68 m to 39.3 km (average 1.6 km), with average gradients from −8.2% to 30.9% (overall average 6.0%).

### Runtime data flow

```
User loads app
  ↓
Streamlit caches segment queries from segments.db (SQLite, read-only)
  ↓
Supabase provides: auth state, favorites, flags, request queues
  ↓
OpenWeatherMap provides: geocoding + 5-day/3-hour forecast (cached 3hr)
  ↓
Physics model runs in-process (Segment_Optimizer.py)
  ↓
Analytics events fire-and-forget to Supabase
```

---

## Physics model

The app runs two levels of physics simulation. Both solve the same underlying power-balance equation; they differ in how they handle fatigue and terrain variability.

### Power balance (common to all models)

At any instant, the rider's delivered power at the wheel equals the sum of resistive forces times velocity:

```
P_wheel = v · (F_gravity + F_rolling + F_aero)
```

Where:
- `F_gravity = m · g · sin(θ)` — `m` is rider + bike mass, `θ` is road gradient
- `F_rolling = m · g · cos(θ) · Crr` — `Crr` adjusts up 20% in wet conditions
- `F_aero = ½ · ρ · CdA · v_apparent²` — `v_apparent` is rider speed plus effective headwind component
- `P_wheel = P_rider · (1 − drivetrain_loss)` — default drivetrain loss 3–4%

Air density `ρ` is computed from temperature, atmospheric pressure, and elevation per the ideal gas law.

### Fatigue: CP / W' model

The rider's power curve (1, 3, 8, 20-minute max efforts) is fit to the critical-power hyperbolic:

```
P(t) = CP + W' / t
```

Where **CP** is the asymptotic critical power (theoretical indefinite-sustainable output) and **W'** is the anaerobic work capacity in joules (the finite energy reservoir above CP).

During simulation, W' depletes when `P > CP` at rate `(P − CP) / W'` per second, and recovers below CP at a rate proportional to how far below CP the rider is. When depletion hits 100%, the model caps power at 70% of CP until recovery.

### Model 1 — Basic estimator (Daily Planner, initial time display)

Single-grade physics with sustainable-power lookup. Computes `sustainable_power(duration)` from the CP/W' curve, solves for steady-state speed at the segment's average gradient, returns `distance / speed`. No W' tracking during the ride.

Fast enough to rank hundreds of segments per page load.

### Model 2 — Even-power simulation (Simulator tab)

Per-section physics sim with W' tracking. Holds constant power across all gradient sections, integrates the force-balance equation at `dt ≈ 0.5s`, and tracks W' depletion throughout.

The constant-power value is **calibrated by binary search** to target ~97.5% W' depletion at the end of the segment — which means the rider spends their full anaerobic budget exactly. Without this calibration, the raw `CP + W'/t` formula tends to under-use W' on rolling terrain (steep sections slow the rider down, so time above CP doesn't accumulate as predicted), leaving the even-power baseline artificially slow.

### Model 3 — Optimized pacing (Simulator tab)

Grade-weighted power allocation: per-section power = `base + α · (grade_i − avg_grade)`, where `base` and `α` are found by a two-phase grid search that minimizes total simulated time subject to the W' depletion ceiling.

Result: more watts on the steep sections (where gravity dominates and extra power buys big speed gains), fewer watts on the flats (where aero drag eats them). Both even-power and optimized models target the same 97.5% W' ceiling, so the comparison is apples-to-apples — any time difference reflects real pacing value, not wasted W'.

---

## Elevation processing

Raw Strava polylines contain GPS trackpoints every ~5–30 meters but with no elevation data. The `Fill_and_Clean_Elevation.py` pipeline cleans and densifies this into a physics-ready profile:

1. **Decode polyline** → full-resolution lat/lon/distance array (average ~56 points per segment)
2. **Fetch elevation** for every point from the Open-Meteo elevation API (batched 50 at a time)
3. **Fix outlier spikes** — single-point elevation jumps that are physically impossible
4. **Gaussian smooth** on full-resolution elevation using `scipy.ndimage.gaussian_filter1d(sigma=4, mode='nearest')`
5. **Resample** to ~1.2 points per 100 m (capped 10–120 points per segment)
6. **Compute grades** from smoothed consecutive-point elevation differences, clamped to ±35%
7. **Write** to `clean_seg_points` + QA stats to `clean_seg_qa`

### Why Gaussian smoothing matters

GPS elevation data is noisy — consecutive points often show 2–5 m of vertical jitter on a surface that's actually smooth. Without smoothing, dividing these jitter values by short horizontal distances produces phantom 40%+ grade spikes that would confuse physics simulation.

**Measured effect across all 3,448 segments:**

| Metric | Raw | Cleaned | Change |
|---|---:|---:|---:|
| Avg points per segment | 56.3 | 19.6 | 2.9× fewer |
| Avg max grade on segment | 54.7% | 10.9% | 5.0× flatter peaks |

The 54.7% raw max grade average is almost entirely GPS/elevation noise — real road grades above ~20% are extremely rare. After Gaussian smoothing, max cleaned grades average 10.9%, which is reasonable for the steep segments in the database.

The optimizer then re-groups consecutive cleaned points with similar grades into 5–15 macro-sections for pacing optimization.

---

## Supabase integration

### Authentication (`sb_auth.py`)

Two sign-in methods, both via Supabase:

- **Google OAuth** — PKCE flow. The `code_verifier` is stored in `st.session_state` (fast path) and `/tmp` (survives Streamlit reruns within a container). Streamlit can't read URL fragments, so a small JS snippet rewrites `#access_token=...` to `?access_token=...` so the app can consume it. Redirect URL is computed dynamically from the current page.
- **Email + password** — standard Supabase `grant_type=password` and `/signup` flows via REST.

All authenticated REST calls are made with the user's access token in the `Authorization: Bearer <token>` header so Row Level Security (RLS) policies on Supabase tables apply correctly.

Signed-in users get:
- Saved power curve, weight, and preferred region (`user_profiles`)
- Per-user favorites (`favorites`)
- Per-user exclusions
- Favorites tab
- Attribution on requests and feedback

The app works fully without sign-in — auth is additive, not gating.

### Request handling
Three queues backed by Supabase tables:

- **`segment_requests`** — users submit Strava segment IDs + optional notes. The admin pipeline (`Segment_Pull.py` + `Fill_and_Clean_Elevation.py`) periodically pulls the queue, fetches each segment from Strava, runs it through the elevation cleaner, and marks the request complete.
- **`location_requests`** — **every** city/region search is logged (successful, unsupported, or failed to geocode). This surfaces which regions users want that don't have segment coverage yet, so new regions can be prioritized based on actual demand.
- **`flagged_segments`** — segments with bad GPS or data issues. Hidden from all tabs until unflagged.

### Analytics & user tracking
All events are session-scoped via a UUID stored in `st.session_state`. Tables:

| Table | What it captures | Rate of writes |
|---|---|---|
| `app_sessions` | One row per browser session with `started_at`, `last_seen_at`, device type, signed-in state, selected region | Upserted on every rerun |
| `tab_views` | First time a user views each tab per session | Once per (session, tab) |
| `tab_interactions` | Rerun count per tab (engagement depth) | Batched every 5 reruns |
| `optimization_runs` | Each optimizer call: segment, context (simulator / forecast), timestamp | Once per optimize trigger |
| `favorite_events` | Add/remove actions on favorites | On every toggle |

Session duration is derived from `last_seen_at − started_at`. Engagement per tab is `tab_interactions.interaction_count`. Popular segments are the top-grouped `optimization_runs.segment_id`.

All writes are fire-and-forget (`try/except: pass`) with a 2-second timeout so analytics failures never break the app.

---

## Setup

### Prerequisites
- Python 3.10+
- A Supabase project (free tier is fine)
- An OpenWeatherMap API key (free tier: 1,000 calls/day — sufficient thanks to 3-hour forecast caching)

### Install

```bash
git clone https://github.com/wyattlowdermilk/Segment_Predict.git
cd Segment_Predict
pip install -r requirements.txt
```

### Configure

Create `.streamlit/secrets.toml`:

```toml
[supabase]
url = "https://your-project.supabase.co"
key = "your-anon-key"
```

Create `config.py` with your OpenWeatherMap key and athlete defaults:

```python
WEATHER_API_KEY = "your-owm-key"

# Default athlete power curve (editable in-app)
POWER_1_MIN  = 400
POWER_3_MIN  = 340
POWER_8_MIN  = 300
POWER_20_MIN = 250
RIDER_WEIGHT_KG = 75
BIKE_WEIGHT_KG  = 8
CDA_M2 = 0.32
CRR    = 0.004
```

### Supabase schema

Run `supabase_analytics_schema.sql` in the Supabase SQL Editor to create the analytics tables (`app_sessions`, `tab_views`, `tab_interactions`, `optimization_runs`, `favorite_events`) plus the `location_requests` column additions.

For Google OAuth: enable the Google provider in Supabase Auth settings and add your app's URL to the allowed redirect URLs.

### Run

```bash
streamlit run app.py
```

### Populate segments (admin only)

```bash
# First: pull new segments from Strava
python Segment_Pull.py

# Then: clean and densify their elevation profiles
python Fill_and_Clean_Elevation.py
```

Edit `SELECTED_REGION` and filter thresholds at the top of `Segment_Pull.py` first. This pulls candidate segments from Strava's `/segments/explore` endpoint, filters by grade/distance/effort count, and inserts survivors into `segments.db`.

---

## Project structure

```
├── app.py                          # Streamlit app (main entry point)
├── Segment_Optimizer.py            # CP/W' physics + optimizer (runtime)
├── segment_time_estimator.py       # Power curve + basic physics helpers
├── sb_auth.py                      # Supabase auth: OAuth + email/password
├── Segment_Pull.py                 # Strava ingestion pipeline (admin)
├── Fill_and_Clean_Elevation.py     # Elevation cleaner with Gaussian smoothing
├── regions.py                      # Supported regions (shared with pipeline)
├── config.py                       # API keys, athlete defaults
├── db.py                           # SQLite connection + table setup
├── api_logger.py                   # Strava API call logging
├── segments.db                     # Bundled segment data (SQLite)
└── supabase_analytics_schema.sql   # Supabase table definitions
```

---

## Known limitations

- **Weather accuracy** is bounded by OpenWeatherMap's free-tier 3-hour resolution. Fine for planning; not sufficient for race-day decisions.
- **Wind modeling** uses a single segment bearing (start → end). Curvy segments get averaged — the model doesn't account for local wind direction changes along the route.
- **Physics model ignores** cornering losses, drafting, surface variations beyond wet/dry, and rider position changes.
- **Leaderboard comparison** depends on leaderboard data being reasonably fresh; stale KOMs will produce misleading "% of KOM" numbers.
- **Elevation cleaning cost**: Open-Meteo's elevation API is rate-limited. Backfilling elevation for thousands of new segments takes hours, not minutes.
- **Streamlit Cloud OAuth**: PKCE `code_verifier` uses `/tmp` for persistence, which doesn't survive container restarts on Streamlit Cloud. Users may see occasional "bad_code_verifier" errors after deploys; retry resolves it.

---

## License

Personal project; no formal license yet.