"""
Fill & Clean Elevation — Full-Resolution Pipeline
===================================================
Decodes polylines from segments.map_polyline, fetches elevation for
EVERY polyline point (full resolution), then smooths and resamples
down to clean_seg_points.

This produces much more accurate profiles than resampling first,
especially for steep segments where the sparse approach missed
gradient detail.

No temporary tables are created — raw points are held in memory
during processing and only clean results are written to the DB.

Usage:
  python Fill_and_Clean_Elevation.py                  # Process new segments only
  python Fill_and_Clean_Elevation.py --all            # Re-process everything
  python Fill_and_Clean_Elevation.py --segment 619307 # Process one segment
  python Fill_and_Clean_Elevation.py --dry-run        # Preview without writing
  python Fill_and_Clean_Elevation.py --cleanup         # Drop legacy segment_points + VACUUM

Run after Segment_Pull (or pipeline.py pull).
"""

import sqlite3
import numpy as np
import argparse
import sys
import math
import time

try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("ERROR: requests package required. pip install requests")
    sys.exit(1)

try:
    import polyline as polyline_lib

    HAS_POLYLINE = True
except ImportError:
    HAS_POLYLINE = False
    print("ERROR: polyline package required. pip install polyline")
    sys.exit(1)

try:
    from scipy.ndimage import gaussian_filter1d

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ============================================================
# Configuration
# ============================================================
DB_PATH = "segments.db"

# Elevation API
ELEV_BATCH_SIZE = 50
ELEV_SLEEP = 1.4  # seconds between batches
MAX_RETRIES = 5

# Smoothing — sigma=4 is applied to full-resolution raw points
# (hundreds of points), so it works correctly here.
SMOOTH_SIGMA = 4

# Resampling targets (applied AFTER smoothing on full data)
MIN_CLEAN_POINTS = 10
MAX_CLEAN_POINTS = 120
POINTS_PER_100M = 1.2

# Grade clamp
MAX_GRADE_CLAMP = 35.0  # %


# ============================================================
# Haversine distance
# ============================================================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0  # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ============================================================
# Elevation API
# ============================================================
def fetch_elevations_open_meteo(points):
    """Fetch from Open-Meteo (no key required)."""
    lats = ",".join(f"{lat:.6f}" for lat, lon in points)
    lons = ",".join(f"{lon:.6f}" for lat, lon in points)
    url = f"https://api.open-meteo.com/v1/elevation?latitude={lats}&longitude={lons}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "elevation" in data:
        return data["elevation"]
    raise ValueError(f"Unexpected response: {data}")


def fetch_elevations_open_topo(points):
    """Fallback: Open Topo Data (SRTM 30m)."""
    locations = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in points)
    url = f"https://api.opentopodata.org/v1/srtm30m?locations={locations}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") == "OK":
        return [
            r["elevation"] if r["elevation"] is not None else 0.0
            for r in data["results"]
        ]
    raise ValueError(f"Open Topo Data error: {data}")


def fetch_elevations(points):
    """Try Open-Meteo first, fall back to Open Topo Data."""
    try:
        return fetch_elevations_open_meteo(points)
    except Exception as e:
        print(f"      Open-Meteo failed ({e}), trying Open Topo Data...")
        return fetch_elevations_open_topo(points)


def fetch_elevations_batched(coords, batch_size=ELEV_BATCH_SIZE, label=""):
    """
    Fetch elevation for a list of (lat, lon) tuples with batching,
    rate-limit backoff, and sleep between batches.
    """
    all_elevations = []
    total = len(coords)
    n_batches = math.ceil(total / batch_size)

    for i in range(0, total, batch_size):
        batch = coords[i : i + batch_size]
        batch_num = i // batch_size + 1

        for attempt in range(MAX_RETRIES):
            try:
                elevs = fetch_elevations(batch)
                all_elevations.extend(elevs)
                break
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    wait = 5 * (attempt + 1)
                    print(f"      Rate limit — waiting {wait}s (attempt {attempt + 1})")
                    time.sleep(wait)
                else:
                    raise
            except Exception as e:
                print(f"      Elevation fetch error: {e}")
                all_elevations.extend([0.0] * len(batch))
                break

        if label and (batch_num % 5 == 0 or batch_num == n_batches):
            print(
                f"      {label}: batch {batch_num}/{n_batches} ({len(all_elevations)}/{total} pts)"
            )

        if i + batch_size < total:
            time.sleep(ELEV_SLEEP)

    return all_elevations


