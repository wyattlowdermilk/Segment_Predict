"""
Cycling Segment Pipeline Manager
================================
Unified tool to manage the full segment data pipeline:

  1. Pull segments (by area exploration OR by specific IDs)
  2. Fill elevation + clean profiles (decodes polyline inline, no segment_points)

Usage:
  python pipeline.py pull --region "Seattle, WA"           # Explore area
  python pipeline.py pull --ids 619307 624537 785087       # Fetch specific IDs
  python pipeline.py pull --ids-file my_segments.txt       # IDs from file
  python pipeline.py process                               # Process anything new
  python pipeline.py process --segment 619307 624537       # Process specific IDs
  python pipeline.py status                                # Show what needs processing
  python pipeline.py full --region "Seattle, WA"           # Pull + process in one shot
  python pipeline.py full --ids 619307 624537              # Pull IDs + process
  python pipeline.py cleanup                               # Drop segment_points + VACUUM

The 'process' command is idempotent — it only touches segments that need work.
"""

import sqlite3
import requests
import json
import time
import os
import sys
import math
import argparse

try:
    import polyline as polyline_lib

    HAS_POLYLINE = True
except ImportError:
    HAS_POLYLINE = False
    print("Warning: 'polyline' package not installed. Run: pip install polyline")

# Import the combined fill+clean module
try:
    from Fill_and_Clean_Elevation import (
        find_segments as fc_find_segments,
        process_single_segment as fc_process_single_segment,
        write_clean_data as fc_write_clean_data,
        cleanup_raw_points as fc_cleanup_raw_points,
        ELEV_BATCH_SIZE,
        ELEV_SLEEP,
    )

    HAS_FILL_CLEAN = True
except ImportError:
    HAS_FILL_CLEAN = False
    print(
        "Warning: Fill_and_Clean_Elevation.py not found. 'process' commands won't work."
    )

# ============================================================
# Configuration
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "segments.db")
TOKEN_FILE = os.path.join(BASE_DIR, "tokens.json")
REJECTED_FILE = os.path.join(BASE_DIR, "rejected_ids.json")

CLIENT_ID = 219680
CLIENT_SECRET = "d7da2226ac32b89029989c9e0e8ba69dea00d4f7"

REGIONS = {
    "Seattle, WA": {"lat": 47.6062, "lon": -122.3321},
    "Orcas Island, WA": {"lat": 48.6561, "lon": -122.8263},
    "Boulder, CO": {"lat": 40.0150, "lon": -105.2705},
    "Salt Lake City, UT": {"lat": 40.7608, "lon": -111.8910},
    "Cottonwood Heights, UT": {"lat": 40.6197, "lon": -111.8103},
    "Weddington, NC": {"lat": 34.9901, "lon": -80.7812},
}

# Explore filters (only apply to area exploration, not ID pulls)
MIN_AVG_GRADE = 3
MAX_AVG_GRADE = 25
MIN_DISTANCE = 100
MAX_DISTANCE = 20000
MIN_EFFORT_COUNT = 20
MIN_ELEV_GAIN = 0

# Grid for area exploration
GRID_ROWS = 5
GRID_COLS = 5
BOX_RADIUS_MILES = 2


# ============================================================
# Strava API helpers
# ============================================================
def get_access_token():
    """Get valid access token, refreshing if expired."""
    if not os.path.exists(TOKEN_FILE):
        print(f"ERROR: {TOKEN_FILE} not found. Set up Strava OAuth first.")
        sys.exit(1)

    with open(TOKEN_FILE) as f:
        tokens = json.load(f)

    if tokens["expires_at"] < time.time():
        print("  Refreshing expired access token...")
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

    return tokens["access_token"]


def api_get(url, headers, params=None, max_retries=3):
    """GET with rate-limit backoff."""
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            print(f"    Rate limit — waiting {wait}s (attempt {attempt+1})")
            time.sleep(wait)
            continue
        return resp
    return resp


