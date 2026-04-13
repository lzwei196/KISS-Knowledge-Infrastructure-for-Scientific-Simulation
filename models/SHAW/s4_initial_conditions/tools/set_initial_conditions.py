#!/usr/bin/env python3
"""
set_initial_conditions.py — Generate SHAW initial moisture and temperature profiles.

Creates .moi and .tem files from:
1. VIC output soil moisture/temperature (preferred for coupling)
2. Climatological defaults based on location and season
3. User-specified uniform values

Moisture format: JDAY JHR JYR VLCDT(1..NS)
    where VLCDT = volumetric water content (m3/m3) at each soil node

Temperature format: JDAY JHR JYR TSDT(1..NS)
    where TSDT = temperature (C) at each soil node

SHAW requires at least 2 profiles in each file:
- One on or before the simulation start date
- One on or after the simulation end date

Usage:
    python set_initial_conditions.py \
        --ns 11 --max_depth 4.0 \
        --start_jday 1 --start_year 2005 \
        --end_jday 365 --end_year 2005 \
        --lat 46.75 \
        --output_moi trial.moi --output_tem trial.tem \
        [--init_moisture 0.30] [--init_temp 8.0] \
        [--vic_output_dir outputs/<run>/vic_result] \
        [--vic_lat 46.75 --vic_lon -116.95]
"""

import argparse
import math
from pathlib import Path


def estimate_soil_temperature_profile(lat, jday, ns, max_depth, annual_mean_temp=None):
    """
    Estimate initial soil temperature profile from latitude and day of year.

    Uses sinusoidal approximation:
    T(z,t) = T_mean + A * exp(-z/d) * sin(2*pi*t/365 - z/d)

    where:
    - T_mean = estimated mean annual temperature from latitude
    - A = annual temperature amplitude (~15C at 45N)
    - d = damping depth (~1-2 m)
    """
    if annual_mean_temp is not None:
        t_mean = annual_mean_temp
    else:
        # Rough estimate: T_mean ~ 25 - 0.5 * |lat|
        t_mean = 25.0 - 0.5 * abs(lat)
        t_mean = max(-5.0, min(30.0, t_mean))

    # Annual amplitude at surface
    amplitude = 10.0 + 0.2 * abs(lat)
    amplitude = min(amplitude, 25.0)

    # Damping depth (m) - depends on soil thermal diffusivity
    damping_depth = 1.5

    # Time phase (radians) - day 0 = coldest
    # Northern hemisphere: coldest ~ day 15, warmest ~ day 196
    if lat >= 0:
        t_phase = 2.0 * math.pi * (jday - 15) / 365.0
    else:
        t_phase = 2.0 * math.pi * (jday - 196) / 365.0

    # Generate depths
    depths = []
    step = max_depth / (ns - 1) if ns > 1 else max_depth
    for i in range(ns):
        depths.append(i * step)

    # Compute temperature at each depth
    temps = []
    for z in depths:
        t = t_mean + amplitude * math.exp(-z / damping_depth) * math.sin(t_phase - z / damping_depth)
        temps.append(round(t, 1))

    return temps


def estimate_soil_moisture_profile(lat, jday, ns, max_depth, init_moisture=None):
    """
    Estimate initial soil moisture profile.

    Uses simple depth-dependent model:
    - Surface: drier (evaporation)
    - Mid-depth: near field capacity
    - Deep: gravitational drainage toward field capacity
    """
    if init_moisture is not None:
        return [round(init_moisture, 3)] * ns

    # Rough estimate of annual precipitation from latitude
    # (very approximate, just for initialization)
    if abs(lat) < 15:
        # Tropical: wet
        base_moisture = 0.35
    elif abs(lat) < 35:
        # Subtropical: moderate
        base_moisture = 0.28
    elif abs(lat) < 55:
        # Mid-latitude: moderate
        base_moisture = 0.30
    else:
        # High latitude: variable
        base_moisture = 0.32

    # Seasonal adjustment
    if lat >= 0:
        # Northern hemisphere: driest in summer (DOY 180-240)
        if 150 < jday < 270:
            seasonal_factor = 0.85
        elif jday < 90 or jday > 330:
            seasonal_factor = 1.05  # spring snowmelt / winter wet
        else:
            seasonal_factor = 0.95
    else:
        # Southern hemisphere: shift by 6 months
        shifted = (jday + 182) % 365
        if 150 < shifted < 270:
            seasonal_factor = 0.85
        elif shifted < 90 or shifted > 330:
            seasonal_factor = 1.05
        else:
            seasonal_factor = 0.95

    # Depth-dependent moisture
    depths = []
    step = max_depth / (ns - 1) if ns > 1 else max_depth
    for i in range(ns):
        depths.append(i * step)

    moistures = []
    for z in depths:
        if z < 0.1:
            # Surface: drier
            m = base_moisture * seasonal_factor * 0.80
        elif z < 0.5:
            # Near surface: moderate
            m = base_moisture * seasonal_factor * 0.95
        elif z < 1.5:
            # Root zone: near field capacity
            m = base_moisture * seasonal_factor
        else:
            # Deep: gradually increasing to near saturation
            m = base_moisture * seasonal_factor * 1.05
        moistures.append(round(min(m, 0.55), 3))

    return moistures


