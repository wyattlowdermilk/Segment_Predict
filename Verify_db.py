"""
verify_db.py
Run after Segment_Pull.py and scraperSel.py to confirm both tables
populated correctly and surface any gaps or parse failures.
"""

import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "segments.db")

conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

PASS = "✅"
WARN = "⚠️ "
FAIL = "❌"


def pct(n, total):
    return f"{n/total*100:.0f}%" if total else "n/a"


def section(title):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")


# ══════════════════════════════════════════════════════
# TABLE 1 — segments  (Strava API)
# ══════════════════════════════════════════════════════
section("TABLE 1 · segments  (Strava API)")

cur.execute("SELECT COUNT(*) FROM segments")
seg_total = cur.fetchone()[0]
print(f"  Total rows : {seg_total}")

if seg_total == 0:
    print(f"  {FAIL} Table is empty — run Segment_Pull.py first")
else:
    # Fields the API reliably returns at any access level
    always_available = [
        "name",
        "distance_m",
        "elevation_gain_m",
        "avg_grade",
        "athlete_count",
        "effort_count",
        "start_lat",
        "start_lng",
        "end_lat",
        "end_lng",
        "map_polyline",
        "created_at",
        "updated_at",
    ]

    # Fields that may be null depending on access level / segment privacy
    sometimes_null = [
        "activity_type",
        "elevation_high_m",
        "elevation_low_m",
        "max_grade",
        "climb_category",
        "city",
        "state",
        "country",
        "star_count",
        "hazardous",
        "private",
        "starred",
    ]

    print(f"\n  {'Field':<22} {'Filled':>7}  {'Null':>6}  {'Fill %':>7}  Status")
    print(f"  {'-'*60}")

    for col in always_available + sometimes_null:
        cur.execute(f"SELECT COUNT(*) FROM segments WHERE {col} IS NOT NULL")
        filled = cur.fetchone()[0]
        null = seg_total - filled
        label = (
            PASS if filled == seg_total else (WARN if col in sometimes_null else FAIL)
        )
        print(
            f"  {col:<22} {filled:>7}  {null:>6}  {pct(filled,seg_total):>7}  {label}"
        )

    # Spot-check: any segments missing coordinates entirely?
    cur.execute(
        "SELECT COUNT(*) FROM segments WHERE start_lat IS NULL OR end_lat IS NULL"
    )
    no_coords = cur.fetchone()[0]
    if no_coords:
        print(
            f"\n  {FAIL} {no_coords} segment(s) missing coordinates — check API response"
        )
    else:
        print(f"\n  {PASS} All segments have coordinates")

    # Spot-check: any segments missing polyline?
    cur.execute("SELECT COUNT(*) FROM segments WHERE map_polyline IS NULL")
    no_poly = cur.fetchone()[0]
    status = PASS if no_poly == 0 else WARN
    print(f"  {status} {no_poly} segment(s) missing map polyline")

    # Sample rows
    print(f"\n  Sample rows (up to 3):")
    cur.execute(
        """
        SELECT id, name, distance_m, avg_grade, city, state, effort_count
        FROM segments LIMIT 3
    """
    )
    for row in cur.fetchall():
        print(
            f"    id={row['id']}  name='{row['name']}'  "
            f"dist={row['distance_m']}m  grade={row['avg_grade']}%  "
            f"loc={row['city']}, {row['state']}  efforts={row['effort_count']}"
        )


# ══════════════════════════════════════════════════════
# TABLE 2 — leaderboard  (scraperSel.py)
# ══════════════════════════════════════════════════════
section("TABLE 2 · leaderboard  (scraperSel.py)")

cur.execute("SELECT COUNT(*) FROM leaderboard")
lb_total = cur.fetchone()[0]
print(f"  Total rows : {lb_total}")

if lb_total == 0:
    print(f"  {FAIL} Table is empty — run scraperSel.py first")
