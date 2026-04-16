# Cycling Segment Predictor - Configuration Template
# Copy this file to config.py and fill in your values

# =============================
# Weather API
# =============================
# Get a free API key at: https://openweathermap.org/api
WEATHER_API_KEY = "YOUR_API_KEY_HERE"

# =============================
# Athlete Profile
# =============================
# Your best power outputs (in watts):
POWER_1_MIN = 400    # 1-minute max power
POWER_3_MIN = 340    # 3-minute max power
POWER_8_MIN = 300    # 8-minute max power
POWER_20_MIN = 250   # 20-minute max power

# If you only know your FTP, use these estimates:
# POWER_1_MIN = FTP * 1.20
# POWER_3_MIN = FTP * 1.10
# POWER_8_MIN = FTP * 1.05
# POWER_20_MIN = FTP * 1.00

RIDER_WEIGHT_KG = 75
BIKE_WEIGHT_KG = 8.5

# Aerodynamics (CdA in m²)
# 0.28=Aero, 0.32=Drops, 0.35=Hoods, 0.40=Upright
CDA_M2 = 0.35

# Rolling Resistance
# 0.003=Race tires, 0.004=Good road, 0.006=Gravel
CRR = 0.004

# Drivetrain efficiency loss (percentage)
DRIVETRAIN_LOSS_PERCENT = 4

# =============================
# Database
# =============================
DATABASE_PATH = "segments.db"