def write_moisture_file(moistures_start, moistures_end, start_jday, start_year,
                        end_jday, end_year, output_path, start_hour=12):
    """Write SHAW moisture profile file (.moi)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    yr_start = start_year % 100
    yr_end = end_year % 100

    with open(output_path, 'w') as f:
        # Profile at start
        moist_str = ' '.join(f'{m:.3f}' for m in moistures_start)
        f.write(f" {start_jday:3d} {start_hour:2d} {yr_start:2d} {moist_str}\n")

        # Profile at end
        moist_str = ' '.join(f'{m:.3f}' for m in moistures_end)
        f.write(f" {end_jday:3d} {start_hour:2d} {yr_end:2d} {moist_str}\n")

    print(f"Moisture file written: {output_path}")
    print(f"  Nodes: {len(moistures_start)}")
    print(f"  Mean moisture (start): {sum(moistures_start)/len(moistures_start):.3f} m3/m3")


def write_temperature_file(temps_start, temps_end, start_jday, start_year,
                           end_jday, end_year, output_path, start_hour=12):
    """Write SHAW temperature profile file (.tem)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    yr_start = start_year % 100
    yr_end = end_year % 100

    with open(output_path, 'w') as f:
        # Profile at start
        temp_str = ' '.join(f'{t:.1f}' for t in temps_start)
        f.write(f" {start_jday:3d} {start_hour:2d} {yr_start:2d} {temp_str}\n")

        # Profile at end (use 99999 for unknown -> model interpolates)
        # Or compute end profile
        temp_str = ' '.join(f'{t:.1f}' for t in temps_end)
        f.write(f" {end_jday:3d} {start_hour:2d} {yr_end:2d} {temp_str}\n")

    print(f"Temperature file written: {output_path}")
    print(f"  Nodes: {len(temps_start)}")
    print(f"  Surface temp (start): {temps_start[0]:.1f} C")
    print(f"  Deep temp (start): {temps_start[-1]:.1f} C")


def main():
    parser = argparse.ArgumentParser(description="Generate SHAW initial conditions")
    parser.add_argument("--ns", type=int, required=True, help="Number of soil nodes")
    parser.add_argument("--max_depth", type=float, default=4.0, help="Max soil depth (m)")
    parser.add_argument("--start_jday", type=int, required=True, help="Start day of year")
    parser.add_argument("--start_year", type=int, required=True, help="Start year")
    parser.add_argument("--end_jday", type=int, required=True, help="End day of year")
    parser.add_argument("--end_year", type=int, required=True, help="End year")
    parser.add_argument("--lat", type=float, required=True, help="Latitude")
    parser.add_argument("--output_moi", type=str, required=True, help="Output moisture file")
    parser.add_argument("--output_tem", type=str, required=True, help="Output temperature file")
    parser.add_argument("--init_moisture", type=float, default=None,
                        help="Uniform initial moisture (m3/m3)")
    parser.add_argument("--init_temp", type=float, default=None,
                        help="Annual mean soil temperature (C)")
    parser.add_argument("--start_hour", type=int, default=12, help="Hour for profiles")

    args = parser.parse_args()

    # Generate temperature profiles
    temps_start = estimate_soil_temperature_profile(
        args.lat, args.start_jday, args.ns, args.max_depth, args.init_temp)
    temps_end = estimate_soil_temperature_profile(
        args.lat, args.end_jday, args.ns, args.max_depth, args.init_temp)

    # Generate moisture profiles
    moistures_start = estimate_soil_moisture_profile(
        args.lat, args.start_jday, args.ns, args.max_depth, args.init_moisture)
    moistures_end = estimate_soil_moisture_profile(
        args.lat, args.end_jday, args.ns, args.max_depth, args.init_moisture)

    # Write files
    write_moisture_file(moistures_start, moistures_end,
                        args.start_jday, args.start_year,
                        args.end_jday, args.end_year,
                        args.output_moi, args.start_hour)

    write_temperature_file(temps_start, temps_end,
                           args.start_jday, args.start_year,
                           args.end_jday, args.end_year,
                           args.output_tem, args.start_hour)


if __name__ == "__main__":
    main()