else:
    cur.execute("SELECT COUNT(DISTINCT segment_id) FROM leaderboard")
    lb_segs = cur.fetchone()[0]
    print(f"  Segments covered : {lb_segs} / {seg_total}")

    missing_segs = seg_total - lb_segs
    if missing_segs:
        print(f"  {WARN} {missing_segs} segment(s) have no leaderboard rows")
    else:
        print(f"  {PASS} Every segment has at least one leaderboard entry")

    # Field fill rates
    scraper_fields = [
        ("athlete_name", True),
        ("time_seconds", True),
        ("date", True),
        ("speed", True),
        ("heart_rate", False),  # often hidden on Strava
        ("power", False),  # only if power meter used
        ("vam", False),  # only on climbs
    ]

    print(f"\n  {'Field':<18} {'Filled':>7}  {'Null':>6}  {'Fill %':>7}  Status")
    print(f"  {'-'*55}")

    for col, required in scraper_fields:
        cur.execute(f"SELECT COUNT(*) FROM leaderboard WHERE {col} IS NOT NULL")
        filled = cur.fetchone()[0]
        null = lb_total - filled
        label = PASS if filled == lb_total else (FAIL if required else WARN)
        print(f"  {col:<18} {filled:>7}  {null:>6}  {pct(filled,lb_total):>7}  {label}")

    # Check time_seconds sanity (no zeros or negatives)
    cur.execute(
        "SELECT COUNT(*) FROM leaderboard WHERE time_seconds IS NULL OR time_seconds <= 0"
    )
    bad_times = cur.fetchone()[0]
    status = PASS if bad_times == 0 else FAIL
    print(f"\n  {status} Bad time_seconds values (null/zero/negative): {bad_times}")

    # Rank distribution — confirm we're getting top 10 per segment
    cur.execute(
        """
        SELECT segment_id, COUNT(*) as cnt
        FROM leaderboard
        GROUP BY segment_id
        ORDER BY cnt ASC
        LIMIT 5
    """
    )
    low_counts = cur.fetchall()
    min_entries = min(r["cnt"] for r in low_counts) if low_counts else 0
    if min_entries < 5:
        print(f"  {WARN} Some segments have fewer than 5 leaderboard entries:")
        for r in low_counts:
            if r["cnt"] < 5:
                print(f"       segment_id={r['segment_id']}  entries={r['cnt']}")
    else:
        print(f"  {PASS} All scraped segments have ≥5 leaderboard entries")

    # Sample rows
    print(f"\n  Sample rows (up to 3):")
    cur.execute(
        """
        SELECT segment_id, rank, athlete_name, time_seconds, date, speed, power, vam
        FROM leaderboard ORDER BY segment_id, rank LIMIT 3
    """
    )
    for row in cur.fetchall():
        print(
            f"    seg={row['segment_id']}  rank={row['rank']}  "
            f"'{row['athlete_name']}'  {row['time_seconds']}s  "
            f"{row['date']}  spd={row['speed']}  "
            f"pwr={row['power']}W  vam={row['vam']}"
        )


# ══════════════════════════════════════════════════════
# CROSS-TABLE — leaderboard ↔ segments join integrity
# ══════════════════════════════════════════════════════
section("CROSS-TABLE · Join integrity")

cur.execute(
    """
    SELECT COUNT(DISTINCT l.segment_id)
    FROM leaderboard l
    LEFT JOIN segments s ON l.segment_id = s.id
    WHERE s.id IS NULL
"""
)
orphans = cur.fetchone()[0]
if orphans:
    print(f"  {FAIL} {orphans} leaderboard segment_id(s) have no matching segments row")
    cur.execute(
        """
        SELECT DISTINCT l.segment_id
        FROM leaderboard l
        LEFT JOIN segments s ON l.segment_id = s.id
        WHERE s.id IS NULL LIMIT 10
    """
    )
    for row in cur.fetchall():
        print(f"       orphan segment_id: {row['segment_id']}")
else:
    print(f"  {PASS} All leaderboard rows join cleanly to segments")

# Segments with API data but no scrape yet
cur.execute(
    """
    SELECT COUNT(*) FROM segments s
    LEFT JOIN leaderboard l ON s.id = l.segment_id
    WHERE l.segment_id IS NULL
"""
)
not_scraped = cur.fetchone()[0]
status = PASS if not_scraped == 0 else WARN
print(f"  {status} Segments with API data but no scraped leaderboard: {not_scraped}")

# ══════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════
section("SUMMARY")
print(f"  segments rows      : {seg_total}")
print(f"  leaderboard rows   : {lb_total}")
print(f"  Segments scraped   : {lb_segs if lb_total else 0} / {seg_total}")
print(f"  Orphaned lb rows   : {orphans}")
print(f"  Not yet scraped    : {not_scraped if lb_total else seg_total}")
print()

conn.close()
