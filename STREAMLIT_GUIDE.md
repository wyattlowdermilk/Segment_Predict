# 🚴 Streamlit App - Quick Start Guide

## Installation

```bash
# Install Streamlit (if not already installed)
pip install streamlit

# You should already have these from the main system
pip install pandas numpy
```

## Running the App

```bash
# From your project directory (where segments.db is located)
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`

## Features

### 🏁 Entrance Speed Modeling (NEW!)

Both tabs now include **entrance speed sliders** that account for acceleration:

- **0 mph** = Standstill start (adds ~5-10 seconds)
- **8-12 mph** = Slow roll (adds ~2-5 seconds)
- **15-20 mph** = Moderate pace (adds ~1-2 seconds)
- **20-25 mph** = Flying start (minimal/no acceleration)

**How it works:**
1. Calculates your steady-state cruise speed based on power
2. If entrance speed < cruise speed → adds acceleration phase
3. Uses numerical integration with realistic physics
4. Shows acceleration time and distance separately

### Tab 1: 📅 Weekly Forecast

**Shows:**
- Next 7 days of afternoon weather (2 PM)
- Temperature, wind speed, wind direction
- Top 3 segments each day where you're **closest to KOM %**

**Controls:**
- Entrance speed slider (applies to all segments)
- Sidebar: Power curve, weight, distance filter

**Use case:** *"Which days this week should I go hunting for PRs?"*

### Tab 2: 🎯 Segment Simulator

**Interactive simulator for any segment with custom conditions:**

**Inputs:**
- Segment selection (dropdown of all segments)
- Entrance speed (0-30 mph)
- Wind condition (10mph tail → 15mph head)
- Temperature (30-100°F)
- Target power (100-600W)

**Outputs:**
- Estimated total time
- Acceleration phase breakdown
- Cruise speed
- Leaderboard position
- % of KOM
- Visual leaderboard with your position highlighted

**Use case:** *"If I hit this climb at 250W with a 10mph tailwind, where would I place?"*

## Configuration

### Sidebar Settings

**Power Curve** (Most Important!)
- Set your 1, 3, 8, 20-minute max power values
- See `POWER_CURVE_GUIDE.md` for help finding these

**Physical Stats**
- Weight (includes you + gear)
- Bike weight

**Equipment**
- CdA (aerodynamics): 0.28=Aero TT, 0.32=Road drops, 0.40=Hoods
- Rolling resistance: 0.003=Race tires, 0.005=Training tires

**Location Filter**
- Max distance from Seattle (0-50 miles)
- Only affects Tab 1 forecast

**Weather API**
- Add your OpenWeatherMap API key for real forecasts
- Without key: uses mock data (stable conditions)

## Understanding the Results

### Acceleration Phase

```
Example: Seminary Hill (892m, 11.5% grade)
├─ Entrance: 15 mph
├─ Cruise: 10.9 mph (power-limited on steep grade)
└─ Result: No acceleration (already above cruise speed)

Example: Flat Sprint (500m, 0% grade)  
├─ Entrance: 0 mph (standstill)
├─ Cruise: 25 mph (high speed on flat)
└─ Acceleration: 120m in 8.2s (adds 8 seconds!)
```

**Key insight:** Entrance speed matters MORE on:
- ✅ Short segments (<1 min)
- ✅ Flat or downhill segments
- ✅ High cruise speeds

