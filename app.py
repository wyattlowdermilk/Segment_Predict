"""
Cycling Segment Predictor - Streamlit App
Physics-based segment time prediction with entrance speed modeling

Run with: streamlit run app.py
"""

import streamlit as st

# Page config MUST be THE FIRST Streamlit command
st.set_page_config(
    page_title="🚴 Cycling Segment Predictor",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Mobile-only responsive overrides ──────────────────────────────────
# CSS is split into two st.markdown blocks to stay under Streamlit's
# internal size limits.  Block 1 uses only class/element selectors
# (no square-bracket attribute selectors which break the markdown parser).
# Block 2 handles the custom HTML classes we control.

# Mobile detection via user-agent header (works on first load, no JS needed)
import streamlit.components.v1 as _components

IS_MOBILE = False
try:
    from streamlit import context as _st_context

    _headers = _st_context.headers
    _ua = _headers.get("User-Agent", "") or _headers.get("user-agent", "")
    IS_MOBILE = any(k in _ua.lower() for k in ["mobile", "android", "iphone", "ipod"])
except Exception:
    # Streamlit < 1.31 or running outside a request context
    IS_MOBILE = False

# Block 1: Streamlit element overrides (no square brackets — safe for markdown parser)
st.markdown(
    """<style>
@media only screen and (max-width: 480px) {
    .main .block-container {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    h1 { font-size: 1.25rem !important; }
    h2 { font-size: 1.08rem !important; }
    h3 { font-size: 0.95rem !important; }
    .stExpander summary span { font-size: 0.82rem !important; }
    .stButton > button { width: 100% !important; }
    .stCaption, .stMarkdown, label { font-size: 0.78rem !important; }
    /* Shrink st.metric text on narrow screens (mobile). Midpoint between
       Streamlit default (1.75rem / 0.875rem) and our first shrink pass,
       since full shrink felt too small on phone. */
    .stMetric [class*="MetricValue"],
    .stMetric div[data-testid="stMetricValue"] {
        font-size: 1.4rem !important;
    }
    .stMetric [class*="MetricLabel"],
    .stMetric div[data-testid="stMetricLabel"] {
        font-size: 0.8rem !important;
    }
}
@media only screen and (max-width: 380px) {
    .stMarkdown, .stCaption { font-size: 0.73rem !important; }
}
</style>""",
    unsafe_allow_html=True,
)

# Block 2: Custom HTML class overrides + sidebar + card layout
st.markdown(
    """<style>
@media only screen and (max-width: 480px) {
    .weather-tbl, .weather-tbl th, .weather-tbl td {
        font-size: 0.8em !important;
        padding: 4px 5px !important;
    }
    .seg-name      { font-size: 0.95em !important; }
    .seg-big-num   { font-size: 1.15em !important; }
    .dp-info       { font-size: 0.78em !important; }
    .dp-tip        { font-size: 0.78em !important; padding: 6px 8px !important; }
    .dp-wind-score { font-size: 0.72em !important; }
    .seg-card-mid  { font-size: 0.78em !important; line-height: 1.5 !important; }
    .seg-card-mid span { font-size: 0.85em !important; }
    .seg-card-inner > .seg-card-left  { flex: 3 !important; }
    .seg-card-inner > .seg-card-mid   { flex: 3 !important; min-width: 90px !important; }
    .seg-card-inner > .seg-card-right { flex: 3 !important; max-height: 90px !important; }
    .seg-card-right svg { max-height: 75px !important; }
}
@media only screen and (max-width: 380px) {
    .seg-big-num { font-size: 1.0em !important; }
}
</style>""",
    unsafe_allow_html=True,
)

# Block 3: Sidebar arrow visibility (injected via components.html because
# it needs attribute selectors that st.markdown can't handle)
_components.html(
    """
<style>
@media only screen and (max-width: 480px) {
    button[data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] {
        background: rgba(49, 51, 63, 0.95) !important;
        border: 1px solid rgba(250, 250, 250, 0.25) !important;
        border-radius: 0 8px 8px 0 !important;
        padding: 10px 8px !important;
        z-index: 999 !important;
    }
    button[data-testid="stSidebarCollapsedControl"] svg,
    [data-testid="collapsedControl"] svg {
        width: 22px !important;
        height: 22px !important;
        stroke: rgba(250, 250, 250, 0.9) !important;
    }
}
</style>
<script>
(function() {
    var s = document.querySelector('style');
    if (s) {
        try {
            var c = window.parent.document.createElement('style');
            c.textContent = s.textContent;
            window.parent.document.head.appendChild(c);
        } catch(e) {}
    }
    try {
        if (!window.parent.document.querySelector('meta[name="viewport"]')) {
            var m = window.parent.document.createElement('meta');
            m.name = 'viewport';
            m.content = 'width=device-width, initial-scale=1.0';
            window.parent.document.head.appendChild(m);
        }
    } catch(e) {}
})();
</script>
""",
    height=0,
)

# ── Capture OAuth tokens from URL fragment ────────────────────────────
# Supabase returns tokens in the URL fragment (#access_token=...) which
# Streamlit cannot read. This JS snippet converts the fragment to query
# params (?access_token=...) and reloads, so Streamlit can process them.
_components.html(
    """
<script>
(function() {
    try {
        var hash = window.parent.location.hash;
        if (hash && hash.includes('access_token')) {
            // Convert #key=val&key2=val2 to ?key=val&key2=val2
            var params = hash.substring(1);
            var newUrl = window.parent.location.pathname + '?' + params;
            window.parent.location.replace(newUrl);
        }
    } catch(e) {}
})();
</script>
""",
    height=0,
)

# Now import everything else AFTER st.set_page_config
import sqlite3
import pandas as pd
import numpy as np
import altair as alt
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

# Import segment optimizer for variable gradient analysis
from Segment_Optimizer import (
    Athlete as OptimizerAthlete,
    SegmentSection,
    build_segment,
    simulate_segment as optimizer_simulate_segment,
    optimize_power_profile,
    simulate_flat_equivalent,
    segment_total_distance,
    segment_avg_grade,
    MILES_TO_METERS,
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

# Import Supabase auth helpers (optional — app works without Supabase)
try:
    from sb_auth import (
        init_supabase,
        login_ui,
        get_user,
        load_profile,
        save_profile,
        toggle_favorite,
        get_favorites,
        log_visit,
        logout,
        logout_ui,
    )

    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


# =============================
# Helper Functions
# =============================


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_forecast_cached(api_key: str, lat: float, lon: float, _date_key: str):
    """
    Cached weather forecast fetch.  _date_key is today's date string so
    the cache auto-invalidates once a day (or every 30 min via ttl).
    """
    weather_api = WeatherForecast(api_key)
    return weather_api.get_forecast(lat, lon)


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
    dt = 0.5  # 0.5 second time steps
    current_speed = starting_speed_ms
    total_time = 0
    total_distance = 0
    max_iterations = 100  # Safety limit (50 seconds)

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
    dt = 0.5  # Time step (seconds)
    current_speed = entrance_speed_ms
    distance_covered = 0
    elapsed_time = 0

    speed_profile = [current_speed]
    # Scale iteration cap to segment distance so long segments (e.g. 6+ mile
    # climbs like Strava segment 659554) don't get cut off at the cap.
    # Assumes a conservative minimum speed of 2 m/s (~4.5 mph) with a 50%
    # safety margin on simulated time. Floor of 2000 for short segments.
    # IMPORTANT: if you tune this, keep it here — the refinement loop below
    # reuses this same variable.
    min_expected_speed_ms = 2.0
    max_sim_seconds = (distance_m / min_expected_speed_ms) * 1.5
    max_iterations = max(2000, int(max_sim_seconds / dt))
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
    Calculate the angle between segment direction and wind direction,
    and a tailwind percentage (0% = pure headwind, 100% = pure tailwind).

    Wind direction = where wind comes FROM.
    angle 0° means wind comes from the direction the rider travels → headwind.
    angle 180° means wind comes from behind the rider → tailwind.

    tailwind_pct uses cosine so that:
      180° → 100%  (pure tailwind)
      135° →  71%  (cross-tailwind)
       90° →  50%  (pure crosswind — no help, no hindrance)
       45° →  29%  (cross-headwind)
        0° →   0%  (pure headwind)

    Returns: (wind_angle, tailwind_pct)
    """
    # Calculate relative angle (0-180)
    angle = abs(segment_bearing - wind_direction)
    if angle > 180:
        angle = 360 - angle

    # Tailwind percentage: map 0°..180° → 0%..100% using cosine
    # cos(0°)=1 (headwind), cos(180°)=-1 (tailwind)
    # tailwind_pct = (1 - cos(angle)) / 2 * 100
    tailwind_pct = (1 - math.cos(math.radians(angle))) / 2 * 100

    return angle, tailwind_pct


def find_tailwind_segments(
    segments_df: pd.DataFrame,
    athlete: AthleteProfile,
    entrance_speed_mph: float,
    weather_conditions: dict,
    db_path: str,
    top_n: int = 3,
    gradient_range: tuple = (-5.0, 20.0),
    time_range: tuple = (10, 1800),
    min_tailwind_pct: float = 50.0,
    min_athletes: int = 0,
    use_qom: bool = False,
):
    """
    Two-phase segment finder:
      1. CHEAP FILTER — compute tailwind % for every segment (just trig).
         Keep only those with tailwind_pct >= min_tailwind_pct.
         Also filters out segments with fewer than min_athletes unique athletes.
      2. SIMULATE — run the physics model only on the tailwind survivors,
         then rank by estimated time closest to KOM/QOM (lowest pct_of_kom).

    When use_qom=True, benchmarks against the leaderboard_qom table; segments
    with no QOM record are skipped (same behavior as missing KOM).

    Returns list of dicts sorted by pct_of_kom ascending (best chances first).
    """
    results = []

    # Apply gradient filter
    min_gradient, max_gradient = gradient_range
    segments_df = segments_df[
        (segments_df["avg_grade"] >= min_gradient)
        & (segments_df["avg_grade"] <= max_gradient)
    ].copy()

    # Pre-fetch all KOM (or QOM) times in one query
    benchmark_table = "leaderboard_qom" if use_qom else "leaderboard"
    conn = sqlite3.connect(db_path)
    seg_ids = segments_df["id"].tolist()
    if not seg_ids:
        conn.close()
        return []
    placeholders = ",".join("?" * len(seg_ids))
    kom_rows = conn.execute(
        f"SELECT segment_id, MIN(time_seconds) FROM {benchmark_table} WHERE segment_id IN ({placeholders}) GROUP BY segment_id",
        seg_ids,
    ).fetchall()
    conn.close()
    kom_map = {row[0]: row[1] for row in kom_rows if row[1]}

    # Check if athlete_count column is available in the dataframe
    has_athlete_count = "athlete_count" in segments_df.columns

    wind_direction = weather_conditions.get("wind_angle", 0)

    # --- Phase 1: cheap tailwind + athlete count filter ---
    tailwind_candidates = []
    for _, seg in segments_df.iterrows():
        # Filter by athlete count first (cheapest check)
        if has_athlete_count and min_athletes > 0:
            athlete_count = seg.get("athlete_count", 0) or 0
            if athlete_count < min_athletes:
                continue

        segment_bearing = calculate_segment_bearing(
            seg["start_lat"], seg["start_lng"], seg["end_lat"], seg["end_lng"]
        )
        wind_angle, tailwind_pct = calculate_wind_angle(segment_bearing, wind_direction)

        if tailwind_pct < min_tailwind_pct:
            continue

        kom_time = kom_map.get(seg["id"])
        if not kom_time:
            continue

        tailwind_candidates.append((seg, wind_angle, tailwind_pct, kom_time))

    # --- Phase 2: simulate only tailwind candidates ---
    for seg, wind_angle, tailwind_pct, kom_time in tailwind_candidates:
        segment_weather = weather_conditions.copy()
        segment_weather["wind_angle"] = wind_angle

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
                        "tailwind_pct": tailwind_pct,
                        "athlete_count": seg.get("athlete_count", None),
                        "effort_count": seg.get("effort_count", None),
                        "city": seg.get("city", ""),
                        "state": seg.get("state", ""),
                    }
                )
        except Exception:
            continue

    # Sort by pct_of_kom — closest to (or below) 100% first
    results_sorted = sorted(results, key=lambda x: x["pct_of_kom"])
    top_results = results_sorted[:top_n]

    # Compute neutral time (no wind) for just the top results to show wind advantage
    neutral_weather = weather_conditions.copy()
    neutral_weather["wind_speed_ms"] = 0
    neutral_weather["wind_angle"] = 90

    for seg_result in top_results:
        segment_dict = {
            "distance_m": seg_result["distance_km"] * 1000,
            "avg_grade": seg_result["avg_grade"],
            "elevation_high_m": seg_result["elevation_gain_m"],
            "elevation_low_m": 0,
        }
        try:
            neutral_result = estimate_time_with_entrance_speed(
                segment_dict, athlete, entrance_speed_mph, neutral_weather
            )
            neutral_time = neutral_result["total_time"]
            seg_result["wind_advantage_s"] = neutral_time - seg_result["your_time"]
        except Exception:
            seg_result["wind_advantage_s"] = 0

    return top_results


# =======================
# Region definitions
# =======================
# To add a new region, just append an entry here.
# Every segment in the DB is assigned to whichever region center is closest.
REGIONS = {
    "Seattle, WA": {"lat": 47.6062, "lon": -122.3321, "min_athletes": 1500},
    "Orcas Island, WA": {"lat": 48.6543, "lon": -122.9060, "min_athletes": 100},
    "Boulder, CO": {"lat": 40.0150, "lon": -105.2705, "min_athletes": 1500},
    "Salt Lake City, UT": {"lat": 40.7608, "lon": -111.8910, "min_athletes": 500},
    "Cottonwood Heights, UT": {"lat": 40.6197, "lon": -111.8103, "min_athletes": 500},
    "Weddington, NC": {"lat": 34.9901, "lon": -80.7812, "min_athletes": 200},
    "Portland, OR": {"lat": 45.5152, "lon": -122.6784, "min_athletes": 1500},
    "Coraopolis, PA": {"lat": 40.4978, "lon": -80.1156, "min_athletes": 200},
    "Pittsburgh, PA": {"lat": 40.4406, "lon": -79.9959, "min_athletes": 500},
    "Cary, NC": {"lat": 35.7915, "lon": -78.7811, "min_athletes": 300},
    "Oakland, CA": {"lat": 37.8044, "lon": -122.2712, "min_athletes": 1500},
    "Cincinnati, OH": {"lat": 39.1031, "lon": -84.5120, "min_athletes": 300},
    "Blacksburg, VA": {"lat": 37.2296, "lon": -80.4139, "min_athletes": 100},
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


@st.cache_data(ttl=3600, show_spinner=False)
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


@st.cache_data(ttl=3600, show_spinner=False)
def get_segments_for_region(
    db_path: str, region_name: str, max_distance_miles: float
) -> pd.DataFrame:
    """
    Get all segments assigned to a region within max_distance_miles of its center.
    If region_name is None (All Locations), returns all segments with distance
    from overall centroid.
    """
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql(
            """
            SELECT id, name, distance_m, elevation_gain_m, avg_grade,
                   start_lat, start_lng, end_lat, end_lng, city, state,
                   effort_count, athlete_count
            FROM segments
            WHERE start_lat IS NOT NULL AND start_lng IS NOT NULL
              AND end_lat IS NOT NULL AND end_lng IS NOT NULL
            """,
            conn,
        )
    except Exception:
        # Columns don't exist — query without them
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


@st.cache_data(ttl=3600, show_spinner=False)
def get_segment_elevation_profile(db_path: str, segment_id: int):
    """
    Load cleaned elevation profile from clean_seg_points table.
    Returns list of (distance_km, elevation_m, grade_pct) tuples, sorted by seq.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT distance_km, elevation_m, grade_pct
        FROM clean_seg_points
        WHERE segment_id = ?
        ORDER BY seq
        """,
        (segment_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


@st.cache_data(show_spinner=False)
def elevation_to_gradient_sections(elevation_points):
    """
    Convert clean elevation profile points into a list of
    (grade_pct, distance_miles) tuples for the optimizer.

    Computes grade directly from elevation differences between consecutive
    points, then merges consecutive sections with similar grades to produce
    a manageable number of sections (targeting 5-15) for pacing optimization.
    """
    if len(elevation_points) < 2:
        return []

    # Step 1: Compute raw grade for each interval
    raw_sections = []
    for i in range(len(elevation_points) - 1):
        d1_km, e1, _ = elevation_points[i]
        d2_km, e2, _ = elevation_points[i + 1]
        dist_m = (d2_km - d1_km) * 1000.0
        if dist_m < 0.1:
            continue
        grade = ((e2 - e1) / dist_m) * 100.0
        grade = max(-25.0, min(35.0, grade))
        raw_sections.append((grade, dist_m))

    if not raw_sections:
        return []

    # If already a small number of sections, just absorb tiny ones
    if len(raw_sections) <= 15:
        return _absorb_short_sections(
            [(g, d / MILES_TO_METERS) for g, d in raw_sections], min_mi=0.01
        )

    # Step 2: Adaptive merging — increase threshold until section count <= 15
    total_dist = sum(d for _, d in raw_sections)
    min_section_m = max(30, total_dist / 30)

    for threshold in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]:
        merged = _merge_similar_grades(raw_sections, threshold)
        merged = _absorb_short_sections_m(merged, min_section_m)
        if len(merged) <= 15:
            break

    return [(g, d / MILES_TO_METERS) for g, d in merged]


def _merge_similar_grades(sections, threshold_pct):
    """Merge consecutive sections whose grades differ by less than threshold."""
    if not sections:
        return []
    merged = []
    cur_grade, cur_dist = sections[0]
    for grade, dist_m in sections[1:]:
        if abs(grade - cur_grade) <= threshold_pct:
            new_dist = cur_dist + dist_m
            cur_grade = (cur_grade * cur_dist + grade * dist_m) / new_dist
            cur_dist = new_dist
        else:
            merged.append((cur_grade, cur_dist))
            cur_grade = grade
            cur_dist = dist_m
    merged.append((cur_grade, cur_dist))
    return merged


def _absorb_short_sections_m(sections, min_m):
    """Merge sections shorter than min_m into their neighbor."""
    final = []
    for grade, dist_m in sections:
        if final and dist_m < min_m:
            prev_g, prev_d = final[-1]
            new_d = prev_d + dist_m
            final[-1] = ((prev_g * prev_d + grade * dist_m) / new_d, new_d)
        else:
            final.append((grade, dist_m))
    return final


def _absorb_short_sections(sections_mi, min_mi):
    """Merge sections shorter than min_mi (in miles) into their neighbor."""
    final = []
    for grade, dist_mi in sections_mi:
        if final and dist_mi < min_mi:
            prev_g, prev_d = final[-1]
            new_d = prev_d + dist_mi
            final[-1] = ((prev_g * prev_d + grade * dist_mi) / new_d, new_d)
        else:
            final.append((grade, dist_mi))
    return final


@st.cache_data(ttl=3600, show_spinner=False)
def _get_leaderboard(
    db_path: str, segment_id: int, limit: int = 20, use_qom: bool = False
):
    """Cached leaderboard fetch.

    When use_qom=True, queries the leaderboard_qom table (female leaderboard)
    instead of the overall leaderboard.
    """
    table = "leaderboard_qom" if use_qom else "leaderboard"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        f"SELECT rank, athlete_name, time_seconds, power, date FROM {table} WHERE segment_id = ? ORDER BY time_seconds ASC LIMIT ?",
        (segment_id, limit),
    )
    data = cur.fetchall()
    conn.close()
    return data


@st.cache_data(ttl=3600, show_spinner=False)
def _get_kom_time(db_path: str, segment_id: int, use_qom: bool = False):
    """Cached KOM (or QOM) time fetch.

    When use_qom=True, returns the top QOM time from leaderboard_qom instead of
    the overall KOM. Returns None if no record exists in the selected table.
    Variable name kept as "kom_time" throughout the app for minimal diff —
    it really represents "benchmark time" when the QOM toggle is on.
    """
    table = "leaderboard_qom" if use_qom else "leaderboard"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        f"SELECT MIN(time_seconds) FROM {table} WHERE segment_id = ?",
        (segment_id,),
    )
    result = cur.fetchone()
    conn.close()
    return result[0] if result and result[0] else None


def create_optimizer_athlete(athlete_profile, drivetrain_loss_pct=4):
    """
    Create an Optimizer Athlete from the app's AthleteProfile, converting
    power curve keys from minutes to seconds as the optimizer expects.
    """
    power_curve_seconds = {}
    for dur_min, watts in athlete_profile.power_curve.items():
        power_curve_seconds[int(dur_min * 60)] = watts

    return OptimizerAthlete(
        power_curve=power_curve_seconds,
        weight_kg=athlete_profile.weight_kg,
        bike_weight_kg=athlete_profile.bike_weight_kg,
        cda=athlete_profile.cda,
        crr=athlete_profile.crr,
        drivetrain_loss=drivetrain_loss_pct / 100.0,
    )


def compute_air_density_from_weather(weather_conditions, elevation_m=0):
    """Compute air density from weather conditions dict."""
    return PowerModel.air_density(
        weather_conditions["temp_c"],
        weather_conditions.get("pressure_hpa", 1013),
        elevation_m,
    )


# =============================
# Flagged Segments (Supabase)
# =============================


def _supabase_rest_headers():
    """Get headers for Supabase REST API calls."""
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }, url


@st.cache_data(ttl=300, show_spinner=False)
def get_flagged_segment_ids(_cache_key: str = "default") -> set:
    """Return set of all flagged segment IDs from Supabase."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        resp = _requests.get(
            f"{url}/rest/v1/flagged_segments?select=segment_id",
            headers=headers,
        )
        if resp.status_code == 200:
            return {row["segment_id"] for row in resp.json()}
    except Exception:
        pass
    return set()


def flag_segment(segment_id: int, reason: str = ""):
    """Flag a segment so it's excluded everywhere."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        headers["Prefer"] = "resolution=merge-duplicates"
        _requests.post(
            f"{url}/rest/v1/flagged_segments",
            json={"segment_id": segment_id, "reason": reason},
            headers=headers,
        )
        get_flagged_segment_ids.clear()
    except Exception:
        pass


def unflag_segment(segment_id: int):
    """Remove a segment from the flagged list."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        _requests.delete(
            f"{url}/rest/v1/flagged_segments?segment_id=eq.{segment_id}",
            headers=headers,
        )
        get_flagged_segment_ids.clear()
    except Exception:
        pass


