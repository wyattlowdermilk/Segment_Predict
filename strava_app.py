"""
Strava Segment Time Predictor - Streamlit App
Fixed version with entrance speed modeling and correct power calculations

Run with: streamlit run strava_app.py
"""

import streamlit as st

# Page config MUST be THE FIRST Streamlit command
st.set_page_config(
    page_title="🚴 Strava Segment Predictor",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Now import everything else AFTER st.set_page_config
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import math
from typing import Tuple

# Import configuration defaults
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
    )

    CONFIG_LOADED = True
except ImportError:
    # Defaults if config.py not found
    WEATHER_API_KEY = "YOUR_API_KEY_HERE"
    POWER_1_MIN = 400
    POWER_3_MIN = 340
    POWER_8_MIN = 300
    POWER_20_MIN = 250
    RIDER_WEIGHT_KG = 75
    BIKE_WEIGHT_KG = 8
    CDA_M2 = 0.32
    CRR = 0.004
    CONFIG_LOADED = False

# Import segment estimator after config
from segment_time_estimator import (
    SegmentEstimator,
    AthleteProfile,
    PowerModel,
    format_time,
    WeatherForecast,
)

# Custom CSS
st.markdown(
    """
<style>
    .segment-card {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #f0f2f6;
        margin-bottom: 0.5rem;
    }
    .metric-row {
        display: flex;
        gap: 1rem;
    }
</style>
""",
    unsafe_allow_html=True,
)


# =============================
# Helper Functions
# =============================


def mph_to_ms(mph):
    """Convert mph to m/s"""
    return mph * 0.44704


def ms_to_mph(ms):
    """Convert m/s to mph"""
    return ms / 0.44704


def wind_direction_to_cardinal(degrees):
    """
    Convert wind direction in degrees to cardinal direction with arrow.

    Returns: string like "N ↓" or "SW ↙"
    """
    # Normalize degrees to 0-360
    degrees = degrees % 360

    # Define cardinal directions with arrows
    # Wind direction indicates where wind is coming FROM
    # Arrow shows where wind is blowing TO
    directions = [
        (0, "N", "↓"),  # North wind blows south
        (45, "NE", "↙"),  # Northeast wind blows southwest
        (90, "E", "←"),  # East wind blows west
        (135, "SE", "↖"),  # Southeast wind blows northwest
        (180, "S", "↑"),  # South wind blows north
        (225, "SW", "↗"),  # Southwest wind blows northeast
        (270, "W", "→"),  # West wind blows east
        (315, "NW", "↘"),  # Northwest wind blows southeast
        (360, "N", "↓"),  # North again
    ]

    # Find closest direction
    min_diff = 360
    best_dir = "N"
    best_arrow = "↓"

    for deg, cardinal, arrow in directions:
        diff = abs(degrees - deg)
        if diff < min_diff:
            min_diff = diff
            best_dir = cardinal
            best_arrow = arrow

    return f"{best_dir} {best_arrow}"


def calculate_acceleration_time_and_distance(
    starting_speed_ms: float,
    target_speed_ms: float,
    athlete: AthleteProfile,
    grade_percent: float,
    air_density: float,
    wind_speed_ms: float = 0,
    wind_angle_deg: float = 0,
) -> tuple:
    """
    Calculate time and distance needed to accelerate from starting speed to target speed.

    Returns: (time_seconds, distance_meters)
    """
    if starting_speed_ms >= target_speed_ms:
        return 0, 0

    # Use numerical integration with small time steps
    dt = 0.1  # 0.1 second time steps
    current_speed = starting_speed_ms
    total_time = 0
    total_distance = 0
    max_iterations = 500  # Safety limit (50 seconds)

    # Use high power for acceleration (assume max 1-min power)
    accel_power = athlete.sustainable_power(1.0) * (1 - athlete.drivetrain_loss)

    for _ in range(max_iterations):
        if current_speed >= target_speed_ms:
            break

        # Power required to maintain current speed
        power_required = PowerModel.power_required(
            current_speed,
            grade_percent,
            athlete.total_weight_kg,
            athlete.cda,
            athlete.crr,
            air_density,
            wind_speed_ms,
            wind_angle_deg,
        )

        # Excess power available for acceleration
        excess_power = accel_power - power_required

        if excess_power <= 0:
            break

        # Force = Power / velocity
        force = excess_power / max(current_speed, 1.0)

        # Acceleration = Force / mass
        acceleration = force / athlete.total_weight_kg

        # Update speed and position
        current_speed += acceleration * dt
        total_distance += current_speed * dt
        total_time += dt

    return total_time, total_distance


def simulate_segment_dynamic(
    distance_m: float,
    avg_grade_percent: float,
    entrance_speed_ms: float,
    athlete_total_weight_kg: float,
    sustainable_power_watts: float,
    cda: float,
    crr: float,
    air_density: float,
    wind_speed_ms: float = 0,
    wind_angle_deg: float = 0,
    dt: float = 0.1,  # Time step in seconds
) -> Tuple[float, list, list]:
    """
    Simulate segment with dynamic speed changes.

    Returns:
        total_time: Time to complete segment (seconds)
        time_profile: List of time points
        speed_profile: List of speeds at each time point
    """
    GRAVITY = 9.81

    # Initial conditions
    current_speed = entrance_speed_ms
    distance_covered = 0
    elapsed_time = 0

    time_profile = [0]
    speed_profile = [current_speed]

    # Safety limits
    max_iterations = 10000  # Prevent infinite loops
    iteration = 0

    while distance_covered < distance_m and iteration < max_iterations:
        iteration += 1

        # Calculate grade (assume constant for now - could vary with position)
        grade_rad = math.atan(avg_grade_percent / 100)

        # Wind component
        wind_angle_rad = math.radians(wind_angle_deg)
        effective_wind = wind_speed_ms * math.cos(wind_angle_rad)
        apparent_speed = current_speed + effective_wind

        # Force components (in Newtons)
        # 1. Propulsive force from power
        if current_speed > 0.1:  # Avoid division by zero
            force_propulsion = sustainable_power_watts / current_speed
        else:
            # At very low speeds, use high force to get moving
            force_propulsion = sustainable_power_watts / 0.1

        # 2. Gravity force (negative when climbing)
        force_gravity = -athlete_total_weight_kg * GRAVITY * math.sin(grade_rad)

        # 3. Air resistance force (always negative)
        force_air = -0.5 * cda * air_density * (apparent_speed**2)

        # 4. Rolling resistance force (always negative)
        force_rolling = -athlete_total_weight_kg * GRAVITY * math.cos(grade_rad) * crr

        # Net force
        net_force = force_propulsion + force_gravity + force_air + force_rolling

        # Acceleration (F = ma)
        acceleration = net_force / athlete_total_weight_kg

        # Update speed (v = v0 + a*dt)
        new_speed = current_speed + acceleration * dt

        # Prevent negative speeds (rider stops if can't maintain speed uphill)
        if new_speed < 0.1:
            new_speed = 0.1  # Minimum speed to keep moving

        # Prevent unrealistic speeds
        new_speed = min(new_speed, 25.0)  # Max ~90 km/h

        # Update position (use average speed over time step)
        avg_speed_step = (current_speed + new_speed) / 2
        distance_step = avg_speed_step * dt

        # Update state
        current_speed = new_speed
        distance_covered += distance_step
        elapsed_time += dt

        # Record profile
        time_profile.append(elapsed_time)
        speed_profile.append(current_speed)

    # Handle case where rider couldn't complete segment
    if iteration >= max_iterations:
        # Rider stalled out - return very long time
        return 9999, time_profile, speed_profile

    return elapsed_time, time_profile, speed_profile


