import requests
import json
import time
import os
import math

from db import get_connection, create_tables

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, "tokens.json")
SEGMENTS_FILE = os.path.join(BASE_DIR, "seattle_segments.json")
REJECTED_FILE = os.path.join(BASE_DIR, "rejected_ids.json")

CLIENT_ID = 219680
CLIENT_SECRET = "d7da2226ac32b89029989c9e0e8ba69dea00d4f7"

REGIONS = {
    # "Seattle, WA": {"lat": 47.6062, "lon": -122.3321}, #Main lat lon
    "Seattle, WA": {"lat": 47.656, "lon": -122.3866},  # mag segment
    "Orcas Island, WA": {"lat": 48.6561, "lon": -122.8263},
    # "Boulder, CO": {"lat": 40.0150, "lon": -105.2705}, #center of town
    "Boulder, CO": {
        "lat": 39.9967,
        "lon": -105.3308,
    },  # Gold Hill Centered, closer to climbs
    "Salt Lake City, UT": {"lat": 40.7608, "lon": -111.8910},
    "Cottonwood Heights, UT": {"lat": 40.6197, "lon": -111.8103},
    "Weddington, NC": {"lat": 34.9901, "lon": -80.7812},
    # "Portland, OR": {"lat": 45.5152, "lon": -122.6784}, #Center Portland
    "Portland, OR": {"lat": 45.599, "lon": -122.823},  # looking for Larch
    "Coraopolis, PA": {"lat": 40.4978, "lon": -80.1156},
    "Pittsburgh, PA": {"lat": 40.416, "lon": -79.96},
}

# ---- Configure these two values ----
SELECTED_REGION = "Boulder, CO"
BOX_RADIUS_MILES = 3

# -------------------------------------

center = REGIONS[SELECTED_REGION]
miles_per_lat_deg = 69.0
miles_per_lon_deg = 69.0 * math.cos(math.radians(center["lat"]))

lat_offset = BOX_RADIUS_MILES / miles_per_lat_deg
lon_offset = BOX_RADIUS_MILES / miles_per_lon_deg

LAT_MIN = center["lat"] - lat_offset
LAT_MAX = center["lat"] + lat_offset
LON_MIN = center["lon"] - lon_offset
LON_MAX = center["lon"] + lon_offset

print(f"Region: {SELECTED_REGION}")
print(f"Box: {LAT_MIN:.3f}–{LAT_MAX:.3f}, {LON_MIN:.3f}–{LON_MAX:.3f}")
print(f"Size: ~{BOX_RADIUS_MILES*2} x {BOX_RADIUS_MILES*2} miles")

# Each tile returns up to 10 segments from the explore endpoint.
# 4x4 = 16 tiles -> up to ~160 unique segments
# 5x5 = 25 tiles -> up to ~250 unique segments
GRID_ROWS = 3
GRID_COLS = 3

# =======================
# Segment quality filters
# =======================
MIN_AVG_GRADE = 4  # % — minimum average gradient
MAX_AVG_GRADE = 25  # % — cap to exclude bad data / stair anomalies
MIN_ELEV_GAIN = 30  # meters — minimum total elevation gain
MIN_DISTANCE = 400  # meters — minimum segment length
MAX_DISTANCE = 20000  # meters — maximum segment length (~12 miles)
MIN_EFFORT_COUNT = 700  # minimum recorded efforts


# =======================
# Token refresh
# =======================
def get_access_token():
    with open(TOKEN_FILE) as f:
        tokens = json.load(f)

    if tokens["expires_at"] < time.time():
        print("Access token expired, refreshing...")
        resp = requests.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
            },
        )
        new_tokens = resp.json()
        tokens["access_token"] = new_tokens["access_token"]
        tokens["refresh_token"] = new_tokens["refresh_token"]
        tokens["expires_at"] = new_tokens["expires_at"]
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
        print("Token refreshed.")
    else:
        print("Access token valid.")

    return tokens["access_token"]


# =======================
# Grid tile generator
# =======================
def make_grid(lat_min, lat_max, lon_min, lon_max, rows, cols):
    """Split bounding box into rows x cols sub-boxes."""
    lat_step = (lat_max - lat_min) / rows
    lon_step = (lon_max - lon_min) / cols
    tiles = []
    for r in range(rows):
        for c in range(cols):
            tiles.append(
                (
                    lat_min + r * lat_step,
                    lat_min + (r + 1) * lat_step,
                    lon_min + c * lon_step,
                    lon_min + (c + 1) * lon_step,
                )
            )
    return tiles


