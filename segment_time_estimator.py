"""
Cycling Segment Time Estimator
Combines segment data, 7-day weather forecast, and athlete power profile
to estimate segment completion times.

Uses physics-based cycling power model accounting for:
- Gradient resistance
- Air resistance (with wind adjustment)
- Rolling resistance
- Temperature effects on air density
"""

import sqlite3
import requests
import math
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import os

# =============================
# Configuration
# =============================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "segments.db")

# OpenWeatherMap API (free tier: 1000 calls/day)
# Get your free API key at: https://openweathermap.org/api
WEATHER_API_KEY = "YOUR_API_KEY_HERE"  # <-- UPDATE THIS
WEATHER_API_URL = "https://api.openweathermap.org/data/2.5/forecast"


# =============================
# Athlete Profile
# =============================
class AthleteProfile:
    """Athlete power and physical characteristics with power duration curve"""

    def __init__(
        self,
        power_curve: Dict[float, float] = None,  # {duration_minutes: power_watts}
        weight_kg: float = 75,  # Rider weight (kg)
        bike_weight_kg: float = 8,  # Bike weight (kg)
        cda: float = 0.32,  # Coefficient of drag × frontal area (m²)
        crr: float = 0.004,  # Coefficient of rolling resistance
        drivetrain_loss: float = 0.03,  # Drivetrain efficiency loss (3%)
    ):
        # Power duration curve points
        if power_curve is None:
            # Default curve based on ~250W FTP
            power_curve = {
                1: 300,  # 1 minute
                3: 285,  # 3 minutes
                8: 265,  # 8 minutes (VO2max)
                20: 250,  # 20 minutes
                60: 237,  # 1 hour (FTP)
            }

        self.power_curve = power_curve
        self.weight_kg = weight_kg
        self.bike_weight_kg = bike_weight_kg
        self.total_weight_kg = weight_kg + bike_weight_kg
        self.cda = cda
        self.crr = crr
        self.drivetrain_loss = drivetrain_loss

        # Fit power duration model
        self._fit_power_model()

    def _fit_power_model(self):
        """
        Fit a power duration curve using Critical Power (CP) model.
        Model: Power = CP + W' / time
        Where CP = critical power (asymptote) and W' = anaerobic work capacity

        For better fit, we use a 3-parameter model:
        Power = CP + W' / (time + tau)
        """
        try:
            import numpy as np
            from scipy.optimize import curve_fit

            # Convert to seconds and watts
            durations_sec = np.array([d * 60 for d in sorted(self.power_curve.keys())])
            powers = np.array(
                [self.power_curve[d] for d in sorted(self.power_curve.keys())]
            )

            # 3-parameter hyperbolic model
            def power_model(t, cp, wprime, tau):
                return cp + wprime / (t + tau)

            # Initial guesses
            cp_guess = min(powers) * 0.9
            wprime_guess = 20000  # ~20kJ typical
            tau_guess = 30

            # Fit the model
            params, _ = curve_fit(
                power_model,
                durations_sec,
                powers,
                p0=[cp_guess, wprime_guess, tau_guess],
                bounds=([0, 0, 0], [500, 50000, 300]),
                maxfev=10000,
            )

            self.cp = params[0]
            self.wprime = params[1]
            self.tau = params[2]
            self.model_type = "3-param"

        except ImportError:
            # scipy not available, use simple interpolation
            self.cp = min(self.power_curve.values())
            self.wprime = 0
            self.tau = 0
            self.model_type = "interpolation"

        except:
            # Fallback to simpler 2-parameter model if 3-param fit fails
            try:
                import numpy as np
                from scipy.optimize import curve_fit

                durations_sec = np.array(
                    [d * 60 for d in sorted(self.power_curve.keys())]
                )
                powers = np.array(
                    [self.power_curve[d] for d in sorted(self.power_curve.keys())]
                )

                def simple_model(t, cp, wprime):
                    return cp + wprime / t

                cp_guess = min(powers) * 0.9
                wprime_guess = 20000

                params, _ = curve_fit(
                    simple_model,
                    durations_sec,
                    powers,
                    p0=[cp_guess, wprime_guess],
                    bounds=([0, 0], [500, 50000]),
                    maxfev=10000,
                )

                self.cp = params[0]
                self.wprime = params[1]
                self.tau = 0
                self.model_type = "2-param"

            except:
                # Ultimate fallback: use simple interpolation
                self.cp = min(self.power_curve.values())
                self.wprime = 0
                self.tau = 0
                self.model_type = "interpolation"

    def sustainable_power(self, duration_minutes: float) -> float:
        """
        Estimate sustainable power for a given duration using fitted power curve.
        """
        duration_sec = duration_minutes * 60

        if self.model_type == "interpolation":
            # Simple linear interpolation between points
            durations = sorted(self.power_curve.keys())
            powers = [self.power_curve[d] for d in durations]

            # Convert to seconds
            durations_sec_list = [d * 60 for d in durations]

            # Find surrounding points
            if duration_sec <= durations_sec_list[0]:
                return powers[0]
            if duration_sec >= durations_sec_list[-1]:
                return powers[-1]

            # Linear interpolation
            for i in range(len(durations_sec_list) - 1):
                if durations_sec_list[i] <= duration_sec <= durations_sec_list[i + 1]:
                    t1, t2 = durations_sec_list[i], durations_sec_list[i + 1]
                    p1, p2 = powers[i], powers[i + 1]
                    ratio = (duration_sec - t1) / (t2 - t1)
                    return p1 + ratio * (p2 - p1)

            return powers[-1]

        else:
            # Use fitted model
            power = self.cp + self.wprime / (duration_sec + self.tau)

            # Sanity bounds
            max_power = max(self.power_curve.values()) * 1.1
            min_power = min(self.power_curve.values()) * 0.7

            return max(min_power, min(max_power, power))

    def get_ftp(self) -> float:
        """Estimate FTP from power curve (60-min power or 95% of 20-min)"""
        if 60 in self.power_curve:
            return self.power_curve[60]
        elif 20 in self.power_curve:
            return self.power_curve[20] * 0.95
        else:
            return self.sustainable_power(60)

    def __str__(self):
        ftp = self.get_ftp()
        power_1min = self.power_curve.get(1, self.sustainable_power(1))
        power_20min = self.power_curve.get(20, self.sustainable_power(20))
        return (
            f"Athlete: Power Curve (1min={power_1min:.0f}W, 20min={power_20min:.0f}W, FTP≈{ftp:.0f}W), "
            f"Weight={self.weight_kg}kg, W/kg={ftp/self.weight_kg:.2f}, "
            f"CdA={self.cda}m², Model={self.model_type}"
        )