# ============================================================
# Step 1a: Pull segments by area exploration
# ============================================================
def pull_by_region(region_name, headers, conn, box_radius=BOX_RADIUS_MILES):
    """Explore a region grid and fetch segment details for new finds."""
    if region_name not in REGIONS:
        print(f"Unknown region '{region_name}'. Available: {list(REGIONS.keys())}")
        return []

    center = REGIONS[region_name]
    miles_per_lat = 69.0
    miles_per_lon = 69.0 * math.cos(math.radians(center["lat"]))
    lat_off = box_radius / miles_per_lat
    lon_off = box_radius / miles_per_lon

    lat_min = center["lat"] - lat_off
    lat_max = center["lat"] + lat_off
    lon_min = center["lon"] - lon_off
    lon_max = center["lon"] + lon_off

    print(f"  Region: {region_name}")
    print(
        f"  Box: {2*box_radius:.0f}×{2*box_radius:.0f} miles, "
        f"{GRID_ROWS}×{GRID_COLS} grid"
    )

    cur = conn.cursor()
    cur.execute("SELECT id FROM segments")
    existing = set(r[0] for r in cur.fetchall())

    rejected = _load_rejected()
    tiles = _make_grid(lat_min, lat_max, lon_min, lon_max, GRID_ROWS, GRID_COLS)

    # Phase 1: Discover candidates
    candidates = set()
    for i, (la, lb, lo, lp) in enumerate(tiles):
        resp = api_get(
            "https://www.strava.com/api/v3/segments/explore",
            headers,
            params={
                "bounds": f"{la},{lo},{lb},{lp}",
                "activity_type": "ride",
                "per_page": 10,
            },
        )
        if resp.status_code != 200:
            continue

        for s in resp.json().get("segments", []):
            sid = s["id"]
            if sid in existing or sid in candidates or sid in rejected:
                continue
            grade = s.get("avg_grade", 0) or 0
            dist = s.get("distance", 0) or 0
            if grade < MIN_AVG_GRADE or grade > MAX_AVG_GRADE:
                rejected.add(sid)
                continue
            if dist < MIN_DISTANCE or dist > MAX_DISTANCE:
                rejected.add(sid)
                continue
            candidates.add(sid)

        time.sleep(2)

    print(f"  Found {len(candidates)} new candidates")

    # Phase 2: Fetch details
    added = _fetch_and_insert_segments(
        list(candidates), headers, conn, rejected, apply_filters=True
    )
    _save_rejected(rejected)
    return added


# ============================================================
# Step 1b: Pull segments by specific IDs
# ============================================================
def pull_by_ids(segment_ids, headers, conn):
    """Fetch specific segment IDs from the Strava API."""
    cur = conn.cursor()
    cur.execute("SELECT id FROM segments")
    existing = set(r[0] for r in cur.fetchall())

    new_ids = [sid for sid in segment_ids if sid not in existing]
    already = len(segment_ids) - len(new_ids)

    if already:
        print(f"  {already} already in DB, skipping")
    if not new_ids:
        print("  Nothing new to fetch")
        return []

    print(f"  Fetching {len(new_ids)} segment(s) from Strava API...")
    added = _fetch_and_insert_segments(
        new_ids, headers, conn, rejected_ids=set(), apply_filters=False
    )
    return added