# =======================
# Early filter (explore data only — no API call needed)
# =======================
def passes_early_filter(seg):
    """
    Filter using fields available from the explore endpoint:
      avg_grade, distance, elev_difference
    Returns (True, 'ok') or (False, reason).
    """
    grade = seg.get("avg_grade", 0) or 0
    dist = seg.get("distance", 0) or 0

    if grade < MIN_AVG_GRADE:
        return False, f"avg grade too low ({grade:.1f}% < {MIN_AVG_GRADE}%)"
    if grade > MAX_AVG_GRADE:
        return False, f"avg grade too high ({grade:.1f}% > {MAX_AVG_GRADE}%)"
    if dist < MIN_DISTANCE:
        return False, f"too short ({dist:.0f}m < {MIN_DISTANCE}m)"
    if dist > MAX_DISTANCE:
        return False, f"too long ({dist:.0f}m > {MAX_DISTANCE}m)"

    return True, "ok"


# =======================
# Full filter (detail endpoint data)
# =======================
def passes_full_filter(seg_data):
    """
    Check fields that are ONLY available from the detail endpoint:
      effort_count, total_elevation_gain
    The early filter already checked grade and distance, so we skip those here.
    """
    gain = seg_data.get("total_elevation_gain") or 0
    efforts = seg_data.get("effort_count") or 0

    if gain < MIN_ELEV_GAIN:
        return False, f"elevation gain too low ({gain:.0f}m < {MIN_ELEV_GAIN}m)"
    if efforts < MIN_EFFORT_COUNT:
        return False, f"too few efforts ({efforts} < {MIN_EFFORT_COUNT})"

    return True, "ok"


# =======================
# Persistent rejected-IDs cache
# =======================
def load_rejected_ids():
    """Load IDs that previously failed the detail-phase filter."""
    if os.path.exists(REJECTED_FILE):
        with open(REJECTED_FILE) as f:
            return set(json.load(f))
    return set()


def save_rejected_ids(rejected):
    with open(REJECTED_FILE, "w") as f:
        json.dump(list(rejected), f)


# =======================
# API call with rate-limit handling
# =======================
def api_get(url, headers, params=None, max_retries=2):
    """GET with automatic rate-limit backoff."""
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            print(f"  rate limit — waiting {wait}s (attempt {attempt+1})")
            time.sleep(wait)
            continue
        return resp
    return resp  # return last response even if still 429


# =======================
# Setup
# =======================
ACCESS_TOKEN = get_access_token()
create_tables()
conn = get_connection()
cur = conn.cursor()

# Ensure change tracking tables/columns exist
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS pipeline_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
        action TEXT NOT NULL,
        segment_id INTEGER,
        detail TEXT,
        source TEXT
    )
