#!/usr/bin/env python3
"""
Test script for Segment Time Estimator
Verifies that all components work correctly
"""

import sys
import os

def test_imports():
    """Test that all required modules can be imported"""
    print("🧪 Testing imports...")
    
    try:
        import requests
        print("  ✅ requests")
    except ImportError:
        print("  ❌ requests - Run: pip install requests")
        return False
    
    try:
        import sqlite3
        print("  ✅ sqlite3")
    except ImportError:
        print("  ❌ sqlite3")
        return False
    
    try:
        import math
        import json
        from datetime import datetime, timedelta
        print("  ✅ standard library modules")
    except ImportError:
        print("  ❌ standard library modules")
        return False
    
    return True


def test_database():
    """Test database connection and structure"""
    print("\n🧪 Testing database...")
    
    import sqlite3
    
    db_paths = ["segments.db", "/mnt/user-data/uploads/segments.db"]
    db_found = None
    
    for db_path in db_paths:
        if os.path.exists(db_path):
            db_found = db_path
            break
    
    if not db_found:
        print(f"  ⚠️  Database not found in {db_paths}")
        print(f"  💡 Make sure segments.db is in the current directory")
        return False
    
    print(f"  ✅ Database found: {db_found}")
    
    try:
        conn = sqlite3.connect(db_found)
        cur = conn.cursor()
        
        # Check segments table
        cur.execute("SELECT COUNT(*) FROM segments")
        seg_count = cur.fetchone()[0]
        print(f"  ✅ Segments table: {seg_count} rows")
        
        if seg_count == 0:
            print(f"  ⚠️  No segments in database")
            print(f"  💡 Run Segment_Pull.py to populate")
            return False
        
        # Check leaderboard table
        cur.execute("SELECT COUNT(*) FROM leaderboard")
        lb_count = cur.fetchone()[0]
        print(f"  ✅ Leaderboard table: {lb_count} rows")
        
        # Get sample segment
        cur.execute("""
            SELECT id, name, distance_m, elevation_gain_m, avg_grade 
            FROM segments LIMIT 1
        """)
        sample = cur.fetchone()
        
        if sample:
            print(f"  ✅ Sample segment: ID={sample[0]}, Name='{sample[1]}'")
            print(f"      Distance={sample[2]:.0f}m, Climb={sample[3]:.0f}m, Grade={sample[4]:.1f}%")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"  ❌ Database error: {e}")
        return False


def test_estimator():
    """Test the estimator module"""
    print("\n🧪 Testing estimator module...")
    
    try:
        from segment_time_estimator import (
            AthleteProfile, PowerModel, WeatherForecast,
            SegmentEstimator, format_time
        )
        print("  ✅ Estimator imports successful")
    except Exception as e:
        print(f"  ❌ Import error: {e}")
        return False
    
    # Test AthleteProfile
    try:
        athlete = AthleteProfile(ftp=250, weight_kg=75)
        print(f"  ✅ AthleteProfile: {athlete}")
    except Exception as e:
        print(f"  ❌ AthleteProfile error: {e}")
        return False
    
    # Test PowerModel
    try:
        power = PowerModel.power_required(
            speed_ms=8.0,
            grade_percent=5.0,
            total_weight_kg=83,
            cda=0.32,
            crr=0.004,
            air_density=1.2
        )
        print(f"  ✅ PowerModel: {power:.0f}W required at 8 m/s on 5% grade")
    except Exception as e:
        print(f"  ❌ PowerModel error: {e}")
        return False
    
    # Test format_time
    try:
        time_str = format_time(256)
        print(f"  ✅ Time formatting: 256s = {time_str}")
    except Exception as e:
        print(f"  ❌ Time formatting error: {e}")
        return False
    
    return True