def _fetch_and_insert_segments(
    seg_ids, headers, conn, rejected_ids, apply_filters=True
):
    """Fetch segment details and insert into DB. Returns list of added IDs."""
    cur = conn.cursor()
    added = []

    for idx, seg_id in enumerate(seg_ids):
        print(f"    [{idx+1}/{len(seg_ids)}] Segment {seg_id}", end=" ... ")

        resp = api_get(
            f"https://www.strava.com/api/v3/segments/{seg_id}",
            headers,
        )
        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}")
            time.sleep(1)
            continue

        d = resp.json()

        # Apply filters only for explore mode
        if apply_filters:
            gain = d.get("total_elevation_gain") or 0
            efforts = d.get("effort_count") or 0
            if gain < MIN_ELEV_GAIN:
                print(f"filtered (gain {gain:.0f}m)")
                rejected_ids.add(seg_id)
                time.sleep(1)
                continue
            if efforts < MIN_EFFORT_COUNT:
                print(f"filtered ({efforts} efforts)")
                rejected_ids.add(seg_id)
                time.sleep(1)
                continue

        start = d.get("start_latlng") or [None, None]
        end = d.get("end_latlng") or [None, None]
        poly = (d.get("map") or {}).get("polyline")

        cur.execute(
            """
            INSERT OR REPLACE INTO segments (
                id, name, activity_type, distance_m, elevation_gain_m,
                elevation_high_m, elevation_low_m, avg_grade, max_grade,
                climb_category, start_lat, start_lng, end_lat, end_lng,
                city, state, country, private, hazardous, starred,
                effort_count, athlete_count, star_count,
                created_at, updated_at, map_polyline, pulled_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        """,
            (
                seg_id,
                d.get("name"),
                d.get("activity_type"),
                d.get("distance"),
                d.get("total_elevation_gain"),
                d.get("elevation_high"),
                d.get("elevation_low"),
                d.get("average_grade"),
                d.get("maximum_grade"),
                d.get("climb_category"),
                start[0],
                start[1],
                end[0],
                end[1],
                d.get("city"),
                d.get("state"),
                d.get("country"),
                int(d.get("private", False)),
                int(d.get("hazardous", False)),
                int(d.get("starred", False)),
                d.get("effort_count"),
                d.get("athlete_count"),
                d.get("star_count"),
                d.get("created_at"),
                d.get("updated_at"),
                poly,
            ),
        )
        conn.commit()
        log_action(conn, "segment_pulled", seg_id, d.get("name"), "pipeline")

        print(
            f"added '{d.get('name')}'  {d.get('average_grade')}%  "
            f"{d.get('total_elevation_gain', 0):.0f}m"
        )
        added.append(seg_id)
        time.sleep(1)

    return added


# ============================================================
# Step 2: Fill elevation + clean (replaces old steps 2, 3, 4)
# ============================================================
def process_elevation_and_clean(conn, segment_ids=None, verbose=False):
    """
    Full-resolution elevation pipeline: processes one segment at a time.
    For each segment: decode polyline → fetch elevation for ALL points →
    smooth → resample → write. The inter-batch sleep acts as natural
    rate limiting for the elevation API.
    """
    if not HAS_FILL_CLEAN:
        print("  ERROR: Fill_and_Clean_Elevation.py not found")
        return 0

    cur = conn.cursor()

    # Ensure output tables exist
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clean_seg_points (
            segment_id INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            distance_km REAL NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            elevation_m REAL NOT NULL,
            grade_pct REAL,
            PRIMARY KEY (segment_id, seq)
        )
    """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clean_seg_qa (
            segment_id INTEGER PRIMARY KEY,
            original_points INTEGER,
            clean_points INTEGER,
            had_duplicate_elevations INTEGER,
            outliers_replaced INTEGER,
            max_raw_grade_pct REAL,
            max_clean_grade_pct REAL,
            elevation_gain_clean_m REAL,
            elevation_gain_strava_m REAL
        )
    """
    )
    conn.commit()

    # Find segments to process
    if segment_ids:
        segments = []
        for sid in segment_ids:
            found = fc_find_segments(conn, "single", sid)
            segments.extend(found)
    else:
        segments = fc_find_segments(conn, "new")

    if not segments:
        print("  All segments already have clean elevation data")
        return 0

    print(
        f"  Processing {len(segments)} segment(s) (full-resolution, one at a time)..."
    )
    print()

    success = 0
    failed = 0
    t_start = time.time()

    for idx, (seg_id, strava_gain) in enumerate(segments, 1):
        # Get segment name for display
        cur.execute("SELECT name FROM segments WHERE id = ?", (seg_id,))
        name_row = cur.fetchone()
        seg_name = (name_row[0] or str(seg_id))[:45] if name_row else str(seg_id)

        print(f"  [{idx}/{len(segments)}] Segment {seg_id} — {seg_name}")

        result = fc_process_single_segment(cur, conn, seg_id, strava_gain, verbose=True)

        if result["success"]:
            # Update elevation_at timestamp in QA table
            try:
                cur.execute(
                    "UPDATE clean_seg_qa SET elevation_at = datetime('now') WHERE segment_id = ?",
                    (seg_id,),
                )
            except Exception:
                pass  # column may not exist yet
            log_action(
                conn,
                "elevation_processed",
                seg_id,
                result.get("message", ""),
                "pipeline",
            )
            success += 1
            print(f"    ✓ {result['message']}")
        else:
            log_action(
                conn, "elevation_failed", seg_id, result.get("message", ""), "pipeline"
            )
            failed += 1
            print(f"    ✗ {result['message']}")

        elapsed = time.time() - t_start
        avg_per = elapsed / idx
        remaining = avg_per * (len(segments) - idx)
        print(f"    [{elapsed/60:.1f}m elapsed, ~{remaining/60:.1f}m remaining]")
        print()

    conn.commit()
    print(f"  Cleaned {success} segment(s)" + (f", {failed} failed" if failed else ""))
    return success