"""
)
try:
    cur.execute("ALTER TABLE segments ADD COLUMN pulled_at TEXT")
except Exception:
    pass  # column already exists
conn.commit()

headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

# Load IDs already in DB — these will be skipped entirely
cur.execute("SELECT id FROM segments")
existing_ids = set(row[0] for row in cur.fetchall())
print(f"Already in DB: {len(existing_ids)} segments")

# Load IDs that were previously rejected by the detail-phase filter
rejected_ids = load_rejected_ids()
print(f"Previously rejected: {len(rejected_ids)} segments")

# =======================
# Step 1: Discover + early-filter in one pass
# =======================
tiles = make_grid(LAT_MIN, LAT_MAX, LON_MIN, LON_MAX, GRID_ROWS, GRID_COLS)
print(f"Grid: {GRID_ROWS}x{GRID_COLS} = {len(tiles)} tiles\n")

discovered_ids = set()
early_filtered = 0
skipped_known = 0

for i, (lat_min, lat_max, lon_min, lon_max) in enumerate(tiles):
    resp = api_get(
        "https://www.strava.com/api/v3/segments/explore",
        headers=headers,
        params={
            "bounds": f"{lat_min},{lon_min},{lat_max},{lon_max}",
            "activity_type": "ride",
            "per_page": 10,
        },
    )

    if resp.status_code != 200:
        print(f"  Tile {i+1:>2}/{len(tiles)}: HTTP {resp.status_code} — skipping tile")
        time.sleep(3)
        continue

    segs = resp.json().get("segments", [])

    new_in_tile = 0
    filtered_in_tile = 0
    known_in_tile = 0

    for s in segs:
        sid = s["id"]

        # Skip segments we already know about (in DB or previously rejected)
        if sid in existing_ids or sid in discovered_ids or sid in rejected_ids:
            known_in_tile += 1
            continue

        # Apply early filter using explore-endpoint data (FREE — no API call)
        qualifies, reason = passes_early_filter(s)
        if not qualifies:
            filtered_in_tile += 1
            rejected_ids.add(sid)  # remember so we don't re-check next run
            continue

        discovered_ids.add(sid)
        new_in_tile += 1

    early_filtered += filtered_in_tile
    skipped_known += known_in_tile

    print(
        f"  Tile {i+1:>2}/{len(tiles)}: "
        f"{len(segs):>2} found, "
        f"{new_in_tile:>2} new, "
        f"{filtered_in_tile:>2} early-filtered, "
        f"{known_in_tile:>2} already known"
    )
    time.sleep(3)

new_ids = list(discovered_ids)
print(f"\nDiscovery summary:")
print(f"  Candidates for detail fetch : {len(new_ids)}")
print(f"  Early-filtered (no API cost): {early_filtered}")
print(f"  Skipped (DB/rejected cache) : {skipped_known}")
print(f"  API calls saved             : {early_filtered + skipped_known}\n")

if not new_ids:
    save_rejected_ids(rejected_ids)
    print("Nothing new to add — try a larger grid or expanding the bounding box.")
    conn.close()
    exit()

# =======================
# Step 2: Fetch detail for survivors only + apply remaining filters + insert
# =======================
added = 0
skipped_filter = 0
errors = 0
segment_db = []

for idx, seg_id in enumerate(new_ids):
    print(f"  [{idx+1:>3}/{len(new_ids)}] Segment {seg_id}", end=" ... ")

    seg_resp = api_get(
        f"https://www.strava.com/api/v3/segments/{seg_id}",
        headers=headers,
    )

    if seg_resp.status_code != 200:
        print(f"HTTP {seg_resp.status_code} — skipping")
        errors += 1
        time.sleep(1)
        continue

    seg_data = seg_resp.json()

    # Apply remaining filters (effort_count, elevation_gain)
    qualifies, reason = passes_full_filter(seg_data)
    if not qualifies:
        print(f"filtered — {reason}")
        skipped_filter += 1
        rejected_ids.add(seg_id)  # cache so we skip next run
        time.sleep(1)
        continue

    # Passed — insert into DB
    start_latlng = seg_data.get("start_latlng") or [None, None]
    end_latlng = seg_data.get("end_latlng") or [None, None]
    map_polyline = (seg_data.get("map") or {}).get("polyline")

    cur.execute(
        """
        INSERT OR REPLACE INTO segments (
            id, name, activity_type, distance_m, elevation_gain_m,
            elevation_high_m, elevation_low_m, avg_grade, max_grade,
            climb_category, start_lat, start_lng, end_lat, end_lng,
            city, state, country, private, hazardous, starred,
            effort_count, athlete_count, star_count,
            created_at, updated_at, map_polyline, pulled_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            seg_id,
            seg_data.get("name"),
            seg_data.get("activity_type"),
            seg_data.get("distance"),
            seg_data.get("total_elevation_gain"),
            seg_data.get("elevation_high"),
            seg_data.get("elevation_low"),
            seg_data.get("average_grade"),
            seg_data.get("maximum_grade"),
            seg_data.get("climb_category"),
            start_latlng[0],
            start_latlng[1],
            end_latlng[0],
            end_latlng[1],
            seg_data.get("city"),
            seg_data.get("state"),
            seg_data.get("country"),
            int(seg_data.get("private", False)),
            int(seg_data.get("hazardous", False)),
            int(seg_data.get("starred", False)),
            seg_data.get("effort_count"),
            seg_data.get("athlete_count"),
            seg_data.get("star_count"),
            seg_data.get("created_at"),
            seg_data.get("updated_at"),
            map_polyline,
        ),
    )
    cur.execute(
        "INSERT INTO pipeline_log (action, segment_id, detail, source) VALUES (?, ?, ?, ?)",
        ("segment_pulled", seg_id, seg_data.get("name"), "Segment_Pull"),
    )
    conn.commit()

    segment_db.append(
        {
            "id": seg_id,
            "name": seg_data.get("name"),
            "distance_m": seg_data.get("distance"),
            "elevation_gain_m": seg_data.get("total_elevation_gain"),
            "avg_grade": seg_data.get("average_grade"),
            "effort_count": seg_data.get("effort_count"),
            "city": seg_data.get("city"),
            "state": seg_data.get("state"),
        }
    )

    print(
        f"added  '{seg_data.get('name')}'  "
        f"{seg_data.get('average_grade')}%  "
        f"{seg_data.get('total_elevation_gain'):.0f}m gain  "
        f"{seg_data.get('effort_count')} efforts"
    )
    added += 1
    time.sleep(1)

conn.close()

# =======================
# Persist rejected IDs for future runs
# =======================
save_rejected_ids(rejected_ids)

# =======================
# Update JSON file
# =======================
all_records = []
if os.path.exists(SEGMENTS_FILE):
    with open(SEGMENTS_FILE) as f:
        all_records = json.load(f)

existing_json_ids = {r["id"] for r in all_records}
all_records.extend(r for r in segment_db if r["id"] not in existing_json_ids)

with open(SEGMENTS_FILE, "w") as f:
    json.dump(all_records, f, indent=2)

# =======================
# Summary
# =======================
print(
    f"""
{'='*50}
  Run complete
{'='*50}
  Already in DB (skipped)      : {len(existing_ids)}
  Previously rejected (cached) : {len(rejected_ids) - early_filtered - skipped_filter}
  Early-filtered (no API cost) : {early_filtered}
  Detail calls made            : {len(new_ids)}
  Filtered at detail phase     : {skipped_filter}
  Errors                       : {errors}
  Added to DB                  : {added}
  Total in JSON                : {len(all_records)}
{'='*50}
  Next: run scraperSel.py to pull leaderboard data
  for the {added} newly added segments.
"""
)
