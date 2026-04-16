#!/usr/bin/env python3
"""
Simple command-line interface for Segment Time Estimator

Usage:
    python estimate.py --segment 2969
    python estimate.py --segment 2969 --datetime "2024-04-10 14:00"
    python estimate.py --list-segments
    python estimate.py --segment 2969 --best-windows
"""

import argparse
import sys
from datetime import datetime
from segment_time_estimator import (
    SegmentEstimator,
    AthleteProfile,
    format_time,
    print_estimate,
    find_best_time_window,
)
import sqlite3

# Import configuration
try:
    from config import (
        WEATHER_API_KEY,
        POWER_1_MIN,
        POWER_3_MIN,
        POWER_8_MIN,
        POWER_20_MIN,
        RIDER_WEIGHT_KG,
        BIKE_WEIGHT_KG,
        CDA_M2,
        CRR,
        DRIVETRAIN_LOSS_PERCENT,
        DATABASE_PATH,
    )
except ImportError:
    print("❌ Error: config.py not found. Using default values.")
    WEATHER_API_KEY = "YOUR_API_KEY_HERE"
    POWER_1_MIN = 400
    POWER_3_MIN = 340
    POWER_8_MIN = 300
    POWER_20_MIN = 250
    RIDER_WEIGHT_KG = 75
    BIKE_WEIGHT_KG = 8
    CDA_M2 = 0.32
    CRR = 0.004
    DRIVETRAIN_LOSS_PERCENT = 3
    DATABASE_PATH = "segments.db"


def list_segments(db_path: str):
    """List all segments in the database"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, name, distance_m, elevation_gain_m, avg_grade, city, state
            FROM segments
            ORDER BY name
        """
        )

        segments = cur.fetchall()
        conn.close()

        if not segments:
            print("❌ No segments found in database.")
            return

        print(f"\n📍 Available Segments ({len(segments)} total)")
        print("=" * 90)
        print(
            f"{'ID':<10} {'Name':<30} {'Distance':>10} {'Climb':>8} {'Grade':>7} {'Location':<20}"
        )
        print("-" * 90)

        for seg in segments:
            location = f"{seg['city'] or ''}, {seg['state'] or ''}".strip(", ")
            print(
                f"{seg['id']:<10} {seg['name']:<30} "
                f"{seg['distance_m']/1000:>9.2f}km {seg['elevation_gain_m']:>7.0f}m "
                f"{seg['avg_grade']:>6.1f}% {location:<20}"
            )

        print("=" * 90 + "\n")

    except Exception as e:
        print(f"❌ Error listing segments: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Estimate cycling segment times with weather forecasts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list-segments                      # Show all segments
  %(prog)s --segment 2969                        # Estimate for next available time
  %(prog)s --segment 2969 --best-windows         # Show 5 best time windows
  %(prog)s --segment 2969 --datetime "2024-04-10 14:00"  # Specific datetime
  
Configuration:
  Edit config.py to set your power curve values and weather API key
        """,
    )

    parser.add_argument("--segment", "-s", type=int, help="Segment ID to analyze")
    parser.add_argument(
        "--list-segments", "-l", action="store_true", help="List all available segments"
    )
    parser.add_argument(
        "--datetime",
        "-d",
        type=str,
        help='Target datetime (format: "YYYY-MM-DD HH:MM")',
    )
    parser.add_argument(
        "--best-windows",
        "-b",
        action="store_true",
        help="Show 5 best time windows in next 7 days",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DATABASE_PATH,
        help=f"Path to database (default: {DATABASE_PATH})",
    )

    args = parser.parse_args()

    # List segments and exit
    if args.list_segments:
        list_segments(args.db)
        return

    # Require segment ID for estimation
    if not args.segment:
        parser.print_help()
        print("\n❌ Error: --segment required for time estimation")
        sys.exit(1)

    # Create athlete profile from config with power curve
    power_curve = {1: POWER_1_MIN, 3: POWER_3_MIN, 8: POWER_8_MIN, 20: POWER_20_MIN}

    athlete = AthleteProfile(
        power_curve=power_curve,
        weight_kg=RIDER_WEIGHT_KG,
        bike_weight_kg=BIKE_WEIGHT_KG,
        cda=CDA_M2,
        crr=CRR,
        drivetrain_loss=DRIVETRAIN_LOSS_PERCENT / 100,
    )

    # Initialize estimator
    estimator = SegmentEstimator(args.db, WEATHER_API_KEY)

    # Print header
    print("\n🚴 Cycling Segment Time Estimator")
    print("=" * 70)
    print(f"\n👤 {athlete}\n")

    # Parse datetime if provided
    target_datetime = None
    if args.datetime:
        try:
            target_datetime = datetime.strptime(args.datetime, "%Y-%m-%d %H:%M")
        except ValueError:
            print(f"❌ Error: Invalid datetime format. Use 'YYYY-MM-DD HH:MM'")
            sys.exit(1)

    # Estimate
    try:
        if args.best_windows:
            # Get 7-day forecast and find best windows
            print(f"Analyzing segment {args.segment} for next 7 days...\n")
            results = estimator.estimate_next_7_days(args.segment, athlete)

            if not results:
                print("❌ No forecast data available")
                sys.exit(1)

            # Show current estimate
            print_estimate(results[0])

            # Find and display best windows
            print("\n🌟 BEST TIME WINDOWS (Next 7 Days)")
            print("=" * 70)
            best_windows = find_best_time_window(results, top_n=5)

            for i, result in enumerate(best_windows, 1):
                time_diff = (
                    result["estimated_time_seconds"]
                    - best_windows[0]["estimated_time_seconds"]
                )
                print(f"\n#{i}. {result['weather']['datetime']}")
                print(
                    f"    Estimated Time: {result['estimated_time_formatted']} "
                    f"(+{time_diff:.0f}s)"
                    if i > 1
                    else f"\n#{i}. {result['weather']['datetime']}\n    Estimated Time: {result['estimated_time_formatted']}"
                )
                print(f"    Speed: {result['avg_speed_kmh']:.1f} km/h")
                print(
                    f"    Wind: {result['weather']['wind_speed_kmh']:.1f} km/h "
                    f"at {result['weather']['wind_angle']:.0f}° angle"
                )
                print(f"    Temp: {result['weather']['temp_c']:.1f}°C")
                print(f"    Conditions: {result['weather']['description']}")

            print("\n" + "=" * 70 + "\n")

        else:
            # Single estimate
            result = estimator.estimate_time(args.segment, athlete, target_datetime)
            print_estimate(result)

        print("✅ Estimation complete!\n")

    except ValueError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
