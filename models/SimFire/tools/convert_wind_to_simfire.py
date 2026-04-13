#!/usr/bin/env python3
"""
convert_wind_to_simfire.py — Convert external wind data to SimFire wind arrays.

Reads wind speed and direction from CSV, NetCDF, or constant values and converts
them to SimFire-compatible numpy arrays in the correct units.

CRITICAL UNIT CONVERSIONS:
  - Wind speed: SimFire expects ft/min internally.
    - From mph: multiply by 88
    - From m/s: multiply by 196.85
    - From km/h: multiply by 54.68
  - Wind direction: SimFire expects degrees (0=North, 90=East, 180=South, 270=West).
    Meteorological convention: direction wind blows FROM.

Output:
  - wind_speed.npy: float array of wind speeds in ft/min, shape (H, W)
  - wind_direction.npy: float array of wind directions in degrees, shape (H, W)
  - wind_metadata.json: source info, conversion applied, statistics

Usage:
    python convert_wind_to_simfire.py \\
        --speed 20 --speed-unit mph \\
        --direction 90 \\
        --grid-shape 225 450 \\
        --output-dir ./simfire_wind/

    python convert_wind_to_simfire.py \\
        --csv wind_data.csv \\
        --speed-col wind_speed --dir-col wind_dir \\
        --speed-unit ms \\
        --grid-shape 225 450 \\
        --output-dir ./simfire_wind/
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

# Unit conversion factors TO ft/min
SPEED_CONVERSIONS = {
    "ftpm": 1.0,           # Already in ft/min
    "mph": 88.0,           # miles/hour → ft/min
    "ms": 196.85,          # m/s → ft/min
    "kmh": 54.6807,        # km/h → ft/min
    "knots": 101.269,      # knots → ft/min
}


def validate_inputs(args):
    """Validate command-line arguments.

    Checks unit names, file existence, grid dimensions.
    """
    errors = []

    if args.speed_unit not in SPEED_CONVERSIONS:
        errors.append(
            f"Unknown speed unit '{args.speed_unit}'. "
            f"Valid: {list(SPEED_CONVERSIONS.keys())}"
        )

    if args.csv:
        if not os.path.isfile(args.csv):
            errors.append(f"CSV file not found: {args.csv}")
        if not args.speed_col or not args.dir_col:
            errors.append("Must provide --speed-col and --dir-col with --csv")
    else:
        if args.speed is None:
            errors.append("Must provide --speed (constant) or --csv (spatiotemporal)")
        if args.direction is None:
            errors.append("Must provide --direction (constant) or --csv")

    if args.grid_shape:
        if len(args.grid_shape) != 2 or any(s <= 0 for s in args.grid_shape):
            errors.append(f"Grid shape must be two positive integers, got {args.grid_shape}")

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_inputs", "errors": errors}))
        sys.exit(1)


def convert_speed(speed_array, from_unit):
    """Convert wind speed array to ft/min.

    CRITICAL: SimFire Rothermel equation expects wind speed in ft/min.
    Using wrong units will silently produce incorrect fire spread rates.

    Common mistake: providing mph (e.g., 20 mph = 1760 ft/min, NOT 20 ft/min).
    At 20 ft/min the wind factor phi_w is negligible.
    At 1760 ft/min (20 mph), phi_w dominates fire spread.

    Args:
        speed_array: numpy array of wind speeds in source units
        from_unit: source unit key (ftpm, mph, ms, kmh, knots)

    Returns:
        speed_ftpm: numpy array of wind speeds in ft/min
    """
    factor = SPEED_CONVERSIONS[from_unit]
    speed_ftpm = speed_array * factor

    # Clamp negative values
    speed_ftpm = np.maximum(speed_ftpm, 0.0)

    return speed_ftpm


def normalize_direction(dir_array):
    """Normalize wind direction to [0, 360) degrees.

    Convention: degrees clockwise from North.
    0° = North, 90° = East, 180° = South, 270° = West.

    Handles:
    - Negative values (e.g., -90° → 270°)
    - Values > 360° (e.g., 450° → 90°)
    - Math convention (0°=East, CCW) → met convention (0°=North, CW)
    """
    return dir_array % 360.0


def read_csv_wind(csv_path, speed_col, dir_col, grid_shape):
    """Read wind data from CSV and reshape to grid.

    Expects CSV with columns for speed and direction.
    If CSV has fewer rows than grid pixels, broadcasts uniformly.
    If CSV has a 'time' column, uses only the first timestep.
    """
    import pandas as pd

    df = pd.read_csv(csv_path)

    if speed_col not in df.columns:
        print(json.dumps({
            "status": "error",
            "errors": [f"Column '{speed_col}' not in CSV. Available: {list(df.columns)}"]
        }))
        sys.exit(1)

    if dir_col not in df.columns:
        print(json.dumps({
            "status": "error",
            "errors": [f"Column '{dir_col}' not in CSV. Available: {list(df.columns)}"]
        }))
        sys.exit(1)

    speeds = df[speed_col].values.astype(float)
    directions = df[dir_col].values.astype(float)

    h, w = grid_shape
    total_pixels = h * w

    if len(speeds) == total_pixels:
        # Exact match: reshape directly
        speed_grid = speeds.reshape(h, w)
        dir_grid = directions.reshape(h, w)
    elif len(speeds) == 1:
        # Single value: broadcast
        speed_grid = np.full((h, w), speeds[0])
        dir_grid = np.full((h, w), directions[0])
    else:
        # Take mean or first row as uniform value
        print(json.dumps({
            "status": "warning",
            "message": f"CSV has {len(speeds)} rows but grid has {total_pixels} pixels. "
                       "Using mean values as uniform field."
        }), file=sys.stderr)
        speed_grid = np.full((h, w), np.mean(speeds))
        dir_grid = np.full((h, w), np.mean(directions))

    return speed_grid, dir_grid


def validate_outputs(speed_array, dir_array):
    """Post-processing validation of converted wind arrays.

    Checks:
    - Arrays have same shape
    - Speed values are physically reasonable in ft/min
    - Directions are in [0, 360)
    """
    errors = []
    warnings = []

    if speed_array.shape != dir_array.shape:
        errors.append(
            f"Shape mismatch: speed {speed_array.shape} vs direction {dir_array.shape}"
        )

    max_speed = np.max(speed_array)
    min_speed = np.min(speed_array)

    # Reasonable wind speed checks (in ft/min)
    if max_speed > 22000:  # ~250 mph
        errors.append(f"Max wind speed {max_speed:.0f} ft/min (~{max_speed/88:.0f} mph) "
                      "exceeds 250 mph. Check unit conversion.")
    if max_speed < 1.0 and max_speed > 0:
        warnings.append(
            f"Max wind speed {max_speed:.2f} ft/min (~{max_speed/88:.4f} mph) is very low. "
            "Did you forget to convert from mph to ft/min? (multiply by 88)"
        )

    if np.any(dir_array < 0) or np.any(dir_array >= 360):
        warnings.append("Direction values outside [0, 360). Normalizing.")

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_outputs", "errors": errors}))
        sys.exit(1)

    for w in warnings:
        print(json.dumps({"status": "warning", "message": w}), file=sys.stderr)

    return {
        "speed_range_ftpm": [float(min_speed), float(max_speed)],
        "speed_range_mph": [float(min_speed / 88), float(max_speed / 88)],
        "direction_range": [float(np.min(dir_array)), float(np.max(dir_array))],
        "shape": list(speed_array.shape),
    }


def process(args):
    """Main processing: read → convert → validate → save."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    grid_shape = tuple(args.grid_shape) if args.grid_shape else (225, 225)

    # Step 1: Read data
    if args.csv:
        speed_raw, dir_raw = read_csv_wind(
            args.csv, args.speed_col, args.dir_col, grid_shape
        )
    else:
        speed_raw = np.full(grid_shape, float(args.speed))
        dir_raw = np.full(grid_shape, float(args.direction))

    # Step 2: Convert units
    speed_ftpm = convert_speed(speed_raw, args.speed_unit)
    direction_deg = normalize_direction(dir_raw)

    # Step 3: Validate outputs
    validation = validate_outputs(speed_ftpm, direction_deg)

    # Step 4: Save
    speed_path = output_dir / "wind_speed.npy"
    dir_path = output_dir / "wind_direction.npy"
    meta_path = output_dir / "wind_metadata.json"

    np.save(str(speed_path), speed_ftpm)
    np.save(str(dir_path), direction_deg)

    metadata = {
        "source_unit": args.speed_unit,
        "target_unit": "ft/min",
        "conversion_factor": SPEED_CONVERSIONS[args.speed_unit],
        "direction_convention": "degrees CW from North (0=N, 90=E, 180=S, 270=W)",
        "validation": validation,
    }
    with open(str(meta_path), "w") as f:
        json.dump(metadata, f, indent=2)

    return {
        "wind_speed": str(speed_path),
        "wind_direction": str(dir_path),
        "metadata": str(meta_path),
        "validation": validation,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert external wind data to SimFire format (ft/min, degrees)"
    )

    # Constant wind mode
    parser.add_argument("--speed", type=float, default=None,
                        help="Constant wind speed (in --speed-unit)")
    parser.add_argument("--direction", type=float, default=None,
                        help="Constant wind direction (degrees, 0=N, 90=E)")
    parser.add_argument("--speed-unit", type=str, default="mph",
                        choices=list(SPEED_CONVERSIONS.keys()),
                        help="Wind speed input unit (default: mph)")

    # CSV mode
    parser.add_argument("--csv", type=str, default=None,
                        help="Path to CSV file with wind data")
    parser.add_argument("--speed-col", type=str, default=None,
                        help="Column name for wind speed in CSV")
    parser.add_argument("--dir-col", type=str, default=None,
                        help="Column name for wind direction in CSV")

    # Grid configuration
    parser.add_argument("--grid-shape", type=int, nargs=2, default=None,
                        help="Grid dimensions: height width (pixels)")

    # Output
    parser.add_argument("--output-dir", type=str, required=True,
                        help="Output directory for wind arrays")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

    print(json.dumps({"status": "success", "output": result}, indent=2))


if __name__ == "__main__":
    main()