def test_weather_api():
    """Test weather API configuration"""
    print("\n🧪 Testing weather API...")
    
    try:
        from config import WEATHER_API_KEY
        
        if WEATHER_API_KEY == "YOUR_API_KEY_HERE":
            print("  ⚠️  Weather API key not configured")
            print("  💡 Edit config.py and add your OpenWeatherMap API key")
            print("  💡 Get free key at: https://openweathermap.org/api")
            print("  💡 Script will use mock weather data for now")
            return True  # Not a failure, just a warning
        
        print(f"  ✅ API key configured: {WEATHER_API_KEY[:8]}...")
        
        # Try a quick test call
        from segment_time_estimator import WeatherForecast
        weather = WeatherForecast(WEATHER_API_KEY)
        
        # Test with Seattle coordinates
        forecasts = weather.get_forecast(47.6062, -122.3321)
        
        if forecasts and len(forecasts) > 0:
            print(f"  ✅ Weather API working: {len(forecasts)} forecast periods")
            print(f"      Next: {forecasts[0]['temp_c']:.1f}°C, "
                  f"{forecasts[0]['description']}")
        else:
            print("  ⚠️  Weather API returned no data (using mock)")
        
        return True
        
    except ImportError:
        print("  ⚠️  Config file not found (using defaults)")
        return True
    except Exception as e:
        print(f"  ⚠️  Weather API error (will use mock): {e}")
        return True


def test_full_estimation():
    """Test a complete estimation run"""
    print("\n🧪 Testing full estimation...")
    
    try:
        from segment_time_estimator import SegmentEstimator, AthleteProfile
        import sqlite3
        
        # Find database
        db_path = "segments.db" if os.path.exists("segments.db") else "/mnt/user-data/uploads/segments.db"
        
        if not os.path.exists(db_path):
            print("  ⚠️  Skipping (no database)")
            return True
        
        # Get first segment
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM segments LIMIT 1")
        row = cur.fetchone()
        conn.close()
        
        if not row:
            print("  ⚠️  Skipping (no segments)")
            return True
        
        segment_id, segment_name = row
        
        # Create estimator
        api_key = "YOUR_API_KEY_HERE"
        try:
            from config import WEATHER_API_KEY
            api_key = WEATHER_API_KEY
        except:
            pass
        
        estimator = SegmentEstimator(db_path, api_key)
        athlete = AthleteProfile(ftp=250, weight_kg=75)
        
        # Run estimation
        print(f"  🔄 Estimating segment: {segment_name} (ID: {segment_id})")
        result = estimator.estimate_time(segment_id, athlete)
        
        print(f"  ✅ Estimation successful!")
        print(f"      Time: {result['estimated_time_formatted']}")
        print(f"      Speed: {result['avg_speed_kmh']:.1f} km/h")
        print(f"      Power: {result['sustainable_power_watts']:.0f}W")
        print(f"      Weather: {result['weather']['temp_c']:.1f}°C, "
              f"{result['weather']['description']}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Estimation error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "="*70)
    print("🚴 Segment Time Estimator - System Test")
    print("="*70 + "\n")
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("Database", test_database()))
    results.append(("Estimator Module", test_estimator()))
    results.append(("Weather API", test_weather_api()))
    results.append(("Full Estimation", test_full_estimation()))
    
    print("\n" + "="*70)
    print("📊 Test Results Summary")
    print("="*70)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status:<10} {test_name}")
    
    all_passed = all(result[1] for result in results)
    
    print("\n" + "="*70)
    
    if all_passed:
        print("🎉 All tests passed! System is ready.")
        print("\nNext steps:")
        print("  1. Edit config.py with your athlete profile")
        print("  2. Add weather API key (optional, but recommended)")
        print("  3. Run: python estimate.py --list-segments")
        print("  4. Run: python estimate.py --segment <ID> --best-windows")
    else:
        print("⚠️  Some tests failed. Please fix issues above.")
        print("\nCommon fixes:")
        print("  - pip install requests")
        print("  - Ensure segments.db is in current directory")
        print("  - Run Segment_Pull.py to populate database")
        print("  - Add weather API key to config.py (optional)")
    
    print("\n" + "="*70 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
