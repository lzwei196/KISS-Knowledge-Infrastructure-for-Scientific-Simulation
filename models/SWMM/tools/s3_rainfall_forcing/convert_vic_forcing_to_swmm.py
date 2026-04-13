#!/usr/bin/env python3
"""
Convert VIC forcing precipitation to SWMM rainfall timeseries.

Extracts precipitation from VIC forcing files and converts to SWMM-compatible
rainfall timeseries format. Handles the critical unit conversion:
  - VIC forcing: accumulated precipitation depth per timestep (mm/3hr)
  - SWMM timeseries: intensity (mm/hr)
  - Conversion: intensity = depth_per_3hr / 3.0

Can average multiple grid cells for a single SWMM rain gage, or produce
separate timeseries per cell.

Inputs:
  - VIC forcing directory (files named like: <prefix>_<lat>_<lon>)
  - Grid cell coordinates (lat,lon pairs)
  - Date range

Outputs:
  - SWMM timeseries file (.dat)
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np


def find_forcing_file(forcing_dir, lat, lon, prefix=None):
    """Find VIC forcing file for a given grid cell."""
    forcing_dir = Path(forcing_dir)
    patterns = [
        f"*_{lat:.4f}_{lon:.4f}",
        f"*_{lat:.2f}_{lon:.2f}",
        f"*{lat}*{lon}*",
    ]

    for pattern in patterns:
        matches = list(forcing_dir.glob(pattern))
        if matches:
            return matches[0]

    # Try listing all files and finding closest match
    best_match = None
    best_dist = float("inf")
    for f in forcing_dir.iterdir():
        if not f.is_file():
            continue
        parts = f.stem.split("_")
        try:
            # Try last two parts as lat/lon
            f_lat = float(parts[-2])
            f_lon = float(parts[-1])
            dist = abs(f_lat - lat) + abs(f_lon - lon)
            if dist < best_dist:
                best_dist = dist
                best_match = f
        except (ValueError, IndexError):
            continue

    if best_match and best_dist < 0.1:
        return best_match
    return None


def read_vic_precip(forcing_file, start_date, end_date, steps_per_day=8):
    """
    Read precipitation from VIC forcing file.

    VIC forcing columns (7 variables):
      0: PREC (mm/timestep)
      1: TMAX (C)
      2: TMIN (C)
      3: WIND (m/s)
      4: SHORTWAVE (W/m2)
      5: LONGWAVE (W/m2)
      6: PRESSURE (kPa)

    Returns list of (datetime, precip_mm_per_timestep).
    """
    records = []
    hours_per_step = 24.0 / steps_per_day

    try:
        data = np.loadtxt(forcing_file)
    except Exception as e:
        print(f"ERROR: Cannot read {forcing_file}: {e}", file=sys.stderr)
        return []

    current_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)

    for i, row in enumerate(data):
        if current_dt > end_dt:
            break
        precip = float(row[0]) if len(row) > 0 else 0.0
        records.append((current_dt, precip))
        current_dt += timedelta(hours=hours_per_step)

    return records


def main():
    parser = argparse.ArgumentParser(
        description="Convert VIC forcing precipitation to SWMM rainfall timeseries"
    )
    parser.add_argument("--vic_forcing_dir", required=True,
                        help="Directory containing VIC forcing files")
    parser.add_argument("--grid_cells", required=True,
                        help='Grid cell coordinates: "lat,lon;lat,lon;..."')
    parser.add_argument("--start_date", required=True,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", required=True,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", required=True,
                        help="Output SWMM timeseries file (.dat)")
    parser.add_argument("--series_name", default="VIC_Rain",
                        help="Timeseries name (default: VIC_Rain)")
    parser.add_argument("--steps_per_day", type=int, default=8,
                        help="VIC forcing steps per day (default: 8 = 3-hourly)")
    parser.add_argument("--method", default="average",
                        choices=["average", "nearest"],
                        help="How to combine multiple cells (default: average)")
    args = parser.parse_args()

    if not os.path.isdir(args.vic_forcing_dir):
        print(f"ERROR: Directory not found: {args.vic_forcing_dir}", file=sys.stderr)
        sys.exit(1)

    # Parse grid cells
    cells = []
    for cell_str in args.grid_cells.split(";"):
        parts = cell_str.strip().split(",")
        if len(parts) != 2:
            print(f"ERROR: Invalid grid cell format: '{cell_str}' (expected lat,lon)",
                  file=sys.stderr)
            sys.exit(1)
        cells.append((float(parts[0]), float(parts[1])))

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")

    print(f"Converting VIC forcing to SWMM rainfall timeseries")
    print(f"  Grid cells: {len(cells)}")
    print(f"  Period: {args.start_date} to {args.end_date}")
    print(f"  Steps/day: {args.steps_per_day}")

    hours_per_step = 24.0 / args.steps_per_day

    # Read precipitation from all cells
    all_precip = []
    for lat, lon in cells:
        ffile = find_forcing_file(args.vic_forcing_dir, lat, lon)
        if ffile is None:
            print(f"  WARNING: No forcing file found for ({lat}, {lon})", file=sys.stderr)
            continue
        print(f"  Reading {ffile.name}...")
        records = read_vic_precip(ffile, start_date, end_date, args.steps_per_day)
        if records:
            all_precip.append(records)
            print(f"    {len(records)} timesteps, max={max(r[1] for r in records):.2f} mm")

    if not all_precip:
        print("ERROR: No precipitation data found", file=sys.stderr)
        sys.exit(1)

    # Average across cells
    min_len = min(len(p) for p in all_precip)
    averaged = []
    for i in range(min_len):
        dt = all_precip[0][i][0]
        if args.method == "average":
            precip_depth = np.mean([p[i][1] for p in all_precip])
        else:
            precip_depth = all_precip[0][i][1]

        # CRITICAL CONVERSION: VIC depth per timestep -> mm/hr intensity
        # VIC gives mm/3hr (for 3-hourly), divide by hours_per_step
        intensity_mm_hr = precip_depth / hours_per_step

        averaged.append((dt, round(intensity_mm_hr, 4)))

    # Write SWMM timeseries
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_written = 0
    with open(output_path, "w") as f:
        f.write(f";;SWMM Rainfall Timeseries from VIC Forcing\n")
        f.write(f";;Period: {args.start_date} to {args.end_date}\n")
        f.write(f";;Grid cells: {len(cells)}, Method: {args.method}\n")
        f.write(f";;Unit: mm/hr (intensity)\n")
        f.write(";;\n")
        for dt, intensity in averaged:
            if intensity > 0.0001:
                date_str = dt.strftime("%m/%d/%Y")
                time_str = dt.strftime("%H:%M:%S")
                f.write(f"{args.series_name}\t{date_str}\t{time_str}\t{intensity:.4f}\n")
                n_written += 1

    intensities = [r[1] for r in averaged if r[1] > 0]
    print(f"\nTimeseries written: {output_path}")
    print(f"  {n_written} non-zero entries")
    if intensities:
        print(f"  Max intensity: {max(intensities):.2f} mm/hr")
        print(f"  Mean non-zero: {np.mean(intensities):.2f} mm/hr")


if __name__ == "__main__":
    main()
