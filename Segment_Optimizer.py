"""
Variable Gradient Segment Optimizer
====================================
Combines exhaustion modeling (W' balance) with physics-based segment simulation
to find the optimal power profile for a segment with variable gradients.

Approach:
  1. User defines a piecewise segment: [(grade%, distance_miles), ...]
  2. Physics sim converts power -> speed at each gradient
  3. Exhaustion model (CP / W') constrains what power is actually deliverable
  4. Optimizer searches for the power profile that minimizes total time
     without exceeding exhaustion limits

Usage:
  python segment_optimizer.py
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize
import math
from typing import List, Tuple, Dict

# ============================================================
# Constants
# ============================================================
GRAVITY = 9.81
AIR_DENSITY_DEFAULT = 1.225  # kg/m³ at sea level, 15°C
MILES_TO_METERS = 1609.34


# ============================================================
# Athlete / Power Model
# ============================================================
class Athlete:
    """Rider parameters and power-duration model."""

    def __init__(
        self,
        power_curve: Dict[int, float],
        weight_kg: float = 75.0,
        bike_weight_kg: float = 8.0,
        cda: float = 0.32,
        crr: float = 0.004,
        drivetrain_loss: float = 0.03,
    ):
        self.power_curve = power_curve  # {seconds: watts}
        self.weight_kg = weight_kg
        self.bike_weight_kg = bike_weight_kg
        self.total_weight = weight_kg + bike_weight_kg
        self.cda = cda
        self.crr = crr
        self.drivetrain_loss = drivetrain_loss

        # Derive CP and W' from power curve
        self.cp, self.w_prime = self._estimate_cp_wprime()

    def _estimate_cp_wprime(self) -> Tuple[float, float]:
        """Estimate Critical Power and W' from power-duration data."""
        # CP ≈ 95% of 20-min power (standard approximation)
        p20 = self.power_curve.get(1200, min(self.power_curve.values()))
        cp = 0.95 * p20

        # W' = mean of (P - CP) * t for efforts above CP
        w_prime_estimates = []
        for t, p in self.power_curve.items():
            if p > cp:
                w_prime_estimates.append((p - cp) * t)
        w_prime = np.mean(w_prime_estimates) if w_prime_estimates else 20000
        return cp, w_prime

    def max_power_for_duration(self, duration_s: float) -> float:
        """Max sustainable power for a given duration using hyperbolic model.
        P = CP + W'/t"""
        if duration_s <= 0:
            return self.power_curve.get(60, 500)
        return self.cp + self.w_prime / max(duration_s, 1)

    def power_at_wheel(self, power: float) -> float:
        return power * (1 - self.drivetrain_loss)


# ============================================================
# Segment Definition
# ============================================================
class SegmentSection:
    """One constant-gradient piece of a segment."""

    def __init__(self, grade_pct: float, distance_miles: float):
        self.grade_pct = grade_pct
        self.distance_m = distance_miles * MILES_TO_METERS

    def __repr__(self):
        return f"{self.grade_pct:.1f}% × {self.distance_m / MILES_TO_METERS:.2f} mi"


def build_segment(pieces: List[Tuple[float, float]]) -> List[SegmentSection]:
    """Build segment from list of (grade_pct, distance_miles) tuples."""
    return [SegmentSection(g, d) for g, d in pieces]


def segment_total_distance(sections: List[SegmentSection]) -> float:
    return sum(s.distance_m for s in sections)


def segment_avg_grade(sections: List[SegmentSection]) -> float:
    total_d = segment_total_distance(sections)
    if total_d == 0:
        return 0
    return sum(s.grade_pct * s.distance_m for s in sections) / total_d