# ============================================================
# Smoothing
# ============================================================
def smooth_elevation(elevations: np.ndarray, sigma: float = SMOOTH_SIGMA) -> np.ndarray:
    """
    Gaussian smooth elevation array on full-resolution raw data.
    With hundreds of raw points, sigma=4 provides meaningful noise
    reduction without destroying gradient detail.
    """
    n = len(elevations)
    if n < 3:
        return elevations.copy()

    if HAS_SCIPY:
        smoothed = gaussian_filter1d(elevations, sigma=sigma, mode="nearest")
    else:
        window = max(3, int(2 * sigma + 1))
        if window % 2 == 0:
            window += 1
        kernel = np.ones(window) / window
        smoothed = np.convolve(elevations, kernel, mode="same")

    return smoothed


# ============================================================
# Decode polyline to full-resolution points
# ============================================================
def decode_polyline(polyline_str):
    """
    Decode a polyline string to arrays of (distance_km, lat, lon).
    Returns (d_raw, lat_raw, lon_raw, n_original) or Nones on failure.
    """
    try:
        raw_points = polyline_lib.decode(polyline_str)
    except Exception:
        return None, None, None, 0

    if len(raw_points) < 2:
        return None, None, None, len(raw_points)

    d_raw = [0.0]
    lat_raw = [raw_points[0][0]]
    lon_raw = [raw_points[0][1]]

    for i in range(1, len(raw_points)):
        dist = haversine(
            raw_points[i - 1][0],
            raw_points[i - 1][1],
            raw_points[i][0],
            raw_points[i][1],
        )
        d_raw.append(d_raw[-1] + dist)
        lat_raw.append(raw_points[i][0])
        lon_raw.append(raw_points[i][1])

    d_raw = np.array(d_raw)
    lat_raw = np.array(lat_raw)
    lon_raw = np.array(lon_raw)

    # Remove duplicate distances
    mask = np.concatenate([[True], np.diff(d_raw) > 1e-7])
    d_raw, lat_raw, lon_raw = d_raw[mask], lat_raw[mask], lon_raw[mask]

    return d_raw, lat_raw, lon_raw, len(raw_points)


