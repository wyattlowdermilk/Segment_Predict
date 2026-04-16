"""
Flag suspicious segments where the config athlete's estimated time
under neutral conditions (no wind) is unrealistically fast.

Two rules:
  1. GLOBAL: Flag if estimated time < threshold × KOM (default: 90%).
     Catches segments with GPS issues or bad data everywhere.

  2. PER-STATE (--state-check): Flag if a segment has many unique athletes
     (default: 100+) AND the config athlete would beat the KOM outright.
     If 100+ real riders can't beat a time but your model does with no
     wind, the segment data is suspect.

Usage:
    python flag_suspicious_segments.py                          # Global 90% rule
    python flag_suspicious_segments.py --state-check CO         # Also flag CO high-competition
    python flag_suspicious_segments.py --state-check CO --min-athletes 200
    python flag_suspicious_segments.py --dry-run                # Preview without writing
    python flag_suspicious_segments.py --threshold 0.85         # Stricter global rule
"""

import sqlite3
import sys

# Re-use the app's imports
from segment_time_estimator import AthleteProfile, PowerModel, format_time

# Try loading config, fall back to defaults
try:
    from config import (
        POWER_1_MIN,
        POWER_3_MIN,
        POWER_8_MIN,
        POWER_20_MIN,
        RIDER_WEIGHT_KG,
        BIKE_WEIGHT_KG,
        CDA_M2,
        CRR,
    )
except ImportError:
    POWER_1_MIN = 400
    POWER_3_MIN = 340
    POWER_8_MIN = 300
    POWER_20_MIN = 250
    RIDER_WEIGHT_KG = 75
    BIKE_WEIGHT_KG = 8
    CDA_M2 = 0.32
    CRR = 0.004

# Re-use the simulation function from the app
from app import estimate_time_with_entrance_speed, ensure_flagged_table

SEGMENTS_DB = "segments.db"
REQUESTS_DB = "requests.db"
ENTRANCE_SPEED_MPH = 20  # Default neutral entrance speed

