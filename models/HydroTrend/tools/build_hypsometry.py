#!/usr/bin/env python3
"""
build_hypsometry.py

Generates a HydroTrend hypsometry file (PREFIX0.HYPS) from DEM data or
manual elevation-area pairs.

Input sources:
  - GeoTIFF DEM (requires rasterio)
  - CSV with elevation and area columns
  - Manual specification of min/max elevation, total area, and bin count

Output: HydroTrend HYPS file format:
  [5 header lines]
  [number of bins]
  [elevation(m)  cumulative_area(km²)]  per line

CRITICAL NOTES:
  - Elevation must be in meters
  - Area must be in km² (model uses km² internally for sediment formulas)
  - First bin area should be 0 (represents lowest point, no area below it)
  - Both columns must be monotonically increasing
  - Basin relief (max_alt - min_alt) drives sediment transport

Usage:
    python build_hypsometry.py \\
        --dem basin_dem.tif \\
        --output HYDRO0.HYPS \\
        --bin-size 50

    python build_hypsometry.py \\
        --csv elevation_area.csv \\
        --elev-col elevation_m \\
        --area-col area_km2 \\
        --output HYDRO0.HYPS

    python build_hypsometry.py \\
        --manual \\
        --min-elev 0 --max-elev 2250 \\
        --total-area 9440 \\
        --n-bins 46 \\
        --output HYDRO0.HYPS
"""

import argparse
import csv
import json
import math
import os
import sys


# --------------------------------------------------------------------------- #
#  Validation
# --------------------------------------------------------------------------- #
def validate_inputs(args):
    """Validate command-line inputs."""
    errors = []

    mode_count = sum([
        args.dem is not None,
        args.csv is not None,
        args.manual,
    ])
    if mode_count != 1:
        errors.append("Specify exactly one of --dem, --csv, or --manual")

    if args.dem and not os.path.isfile(args.dem):
        errors.append(f"DEM file not found: {args.dem}")

    if args.csv and not os.path.isfile(args.csv):
        errors.append(f"CSV file not found: {args.csv}")

    if args.manual:
        if args.min_elev is None or args.max_elev is None:
            errors.append("--manual requires --min-elev and --max-elev")
        if args.total_area is None:
            errors.append("--manual requires --total-area")
        if args.min_elev is not None and args.max_elev is not None:
            if args.min_elev >= args.max_elev:
                errors.append("--min-elev must be less than --max-elev")
        if args.total_area is not None and args.total_area <= 0:
            errors.append("--total-area must be positive")

    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def validate_hypsometry(elevations, areas):
    """Validate hypsometry data for HydroTrend requirements."""
    warnings = []

    if len(elevations) < 3:
        warnings.append("Very few hypsometry bins (<3) — model may be unstable")

    if len(elevations) != len(areas):
        warnings.append(
            f"Elevation count ({len(elevations)}) != area count ({len(areas)})"
        )

    # Check monotonicity
    for i in range(1, len(elevations)):
        if elevations[i] <= elevations[i - 1]:
            warnings.append(
                f"Elevation not monotonically increasing at bin {i}: "
                f"{elevations[i-1]} >= {elevations[i]}"
            )
            break

    for i in range(1, len(areas)):
        if areas[i] < areas[i - 1]:
            warnings.append(
                f"Area not monotonically increasing at bin {i}: "
                f"{areas[i-1]} > {areas[i]}"
            )
            break

    # First bin area should be 0
    if areas and areas[0] != 0:
        warnings.append(
            f"First bin area = {areas[0]} (expected 0 for basin bottom)"
        )

    # Relief check
    if elevations:
        relief = elevations[-1] - elevations[0]
        if relief < 10:
            warnings.append(f"Basin relief = {relief}m — extremely low")
        if relief > 9000:
            warnings.append(f"Basin relief = {relief}m — exceeds Everest")

    # Total area check
    if areas:
        total = areas[-1]
        if total < 1:
            warnings.append(f"Total area = {total} km² — very small basin")
        if total > 1e7:
            warnings.append(
                f"Total area = {total} km² — larger than Amazon basin"
            )

    return warnings