def estimate_time_with_entrance_speed(
    segment_dict: dict,
    athlete,
    entrance_speed_mph: float,
    weather_conditions: dict,
    target_power: float = None,
) -> dict:
    """
    Estimate segment time using DYNAMIC PHYSICS SIMULATION.

    Models realistic acceleration/deceleration based on instantaneous forces:
    - Propulsion force from power output
    - Gravity force from grade
    - Air resistance (drag)
    - Rolling resistance

    Speed changes continuously throughout segment based on net force.
    """
    GRAVITY = 9.81

    distance_m = segment_dict["distance_m"]
    avg_grade = segment_dict["avg_grade"]
    entrance_speed_ms = entrance_speed_mph * 0.44704  # mph to m/s

    # Air density
    elevation_m = (
        segment_dict.get("elevation_high_m", 0) + segment_dict.get("elevation_low_m", 0)
    ) / 2
    air_density = PowerModel.air_density(
        weather_conditions["temp_c"], weather_conditions["pressure_hpa"], elevation_m
    )

    # Estimate duration for power curve (initial guess)
    initial_time_minutes = (distance_m / 1000) / 20 * 60

    # Determine sustainable power
    if target_power:
        sustainable_power = target_power
    else:
        sustainable_power = athlete.sustainable_power(initial_time_minutes)

    power_at_wheel = sustainable_power * (1 - athlete.drivetrain_loss)

    # DYNAMIC SIMULATION - model speed changes over time
    dt = 0.1  # Time step (seconds)
    current_speed = entrance_speed_ms
    distance_covered = 0
    elapsed_time = 0

    speed_profile = [current_speed]
    max_iterations = 10000
    iteration = 0

    grade_rad = math.atan(avg_grade / 100)
    wind_speed_ms = weather_conditions.get("wind_speed_ms", 0)
    wind_angle_deg = weather_conditions.get("wind_angle", 0)
    wind_angle_rad = math.radians(wind_angle_deg)

    while distance_covered < distance_m and iteration < max_iterations:
        iteration += 1

        # Wind component
        effective_wind = wind_speed_ms * math.cos(wind_angle_rad)
        apparent_speed = current_speed + effective_wind

        # FORCE CALCULATIONS (Newtons)
        # 1. Propulsive force from rider's power
        if current_speed > 0.1:
            force_propulsion = power_at_wheel / current_speed
        else:
            force_propulsion = power_at_wheel / 0.1  # High force at low speed

        # 2. Gravity force (negative when climbing)
        force_gravity = -athlete.total_weight_kg * GRAVITY * math.sin(grade_rad)

        # 3. Air resistance (always opposes motion)
        force_air = -0.5 * athlete.cda * air_density * (apparent_speed**2)

        # 4. Rolling resistance
        force_rolling = (
            -athlete.total_weight_kg * GRAVITY * math.cos(grade_rad) * athlete.crr
        )

        # Net force determines acceleration
        net_force = force_propulsion + force_gravity + force_air + force_rolling
        acceleration = net_force / athlete.total_weight_kg

        # Update speed: v = v0 + a*dt
        new_speed = current_speed + acceleration * dt
        new_speed = max(0.1, min(25.0, new_speed))  # Keep in realistic range

        # Update position using average speed
        avg_speed_step = (current_speed + new_speed) / 2
        distance_step = avg_speed_step * dt

        current_speed = new_speed
        distance_covered += distance_step
        elapsed_time += dt

        speed_profile.append(current_speed)

    # Handle stall (couldn't complete segment)
    if iteration >= max_iterations:
        total_time = 9999
    else:
        total_time = elapsed_time

    # Refine power estimate based on actual duration
    refined_minutes = total_time / 60
    if not target_power and total_time < 9999:
        refined_power = athlete.sustainable_power(refined_minutes)

        # Re-run simulation with refined power (one iteration for accuracy)
        power_at_wheel_refined = refined_power * (1 - athlete.drivetrain_loss)

        current_speed = entrance_speed_ms
        distance_covered = 0
        elapsed_time = 0
        speed_profile = [current_speed]
        iteration = 0

        while distance_covered < distance_m and iteration < max_iterations:
            iteration += 1

            effective_wind = wind_speed_ms * math.cos(wind_angle_rad)
            apparent_speed = current_speed + effective_wind

            if current_speed > 0.1:
                force_propulsion = power_at_wheel_refined / current_speed
            else:
                force_propulsion = power_at_wheel_refined / 0.1

            force_gravity = -athlete.total_weight_kg * GRAVITY * math.sin(grade_rad)
            force_air = -0.5 * athlete.cda * air_density * (apparent_speed**2)
            force_rolling = (
                -athlete.total_weight_kg * GRAVITY * math.cos(grade_rad) * athlete.crr
            )

            net_force = force_propulsion + force_gravity + force_air + force_rolling
            acceleration = net_force / athlete.total_weight_kg

            new_speed = current_speed + acceleration * dt
            new_speed = max(0.1, min(25.0, new_speed))

            avg_speed_step = (current_speed + new_speed) / 2
            distance_step = avg_speed_step * dt

            current_speed = new_speed
            distance_covered += distance_step
            elapsed_time += dt

            speed_profile.append(current_speed)

        total_time = elapsed_time if iteration < max_iterations else 9999
        sustainable_power = refined_power
        power_at_wheel = power_at_wheel_refined

    avg_speed_ms = distance_m / total_time if total_time > 0 else 0

    return {
        "total_time": total_time,
        "accel_time": 0,
        "cruise_time": total_time,
        "accel_distance": 0,
        "cruise_speed_mph": avg_speed_ms / 0.44704,
        "sustainable_power": sustainable_power,
        "power_at_wheel": power_at_wheel,
        "speed_profile": {
            "initial_mph": speed_profile[0] * 2.237,
            "final_mph": speed_profile[-1] * 2.237,
            "min_mph": min(speed_profile) * 2.237,
            "max_mph": max(speed_profile) * 2.237,
        },
    }