def get_flagged_segments_detail(segments_db_path: str = "segments.db") -> list:
    """Return list of (segment_id, name, reason, flagged_at) for all flagged segments."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        resp = _requests.get(
            f"{url}/rest/v1/flagged_segments?select=segment_id,reason,flagged_at&order=flagged_at.desc",
            headers=headers,
        )
        if resp.status_code != 200:
            return []
        flagged = resp.json()
    except Exception:
        return []

    if not flagged:
        return []

    # Look up segment names from the local segments DB
    conn = sqlite3.connect(segments_db_path)
    cur = conn.cursor()
    results = []
    for f in flagged:
        cur.execute("SELECT name FROM segments WHERE id = ?", (f["segment_id"],))
        row = cur.fetchone()
        name = row[0] if row else "(unknown)"
        results.append(
            (f["segment_id"], name, f.get("reason", ""), f.get("flagged_at", ""))
        )
    conn.close()
    return results


# =============================
# User Feedback (Supabase)
# =============================


def submit_feedback(
    feedback_type: str,
    message: str,
    segment_id: int = None,
    submitted_by: str = None,
    user_id: str = None,
):
    """Insert a feedback row into Supabase."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        row = {
            "feedback_type": feedback_type,
            "message": message,
        }
        if segment_id:
            row["segment_id"] = segment_id
        if submitted_by:
            row["submitted_by"] = submitted_by
        if user_id:
            row["user_id"] = user_id
        headers["Prefer"] = "return=minimal"
        _requests.post(
            f"{url}/rest/v1/user_feedback",
            json=row,
            headers=headers,
        )
    except Exception:
        pass


def get_recent_feedback(limit: int = 50) -> list:
    """Return recent feedback rows from Supabase."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        resp = _requests.get(
            f"{url}/rest/v1/user_feedback?select=id,feedback_type,message,segment_id,submitted_by,submitted_at&order=submitted_at.desc&limit={limit}",
            headers=headers,
        )
        if resp.status_code == 200:
            rows = resp.json()
            return [
                (
                    r["id"],
                    r["feedback_type"],
                    r["message"],
                    r.get("segment_id"),
                    r.get("submitted_by"),
                    r.get("submitted_at"),
                )
                for r in rows
            ]
    except Exception:
        pass
    return []


# =============================
# Location Geocoding & Requests (Supabase)
# =============================


def log_location_request(
    location_input: str,
    resolved_name: str,
    lat: float,
    lon: float,
    nearest_region: str,
    distance_miles: float,
    user_id: str = None,
):
    """Log an unsupported location request to Supabase."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        headers["Prefer"] = "return=minimal"
        _requests.post(
            f"{url}/rest/v1/location_requests",
            json={
                "location_input": location_input,
                "resolved_name": resolved_name,
                "lat": lat,
                "lon": lon,
                "nearest_region": nearest_region,
                "distance_miles": distance_miles,
                "user_id": user_id,
            },
            headers=headers,
        )
    except Exception:
        pass


# =============================
# Segment Requests (Supabase)
# =============================