# =============================
# Weather Data
# =============================
class WeatherForecast:
    """Fetch and store weather forecast data"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_forecast(self, lat: float, lon: float) -> List[Dict]:
        """
        Get 7-day forecast for a location.
        Returns list of forecast periods (every 3 hours for 5 days on free tier)
        """
        if self.api_key == "YOUR_API_KEY_HERE":
            print("⚠️  Using mock weather data (no API key provided)")
            return self._mock_forecast()

        try:
            params = {
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": "metric",  # Celsius, m/s for wind
            }
            response = requests.get(WEATHER_API_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            forecasts = []
            for item in data["list"][:56]:  # 7 days × 8 (3-hour intervals)
                forecasts.append(
                    {
                        "datetime": datetime.fromtimestamp(item["dt"]),
                        "temp_c": item["main"]["temp"],
                        "wind_speed_ms": item["wind"]["speed"],
                        "wind_deg": item["wind"]["deg"],
                        "wind_gust_ms": item["wind"].get("gust", 0),
                        "pressure_hpa": item["main"]["pressure"],
                        "humidity": item["main"]["humidity"],
                        "description": item["weather"][0]["description"],
                        "rain_mm": item.get("rain", {}).get("3h", 0),
                    }
                )

            return forecasts

        except Exception as e:
            print(f"⚠️  Weather API error: {e}. Using mock data.")
            return self._mock_forecast()

    def _mock_forecast(self) -> List[Dict]:
        """Generate mock forecast for testing"""
        forecasts = []
        base_time = datetime.now()

        for i in range(56):  # 7 days
            forecasts.append(
                {
                    "datetime": base_time + timedelta(hours=3 * i),
                    "temp_c": 15 + 5 * math.sin(i * math.pi / 8),  # Varies 10-20°C
                    "wind_speed_ms": 3 + 2 * math.sin(i * math.pi / 12),  # 1-5 m/s
                    "wind_deg": 180,  # South wind
                    "wind_gust_ms": 5
                    + 3 * math.sin(i * math.pi / 12),  # Gusts ~2-8 m/s
                    "pressure_hpa": 1013,
                    "humidity": 60,
                    "description": "clear sky",
                    "rain_mm": 0,
                }
            )

        return forecasts


# =============================
# Physics-Based Power Model
# =============================
class PowerModel:
    """Calculate power requirements and estimate times"""

    # Physical constants
    GRAVITY = 9.81  # m/s²
    AIR_DENSITY_SEA_LEVEL = 1.225  # kg/m³ at 15°C, sea level

    @staticmethod
    def air_density(
        temp_c: float, pressure_hpa: float, elevation_m: float = 0
    ) -> float:
        """Calculate air density based on temperature, pressure, and elevation"""
        # Simplified air density calculation
        temp_k = temp_c + 273.15
        # Adjust pressure for elevation (rough approximation)
        adjusted_pressure = pressure_hpa * math.exp(-elevation_m / 8500)
        # Air density in kg/m³
        rho = (adjusted_pressure * 100) / (287.05 * temp_k)
        return rho

    @staticmethod
    def power_required(
        speed_ms: float,
        grade_percent: float,
        total_weight_kg: float,
        cda: float,
        crr: float,
        air_density: float,
        wind_speed_ms: float = 0,
        wind_angle_deg: float = 0,
    ) -> float:
        """
        Calculate power required to maintain speed on a given grade.

        Returns: power in watts (at wheel)
        """
        # Headwind component (positive = headwind, negative = tailwind)
        wind_angle_rad = math.radians(wind_angle_deg)
        effective_wind = wind_speed_ms * math.cos(wind_angle_rad)
        apparent_speed = speed_ms + effective_wind

        # Power components
        # 1. Gravity (climbing)
        grade_rad = math.atan(grade_percent / 100)
        power_gravity = (
            total_weight_kg * PowerModel.GRAVITY * math.sin(grade_rad) * speed_ms
        )

        # 2. Air resistance (drag)
        power_air = 0.5 * cda * air_density * (apparent_speed**3)

        # 3. Rolling resistance
        power_rolling = (
            total_weight_kg * PowerModel.GRAVITY * math.cos(grade_rad) * crr * speed_ms
        )

        total_power = power_gravity + power_air + power_rolling

        return max(0, total_power)  # Power can't be negative

    @staticmethod
    def estimate_speed(
        power_watts: float,
        grade_percent: float,
        total_weight_kg: float,
        cda: float,
        crr: float,
        air_density: float,
        wind_speed_ms: float = 0,
        wind_angle_deg: float = 0,
        initial_guess_ms: float = 7.0,
    ) -> float:
        """
        Estimate speed given power output using iterative solver.

        Returns: speed in m/s
        """
        # Newton-Raphson iteration to solve for speed
        speed = initial_guess_ms
        tolerance = 0.01  # m/s
        max_iterations = 50

        for _ in range(max_iterations):
            power_calc = PowerModel.power_required(
                speed,
                grade_percent,
                total_weight_kg,
                cda,
                crr,
                air_density,
                wind_speed_ms,
                wind_angle_deg,
            )

            # Error
            error = power_calc - power_watts

            if abs(error) < tolerance:
                break

            # Numerical derivative
            delta = 0.1
            power_calc_delta = PowerModel.power_required(
                speed + delta,
                grade_percent,
                total_weight_kg,
                cda,
                crr,
                air_density,
                wind_speed_ms,
                wind_angle_deg,
            )
            derivative = (power_calc_delta - power_calc) / delta

            # Update speed
            if derivative != 0:
                speed = speed - error / derivative
                speed = max(1.0, min(25.0, speed))  # Constrain to 1-25 m/s

        return speed


# =============================
# Segment Time Estimator
# =============================
class SegmentEstimator:
    """Main class for estimating segment times"""

    def __init__(self, db_file: str, weather_api_key: str):
        self.db_file = db_file
        self.weather = WeatherForecast(weather_api_key)

    def get_segment(self, segment_id: int) -> Optional[Dict]:
        """Retrieve segment data from database"""
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            """
            SELECT * FROM segments WHERE id = ?
        """,
            (segment_id,),
        )

        row = cur.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    def get_leaderboard_stats(self, segment_id: int) -> Dict:
        """Get leaderboard statistics for reference"""
        conn = sqlite3.connect(self.db_file)
        cur = conn.cursor()

        cur.execute(
            """
            SELECT 
                MIN(time_seconds) as best_time,
                AVG(time_seconds) as avg_time,
                AVG(power) as avg_power
            FROM leaderboard
            WHERE segment_id = ? AND power IS NOT NULL
        """,
            (segment_id,),
        )

        row = cur.fetchone()
        conn.close()

        return {"best_time": row[0], "avg_time": row[1], "avg_power": row[2]}

    def calculate_wind_angle(
        self, segment_bearing: float, wind_direction: float
    ) -> float:
        """
        Calculate angle between segment direction and wind.
        0° = headwind, 90° = crosswind, 180° = tailwind
        """
        # Wind direction is "from" direction, segment is "to" direction
        angle_diff = abs(wind_direction - segment_bearing)

        # Normalize to 0-180
        if angle_diff > 180:
            angle_diff = 360 - angle_diff

        return angle_diff

    def estimate_time(
        self,
        segment_id: int,
        athlete: AthleteProfile,
        forecast_datetime: Optional[datetime] = None,
    ) -> Dict:
        """
        Estimate time for a segment given athlete profile and conditions.

        Returns dict with estimated time and detailed breakdown.
        """
        # Get segment data
        segment = self.get_segment(segment_id)
        if not segment:
            raise ValueError(f"Segment {segment_id} not found")

        # Get weather forecast
        forecasts = self.weather.get_forecast(
            segment["start_lat"], segment["start_lng"]
        )

        # Find closest forecast to target datetime
        if forecast_datetime is None:
            forecast_datetime = datetime.now()

        closest_forecast = min(
            forecasts,
            key=lambda f: abs((f["datetime"] - forecast_datetime).total_seconds()),
        )

        # Calculate segment bearing (rough approximation)
        lat1, lon1 = segment["start_lat"], segment["start_lng"]
        lat2, lon2 = segment["end_lat"], segment["end_lng"]

        dlon = math.radians(lon2 - lon1)
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)

        x = math.cos(lat2_rad) * math.sin(dlon)
        y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(
            lat2_rad
        ) * math.cos(dlon)

        bearing = math.degrees(math.atan2(x, y))
        bearing = (bearing + 360) % 360

        # Calculate wind angle
        wind_angle = self.calculate_wind_angle(bearing, closest_forecast["wind_deg"])

        # Air density
        elevation_m = (segment["elevation_high_m"] + segment["elevation_low_m"]) / 2
        air_density = PowerModel.air_density(
            closest_forecast["temp_c"], closest_forecast["pressure_hpa"], elevation_m
        )

        # Estimate sustainable power for expected duration
        # Start with rough estimate based on distance and grade
        distance_m = segment["distance_m"]
        avg_grade = segment["avg_grade"]

        # Initial time guess (assuming 25 km/h average)
        initial_time_minutes = (distance_m / 1000) / 25 * 60
        sustainable_power = athlete.sustainable_power(initial_time_minutes)

        # Account for drivetrain loss
        power_at_wheel = sustainable_power * (1 - athlete.drivetrain_loss)

        # Adjust rolling resistance for wet conditions
        crr_adjusted = athlete.crr
        if closest_forecast["rain_mm"] > 0:
            crr_adjusted *= 1.2  # 20% increase in wet conditions

        # Estimate average speed
        avg_speed_ms = PowerModel.estimate_speed(
            power_watts=power_at_wheel,
            grade_percent=avg_grade,
            total_weight_kg=athlete.total_weight_kg,
            cda=athlete.cda,
            crr=crr_adjusted,
            air_density=air_density,
            wind_speed_ms=closest_forecast["wind_speed_ms"],
            wind_angle_deg=wind_angle,
        )

        # Calculate time
        estimated_time_seconds = distance_m / avg_speed_ms
        estimated_time_minutes = estimated_time_seconds / 60

        # Refine power estimate with better duration
        sustainable_power_refined = athlete.sustainable_power(estimated_time_minutes)
        power_at_wheel_refined = sustainable_power_refined * (
            1 - athlete.drivetrain_loss
        )

        # Recalculate with refined power
        avg_speed_ms_refined = PowerModel.estimate_speed(
            power_watts=power_at_wheel_refined,
            grade_percent=avg_grade,
            total_weight_kg=athlete.total_weight_kg,
            cda=athlete.cda,
            crr=crr_adjusted,
            air_density=air_density,
            wind_speed_ms=closest_forecast["wind_speed_ms"],
            wind_angle_deg=wind_angle,
        )

        estimated_time_seconds = distance_m / avg_speed_ms_refined

        # Get leaderboard stats for comparison
        lb_stats = self.get_leaderboard_stats(segment_id)

        return {
            "segment_id": segment_id,
            "segment_name": segment["name"],
            "estimated_time_seconds": estimated_time_seconds,
            "estimated_time_formatted": format_time(estimated_time_seconds),
            "avg_speed_kmh": avg_speed_ms_refined * 3.6,
            "sustainable_power_watts": sustainable_power_refined,
            "power_at_wheel_watts": power_at_wheel_refined,
            "weather": {
                "datetime": closest_forecast["datetime"].strftime("%Y-%m-%d %H:%M"),
                "temp_c": closest_forecast["temp_c"],
                "wind_speed_ms": closest_forecast["wind_speed_ms"],
                "wind_speed_kmh": closest_forecast["wind_speed_ms"] * 3.6,
                "wind_direction": closest_forecast["wind_deg"],
                "wind_angle": wind_angle,
                "description": closest_forecast["description"],
                "rain_mm": closest_forecast["rain_mm"],
            },
            "segment": {
                "distance_km": distance_m / 1000,
                "elevation_gain_m": segment["elevation_gain_m"],
                "avg_grade": avg_grade,
                "bearing": bearing,
            },
            "leaderboard": lb_stats,
            "conditions": {
                "air_density": air_density,
                "crr": crr_adjusted,
                "wet_conditions": closest_forecast["rain_mm"] > 0,
            },
        }

    def estimate_next_7_days(
        self, segment_id: int, athlete: AthleteProfile
    ) -> List[Dict]:
        """Get estimates for all forecast periods in next 7 days"""
        segment = self.get_segment(segment_id)
        if not segment:
            raise ValueError(f"Segment {segment_id} not found")

        forecasts = self.weather.get_forecast(
            segment["start_lat"], segment["start_lng"]
        )

        results = []
        for forecast in forecasts:
            try:
                estimate = self.estimate_time(segment_id, athlete, forecast["datetime"])
                results.append(estimate)
            except Exception as e:
                print(f"Error estimating for {forecast['datetime']}: {e}")
                continue

        return results


# =============================
# Utility Functions
# =============================
def format_time(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def print_estimate(result: Dict):
    """Pretty print estimation result"""
    print("\n" + "=" * 70)
    print(f"SEGMENT: {result['segment_name']} (ID: {result['segment_id']})")
    print("=" * 70)

    print(f"\n📍 Segment Details:")
    print(f"   Distance: {result['segment']['distance_km']:.2f} km")
    print(f"   Elevation Gain: {result['segment']['elevation_gain_m']:.0f} m")
    print(f"   Average Grade: {result['segment']['avg_grade']:.1f}%")
    print(f"   Bearing: {result['segment']['bearing']:.0f}°")

    print(f"\n🌤️  Weather Conditions ({result['weather']['datetime']}):")
    print(f"   Temperature: {result['weather']['temp_c']:.1f}°C")
    print(
        f"   Wind: {result['weather']['wind_speed_kmh']:.1f} km/h from {result['weather']['wind_direction']}°"
    )
    print(
        f"   Wind Angle to Segment: {result['weather']['wind_angle']:.0f}° "
        f"({'headwind' if result['weather']['wind_angle'] < 45 else 'crosswind' if result['weather']['wind_angle'] < 135 else 'tailwind'})"
    )
    print(f"   Conditions: {result['weather']['description']}")
    if result["weather"]["rain_mm"] > 0:
        print(f"   Rain: {result['weather']['rain_mm']:.1f} mm (wet roads)")

    print(f"\n⚡ Power & Speed:")
    print(f"   Sustainable Power: {result['sustainable_power_watts']:.0f} W")
    print(f"   Power at Wheel: {result['power_at_wheel_watts']:.0f} W")
    print(f"   Average Speed: {result['avg_speed_kmh']:.1f} km/h")

    print(f"\n⏱️  Estimated Time: {result['estimated_time_formatted']}")
    print(f"   ({result['estimated_time_seconds']:.0f} seconds)")

    if result["leaderboard"]["best_time"]:
        lb_best = format_time(result["leaderboard"]["best_time"])
        lb_avg = format_time(result["leaderboard"]["avg_time"])
        print(f"\n🏆 Leaderboard Comparison:")
        print(f"   Best Time: {lb_best}")
        print(f"   Average Time: {lb_avg}")
        if result["leaderboard"]["avg_power"]:
            print(f"   Average Power: {result['leaderboard']['avg_power']:.0f} W")

    print("\n" + "=" * 70 + "\n")


def find_best_time_window(results: List[Dict], top_n: int = 5) -> List[Dict]:
    """Find the top N time windows with fastest estimated times"""
    sorted_results = sorted(results, key=lambda x: x["estimated_time_seconds"])
    return sorted_results[:top_n]


# =============================
# Main Execution
# =============================
def main():
    """Example usage"""

    print("\n🚴 Cycling Segment Time Estimator")
    print("=" * 70)

    # Initialize estimator
    estimator = SegmentEstimator(DB_FILE, WEATHER_API_KEY)

    # Define athlete profile with power curve
    athlete = AthleteProfile(
        power_curve={
            1: 400,  # 1-minute power
            3: 340,  # 3-minute power
            8: 300,  # 8-minute power
            20: 250,  # 20-minute power
        },
        weight_kg=75,
        bike_weight_kg=8,
        cda=0.32,
        crr=0.004,
    )

    print(f"\n👤 {athlete}\n")

    # Get list of segments
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM segments LIMIT 5")
    segments = cur.fetchall()
    conn.close()

    if not segments:
        print("❌ No segments found in database. Run Segment_Pull.py first.")
        return

    print(f"Found {len(segments)} segments to analyze:\n")

    # Example: Estimate for first segment
    segment_id = segments[0][0]
    segment_name = segments[0][1]

    print(f"Analyzing: {segment_name} (ID: {segment_id})")
    print("Estimating times for next 7 days...\n")

    # Get 7-day estimates
    results = estimator.estimate_next_7_days(segment_id, athlete)

    if not results:
        print("❌ No results generated")
        return

    # Show current/next forecast
    print_estimate(results[0])

    # Find best time windows
    print("\n🌟 BEST TIME WINDOWS (Next 7 Days)")
    print("=" * 70)
    best_windows = find_best_time_window(results, top_n=5)

    for i, result in enumerate(best_windows, 1):
        print(f"\n#{i}. {result['weather']['datetime']}")
        print(f"    Estimated Time: {result['estimated_time_formatted']}")
        print(f"    Speed: {result['avg_speed_kmh']:.1f} km/h")
        print(
            f"    Wind: {result['weather']['wind_speed_kmh']:.1f} km/h "
            f"at {result['weather']['wind_angle']:.0f}° angle"
        )
        print(f"    Temp: {result['weather']['temp_c']:.1f}°C")
        print(f"    Conditions: {result['weather']['description']}")

    print("\n" + "=" * 70)
    print("\n✅ Analysis complete!")
    print(f"\n💡 Tip: Edit config.py to set your power curve values")
    print(f"   from your power meter data for accurate estimates.")
    print(f"\n💡 Get a free weather API key at: https://openweathermap.org/api")
    print(f"   (1000 calls/day free tier)\n")


if __name__ == "__main__":
    main()