# ============================================================
# Process a single segment end-to-end
# ============================================================
def process_single_segment(cur, conn, segment_id, strava_gain_m=None, verbose=True):
    """
    Full-resolution elevation pipeline for one segment:
      1. Decode polyline → all points (in memory)
      2. Fetch elevation for EVERY point via API
      3. Fix outlier spikes
      4. Smooth on full-resolution data (sigma=4)
      5. Resample down to clean resolution
      6. Compute grades
      7. Write clean_seg_points + clean_seg_qa
      (No temp tables — raw data stays in memory only)
    """
    # 1. Get polyline and decode
    cur.execute("SELECT map_polyline FROM segments WHERE id = ?", (segment_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        return {"success": False, "message": "No polyline data"}

    d_raw, lat_raw, lon_raw, n_original = decode_polyline(row[0])
    if d_raw is None or len(d_raw) < 2:
        return {"success": False, "message": f"Only {n_original} polyline points"}

    total_dist_m = (d_raw[-1] - d_raw[0]) * 1000
    if verbose:
        print(f"    Step 1: Decoded {n_original} polyline points ({total_dist_m:.0f}m)")

    # 2. Fetch elevation for ALL points
    coords = list(zip(lat_raw.tolist(), lon_raw.tolist()))
    n_batches = math.ceil(len(coords) / ELEV_BATCH_SIZE)
    est_time = n_batches * ELEV_SLEEP
    if verbose:
        print(
            f"    Step 2: Fetching elevation — {len(coords)} pts, {n_batches} batches (~{est_time:.0f}s)"
        )

    elevations = fetch_elevations_batched(
        coords, label=f"Seg {segment_id}" if verbose else ""
    )

    if len(elevations) != len(d_raw):
        return {
            "success": False,
            "message": f"Elevation mismatch: got {len(elevations)}, expected {len(d_raw)}",
        }

    e_raw = np.array(elevations, dtype=float)

    # 3. Fix outlier spikes
    outliers_replaced = 0
    if len(e_raw) >= 3:
        for i in range(1, len(e_raw) - 1):
            d_prev = (d_raw[i] - d_raw[i - 1]) * 1000
            d_next = (d_raw[i + 1] - d_raw[i]) * 1000
            if d_prev < 0.1 or d_next < 0.1:
                continue
            grade_in = abs(e_raw[i] - e_raw[i - 1]) / d_prev * 100
            grade_out = abs(e_raw[i + 1] - e_raw[i]) / d_next * 100
            if grade_in > 40 and grade_out > 40:
                change_in = e_raw[i] - e_raw[i - 1]
                change_out = e_raw[i + 1] - e_raw[i]
                if (change_in > 0 and change_out < 0) or (
                    change_in < 0 and change_out > 0
                ):
                    e_raw[i] = e_raw[i - 1] + (
                        (e_raw[i + 1] - e_raw[i - 1])
                        * (d_raw[i] - d_raw[i - 1])
                        / (d_raw[i + 1] - d_raw[i - 1])
                    )
                    outliers_replaced += 1

    # Raw grade QA
    raw_grades = []
    for i in range(1, len(d_raw)):
        dist_m = (d_raw[i] - d_raw[i - 1]) * 1000
        if dist_m > 0.1:
            raw_grades.append(((e_raw[i] - e_raw[i - 1]) / dist_m) * 100)
    max_raw_grade = max(abs(g) for g in raw_grades) if raw_grades else 0

    if verbose:
        print(
            f"    Step 3: Fixed {outliers_replaced} outlier(s), max raw grade {max_raw_grade:.0f}%"
        )

    # 4. Smooth on full-resolution data
    e_smooth = smooth_elevation(e_raw, sigma=SMOOTH_SIGMA)
    if verbose:
        print(f"    Step 4: Smoothed {len(e_smooth)} points (sigma={SMOOTH_SIGMA})")

    # 5. Resample to clean resolution
    n_clean = max(
        MIN_CLEAN_POINTS,
        min(MAX_CLEAN_POINTS, int(total_dist_m / 100 * POINTS_PER_100M)),
    )
    if total_dist_m < 200:
        n_clean = MIN_CLEAN_POINTS

    clean_d = np.linspace(d_raw[0], d_raw[-1], n_clean)
    clean_e = np.interp(clean_d, d_raw, e_smooth)
    clean_lat = np.interp(clean_d, d_raw, lat_raw)
    clean_lon = np.interp(clean_d, d_raw, lon_raw)

    # 6. Compute grades
    grades = []
    for i in range(n_clean):
        if i == 0:
            dist_m = (clean_d[1] - clean_d[0]) * 1000
            g = ((clean_e[1] - clean_e[0]) / dist_m) * 100 if dist_m > 0 else 0
        else:
            dist_m = (clean_d[i] - clean_d[i - 1]) * 1000
            g = ((clean_e[i] - clean_e[i - 1]) / dist_m) * 100 if dist_m > 0 else 0
        g = max(-MAX_GRADE_CLAMP, min(MAX_GRADE_CLAMP, g))
        grades.append(g)
    grades[-1] = None

    total_gain = sum(max(0, clean_e[i] - clean_e[i - 1]) for i in range(1, n_clean))
    max_clean_grade = (
        max(abs(g) for g in grades if g is not None)
        if any(g is not None for g in grades)
        else 0
    )

    if verbose:
        print(f"    Step 5: Resampled {len(e_smooth)} pts -> {n_clean} clean points")
        print(
            f"    Step 6: Max clean grade {max_clean_grade:.1f}%, gain {total_gain:.1f}m"
        )

    # 7. Write
    clean_points = []
    for i in range(n_clean):
        clean_points.append(
            (
                i,
                float(clean_d[i]),
                float(clean_lat[i]),
                float(clean_lon[i]),
                float(clean_e[i]),
                grades[i],
            )
        )

    qa = {
        "original_points": n_original,
        "clean_points": n_clean,
        "had_duplicate_elevations": 0,
        "outliers_replaced": outliers_replaced,
        "max_raw_grade_pct": round(max_raw_grade, 2),
        "max_clean_grade_pct": round(max_clean_grade, 2),
        "elevation_gain_clean_m": round(total_gain, 2),
        "elevation_gain_strava_m": round(strava_gain_m, 4) if strava_gain_m else None,
    }

    result = {"success": True, "clean_points": clean_points, "qa": qa}
    write_clean_data(conn, segment_id, result)

    msg = (
        f"{n_original} raw -> {n_clean} clean, "
        f"max grade {max_raw_grade:.0f}% -> {max_clean_grade:.1f}%, "
        f"gain {total_gain:.1f}m"
        + (f" (Strava: {strava_gain_m:.0f}m)" if strava_gain_m else "")
    )
    return {"success": True, "message": msg, "qa": qa}


# ============================================================
# Write results to DB
# ============================================================
def write_clean_data(conn, segment_id, result):
    """Write cleaned elevation data and QA metrics to the database."""
    cur = conn.cursor()
    cur.execute("DELETE FROM clean_seg_points WHERE segment_id = ?", (segment_id,))
    cur.execute("DELETE FROM clean_seg_qa WHERE segment_id = ?", (segment_id,))

    for seq, dist, lat, lon, elev, grade in result["clean_points"]:
        cur.execute(
            "INSERT INTO clean_seg_points "
            "(segment_id, seq, distance_km, lat, lon, elevation_m, grade_pct) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (segment_id, seq, dist, lat, lon, elev, grade),
        )

    qa = result["qa"]
    cur.execute(
        "INSERT INTO clean_seg_qa "
        "(segment_id, original_points, clean_points, had_duplicate_elevations, "
        "outliers_replaced, max_raw_grade_pct, max_clean_grade_pct, "
        "elevation_gain_clean_m, elevation_gain_strava_m) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            segment_id,
            qa["original_points"],
            qa["clean_points"],
            qa["had_duplicate_elevations"],
            qa["outliers_replaced"],
            qa["max_raw_grade_pct"],
            qa["max_clean_grade_pct"],
            qa["elevation_gain_clean_m"],
            qa["elevation_gain_strava_m"],
        ),
    )
    conn.commit()


# ============================================================
# Cleanup: drop legacy segment_points and reclaim space
# ============================================================
def cleanup_raw_points(conn):
    """Drop the segment_points table and VACUUM to reclaim disk space."""
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='segment_points'"
    )
    if cur.fetchone():
        cur.execute("SELECT COUNT(*) FROM segment_points")
        count = cur.fetchone()[0]
        print(f"  Dropping segment_points table ({count:,} rows)...")
        cur.execute("DROP TABLE segment_points")
        conn.commit()
        print("  Running VACUUM to reclaim disk space...")
        conn.execute("VACUUM")
        print("  Done — raw points removed.")
    else:
        print("  segment_points table doesn't exist — nothing to clean up.")