# ============================================================
# Status report
# ============================================================
def show_status(conn):
    """Show what needs processing."""
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM segments")
    total_seg = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM segments WHERE map_polyline IS NOT NULL")
    has_polyline = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COUNT(*) FROM segments s
        LEFT JOIN clean_seg_points csp ON s.id = csp.segment_id
        WHERE s.map_polyline IS NOT NULL AND csp.segment_id IS NULL
    """
    )
    need_process = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT segment_id) FROM clean_seg_points")
    has_clean = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT segment_id) FROM leaderboard")
    has_lb = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COUNT(DISTINCT s.id) FROM segments s
        LEFT JOIN leaderboard l ON s.id = l.segment_id
        WHERE l.segment_id IS NULL
    """
    )
    need_lb = cur.fetchone()[0]

    # Check if legacy segment_points table exists
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='segment_points'"
    )
    has_raw_table = cur.fetchone() is not None
    raw_pts = 0
    if has_raw_table:
        cur.execute("SELECT COUNT(*) FROM segment_points")
        raw_pts = cur.fetchone()[0]

    print(
        f"""
Pipeline Status
{'='*45}
  Total segments:           {total_seg:>6}
  With polyline:            {has_polyline:>6}
  With clean elevation:     {has_clean:>6}
  With leaderboard:         {has_lb:>6}
{'─'*45}
  Need elevation + clean:   {need_process:>6}
  Need leaderboard scrape:  {need_lb:>6}
{'='*45}"""
    )

    if has_raw_table and raw_pts > 0:
        est_mb = raw_pts * 50 / 1024 / 1024
        print(f"\n  ⚠ Legacy segment_points table has {raw_pts:,} rows.")
        print(
            f"    Run 'python pipeline.py cleanup' to drop it and reclaim ~{est_mb:.0f} MB."
        )

    if need_process > 0:
        print(
            f"\n  Run 'python pipeline.py process' to handle {need_process} pending segment(s)."
        )
    if need_lb > 0:
        print(f"  Run 'python scraperSel.py' to scrape {need_lb} leaderboard(s).")
    if need_process + need_lb == 0 and not (has_raw_table and raw_pts > 0):
        print("\n  ✓ Everything is up to date!")


