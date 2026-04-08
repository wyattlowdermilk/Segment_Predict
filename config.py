# Segment Time Estimator Configuration

# =============================
# Weather API
# =============================
# Get a free API key at: https://openweathermap.org/api
# Free tier: 1000 calls/day, 5-day forecast in 3-hour intervals
try:
    import streamlit as st
    WEATHER_API_KEY = st.secrets["WEATHER_API_KEY"]
except:
    WEATHER_API_KEY = "YOUR_API_KEY_HERE"

# =============================
# Athlete Profile
# =============================
# Adjust these values to match your fitness and equipment

# Power Duration Curve - Your maximum sustainable power at different durations
# Get these values from your power meter data or from a ramp/step test
# The script will fit a curve through these points to estimate power for any duration

# Your best power outputs (in watts):
POWER_1_MIN = 570  # 1-minute max power
POWER_3_MIN = 400  # 3-minute max power (typically ~85-90% of 1-min)
POWER_8_MIN = 340  # 8-minute max power (typically VO2max/5-min power)
POWER_20_MIN = 315  # 20-minute max power (typically ~95% of FTP)
# Note: FTP is typically 95% of 20-min power, so FTP ≈ 237W in this example

# If you only know your FTP, use these estimates:
# POWER_1_MIN = FTP * 1.20
# POWER_3_MIN = FTP * 1.10
# POWER_8_MIN = FTP * 1.05
# POWER_20_MIN = FTP * 1.00

# Your weight in kilograms
RIDER_WEIGHT_KG = 75

# Your bike weight in kilograms
BIKE_WEIGHT_KG = 8.5

# Coefficient of Drag × Frontal Area (CdA) in m²
# Typical values:
#   - Upright position: 0.40-0.45
#   - Hoods: 0.35-0.40
#   - Drops: 0.30-0.35
#   - Aero position: 0.25-0.30
CDA_M2 = 0.35

# Coefficient of Rolling Resistance (Crr)
# Typical values:
#   - Clincher, good road tires: 0.004-0.005
#   - High-end race tires: 0.003-0.004
#   - Wider gravel tires: 0.006-0.008
CRR = 0.004

# Drivetrain efficiency loss (percentage)
# Typical: 2-4% for well-maintained chain
DRIVETRAIN_LOSS_PERCENT = 4

# =============================
# Database Location
# =============================
# Path to your strava.db file
# Leave as "strava.db" if in same directory
DATABASE_PATH = "strava.db"