# Neutral weather: no wind, standard conditions
NEUTRAL_WEATHER = {
    "temp_c": 15,
    "pressure_hpa": 1013,
    "wind_speed_ms": 0,
    "wind_angle": 90,  # crosswind = effectively no wind component
}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Flag suspicious segments")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print results without writing to DB"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.90,
        help="Global rule: flag if estimated < threshold × KOM (default: 0.90)",
    )
    parser.add_argument(
        "--state-check",
        type=str,
        nargs="+",
        metavar="STATE",
        help="State(s) to apply high-competition check (e.g. CO PA)",
    )
    parser.add_argument(
        "--min-athletes",
        type=int,
        default=100,
        help="Min unique athletes for state-check rule (default: 100)",
    )
    args = parser.parse_args()

    threshold = args.threshold
    dry_run = args.dry_run
    state_check = (
        set(s.upper() for s in args.state_check) if args.state_check else set()
    )
    min_athletes = args.min_athletes

    # Create athlete from config defaults
    power_curve = {1: POWER_1_MIN, 3: POWER_3_MIN, 8: POWER_8_MIN, 20: POWER_20_MIN}
    athlete = AthleteProfile(
        power_curve=power_curve,
        weight_kg=RIDER_WEIGHT_KG,
        bike_weight_kg=BIKE_WEIGHT_KG,
        cda=CDA_M2,
        crr=CRR,
    )

    # Ensure flagged table exists
    ensure_flagged_table(REQUESTS_DB)

    # Load all segments
    conn = sqlite3.connect(SEGMENTS_DB)
    segments = conn.execute(
        """
        SELECT s.id, s.name, s.distance_m, s.avg_grade, s.elevation_gain_m,
               s.state, s.athlete_count
        FROM segments s
        WHERE s.start_lat IS NOT NULL
        """
    ).fetchall()

    # Load all KOM times
    kom_rows = conn.execute(
        "SELECT segment_id, MIN(time_seconds) FROM leaderboard GROUP BY segment_id"
    ).fetchall()
    kom_map = {row[0]: row[1] for row in kom_rows if row[1]}

    # Load already-flagged (from requests DB)
    conn_req = sqlite3.connect(REQUESTS_DB)
    already_flagged = set(
        row[0]
        for row in conn_req.execute(
            "SELECT segment_id FROM flagged_segments"
        ).fetchall()
    )
    conn_req.close()
    conn.close()

    print(
        f"Config athlete: {POWER_1_MIN}W/1min, {POWER_3_MIN}W/3min, "
        f"{POWER_8_MIN}W/8min, {POWER_20_MIN}W/20min"
    )
    print(f"Weight: {RIDER_WEIGHT_KG}kg rider + {BIKE_WEIGHT_KG}kg bike")
    print(f"CdA: {CDA_M2}, Crr: {CRR}")
    print(f"Entrance speed: {ENTRANCE_SPEED_MPH} mph")
    print(f"Rule 1 — Global:      estimated < {threshold*100:.0f}% of KOM → flag")
    if state_check:
        print(
            f"Rule 2 — State check: {', '.join(sorted(state_check))} with "
            f"{min_athletes}+ athletes AND estimated < KOM → flag"
        )
    print(f"Segments to test: {len(segments)}")
    print(f"Already excluded: {len(already_flagged)}")
    print(f"{'DRY RUN' if dry_run else 'LIVE — will write to DB'}")
    print("-" * 80)

    to_flag = []

    for (
        seg_id,
        name,
        distance_m,
        avg_grade,
        elev_gain,
        state,
        athlete_count,
    ) in segments:
        kom_time = kom_map.get(seg_id)
        if not kom_time:
            continue

        if seg_id in already_flagged:
            continue

        segment_dict = {
            "distance_m": distance_m,
            "avg_grade": avg_grade,
            "elevation_high_m": elev_gain or 0,
            "elevation_low_m": 0,
        }

        try:
            result = estimate_time_with_entrance_speed(
                segment_dict, athlete, ENTRANCE_SPEED_MPH, NEUTRAL_WEATHER
            )
            est_time = result["total_time"]
        except Exception:
            continue

        if est_time >= 9999:
            continue

        pct_of_kom = est_time / kom_time
        reason = None

        # Rule 1: Global threshold (est < 90% of KOM)
        if pct_of_kom < threshold:
            reason = (
                f"Auto-excluded: estimated {pct_of_kom*100:.0f}% of KOM "
                f"under neutral conditions"
            )

        # Rule 2: State-specific high-competition check
        # If the segment is in a checked state, has many athletes,
        # and the config athlete beats the KOM outright — flag it.
        if (
            reason is None
            and state_check
            and (state or "").upper() in state_check
            and (athlete_count or 0) >= min_athletes
            and pct_of_kom < 1.0
        ):
            reason = (
                f"Auto-excluded ({state}): config athlete beats KOM "
                f"({pct_of_kom*100:.0f}%) on segment with "
                f"{athlete_count} athletes — likely bad data"
            )

        if reason:
            to_flag.append(
                {
                    "id": seg_id,
                    "name": name,
                    "est_time": est_time,
                    "kom_time": kom_time,
                    "pct_of_kom": pct_of_kom * 100,
                    "reason": reason,
                    "state": state,
                    "athlete_count": athlete_count or 0,
                }
            )
            rule_tag = "R1-GLOBAL" if pct_of_kom < threshold else "R2-STATE "
            print(
                f"  {rule_tag}  {seg_id:>10}  {pct_of_kom*100:5.1f}% of KOM  "
                f"est={format_time(est_time)}  KOM={format_time(kom_time)}  "
                f"athletes={athlete_count or '?':>5}  "
                f"{name[:45]}"
            )

    print("-" * 80)
    print(f"Segments to exclude: {len(to_flag)}")

    if to_flag and not dry_run:
        conn = sqlite3.connect(REQUESTS_DB)
        for seg in to_flag:
            conn.execute(
                "INSERT OR REPLACE INTO flagged_segments (segment_id, reason) VALUES (?, ?)",
                (seg["id"], seg["reason"]),
            )
        conn.commit()
        conn.close()
        print(f"Wrote {len(to_flag)} segments to flagged_segments table.")
    elif to_flag:
        print("Dry run — no changes written. Remove --dry-run to apply.")
    else:
        print("No suspicious segments found.")


if __name__ == "__main__":
    main()