Entrance speed matters LESS on:
- ❌ Long climbs (>3 min)
- ❌ Steep gradients (you're slow anyway)
- ❌ Segments where you're power-limited

### % of KOM Interpretation

| % of KOM | Meaning | Advice |
|----------|---------|--------|
| 90-100% | Elite level | You could win! |
| 100-110% | Very competitive | Top 10 possible |
| 110-120% | Strong rider | Respectable time |
| 120-140% | Average | Good training effort |
| 140%+ | Learning | Build fitness |

### Power Warnings

The app shows warnings if your target power is:
- **10%+ above natural sustainable** → "This is unsustainable"
- **10%+ below natural sustainable** → "This is easier pace"
- **Within 10%** → "This matches your sustainable power"

## Tips for Best Results

### 1. Set Accurate Power Curve
```python
# BAD - Using same value
POWER_1_MIN = 250
POWER_3_MIN = 250  # Wrong!
POWER_8_MIN = 250  # Wrong!

# GOOD - Realistic progression
POWER_1_MIN = 400  # Sprint power
POWER_3_MIN = 340  # Hard effort
POWER_8_MIN = 300  # VO2max
POWER_20_MIN = 250 # FTP test
```

### 2. Choose Entrance Speed Realistically

**Ask yourself:**
- Is there a traffic light before the segment start?
- Do I usually hit this segment mid-ride with momentum?
- Is this a dedicated PR attempt or casual riding?

**Typical scenarios:**
- **Segment hunting**: 20-25 mph (you plan your approach)
- **Group ride**: 18-22 mph (maintaining group pace)
- **Commuting**: 12-18 mph (casual)
- **From red light**: 0-8 mph (stopped)

### 3. Use Tab 1 for Planning

Sunday morning routine:
1. Open app
2. Check next 7 days
3. Note which days have best conditions
4. Plan your week around those days
5. Show up ready to crush segments!

### 4. Use Tab 2 for Strategy

Before a PR attempt:
1. Select your target segment
2. Set realistic entrance speed
3. Try different power targets
4. Find the power needed for top 10
5. Train at that power!

## Troubleshooting

### "No segments found"
- Check that `segments.db` is in the same directory
- Increase distance filter in sidebar
- Run `python Segment_Pull.py` to add segments

### "No leaderboard data"
- Run `python scraperSel.py` to scrape leaderboards
- Some segments may have no public leaderboard

### App is slow
- Reduce max distance (fewer segments to analyze)
- Tab 1 analyzes 7 days × distance filter segments
- Tab 2 is fast (single segment calculation)

### Weather data is fake
- Add your OpenWeatherMap API key in sidebar
- Get free key: https://openweathermap.org/api
- Without key, uses mock data (stable 60°F, 5mph wind)

### Estimates seem off
- Verify your power curve values
- Check weight is correct (you + bottles + gear)
- Adjust CdA if you ride more upright/aero
- Compare entrance speed to how you actually ride

## Advanced Usage

### Compare Different Strategies

Use Tab 2 to A/B test:

**Strategy A: High power, standstill**
- Entrance: 0 mph
- Power: 400W
- Result: Fast cruise but loses time in acceleration

**Strategy B: Moderate power, flying start**
- Entrance: 22 mph
- Power: 300W
- Result: Less acceleration penalty, more sustainable

### Find Your Best Segments

Tab 1 automatically finds segments where you're closest to KOM.

**Why this matters:**
- Shows which segments suit your physiology
- Power curve strong in 1-3 min? You'll see short climbs
- High FTP? You'll see longer efforts
- Helps you pick winnable targets!

### Weather Strategy

Tab 1 shows which days have the best conditions.

**Look for:**
- 🌡️ **Cool temps** (50-65°F) = better air density
- 💨 **Low wind** or **tailwind** = faster times
- ☀️ **Clear skies** = no wet roads (lower rolling resistance)

**Avoid:**
- 🌧️ **Rain** = +20% rolling resistance
- 🌡️ **Hot days** (80°F+) = reduced power output
- 💨 **Headwinds** = significantly slower

## Keyboard Shortcuts

Streamlit has built-in shortcuts:

- `Ctrl + R` = Rerun app
- `Ctrl + K` = Clear cache
- `?` = Show keyboard shortcuts

## Deploying Online

Want to share with friends?

```bash
# 1. Create account at streamlit.io
# 2. Push code to GitHub
# 3. Connect repo in Streamlit Cloud
# 4. Deploy (free!)

# Your app will be live at:
# https://your-username-strava-predictor.streamlit.app
```

## Next Steps

1. ✅ **Configure your power curve** (sidebar)
2. ✅ **Add weather API key** (sidebar)
3. ✅ **Test Tab 2** with a segment you know well
4. ✅ **Validate** against your actual time
5. ✅ **Use Tab 1** to plan your week
6. ✅ **Go crush some segments!** 🚀

## Questions?

The app is fully self-contained and commented. Check:
- Inline comments in `app.py`
- Main README.md for physics explanations
- POWER_CURVE_GUIDE.md for power setup help

---

**Happy segment hunting! 🚴💨**
