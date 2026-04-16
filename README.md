# Cycling Segment Predictor

https://segment-predict.streamlit.app/

A physics-based Python tool that estimates your time on cycling segments by combining:
- **Segment data** (distance, elevation, gradient)
- **7-day weather forecasts** (temperature, wind, rain)
- **Your power profile** (FTP, weight, aerodynamics)

## Features

- 🔬 **Physics-based power model** accounting for:
  - Gradient resistance
  - Air resistance with wind adjustment
  - Rolling resistance (including wet conditions)
  - Temperature effects on air density
  - Drivetrain losses

- 🌤️ **Weather integration**:
  - 7-day hourly forecasts
  - Wind speed and direction relative to segment
  - Temperature effects on performance
  - Rain detection for wet road adjustments

- ⚡ **Power duration curve**:
  - Automatically adjusts sustainable power based on segment duration
  - Accounts for FTP, VO2max, and endurance efforts

- 🏆 **Leaderboard comparison**:
  - Compare your estimate to actual top times
  - See average power from leaderboard

- 📊 **Find optimal time windows**:
  - Identifies the 5 best weather conditions in the next 7 days
  - Helps you plan when to attempt your PR

## Installation

### Prerequisites

```bash
# Python 3.7+ required
python3 --version

# Install required packages
pip install requests
```

### Setup

1. **Get your files in order**:
   ```
   your_directory/
   ├── segments.db              # Your segment database
   ├── segment_time_estimator.py
   ├── estimate.py
   └── config.py
   ```

2. **Get a weather API key** (free):
   - Go to https://openweathermap.org/api
   - Sign up for a free account
   - Get your API key (1000 calls/day free)

3. **Configure your athlete profile**:
   Edit `config.py` with your details:
   ```python
   WEATHER_API_KEY = "your_key_here"
   FTP_WATTS = 250              # Your FTP
   RIDER_WEIGHT_KG = 75         # Your weight
   BIKE_WEIGHT_KG = 8           # Your bike weight
   CDA_M2 = 0.32               # Your aerodynamics
   CRR = 0.004                 # Tire rolling resistance
   ```

## Usage

### Quick Start

```bash
# List all segments in your database
python estimate.py --list-segments

# Estimate time for a specific segment (next available weather)
python estimate.py --segment 2969

# Find the 5 best time windows in next 7 days
python estimate.py --segment 2969 --best-windows

# Estimate for a specific date/time
python estimate.py --segment 2969 --datetime "2024-04-10 14:00"
```

### Example Output

```
🚴 Cycling Segment Predictor
======================================================================

👤 Athlete: FTP=250W, Weight=75kg, W/kg=3.33, CdA=0.32m²

======================================================================
SEGMENT: Seminary Hill (ID: 2969)
======================================================================

📍 Segment Details:
   Distance: 0.89 km
   Elevation Gain: 101 m
   Average Grade: 11.5%
   Bearing: 45°

🌤️  Weather Conditions (2024-04-06 15:00):
   Temperature: 15.0°C
   Wind: 10.8 km/h from 180°
   Wind Angle to Segment: 135° (tailwind)
   Conditions: clear sky

⚡ Power & Speed:
   Sustainable Power: 263 W
   Power at Wheel: 255 W
   Average Speed: 12.5 km/h

⏱️  Estimated Time: 4:16
   (256 seconds)

🏆 Leaderboard Comparison:
   Best Time: 3:45
   Average Time: 4:30
   Average Power: 285 W

======================================================================
```

## How It Works

### Power Model

The estimator uses the fundamental cycling power equation:

```
Power = Power_gravity + Power_air + Power_rolling
```

Where:
- **Power_gravity** = m × g × sin(grade) × v
- **Power_air** = 0.5 × CdA × ρ × (v + v_wind)³
- **Power_rolling** = m × g × cos(grade) × Crr × v

Variables:
- `m` = total mass (rider + bike)
- `g` = gravity (9.81 m/s²)
- `CdA` = drag coefficient × frontal area
- `ρ` = air density (adjusted for temperature, pressure, elevation)
- `v` = speed
- `v_wind` = headwind component
- `Crr` = rolling resistance coefficient

### Weather Adjustments

1. **Air density**: Calculated from temperature, pressure, and elevation
   - Warmer air = less resistance = faster times
   - Higher elevation = less resistance = faster times

2. **Wind**: 
   - Calculated relative to segment bearing
   - 0° = direct headwind (slowest)
   - 90° = crosswind (moderate impact)
   - 180° = direct tailwind (fastest)

3. **Wet conditions**:
   - Rolling resistance increases 20% in rain
   - Detected from precipitation in forecast

### Power Duration Curve

Your sustainable power varies with effort duration:

| Duration | % of FTP | Typical Use |
|----------|----------|-------------|
| < 5 min  | 120%     | VO2max efforts |
| 5-20 min | 105%     | Above threshold |
| 20-60 min| 100%     | FTP efforts |
| > 60 min | 90%      | Endurance |

The estimator automatically adjusts your power target based on estimated segment duration.

## Configuration Guide

### Finding Your FTP

Your Functional Threshold Power is the power you can sustain for ~1 hour:

- **Direct test**: 20-minute max effort × 0.95
- **Ramp test**: Maximum 1-minute power × 0.75
- **From training**: Check your power meter or training app
- **Estimates**: 
  - Beginner: 150-200W (2.0-2.5 W/kg)
  - Intermediate: 200-300W (2.5-3.5 W/kg)
  - Advanced: 300-400W (3.5-5.0 W/kg)
  - Elite: 400+ W (5.0+ W/kg)

### Aerodynamics (CdA)

Your CdA depends on position and equipment:

| Position | CdA (m²) |
|----------|----------|
| Upright (commuter) | 0.40-0.45 |
| Hoods (road bike) | 0.35-0.40 |
| Drops (road bike) | 0.30-0.35 |
| Aero position (TT bike) | 0.25-0.30 |

**To improve accuracy**: Get a wind tunnel test or use field testing methods.

### Rolling Resistance (Crr)

Depends on tire type and pressure:

| Tire Type | Crr |
|-----------|-----|
| High-end race (25mm, 100psi) | 0.003-0.004 |
| Good road tires (25-28mm) | 0.004-0.005 |
| Budget road tires | 0.005-0.006 |
| Gravel tires (40mm+) | 0.006-0.008 |

**Lower = faster**. Higher pressure generally = lower Crr (to a point).

## Advanced Usage

### Custom Athlete Profiles

You can create multiple profiles programmatically:

```python
from segment_time_estimator import AthleteProfile, SegmentEstimator

# Create profiles
amateur = AthleteProfile(ftp=200, weight_kg=80, cda=0.35)
pro = AthleteProfile(ftp=400, weight_kg=65, cda=0.28)

# Compare estimates
estimator = SegmentEstimator("segments.db", "your_api_key")
result_amateur = estimator.estimate_time(2969, amateur)
result_pro = estimator.estimate_time(2969, pro)

print(f"Amateur: {result_amateur['estimated_time_formatted']}")
print(f"Pro: {result_pro['estimated_time_formatted']}")
```

### Batch Analysis

Estimate all segments:

```python
import sqlite3
from segment_time_estimator import AthleteProfile, SegmentEstimator

athlete = AthleteProfile(ftp=250, weight_kg=75)
estimator = SegmentEstimator("segments.db", "your_api_key")

# Get all segments
conn = sqlite3.connect("segments.db")
cur = conn.cursor()
cur.execute("SELECT id FROM segments")
segment_ids = [row[0] for row in cur.fetchall()]
conn.close()

# Estimate each
results = []
for seg_id in segment_ids:
    try:
        result = estimator.estimate_time(seg_id, athlete)
        results.append(result)
        print(f"Segment {seg_id}: {result['estimated_time_formatted']}")
    except Exception as e:
        print(f"Error on segment {seg_id}: {e}")

# Find fastest segments for your profile
results.sort(key=lambda x: x['estimated_time_seconds'])
print("\nYour fastest segments:")
for r in results[:5]:
    print(f"{r['segment_name']}: {r['estimated_time_formatted']}")
```

### Export Results

Save estimates to CSV:

```python
import csv
from segment_time_estimator import SegmentEstimator, AthleteProfile

athlete = AthleteProfile(ftp=250, weight_kg=75)
estimator = SegmentEstimator("segments.db", "your_api_key")

# Get 7-day forecast for a segment
results = estimator.estimate_next_7_days(2969, athlete)

# Export to CSV
with open('forecast.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'datetime', 'estimated_time', 'speed_kmh', 'temp_c', 
        'wind_kmh', 'wind_angle', 'conditions'
    ])
    writer.writeheader()
    
    for r in results:
        writer.writerow({
            'datetime': r['weather']['datetime'],
            'estimated_time': r['estimated_time_formatted'],
            'speed_kmh': f"{r['avg_speed_kmh']:.1f}",
            'temp_c': f"{r['weather']['temp_c']:.1f}",
            'wind_kmh': f"{r['weather']['wind_speed_kmh']:.1f}",
            'wind_angle': f"{r['weather']['wind_angle']:.0f}",
            'conditions': r['weather']['description']
        })

print("✅ Exported to forecast.csv")
```

## Limitations & Accuracy

### What affects accuracy:

✅ **Accurate**:
- Relative comparison between conditions
- Identifying best weather windows
- Understanding power requirements

⚠️ **Moderate accuracy**:
- Absolute time predictions (±10-20%)
- Segments with consistent gradient
- Experienced cyclists who know their FTP

❌ **Less accurate for**:
- Highly variable gradients (power model uses average)
- Technical descents (cornering, braking not modeled)
- Extreme conditions (heat, cold, heavy rain)
- Drafting situations (group rides)
- Beginners without accurate FTP

### Improving accuracy:

1. **Accurate FTP**: Test regularly, use power meter data
2. **Correct weight**: Include gear (helmet, shoes, bottles)
3. **Realistic CdA**: Use your actual riding position
4. **Calibrated power meter**: Zero offset before rides
5. **Compare to actuals**: Adjust parameters based on real results

## Troubleshooting

### "Weather API error" or using mock data

- Check your API key in `config.py`
- Verify your OpenWeatherMap account is active
- Free tier has 1000 calls/day limit

### Estimates seem too fast/slow

- Verify your FTP is accurate (test it!)
- Check your weight includes all gear
- Adjust CdA if you ride more upright/aero
- Compare to your actual power files from similar segments

### No segments found

- Make sure `segments.db` is in the same directory
- Run your `Segment_Pull.py` script first to populate the database
- Check database path in `config.py`

### Best windows all the same time

- Weather might be very stable
- Try a segment in a different location
- Check if weather API is returning data

## Contributing

Suggestions for improvements:

- [ ] Variable power strategy (surge on steep sections)
- [ ] Gradient profile analysis (not just average)
- [ ] Historical weather patterns
- [ ] Multiple weather sources
- [ ] GUI interface
- [ ] Integration with cycling platforms

## License

MIT License - feel free to modify and share!

## Credits

Built using:
- OpenWeatherMap API
- Physics-based cycling power models
- Your cycling segment data

---

**Disclaimer**: These are estimates based on mathematical models. Actual performance varies with fatigue, motivation, pacing strategy, bike handling, and many other factors. Use as a guide, not a guarantee!