# ============================================================
# Exhaustion Model (W' balance)
# ============================================================
def simulate_exhaustion(
    power_series: np.ndarray,
    cp: float,
    w_prime: float,
    dt: float = 1.0,
    recovery_rate: float = 1.0,
    alpha: float = 2.0,
    fatigue_factor: float = 0.7,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Simulate W' depletion / recovery over a power time series.

    Returns:
        exhaustion_pct: array of exhaustion % (0-100) at each time step
        actual_power:   array of deliverable power (capped when exhausted)
    """
    E = 0.0
    exhaustion = np.zeros(len(power_series))
    actual_power = np.zeros(len(power_series))

    for i, p_try in enumerate(power_series):
        # W' depletion / recovery
        if p_try > cp:
            dE = ((p_try - cp) / w_prime) * 100 * dt
        else:
            intensity_factor = ((cp - p_try) / cp) ** alpha
            dE = -recovery_rate * intensity_factor * dt

        E = np.clip(E + dE, 0, 100)
        exhaustion[i] = E

        # Cap power if fully exhausted
        if E >= 100:
            actual_power[i] = min(p_try, cp * fatigue_factor)
        else:
            actual_power[i] = p_try

    return exhaustion, actual_power


# ============================================================
# Physics: Speed from Power at a Given Grade
# ============================================================
def steady_state_speed(
    power_watts: float,
    grade_pct: float,
    total_weight: float,
    cda: float,
    crr: float,
    air_density: float = AIR_DENSITY_DEFAULT,
    wind_speed_ms: float = 0.0,
) -> float:
    """
    Solve for steady-state speed given power output and gradient.
    Uses iterative Newton-Raphson on the power balance equation:
        P = v * (F_gravity + F_rolling + F_aero)
    """
    grade_rad = math.atan(grade_pct / 100)
    cos_grade = math.cos(grade_rad)
    sin_grade = math.sin(grade_rad)

    # Initial guess based on flat-ground approximation
    v = max(1.0, (power_watts / (0.5 * cda * air_density)) ** (1 / 3))

    for _ in range(50):
        v_air = v + wind_speed_ms  # headwind positive
        f_gravity = total_weight * GRAVITY * sin_grade
        f_rolling = total_weight * GRAVITY * cos_grade * crr
        f_aero = 0.5 * cda * air_density * v_air**2

        # Power balance: P = v * (f_gravity + f_rolling + f_aero)
        residual = v * (f_gravity + f_rolling + f_aero) - power_watts

        # Derivative w.r.t. v
        d_residual = (
            f_gravity
            + f_rolling
            + 0.5 * cda * air_density * (3 * v_air**2 + 2 * v_air * wind_speed_ms)
        )
        # Simplified: just use numerical-friendly version
        d_residual = (f_gravity + f_rolling + f_aero) + v * cda * air_density * v_air

        if abs(d_residual) < 1e-10:
            break

        v_new = v - residual / d_residual
        v_new = max(0.5, v_new)  # floor at 0.5 m/s

        if abs(v_new - v) < 1e-6:
            break
        v = v_new

    return max(0.5, v)


# ============================================================
# Dynamic Simulation: Ride a Variable-Gradient Segment
# ============================================================
def simulate_segment(
    sections: List[SegmentSection],
    power_per_section: List[float],
    athlete: Athlete,
    entrance_speed_mph: float = 20.0,
    air_density: float = AIR_DENSITY_DEFAULT,
    dt: float = 0.5,
    wind_speed_ms: float = 0.0,
) -> Dict:
    """
    Simulate riding through a multi-gradient segment with per-section power targets.

    The physics simulation uses force-balance at each time step (like app.py).
    The exhaustion model constrains actual deliverable power.

    Args:
        wind_speed_ms: Effective headwind component in m/s (positive = headwind,
                       negative = tailwind). This is the along-segment component,
                       i.e. wind_speed * cos(wind_angle) where angle 0 = headwind.

    Returns dict with time, profiles, and per-section breakdowns.
    """
    current_speed = entrance_speed_mph * 0.44704  # mph -> m/s
    distance_covered = 0.0
    elapsed = 0.0

    # Build flat arrays: one target power per meter of segment
    section_boundaries = []
    cumulative = 0.0
    for sec in sections:
        section_boundaries.append((cumulative, cumulative + sec.distance_m, sec))
        cumulative += sec.distance_m
    total_distance = cumulative

    # Profiles for plotting
    time_profile = [0.0]
    speed_profile = [current_speed]
    power_target_profile = [0.0]
    power_actual_profile = [0.0]
    exhaustion_profile = [0.0]
    distance_profile = [0.0]
    grade_profile = [sections[0].grade_pct]

    # Exhaustion state
    E = 0.0  # exhaustion %
    max_iter = int(3600 / dt)  # 1-hour safety cap

    for _ in range(max_iter):
        if distance_covered >= total_distance:
            break

        # Determine which section we're in
        current_section_idx = 0
        current_grade = sections[0].grade_pct
        for idx, (start_d, end_d, sec) in enumerate(section_boundaries):
            if start_d <= distance_covered < end_d:
                current_section_idx = idx
                current_grade = sec.grade_pct
                break

        target_power = power_per_section[current_section_idx]

        # --- Exhaustion check ---
        if target_power > athlete.cp:
            dE = ((target_power - athlete.cp) / athlete.w_prime) * 100 * dt
        else:
            intensity = ((athlete.cp - target_power) / athlete.cp) ** 2
            dE = -1.0 * intensity * dt

        E = np.clip(E + dE, 0, 100)

        if E >= 100:
            actual_power = min(target_power, athlete.cp * 0.7)
        else:
            actual_power = target_power

        power_at_wheel = athlete.power_at_wheel(actual_power)

        # --- Force balance (from app.py approach) ---
        grade_rad = math.atan(current_grade / 100)

        if current_speed > 0.1:
            force_prop = power_at_wheel / current_speed
        else:
            force_prop = power_at_wheel / 0.1

        force_gravity = -athlete.total_weight * GRAVITY * math.sin(grade_rad)
        apparent_speed = current_speed + wind_speed_ms  # headwind positive
        force_aero = -0.5 * athlete.cda * air_density * apparent_speed**2
        force_rolling = (
            -athlete.total_weight * GRAVITY * math.cos(grade_rad) * athlete.crr
        )

        net_force = force_prop + force_gravity + force_aero + force_rolling
        accel = net_force / athlete.total_weight

        new_speed = current_speed + accel * dt
        new_speed = max(0.5, min(25.0, new_speed))  # 0.5 m/s floor, ~56 mph cap

        avg_speed = (current_speed + new_speed) / 2
        distance_covered += avg_speed * dt
        elapsed += dt
        current_speed = new_speed

        # Record
        time_profile.append(elapsed)
        speed_profile.append(current_speed)
        power_target_profile.append(target_power)
        power_actual_profile.append(actual_power)
        exhaustion_profile.append(E)
        distance_profile.append(distance_covered)
        grade_profile.append(current_grade)

    # Per-section breakdown
    section_results = []
    for idx, (start_d, end_d, sec) in enumerate(section_boundaries):
        # Find time spent in this section from profiles
        in_section = [
            (t, d)
            for t, d in zip(time_profile, distance_profile)
            if start_d <= d < end_d
        ]
        if len(in_section) >= 2:
            sec_time = in_section[-1][0] - in_section[0][0]
        else:
            sec_time = 0
        section_results.append(
            {
                "grade_pct": sec.grade_pct,
                "distance_m": sec.distance_m,
                "distance_mi": sec.distance_m / MILES_TO_METERS,
                "target_power": power_per_section[idx],
                "time_s": sec_time,
            }
        )

    return {
        "total_time": elapsed,
        "total_distance": distance_covered,
        "time_profile": np.array(time_profile),
        "speed_profile": np.array(speed_profile),
        "power_target_profile": np.array(power_target_profile),
        "power_actual_profile": np.array(power_actual_profile),
        "exhaustion_profile": np.array(exhaustion_profile),
        "distance_profile": np.array(distance_profile),
        "grade_profile": np.array(grade_profile),
        "section_results": section_results,
    }


# ============================================================
# Optimizer: Find Best Power Allocation
# ============================================================
def optimize_power_profile(
    sections: List[SegmentSection],
    athlete: Athlete,
    entrance_speed_mph: float = 20.0,
    air_density: float = AIR_DENSITY_DEFAULT,
    wind_speed_ms: float = 0.0,
) -> Dict:
    """
    Find the per-section power allocation that minimizes total segment time,
    subject to exhaustion constraints (W' balance must not exceed ~97%).

    Two-phase approach:
      Phase 1: Find the best EVEN power (base_power) — the highest sustainable
               flat power that doesn't blow through exhaustion.
      Phase 2: Fix base at that level, search alpha to redistribute power
               proportionally to gradient:  power_i = base + alpha * (grade_i - avg)
               This finds how much variation improves time without changing
               the overall effort level.
    """
    n = len(sections)

    # --- Establish the even-power baseline ---
    total_dist = segment_total_distance(sections)
    est_duration_s = max(30, total_dist / 6.0)
    even_power_init = athlete.max_power_for_duration(est_duration_s)

    # First pass at safe dt=0.5 to get accurate time
    even_sim_init = simulate_segment(
        sections,
        [even_power_init] * n,
        athlete,
        entrance_speed_mph,
        air_density,
        dt=0.5,
        wind_speed_ms=wind_speed_ms,
    )
    even_power = athlete.max_power_for_duration(even_sim_init["total_time"])

    # Adaptive timestep based on actual duration AND section count
    actual_est = even_sim_init["total_time"]
    avg_section_time = actual_est / max(n, 1)
    # At least 300 total steps, AND at least 40 steps per section
    dt_from_total = actual_est / 300
    dt_from_sections = avg_section_time / 40
    opt_dt = max(0.25, min(0.75, min(dt_from_total, dt_from_sections)))
    search_dt = opt_dt

    even_sim_ref = simulate_segment(
        sections,
        [even_power] * n,
        athlete,
        entrance_speed_mph,
        air_density,
        dt=opt_dt,
        wind_speed_ms=wind_speed_ms,
    )
    even_time = even_sim_ref["total_time"]

    # --- Grade-proportional power allocation ---
    avg_grade = segment_avg_grade(sections)
    grade_offsets = np.array([s.grade_pct - avg_grade for s in sections])

    # Power bounds
    p1min = athlete.power_curve.get(60, athlete.cp * 1.5)
    lower_clamp = athlete.cp * 0.3
    upper_clamp = max(p1min * 1.2, athlete.cp * 2.0, even_power * 1.5)

    def make_powers(base, alpha):
        """Generate per-section powers from base + alpha * grade_offset."""
        return [
            max(lower_clamp, min(upper_clamp, base + alpha * go))
            for go in grade_offsets
        ]

    def simulate_and_score(base, alpha):
        """Simulate and return (time + penalty, exhaustion)."""
        powers = make_powers(base, alpha)
        sim = simulate_segment(
            sections,
            powers,
            athlete,
            entrance_speed_mph,
            air_density,
            dt=search_dt,
            wind_speed_ms=wind_speed_ms,
        )
        time = sim["total_time"]
        max_exh = max(sim["exhaustion_profile"])

        penalty = 0.0
        if max_exh > 98:
            penalty += (max_exh - 98) ** 2 * 10
        return time + penalty

    # === Search: for each base, find the best alpha, then pick overall best ===
    # This ensures we explore varied power at every effort level
    base_lo = athlete.cp * 0.7
    base_hi = even_power * 1.15
    base_step = max(1, (base_hi - base_lo) / 40)

    max_offset = max(abs(grade_offsets)) if len(grade_offsets) > 0 else 1
    global_max_alpha = min(25, (upper_clamp - base_hi) / max(max_offset, 0.1))
    # Ensure we search at least up to alpha=10
    global_max_alpha = max(global_max_alpha, 10)

    best_cost = float("inf")
    best_base = even_power
    best_alpha = 0

    for base in np.arange(base_lo, base_hi + base_step, base_step):
        for alpha in np.arange(0, global_max_alpha + 0.5, 0.5):
            cost = simulate_and_score(base, alpha)
            if cost < best_cost:
                best_cost = cost
                best_base = base
                best_alpha = alpha

    # === Fine-tune around best point ===
    for base in np.arange(best_base - 3, best_base + 4, 1):
        for alpha in np.arange(max(0, best_alpha - 1), best_alpha + 1.5, 0.25):
            cost = simulate_and_score(base, alpha)
            if cost < best_cost:
                best_cost = cost
                best_base = base
                best_alpha = alpha

    optimal_powers = make_powers(best_base, best_alpha)

    # --- Final simulation at fine dt ---
    sim = simulate_segment(
        sections,
        optimal_powers,
        athlete,
        entrance_speed_mph,
        air_density,
        dt=opt_dt,
        wind_speed_ms=wind_speed_ms,
    )

    # Guard: fall back to even power if optimized is not meaningfully better
    even_sim_final = simulate_segment(
        sections,
        [even_power] * n,
        athlete,
        entrance_speed_mph,
        air_density,
        dt=opt_dt,
        wind_speed_ms=wind_speed_ms,
    )
    if sim["total_time"] > even_sim_final["total_time"] + 0.5:
        sim = even_sim_final
        optimal_powers = [even_power] * n

    sim["optimal_powers"] = optimal_powers
    sim["optimizer_success"] = True
    return sim


# ============================================================
# Flat-Equivalent Baseline
# ============================================================
def simulate_flat_equivalent(
    sections: List[SegmentSection],
    athlete: Athlete,
    entrance_speed_mph: float = 20.0,
    air_density: float = AIR_DENSITY_DEFAULT,
    wind_speed_ms: float = 0.0,
) -> Dict:
    """
    Simulate the same total distance at the average gradient with a single
    constant power (athlete's sustainable power for the estimated duration).
    This is the "naive" baseline to compare against variable pacing.
    """
    total_dist = segment_total_distance(sections)
    avg_grade = segment_avg_grade(sections)

    # Create a single-section segment
    flat_section = [SegmentSection(avg_grade, total_dist / MILES_TO_METERS)]

    # Estimate duration, pick sustainable power
    est_time = max(30, total_dist / 6.0)
    power = athlete.max_power_for_duration(est_time)

    # Simulate
    sim = simulate_segment(
        flat_section,
        [power],
        athlete,
        entrance_speed_mph,
        air_density,
        wind_speed_ms=wind_speed_ms,
    )

    # Refine: re-estimate power for actual duration
    actual_time = sim["total_time"]
    refined_power = athlete.max_power_for_duration(actual_time)
    sim = simulate_segment(
        flat_section,
        [refined_power],
        athlete,
        entrance_speed_mph,
        air_density,
        wind_speed_ms=wind_speed_ms,
    )
    sim["constant_power"] = refined_power
    return sim


# ============================================================
# Plotting
# ============================================================
def plot_results(sim: Dict, title: str = "Segment Simulation"):
    """Plot speed, power, exhaustion, and gradient profiles."""
    t = sim["time_profile"]
    d = sim["distance_profile"] / MILES_TO_METERS  # miles

    fig, axes = plt.subplots(4, 1, figsize=(7, 6), sharex=True)
    fig.suptitle(title, fontsize=10, fontweight="bold")

    # 1. Speed
    ax = axes[0]
    speed_mph = sim["speed_profile"] * 2.237
    ax.plot(d, speed_mph, color="#2563EB", linewidth=1.5)
    ax.set_ylabel("Speed (mph)")
    ax.grid(True, alpha=0.3)
    ax.fill_between(d, speed_mph, alpha=0.1, color="#2563EB")

    # 2. Power
    ax = axes[1]
    ax.plot(
        d,
        sim["power_target_profile"],
        color="#16A34A",
        linestyle="--",
        linewidth=1,
        label="Target Power",
        alpha=0.7,
    )
    ax.plot(
        d,
        sim["power_actual_profile"],
        color="#2563EB",
        linewidth=1.5,
        label="Actual Power",
    )
    ax.set_ylabel("Power (W)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)

    # 3. Exhaustion
    ax = axes[2]
    ax.plot(d, sim["exhaustion_profile"], color="#DC2626", linewidth=1.5)
    ax.axhline(100, linestyle="--", color="black", alpha=0.5, label="Limit")
    ax.set_ylabel("Exhaustion (%)")
    ax.set_ylim(-5, 110)
    ax.grid(True, alpha=0.3)
    ax.fill_between(d, sim["exhaustion_profile"], alpha=0.1, color="#DC2626")

    # 4. Gradient
    ax = axes[3]
    ax.fill_between(d, sim["grade_profile"], alpha=0.3, color="#F59E0B", step="post")
    ax.step(d, sim["grade_profile"], color="#D97706", linewidth=1.5, where="post")
    ax.set_ylabel("Grade (%)")
    ax.set_xlabel("Distance (miles)")
    ax.grid(True, alpha=0.3)
    ax.axhline(0, color="black", linewidth=0.5)

    plt.tight_layout()
    return fig


def plot_comparison(variable_sim: Dict, flat_sim: Dict, optimized_sim: Dict = None):
    """Compare variable-gradient pacing vs flat-equivalent vs optimized."""
    fig, axes = plt.subplots(2, 1, figsize=(7, 4))
    fig.suptitle("Pacing Strategy Comparison", fontsize=10, fontweight="bold")

    # Speed comparison
    ax = axes[0]
    d_var = variable_sim["distance_profile"] / MILES_TO_METERS
    d_flat = flat_sim["distance_profile"] / MILES_TO_METERS

    ax.plot(
        d_var,
        variable_sim["speed_profile"] * 2.237,
        color="#2563EB",
        linewidth=1.5,
        label="Even Power (variable grade)",
    )
    ax.plot(
        d_flat,
        flat_sim["speed_profile"] * 2.237,
        color="#9CA3AF",
        linewidth=1.5,
        linestyle="--",
        label="Even Power (avg grade)",
    )
    if optimized_sim:
        d_opt = optimized_sim["distance_profile"] / MILES_TO_METERS
        ax.plot(
            d_opt,
            optimized_sim["speed_profile"] * 2.237,
            color="#16A34A",
            linewidth=2,
            label="Optimized Pacing",
        )
    ax.set_ylabel("Speed (mph)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    # Power comparison
    ax = axes[1]
    ax.plot(
        d_var,
        variable_sim["power_actual_profile"],
        color="#2563EB",
        linewidth=1.5,
        label="Even Power",
    )
    if optimized_sim:
        ax.plot(
            d_opt,
            optimized_sim["power_actual_profile"],
            color="#16A34A",
            linewidth=2,
            label="Optimized",
        )
    ax.axhline(
        flat_sim.get("constant_power", 0),
        color="#9CA3AF",
        linestyle="--",
        label="Flat-equiv power",
    )
    ax.set_ylabel("Power (W)")
    ax.set_xlabel("Distance (miles)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    return fig


# ============================================================
# Print Summary
# ============================================================
def print_summary(label: str, sim: Dict, sections: List[SegmentSection] = None) -> Dict:
    """Collect summary stats into a dict (for columnar printing later). Also prints standalone."""
    total_time = sim["total_time"]
    mins = int(total_time // 60)
    secs = total_time % 60
    total_dist_mi = sim["total_distance"] / MILES_TO_METERS
    avg_speed_mph = (
        (sim["total_distance"] / total_time) * 2.237 if total_time > 0 else 0
    )
    max_exhaust = max(sim["exhaustion_profile"])

    if "section_results" in sim:
        sr_list = sim["section_results"]
        grades_used = sorted(set(sr["grade_pct"] for sr in sr_list))
        powers_used = sorted(set(round(sr["target_power"]) for sr in sr_list))
        n_sections = len(sr_list)
    elif sections:
        grades_used = sorted(set(s.grade_pct for s in sections))
        powers_used = []
        n_sections = len(sections)
    else:
        grades_used = []
        powers_used = []
        n_sections = 0

    stats = {
        "label": label,
        "n_sections": n_sections,
        "n_grades": len(grades_used),
        "n_powers": len(powers_used),
        "grades": grades_used,
        "powers": powers_used,
        "time_str": f"{mins}:{secs:05.2f}",
        "time_s": total_time,
        "distance_mi": total_dist_mi,
        "avg_speed_mph": avg_speed_mph,
        "peak_exhaustion": max_exhaust,
        "section_results": sim.get("section_results", []),
        "optimal_powers": sim.get("optimal_powers"),
    }
    return stats


def print_columnar_comparison(stats_list: List[Dict], reference_idx: int = 0):
    """Print all simulations side-by-side in aligned columns."""
    n = len(stats_list)
    COL_W = 30  # width of each data column
    LABEL_W = 20  # width of the row label column

    ref_time = stats_list[reference_idx]["time_s"]

    def _pad(s, w=COL_W):
        return str(s).center(w)

    sep = "─" * LABEL_W + ("─" * COL_W) * n

    # Header row: strategy labels
    print(f"\n{'═' * (LABEL_W + COL_W * n)}")
    print(f"  SIDE-BY-SIDE COMPARISON")
    print(f"{'═' * (LABEL_W + COL_W * n)}")

    header = " " * LABEL_W
    for s in stats_list:
        header += _pad(s["label"][: COL_W - 2])
    print(header)
    print(sep)

    # Dimension rows
    row = f"{'  # Powers':<{LABEL_W}}"
    for s in stats_list:
        row += _pad(f"{s['n_powers']}")
    print(row)

    row = f"{'  Power values':<{LABEL_W}}"
    for s in stats_list:
        pstr = ", ".join(f"{p:.0f}W" for p in s["powers"]) if s["powers"] else "—"
        row += _pad(pstr)
    print(row)

    row = f"{'  # Gradients':<{LABEL_W}}"
    for s in stats_list:
        row += _pad(f"{s['n_grades']}")
    print(row)

    row = f"{'  Grade values':<{LABEL_W}}"
    for s in stats_list:
        gstr = ", ".join(f"{g:.1f}%" for g in s["grades"])
        row += _pad(gstr)
    print(row)

    print(sep)

    # Results rows
    row = f"{'  Total Time':<{LABEL_W}}"
    for s in stats_list:
        row += _pad(s["time_str"])
    print(row)

    row = f"{'  Δ vs basic model':<{LABEL_W}}"
    for s in stats_list:
        delta = s["time_s"] - ref_time
        if abs(delta) < 0.01:
            row += _pad("(baseline)")
        else:
            row += _pad(f"{delta:+.1f}s")
    print(row)

    row = f"{'  Avg Speed':<{LABEL_W}}"
    for s in stats_list:
        row += _pad(f"{s['avg_speed_mph']:.1f} mph")
    print(row)

    row = f"{'  Peak Exhaustion':<{LABEL_W}}"
    for s in stats_list:
        row += _pad(f"{s['peak_exhaustion']:.1f}%")
    print(row)

    print(sep)

    # Per-section breakdown (only for multi-section sims)
    max_sections = max(s["n_sections"] for s in stats_list)
    if max_sections > 1:
        for sec_i in range(max_sections):
            row = f"{'  Sec ' + str(sec_i+1) + ' grade':<{LABEL_W}}"
            for s in stats_list:
                sr = s["section_results"]
                if sec_i < len(sr):
                    row += _pad(f"{sr[sec_i]['grade_pct']:.1f}%")
                else:
                    row += _pad("—")
            print(row)

            row = f"{'  Sec ' + str(sec_i+1) + ' power':<{LABEL_W}}"
            for s in stats_list:
                sr = s["section_results"]
                if sec_i < len(sr):
                    row += _pad(f"{sr[sec_i]['target_power']:.0f} W")
                else:
                    row += _pad("—")
            print(row)

            row = f"{'  Sec ' + str(sec_i+1) + ' time':<{LABEL_W}}"
            for s in stats_list:
                sr = s["section_results"]
                if sec_i < len(sr):
                    m = int(sr[sec_i]["time_s"] // 60)
                    sc = sr[sec_i]["time_s"] % 60
                    row += _pad(f"{m}:{sc:04.1f}")
                else:
                    row += _pad("—")
            print(row)

        print(sep)

    # Notes
    for s in stats_list:
        if s["n_grades"] == 1 and max_sections > 1:
            print(
                f"\n  ⚠  \"{s['label']}\" uses 1 averaged gradient ({s['grades'][0]:.1f}%)."
            )
            print(f"     This is unrealistic — real roads have variable grade, so this")
            print(f"     time is a theoretical lower bound, not an achievable target.")

    if any(s.get("optimal_powers") for s in stats_list):
        for s in stats_list:
            if s.get("optimal_powers"):
                print(
                    f"\n  ✓  Optimal powers: {['%.0f W' % p for p in s['optimal_powers']]}"
                )

    print(f"{'═' * (LABEL_W + COL_W * n)}\n")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":

    # ---------------------------------------------------------
    # 1. Define your power curve: {seconds: watts}
    # ---------------------------------------------------------
    power_curve = {
        60: 500,  # 1-min power
        180: 420,  # 3-min power
        480: 360,  # 8-min power
        1200: 320,  # 20-min power
    }

    athlete = Athlete(
        power_curve=power_curve,
        weight_kg=75,
        bike_weight_kg=8,
        cda=0.32,
        crr=0.004,
    )

    print(f"Athlete Profile:")
    print(f"  CP:  {athlete.cp:.0f} W")
    print(f"  W':  {athlete.w_prime / 1000:.1f} kJ")
    print(f"  Weight: {athlete.total_weight:.0f} kg (rider + bike)")

    # ---------------------------------------------------------
    # 2. Define the segment: (grade_percent, distance_miles)
    #
    #    *** EDIT THIS to model your segment ***
    # ---------------------------------------------------------
    segment_pieces = [
        (9.0, 0.50),  # 6% grade for 0.5 miles
        (3.0, 0.50),  # 3% grade for 0.5 miles
    ]

    sections = build_segment(segment_pieces)

    total_dist_mi = segment_total_distance(sections) / MILES_TO_METERS
    avg_grade = segment_avg_grade(sections)
    total_elev_m = sum(
        s.distance_m * math.sin(math.atan(s.grade_pct / 100)) for s in sections
    )
    total_elev_ft = total_elev_m * 3.28084

    print(f"\nSegment Definition:")
    for i, (g, d) in enumerate(segment_pieces):
        print(f"  Section {i+1}: {g:.1f}% grade × {d:.2f} mi")
    print(
        f"  Total:    {total_dist_mi:.2f} mi | Avg Grade: {avg_grade:.1f}% | "
        f"Elevation: {total_elev_ft:.0f} ft ({total_elev_m:.0f} m)"
    )

    n_sections = len(sections)
    n_distinct_grades = len(set(g for g, d in segment_pieces))
    entrance_speed_mph = 20.0

    # ---------------------------------------------------------
    # 3. Even-power simulation (constant power, variable grade)
    # ---------------------------------------------------------
    est_time = segment_total_distance(sections) / 6.0
    even_power = athlete.max_power_for_duration(est_time)
    even_powers = [even_power] * len(sections)

    even_sim = simulate_segment(sections, even_powers, athlete, entrance_speed_mph)

    # Refine power estimate
    refined_power = athlete.max_power_for_duration(even_sim["total_time"])
    even_powers = [refined_power] * len(sections)
    even_sim = simulate_segment(sections, even_powers, athlete, entrance_speed_mph)

    even_stats = print_summary(
        f"1P × {n_distinct_grades}G  detailed gradient",
        even_sim,
        sections,
    )

    # ---------------------------------------------------------
    # 4. Basic model baseline (avg grade, constant power)
    # ---------------------------------------------------------
    flat_sim = simulate_flat_equivalent(sections, athlete, entrance_speed_mph)
    flat_stats = print_summary(
        f"1P × 1G  basic model",
        flat_sim,
    )

    # ---------------------------------------------------------
    # 5. Optimized pacing (variable power per section)
    # ---------------------------------------------------------
    print("Optimizing power profile... (this may take a moment)")
    opt_sim = optimize_power_profile(sections, athlete, entrance_speed_mph)
    n_opt_powers = len(set(round(p) for p in opt_sim["optimal_powers"]))
    opt_stats = print_summary(
        f"{n_opt_powers}P × {n_distinct_grades}G  optimized advanced",
        opt_sim,
        sections,
    )

    # ---------------------------------------------------------
    # 6. Side-by-side columnar comparison
    #    Column order: basic model (baseline) | detailed gradient | optimized advanced
    # ---------------------------------------------------------
    print_columnar_comparison([flat_stats, even_stats, opt_stats], reference_idx=0)

    # ---------------------------------------------------------
    # 7. Plots
    # ---------------------------------------------------------
    fig1 = plot_results(even_sim, "Detailed Gradient — 1 Power × Variable Grade")
    fig2 = plot_results(opt_sim, "Optimized Advanced — Variable Power × Variable Grade")
    fig3 = plot_comparison(even_sim, flat_sim, opt_sim)

    plt.show()