def submit_segment_request(
    segment_id: int,
    requested_by: str = None,
    user_id: str = None,
    user_email: str = None,
    notes: str = None,
):
    """Submit a segment request to Supabase."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        headers["Prefer"] = "return=minimal"
        row = {"segment_id": segment_id}
        if requested_by:
            row["requested_by"] = requested_by
        if user_id:
            row["user_id"] = user_id
        if user_email:
            row["user_email"] = user_email
        if notes:
            row["notes"] = notes
        _requests.post(
            f"{url}/rest/v1/segment_requests",
            json=row,
            headers=headers,
        )
    except Exception:
        pass


def get_pending_requests() -> list:
    """Get pending segment requests from Supabase."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        resp = _requests.get(
            f"{url}/rest/v1/segment_requests?status=eq.pending&select=segment_id,requested_by,notes,requested_at&order=requested_at.desc",
            headers=headers,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def get_pending_segment_ids() -> set:
    """Get set of segment IDs that are already pending."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        resp = _requests.get(
            f"{url}/rest/v1/segment_requests?status=eq.pending&select=segment_id",
            headers=headers,
        )
        if resp.status_code == 200:
            return {r["segment_id"] for r in resp.json()}
    except Exception:
        pass
    return set()


def get_processed_requests(limit: int = 20) -> list:
    """Get recently processed segment requests from Supabase."""
    import requests as _requests

    try:
        headers, url = _supabase_rest_headers()
        resp = _requests.get(
            f"{url}/rest/v1/segment_requests?status=neq.pending&select=segment_id,requested_by,status,requested_at,processed_at&order=processed_at.desc&limit={limit}",
            headers=headers,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


@st.cache_data(ttl=86400, show_spinner=False)
def geocode_location(api_key: str, query: str) -> dict:
    """
    Geocode a location string using OpenWeatherMap's Geocoding API.
    Returns dict with name, state, country, lat, lon or empty dict on failure.
    """
    import requests as _requests

    # Clean up the query — add US country code if it looks like a US location
    q = query.strip()
    # If input has "STATE" abbreviation pattern (e.g. "Denver, CO"), append ",US"
    parts = [p.strip() for p in q.split(",")]
    if len(parts) == 2 and len(parts[1]) == 2 and parts[1].isalpha():
        q = f"{parts[0]},{parts[1]},US"

    try:
        resp = _requests.get(
            "http://api.openweathermap.org/geo/1.0/direct",
            params={"q": q, "limit": 1, "appid": api_key},
            timeout=5,
        )
        if resp.status_code == 200 and resp.json():
            data = resp.json()[0]
            return {
                "name": data.get("name", ""),
                "state": data.get("state", ""),
                "country": data.get("country", ""),
                "lat": data["lat"],
                "lon": data["lon"],
            }
    except Exception:
        pass
    return {}


def find_nearest_region(lat: float, lon: float) -> tuple:
    """
    Find the nearest supported region to a lat/lon point.
    Returns (region_name, distance_miles).
    """
    closest_name = None
    closest_dist = float("inf")
    for name, info in REGIONS.items():
        dist = _haversine(lat, lon, info["lat"], info["lon"])
        if dist < closest_dist:
            closest_dist = dist
            closest_name = name
    return closest_name, closest_dist


# =============================
# Main Application
# =============================


def main():
    """Main application entry point"""

    # Constants
    DB_PATH = "segments.db"
    # Tables for requests/feedback/flags are in Supabase (no local DB needed)

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
    st.sidebar.title("⚙️ Rider Profile")

    # ── Auth: Check existing session (no UI yet) ──
    sb = None
    user = None
    profile = {}
    _save_btn_placeholder = None
    if SUPABASE_AVAILABLE:
        try:
            sb = init_supabase()
            user = get_user(sb)
            if user:
                with st.sidebar:
                    logout_ui()
                    _save_btn_placeholder = st.empty()
                profile = load_profile(sb, str(user.id))
                log_visit(sb, str(user.id))
            else:
                with st.sidebar:
                    login_ui(sb)
        except Exception as e:
            st.sidebar.caption(f"⚠️ Auth unavailable: {e}")

    # Helper: get saved profile value or fall back to config default
    def pval(key, default):
        val = profile.get(key)
        if val is not None:
            return val
        return default

    # Check if user is signed in (used throughout)
    _is_signed_in = "_supabase_user" in st.session_state and SUPABASE_AVAILABLE
    if _is_signed_in and not user:
        user = get_user(sb) if sb else None
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

    # Weather API key — needed for geocoding and forecasts
    api_key = WEATHER_API_KEY

    # ---- Location selector in sidebar ----
    with st.sidebar.expander("📍 Location", expanded=True):
        # Text input for custom location
        location_input = st.text_input(
            "Your location",
            value=st.session_state.get("_user_location_input", ""),
            placeholder="City, State (e.g. Denver, CO)",
            key="_location_input",
        )
        search_clicked = st.button(
            "Find", key="_location_search", use_container_width=True
        )

        # Also trigger search on Enter (detect when input changed)
        _prev_location = st.session_state.get("_prev_location_input", "")
        _current_location = location_input.strip()
        if (
            _current_location
            and _current_location != _prev_location
            and not search_clicked
        ):
            search_clicked = True
        if search_clicked:
            st.session_state["_prev_location_input"] = _current_location

        # Geocode when user clicks search or presses Enter
        if search_clicked and location_input.strip():
            geo = geocode_location(api_key, location_input.strip())
            if geo:
                st.session_state["_user_location_input"] = location_input.strip()
                resolved_name = (
                    f"{geo['name']}, {geo['state']}"
                    if geo.get("state")
                    else geo["name"]
                )
                st.session_state["_user_geo"] = geo
                st.session_state["_user_geo_name"] = resolved_name

                nearest_region, nearest_dist = find_nearest_region(
                    geo["lat"], geo["lon"]
                )

                if nearest_dist <= 10:
                    st.session_state["_auto_region"] = nearest_region
                    st.session_state["_location_msg"] = (
                        "success",
                        f"✅ **{resolved_name}** matched to **{nearest_region}** region",
                    )
                else:
                    user_id = str(user.id) if user else None
                    log_location_request(
                        location_input.strip(),
                        resolved_name,
                        geo["lat"],
                        geo["lon"],
                        nearest_region,
                        nearest_dist,
                        user_id,
                    )
                    st.session_state["_auto_region"] = nearest_region
                    st.session_state["_location_msg"] = (
                        "unsupported",
                        f"📍 **{resolved_name}** doesn't have segment data yet. "
                        f"We've logged **{resolved_name}** as a requested region "
                        f"and will work on adding segments there. "
                        f"For now, showing **{nearest_region}** as the closest "
                        f"supported region ({nearest_dist:.0f} mi away).",
                    )
                st.rerun()
            else:
                st.session_state["_location_msg"] = (
                    "error",
                    "❌ Could not find that location. Try 'City, State' format (e.g. Denver, CO).",
                )
                st.rerun()

        # Show any location message ABOVE the dropdown
        _loc_msg = st.session_state.get("_location_msg")
        if _loc_msg:
            msg_type, msg_text = _loc_msg
            if msg_type == "success":
                st.success(msg_text)
            elif msg_type == "unsupported":
                st.info(msg_text)
            elif msg_type == "error":
                st.warning(msg_text)

        # If auto_region was set by geocoding, sync the dropdown
        auto_region = st.session_state.get("_auto_region")
        if auto_region and auto_region in REGIONS:
            # Find the label that matches this region
            auto_label = None
            for label, rname in region_options.items():
                if rname == auto_region:
                    auto_label = label
                    break
            if auto_label:
                st.session_state["_region_select"] = auto_label

        # Region dropdown
        region_labels = list(region_options.keys())
        selected_label = st.selectbox(
            "Region",
            region_labels,
            key="_region_select",
        )
        selected_region = region_options[selected_label]

        # Determine center coordinates
        if selected_region and selected_region in REGIONS:
            center_lat = REGIONS[selected_region]["lat"]
            center_lon = REGIONS[selected_region]["lon"]
            location_name = selected_region.split(",")[0]
        else:
            conn = sqlite3.connect(DB_PATH)
            center = pd.read_sql(
                "SELECT AVG(start_lat) as lat, AVG(start_lng) as lng FROM segments WHERE start_lat IS NOT NULL",
                conn,
            )
            conn.close()
            center_lat = center["lat"].iloc[0]
            center_lon = center["lng"].iloc[0]
            location_name = "all regions"

        geo = st.session_state.get("_user_geo")
        if geo:
            st.caption(f"📌 {geo['lat']:.3f}, {geo['lon']:.3f}")
        else:
            st.caption(f"📌 {center_lat:.3f}, {center_lon:.3f}")

    # Initialize use_metric early — the UI checkbox is rendered later
    # in the Units expander, but other expanders need the value now.
    if "use_metric_cb" not in st.session_state:
        st.session_state["use_metric_cb"] = False
    use_metric = st.session_state["use_metric_cb"]

    with st.sidebar.expander("💪 Power Curve", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            power_1 = st.number_input(
                "1-min (W)", value=int(pval("power_1_min", POWER_1_MIN)), step=10
            )
            power_8 = st.number_input(
                "8-min (W)", value=int(pval("power_8_min", POWER_8_MIN)), step=10
            )
        with col2:
            power_3 = st.number_input(
                "3-min (W)", value=int(pval("power_3_min", POWER_3_MIN)), step=10
            )
            power_20 = st.number_input(
                "20-min (W)", value=int(pval("power_20_min", POWER_20_MIN)), step=10
            )

    with st.sidebar.expander("🏋️ Physical Stats", expanded=True):
        weight_kg = st.slider(
            "Weight (kg)", 50, 120, int(pval("weight_kg", RIDER_WEIGHT_KG))
        )
        bike_weight = st.slider(
            "Bike Weight (kg)", 6, 15, int(pval("bike_weight_kg", BIKE_WEIGHT_KG))
        )
        show_qom = st.checkbox(
            "Show QOM",
            value=bool(pval("show_qom", False)),
            key="show_qom_cb",
            help="Display QOM times and benchmarks instead of KOM. "
            "Segments without QOM data show '—'.",
        )

    # Benchmark label used throughout the UI. Driven by the Show QOM toggle.
    # The DB column and internal variable name stay as "kom_time" for minimal
    # diff — this label is purely for display.
    _bench_label = "QOM" if show_qom else "KOM"

    with st.sidebar.expander("🚴 Equipment", expanded=False):
        cda = st.slider(
            "CdA (m²)",
            0.25,
            0.45,
            float(pval("cda", CDA_M2)),
            0.01,
            help="0.28=Aero, 0.32=Drops, 0.40=Hoods",
        )
        crr = st.slider(
            "Rolling Resistance",
            0.003,
            0.008,
            float(pval("crr", CRR)),
            0.0001,
            format="%.4f",
            help="0.003=Race tires, 0.005=Training tires",
        )

    # =============================================================================
    # Entrance Speed — MOVED to Tab 1b (below calendar, alongside filters).
    # Tab 2 has its own entrance speed slider (entrance_speed_t2).
    # A default scalar is set here so any code that runs before Tab 1b's widget
    # renders has a value to fall back on. Tab 1b's widget overwrites it.
    # =============================================================================
    if use_metric:
        entrance_speed = 26 * 0.621371  # 26 km/h default, converted to mph
    else:
        entrance_speed = 16.0  # mph default

    # =============================================================================
    # Segment Filters — MOVED to Tab 1b (below calendar).
    # Other tabs (2/4/5/6/Favorites) use wide-open defaults defined here so their
    # existing filter logic keeps working without a sidebar UI.
    # Tab 1b will OVERWRITE these values from its own widgets when it renders.
    # =============================================================================
    _region_min_athletes = (
        REGIONS[selected_region].get("min_athletes", 500)
        if selected_region and selected_region in REGIONS
        else 500
    )
    # Wide-open defaults for tabs 2/4/5/6/Favorites (show everything)
    max_distance = 25  # miles — generous radius
    gradient_range = (-5, 20)  # full gradient range
    time_range = (0, 99999)  # no time limit (seconds)
    min_athletes = 10  # minimal floor

    with st.sidebar.expander("📏 Units", expanded=True):
        use_metric = st.checkbox(
            "Use Metric (km, km/h, °C)", value=False, key="use_metric_cb"
        )
        if use_metric:
            st.caption("🌍 Metric units enabled")
        else:
            st.caption("🇺🇸 Imperial units (mi, mph, °F)")

    # ── Save to Profile button (fills the placeholder near sign-out) ──
    if _is_signed_in and _save_btn_placeholder and user and sb:
        with _save_btn_placeholder:
            if st.button(
                "Save to Profile",
                type="primary",
                key="save_profile_btn",
                use_container_width=True,
            ):
                save_profile(
                    sb,
                    str(user.id),
                    {
                        "power_1_min": power_1,
                        "power_3_min": power_3,
                        "power_8_min": power_8,
                        "power_20_min": power_20,
                        "weight_kg": float(weight_kg),
                        "bike_weight_kg": float(bike_weight),
                        "cda": float(cda),
                        "crr": float(crr),
                        "preferred_region": selected_region or "Seattle, WA",
                        "use_metric": use_metric,
                        "show_qom": bool(show_qom),
                    },
                )
                st.success("✅ Saved!")

    # ── First-sign-in onboarding ──
    # If the user just signed in and their profile has all default values,
    # show a welcome prompt in the main area asking them to set up their profile.
    if _is_signed_in and user and profile:
        _has_defaults = (
            profile.get("power_1_min") == 400
            and profile.get("power_20_min") == 250
            and profile.get("weight_kg") == 75.0
        )
        if _has_defaults and "_onboarding_dismissed" not in st.session_state:
            st.info(
                "👋 **Welcome!** Your profile is using default values. "
                "Update your **power numbers**, **weight**, and **region** "
                "in the sidebar, then click **Save to Profile** to keep them for next time."
            )
            if st.button("Got it", key="_dismiss_onboarding"):
                st.session_state["_onboarding_dismissed"] = True
                st.rerun()
    elif _is_signed_in and user and not profile:
        # Profile row might not exist yet (trigger may not have fired)
        if "_onboarding_dismissed" not in st.session_state:
            st.info(
                "👋 **Welcome!** Set up your **power curve**, **weight**, and **region** "
                "in the sidebar, then click **Save to Profile** to save your settings."
            )
            if st.button("Got it", key="_dismiss_onboarding"):
                st.session_state["_onboarding_dismissed"] = True
                st.rerun()

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

    # Tabs — add Favorites tab if signed in
    if _is_signed_in:
        tab1b, tab_favs, tab2, tab4, tab5, tab6 = st.tabs(
            [
                "📅 Daily Planner",
                "⭐ My Favorites",
                "🎯 Segment Simulator",
                "📬 Request Segments",
                "🚫 Excluded Segments",
                "💬 Feedback",
            ]
        )
    else:
        tab1b, tab2, tab4, tab5, tab6 = st.tabs(
            [
                "📅 Daily Planner",
                "🎯 Segment Simulator",
                "📬 Request Segments",
                "🚫 Excluded Segments",
                "💬 Feedback",
            ]
        )
        tab_favs = None

    # Load flagged segment IDs once (used by all tabs)
    flagged_ids = get_flagged_segment_ids()

    def _render_segment_cards(top_segments, use_metric):
        """Render the top segment cards for a day column in Tab 1."""
        if top_segments:
            for i, seg in enumerate(top_segments[:3], 1):
                name_display = (
                    seg["name"] if len(seg["name"]) <= 35 else seg["name"][:32] + "..."
                )
                tailwind_pct = seg["tailwind_pct"]
                strava_url = f"https://www.strava.com/segments/{seg['segment_id']}"
                st.markdown(f"**{i}. {name_display}**")
                st.caption(
                    f"[ID: {seg['segment_id']}]({strava_url}) • {tailwind_pct:.0f}% tailwind"
                )

                if use_metric:
                    st.caption(
                        f"📏 {seg['distance_km']:.1f}km • ⛰️ {seg['elevation_gain_m']:.0f}m"
                    )
                else:
                    distance_mi = seg["distance_km"] * 0.621371
                    elevation_ft = seg["elevation_gain_m"] * 3.28084
                    st.caption(f"📏 {distance_mi:.1f}mi • ⛰️ {elevation_ft:.0f}ft")

                st.caption(f"📈 {seg['avg_grade']:.1f}% • ⚡ {seg['power']:.0f}W")

                your_time_str = format_time(seg["your_time"])
                kom_time_str = format_time(seg["kom_time"])
                wind_adv = seg.get("wind_advantage_s", 0)
                wind_adv_str = (
                    f" - {wind_adv:.0f}s faster from wind" if wind_adv > 0 else ""
                )

                if seg["time_behind"] < 0:
                    st.success(
                        f"{your_time_str} ({abs(seg['time_behind']):.0f}s faster than {_bench_label}!){wind_adv_str}"
                    )
                elif seg["time_behind"] < 10:
                    st.success(
                        f"{your_time_str} ({seg['time_behind']:.0f}s slower than {_bench_label}){wind_adv_str}"
                    )
                else:
                    st.info(
                        f"{your_time_str} ({seg['time_behind']:.0f}s slower than {_bench_label}){wind_adv_str}"
                    )

                st.caption(f"🏆 {_bench_label}: {kom_time_str}")

                if i < 3:
                    st.markdown("")
        else:
            st.warning("No tailwind segments")

    # =============================
    # TAB 1b: Daily Planner
    # =============================
    with tab1b:
        # Custom CSS for this tab — better contrast and styled cards
        st.markdown(
            """
        <style>
            .dp-card {
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                border-radius: 12px;
                padding: 16px 20px;
                margin-bottom: 12px;
                border-left: 4px solid #0ea5e9;
                color: #e2e8f0;
            }
            .dp-card-hot {
                background: linear-gradient(135deg, #1a2e1a 0%, #163e21 100%);
                border-left: 4px solid #22c55e;
            }
            .dp-card-close {
                background: linear-gradient(135deg, #2e2a1a 0%, #3e3516 100%);
                border-left: 4px solid #eab308;
            }
            .dp-card .dp-time {
                font-size: 1.6em;
                font-weight: 700;
                color: #ffffff;
                margin-bottom: 2px;
            }
            .dp-card .dp-name {
                font-size: 1.05em;
                font-weight: 600;
                color: #f1f5f9;
                margin-bottom: 4px;
            }
            .dp-card .dp-detail {
                font-size: 0.88em;
                color: #cbd5e1;
                line-height: 1.5;
            }
            .dp-card .dp-badge {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 0.8em;
                font-weight: 600;
            }
            .dp-badge-faster { background: #166534; color: #bbf7d0; }
            .dp-badge-close { background: #854d0e; color: #fef08a; }
            .dp-badge-slower { background: #1e3a5f; color: #bfdbfe; }
            .dp-badge-wind { background: #164e63; color: #a5f3fc; margin-left: 6px; }
            .dp-wind-score {
                display: inline-block;
                padding: 2px 10px;
                border-radius: 12px;
                font-size: 0.82em;
                font-weight: 700;
            }
            .dp-wind-high { background: #166534; color: #bbf7d0; }
            .dp-wind-med { background: #854d0e; color: #fef08a; }
            .dp-wind-low { background: #374151; color: #9ca3af; }
            .dp-info { color: #e2e8f0; font-size: 0.92em; line-height: 1.6; }
            .dp-tip {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 10px 14px;
                color: #94a3b8;
                font-size: 0.88em;
                line-height: 1.5;
                margin-bottom: 12px;
            }
            .dp-tip b { color: #cbd5e1; }
        </style>
        """,
            unsafe_allow_html=True,
        )

        if IS_MOBILE:
            st.markdown(
                '<div class="dp-tip">'
                "💡 <b>Tip:</b> Tap the <b>&gt; arrow in the top left</b> to open the sidebar — "
                "select your <b>Region</b> and update your <b>Athlete Profile</b> "
                "(power curve, weight, equipment). "
                "Use the <b>Segment Filters</b> below the calendar to refine results."
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="dp-tip">'
                "💡 <b>Tip:</b> Use the <b>Segment Filters</b> below the calendar to adjust gradient, "
                "distance, time range, and minimum athletes — find shorter sprints, longer climbs, "
                "or more competitive segments."
                "</div>",
                unsafe_allow_html=True,
            )

        # ------------------------------------------------------------------
        # Tab 1b filter values (widgets render BELOW calendar, but values
        # must be read from session_state here so segment loading below
        # uses them. First run uses defaults; subsequent runs pick up user
        # changes via Streamlit's natural top-to-bottom rerun.
        # ------------------------------------------------------------------
        # Distance default (internal value is miles)
        if use_metric:
            _default_dist_miles = 25 * 0.621371  # 25 km default
        else:
            _default_dist_miles = 15.0  # 15 mi default
        max_distance = st.session_state.get(
            "tab1b_max_distance_mi", _default_dist_miles
        )

        gradient_range = st.session_state.get("tab1b_gradient_range", (3, 20))

        # Time range stored as (min_min, max_min) in MINUTES; convert to seconds
        _t_min_min, _t_max_min = st.session_state.get("tab1b_time_range_min", (0, 30))
        time_range = (_t_min_min * 60, _t_max_min * 60)

        min_athletes = st.session_state.get("tab1b_min_athletes", _region_min_athletes)

        # Load segments (cached)
        try:
            segments_df_1b = get_segments_for_region(
                DB_PATH, selected_region, max_distance
            )
            segments_df_1b = segments_df_1b[~segments_df_1b["id"].isin(flagged_ids)]
        except Exception as e:
            st.error(f"Error loading segments: {e}")
            segments_df_1b = pd.DataFrame()

        # Fetch forecast (cached)
        _today_key_1b = datetime.now().strftime("%Y-%m-%d")
        forecasts_1b = _fetch_forecast_cached(
            api_key, center_lat, center_lon, _today_key_1b
        )

        # Pre-compute segment bearings for wind opportunity scoring (cheap, one-time)
        seg_bearings = []
        if len(segments_df_1b) > 0:
            # Apply same filters as find_tailwind_segments would
            min_g, max_g = gradient_range
            filtered_1b = segments_df_1b[
                (segments_df_1b["avg_grade"] >= min_g)
                & (segments_df_1b["avg_grade"] <= max_g)
            ]
            if "athlete_count" in filtered_1b.columns and min_athletes > 0:
                filtered_1b = filtered_1b[
                    filtered_1b["athlete_count"].fillna(0) >= min_athletes
                ]
            for _, seg in filtered_1b.iterrows():
                bearing = calculate_segment_bearing(
                    seg["start_lat"], seg["start_lng"], seg["end_lat"], seg["end_lng"]
                )
                seg_bearings.append(bearing)

        # Build weather + wind opportunity data for all 8 days
        weather_rows = []
        day_labels = []
        day_forecasts = {}
        for day_offset in range(8):
            target_date = datetime.now() + timedelta(days=day_offset)
            afternoon_time = target_date.replace(
                hour=14, minute=0, second=0, microsecond=0
            )
            closest_fc = min(
                forecasts_1b,
                key=lambda f: abs((f["datetime"] - afternoon_time).total_seconds()),
            )
            day_forecasts[day_offset] = closest_fc

            if day_offset == 0:
                day_label = "Today"
            elif day_offset == 1:
                day_label = "Tomorrow"
            else:
                day_label = target_date.strftime("%a %b %d")
            day_labels.append(day_label)

            wind_cardinal = wind_direction_to_cardinal(closest_fc["wind_deg"])
            wind_speed_ms = closest_fc["wind_speed_ms"]

            if use_metric:
                temp_str = f"{closest_fc['temp_c']:.0f}°C"
                wind_str = f"{wind_speed_ms * 3.6:.0f} km/h {wind_cardinal}"
            else:
                temp_str = f"{closest_fc['temp_c'] * 9 / 5 + 32:.0f}°F"
                wind_str = f"{wind_speed_ms * 2.237:.0f} mph {wind_cardinal}"

            # Wind opportunity score:
            # For each segment, compute tailwind_pct for this day's wind direction.
            # Score = wind_speed * mean(top 10 tailwind percentages) / 100
            # High score = windy day where many segments get strong tailwinds
            wind_opp_score = 0
            if seg_bearings and wind_speed_ms > 0.5:
                tailwind_pcts = []
                for bearing in seg_bearings:
                    _, tw_pct = calculate_wind_angle(bearing, closest_fc["wind_deg"])
                    if tw_pct >= 50:  # Only count tailwind segments
                        tailwind_pcts.append(tw_pct)
                if tailwind_pcts:
                    # Top tailwind segments, weighted by wind speed
                    top_tw = sorted(tailwind_pcts, reverse=True)[:10]
                    avg_tw = sum(top_tw) / len(top_tw)
                    wind_opp_score = wind_speed_ms * avg_tw / 100

            if wind_opp_score >= 4:
                score_label = f'<span class="dp-wind-score dp-wind-high">★ {wind_opp_score:.1f}</span>'
            elif wind_opp_score >= 2:
                score_label = f'<span class="dp-wind-score dp-wind-med">{wind_opp_score:.1f}</span>'
            else:
                score_label = f'<span class="dp-wind-score dp-wind-low">{wind_opp_score:.1f}</span>'

            weather_rows.append(
                {
                    "day_label": day_label,
                    "temp_str": temp_str,
                    "wind_str": wind_str,
                    "conditions": closest_fc["description"].title(),
                    "wind_opp_score": wind_opp_score,
                    "score_html": score_label,
                }
            )

        # Layout: weather on left, segments on right
        col_weather, col_segments = st.columns([3, 4])

        with col_weather:
            if IS_MOBILE:
                st.markdown(f"##### 8-Day Forecast — {location_name}")
            else:
                st.markdown("##### 8-Day Forecast")

            # Build HTML weather table for better styling
            table_html = '<table class="weather-tbl" style="width:100%; border-collapse:collapse; font-size:1.05em;">'
            table_html += '<tr style="border-bottom:2px solid #4a5568;">'
            for h in ["Day", "Temp", "Wind", "Opp."]:
                table_html += f'<th style="padding:8px 10px; text-align:left; color:#e2e8f0; font-weight:600;">{h}</th>'
            table_html += "</tr>"

            for row in weather_rows:
                table_html += '<tr style="border-bottom:1px solid #2d3748;">'
                table_html += f'<td style="padding:7px 10px; color:#f1f5f9; font-weight:500;">{row["day_label"]}</td>'
                table_html += f'<td style="padding:7px 10px; color:#cbd5e1;">{row["temp_str"]}</td>'
                table_html += f'<td style="padding:7px 10px; color:#cbd5e1;">{row["wind_str"]}</td>'
                table_html += f'<td style="padding:7px 10px;">{row["score_html"]}</td>'
                table_html += "</tr>"
            table_html += "</table>"

            st.markdown(table_html, unsafe_allow_html=True)
            st.markdown("")
            st.markdown(
                '<div class="dp-info">'
                "<b>Opportunity</b> = wind speed × tailwind coverage. "
                "Higher means strong wind from an unusual direction that benefits many segments. "
                '<span class="dp-wind-score dp-wind-high">★ 4+</span> = rare opportunity, '
                '<span class="dp-wind-score dp-wind-med">2-4</span> = good, '
                '<span class="dp-wind-score dp-wind-low">&lt;2</span> = calm/unfavorable.'
                "</div>",
                unsafe_allow_html=True,
            )

            # -------------------------------------------------------------
            # Segment Filters (Tab 1b only) — rendered below the calendar.
            # Changes here trigger a Streamlit rerun, and the top-of-tab
            # code picks up the new values from session_state.
            # -------------------------------------------------------------
            st.markdown("")
            st.markdown("##### Segment Filters")
            # Distance filter — label reflects selected location/units
            if use_metric:
                _cur_km = int(round(max_distance / 0.621371))
                _cur_km = max(0, min(40, _cur_km))
                _max_km = st.slider(
                    f"Max distance from {location_name} (km)",
                    0,
                    40,
                    _cur_km,
                    5,
                    key="tab1b_max_distance_km",
                )
                st.session_state["tab1b_max_distance_mi"] = _max_km * 0.621371
            else:
                _cur_mi = int(round(max_distance))
                _cur_mi = max(0, min(25, _cur_mi))
                st.slider(
                    f"Max distance from {location_name} (miles)",
                    0,
                    25,
                    _cur_mi,
                    5,
                    key="tab1b_max_distance_mi_widget",
                )
                st.session_state["tab1b_max_distance_mi"] = st.session_state[
                    "tab1b_max_distance_mi_widget"
                ]

            # Gradient filter
            st.slider(
                "Average gradient (%)",
                min_value=-5,
                max_value=20,
                value=gradient_range,
                step=1,
                key="tab1b_gradient_range",
                help="Filter segments by average gradient",
            )

            # Time filter — 0 to 30 minutes (Tab 1b only)
            st.slider(
                "Estimated time (minutes)",
                min_value=0,
                max_value=30,
                value=(_t_min_min, _t_max_min),
                step=1,
                key="tab1b_time_range_min",
                help="Filter segments by your estimated completion time",
            )

            # Minimum athletes filter
            st.slider(
                "Min athletes on segment",
                min_value=10,
                max_value=10000,
                value=min_athletes,
                step=10,
                key="tab1b_min_athletes",
                help="Only show segments ridden by at least this many unique athletes",
            )

            # Entrance Speed — always visible, not a dropdown
            st.markdown("")
            st.markdown("##### Entrance Speed")
            if use_metric:
                _es_kmh = st.slider(
                    "Segment Entry Speed (km/h)",
                    min_value=0,
                    max_value=48,
                    value=26,
                    step=3,
                    key="tab1b_entrance_speed_kmh",
                    help="Speed you'll have when starting each segment",
                )
                entrance_speed = _es_kmh * 0.621371  # to mph for internal use
            else:
                entrance_speed = st.slider(
                    "Segment Entry Speed (mph)",
                    min_value=0,
                    max_value=30,
                    value=16,
                    step=2,
                    key="tab1b_entrance_speed_mph",
                    help="Speed you'll have when starting each segment",
                )

        with col_segments:
            # Day selector
            selected_day_label = st.selectbox(
                "Show segments for",
                day_labels,
                key="tab1b_day_select",
            )
            selected_day_offset = day_labels.index(selected_day_label)

            # Favorites-only toggle (only for signed-in users)
            show_favs_only = False
            if user and sb and SUPABASE_AVAILABLE:
                show_favs_only = st.checkbox(
                    "⭐ Show only favorite segments",
                    key="tab1b_favs_only",
                )

            if len(segments_df_1b) == 0:
                st.warning("No segments found. Adjust filters or check database.")
            else:
                closest_fc = day_forecasts[selected_day_offset]
                weather_conditions_1b = {
                    "temp_c": closest_fc["temp_c"],
                    "pressure_hpa": closest_fc["pressure_hpa"],
                    "wind_speed_ms": closest_fc["wind_speed_ms"],
                    "wind_angle": closest_fc["wind_deg"],
                }

                # Load user's favorites (if signed in)
                user_favorites = set()
                if user and sb and SUPABASE_AVAILABLE:
                    try:
                        sb_url = st.secrets["supabase"]["url"]
                        sb_key = st.secrets["supabase"]["key"]
                        user_favorites = get_favorites(str(user.id), sb_url, sb_key)
                    except Exception:
                        pass

                if show_favs_only and user_favorites:
                    # ── FAVORITES-ONLY MODE ──
                    # Simulate only favorited segments, rank by wind advantage
                    _fav_cache_key = (
                        frozenset(user_favorites),
                        selected_day_offset,
                        _today_key_1b,
                        entrance_speed,
                        power_1,
                        power_3,
                        power_8,
                        power_20,
                        weight_kg,
                        bike_weight,
                        cda,
                        crr,
                        show_qom,
                    )
                    if (
                        st.session_state.get("_tab1b_fav_cache_key") != _fav_cache_key
                        or "_tab1b_fav_segments" not in st.session_state
                    ):
                        with st.spinner("Simulating favorite segments..."):
                            fav_segments_df = segments_df_1b[
                                segments_df_1b["id"].isin(user_favorites)
                            ]
                            top_segments_1b = find_tailwind_segments(
                                fav_segments_df,
                                athlete,
                                entrance_speed,
                                weather_conditions_1b,
                                DB_PATH,
                                top_n=50,
                                gradient_range=(-10, 30),
                                time_range=(0, 9999),
                                min_tailwind_pct=0,
                                min_athletes=0,
                                use_qom=show_qom,
                            )
                            # Sort by wind advantage (most helped first)
                            top_segments_1b = sorted(
                                top_segments_1b,
                                key=lambda x: x.get("wind_advantage_s", 0),
                                reverse=True,
                            )
                        st.session_state["_tab1b_fav_cache_key"] = _fav_cache_key
                        st.session_state["_tab1b_fav_segments"] = top_segments_1b

                    top_segments_1b = st.session_state["_tab1b_fav_segments"]

                elif show_favs_only and not user_favorites:
                    st.info(
                        "You haven't favorited any segments yet. Use the ☆ checkbox on segment cards to add favorites."
                    )
                    top_segments_1b = []

                else:
                    # ── NORMAL MODE (tailwind-ranked) ──
                    _tab1b_cache_key = (
                        selected_region,
                        max_distance,
                        entrance_speed,
                        power_1,
                        power_3,
                        power_8,
                        power_20,
                        weight_kg,
                        bike_weight,
                        cda,
                        crr,
                        gradient_range,
                        time_range,
                        min_athletes,
                        frozenset(flagged_ids),
                        selected_day_offset,
                        _today_key_1b,
                        show_qom,
                    )
                    if (
                        st.session_state.get("_tab1b_cache_key") != _tab1b_cache_key
                        or "_tab1b_segments" not in st.session_state
                    ):
                        with st.spinner("Finding best tailwind segments..."):
                            top_segments_1b = find_tailwind_segments(
                                segments_df_1b,
                                athlete,
                                entrance_speed,
                                weather_conditions_1b,
                                DB_PATH,
                                top_n=15,
                                gradient_range=gradient_range,
                                time_range=time_range,
                                min_athletes=min_athletes,
                                use_qom=show_qom,
                            )
                        st.session_state["_tab1b_cache_key"] = _tab1b_cache_key
                        st.session_state["_tab1b_segments"] = top_segments_1b
                        # Reset show count when results change
                        for k in list(st.session_state.keys()):
                            if k.startswith("_tab1b_show_count_"):
                                del st.session_state[k]

                    top_segments_1b = st.session_state["_tab1b_segments"]

                # Render styled segment cards
                if top_segments_1b:
                    # Track how many to show (3 at a time)
                    _show_key = f"_tab1b_show_count_{selected_day_offset}"
                    if _show_key not in st.session_state:
                        st.session_state[_show_key] = 4
                    _show_count = min(st.session_state[_show_key], len(top_segments_1b))

                    for seg in top_segments_1b[:_show_count]:
                        strava_url = (
                            f"https://www.strava.com/segments/{seg['segment_id']}"
                        )
                        your_time_str = format_time(seg["your_time"])
                        kom_time_str = format_time(seg["kom_time"])
                        tailwind_pct = seg["tailwind_pct"]
                        wind_adv = seg.get("wind_advantage_s", 0)

                        # Pick card style — all inline, no CSS classes
                        _badge_base = "border-radius:4px; font-size:0.8em; font-weight:600; text-align:center;"
                        if IS_MOBILE:
                            _badge_base += " padding:4px 10px; white-space:nowrap; display:inline-block;"
                        else:
                            _badge_base += " padding:4px 0;"
                        if seg["time_behind"] < 0:
                            kom_badge = f'<div style="background:#166534; color:#bbf7d0; {_badge_base}">{abs(seg["time_behind"]):.0f}s faster than {_bench_label}!</div>'
                        elif seg["time_behind"] < 10:
                            kom_badge = f'<div style="background:#854d0e; color:#fef08a; {_badge_base}">{seg["time_behind"]:.0f}s off {_bench_label}</div>'
                        else:
                            kom_badge = f'<div style="background:#1e3a5f; color:#bfdbfe; {_badge_base}">{seg["time_behind"]:.0f}s off {_bench_label}</div>'

                        # Wind insight — single line combining tailwind %, wind speed, and time advantage
                        wind_adv = seg.get("wind_advantage_s", 0)
                        if use_metric:
                            wind_spd_str = (
                                f"{closest_fc['wind_speed_ms'] * 3.6:.0f} km/h"
                            )
                        else:
                            wind_spd_str = (
                                f"{closest_fc['wind_speed_ms'] * 2.237:.0f} mph"
                            )
                        if wind_adv > 0:
                            wind_insight = f'<div style="color:#94a3b8; font-size:0.78em; margin-top:4px;">{tailwind_pct:.0f}% tailwind at {wind_spd_str} is {wind_adv:.0f}s faster than calm conditions</div>'
                        else:
                            wind_insight = f'<div style="color:#94a3b8; font-size:0.78em; margin-top:4px;">{tailwind_pct:.0f}% tailwind at {wind_spd_str}</div>'

                        if use_metric:
                            dist_str = f"{seg['distance_km']:.1f} km"
                            elev_str = f"{seg['elevation_gain_m']:.0f} m"
                        else:
                            dist_str = f"{seg['distance_km'] * 0.621371:.2f} mi"
                            elev_str = f"{seg['elevation_gain_m'] * 3.28084:.0f} ft"

                        # Middle column stats
                        athlete_ct = seg.get("athlete_count") or 0
                        effort_ct = seg.get("effort_count") or 0
                        athlete_str = f"{athlete_ct:,}" if athlete_ct else "—"
                        effort_str = f"{effort_ct:,}" if effort_ct else "—"

                        # Build elevation sparkline SVG
                        elev_svg = '<div style="display:flex;align-items:center;justify-content:center;color:#4a5568;font-size:0.75em;height:100%;">No data</div>'
                        try:
                            elev_points = get_segment_elevation_profile(
                                DB_PATH, int(seg["segment_id"])
                            )
                            if elev_points and len(elev_points) >= 2:
                                elevations = [p[1] for p in elev_points]
                                distances = [p[0] for p in elev_points]
                                e_min, e_max = min(elevations), max(elevations)
                                d_min, d_max = min(distances), max(distances)
                                svg_w, svg_h = 500, 300
                                pad = 4
                                e_range = e_max - e_min if e_max > e_min else 1
                                d_range = d_max - d_min if d_max > d_min else 1

                                pts = []
                                for d, e in zip(distances, elevations):
                                    x = pad + (d - d_min) / d_range * (svg_w - 2 * pad)
                                    y = pad + (1 - (e - e_min) / e_range) * (
                                        svg_h - 2 * pad
                                    )
                                    pts.append(f"{x:.1f},{y:.1f}")

                                polyline = " ".join(pts)
                                fill_pts = (
                                    f"{pad},{svg_h - pad} "
                                    + " ".join(pts)
                                    + f" {svg_w - pad},{svg_h - pad}"
                                )

                                if use_metric:
                                    e_lo_str = f"{e_min:.0f}m"
                                    e_hi_str = f"{e_max:.0f}m"
                                else:
                                    e_lo_str = f"{e_min * 3.28084:.0f}ft"
                                    e_hi_str = f"{e_max * 3.28084:.0f}ft"

                                elev_svg = (
                                    f'<div style="position:relative; width:100%; height:100%;">'
                                    f'<svg viewBox="0 0 {svg_w} {svg_h}" preserveAspectRatio="none" '
                                    f'style="display:block; width:100%; height:100%;">'
                                    f'<polygon points="{fill_pts}" fill="rgba(34,197,94,0.15)" />'
                                    f'<polyline points="{polyline}" fill="none" stroke="#4ade80" stroke-width="4" />'
                                    f"</svg>"
                                    f'<span style="position:absolute; top:2px; left:4px; font-size:0.8em; color:#6b7280;">{e_hi_str}</span>'
                                    f'<span style="position:absolute; bottom:2px; left:4px; font-size:0.8em; color:#6b7280;">{e_lo_str}</span>'
                                    f"</div>"
                                )
                        except Exception:
                            pass

                        # Card background/border based on performance
                        if seg["time_behind"] < 0:
                            card_bg = "background:linear-gradient(135deg,#1a2e1a 0%,#163e21 100%); border-left:4px solid #22c55e;"
                        elif seg["time_behind"] < 10:
                            card_bg = "background:linear-gradient(135deg,#2e2a1a 0%,#3e3516 100%); border-left:4px solid #eab308;"
                        else:
                            card_bg = "background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%); border-left:4px solid #0ea5e9;"

                        card_parts = []
                        card_parts.append(
                            f'<div style="{card_bg} border-radius:12px; padding:12px 16px; margin-bottom:12px; color:#e2e8f0;">'
                        )

                        if IS_MOBILE:
                            # ── MOBILE LAYOUT ──
                            # Row 1: Segment name (full width)
                            card_parts.append(
                                f'<div class="seg-name" style="font-size:1.05em; font-weight:600; color:#f1f5f9; margin-bottom:8px;">'
                                f'<a href="{strava_url}" target="_blank" style="color:#93c5fd; text-decoration:none;">{seg["name"]} '
                                f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#93c5fd" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle; margin-left:2px;">'
                                f'<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg></a></div>'
                            )

                            # Row 2: Est Time | Power | KOM + badge inline
                            card_parts.append(
                                '<div style="display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:8px;">'
                            )
                            card_parts.append(
                                f'<div><div style="color:#94a3b8; font-size:0.68em; text-transform:uppercase; letter-spacing:0.04em;">Est. Time</div>'
                                f'<span style="font-size:1.2em; font-weight:700; color:#ffffff;">{your_time_str}</span></div>'
                            )
                            card_parts.append(
                                f'<div><div style="color:#94a3b8; font-size:0.68em; text-transform:uppercase; letter-spacing:0.04em;">Power</div>'
                                f'<span style="font-size:1.2em; font-weight:700; color:#f59e0b;">{seg["power"]:.0f}'
                                f'<span style="font-size:0.5em; color:#94a3b8;">W</span></span></div>'
                            )
                            card_parts.append(
                                f'<div style="display:flex; align-items:baseline; gap:8px;">'
                                f'<div><div style="color:#94a3b8; font-size:0.68em; text-transform:uppercase; letter-spacing:0.04em;">{_bench_label}</div>'
                                f'<span style="font-size:1.2em; font-weight:700; color:#e2e8f0;">{kom_time_str}</span></div>'
                                f'<div style="align-self:flex-end; margin-bottom:2px;">{kom_badge}</div>'
                                f"</div>"
                            )
                            card_parts.append("</div>")

                            # Row 3: Two columns — elevation plot (left) | metrics (right)
                            card_parts.append(
                                '<div style="display:flex; gap:10px; align-items:stretch;">'
                            )
                            # Left: elevation sparkline
                            card_parts.append(
                                f'<div style="flex:1; min-width:0; min-height:70px; max-height:90px;">{elev_svg}</div>'
                            )
                            # Right: segment metrics only
                            card_parts.append(
                                '<div style="flex:1; min-width:0; font-size:0.8em; line-height:1.6; display:flex; flex-direction:column; justify-content:center;">'
                            )
                            card_parts.append(
                                f'<div style="display:flex; justify-content:space-between;"><span style="color:#94a3b8;">Dist</span><span style="color:#e2e8f0;">{dist_str}</span></div>'
                            )
                            card_parts.append(
                                f'<div style="display:flex; justify-content:space-between;"><span style="color:#94a3b8;">Gain</span><span style="color:#e2e8f0;">{elev_str}</span></div>'
                            )
                            card_parts.append(
                                f'<div style="display:flex; justify-content:space-between;"><span style="color:#94a3b8;">Grade</span><span style="color:#e2e8f0;">{seg["avg_grade"]:.1f}%</span></div>'
                            )
                            card_parts.append(
                                f'<div style="display:flex; justify-content:space-between;"><span style="color:#94a3b8;">Athletes</span><span style="color:#e2e8f0;">{athlete_str}</span></div>'
                            )
                            card_parts.append(
                                f'<div style="display:flex; justify-content:space-between;"><span style="color:#94a3b8;">Efforts</span><span style="color:#e2e8f0;">{effort_str}</span></div>'
                            )
                            card_parts.append("</div>")  # close right metrics col
                            card_parts.append("</div>")  # close row 3 flex

                            # Row 4: Wind insight — full width across the bottom
                            card_parts.append(wind_insight)

                        else:
                            # ── DESKTOP LAYOUT (original 3-column) ──
                            card_parts.append(
                                '<div class="seg-card-inner" style="display:flex; gap:0; align-items:stretch; min-height:120px;">'
                            )
                            # LEFT column (flex:4)
                            card_parts.append(
                                '<div class="seg-card-left" style="flex:4; min-width:0; display:flex; flex-direction:column; justify-content:space-between; padding-right:14px;">'
                            )
                            card_parts.append("<div>")
                            card_parts.append(
                                f'<div class="seg-name" style="font-size:1.2em; font-weight:600; color:#f1f5f9; margin-bottom:6px;"><a href="{strava_url}" target="_blank" style="color:#93c5fd; text-decoration:none;">{seg["name"]} <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#93c5fd" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle; margin-left:2px;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg></a></div>'
                            )
                            card_parts.append(
                                '<div style="display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;">'
                            )
                            card_parts.append(
                                f'<div><div style="color:#94a3b8; font-size:0.75em; text-transform:uppercase; letter-spacing:0.05em;">Est. Time</div><span class="seg-big-num" style="font-size:1.5em; font-weight:700; color:#ffffff;">{your_time_str}</span></div>'
                            )
                            card_parts.append(
                                f'<div><div style="color:#94a3b8; font-size:0.75em; text-transform:uppercase; letter-spacing:0.05em;">Power</div><span class="seg-big-num" style="font-size:1.5em; font-weight:700; color:#f59e0b;">{seg["power"]:.0f}<span style="font-size:0.5em; color:#94a3b8;">W</span></span></div>'
                            )
                            card_parts.append(
                                f'<div><div style="color:#94a3b8; font-size:0.75em; text-transform:uppercase; letter-spacing:0.05em;">{_bench_label}</div><span class="seg-big-num" style="font-size:1.5em; font-weight:700; color:#e2e8f0;">{kom_time_str}</span></div>'
                            )
                            card_parts.append("</div></div>")
                            card_parts.append(f'<div style="margin-top:6px;">')
                            card_parts.append(kom_badge)
                            card_parts.append(wind_insight)
                            card_parts.append("</div>")
                            card_parts.append("</div>")
                            # MIDDLE column (flex:2)
                            card_parts.append(
                                '<div class="seg-card-mid" style="flex:2; display:flex; flex-direction:column; justify-content:center; border-left:1px solid #2d3748; border-right:1px solid #2d3748; padding:0 12px; min-width:80px;">'
                            )
                            card_parts.append(
                                '<div style="font-size:0.95em; line-height:1.7;">'
                            )
                            card_parts.append(
                                f'<div style="display:flex; justify-content:space-between;"><span style="color:#94a3b8;">Dist</span><span style="color:#e2e8f0;">{dist_str}</span></div>'
                            )
                            card_parts.append(
                                f'<div style="display:flex; justify-content:space-between;"><span style="color:#94a3b8;">Gain</span><span style="color:#e2e8f0;">{elev_str}</span></div>'
                            )
                            card_parts.append(
                                f'<div style="display:flex; justify-content:space-between;"><span style="color:#94a3b8;">Grade</span><span style="color:#e2e8f0;">{seg["avg_grade"]:.1f}%</span></div>'
                            )
                            card_parts.append(
                                f'<div style="display:flex; justify-content:space-between;"><span style="color:#94a3b8;">Athletes</span><span style="color:#e2e8f0;">{athlete_str}</span></div>'
                            )
                            card_parts.append(
                                f'<div style="display:flex; justify-content:space-between;"><span style="color:#94a3b8;">Efforts</span><span style="color:#e2e8f0;">{effort_str}</span></div>'
                            )
                            card_parts.append("</div></div>")
                            # RIGHT column (flex:3)
                            card_parts.append(
                                '<div class="seg-card-right" style="flex:3; min-width:100px; padding-left:12px; display:flex; align-items:stretch;">'
                            )
                            card_parts.append(elev_svg)
                            card_parts.append("</div>")
                            card_parts.append("</div>")  # close seg-card-inner

                        card_parts.append("</div>")  # close outer card div

                        card_html = "".join(card_parts)
                        st.markdown(card_html, unsafe_allow_html=True)

                        # Favorite checkbox (only for signed-in users)
                        if user and sb and SUPABASE_AVAILABLE:
                            seg_id_fav = int(seg["segment_id"])
                            is_fav = seg_id_fav in user_favorites
                            fav_checked = st.checkbox(
                                f"⭐ Favorite",
                                value=is_fav,
                                key=f"fav_{seg_id_fav}",
                            )
                            # Toggle if state changed
                            if fav_checked != is_fav:
                                toggle_favorite(sb, str(user.id), seg_id_fav)
                                st.rerun()

                    # Show More button (if more segments available)
                    _total_available = len(top_segments_1b)
                    if _show_count < _total_available:
                        _remaining = _total_available - _show_count
                        _next_batch = min(4, _remaining)
                        _label = f"Show {_next_batch} more segment{'s' if _next_batch > 1 else ''}"
                        if st.button(_label, key=f"_show_more_{selected_day_offset}"):
                            st.session_state[_show_key] = _show_count + 4
                            st.rerun()

                    # Simulator link below all cards
                    st.markdown(
                        '<div style="color:#94a3b8; font-size:0.85em; margin-top:8px; line-height:1.6;">'
                        "💡 Want optimized pacing for variable gradients? "
                        'Search for these segments in the <b style="color:#e2e8f0;">Segment Simulator</b> tab '
                        "to see split-by-split power targets and detailed forecasts."
                        "</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.warning("No tailwind segments found for this day.")

    # =============================
    # TAB: My Favorites
    # =============================
    if tab_favs is not None and user and sb and SUPABASE_AVAILABLE:
        with tab_favs:
            st.header("⭐ My Favorite Segments")

            # Load favorites
            try:
                sb_url = st.secrets["supabase"]["url"]
                sb_key = st.secrets["supabase"]["key"]
                fav_ids = get_favorites(str(user.id), sb_url, sb_key)
            except Exception:
                fav_ids = set()

            if not fav_ids:
                st.info(
                    "You haven't favorited any segments yet. "
                    "Use the ⭐ checkbox on segment cards in the Daily Planner or Segment Simulator tabs."
                )
            else:
                # Load ALL segments (not filtered by region) so favorites from any region show
                try:
                    conn_fav = sqlite3.connect(DB_PATH)
                    all_fav_segments = pd.read_sql(
                        """
                        SELECT id, name, distance_m, elevation_gain_m, avg_grade,
                               start_lat, start_lng, end_lat, end_lng, city, state
                        FROM segments
                        WHERE start_lat IS NOT NULL AND end_lat IS NOT NULL
                        """,
                        conn_fav,
                    )
                    conn_fav.close()
                    fav_df = all_fav_segments[
                        all_fav_segments["id"].isin(fav_ids)
                    ].copy()
                except Exception:
                    fav_df = pd.DataFrame()

                if len(fav_df) == 0:
                    st.warning(
                        "Could not load your favorited segments from the database."
                    )
                else:
                    # Assign region to each segment
                    def _assign_region(row):
                        closest = min(
                            REGIONS.items(),
                            key=lambda r: _haversine(
                                row["start_lat"],
                                row["start_lng"],
                                r[1]["lat"],
                                r[1]["lon"],
                            ),
                        )
                        return closest[0]

                    fav_df["_region"] = fav_df.apply(_assign_region, axis=1)

                    # Get today's weather for wind calculations
                    _today_key_fav = datetime.now().strftime("%Y-%m-%d")
                    forecasts_fav = _fetch_forecast_cached(
                        api_key, center_lat, center_lon, _today_key_fav
                    )
                    today_time = datetime.now().replace(
                        hour=14, minute=0, second=0, microsecond=0
                    )
                    today_fc = min(
                        forecasts_fav,
                        key=lambda f: abs((f["datetime"] - today_time).total_seconds()),
                    )
                    weather_fav = {
                        "temp_c": today_fc["temp_c"],
                        "pressure_hpa": today_fc["pressure_hpa"],
                        "wind_speed_ms": today_fc["wind_speed_ms"],
                        "wind_angle": today_fc["wind_deg"],
                    }

                    # Simulate each favorite segment
                    fav_rows = []
                    for _, seg in fav_df.iterrows():
                        seg_bearing = calculate_segment_bearing(
                            seg["start_lat"],
                            seg["start_lng"],
                            seg["end_lat"],
                            seg["end_lng"],
                        )
                        wind_angle, tailwind_pct = calculate_wind_angle(
                            seg_bearing, today_fc["wind_deg"]
                        )

                        segment_dict = {
                            "distance_m": seg["distance_m"],
                            "avg_grade": seg["avg_grade"],
                            "elevation_high_m": seg.get("elevation_gain_m", 0),
                            "elevation_low_m": 0,
                        }
                        seg_weather = weather_fav.copy()
                        seg_weather["wind_angle"] = wind_angle

                        try:
                            result = estimate_time_with_entrance_speed(
                                segment_dict,
                                athlete,
                                entrance_speed,
                                seg_weather,
                            )
                            your_time = result["total_time"]
                            power_w = result["sustainable_power"]
                        except Exception:
                            your_time = 9999
                            power_w = 0

                        try:
                            neutral_weather = seg_weather.copy()
                            neutral_weather["wind_speed_ms"] = 0
                            neutral_weather["wind_angle"] = 90
                            neutral_result = estimate_time_with_entrance_speed(
                                segment_dict,
                                athlete,
                                entrance_speed,
                                neutral_weather,
                            )
                            wind_impact = neutral_result["total_time"] - your_time
                        except Exception:
                            wind_impact = 0

                        kom_time = _get_kom_time(
                            DB_PATH, int(seg["id"]), use_qom=show_qom
                        )

                        if use_metric:
                            dist_val = seg["distance_m"] / 1000
                            elev_val = seg.get("elevation_gain_m", 0)
                        else:
                            dist_val = seg["distance_m"] / 1000 * 0.621371
                            elev_val = seg.get("elevation_gain_m", 0) * 3.28084

                        fav_rows.append(
                            {
                                "Segment": seg["name"],
                                "Region": seg["_region"].split(",")[0],
                                "Dist": round(dist_val, 2),
                                "Elev": round(elev_val, 0),
                                "Grade %": round(seg["avg_grade"], 1),
                                "Est. Time": (
                                    format_time(your_time) if your_time < 9999 else "—"
                                ),
                                "Power": int(power_w) if power_w > 0 else None,
                                _bench_label: (
                                    format_time(kom_time) if kom_time else "—"
                                ),
                                "Wind": f"{tailwind_pct:.0f}%",
                                "Impact": (
                                    f"{wind_impact:+.1f}s"
                                    if abs(wind_impact) >= 0.5
                                    else "—"
                                ),
                                "Link": f"https://www.strava.com/segments/{seg['id']}",
                                "_segment_id": int(seg["id"]),
                                "_wind_impact_sort": wind_impact,
                                "_time_sort": your_time,
                            }
                        )

                    # Sort alphabetically by segment name
                    fav_rows = sorted(fav_rows, key=lambda x: x["Segment"].lower())

                    # Summary caption
                    regions_represented = sorted(set(r["Region"] for r in fav_rows))
                    if use_metric:
                        wind_str = f"{today_fc['wind_speed_ms'] * 3.6:.0f} km/h"
                    else:
                        wind_str = f"{today_fc['wind_speed_ms'] * 2.237:.0f} mph"
                    st.caption(
                        f"**{len(fav_rows)} favorite(s)** across {len(regions_represented)} region(s) · "
                        f"Wind today: {wind_str} {wind_direction_to_cardinal(today_fc['wind_deg'])}"
                    )

                    # Build display dataframe
                    display_cols = [
                        "Segment",
                        "Region",
                        "Dist",
                        "Elev",
                        "Grade %",
                        "Est. Time",
                        "Power",
                        _bench_label,
                        "Wind",
                        "Impact",
                        "Link",
                    ]
                    fav_display_df = pd.DataFrame(fav_rows)[display_cols]

                    # Column config for nicer display
                    dist_label = "Dist (km)" if use_metric else "Dist (mi)"
                    elev_label = "Elev (m)" if use_metric else "Elev (ft)"

                    st.dataframe(
                        fav_display_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Segment": st.column_config.TextColumn(
                                "Segment", width="medium"
                            ),
                            "Region": st.column_config.TextColumn(
                                "Region", width="small"
                            ),
                            "Dist": st.column_config.NumberColumn(
                                dist_label, format="%.2f"
                            ),
                            "Elev": st.column_config.NumberColumn(
                                elev_label, format="%.0f"
                            ),
                            "Grade %": st.column_config.NumberColumn(
                                "Grade %", format="%.1f"
                            ),
                            "Est. Time": st.column_config.TextColumn("Est. Time"),
                            "Power": st.column_config.NumberColumn(
                                "Power (W)", format="%d"
                            ),
                            _bench_label: st.column_config.TextColumn(_bench_label),
                            "Wind": st.column_config.TextColumn("Tailwind"),
                            "Impact": st.column_config.TextColumn("Wind Δ"),
                            "Link": st.column_config.LinkColumn(
                                "Strava", display_text="Open"
                            ),
                        },
                    )

                    # Unfavorite option
                    with st.expander("Remove favorites", expanded=False):
                        for row in fav_rows:
                            seg_id = row["_segment_id"]
                            if st.checkbox(
                                f"Remove: {row['Segment']} ({row['Region']})",
                                key=f"unfav_{seg_id}",
                            ):
                                toggle_favorite(sb, str(user.id), seg_id)
                                st.rerun()

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

        # Searchable segment selector
        search_t2 = st.text_input(
            "🔍 Search by name or ID",
            placeholder="Type segment name or ID...",
            key="tab2_search",
        )
        if search_t2.strip():
            query = search_t2.strip().lower()
            mask = segments_list["name"].str.lower().str.contains(
                query, na=False
            ) | segments_list["id"].astype(str).str.contains(query, na=False)
            filtered = segments_list[mask]
        else:
            filtered = segments_list

        if len(filtered) == 0:
            st.warning(f"No segments matching '{search_t2}'")
            return

        display_options = [
            f"{row['name']}  (ID: {row['id']})" for _, row in filtered.iterrows()
        ]
        selected_display = st.selectbox(
            "Select Segment",
            display_options,
            key="tab2_segment_select",
        )
        selected_idx = display_options.index(selected_display)
        segment_id = filtered.iloc[selected_idx]["id"]
        segment_data = filtered.iloc[selected_idx]

        # Strava link and favorite toggle
        col_link, col_fav = st.columns([3, 1])
        with col_link:
            st.markdown(
                f"[🔗 View on Strava](https://www.strava.com/segments/{segment_id})",
                unsafe_allow_html=True,
            )
        with col_fav:
            if _is_signed_in and user and sb:
                try:
                    sb_url = st.secrets["supabase"]["url"]
                    sb_key = st.secrets["supabase"]["key"]
                    _t2_favs = get_favorites(str(user.id), sb_url, sb_key)
                except Exception:
                    _t2_favs = set()
                _t2_is_fav = int(segment_id) in _t2_favs
                _t2_fav_checked = st.checkbox(
                    "⭐ Favorite",
                    value=_t2_is_fav,
                    key=f"fav_t2_{segment_id}",
                )
                if _t2_fav_checked != _t2_is_fav:
                    toggle_favorite(sb, str(user.id), int(segment_id))
                    st.rerun()

        # Get KOM/QOM time for this segment (based on Show QOM toggle)
        kom_time = _get_kom_time(DB_PATH, int(segment_id), use_qom=show_qom)

        # ── Pre-compute everything needed for the metrics display ──
        # This block was previously interleaved between the top metrics
        # row and the parameter sliders. It now runs first so that on
        # mobile we can render all 7 metrics (static + simulated) in a
        # single 2-column HTML grid at the top of the page.

        # Segment dict used for several estimates below
        segment_dict_est = {
            "distance_m": segment_data["distance_m"],
            "avg_grade": segment_data["avg_grade"],
            "elevation_high_m": segment_data["elevation_gain_m"],
            "elevation_low_m": 0,
        }

        # Read Tab 2's own entrance speed AND wind condition from session_state.
        # The widgets render further down but we need their values here so the
        # Best Effort / KOM-match / Results calcs reflect current selections.
        # Falls back to slider defaults on first render.
        if use_metric:
            _t2_es_default_kmh = 32
            _t2_es_raw = st.session_state.get("tab2_entrance", _t2_es_default_kmh)
            entrance_speed_t2_early = _t2_es_raw * 0.621371  # km/h -> mph
        else:
            _t2_es_default_mph = 20
            entrance_speed_t2_early = st.session_state.get(
                "tab2_entrance", _t2_es_default_mph
            )

        # Build the same wind_options dict used by the slider below, so we can
        # translate the user's selection to wind_speed_ms + wind_angle BEFORE
        # the slider renders. Kept in sync with the slider block further down.
        if use_metric:
            _t2_wind_options = {
                "16 km/h tailwind": (10, 180),
                "8 km/h tailwind": (5, 180),
                "Neutral (0 km/h)": (0, 0),
                "8 km/h headwind": (5, 0),
                "16 km/h headwind": (10, 0),
                "24 km/h headwind": (15, 0),
            }
            _t2_wind_default = "Neutral (0 km/h)"
        else:
            _t2_wind_options = {
                "10 mph tailwind": (10, 180),
                "5 mph tailwind": (5, 180),
                "Neutral (0 mph)": (0, 0),
                "5 mph headwind": (5, 0),
                "10 mph headwind": (10, 0),
                "15 mph headwind": (15, 0),
            }
            _t2_wind_default = "Neutral (0 mph)"
        _t2_wind_sel_early = st.session_state.get("tab2_wind", _t2_wind_default)
        _t2_wind_mph_early, _t2_wind_angle_early = _t2_wind_options.get(
            _t2_wind_sel_early, (0, 0)
        )
        _t2_wind_ms_early = _t2_wind_mph_early * 0.44704

        weather_est = {
            "temp_c": 15,
            "pressure_hpa": 1013,
            "wind_speed_ms": _t2_wind_ms_early,
            "wind_angle": _t2_wind_angle_early,
        }

        # Estimate duration with a 3-min-power guess, then look up the correct
        # sustainable power for that actual duration.
        initial_guess_power = athlete.sustainable_power(3.0)
        est_result = estimate_time_with_entrance_speed(
            segment_dict_est,
            athlete,
            entrance_speed_t2_early,
            weather_est,
            target_power=initial_guess_power,
        )
        est_duration_minutes = est_result["total_time"] / 60
        natural_power = athlete.sustainable_power(est_duration_minutes)

        # Compute KOM-matching power if KOM exists
        optimized_power = None
        if kom_time:
            segment_dict_kom = {
                "distance_m": segment_data["distance_m"],
                "avg_grade": segment_data["avg_grade"],
                "elevation_high_m": segment_data["elevation_gain_m"],
                "elevation_low_m": 0,
            }
            weather_kom = {
                "temp_c": 15,
                "pressure_hpa": 1013,
                "wind_speed_ms": _t2_wind_ms_early,
                "wind_angle": _t2_wind_angle_early,
            }
            lo_p, hi_p = 100, 800
            for _ in range(15):
                mid_p = (lo_p + hi_p) / 2
                r_kom = estimate_time_with_entrance_speed(
                    segment_dict_kom,
                    athlete,
                    entrance_speed_t2_early,
                    weather_kom,
                    target_power=mid_p,
                )
                if abs(r_kom["total_time"] - kom_time) < 0.5:
                    optimized_power = int(mid_p)
                    break
                elif r_kom["total_time"] > kom_time:
                    lo_p = mid_p
                else:
                    hi_p = mid_p

        power_note = f"Best effort for these conditions: **{natural_power:.0f} W**"
        if optimized_power and kom_time:
            power_note += f" · To match {_bench_label} ({format_time(kom_time)}): **{optimized_power} W**"

        # Reset power slider when segment changes
        if st.session_state.get("_tab2_segment_id") != segment_id:
            st.session_state["_tab2_segment_id"] = segment_id
            st.session_state["tab2_power"] = int(natural_power)

        # Read the target power from session_state (set by the slider on a
        # prior render, or by the segment-change reset above on first render).
        _t2_target_power_early = st.session_state.get("tab2_power", int(natural_power))

        # Run the simulation with all current values (used by mobile top-grid
        # and by desktop col_results further down — avoids running twice).
        segment_dict = {
            "distance_m": segment_data["distance_m"],
            "avg_grade": segment_data["avg_grade"],
            "elevation_high_m": segment_data["elevation_gain_m"],
            "elevation_low_m": 0,
        }
        weather_conditions_early = {
            "temp_c": 15,
            "pressure_hpa": 1013,
            "wind_speed_ms": _t2_wind_ms_early,
            "wind_angle": _t2_wind_angle_early,
        }
        result = estimate_time_with_entrance_speed(
            segment_dict,
            athlete,
            entrance_speed_t2_early,
            weather_conditions_early,
            target_power=_t2_target_power_early,
        )

        # Build display strings for the simulated metrics
        your_time = result["total_time"]
        leaderboard_data = _get_leaderboard(
            DB_PATH, int(segment_id), 20, use_qom=show_qom
        )
        if leaderboard_data and kom_time:
            time_behind_kom = your_time - kom_time
            _time_display = f"{format_time(your_time)} ({time_behind_kom:+.0f}s)"
        else:
            _time_display = format_time(your_time)

        avg_speed_mph = result["cruise_speed_mph"]
        if use_metric:
            _speed_display = f"{avg_speed_mph * 1.60934:.1f} km/h"
        else:
            _speed_display = f"{avg_speed_mph:.1f} mph"
        _power_display = f"{_t2_target_power_early:.0f} W"

        # Pre-compute the static metric strings used in both layouts.
        if use_metric:
            _dist_display = f"{segment_data['distance_m']/1000:.2f} km"
            _elev_display = f"{segment_data['elevation_gain_m']:.0f} m"
        else:
            _dist_display = f"{segment_data['distance_m']/1000 * 0.621371:.2f} mi"
            _elev_display = f"{segment_data['elevation_gain_m'] * 3.28084:.0f} ft"
        _grade_display = f"{segment_data['avg_grade']:.1f}%"
        _kom_display = format_time(kom_time) if kom_time else "—"

        # ── Top metrics layout ──
        # Mobile: single HTML grid, 4 columns × 2 rows.
        #   Row 1: Distance | Elev Gain | Avg Grade | KOM
        #   Row 2: Est Time | Avg Speed | Power | (blank)
        # Pure HTML/CSS — not st.columns — so layout is guaranteed at any
        # viewport width regardless of Streamlit's auto-collapse behavior.
        # Desktop: 4-column row of st.metric widgets.
        if IS_MOBILE:
            _metric_html = f"""
            <style>
              .t2-metric-grid {{
                display: grid;
                grid-template-columns: 1.9fr 1.5fr 1.2fr 1fr;
                gap: 10px 6px;
                margin: 4px 0 12px 0;
              }}
              .t2-metric-cell {{
                padding: 2px 0;
                min-width: 0;
              }}
              .t2-metric-label {{
                font-size: 0.78rem;
                color: rgba(250, 250, 250, 0.6);
                line-height: 1.2;
                margin-bottom: 2px;
                text-transform: none;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
              }}
              .t2-metric-value {{
                font-size: 1.19rem;
                font-weight: 600;
                color: inherit;
                line-height: 1.2;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
              }}
            </style>
            <div class="t2-metric-grid">
              <div class="t2-metric-cell">
                <div class="t2-metric-label">Distance</div>
                <div class="t2-metric-value">{_dist_display}</div>
              </div>
              <div class="t2-metric-cell">
                <div class="t2-metric-label">Elev Gain</div>
                <div class="t2-metric-value">{_elev_display}</div>
              </div>
              <div class="t2-metric-cell">
                <div class="t2-metric-label">Avg Grade</div>
                <div class="t2-metric-value">{_grade_display}</div>
              </div>
              <div class="t2-metric-cell">
                <div class="t2-metric-label">🏆 {_bench_label}</div>
                <div class="t2-metric-value">{_kom_display}</div>
              </div>
              <div class="t2-metric-cell">
                <div class="t2-metric-label">⏱️ Est. Time</div>
                <div class="t2-metric-value">{_time_display}</div>
              </div>
              <div class="t2-metric-cell">
                <div class="t2-metric-label">🏁 Avg Speed</div>
                <div class="t2-metric-value">{_speed_display}</div>
              </div>
              <div class="t2-metric-cell">
                <div class="t2-metric-label">⚡ Power</div>
                <div class="t2-metric-value">{_power_display}</div>
              </div>
              <div class="t2-metric-cell"></div>
            </div>
            """
            st.markdown(_metric_html, unsafe_allow_html=True)
        else:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Distance", _dist_display)
            with col2:
                st.metric("Elevation Gain", _elev_display)
            with col3:
                st.metric("Average Grade", _grade_display)
            with col4:
                st.metric(f"🏆 {_bench_label}", _kom_display)

        # === Three-column layout: Parameters | Results | Elevation Profile ===
        # Load elevation data early so we can show it in the right column
        elev_points = get_segment_elevation_profile(DB_PATH, int(segment_id))

        col_params, col_results, col_elev = st.columns([3, 2, 4])

        with col_params:
            st.caption("**Adjust Parameters**")

            target_power = st.slider(
                "⚡ Power (W)",
                100,
                1000,
                int(natural_power),
                10,
                key="tab2_power",
            )

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
                key="tab2_wind",
            )
            wind_speed_mph, wind_direction = wind_options[wind_selection]
            wind_speed_ms = wind_speed_mph * 0.44704

            if use_metric:
                entrance_speed_t2 = (
                    st.slider(
                        "🏁 Entrance Speed (km/h)",
                        0,
                        48,
                        32,
                        3,
                        key="tab2_entrance",
                    )
                    * 0.621371
                )
            else:
                entrance_speed_t2 = st.slider(
                    "🏁 Entrance Speed (mph)",
                    0,
                    30,
                    20,
                    2,
                    key="tab2_entrance",
                )

            st.caption(power_note)

        # Run simulation
        temp_c = 15  # Use standard temperature
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
            entrance_speed_t2,
            weather_conditions,
            target_power=target_power,
        )

        with col_results:
            # Results caption only makes sense on desktop — on mobile, the
            # Est Time / Avg Speed / Power metrics render in the top HTML grid
            # instead of here (nothing to show in this column).
            if not IS_MOBILE:
                st.caption("**Results**")
                # Desktop: render the three results metrics. The display
                # strings (_time_display, _speed_display, _power_display)
                # were pre-computed at the top of this page.
                st.metric("⏱️ Estimated Time", _time_display)
                st.metric("🏁 Average Speed", _speed_display)
                st.metric("⚡ Power", _power_display)

        with col_elev:
            st.caption("**Elevation Profile**")
            if len(elev_points) >= 2:
                elev_dist = [p[0] for p in elev_points]
                elev_vals = [p[1] for p in elev_points]
                elev_grades = [p[2] if p[2] is not None else 0.0 for p in elev_points]

                if use_metric:
                    elev_chart_data = pd.DataFrame(
                        {
                            "Distance (km)": [round(d, 2) for d in elev_dist],
                            "Elevation (m)": [round(e, 1) for e in elev_vals],
                            "Grade (%)": [round(g, 1) for g in elev_grades],
                        }
                    )
                    x_col, y_col = "Distance (km)", "Elevation (m)"
                else:
                    elev_chart_data = pd.DataFrame(
                        {
                            "Distance (mi)": [
                                round(d * 0.621371, 2) for d in elev_dist
                            ],
                            "Elevation (ft)": [
                                round(e * 3.28084, 0) for e in elev_vals
                            ],
                            "Grade (%)": [round(g, 1) for g in elev_grades],
                        }
                    )
                    x_col, y_col = "Distance (mi)", "Elevation (ft)"

                y_vals = elev_chart_data[y_col]
                y_min, y_max = y_vals.min(), y_vals.max()
                y_range = max(y_max - y_min, 1)
                y_pad = y_range * 0.08
                y_domain = [float(y_min - y_pad), float(y_max + y_pad)]

                elev_chart = (
                    alt.Chart(elev_chart_data)
                    .mark_area(
                        opacity=0.4,
                        color="#F59E0B",
                        line={"color": "#D97706", "strokeWidth": 2},
                    )
                    .encode(
                        x=alt.X(x_col, axis=alt.Axis(format=".2f")),
                        y=alt.Y(y_col, scale=alt.Scale(domain=y_domain)),
                        tooltip=[
                            alt.Tooltip(x_col, format=".2f"),
                            alt.Tooltip(y_col, format=".0f"),
                            alt.Tooltip("Grade (%)", format=".1f"),
                        ],
                    )
                    .properties(height=280)
                    .interactive()
                )
                st.altair_chart(elev_chart, use_container_width=True)
            else:
                st.caption("No elevation data available")

        # =============================================
        # Advanced Gradient Analysis
        # =============================================
        st.markdown("---")

        if len(elev_points) < 2:
            st.warning(
                "No cleaned elevation data available for this segment in `clean_seg_points`."
            )
        else:
            # Convert to gradient sections using pre-computed grade_pct
            gradient_sections = elevation_to_gradient_sections(elev_points)

            if len(gradient_sections) == 0:
                st.warning("Could not compute gradient sections from elevation data.")
            else:
                elev_dist = [p[0] for p in elev_points]
                elev_vals = [p[1] for p in elev_points]
                elev_grades = [p[2] if p[2] is not None else 0.0 for p in elev_points]

                # Leaderboard
                with st.expander(f"🏆 Full {_bench_label} Leaderboard", expanded=False):
                    leaderboard_data = _get_leaderboard(
                        DB_PATH, int(segment_id), 20, use_qom=show_qom
                    )
                    if leaderboard_data:
                        your_time = result["total_time"]
                        lb_df = pd.DataFrame(
                            leaderboard_data[:10],
                            columns=[
                                "_rank",
                                "Athlete",
                                "_time_s",
                                "Power (W)",
                                "Date",
                            ],
                        )
                        lb_df["Time"] = lb_df["_time_s"].apply(format_time)
                        lb_df["Power (W)"] = lb_df["Power (W)"].apply(
                            lambda x: f"{x:.0f}" if pd.notna(x) and x else "—"
                        )
                        lb_df["Date"] = lb_df["Date"].fillna("—")

                        max_lb_time = max(
                            row[2] for row in leaderboard_data[:10] if row[2]
                        )
                        is_on_board = your_time <= max_lb_time
                        if is_on_board:
                            your_row = pd.DataFrame(
                                [
                                    {
                                        "_rank": 0,
                                        "Athlete": "YOU",
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

                        combined = combined.sort_values("_time_s").reset_index(
                            drop=True
                        )
                        combined["#"] = range(1, len(combined) + 1)
                        combined = combined[
                            ["#", "Athlete", "Date", "Time", "Power (W)"]
                        ]

                        def highlight_you(row):
                            return [
                                (
                                    "background-color: #2563EB22; font-weight: bold"
                                    if row["Athlete"] == "YOU"
                                    else ""
                                )
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
                        st.caption("No leaderboard data available.")

                st.markdown("---")

                # --- Reset optimizer state when segment or key params change ---
                _opt_trigger_key = (
                    segment_id,
                    entrance_speed_t2,
                    wind_selection,
                    power_1,
                    power_3,
                    power_8,
                    power_20,
                    weight_kg,
                    bike_weight,
                    cda,
                    crr,
                )
                if st.session_state.get("_opt_trigger_key") != _opt_trigger_key:
                    st.session_state["_opt_trigger_key"] = _opt_trigger_key
                    st.session_state["_run_optimizer"] = False
                    st.session_state.pop("_opt_cache_key", None)
                    st.session_state.pop("_opt_results", None)
                    st.session_state.pop("_opt_forecast_data", None)

                # --- Optimize button ---
                _has_cached_results = (
                    "_opt_results" in st.session_state
                    and st.session_state.get("_opt_results", {}).get("success", False)
                )

                # Only show the button if optimizer hasn't been run yet
                if not _has_cached_results:
                    col_btn, col_info = st.columns([1, 3])
                    with col_btn:
                        if st.button(
                            "⚡ Optimize!", type="primary", key="optimize_btn"
                        ):
                            st.session_state["_run_optimizer"] = True
                    with col_info:
                        if not st.session_state.get("_run_optimizer"):
                            st.caption(
                                f"Analyzes {len(gradient_sections)} gradient sections to find optimal power distribution"
                            )

                optimizer_active = st.session_state.get("_run_optimizer", False)

                if not optimizer_active and not _has_cached_results:
                    # --- Greyed-out placeholder content ---
                    st.markdown(
                        """
                        <div style="position: relative; opacity: 0.15; pointer-events: none; user-select: none; filter: grayscale(100%);">
                        """,
                        unsafe_allow_html=True,
                    )

                    # Placeholder metrics
                    st.subheader("Optimized Segment Power Profile")
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        st.metric("🟡 Avg-Grade Model", "—:——")
                    with col_b:
                        st.metric("🔵 Even Power (Variable Grade)", "—:——")
                    with col_c:
                        st.metric("🟢 Optimized Pacing", "—:——")

                    # Placeholder power chart
                    st.caption("**Power Output Along Segment**")
                    placeholder_df = pd.DataFrame(
                        {
                            "Distance": np.linspace(0, 1, 50),
                            "Power (W)": [300] * 50,
                            "Strategy": ["Even Power"] * 50,
                        }
                    )
                    placeholder_chart = (
                        alt.Chart(placeholder_df)
                        .mark_line(strokeWidth=2, color="#888888")
                        .encode(
                            x="Distance",
                            y=alt.Y("Power (W)", scale=alt.Scale(domain=[250, 400])),
                        )
                        .properties(height=200)
                    )
                    st.altair_chart(placeholder_chart, use_container_width=True)

                    st.markdown("</div>", unsafe_allow_html=True)

                    # Overlay message
                    st.markdown(
                        """
                        <div style="text-align: center; margin-top: -300px; margin-bottom: 250px; position: relative; z-index: 10;">
                            <div style="background: rgba(14,17,23,0.92); display: inline-block; padding: 1.5rem 2.5rem; border-radius: 12px; border: 1px solid #444; box-shadow: 0 4px 20px rgba(0,0,0,0.5);">
                                <p style="font-size: 1.4rem; color: #aaa; margin: 0 0 0.5rem 0;">
                                    Press <strong style="color: #f0f0f0;">⚡ Optimize!</strong> above
                                </p>
                                <p style="font-size: 0.95rem; color: #666; margin: 0;">
                                    to see optimized power distribution for this segment
                                </p>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                else:
                    # --- REAL optimizer content ---

                    # Use tab2's weather conditions for optimizer
                    avg_elevation = (
                        (elev_vals[0] + elev_vals[-1]) / 2 if elev_vals else 0
                    )
                    air_density_opt = compute_air_density_from_weather(
                        weather_conditions, avg_elevation
                    )

                    # Compute effective headwind for optimizer
                    _wind_angle_rad_opt = math.radians(weather_conditions["wind_angle"])
                    effective_headwind_opt = wind_speed_ms * math.cos(
                        _wind_angle_rad_opt
                    )

                    st.caption(
                        f"Optimizer uses {len(gradient_sections)} gradient sections from cleaned elevation data"
                    )

                    # Create optimizer athlete
                    opt_athlete = create_optimizer_athlete(
                        athlete, drivetrain_loss_pct=4
                    )

                    # Build optimizer sections
                    sections_opt = build_segment(gradient_sections)

                    # Cache optimizer results in session_state
                    _opt_cache_key = (
                        segment_id,
                        entrance_speed_t2,
                        power_1,
                        power_3,
                        power_8,
                        power_20,
                        weight_kg,
                        bike_weight,
                        cda,
                        crr,
                        wind_selection,
                        tuple((g, d) for g, d in gradient_sections),
                    )
                    if (
                        st.session_state.get("_opt_cache_key") != _opt_cache_key
                        or "_opt_results" not in st.session_state
                    ):
                        with st.spinner(
                            "Running optimizer (this may take a moment)..."
                        ):
                            try:
                                # Even-power simulation (constant power, variable grade)
                                est_time_init = (
                                    segment_total_distance(sections_opt) / 6.0
                                )
                                even_power_val = opt_athlete.max_power_for_duration(
                                    est_time_init
                                )
                                even_powers = [even_power_val] * len(sections_opt)

                                even_sim = optimizer_simulate_segment(
                                    sections_opt,
                                    even_powers,
                                    opt_athlete,
                                    entrance_speed_mph=entrance_speed_t2,
                                    air_density=air_density_opt,
                                    wind_speed_ms=effective_headwind_opt,
                                )
                                refined_power_val = opt_athlete.max_power_for_duration(
                                    even_sim["total_time"]
                                )
                                even_powers = [refined_power_val] * len(sections_opt)
                                even_sim = optimizer_simulate_segment(
                                    sections_opt,
                                    even_powers,
                                    opt_athlete,
                                    entrance_speed_mph=entrance_speed_t2,
                                    air_density=air_density_opt,
                                    wind_speed_ms=effective_headwind_opt,
                                )

                                # Optimized pacing
                                opt_result = optimize_power_profile(
                                    sections_opt,
                                    opt_athlete,
                                    entrance_speed_mph=entrance_speed_t2,
                                    air_density=air_density_opt,
                                    wind_speed_ms=effective_headwind_opt,
                                )

                                # Re-simulate optimized powers at dt=0.5
                                # so the display profile has the same point
                                # density as even_sim (which also uses dt=0.5)
                                opt_sim = optimizer_simulate_segment(
                                    sections_opt,
                                    opt_result["optimal_powers"],
                                    opt_athlete,
                                    entrance_speed_mph=entrance_speed_t2,
                                    air_density=air_density_opt,
                                    wind_speed_ms=effective_headwind_opt,
                                )
                                opt_sim["optimal_powers"] = opt_result["optimal_powers"]

                                # Flat equivalent baseline
                                flat_sim = simulate_flat_equivalent(
                                    sections_opt,
                                    opt_athlete,
                                    entrance_speed_mph=entrance_speed_t2,
                                    air_density=air_density_opt,
                                    wind_speed_ms=effective_headwind_opt,
                                )

                                st.session_state["_opt_cache_key"] = _opt_cache_key
                                st.session_state["_opt_results"] = {
                                    "even_sim": even_sim,
                                    "opt_sim": opt_sim,
                                    "flat_sim": flat_sim,
                                    "success": True,
                                }
                            except Exception as e:
                                st.error(f"Optimizer error: {e}")
                                import traceback

                                st.code(traceback.format_exc())
                                st.session_state["_opt_cache_key"] = _opt_cache_key
                                st.session_state["_opt_results"] = {"success": False}

                    _opt_cached = st.session_state["_opt_results"]
                    optimization_success = _opt_cached["success"]
                    if optimization_success:
                        even_sim = _opt_cached["even_sim"]
                        opt_sim = _opt_cached["opt_sim"]
                        flat_sim = _opt_cached["flat_sim"]

                    if optimization_success:
                        # ---- Optimized Segment Power Profile ----
                        st.subheader("Optimized Segment Power Profile")

                        # ---- Results Summary ----
                        col_a, col_b, col_c = st.columns(3)
                        with col_a:
                            flat_time = flat_sim["total_time"]
                            st.metric(
                                "🟡 Avg-Grade Model",
                                format_time(flat_time),
                                help="Constant power, average gradient (basic model)",
                            )
                        with col_b:
                            even_time = even_sim["total_time"]
                            delta_even = even_time - flat_time
                            st.metric(
                                "🔵 Even Power (Variable Grade)",
                                format_time(even_time),
                                delta=f"{delta_even:+.1f}s vs basic",
                                delta_color="inverse",
                                help="Constant power across real gradient sections",
                            )
                        with col_c:
                            opt_time = opt_sim["total_time"]
                            delta_opt = opt_time - flat_time
                            st.metric(
                                "🟢 Optimized Pacing",
                                format_time(opt_time),
                                delta=f"{delta_opt:+.1f}s vs basic",
                                delta_color="inverse",
                                help="Optimizer finds best power for each section",
                            )

                        # Show optimal powers per section
                        if "optimal_powers" in opt_sim and opt_sim["optimal_powers"]:
                            opt_powers = opt_sim["optimal_powers"]
                            with st.expander(
                                "Optimal Power per Section", expanded=False
                            ):
                                opt_rows = []
                                for i, (grade, dist_mi) in enumerate(gradient_sections):
                                    pw = opt_powers[i] if i < len(opt_powers) else 0
                                    dist_m = dist_mi * MILES_TO_METERS
                                    sr = (
                                        opt_sim["section_results"][i]
                                        if i < len(opt_sim.get("section_results", []))
                                        else {}
                                    )
                                    sec_time = sr.get("time_s", 0)
                                    opt_rows.append(
                                        {
                                            "#": i + 1,
                                            "Grade (%)": f"{grade:.1f}",
                                            "Distance": (
                                                f"{dist_m:.0f} m"
                                                if use_metric
                                                else f"{dist_mi:.3f} mi"
                                            ),
                                            "Optimal Power (W)": f"{pw:.0f}",
                                            "Section Time": (
                                                format_time(sec_time)
                                                if sec_time > 0
                                                else "—"
                                            ),
                                        }
                                    )
                                st.dataframe(
                                    pd.DataFrame(opt_rows),
                                    use_container_width=True,
                                    hide_index=True,
                                )

                        # ---- Power Profile Chart ----
                        opt_d = opt_sim["distance_profile"] / MILES_TO_METERS
                        even_d = even_sim["distance_profile"] / MILES_TO_METERS

                        if use_metric:
                            x_label = "Distance (km)"
                            opt_x = opt_d / 0.621371
                            even_x = even_d / 0.621371
                        else:
                            x_label = "Distance (mi)"
                            opt_x = opt_d
                            even_x = even_d

                        # --- Smoothing helper ---
                        def smooth_profile(values, window=15):
                            """Rolling average smoothing that preserves array length."""
                            arr = np.asarray(values, dtype=float)
                            if len(arr) < window * 2:
                                return arr
                            kernel = np.ones(window) / window
                            smoothed = np.convolve(arr, kernel, mode="same")
                            half = window // 2
                            smoothed[:half] = arr[:half]
                            smoothed[-half:] = arr[-half:]
                            return smoothed

                        # --- Smooth the profiles and remove startup artifact ---
                        # The simulation records 0W at t=0 and ramps up over the
                        # first few timesteps, creating a steep dip.  Clamp the
                        # initial low-power points to the first stable value so
                        # the smoothing kernel doesn't bleed the dip into the plot.
                        def _clamp_startup(power_arr):
                            """Replace initial low-power ramp-up with the first stable value."""
                            arr = np.array(power_arr, dtype=float)
                            if len(arr) < 10:
                                return arr
                            # Find a stable reference: median of points 5-25
                            ref = np.median(arr[5 : min(25, len(arr))])
                            # Threshold: anything below 70% of reference is startup noise
                            threshold = ref * 0.70
                            for i in range(min(30, len(arr))):
                                if arr[i] < threshold:
                                    arr[i] = ref
                                else:
                                    break
                            return arr

                        opt_power_clamped = _clamp_startup(
                            opt_sim["power_actual_profile"]
                        )
                        even_power_clamped = _clamp_startup(
                            even_sim["power_actual_profile"]
                        )

                        opt_power_smooth = smooth_profile(opt_power_clamped)
                        even_power_smooth = smooth_profile(even_power_clamped)

                        # Skip first few points to avoid any residual edge effects
                        skip = 3

                        # --- Build DataFrames, skip initial ramp-up points ---
                        opt_power_df = pd.DataFrame(
                            {
                                x_label: opt_x[skip:],
                                "Power (W)": np.round(opt_power_smooth[skip:], 0),
                                "Strategy": "Optimized",
                            }
                        )
                        even_power_df = pd.DataFrame(
                            {
                                x_label: even_x[skip:],
                                "Power (W)": np.round(even_power_smooth[skip:], 0),
                                "Strategy": "Even Power",
                            }
                        )
                        power_chart_data = pd.concat(
                            [opt_power_df, even_power_df], ignore_index=True
                        )

                        st.caption("**Power Output Along Segment**")
                        power_chart = (
                            alt.Chart(power_chart_data)
                            .mark_line(strokeWidth=2)
                            .encode(
                                x=alt.X(x_label, axis=alt.Axis(format=".2f")),
                                y=alt.Y("Power (W)", scale=alt.Scale(zero=False)),
                                color=alt.Color(
                                    "Strategy",
                                    scale=alt.Scale(
                                        domain=["Optimized", "Even Power"],
                                        range=["#16A34A", "#2563EB"],
                                    ),
                                    legend=alt.Legend(
                                        orient="top",
                                        direction="horizontal",
                                    ),
                                ),
                                tooltip=[
                                    alt.Tooltip(x_label, format=".3f"),
                                    alt.Tooltip("Power (W)", format=".0f"),
                                    alt.Tooltip("Strategy"),
                                ],
                            )
                            .interactive()
                        )
                        st.altair_chart(power_chart, use_container_width=True)

                        # =============================================
                        # Compute optimizer forecast data for the main table
                        # =============================================
                        if "_opt_forecast_data" not in st.session_state:
                            with st.status(
                                "Computing optimized 7-day forecast...", expanded=False
                            ) as _opt_status:
                                seg_bearing_opt = calculate_segment_bearing(
                                    segment_data["start_lat"],
                                    segment_data["start_lng"],
                                    segment_data["end_lat"],
                                    segment_data["end_lng"],
                                )

                                _today_key_opt = datetime.now().strftime("%Y-%m-%d")
                                forecasts_opt = _fetch_forecast_cached(
                                    api_key, center_lat, center_lon, _today_key_opt
                                )

                                opt_forecast_data = []
                                for day_offset in range(8):
                                    target_date = datetime.now() + timedelta(
                                        days=day_offset
                                    )
                                    afternoon_time = target_date.replace(
                                        hour=14, minute=0, second=0, microsecond=0
                                    )

                                    closest_fc = min(
                                        forecasts_opt,
                                        key=lambda f: abs(
                                            (
                                                f["datetime"] - afternoon_time
                                            ).total_seconds()
                                        ),
                                    )

                                    wind_angle_fc, tailwind_pct_fc = (
                                        calculate_wind_angle(
                                            seg_bearing_opt, closest_fc["wind_deg"]
                                        )
                                    )

                                    day_weather = {
                                        "temp_c": closest_fc["temp_c"],
                                        "pressure_hpa": closest_fc["pressure_hpa"],
                                        "wind_speed_ms": closest_fc["wind_speed_ms"],
                                        "wind_angle": wind_angle_fc,
                                    }

                                    avg_elevation = (
                                        (elev_vals[0] + elev_vals[-1]) / 2
                                        if elev_vals
                                        else 0
                                    )
                                    day_air_density = compute_air_density_from_weather(
                                        day_weather, avg_elevation
                                    )
                                    _day_wind_angle_rad = math.radians(
                                        day_weather["wind_angle"]
                                    )
                                    day_effective_headwind = day_weather[
                                        "wind_speed_ms"
                                    ] * math.cos(_day_wind_angle_rad)

                                    # Even power time
                                    try:
                                        day_even_power = (
                                            opt_athlete.max_power_for_duration(
                                                max(
                                                    30,
                                                    segment_total_distance(sections_opt)
                                                    / 6.0,
                                                )
                                            )
                                        )
                                        day_even_sim = optimizer_simulate_segment(
                                            sections_opt,
                                            [day_even_power] * len(sections_opt),
                                            opt_athlete,
                                            entrance_speed_mph=entrance_speed_t2,
                                            air_density=day_air_density,
                                            wind_speed_ms=day_effective_headwind,
                                        )
                                        day_refined_power = (
                                            opt_athlete.max_power_for_duration(
                                                day_even_sim["total_time"]
                                            )
                                        )
                                        day_even_sim = optimizer_simulate_segment(
                                            sections_opt,
                                            [day_refined_power] * len(sections_opt),
                                            opt_athlete,
                                            entrance_speed_mph=entrance_speed_t2,
                                            air_density=day_air_density,
                                            wind_speed_ms=day_effective_headwind,
                                        )
                                        day_time_dynamic = day_even_sim["total_time"]
                                    except Exception:
                                        day_time_dynamic = 9999
                                        day_refined_power = 0

                                    # Optimized time
                                    try:
                                        day_opt_sim = optimize_power_profile(
                                            sections_opt,
                                            opt_athlete,
                                            entrance_speed_mph=entrance_speed_t2,
                                            air_density=day_air_density,
                                            wind_speed_ms=day_effective_headwind,
                                        )
                                        day_time_optimized = day_opt_sim["total_time"]
                                    except Exception:
                                        day_time_optimized = day_time_dynamic

                                    opt_forecast_data.append(
                                        {
                                            "opt_time": format_time(day_time_optimized),
                                            "even_time": format_time(day_time_dynamic),
                                            "even_power": (
                                                f"{day_refined_power:.0f}"
                                                if day_refined_power > 0
                                                else "—"
                                            ),
                                        }
                                    )

                                _opt_status.update(
                                    label="✅ Optimized forecast complete",
                                    state="complete",
                                )

                            st.session_state["_opt_forecast_data"] = opt_forecast_data
                            st.rerun()

        # =============================================
        # 7-Day Segment Forecast
        # =============================================
        st.caption("**📅 7-Day Segment Forecast**")

        # Show computing note if optimizer is active but forecast data not ready
        _optimizer_active_check = st.session_state.get("_run_optimizer", False)
        _opt_forecast_ready = st.session_state.get("_opt_forecast_data") is not None
        if _optimizer_active_check and not _opt_forecast_ready:
            st.markdown(
                '<div style="display:flex; align-items:center; gap:8px; padding:8px 12px; '
                'background:#1e293b; border:1px solid #334155; border-radius:8px; margin-bottom:12px;">'
                '<div style="width:16px; height:16px; border:2px solid #3b82f6; border-top-color:transparent; '
                'border-radius:50%; animation:spin 1s linear infinite;"></div>'
                '<span style="color:#94a3b8; font-size:0.85em;">Computing optimized forecast — optimizer columns will update shortly</span>'
                "</div>"
                "<style>@keyframes spin { to { transform: rotate(360deg); } }</style>",
                unsafe_allow_html=True,
            )

        seg_bearing = calculate_segment_bearing(
            segment_data["start_lat"],
            segment_data["start_lng"],
            segment_data["end_lat"],
            segment_data["end_lng"],
        )

        _today_key = datetime.now().strftime("%Y-%m-%d")
        forecasts_tab2 = _fetch_forecast_cached(
            api_key, center_lat, center_lon, _today_key
        )

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

            wind_angle, tailwind_pct = calculate_wind_angle(
                seg_bearing, closest_fc["wind_deg"]
            )

            day_weather = {
                "temp_c": closest_fc["temp_c"],
                "pressure_hpa": closest_fc["pressure_hpa"],
                "wind_speed_ms": closest_fc["wind_speed_ms"],
                "wind_angle": wind_angle,
            }

            day_result = estimate_time_with_entrance_speed(
                segment_dict, athlete, entrance_speed_t2, day_weather
            )
            day_time = day_result["total_time"]
            day_power = day_result["sustainable_power"]

            day_kom_power = None
            if kom_time:
                lo, hi = 50, 1200
                for _ in range(20):
                    mid = (lo + hi) / 2
                    r = estimate_time_with_entrance_speed(
                        segment_dict,
                        athlete,
                        entrance_speed_t2,
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
                else:
                    # Converged but didn't hit 0.5s tolerance
                    if lo < 1100:
                        day_kom_power = int(mid)

            if day_offset == 0:
                day_label = "Today"
            elif day_offset == 1:
                day_label = "Tomorrow"
            else:
                day_label = target_date.strftime("%a %b %d")

            wind_cardinal = wind_direction_to_cardinal(closest_fc["wind_deg"])
            if use_metric:
                wind_speed_display = closest_fc["wind_speed_ms"] * 3.6
                wind_unit = "km/h"
            else:
                wind_speed_display = closest_fc["wind_speed_ms"] * 2.237
                wind_unit = "mph"

            gust_ms = closest_fc.get("wind_gust_ms") or closest_fc.get("wind_gust") or 0
            if use_metric:
                gust_display = f"{gust_ms * 3.6:.0f} {wind_unit}" if gust_ms else "—"
                temp_display = f"{closest_fc['temp_c']:.0f}°C"
            else:
                gust_display = f"{gust_ms * 2.237:.0f} {wind_unit}" if gust_ms else "—"
                temp_display = f"{closest_fc['temp_c'] * 9 / 5 + 32:.0f}°F"

            forecast_rows.append(
                {
                    "Day": day_label,
                    "Temp": temp_display,
                    "Wind (2pm)": f"{wind_speed_display:.0f} {wind_unit} {wind_cardinal}",
                    "Gust": gust_display,
                    "Effect": f"💨 {tailwind_pct:.0f}% tailwind",
                    "Est. Time": format_time(day_time),
                    "Power (W)": f"{day_power:.0f}",
                    f"{_bench_label} Power": (
                        f"{day_kom_power}" if day_kom_power else "—"
                    ),
                    "Opt. Time": "—",
                    "Even Time": "—",
                    "Even W": "—",
                }
            )

        # If optimizer has been run, merge in the optimized forecast data
        _opt_forecast = st.session_state.get("_opt_forecast_data")
        if _opt_forecast and len(_opt_forecast) == len(forecast_rows):
            for i, opt_row in enumerate(_opt_forecast):
                forecast_rows[i]["Opt. Time"] = opt_row.get("opt_time", "—")
                forecast_rows[i]["Even Time"] = opt_row.get("even_time", "—")
                forecast_rows[i]["Even W"] = opt_row.get("even_power", "—")

        forecast_df = pd.DataFrame(forecast_rows)

        # Hide basic model columns when optimizer data is available
        _has_opt_data = (
            _opt_forecast
            and len(_opt_forecast) == len(forecast_rows)
            and _opt_forecast[0].get("opt_time") != "—"
        )
        if _has_opt_data:
            forecast_df = forecast_df.drop(
                columns=["Est. Time", "Power (W)"], errors="ignore"
            )

        # On mobile, move Effect to the last column so the important
        # time/power columns are visible without scrolling
        if IS_MOBILE:
            cols = [c for c in forecast_df.columns if c != "Effect"] + ["Effect"]
            forecast_df = forecast_df[cols]

        # Determine best day based on best available time column
        _best_time_col = "Opt. Time" if _has_opt_data else "Est. Time"
        if _best_time_col in forecast_df.columns:
            best_day_label = min(forecast_rows, key=lambda r: r[_best_time_col])["Day"]
        else:
            best_day_label = forecast_rows[0]["Day"]
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

        # =============================
        # TAB 4: Segment Requests
        # =============================
    with tab4:
        st.header("Request New Segments")
        st.caption(
            "Submit Strava segment IDs to be added to the database. "
            "Requests are queued and processed periodically by the admin."
        )

        # --- Submit form ---
        st.subheader("Submit a Request")
        st.caption(
            "Find segment IDs from Strava URLs — e.g. strava.com/segments/**619307**"
        )

        col_input, col_info = st.columns([2, 1])
        with col_input:
            segment_ids_input = st.text_area(
                "Segment IDs",
                placeholder="Enter one or more segment IDs, separated by commas or newlines\n\nExample:\n619307\n624537, 785087",
                height=120,
                key="request_ids_input",
            )
            requested_by = st.text_input(
                "Your name (optional)",
                placeholder="e.g. Alex",
                key="request_name",
            )
            notes = st.text_input(
                "Notes (optional)",
                placeholder="e.g. Great hill near Greenlake",
                key="request_notes",
            )

        with col_info:
            st.markdown(
                """
            **How to find a segment ID:**

            1. Go to [strava.com](https://www.strava.com)
            2. Find a segment page
            3. The ID is the number in the URL:
               `strava.com/segments/`**`619307`**

            You can submit multiple IDs at once.
            """
            )

        submit_clicked = st.button(
            "📬 Submit Request", type="primary", key="submit_request"
        )

        if submit_clicked and segment_ids_input.strip():
            # Parse IDs from input
            raw = segment_ids_input.replace(",", " ").replace("\n", " ").split()
            parsed_ids = []
            bad_ids = []
            for token in raw:
                token = token.strip()
                if not token:
                    continue
                if "/" in token:
                    token = token.rstrip("/").split("/")[-1]
                try:
                    parsed_ids.append(int(token))
                except ValueError:
                    bad_ids.append(token)

            if bad_ids:
                st.warning(f"Could not parse: {', '.join(bad_ids)}")

            if parsed_ids:
                # Check which are already in segments database
                conn_seg_check = sqlite3.connect(DB_PATH)
                cur_seg_check = conn_seg_check.cursor()
                placeholders = ",".join("?" * len(parsed_ids))
                cur_seg_check.execute(
                    f"SELECT id FROM segments WHERE id IN ({placeholders})",
                    parsed_ids,
                )
                already_in_db = set(r[0] for r in cur_seg_check.fetchall())
                conn_seg_check.close()

                # Check which are already pending in Supabase
                already_requested = get_pending_segment_ids()

                submitted = []
                skipped_db = []
                skipped_pending = []

                for sid in parsed_ids:
                    if sid in already_in_db:
                        skipped_db.append(sid)
                    elif sid in already_requested:
                        skipped_pending.append(sid)
                    else:
                        _req_user_id = str(user.id) if user else None
                        _req_user_email = user.email if user else None
                        submit_segment_request(
                            sid,
                            requested_by=requested_by.strip() or None,
                            user_id=_req_user_id,
                            user_email=_req_user_email,
                            notes=notes.strip() or None,
                        )
                        submitted.append(sid)

                if submitted:
                    st.success(
                        f"Submitted {len(submitted)} segment(s): {', '.join(str(s) for s in submitted)}"
                    )
                if skipped_db:
                    st.info(
                        f"Already in database: {', '.join(str(s) for s in skipped_db)}"
                    )
                if skipped_pending:
                    st.info(
                        f"Already pending: {', '.join(str(s) for s in skipped_pending)}"
                    )

        elif submit_clicked:
            st.warning("Please enter at least one segment ID")

        # --- Request queue display ---
        st.markdown("---")
        st.subheader("Request Queue")

        pending = get_pending_requests()

        if pending:
            st.caption(f"**{len(pending)} pending request(s)** — awaiting processing")
            pending_df = pd.DataFrame(pending)
            pending_df.columns = ["Segment ID", "Requested By", "Notes", "Requested At"]
            pending_df["Requested By"] = pending_df["Requested By"].fillna("—")
            pending_df["Notes"] = pending_df["Notes"].fillna("—")
            pending_df["Strava Link"] = pending_df["Segment ID"].apply(
                lambda sid: f"https://strava.com/segments/{sid}"
            )
            st.dataframe(
                pending_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Strava Link": st.column_config.LinkColumn(
                        "Strava Link", display_text="Open"
                    ),
                },
            )
        else:
            st.caption("No pending requests")

        # Recently processed
        processed = get_processed_requests()

        if processed:
            with st.expander(f"Recently processed ({len(processed)})", expanded=False):
                proc_df = pd.DataFrame(processed)
                proc_df.columns = [
                    "Segment ID",
                    "Requested By",
                    "Status",
                    "Requested",
                    "Processed",
                ]
                proc_df["Requested By"] = proc_df["Requested By"].fillna("—")
                st.dataframe(proc_df, use_container_width=True, hide_index=True)

        # --- Admin instructions ---
        with st.expander("🔧 Admin: How to process requests"):
            st.markdown(
                """
            Run this command to process all pending segment requests:

            ```bash
            python pipeline.py process-requests
            ```

            Or manually with specific IDs:

            ```bash
            python pipeline.py full --ids 619307 624537
            ```

            After processing, run `scraperSel.py` to fetch leaderboard data
            for the new segments.
            """
            )

    # =============================
    # TAB 5: Flagged Segments
    # =============================
    with tab5:
        st.header("Excluded Segments")
        st.caption(
            "Exclude segments from all tabs. "
            "Useful for segments with inaccurate GPS, odd turns, or bad data."
        )

        # --- Flag a segment ---
        st.subheader("Exclude a Segment")
        col_flag_id, col_flag_reason = st.columns([1, 2])
        with col_flag_id:
            flag_id_input = st.text_input(
                "Segment ID",
                placeholder="e.g. 8587047",
                key="flag_segment_id",
            )
        with col_flag_reason:
            flag_reason = st.text_input(
                "Reason (optional)",
                placeholder="e.g. Many odd turns, GPS issues",
                key="flag_reason",
            )

        flag_clicked = st.button("🚫 Exclude Segment", type="primary", key="flag_btn")

        if flag_clicked and flag_id_input.strip():
            try:
                seg_id = int(flag_id_input.strip())
                if seg_id in flagged_ids:
                    st.info(f"Segment {seg_id} is already excluded.")
                else:
                    # Verify the segment exists
                    conn_check = sqlite3.connect(DB_PATH)
                    cur_check = conn_check.cursor()
                    cur_check.execute(
                        "SELECT name FROM segments WHERE id = ?", (seg_id,)
                    )
                    seg_row = cur_check.fetchone()
                    conn_check.close()

                    if seg_row:
                        flag_segment(seg_id, flag_reason.strip())
                        st.success(
                            f"Excluded segment {seg_id} ({seg_row[0]}). "
                            "It will be hidden from all tabs."
                        )
                        st.rerun()
                    else:
                        st.warning(f"Segment {seg_id} not found in database.")
            except ValueError:
                st.warning("Please enter a valid numeric segment ID.")
        elif flag_clicked:
            st.warning("Please enter a segment ID.")

        # --- Currently flagged ---
        st.subheader("Currently Excluded")
        flagged_details = get_flagged_segments_detail(DB_PATH)

        if flagged_details:
            flagged_df = pd.DataFrame(
                flagged_details,
                columns=["Segment ID", "Name", "Reason", "Excluded At"],
            )
            flagged_df["Name"] = flagged_df["Name"].fillna("(unknown)")
            flagged_df["Reason"] = flagged_df["Reason"].fillna("—")
            flagged_df["Strava"] = flagged_df["Segment ID"].apply(
                lambda sid: f"https://strava.com/segments/{sid}"
            )
            st.dataframe(
                flagged_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Strava": st.column_config.LinkColumn(
                        "Strava", display_text="Open"
                    ),
                },
            )

            # --- Unflag ---
            st.subheader("Restore a Segment")
            unflag_options = [
                f"{row[0]} — {row[1] or '(unknown)'}" for row in flagged_details
            ]
            selected_unflag = st.selectbox(
                "Select segment to restore",
                unflag_options,
                key="unflag_select",
            )
            unflag_clicked = st.button("✅ Restore Segment", key="unflag_btn")

            if unflag_clicked:
                unflag_id = int(selected_unflag.split(" — ")[0])
                unflag_segment(unflag_id)
                st.success(f"Restored segment {unflag_id}.")
                st.rerun()
        else:
            st.caption("No segments are currently excluded.")

    # =============================
    # TAB 6: Feedback
    # =============================
    with tab6:
        st.header("Feedback")
        st.caption(
            "Found a bug? Have an idea? Let us know. "
            "Feedback is stored locally and reviewed periodically."
        )

        # --- Submit feedback ---
        col_type, col_name = st.columns([1, 2])
        with col_type:
            feedback_type = st.selectbox(
                "Type",
                ["Bug Report", "Feature Request", "Data Issue", "General"],
                key="fb_type",
            )
        with col_name:
            submitted_by = st.text_input(
                "Your name (optional)",
                placeholder="e.g. John",
                key="fb_name",
            )

        segment_id_fb = st.text_input(
            "Related segment ID (optional)",
            placeholder="e.g. 713680",
            key="fb_segment",
        )

        message = st.text_area(
            "Message",
            placeholder="Describe the issue or suggestion...",
            height=120,
            key="fb_message",
        )

        submit_fb = st.button("📨 Submit Feedback", type="primary", key="fb_submit")

        if submit_fb and message.strip():
            seg_id_val = None
            if segment_id_fb.strip():
                try:
                    seg_id_val = int(segment_id_fb.strip())
                except ValueError:
                    pass

            _fb_user_id = str(user.id) if user else None
            submit_feedback(
                feedback_type,
                message.strip(),
                segment_id=seg_id_val,
                submitted_by=submitted_by.strip() or None,
                user_id=_fb_user_id,
            )
            st.success("Thanks! Your feedback has been submitted.")
        elif submit_fb:
            st.warning("Please enter a message.")

        # --- Recent feedback ---
        st.markdown("---")
        st.subheader("Recent Feedback")

        recent = get_recent_feedback(limit=20)
        if recent:
            for fb_id, fb_type, fb_msg, fb_seg, fb_by, fb_at in recent:
                by_str = f" — {fb_by}" if fb_by else ""
                seg_str = f" (Segment {fb_seg})" if fb_seg else ""
                st.markdown(
                    f"**{fb_type}**{seg_str}{by_str}  \n"
                    f"<small style='color: #888;'>{fb_at}</small>",
                    unsafe_allow_html=True,
                )
                st.caption(fb_msg)
                st.markdown("")
        else:
            st.caption("No feedback submitted yet.")

    st.markdown("---")
    st.caption("🚴 Cycling Segment Predictor | Built with Streamlit")


if __name__ == "__main__":
    main()
