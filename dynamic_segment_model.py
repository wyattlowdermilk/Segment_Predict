"""
Dynamic segment time estimation with variable speed.

Models acceleration/deceleration based on instantaneous power balance:
- Net force = (Power/Speed) - Gravity - Air drag - Rolling resistance
- Acceleration = Net force / Mass
- Integrates over time to get speed profile and total time
"""

import math
from typing import Tuple

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
    dt: float = 0.1  # Time step in seconds
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
        force_air = -0.5 * cda * air_density * (apparent_speed ** 2)
        
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


def estimate_time_dynamic(
    segment_dict: dict,
    athlete,
    entrance_speed_mph: float,
    weather_conditions: dict,
    target_power: float = None
) -> dict:
    """
    Estimate segment time with dynamic speed simulation.
    
    This replaces the constant-speed model with a physics simulation
    that accounts for acceleration/deceleration throughout the segment.
    """
    from segment_time_estimator import PowerModel
    
    distance_m = segment_dict['distance_m']
    avg_grade = segment_dict['avg_grade']
    entrance_speed_ms = entrance_speed_mph * 0.44704  # mph to m/s
    
    # Air density
    elevation_m = (segment_dict.get('elevation_high_m', 0) + 
                   segment_dict.get('elevation_low_m', 0)) / 2
    air_density = PowerModel.air_density(
        weather_conditions['temp_c'],
        weather_conditions['pressure_hpa'],
        elevation_m
    )
    
    # Estimate duration for power curve (initial guess)
    initial_time_minutes = (distance_m / 1000) / 20 * 60
    
    # Determine sustainable power
    if target_power:
        sustainable_power = target_power
    else:
        sustainable_power = athlete.sustainable_power(initial_time_minutes)
    
    # Apply drivetrain loss
    power_at_wheel = sustainable_power * (1 - athlete.drivetrain_loss)
    
    # Run dynamic simulation
    total_time, time_profile, speed_profile = simulate_segment_dynamic(
        distance_m=distance_m,
        avg_grade_percent=avg_grade,
        entrance_speed_ms=entrance_speed_ms,
        athlete_total_weight_kg=athlete.total_weight_kg,
        sustainable_power_watts=power_at_wheel,
        cda=athlete.cda,
        crr=athlete.crr,
        air_density=air_density,
        wind_speed_ms=weather_conditions.get('wind_speed_ms', 0),
        wind_angle_deg=weather_conditions.get('wind_angle', 0)
    )
    
    # Refine power estimate based on actual duration
    refined_minutes = total_time / 60
    if not target_power:
        refined_power = athlete.sustainable_power(refined_minutes)
        power_at_wheel_refined = refined_power * (1 - athlete.drivetrain_loss)
        
        # Re-run simulation with refined power
        total_time, time_profile, speed_profile = simulate_segment_dynamic(
            distance_m=distance_m,
            avg_grade_percent=avg_grade,
            entrance_speed_ms=entrance_speed_ms,
            athlete_total_weight_kg=athlete.total_weight_kg,
            sustainable_power_watts=power_at_wheel_refined,
            cda=athlete.cda,
            crr=athlete.crr,
            air_density=air_density,
            wind_speed_ms=weather_conditions.get('wind_speed_ms', 0),
            wind_angle_deg=weather_conditions.get('wind_angle', 0)
        )
        
        sustainable_power = refined_power
        power_at_wheel = power_at_wheel_refined
    
    # Calculate average speed
    avg_speed_ms = distance_m / total_time if total_time > 0 else 0
    
    # Identify acceleration/deceleration phases
    initial_speed = speed_profile[0]
    final_speed = speed_profile[-1]
    min_speed = min(speed_profile)
    max_speed = max(speed_profile)
    
    return {
        'total_time': total_time,
        'accel_time': 0,  # Not applicable in dynamic model
        'cruise_time': total_time,  # Entire segment is "cruise" with varying speed
        'accel_distance': 0,
        'cruise_speed_mph': avg_speed_ms / 0.44704,
        'sustainable_power': sustainable_power,
        'power_at_wheel': power_at_wheel,
        'speed_profile': {
            'initial_speed_ms': initial_speed,
            'final_speed_ms': final_speed,
            'min_speed_ms': min_speed,
            'max_speed_ms': max_speed,
            'avg_speed_ms': avg_speed_ms
        }
    }


# Test the model
if __name__ == "__main__":
    from segment_time_estimator import AthleteProfile
    
    print("="*70)
    print("TESTING: Dynamic vs Static Model")
    print("="*70)
    
    # Create athlete
    athlete = AthleteProfile(
        power_curve={1: 590, 3: 500, 8: 420, 20: 315},
        weight_kg=100,
        bike_weight_kg=8
    )
    
    # Test segment: 400m, 8% grade
    segment = {
        'distance_m': 400,
        'avg_grade': 8.0,
        'elevation_high_m': 32,
        'elevation_low_m': 0
    }
    
    weather = {
        'temp_c': 15,
        'pressure_hpa': 1013,
        'wind_speed_ms': 0,
        'wind_angle': 0
    }
    
    # Test with 20 mph entrance speed
    entrance_speed = 20  # mph
    
    print(f"\nSegment: {segment['distance_m']}m at {segment['avg_grade']}% grade")
    print(f"Athlete: {athlete.total_weight_kg}kg total")
    print(f"Entrance speed: {entrance_speed} mph ({entrance_speed * 0.44704:.2f} m/s)")
    
    result = estimate_time_dynamic(segment, athlete, entrance_speed, weather)
    
    print(f"\n📊 Results:")
    print(f"   Total time: {result['total_time']:.1f}s")
    print(f"   Sustainable power: {result['sustainable_power']:.0f}W")
    print(f"   Average speed: {result['cruise_speed_mph']:.1f} mph")
    print(f"\n🎢 Speed Profile:")
    print(f"   Initial: {result['speed_profile']['initial_speed_ms']:.2f} m/s ({result['speed_profile']['initial_speed_ms'] * 2.237:.1f} mph)")
    print(f"   Final: {result['speed_profile']['final_speed_ms']:.2f} m/s ({result['speed_profile']['final_speed_ms'] * 2.237:.1f} mph)")
    print(f"   Min: {result['speed_profile']['min_speed_ms']:.2f} m/s")
    print(f"   Max: {result['speed_profile']['max_speed_ms']:.2f} m/s")
    
    if result['speed_profile']['final_speed_ms'] < result['speed_profile']['initial_speed_ms']:
        print(f"   ⬇️  DECELERATED: Lost {(result['speed_profile']['initial_speed_ms'] - result['speed_profile']['final_speed_ms']) * 2.237:.1f} mph on climb")
    else:
        print(f"   ⬆️  ACCELERATED: Gained {(result['speed_profile']['final_speed_ms'] - result['speed_profile']['initial_speed_ms']) * 2.237:.1f} mph")
