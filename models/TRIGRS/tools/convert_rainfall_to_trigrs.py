#!/usr/bin/env python3
"""
convert_rainfall_to_trigrs.py
=============================
Convert rainfall time-series data (CSV, NetCDF, or gauge records) into
TRIGRS-format rainfall intensity grids (.asc) and corresponding tr_in.txt
parameters (cri, capt arrays).

CRITICAL UNIT CONVERSION:
    TRIGRS expects rainfall intensity in **m/s**.
    - From mm/hr:  divide by 3.6e6   (1 mm/hr = 2.778e-7 m/s)
    - From mm/day: divide by 8.64e7  (1 mm/day = 1.157e-8 m/s)
    - From in/hr:  multiply by 7.056e-6

Usage:
    python convert_rainfall_to_trigrs.py \\
        --input rainfall.csv \\
        --input_unit mm/hr \\
        --dem dem.asc \\
        --output_dir data/tutorial/ \\
        --event_start "2020-06-15 00:00" \\
        --event_end "2020-06-17 12:00"

Output:
    - ri1.asc, ri2.asc, ... (one per rainfall period)
    - rainfall_params.txt   (cri and capt values for tr_in.txt)
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Unit conversion factors TO m/s
# ---------------------------------------------------------------------------
UNIT_FACTORS = {
    "m/s": 1.0,
    "mm/hr": 1.0 / 3.6e6,       # 1 mm/hr = 2.778e-7 m/s
    "mm/h": 1.0 / 3.6e6,
    "mm/day": 1.0 / 8.64e7,     # 1 mm/day = 1.157e-8 m/s
    "mm/d": 1.0 / 8.64e7,
    "cm/hr": 1.0 / 3.6e5,
    "cm/h": 1.0 / 3.6e5,
    "in/hr": 7.056e-6,
    "m/hr": 1.0 / 3600.0,
    "m/h": 1.0 / 3600.0,
}

# Physical limits for validation (m/s)
MAX_RAINFALL_MS = 1.0e-3   # ~3600 mm/hr, extreme upper bound
MIN_RAINFALL_MS = 0.0
TYPICAL_HEAVY_MS = 2.0e-5  # ~72 mm/hr
TYPICAL_EXTREME_MS = 1.0e-4  # ~360 mm/hr


def validate_inputs(input_path: str, input_unit: str, dem_path: str) -> dict:
    """
    Validate all inputs before processing.

    Returns:
        dict with validated parameters and metadata

    Raises:
        ValueError: if any input is invalid
    """
    errors = []

    # Check input file exists
    if not os.path.isfile(input_path):
        errors.append(f"Input file not found: {input_path}")

    # Check unit is recognized
    if input_unit not in UNIT_FACTORS:
        errors.append(
            f"Unknown input unit '{input_unit}'. "
            f"Valid units: {list(UNIT_FACTORS.keys())}"
        )

    # Check DEM file exists and read header
    dem_meta = {}
    if os.path.isfile(dem_path):
        dem_meta = read_asc_header(dem_path)
    else:
        errors.append(f"DEM file not found: {dem_path}")

    if errors:
        raise ValueError("Input validation failed:\n  " + "\n  ".join(errors))

    return {"input_path": input_path, "input_unit": input_unit,
            "dem_meta": dem_meta, "conversion_factor": UNIT_FACTORS[input_unit]}


def read_asc_header(filepath: str) -> dict:
    """Read ESRI ASCII grid header (6 lines)."""
    meta = {}
    with open(filepath, "r") as f:
        for _ in range(6):
            line = f.readline().strip().split()
            if len(line) >= 2:
                key = line[0].lower()
                try:
                    val = int(line[1])
                except ValueError:
                    val = float(line[1])
                meta[key] = val
    return meta


def read_rainfall_csv(filepath: str) -> list:
    """
    Read rainfall CSV with columns: datetime, intensity.
    Returns list of (datetime, value) tuples.
    """
    records = []
    with open(filepath, "r") as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header
        for row in reader:
            if len(row) < 2:
                continue
            try:
                dt = datetime.strptime(row[0].strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                try:
                    dt = datetime.strptime(row[0].strip(), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dt = datetime.strptime(row[0].strip(), "%Y/%m/%d %H:%M")
            val = float(row[1].strip())
            records.append((dt, val))
    return records


def aggregate_to_periods(records: list, period_hours: float = 1.0) -> list:
    """
    Aggregate rainfall records into constant-intensity periods.

    Returns:
        list of (start_seconds, end_seconds, intensity_m_s)
    """
    if not records:
        return []

    t0 = records[0][0]
    periods = []
    current_start = 0.0
    current_sum = 0.0
    current_count = 0
    period_sec = period_hours * 3600.0

    for dt, val in records:
        elapsed = (dt - t0).total_seconds()
        period_idx = int(elapsed / period_sec)
        expected_start = period_idx * period_sec

        if expected_start != current_start and current_count > 0:
            avg_intensity = current_sum / current_count
            periods.append((current_start, expected_start, avg_intensity))
            current_start = expected_start
            current_sum = val
            current_count = 1
        else:
            current_sum += val
            current_count += 1

    # Final period
    if current_count > 0:
        end = current_start + period_sec
        avg_intensity = current_sum / current_count
        periods.append((current_start, end, avg_intensity))

    return periods


def convert_intensity(value: float, factor: float) -> float:
    """Convert a single intensity value to m/s."""
    return value * factor


def write_rainfall_grid(filepath: str, dem_meta: dict,
                        intensity_ms: float, nodata: int = -9999) -> None:
    """
    Write a uniform rainfall intensity grid matching the DEM dimensions.

    For spatially variable rainfall, override values per cell.
    """
    ncols = dem_meta.get("ncols", 10)
    nrows = dem_meta.get("nrows", 10)
    xll = dem_meta.get("xllcorner", 0)
    yll = dem_meta.get("yllcorner", 0)
    cellsize = dem_meta.get("cellsize", 10)
    nodata_val = dem_meta.get("nodata_value", nodata)

    with open(filepath, "w") as f:
        f.write(f"ncols         {ncols}\n")
        f.write(f"nrows         {nrows}\n")
        f.write(f"xllcorner     {xll}\n")
        f.write(f"yllcorner     {yll}\n")
        f.write(f"cellsize      {cellsize}\n")
        f.write(f"NODATA_value  {nodata_val}\n")
        for _ in range(nrows):
            row_vals = " ".join([f"{intensity_ms:.6e}"] * ncols)
            f.write(row_vals + "\n")


def validate_outputs(periods: list, output_dir: str) -> list:
    """
    Validate converted rainfall parameters.

    Returns:
        list of warning strings (empty = OK)
    """
    warnings = []

    for i, (start, end, intensity) in enumerate(periods):
        # Check physical bounds
        if intensity < MIN_RAINFALL_MS:
            warnings.append(
                f"Period {i+1}: negative intensity {intensity:.2e} m/s"
            )
        if intensity > MAX_RAINFALL_MS:
            warnings.append(
                f"Period {i+1}: intensity {intensity:.2e} m/s exceeds "
                f"physical maximum ({MAX_RAINFALL_MS:.2e} m/s). "
                f"CHECK UNIT CONVERSION!"
            )
        if intensity > TYPICAL_EXTREME_MS:
            warnings.append(
                f"Period {i+1}: intensity {intensity:.2e} m/s is extreme. "
                f"Verify units are correct (expected m/s)."
            )

        # Check time ordering
        if end <= start:
            warnings.append(
                f"Period {i+1}: end time ({end}) <= start time ({start})"
            )

        # Check grid file exists
        grid_file = os.path.join(output_dir, f"ri{i+1}.asc")
        if not os.path.isfile(grid_file):
            warnings.append(f"Missing output grid: {grid_file}")

    return warnings


def write_params_file(filepath: str, periods: list) -> None:
    """Write cri and capt arrays for inclusion in tr_in.txt."""
    cri_values = [f"{p[2]:.6e}" for p in periods]
    capt_values = [f"{p[0]:.0f}"]
    for p in periods:
        capt_values.append(f"{p[1]:.0f}")

    with open(filepath, "w") as f:
        f.write("# Rainfall parameters for tr_in.txt\n")
        f.write("# Generated by convert_rainfall_to_trigrs.py\n")
        f.write(f"# {len(periods)} rainfall periods\n\n")
        f.write(f"nper = {len(periods)}\n\n")
        f.write("cri(1), cri(2), ..., cri(nper)  [m/s]\n")
        f.write(", ".join(cri_values) + "\n\n")
        f.write("capt(1), capt(2), ..., capt(n+1)  [seconds]\n")
        f.write(", ".join(capt_values) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Convert rainfall data to TRIGRS format"
    )
    parser.add_argument("--input", required=True, help="Input CSV file")
    parser.add_argument("--input_unit", required=True,
                        choices=list(UNIT_FACTORS.keys()),
                        help="Unit of input rainfall intensity")
    parser.add_argument("--dem", required=True, help="DEM ASCII grid file")
    parser.add_argument("--output_dir", required=True,
                        help="Output directory for grid files")
    parser.add_argument("--period_hours", type=float, default=1.0,
                        help="Aggregation period in hours (default: 1)")
    parser.add_argument("--event_start", default=None,
                        help="Event start datetime (YYYY-MM-DD HH:MM)")
    parser.add_argument("--event_end", default=None,
                        help="Event end datetime (YYYY-MM-DD HH:MM)")

    args = parser.parse_args()

    # Step 1: Validate inputs
    print("[1/4] Validating inputs...")
    params = validate_inputs(args.input, args.input_unit, args.dem)
    print(f"  Unit conversion: {args.input_unit} -> m/s "
          f"(factor = {params['conversion_factor']:.6e})")

    # Step 2: Read and convert rainfall data
    print("[2/4] Reading rainfall data...")
    records = read_rainfall_csv(args.input)
    print(f"  Read {len(records)} records")

    # Filter by event window if specified
    if args.event_start:
        t_start = datetime.strptime(args.event_start, "%Y-%m-%d %H:%M")
        records = [(dt, v) for dt, v in records if dt >= t_start]
    if args.event_end:
        t_end = datetime.strptime(args.event_end, "%Y-%m-%d %H:%M")
        records = [(dt, v) for dt, v in records if dt <= t_end]

    # Aggregate to periods
    periods_raw = aggregate_to_periods(records, args.period_hours)

    # Convert units
    factor = params["conversion_factor"]
    periods = [(s, e, convert_intensity(v, factor))
               for s, e, v in periods_raw]
    print(f"  Aggregated to {len(periods)} periods")

    # Step 3: Write output grids
    print("[3/4] Writing rainfall grids...")
    os.makedirs(args.output_dir, exist_ok=True)
    dem_meta = params["dem_meta"]

    for i, (start, end, intensity) in enumerate(periods):
        grid_path = os.path.join(args.output_dir, f"ri{i+1}.asc")
        write_rainfall_grid(grid_path, dem_meta, intensity)
        print(f"  ri{i+1}.asc: {intensity:.6e} m/s "
              f"({intensity * 3.6e6:.2f} mm/hr), "
              f"t=[{start:.0f}, {end:.0f}] s")

    # Write parameter summary
    params_path = os.path.join(args.output_dir, "rainfall_params.txt")
    write_params_file(params_path, periods)

    # Step 4: Validate outputs
    print("[4/4] Validating outputs...")
    warnings = validate_outputs(periods, args.output_dir)
    if warnings:
        print("  WARNINGS:")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("  All outputs validated OK")

    print(f"\nDone. {len(periods)} rainfall grids written to {args.output_dir}")
    print(f"Parameters saved to {params_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