# --------------------------------------------------------------------------- #
#  Processing
# --------------------------------------------------------------------------- #
def build_from_dem(dem_path, bin_size=50):
    """
    Build hypsometry from a GeoTIFF DEM.

    Requires rasterio. Computes cumulative area below each elevation band.
    """
    try:
        import rasterio
        import numpy as np
    except ImportError:
        raise ImportError(
            "rasterio and numpy required for DEM processing. "
            "Install with: pip install rasterio numpy"
        )

    with rasterio.open(dem_path) as src:
        dem = src.read(1)
        nodata = src.nodata
        transform = src.transform

        # Calculate pixel area in km²
        pixel_width = abs(transform[0])
        pixel_height = abs(transform[4])
        # Approximate for geographic coords (degrees)
        if pixel_width < 1:  # likely in degrees
            lat_center = (src.bounds.top + src.bounds.bottom) / 2
            km_per_deg_lon = 111.32 * math.cos(math.radians(lat_center))
            km_per_deg_lat = 110.574
            pixel_area_km2 = (pixel_width * km_per_deg_lon *
                              pixel_height * km_per_deg_lat)
        else:
            # Projected coordinates (meters)
            pixel_area_km2 = (pixel_width * pixel_height) / 1e6

        # Mask nodata
        if nodata is not None:
            valid = dem[dem != nodata]
        else:
            valid = dem[~np.isnan(dem)]

        min_elev = float(np.floor(valid.min()))
        max_elev = float(np.ceil(valid.max()))

        # Build bins
        elevations = []
        areas = []
        elev = min_elev
        while elev <= max_elev:
            count = int(np.sum(valid <= elev))
            cumulative_area = count * pixel_area_km2
            elevations.append(elev)
            areas.append(round(cumulative_area, 2))
            elev += bin_size

        # Ensure first bin area is 0
        if areas and areas[0] > 0:
            elevations.insert(0, min_elev)
            areas.insert(0, 0)

    return elevations, areas


def build_from_csv(csv_path, elev_col, area_col):
    """Read elevation-area pairs from CSV."""
    elevations = []
    areas = []

    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            elevations.append(float(row[elev_col]))
            areas.append(float(row[area_col]))

    return elevations, areas


def build_manual(min_elev, max_elev, total_area, n_bins):
    """
    Generate synthetic hypsometry using a power-law curve.

    Uses the empirical observation that many basins have a roughly
    sigmoidal or concave-up hypsometric curve.
    """
    elevations = []
    areas = []
    bin_size = (max_elev - min_elev) / (n_bins - 1)

    for i in range(n_bins):
        elev = min_elev + i * bin_size
        # Normalized position [0, 1]
        x = i / (n_bins - 1)
        # Power-law cumulative area (concave-up)
        area = total_area * (x ** 1.5)
        elevations.append(round(elev, 1))
        areas.append(round(area, 2))

    # Ensure first area is 0
    areas[0] = 0

    return elevations, areas


def write_hyps_file(output_path, elevations, areas, prefix="HYDRO"):
    """Write HydroTrend HYPS file."""
    with open(output_path, "w") as f:
        f.write("-------------------------------------------------\n")
        f.write(f"HYDROTREND hypsometry input file ({prefix}).\n")
        f.write("First line: number of hypsometric bins\n")
        f.write("Other lines: altitude (m) and area (km^2) data\n")
        f.write("-------------------------------------------------\n")
        f.write(f"{len(elevations)}\n")
        for elev, area in zip(elevations, areas):
            f.write(f"{elev}\t{area}\n")


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="Build HydroTrend hypsometry file"
    )
    parser.add_argument("--dem", default=None, help="Input DEM GeoTIFF")
    parser.add_argument("--csv", default=None, help="Input CSV file")
    parser.add_argument("--manual", action="store_true",
                        help="Generate synthetic hypsometry")
    parser.add_argument("--output", required=True, help="Output HYPS file")
    parser.add_argument("--bin-size", type=float, default=50,
                        help="Elevation bin size in meters (DEM mode)")
    parser.add_argument("--elev-col", default="elevation_m",
                        help="Elevation column name (CSV mode)")
    parser.add_argument("--area-col", default="area_km2",
                        help="Area column name (CSV mode)")
    parser.add_argument("--min-elev", type=float, default=None,
                        help="Minimum elevation (manual mode)")
    parser.add_argument("--max-elev", type=float, default=None,
                        help="Maximum elevation (manual mode)")
    parser.add_argument("--total-area", type=float, default=None,
                        help="Total basin area in km² (manual mode)")
    parser.add_argument("--n-bins", type=int, default=46,
                        help="Number of bins (manual mode)")
    parser.add_argument("--prefix", default="HYDRO",
                        help="File prefix for header")
    args = parser.parse_args()

    # Step 1: Validate inputs
    check = validate_inputs(args)
    if check["status"] == "error":
        print(json.dumps(check, indent=2))
        sys.exit(1)

    # Step 2: Process
    try:
        if args.dem:
            elevations, areas = build_from_dem(args.dem, args.bin_size)
        elif args.csv:
            elevations, areas = build_from_csv(
                args.csv, args.elev_col, args.area_col
            )
        else:
            elevations, areas = build_manual(
                args.min_elev, args.max_elev, args.total_area, args.n_bins
            )
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, indent=2))
        sys.exit(1)

    # Step 3: Validate outputs
    warnings = validate_hypsometry(elevations, areas)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    # Step 4: Write output
    write_hyps_file(args.output, elevations, areas, args.prefix)

    relief = elevations[-1] - elevations[0] if elevations else 0
    result = {
        "status": "success",
        "output_file": args.output,
        "n_bins": len(elevations),
        "elevation_range_m": [elevations[0], elevations[-1]],
        "relief_m": relief,
        "total_area_km2": areas[-1] if areas else 0,
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