def calculate_segment_bearing(
    start_lat: float, start_lng: float, end_lat: float, end_lng: float
) -> float:
    """Calculate the bearing (direction) of a segment from start to end in degrees (0-360)"""
    lat1 = math.radians(start_lat)
    lat2 = math.radians(end_lat)
    lon_diff = math.radians(end_lng - start_lng)

    x = math.sin(lon_diff) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
        lon_diff
    )

    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def calculate_wind_angle(segment_bearing: float, wind_direction: float) -> tuple:
    """
    Calculate the angle between segment direction and wind direction.

    Returns: (wind_angle, wind_effect_type)
        wind_angle: 0° = headwind, 90° = crosswind, 180° = tailwind
        wind_effect_type: "headwind", "tailwind", "crosswind", "cross-headwind", "cross-tailwind"
    """
    # Calculate relative angle
    angle = abs(segment_bearing - wind_direction)
    if angle > 180:
        angle = 360 - angle

    # Determine wind effect type
    if angle < 22.5:
        effect = "headwind"
        icon = "🔴"
    elif angle < 67.5:
        effect = "cross-headwind"
        icon = "🟠"
    elif angle < 112.5:
        effect = "crosswind"
        icon = "⚪"
    elif angle < 157.5:
        effect = "cross-tailwind"
        icon = "🟢"
    else:
        effect = "tailwind"
        icon = "🟢"

    return angle, effect, icon


def find_closest_to_kom_segments(
    segments_df: pd.DataFrame,
    athlete: AthleteProfile,
    entrance_speed_mph: float,
    weather_conditions: dict,
    db_path: str,
    top_n: int = 3,
    gradient_range: tuple = (-5.0, 20.0),
    time_range: tuple = (10, 600),
):
    """Find segments where your time is closest to KOM as a percentage"""
    results = []

    # Apply gradient filter
    min_gradient, max_gradient = gradient_range
    segments_df = segments_df[
        (segments_df["avg_grade"] >= min_gradient)
        & (segments_df["avg_grade"] <= max_gradient)
    ].copy()

    conn = sqlite3.connect(db_path)

    for _, seg in segments_df.iterrows():
        # Get KOM time
        cur = conn.cursor()
        cur.execute(
            """
            SELECT MIN(time_seconds) as kom_time
            FROM leaderboard
            WHERE segment_id = ?
        """,
            (seg["id"],),
        )

        row = cur.fetchone()
        if not row or not row[0]:
            continue

        kom_time = row[0]

        # Calculate segment bearing for wind effect
        segment_bearing = calculate_segment_bearing(
            seg["start_lat"], seg["start_lng"], seg["end_lat"], seg["end_lng"]
        )

        # Calculate proper wind angle relative to segment direction
        wind_direction = weather_conditions.get("wind_angle", 0)
        wind_angle, wind_effect, wind_icon = calculate_wind_angle(
            segment_bearing, wind_direction
        )

        # Update weather conditions with correct wind angle
        segment_weather = weather_conditions.copy()
        segment_weather["wind_angle"] = wind_angle

        # Estimate your time
        segment_dict = {
            "distance_m": seg["distance_m"],
            "avg_grade": seg["avg_grade"],
            "elevation_high_m": seg.get("elevation_gain_m", 0),
            "elevation_low_m": 0,
        }

        try:
            result = estimate_time_with_entrance_speed(
                segment_dict, athlete, entrance_speed_mph, segment_weather
            )

            your_time = result["total_time"]
            pct_of_kom = (your_time / kom_time) * 100

            # Apply time filter
            min_time, max_time = time_range
            if min_time <= your_time <= max_time:
                results.append(
                    {
                        "segment_id": seg["id"],
                        "name": seg["name"],
                        "distance_km": seg["distance_m"] / 1000,
                        "elevation_gain_m": seg["elevation_gain_m"],
                        "avg_grade": seg["avg_grade"],
                        "kom_time": kom_time,
                        "your_time": your_time,
                        "pct_of_kom": pct_of_kom,
                        "time_behind": your_time - kom_time,
                        "power": result["sustainable_power"],
                        "city": seg.get("city", ""),
                        "state": seg.get("state", ""),
                        "debug_weight": athlete.total_weight_kg,
                        "wind_effect": wind_effect,
                        "wind_icon": wind_icon,
                    }
                )
        except Exception as e:
            st.error(f"🔴 ERROR: Segment {seg['id']} ({seg['name']}): {str(e)}")
            import traceback

            st.code(traceback.format_exc())
            continue

    conn.close()

    # Sort by percentage (closest to 100% = best chance for PR)
    results_sorted = sorted(results, key=lambda x: abs(100 - x["pct_of_kom"]))

    return results_sorted[:top_n]


# =======================
# Region definitions
# =======================
# To add a new region, just append an entry here.
# Every segment in the DB is assigned to whichever region center is closest.
REGIONS = {
    "Seattle, WA": {"lat": 47.6062, "lon": -122.3321},
    "Orcas Island, WA": {"lat": 48.6543, "lon": -122.9060},
    "Boulder, CO": {"lat": 40.0150, "lon": -105.2705},
    "Salt Lake City, UT": {"lat": 40.7608, "lon": -111.8910},
    "Weddington, NC": {"lat": 34.9901, "lon": -80.7812},
}


def _haversine(lat1, lon1, lat2, lon2):
    """Distance in miles between two lat/lon points."""
    R = 3959
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_region_segment_counts(db_path: str) -> dict:
    """
    Count how many DB segments belong to each region (nearest-center assignment).
    Returns dict like {"Seattle, WA": 142, "Orcas Island, WA": 38}
    """
    conn = sqlite3.connect(db_path)
    df = pd.read_sql(
        "SELECT start_lat, start_lng FROM segments WHERE start_lat IS NOT NULL",
        conn,
    )
    conn.close()

    counts = {name: 0 for name in REGIONS}
    for _, row in df.iterrows():
        closest = min(
            REGIONS.items(),
            key=lambda r: _haversine(
                row["start_lat"], row["start_lng"], r[1]["lat"], r[1]["lon"]
            ),
        )
        counts[closest[0]] += 1
    return counts


def get_segments_for_region(
    db_path: str, region_name: str, max_distance_miles: float
) -> pd.DataFrame:
    """
    Get all segments assigned to a region within max_distance_miles of its center.
    If region_name is None (All Locations), returns all segments with distance
    from overall centroid.
    """
    conn = sqlite3.connect(db_path)
    df = pd.read_sql(
        """
        SELECT id, name, distance_m, elevation_gain_m, avg_grade,
               start_lat, start_lng, end_lat, end_lng, city, state
        FROM segments
        WHERE start_lat IS NOT NULL AND start_lng IS NOT NULL
          AND end_lat IS NOT NULL AND end_lng IS NOT NULL
        """,
        conn,
    )
    conn.close()

    if len(df) == 0:
        return df

    if region_name and region_name in REGIONS:
        center = REGIONS[region_name]

        # Assign each segment to its nearest region, keep only this region's
        df["_assigned_region"] = df.apply(
            lambda row: min(
                REGIONS.items(),
                key=lambda r: _haversine(
                    row["start_lat"], row["start_lng"], r[1]["lat"], r[1]["lon"]
                ),
            )[0],
            axis=1,
        )
        df = df[df["_assigned_region"] == region_name].drop(
            columns=["_assigned_region"]
        )

        # Distance from region center
        df["distance_from_center"] = df.apply(
            lambda row: _haversine(
                center["lat"], center["lon"], row["start_lat"], row["start_lng"]
            ),
            axis=1,
        )
    else:
        # All Locations — use overall centroid
        center_lat = df["start_lat"].mean()
        center_lon = df["start_lng"].mean()
        df["distance_from_center"] = df.apply(
            lambda row: _haversine(
                center_lat, center_lon, row["start_lat"], row["start_lng"]
            ),
            axis=1,
        )

    df = df[df["distance_from_center"] <= max_distance_miles]
    return df