# ============================================================
# Find segments to process
# ============================================================
def find_segments(conn, mode, segment_id=None):
    """Returns list of (segment_id, elevation_gain_m)."""
    cur = conn.cursor()

    if mode == "single":
        cur.execute(
            "SELECT id, elevation_gain_m FROM segments "
            "WHERE id = ? AND map_polyline IS NOT NULL",
            (segment_id,),
        )
    elif mode == "new":
        cur.execute(
            """
            SELECT s.id, s.elevation_gain_m
            FROM segments s
            LEFT JOIN clean_seg_points csp ON s.id = csp.segment_id
            WHERE s.map_polyline IS NOT NULL
              AND csp.segment_id IS NULL
            ORDER BY s.id
        """
        )
    elif mode == "all":
        cur.execute(
            """
            SELECT id, elevation_gain_m
            FROM segments
            WHERE map_polyline IS NOT NULL
            ORDER BY id
        """
        )
    else:
        return []

    return cur.fetchall()


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Full-resolution elevation fill + clean for cycling segments"
    )
    parser.add_argument("--db", default=DB_PATH, help="Path to segments.db")
    parser.add_argument("--all", action="store_true", help="Re-process all segments")
    parser.add_argument("--segment", type=int, help="Process a single segment ID")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writing"
    )
    parser.add_argument(
        "--cleanup", action="store_true", help="Drop segment_points table and VACUUM"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    if args.cleanup:
        cleanup_raw_points(conn)
        conn.close()
        return

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

    # Find segments
    if args.segment:
        segments = find_segments(conn, "single", args.segment)
    elif args.all:
        segments = find_segments(conn, "all")
    else:
        segments = find_segments(conn, "new")

    if not segments:
        print("✓ All segments already processed. Use --all to redo.")
        conn.close()
        return

    # Estimate total work
    total_pts_est = 0
    for seg_id, _ in segments:
        cur.execute("SELECT map_polyline FROM segments WHERE id = ?", (seg_id,))
        poly_row = cur.fetchone()
        if poly_row and poly_row[0]:
            try:
                pts = polyline_lib.decode(poly_row[0])
                total_pts_est += len(pts)
            except Exception:
                pass

    n_batches_est = math.ceil(total_pts_est / ELEV_BATCH_SIZE)
    est_minutes = n_batches_est * ELEV_SLEEP / 60

    print(f"Processing {len(segments)} segment(s)")
    print(f"  Total polyline points: ~{total_pts_est:,}")
    print(f"  Estimated API batches: ~{n_batches_est:,}")
    print(f"  Estimated time: ~{est_minutes:.1f} minutes")

    if args.dry_run:
        print("\n[DRY RUN] No changes made.")
        conn.close()
        return

    print()

    success = 0
    failed = 0
    t_start = time.time()

    for idx, (seg_id, strava_gain) in enumerate(segments, 1):
        cur.execute("SELECT name FROM segments WHERE id = ?", (seg_id,))
        name_row = cur.fetchone()
        seg_name = (name_row[0] or str(seg_id))[:45] if name_row else str(seg_id)

        print(f"  [{idx}/{len(segments)}] Segment {seg_id} — {seg_name}")

        result = process_single_segment(cur, conn, seg_id, strava_gain, verbose=True)

        if result["success"]:
            success += 1
            print(f"    ✓ {result['message']}")
        else:
            failed += 1
            print(f"    ✗ {result['message']}")

        elapsed = time.time() - t_start
        avg_per_seg = elapsed / idx
        remaining = avg_per_seg * (len(segments) - idx)
        print(f"    [{elapsed/60:.1f}m elapsed, ~{remaining/60:.1f}m remaining]")
        print()

    print(
        f"Done! Processed {success} segment(s)"
        + (f", {failed} failed" if failed else "")
    )
    print(f"Total time: {(time.time() - t_start)/60:.1f} minutes")
    conn.close()


if __name__ == "__main__":
    main()