def _show_log(conn, args):
    """Display pipeline change history."""
    cur = conn.cursor()

    # Check if table exists
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pipeline_log'"
    )
    if not cur.fetchone():
        print("No pipeline_log table yet. Run any pipeline command to create it.")
        return

    query = "SELECT timestamp, action, segment_id, detail, source FROM pipeline_log"
    conditions = []
    params = []

    if hasattr(args, "segment") and args.segment:
        conditions.append("segment_id = ?")
        params.append(args.segment)
    if hasattr(args, "action") and args.action:
        conditions.append("action LIKE ?")
        params.append(f"%{args.action}%")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(args.n)

    rows = cur.execute(query, params).fetchall()

    if not rows:
        print("No log entries found.")
        return

    print(f"\n{'Timestamp':<20} {'Action':<22} {'Seg ID':>8}  {'Source':<10} Detail")
    print("─" * 95)
    for ts, action, seg_id, detail, source in reversed(rows):
        sid = str(seg_id) if seg_id else "—"
        src = source or "—"
        det = (detail[:45] + "…") if detail and len(detail) > 46 else (detail or "")
        print(f"{ts:<20} {action:<22} {sid:>8}  {src:<10} {det}")

    print(f"\n  ({len(rows)} entries shown, use -n to show more)")


# ============================================================
# Helpers
# ============================================================
def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _make_grid(lat_min, lat_max, lon_min, lon_max, rows, cols):
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


def _load_rejected():
    if os.path.exists(REJECTED_FILE):
        with open(REJECTED_FILE) as f:
            return set(json.load(f))
    return set()


def _save_rejected(rejected):
    with open(REJECTED_FILE, "w") as f:
        json.dump(list(rejected), f)


def _read_ids_file(filepath):
    """Read segment IDs from a file (one per line, ignores comments/blanks)."""
    ids = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    ids.append(int(line.split()[0]))
                except ValueError:
                    continue
    return ids


