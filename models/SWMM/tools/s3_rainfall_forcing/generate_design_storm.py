#!/usr/bin/env python3
"""
Generate synthetic design storms for SWMM simulation.

Supports:
  - SCS Type I, IA, II, III rainfall distributions (24-hour design storms)
  - Chicago design storm (custom duration, user-specified peak position)
  - Uniform intensity (constant rate for duration)
  - Triangular hyetograph

Each method produces a SWMM-compatible timeseries file with intensities
in mm/hr at the specified timestep.

Inputs:
  - Storm type and parameters
  - Total depth (mm) and duration (hours)
  - Timestep (minutes)

Outputs:
  - SWMM timeseries file (.dat)
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# SCS cumulative rainfall fractions (fraction of total depth vs. fraction of duration)
# Source: USDA TR-55, interpolated to 0.1 increments
SCS_DISTRIBUTIONS = {
    "SCS_I": [
        0.000, 0.017, 0.035, 0.055, 0.076, 0.100, 0.125, 0.156, 0.194, 0.254,
        0.515, 0.624, 0.682, 0.727, 0.767, 0.799, 0.826, 0.851, 0.874, 0.895,
        0.914, 0.932, 0.948, 0.964, 0.980, 1.000,
    ],
    "SCS_IA": [
        0.000, 0.020, 0.050, 0.082, 0.116, 0.156, 0.206, 0.268, 0.425, 0.520,
        0.577, 0.624, 0.664, 0.701, 0.736, 0.768, 0.800, 0.830, 0.858, 0.886,
        0.910, 0.932, 0.952, 0.968, 0.984, 1.000,
    ],
    "SCS_II": [
        0.000, 0.011, 0.022, 0.035, 0.048, 0.063, 0.080, 0.098, 0.120, 0.147,
        0.181, 0.235, 0.663, 0.735, 0.776, 0.804, 0.825, 0.842, 0.856, 0.869,
        0.881, 0.893, 0.905, 0.922, 0.950, 1.000,
    ],
    "SCS_III": [
        0.000, 0.010, 0.020, 0.032, 0.043, 0.055, 0.070, 0.085, 0.104, 0.130,
        0.164, 0.206, 0.515, 0.583, 0.641, 0.695, 0.742, 0.782, 0.816, 0.845,
        0.870, 0.891, 0.910, 0.928, 0.950, 1.000,
    ],
}


def generate_scs_storm(scs_type, total_depth_mm, duration_hr, timestep_min):
    """Generate SCS design storm hyetograph."""
    cum_fracs = SCS_DISTRIBUTIONS[scs_type]
    n_intervals = len(cum_fracs) - 1  # 24 intervals for 24-hour storm

    # Interpolate cumulative fractions to desired timestep
    n_steps = int(duration_hr * 60 / timestep_min)
    time_fracs = np.linspace(0, 1, n_steps + 1)
    cum_interp = np.interp(time_fracs, np.linspace(0, 1, len(cum_fracs)), cum_fracs)

    # Incremental depths
    incremental = np.diff(cum_interp) * total_depth_mm

    # Convert to intensity (mm/hr)
    timestep_hr = timestep_min / 60.0
    intensities = incremental / timestep_hr

    return intensities


def generate_chicago_storm(total_depth_mm, duration_hr, timestep_min, r=0.4):
    """
    Generate Chicago design storm.

    r = peak position ratio (0-1), default 0.4 means peak at 40% of duration.
    Uses IDF-based temporal distribution.
    """
    n_steps = int(duration_hr * 60 / timestep_min)
    timestep_hr = timestep_min / 60.0

    # Time array centered on peak
    peak_time = r * duration_hr
    times = np.linspace(0, duration_hr, n_steps)

    # Chicago formula: i(t) = a / (t_c + b)^n * (1 - n * (t-tp)/(t_c + b))
    # Simplified version using exponential decay from peak
    a = 2.0  # shape parameter
    intensities = np.zeros(n_steps)

    for i, t in enumerate(times):
        dt = abs(t - peak_time)
        intensities[i] = np.exp(-a * (dt / duration_hr) ** 1.5)

    # Normalize to match total depth
    current_total = np.sum(intensities) * timestep_hr
    if current_total > 0:
        intensities = intensities * (total_depth_mm / current_total) / timestep_hr

    return intensities


def generate_uniform_storm(total_depth_mm, duration_hr, timestep_min):
    """Generate uniform-intensity storm."""
    n_steps = int(duration_hr * 60 / timestep_min)
    intensity = total_depth_mm / duration_hr  # mm/hr
    return np.full(n_steps, intensity)


def generate_triangular_storm(total_depth_mm, duration_hr, timestep_min, peak_ratio=0.4):
    """Generate triangular hyetograph."""
    n_steps = int(duration_hr * 60 / timestep_min)
    timestep_hr = timestep_min / 60.0

    peak_idx = int(peak_ratio * n_steps)
    intensities = np.zeros(n_steps)

    # Rising limb
    for i in range(peak_idx):
        intensities[i] = (i + 1) / (peak_idx + 1)
    # Falling limb
    for i in range(peak_idx, n_steps):
        intensities[i] = 1.0 - (i - peak_idx) / (n_steps - peak_idx)

    # Normalize to total depth
    current_total = np.sum(intensities) * timestep_hr
    if current_total > 0:
        intensities = intensities * (total_depth_mm / current_total) / timestep_hr

    return intensities


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic design storms for SWMM"
    )
    parser.add_argument("--type", required=True,
                        choices=["SCS_I", "SCS_IA", "SCS_II", "SCS_III",
                                 "Chicago", "Uniform", "Triangular"],
                        help="Storm type")
    parser.add_argument("--depth_mm", type=float, required=True,
                        help="Total rainfall depth (mm)")
    parser.add_argument("--duration_hr", type=float, default=24.0,
                        help="Storm duration (hours, default: 24)")
    parser.add_argument("--timestep_min", type=float, default=5.0,
                        help="Output timestep (minutes, default: 5)")
    parser.add_argument("--output", required=True,
                        help="Output SWMM timeseries file (.dat)")
    parser.add_argument("--series_name", default="DesignStorm",
                        help="Timeseries name (default: DesignStorm)")
    parser.add_argument("--start_datetime", default="01/01/2000 00:00:00",
                        help="Start date/time (MM/DD/YYYY HH:MM:SS)")
    parser.add_argument("--peak_ratio", type=float, default=0.4,
                        help="Peak position ratio for Chicago/Triangular (default: 0.4)")
    args = parser.parse_args()

    if args.depth_mm <= 0:
        print("ERROR: depth_mm must be positive", file=sys.stderr)
        sys.exit(1)
    if args.duration_hr <= 0:
        print("ERROR: duration_hr must be positive", file=sys.stderr)
        sys.exit(1)
    if args.timestep_min <= 0:
        print("ERROR: timestep_min must be positive", file=sys.stderr)
        sys.exit(1)

    print(f"Generating {args.type} design storm")
    print(f"  Total depth: {args.depth_mm} mm")
    print(f"  Duration: {args.duration_hr} hr")
    print(f"  Timestep: {args.timestep_min} min")

    # Generate hyetograph
    if args.type.startswith("SCS_"):
        intensities = generate_scs_storm(args.type, args.depth_mm,
                                         args.duration_hr, args.timestep_min)
    elif args.type == "Chicago":
        intensities = generate_chicago_storm(args.depth_mm, args.duration_hr,
                                             args.timestep_min, args.peak_ratio)
    elif args.type == "Uniform":
        intensities = generate_uniform_storm(args.depth_mm, args.duration_hr,
                                             args.timestep_min)
    elif args.type == "Triangular":
        intensities = generate_triangular_storm(args.depth_mm, args.duration_hr,
                                                args.timestep_min, args.peak_ratio)

    # Parse start datetime
    try:
        start_dt = datetime.strptime(args.start_datetime, "%m/%d/%Y %H:%M:%S")
    except ValueError:
        start_dt = datetime(2000, 1, 1, 0, 0, 0)

    # Write SWMM timeseries
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_written = 0
    with open(output_path, "w") as f:
        f.write(f";;SWMM Design Storm: {args.type}\n")
        f.write(f";;Depth: {args.depth_mm} mm, Duration: {args.duration_hr} hr\n")
        f.write(f";;Timestep: {args.timestep_min} min\n")
        f.write(";;\n")
        dt = start_dt
        for intensity in intensities:
            if intensity > 0.0001:
                date_str = dt.strftime("%m/%d/%Y")
                time_str = dt.strftime("%H:%M:%S")
                f.write(f"{args.series_name}\t{date_str}\t{time_str}\t{intensity:.4f}\n")
                n_written += 1
            dt += timedelta(minutes=args.timestep_min)

    print(f"\nDesign storm written: {output_path}")
    print(f"  {n_written} entries, Peak intensity: {max(intensities):.2f} mm/hr")
    actual_depth = sum(intensities) * (args.timestep_min / 60.0)
    print(f"  Verified total depth: {actual_depth:.2f} mm (target: {args.depth_mm} mm)")


if __name__ == "__main__":
    main()