# =============================
# Main Application
# =============================


def main():
    """Main application entry point"""

    # Constants
    DB_PATH = "strava.db"

    # =============================
    # Location selector (drives everything else)
    # =============================
    region_counts = get_region_segment_counts(DB_PATH)
    total_segments = sum(region_counts.values())

    if total_segments == 0:
        st.error("No segments with location data found in database.")
        return

    # Build dropdown options: "Region Name (N segments)" -> region key or None
    # Seattle first as default
    region_options = {}
    for name, count in region_counts.items():
        label = f"{name} ({count} segments)"
        region_options[label] = name
    region_options["All Locations"] = None

    # Sidebar settings
    st.sidebar.title("⚙️ Athlete Settings")
    # Compact sidebar and main content spacing
    st.markdown(
        """
    <style>
        /* Compact sidebar */
        .stExpander {margin-bottom: 0.25rem !important;}
        section[data-testid="stSidebar"] .element-container {margin-bottom: 0.25rem;}
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {margin-bottom: 0.25rem;}
        section[data-testid="stSidebar"] .stSlider {margin-bottom: 0.5rem;}
        
        /* Reduce header spacing */
        .main .block-container {padding-top: 1rem; padding-bottom: 0rem;}
        h1, h2, h3 {margin-top: 0.25rem; margin-bottom: 0.25rem;}
        
        /* Compact main content elements */
        .main .element-container {margin-bottom: 0.1rem;}
        .main [data-testid="stMarkdownContainer"] p {margin-bottom: 0.2rem;}
        .main [data-testid="stMetric"] {padding: 0.3rem 0;}
        .main hr {margin: 0.3rem 0;}
        .main [data-testid="stSubheader"] {margin-top: 0.25rem; margin-bottom: 0.25rem;}
        
        /* Smaller text throughout */
        .main [data-testid="stMarkdownContainer"] {font-size: 0.9rem;}
        .main .stCaption {font-size: 0.78rem;}
        
        /* Make sidebar scrollable if content is too tall */
        section[data-testid="stSidebar"] > div {max-height: 100vh; overflow-y: auto;}
    </style>
    """,
        unsafe_allow_html=True,
    )

    # ---- Location selector in sidebar ----
    with st.sidebar.expander("📍 Location", expanded=True):
        selected_label = st.selectbox("Region", list(region_options.keys()))
        selected_region = region_options[selected_label]

        if selected_region and selected_region in REGIONS:
            center_lat = REGIONS[selected_region]["lat"]
            center_lon = REGIONS[selected_region]["lon"]
            location_name = selected_region.split(",")[
                0
            ]  # "Seattle" from "Seattle, WA"
        else:
            # "All Locations" — compute overall centroid
            conn = sqlite3.connect(DB_PATH)
            center = pd.read_sql(
                "SELECT AVG(start_lat) as lat, AVG(start_lng) as lng FROM segments WHERE start_lat IS NOT NULL",
                conn,
            )
            conn.close()
            center_lat = center["lat"].iloc[0]
            center_lon = center["lng"].iloc[0]
            location_name = "all regions"

        st.caption(f"📌 {center_lat:.3f}, {center_lon:.3f}")

    with st.sidebar.expander("📏 Units", expanded=True):
        use_metric = st.checkbox("Use Metric (km, km/h, °C)", value=False)
        if use_metric:
            st.caption("🌍 Metric units enabled")
        else:
            st.caption("🇺🇸 Imperial units (mi, mph, °F)")

    with st.sidebar.expander("💪 Power Curve", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            power_1 = st.number_input("1-min (W)", value=POWER_1_MIN, step=10)
            power_8 = st.number_input("8-min (W)", value=POWER_8_MIN, step=10)
        with col2:
            power_3 = st.number_input("3-min (W)", value=POWER_3_MIN, step=10)
            power_20 = st.number_input("20-min (W)", value=POWER_20_MIN, step=10)

    with st.sidebar.expander("🏋️ Physical Stats", expanded=True):
        weight_kg = st.slider("Weight (kg)", 50, 120, int(RIDER_WEIGHT_KG))
        bike_weight = st.slider("Bike Weight (kg)", 6, 15, int(BIKE_WEIGHT_KG))

    with st.sidebar.expander("🚴 Equipment", expanded=False):
        cda = st.slider(
            "CdA (m²)",
            0.25,
            0.45,
            float(CDA_M2),
            0.01,
            help="0.28=Aero, 0.32=Drops, 0.40=Hoods",
        )
        crr = st.slider(
            "Rolling Resistance",
            0.003,
            0.008,
            float(CRR),
            0.0001,
            format="%.4f",
            help="0.003=Race tires, 0.005=Training tires",
        )

    with st.sidebar.expander("🏁 Entrance Speed", expanded=False):
        if use_metric:
            entrance_speed_kmh = st.slider(
                "Segment Entry Speed (km/h)",
                min_value=0,
                max_value=48,
                value=32,
                step=3,
                help="Speed you'll have when starting each segment",
            )
            entrance_speed = (
                entrance_speed_kmh * 0.621371
            )  # Convert to mph for internal use
        else:
            entrance_speed = st.slider(
                "Segment Entry Speed (mph)",
                min_value=0,
                max_value=30,
                value=20,
                step=2,
                help="Speed you'll have when starting each segment",
            )

    with st.sidebar.expander("🔍 Segment Filters", expanded=False):
        # Distance filter — label reflects selected location
        if use_metric:
            max_distance_km = st.slider(
                f"Max distance from {location_name} (km)", 0, 40, 25, 5
            )
            max_distance = (
                max_distance_km * 0.621371
            )  # Convert to miles for internal use
        else:
            max_distance = st.slider(
                f"Max distance from {location_name} (miles)", 0, 25, 15, 5
            )

        st.divider()

        # Gradient filter
        gradient_range = st.slider(
            "Average gradient (%)",
            min_value=-5.0,
            max_value=20.0,
            value=(-5.0, 20.0),
            step=0.5,
            help="Filter segments by average gradient",
        )

        # Time filter
        time_range = st.slider(
            "Estimated time (seconds)",
            min_value=10,
            max_value=1800,
            value=(10, 1800),
            step=10,
            help="Filter segments by your estimated completion time",
        )

    with st.sidebar.expander("🌤️ Weather API", expanded=False):
        api_key = st.text_input(
            "OpenWeatherMap API Key",
            value=WEATHER_API_KEY,
            type="password",
            help="Get free key at openweathermap.org/api",
        )

    # Create athlete profile
    power_curve = {1: power_1, 3: power_3, 8: power_8, 20: power_20}
    athlete = AthleteProfile(
        power_curve=power_curve,
        weight_kg=weight_kg,
        bike_weight_kg=bike_weight,
        cda=cda,
        crr=crr,
    )

    # Main content - compact header
    ftp = athlete.get_ftp()
    st.caption(
        f"⚡ {power_1}W (1min) → {power_20}W (20min) | FTP≈{ftp:.0f}W | {weight_kg}kg ({ftp/weight_kg:.2f} W/kg)"
    )

    # Tabs
    tab1, tab2 = st.tabs(["📅 KOM Weather Report", "🎯 Segment Simulator"])

    # =============================
    # TAB 1: Weekly Forecast
    # =============================
    with tab1:
        st.subheader("KOM Weather Report")

        with st.spinner("Loading segments..."):
            try:
                segments_df = get_segments_for_region(
                    DB_PATH, selected_region, max_distance
                )
                if use_metric:
                    dist_label = f"{max_distance / 0.621371:.0f} km"
                else:
                    dist_label = f"{max_distance:.0f} miles"
                st.success(
                    f"Found {len(segments_df)} segments within {dist_label} of {location_name}"
                )
            except Exception as e:
                st.error(f"Error loading segments: {e}")
                return

        if len(segments_df) == 0:
            st.warning("No segments found. Increase distance or check database.")
            return

        weather_api = WeatherForecast(api_key)

        # Fetch forecast once for the selected location
        forecasts = weather_api.get_forecast(center_lat, center_lon)

        # First row: Today + next 3 days
        st.subheader("📅 This Week")
        day_cols_1 = st.columns(4)

        for day_offset in range(4):
            with day_cols_1[day_offset]:
                target_date = datetime.now() + timedelta(days=day_offset)
                afternoon_time = target_date.replace(
                    hour=14, minute=0, second=0, microsecond=0
                )

                # Day header
                if day_offset == 0:
                    st.markdown(f"**Today**")
                elif day_offset == 1:
                    st.markdown(f"**Tomorrow**")
                else:
                    st.markdown(f"**{target_date.strftime('%a')}**")

                st.caption(target_date.strftime("%b %d"))

                # Weather — use the single forecast already fetched for this location
                closest_forecast = min(
                    forecasts,
                    key=lambda f: abs((f["datetime"] - afternoon_time).total_seconds()),
                )

                temp_f = closest_forecast["temp_c"] * 9 / 5 + 32
                wind_mph = closest_forecast["wind_speed_ms"] * 2.237
                wind_cardinal = wind_direction_to_cardinal(closest_forecast["wind_deg"])

                if use_metric:
                    st.caption(
                        f"🌡️ {closest_forecast['temp_c']:.0f}°C • 💨 {closest_forecast['wind_speed_ms'] * 3.6:.0f} km/h {wind_cardinal}"
                    )
                else:
                    st.caption(
                        f"🌡️ {temp_f:.0f}°F • 💨 {wind_mph:.0f} mph {wind_cardinal}"
                    )

                st.caption(f"{closest_forecast['description'].title()}")

                # Find top segments for this day
                weather_conditions = {
                    "temp_c": closest_forecast["temp_c"],
                    "pressure_hpa": closest_forecast["pressure_hpa"],
                    "wind_speed_ms": closest_forecast["wind_speed_ms"],
                    "wind_angle": closest_forecast["wind_deg"],  # Wind direction
                }

                with st.spinner(""):
                    top_segments = find_closest_to_kom_segments(
                        segments_df,
                        athlete,
                        entrance_speed,
                        weather_conditions,
                        DB_PATH,
                        top_n=3,
                        gradient_range=gradient_range,
                        time_range=time_range,
                    )

                st.markdown("---")

                # Display top 3 segments compactly
                if top_segments:
                    for i, seg in enumerate(top_segments[:3], 1):
                        name_display = (
                            seg["name"]
                            if len(seg["name"]) <= 35
                            else seg["name"][:32] + "..."
                        )
                        wind_icon = seg.get("wind_icon", "")
                        st.markdown(f"**{i}. {name_display}** {wind_icon}")
                        st.caption(
                            f"ID: {seg['segment_id']} • {seg.get('wind_effect', 'unknown wind')}"
                        )

                        if use_metric:
                            st.caption(
                                f"📏 {seg['distance_km']:.1f}km • ⛰️ {seg['elevation_gain_m']:.0f}m"
                            )
                        else:
                            distance_mi = seg["distance_km"] * 0.621371
                            elevation_ft = seg["elevation_gain_m"] * 3.28084
                            st.caption(
                                f"📏 {distance_mi:.1f}mi • ⛰️ {elevation_ft:.0f}ft"
                            )

                        st.caption(
                            f"📈 {seg['avg_grade']:.1f}% • ⚡ {seg['power']:.0f}W"
                        )

                        your_time_str = format_time(seg["your_time"])
                        kom_time_str = format_time(seg["kom_time"])

                        if seg["time_behind"] < 0:
                            st.success(
                                f"⏱️ {your_time_str} (🟢 {abs(seg['time_behind']):.0f}s faster!)"
                            )
                        elif seg["time_behind"] < 10:
                            st.success(
                                f"⏱️ {your_time_str} (🟡 {seg['time_behind']:.0f}s slower)"
                            )
                        else:
                            st.info(
                                f"⏱️ {your_time_str} ({seg['time_behind']:.0f}s slower)"
                            )

                        st.caption(f"🏆 KOM: {kom_time_str} • {seg['pct_of_kom']:.0f}%")

                        if i < 3:
                            st.markdown("")
                else:
                    st.warning("No matches")

        # Second row: Next 3 days
        st.markdown("---")
        st.subheader("📅 Next Weekend")
        day_cols_2 = st.columns(3)

        for day_offset in range(4, 7):
            with day_cols_2[day_offset - 4]:
                target_date = datetime.now() + timedelta(days=day_offset)
                afternoon_time = target_date.replace(
                    hour=14, minute=0, second=0, microsecond=0
                )

                # Day header
                if day_offset == 0:
                    st.markdown(f"**Today**")
                elif day_offset == 1:
                    st.markdown(f"**Tomorrow**")
                else:
                    st.markdown(f"**{target_date.strftime('%a')}**")

                st.caption(target_date.strftime("%b %d"))

                # Weather — reuse the same forecast data
                closest_forecast = min(
                    forecasts,
                    key=lambda f: abs((f["datetime"] - afternoon_time).total_seconds()),
                )

                temp_f = closest_forecast["temp_c"] * 9 / 5 + 32
                wind_mph = closest_forecast["wind_speed_ms"] * 2.237
                wind_cardinal = wind_direction_to_cardinal(closest_forecast["wind_deg"])

                if use_metric:
                    st.caption(
                        f"🌡️ {closest_forecast['temp_c']:.0f}°C • 💨 {closest_forecast['wind_speed_ms'] * 3.6:.0f} km/h {wind_cardinal}"
                    )
                else:
                    st.caption(
                        f"🌡️ {temp_f:.0f}°F • 💨 {wind_mph:.0f} mph {wind_cardinal}"
                    )

                st.caption(f"{closest_forecast['description'].title()}")

                # Find top segments for this day
                weather_conditions = {
                    "temp_c": closest_forecast["temp_c"],
                    "pressure_hpa": closest_forecast["pressure_hpa"],
                    "wind_speed_ms": closest_forecast["wind_speed_ms"],
                    "wind_angle": closest_forecast["wind_deg"],
                }

                with st.spinner(""):
                    top_segments = find_closest_to_kom_segments(
                        segments_df,
                        athlete,
                        entrance_speed,
                        weather_conditions,
                        DB_PATH,
                        top_n=3,
                        gradient_range=gradient_range,
                        time_range=time_range,
                    )

                st.markdown("---")

                # Display top 3 segments compactly
                if top_segments:
                    for i, seg in enumerate(top_segments[:3], 1):
                        name_display = (
                            seg["name"]
                            if len(seg["name"]) <= 35
                            else seg["name"][:32] + "..."
                        )
                        wind_icon = seg.get("wind_icon", "")
                        st.markdown(f"**{i}. {name_display}** {wind_icon}")
                        st.caption(
                            f"ID: {seg['segment_id']} • {seg.get('wind_effect', 'unknown wind')}"
                        )

                        if use_metric:
                            st.caption(
                                f"📏 {seg['distance_km']:.1f}km • ⛰️ {seg['elevation_gain_m']:.0f}m"
                            )
                        else:
                            distance_mi = seg["distance_km"] * 0.621371
                            elevation_ft = seg["elevation_gain_m"] * 3.28084
                            st.caption(
                                f"📏 {distance_mi:.1f}mi • ⛰️ {elevation_ft:.0f}ft"
                            )

                        st.caption(
                            f"📈 {seg['avg_grade']:.1f}% • ⚡ {seg['power']:.0f}W"
                        )

                        your_time_str = format_time(seg["your_time"])
                        kom_time_str = format_time(seg["kom_time"])

                        if seg["time_behind"] < 0:
                            st.success(
                                f"⏱️ {your_time_str} (🟢 {abs(seg['time_behind']):.0f}s faster!)"
                            )
                        elif seg["time_behind"] < 10:
                            st.success(
                                f"⏱️ {your_time_str} (🟡 {seg['time_behind']:.0f}s slower)"
                            )
                        else:
                            st.info(
                                f"⏱️ {your_time_str} ({seg['time_behind']:.0f}s slower)"
                            )

                        st.caption(f"🏆 KOM: {kom_time_str} • {seg['pct_of_kom']:.0f}%")

                        if i < 3:
                            st.markdown("")
                else:
                    st.warning("No matches")

    # =============================
    # TAB 2: Segment Simulator
    # =============================
    with tab2:
        st.header("Segment Time Simulator")

        # Load only segments within the selected region/distance
        try:
            segments_list = get_segments_for_region(
                DB_PATH, selected_region, max_distance
            )
            if "elevation_gain_m" not in segments_list.columns:
                st.warning("No segments in database.")
                return
            segments_list = segments_list.sort_values("name").reset_index(drop=True)
        except Exception as e:
            st.error(f"Error: {e}")
            return

        if len(segments_list) == 0:
            st.warning(
                f"No segments within {max_distance:.0f} miles of {location_name}. "
                "Try increasing the distance filter."
            )
            return

        selected_segment_name = st.selectbox(
            "Select Segment", segments_list["name"].tolist()
        )
        segment_id = segments_list[segments_list["name"] == selected_segment_name][
            "id"
        ].values[0]
        segment_data = segments_list[
            segments_list["name"] == selected_segment_name
        ].iloc[0]

        col1, col2, col3 = st.columns(3)
        with col1:
            if use_metric:
                st.metric("Distance", f"{segment_data['distance_m']/1000:.2f} km")
            else:
                st.metric(
                    "Distance", f"{segment_data['distance_m']/1000 * 0.621371:.2f} mi"
                )
        with col2:
            if use_metric:
                st.metric("Elevation Gain", f"{segment_data['elevation_gain_m']:.0f} m")
            else:
                st.metric(
                    "Elevation Gain",
                    f"{segment_data['elevation_gain_m'] * 3.28084:.0f} ft",
                )
        with col3:
            st.metric("Average Grade", f"{segment_data['avg_grade']:.1f}%")

        st.markdown("---")

        # Get KOM time for this segment
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT MIN(time_seconds) FROM leaderboard WHERE segment_id = ?",
            (int(segment_id),),
        )
        kom_time_result = cur.fetchone()
        kom_time = (
            kom_time_result[0] if kom_time_result and kom_time_result[0] else None
        )
        conn.close()

        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Conditions")

            if use_metric:
                wind_options = {
                    "16 km/h tailwind": (10, 180),
                    "8 km/h tailwind": (5, 180),
                    "Neutral (0 km/h)": (0, 0),
                    "8 km/h headwind": (5, 0),
                    "16 km/h headwind": (10, 0),
                    "24 km/h headwind": (15, 0),
                }
                default_wind = "Neutral (0 km/h)"
            else:
                wind_options = {
                    "10 mph tailwind": (10, 180),
                    "5 mph tailwind": (5, 180),
                    "Neutral (0 mph)": (0, 0),
                    "5 mph headwind": (5, 0),
                    "10 mph headwind": (10, 0),
                    "15 mph headwind": (15, 0),
                }
                default_wind = "Neutral (0 mph)"

            wind_selection = st.select_slider(
                "💨 Wind Condition",
                options=list(wind_options.keys()),
                value=default_wind,
            )
            wind_speed_mph, wind_direction = wind_options[wind_selection]
            wind_speed_ms = wind_speed_mph * 0.44704

            if use_metric:
                temp_c = st.slider("🌡️ Temperature (°C)", -1, 38, 15, 2)
            else:
                temp_f = st.slider("🌡️ Temperature (°F)", 30, 100, 60, 5)
                temp_c = (temp_f - 32) * 5 / 9

        with col_right:
            st.subheader("Effort")

            if kom_time:
                st.caption(f"🏆 KOM Time: {format_time(kom_time)}")

                weather_conditions_kom = {
                    "temp_c": temp_c,
                    "pressure_hpa": 1013,
                    "wind_speed_ms": wind_speed_ms,
                    "wind_angle": (
                        0
                        if "headwind" in wind_selection
                        else 180 if "tailwind" in wind_selection else 90
                    ),
                }

                segment_dict = {
                    "distance_m": segment_data["distance_m"],
                    "avg_grade": segment_data["avg_grade"],
                    "elevation_high_m": segment_data["elevation_gain_m"],
                    "elevation_low_m": 0,
                }

                low_power, high_power = 100, 800
                optimized_power = None

                for _ in range(15):
                    mid_power = (low_power + high_power) / 2
                    r = estimate_time_with_entrance_speed(
                        segment_dict,
                        athlete,
                        entrance_speed,
                        weather_conditions_kom,
                        target_power=mid_power,
                    )
                    if abs(r["total_time"] - kom_time) < 0.5:
                        optimized_power = mid_power
                        break
                    elif r["total_time"] > kom_time:
                        low_power = mid_power
                    else:
                        high_power = mid_power

                if optimized_power:
                    optimized_power = int(optimized_power)
                    duration_minutes = kom_time / 60
                    max_sustainable = athlete.sustainable_power(duration_minutes)

                    if optimized_power <= max_sustainable * 1.02:
                        use_optimized = st.checkbox(
                            f"✅ Use Optimized Power ({optimized_power}W to match KOM)",
                            value=False,
                            help=f"This power would match the KOM time of {format_time(kom_time)}",
                        )
                    else:
                        pct_over = (optimized_power / max_sustainable - 1) * 100
                        use_optimized = st.checkbox(
                            f"⚠️ Use Optimized Power ({optimized_power}W, +{pct_over:.0f}% over sustainable)",
                            value=False,
                            help=f"This power would match KOM but is {pct_over:.0f}% above your sustainable power for this duration",
                        )
                else:
                    use_optimized = False
                    optimized_power = None
            else:
                use_optimized = False
                optimized_power = None

            duration_minutes = (segment_data["distance_m"] / 1000) / 20 * 60
            natural_power = athlete.sustainable_power(duration_minutes)

            if use_optimized and optimized_power:
                target_power = optimized_power
                st.metric(
                    "⚡ Target Power", f"{target_power} W", delta="Optimized for KOM"
                )
            else:
                target_power = st.slider(
                    "⚡ Target Power (W)", 100, 600, int(natural_power), 10
                )
                if target_power > natural_power * 1.1:
                    st.warning(
                        f"⚠️ {(target_power/natural_power - 1)*100:.0f}% above sustainable power"
                    )
                elif target_power < natural_power * 0.9:
                    st.info(
                        f"ℹ️ {(1 - target_power/natural_power)*100:.0f}% below sustainable power"
                    )
                else:
                    st.success(f"✅ Matches sustainable power")

        # =============================================
        # Auto-calculate simulation (runs on every input change)
        # =============================================
        weather_conditions = {
            "temp_c": temp_c,
            "pressure_hpa": 1013,
            "wind_speed_ms": wind_speed_ms,
            "wind_angle": (
                0
                if "headwind" in wind_selection
                else 180 if "tailwind" in wind_selection else 90
            ),
        }

        segment_dict = {
            "distance_m": segment_data["distance_m"],
            "avg_grade": segment_data["avg_grade"],
            "elevation_high_m": segment_data["elevation_gain_m"],
            "elevation_low_m": 0,
        }

        result = estimate_time_with_entrance_speed(
            segment_dict,
            athlete,
            entrance_speed,
            weather_conditions,
            target_power=target_power,
        )

        # --- Results section ---
        st.markdown("---")
        st.subheader("📊 Results")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("⏱️ Estimated Time", format_time(result["total_time"]))
        with col2:
            avg_speed_mph = result["cruise_speed_mph"]
            if use_metric:
                avg_speed_kmh = avg_speed_mph * 1.60934
                st.metric("🏁 Average Speed", f"{avg_speed_kmh:.1f} km/h")
            else:
                st.metric("🏁 Average Speed", f"{avg_speed_mph:.1f} mph")
        with col3:
            st.metric("⚡ Target Power", f"{target_power:.0f} W")
        with col4:
            if "speed_profile" in result:
                final_mph = result["speed_profile"]["final_mph"]
                initial_mph = result["speed_profile"]["initial_mph"]
                speed_change = final_mph - initial_mph
                if use_metric:
                    final_display = f"{final_mph * 1.60934:.1f} km/h"
                    delta_str = (
                        f"{speed_change * 1.60934:+.1f} km/h"
                        if abs(speed_change) > 0.5
                        else None
                    )
                else:
                    final_display = f"{final_mph:.1f} mph"
                    delta_str = (
                        f"{speed_change:+.1f} mph" if abs(speed_change) > 0.5 else None
                    )
                st.metric("🏁 Final Speed", final_display, delta=delta_str)

        if "speed_profile" in result:
            profile = result["speed_profile"]
            if use_metric:
                initial_kmh = profile["initial_mph"] * 1.60934
                final_kmh = profile["final_mph"] * 1.60934
                avg_kmh = avg_speed_mph * 1.60934
                if profile["final_mph"] < profile["initial_mph"] - 0.5:
                    st.info(
                        f"⬇️ **Decelerated**: Entered at {initial_kmh:.1f} km/h, exited at {final_kmh:.1f} km/h (lost {initial_kmh - final_kmh:.1f} km/h on climb)"
                    )
                elif profile["final_mph"] > profile["initial_mph"] + 0.5:
                    st.success(
                        f"⬆️ **Accelerated**: Entered at {initial_kmh:.1f} km/h, exited at {final_kmh:.1f} km/h (gained {final_kmh - initial_kmh:.1f} km/h)"
                    )
                else:
                    st.success(
                        f"➡️ **Steady**: Maintained ~{avg_kmh:.1f} km/h throughout segment"
                    )
            else:
                if profile["final_mph"] < profile["initial_mph"] - 0.5:
                    st.info(
                        f"⬇️ **Decelerated**: Entered at {profile['initial_mph']:.1f} mph, exited at {profile['final_mph']:.1f} mph (lost {profile['initial_mph'] - profile['final_mph']:.1f} mph on climb)"
                    )
                elif profile["final_mph"] > profile["initial_mph"] + 0.5:
                    st.success(
                        f"⬆️ **Accelerated**: Entered at {profile['initial_mph']:.1f} mph, exited at {profile['final_mph']:.1f} mph (gained {profile['final_mph'] - profile['initial_mph']:.1f} mph)"
                    )
                else:
                    st.success(
                        f"➡️ **Steady**: Maintained ~{avg_speed_mph:.1f} mph throughout segment"
                    )

        # =============================================
        # Leaderboard section (always visible)
        # =============================================
        st.markdown("---")

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT rank, athlete_name, time_seconds, power, date FROM leaderboard WHERE segment_id = ? ORDER BY time_seconds ASC LIMIT 20",
            (int(segment_id),),
        )
        leaderboard_data = cur.fetchall()
        conn.close()

        if leaderboard_data:
            st.subheader("🏆 Leaderboard")

            your_time = result["total_time"]
            kom_time_lb = leaderboard_data[0][2]
            time_behind_kom = your_time - kom_time_lb
            pct_of_kom = (your_time / kom_time_lb) * 100

            max_lb_time = max(row[2] for row in leaderboard_data[:10] if row[2])
            is_on_board = your_time <= max_lb_time

            col1, col2, col3 = st.columns(3)
            with col1:
                if is_on_board:
                    position = (
                        sum(
                            1
                            for _, _, t, _, _ in leaderboard_data
                            if t and your_time > t
                        )
                        + 1
                    )
                    st.metric(
                        "Your Position",
                        f"#{position}",
                        delta=f"{time_behind_kom:+.0f}s",
                    )
                else:
                    st.metric("Your Position", "N/A", delta=f"{time_behind_kom:+.0f}s")
            with col2:
                st.metric("KOM Time", format_time(kom_time_lb))
            with col3:
                color = "🟢" if pct_of_kom < 110 else "🟡" if pct_of_kom < 120 else "🔴"
                st.metric("% of KOM", f"{pct_of_kom:.1f}%", delta=color)

            st.markdown("##### Top 10 + Your Position")

            lb_df = pd.DataFrame(
                leaderboard_data[:10],
                columns=["_rank", "Athlete", "_time_s", "Power (W)", "Date"],
            )
            lb_df["Time"] = lb_df["_time_s"].apply(format_time)
            lb_df["Power (W)"] = lb_df["Power (W)"].apply(
                lambda x: f"{x:.0f}" if pd.notna(x) and x else "—"
            )
            lb_df["Date"] = lb_df["Date"].fillna("—")

            if is_on_board:
                your_row = pd.DataFrame(
                    [
                        {
                            "_rank": 0,
                            "Athlete": "👉 YOU",
                            "_time_s": your_time,
                            "Time": format_time(your_time),
                            "Power (W)": f"{target_power:.0f}",
                            "Date": "—",
                        }
                    ]
                )
                combined = pd.concat([lb_df, your_row])
            else:
                combined = lb_df.copy()

            combined = combined.sort_values("_time_s").reset_index(drop=True)
            combined["#"] = range(1, len(combined) + 1)
            combined = combined[["#", "Athlete", "Date", "Time", "Power (W)"]]

            def highlight_you(row):
                return [
                    ("background-color: #90EE90" if row["Athlete"] == "👉 YOU" else "")
                    for _ in row
                ]

            st.dataframe(
                combined.style.apply(highlight_you, axis=1),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "#": st.column_config.NumberColumn(width="small"),
                },
            )
        else:
            st.warning("No leaderboard data available for this segment.")

        # =============================================
        # 7-Day Segment Forecast
        # =============================================
        st.markdown("---")
        st.subheader("📅 7-Day Forecast for This Segment")

        seg_bearing = calculate_segment_bearing(
            segment_data["start_lat"],
            segment_data["start_lng"],
            segment_data["end_lat"],
            segment_data["end_lng"],
        )

        weather_api_tab2 = WeatherForecast(api_key)
        forecasts_tab2 = weather_api_tab2.get_forecast(center_lat, center_lon)

        forecast_rows = []
        for day_offset in range(8):
            target_date = datetime.now() + timedelta(days=day_offset)
            afternoon_time = target_date.replace(
                hour=14, minute=0, second=0, microsecond=0
            )

            closest_fc = min(
                forecasts_tab2,
                key=lambda f: abs((f["datetime"] - afternoon_time).total_seconds()),
            )

            # Wind relative to this specific segment
            wind_angle, wind_effect, wind_icon = calculate_wind_angle(
                seg_bearing, closest_fc["wind_deg"]
            )

            day_weather = {
                "temp_c": closest_fc["temp_c"],
                "pressure_hpa": closest_fc["pressure_hpa"],
                "wind_speed_ms": closest_fc["wind_speed_ms"],
                "wind_angle": wind_angle,
            }

            # Estimate time at sustainable power
            day_result = estimate_time_with_entrance_speed(
                segment_dict, athlete, entrance_speed, day_weather
            )
            day_time = day_result["total_time"]
            day_power = day_result["sustainable_power"]

            # Binary search for KOM-matching power on this day
            day_kom_power = None
            if kom_time:
                lo, hi = 100, 800
                for _ in range(15):
                    mid = (lo + hi) / 2
                    r = estimate_time_with_entrance_speed(
                        segment_dict,
                        athlete,
                        entrance_speed,
                        day_weather,
                        target_power=mid,
                    )
                    if abs(r["total_time"] - kom_time) < 0.5:
                        day_kom_power = int(mid)
                        break
                    elif r["total_time"] > kom_time:
                        lo = mid
                    else:
                        hi = mid

            # Format day label
            if day_offset == 0:
                day_label = "Today"
            elif day_offset == 1:
                day_label = "Tomorrow"
            else:
                day_label = target_date.strftime("%a %b %d")

            # Format wind speed with direction
            wind_cardinal = wind_direction_to_cardinal(closest_fc["wind_deg"])
            if use_metric:
                wind_speed_display = closest_fc["wind_speed_ms"] * 3.6
                wind_unit = "km/h"
            else:
                wind_speed_display = closest_fc["wind_speed_ms"] * 2.237
                wind_unit = "mph"

            # Gust data (may or may not be in forecast)
            gust_ms = closest_fc.get("wind_gust_ms") or closest_fc.get("wind_gust") or 0
            if use_metric:
                gust_display = f"{gust_ms * 3.6:.0f} {wind_unit}" if gust_ms else "—"
            else:
                gust_display = f"{gust_ms * 2.237:.0f} {wind_unit}" if gust_ms else "—"

            if use_metric:
                temp_display = f"{closest_fc['temp_c']:.0f}°C"
            else:
                temp_display = f"{closest_fc['temp_c'] * 9 / 5 + 32:.0f}°F"

            forecast_rows.append(
                {
                    "Day": day_label,
                    "Temp": temp_display,
                    "Wind (2pm)": f"{wind_speed_display:.0f} {wind_unit} {wind_cardinal}",
                    "Gust": gust_display,
                    "Effect": f"{wind_icon} {wind_effect}",
                    "Est. Time": format_time(day_time),
                    "Power (W)": f"{day_power:.0f}",
                    "KOM Power": f"{day_kom_power}" if day_kom_power else "—",
                }
            )

        forecast_df = pd.DataFrame(forecast_rows)

        # Mark the best day
        best_day_label = min(forecast_rows, key=lambda r: r["Est. Time"])["Day"]
        forecast_df["Day"] = forecast_df["Day"].apply(
            lambda d: f"{d} (Best)" if d == best_day_label else d
        )

        def bold_best_day(row):
            if "(Best)" in str(row["Day"]):
                return ["font-weight: bold"] * len(row)
            return [""] * len(row)

        st.dataframe(
            forecast_df.style.apply(bold_best_day, axis=1),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Day": st.column_config.TextColumn(width="small"),
            },
        )

    st.markdown("---")
    st.caption("🚴 Strava Segment Time Predictor | Built with Streamlit")


if __name__ == "__main__":
    main()