# ============================================================
# Ensure tables
# ============================================================
def _ensure_tables(conn):
    """Ensure all required tables exist, and add tracking columns/tables."""
    cur = conn.cursor()

    # We no longer create segment_points — it's not needed
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clean_seg_points (
            segment_id INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            distance_km REAL NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            elevation_m REAL NOT NULL,
            grade_pct REAL,
            PRIMARY KEY (segment_id, seq)
        )
    """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clean_seg_qa (
            segment_id INTEGER PRIMARY KEY,
            original_points INTEGER,
            clean_points INTEGER,
            had_duplicate_elevations INTEGER,
            outliers_replaced INTEGER,
            max_raw_grade_pct REAL,
            max_clean_grade_pct REAL,
            elevation_gain_clean_m REAL,
            elevation_gain_strava_m REAL
        )
    """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS segment_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            segment_id INTEGER NOT NULL,
            requested_by TEXT,
            notes TEXT,
            status TEXT DEFAULT 'pending',
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP
        )
    """
    )

    # ── Change tracking ──

    # pipeline_log: append-only log of every pipeline action
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

    # Add pulled_at to segments (when the segment was first fetched from Strava)
    try:
        cur.execute("ALTER TABLE segments ADD COLUMN pulled_at TEXT")
    except Exception:
        pass  # column already exists

    # Add elevation_at to clean_seg_qa (when elevation was last processed)
    try:
        cur.execute("ALTER TABLE clean_seg_qa ADD COLUMN elevation_at TEXT")
    except Exception:
        pass

    # Add scraped_at to leaderboard tracking (per-segment, not per-row)
    # We track this via pipeline_log rather than altering the leaderboard table,
    # since leaderboard has a composite PK and adding a timestamp per-row is wasteful.

    conn.commit()


def log_action(conn, action, segment_id=None, detail=None, source=None):
    """Append a row to pipeline_log. Call after any data-changing operation."""
    conn.execute(
        "INSERT INTO pipeline_log (action, segment_id, detail, source) VALUES (?, ?, ?, ?)",
        (action, segment_id, detail, source),
    )
    conn.commit()


# ============================================================
# Process request queue
# ============================================================
def _process_request_queue(conn):
    """Process all pending segment requests from the web app."""
    cur = conn.cursor()

    cur.execute(
        """
        SELECT DISTINCT segment_id FROM segment_requests WHERE status = 'pending'
    """
    )
    pending = [r[0] for r in cur.fetchall()]

    if not pending:
        print("No pending requests in queue.")
        return

    print(f"Processing {len(pending)} requested segment(s)...\n")

    # Step 1: Pull from Strava
    print("═══ Step 1: Pull segments from Strava ═══")
    headers = {"Authorization": f"Bearer {get_access_token()}"}
    added = pull_by_ids(pending, headers, conn)
    print(f"  → {len(added)} segment(s) added\n")

    # Step 2: Fill elevation + clean
    print("═══ Step 2: Fill elevation + clean profiles ═══")
    target_ids = added if added else pending
    process_elevation_and_clean(conn, target_ids)

    # Update request status
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for sid in pending:
        if sid in added:
            cur.execute(
                "UPDATE segment_requests SET status = 'completed', processed_at = ? "
                "WHERE segment_id = ? AND status = 'pending'",
                (now, sid),
            )
        else:
            # Check if it was already in the DB
            cur.execute("SELECT id FROM segments WHERE id = ?", (sid,))
            if cur.fetchone():
                cur.execute(
                    "UPDATE segment_requests SET status = 'already_exists', "
                    "processed_at = ? "
                    "WHERE segment_id = ? AND status = 'pending'",
                    (now, sid),
                )
            else:
                cur.execute(
                    "UPDATE segment_requests SET status = 'failed', processed_at = ? "
                    "WHERE segment_id = ? AND status = 'pending'",
                    (now, sid),
                )
    conn.commit()

    completed = sum(1 for sid in pending if sid in added)
    already = sum(
        1
        for sid in pending
        if sid not in added
        and conn.execute("SELECT id FROM segments WHERE id = ?", (sid,)).fetchone()
    )
    failed = len(pending) - completed - already

    print(f"\n═══ Request Queue Results ═══")
    print(f"  Completed:      {completed}")
    print(f"  Already in DB:  {already}")
    print(f"  Failed:         {failed}")
    print(f"\n  Don't forget to run scraperSel.py to fetch leaderboard data!")

    show_status(conn)


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Cycling Segment Pipeline Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py pull --region "Seattle, WA"
  python pipeline.py pull --ids 619307 624537 785087
  python pipeline.py process
  python pipeline.py full --ids 619307 624537
  python pipeline.py reprocess --all
  python pipeline.py reprocess --segment 713680 815373
  python pipeline.py reprocess --state PA
  python pipeline.py log
  python pipeline.py status
  python pipeline.py cleanup
        """,
    )
    sub = parser.add_subparsers(dest="command", help="Command to run")

    # pull
    p_pull = sub.add_parser("pull", help="Pull segments from Strava API")
    pull_group = p_pull.add_mutually_exclusive_group(required=True)
    pull_group.add_argument("--region", type=str, help="Region name to explore")
    pull_group.add_argument("--ids", type=int, nargs="+", help="Specific segment IDs")
    pull_group.add_argument(
        "--ids-file", type=str, help="File with segment IDs (one per line)"
    )
    p_pull.add_argument(
        "--radius",
        type=float,
        default=BOX_RADIUS_MILES,
        help="Search radius in miles (region mode only)",
    )

    # process
    p_proc = sub.add_parser(
        "process", help="Process pending segments (elevation + clean)"
    )
    p_proc.add_argument(
        "--segment", type=int, nargs="+", help="Process specific segment ID(s)"
    )

    # status
    sub.add_parser("status", help="Show pipeline status")

    # log — view change history
    p_log = sub.add_parser("log", help="View pipeline change history")
    p_log.add_argument(
        "--segment", type=int, help="Filter log to a specific segment ID"
    )
    p_log.add_argument(
        "--action",
        type=str,
        help="Filter by action type (e.g. segment_pulled, elevation_processed, leaderboard_scraped)",
    )
    p_log.add_argument(
        "-n",
        type=int,
        default=30,
        help="Number of recent entries to show (default: 30)",
    )

    # cleanup
    sub.add_parser("cleanup", help="Drop legacy segment_points table and VACUUM")

    # reprocess — re-fetch elevation and re-clean existing segments
    p_reproc = sub.add_parser(
        "reprocess",
        help="Re-fetch elevation + re-clean segments that already have data",
    )
    reproc_group = p_reproc.add_mutually_exclusive_group(required=True)
    reproc_group.add_argument(
        "--all", action="store_true", help="Re-process every segment"
    )
    reproc_group.add_argument(
        "--segment", type=int, nargs="+", help="Re-process specific segment ID(s)"
    )
    reproc_group.add_argument(
        "--state", type=str, help="Re-process all segments in a state (e.g. PA)"
    )

    # process-requests (from web app queue)
    sub.add_parser(
        "process-requests", help="Process pending segment requests from web app"
    )

    # full (pull + process)
    p_full = sub.add_parser("full", help="Pull + process in one shot")
    full_group = p_full.add_mutually_exclusive_group(required=True)
    full_group.add_argument("--region", type=str, help="Region name to explore")
    full_group.add_argument("--ids", type=int, nargs="+", help="Specific segment IDs")
    full_group.add_argument(
        "--ids-file", type=str, help="File with segment IDs (one per line)"
    )
    p_full.add_argument("--radius", type=float, default=BOX_RADIUS_MILES)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    conn = sqlite3.connect(DB_FILE)
    _ensure_tables(conn)

    if args.command == "status":
        show_status(conn)
        conn.close()
        return

    if args.command == "log":
        _show_log(conn, args)
        conn.close()
        return

    if args.command == "cleanup":
        if HAS_FILL_CLEAN:
            fc_cleanup_raw_points(conn)
        else:
            print("Fill_and_Clean_Elevation.py not found — doing manual cleanup")
            conn.execute("DROP TABLE IF EXISTS segment_points")
            conn.commit()
            conn.execute("VACUUM")
            print("Done.")
        conn.close()
        return

    if args.command == "process-requests":
        _process_request_queue(conn)
        conn.close()
        return

    if args.command == "reprocess":
        print("\n═══ Re-processing elevation + clean profiles ═══")
        cur = conn.cursor()
        if hasattr(args, "all") and args.all:
            cur.execute(
                "SELECT id FROM segments WHERE map_polyline IS NOT NULL ORDER BY id"
            )
            target_ids = [r[0] for r in cur.fetchall()]
            print(f"  Re-processing ALL {len(target_ids)} segments...")
        elif hasattr(args, "state") and args.state:
            # Match both abbreviation (PA) and full name (Pennsylvania)
            cur.execute(
                "SELECT id FROM segments WHERE (state = ? OR state = ? OR state LIKE ?) "
                "AND map_polyline IS NOT NULL ORDER BY id",
                (args.state, args.state.upper(), f"%{args.state}%"),
            )
            target_ids = [r[0] for r in cur.fetchall()]
            print(
                f"  Re-processing {len(target_ids)} segments in state '{args.state}'..."
            )
        else:
            target_ids = args.segment
            print(f"  Re-processing {len(target_ids)} specific segment(s)...")

        if target_ids:
            process_elevation_and_clean(conn, target_ids)
        else:
            print("  No matching segments found.")

        print("\n═══ Done ═══")
        show_status(conn)
        conn.close()
        return

    # Pull
    new_ids = []
    if args.command in ("pull", "full"):
        print("\n═══ Step 1: Pull segments from Strava ═══")
        headers = {"Authorization": f"Bearer {get_access_token()}"}

        if args.region:
            new_ids = pull_by_region(args.region, headers, conn, args.radius)
        elif args.ids:
            new_ids = pull_by_ids(args.ids, headers, conn)
        elif args.ids_file:
            ids = _read_ids_file(args.ids_file)
            new_ids = pull_by_ids(ids, headers, conn)

        print(f"  → {len(new_ids)} segment(s) added\n")

    # Process
    if args.command in ("process", "full"):
        target_ids = None
        if args.command == "process" and hasattr(args, "segment") and args.segment:
            target_ids = args.segment
        elif args.command == "full" and new_ids:
            target_ids = new_ids

        print("═══ Step 2: Fill elevation + clean profiles ═══")
        process_elevation_and_clean(conn, target_ids)

        print("\n═══ Done ═══")
        show_status(conn)

    conn.close()


if __name__ == "__main__":
    main()
