#!/usr/bin/env python3
"""
parse_elmfire_output.py — Parse ELMFIRE outputs to CSV and compute fire behavior metrics.

Reads:
  - time_of_arrival GeoTIFFs → fire perimeter progression
  - spread_rate GeoTIFFs → rate of spread statistics
  - flin GeoTIFFs → fireline intensity statistics
  - flame_length GeoTIFFs → flame length statistics
  - fire_size_stats CSV → cumulative burned area

Outputs:
  - summary.csv: time series of fire area, max ROS, max FLIN, max FL
  - metrics.json: aggregate fire behavior metrics
  - Optionally: comparison with observed fire perimeters

Unit notes (ELMFIRE native output units):
  - Rate of spread: ft/min (×0.00508 for m/s, ×0.01829 for km/hr)
  - Flame length: feet (×0.3048 for meters)
  - Fireline intensity: kW/m (×0.289 for BTU/ft/s)
  - Area: acres in fire_size_stats (×0.4047 for hectares)
  - Time of arrival: seconds from simulation start

Usage:
    python parse_elmfire_output.py \\
        --outputs_dir ./outputs \\
        --out results.csv

    # With observed data comparison
    python parse_elmfire_output.py \\
        --outputs_dir ./outputs \\
        --observed_perimeter perimeter.shp \\
        --out results.csv
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

try:
    from osgeo import gdal, ogr
    gdal.UseExceptions()
    HAS_GDAL = True
except ImportError:
    HAS_GDAL = False


# Unit conversion constants
FT_MIN_TO_M_S = 0.00508
FT_MIN_TO_KM_HR = 0.01829
FT_TO_M = 0.3048
ACRES_TO_HA = 0.4047
KW_M_TO_BTU_FT_S = 0.289


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isdir(args.outputs_dir):
        errors.append(f"Outputs directory not found: {args.outputs_dir}")

    if args.observed_perimeter and not os.path.isfile(args.observed_perimeter):
        errors.append(f"Observed perimeter not found: {args.observed_perimeter}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def parse_fire_size_stats(outputs_dir):
    """Parse fire_size_stats CSV files."""
    csv_files = sorted(glob.glob(os.path.join(outputs_dir, "fire_size_stats*.csv")))
    if not csv_files:
        # Also check for any CSV
        csv_files = sorted(glob.glob(os.path.join(outputs_dir, "*.csv")))

    if not csv_files:
        return None

    records = []
    for csv_file in csv_files:
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                record = {}
                for key, val in row.items():
                    key = key.strip()
                    try:
                        record[key] = float(val)
                    except (ValueError, TypeError):
                        record[key] = val
                records.append(record)

    return records


def parse_raster_stats(filepath):
    """Get basic statistics from a GeoTIFF raster."""
    if not HAS_GDAL:
        return None

    ds = gdal.Open(filepath)
    if ds is None:
        return None

    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    data = band.ReadAsArray().astype(float)

    if nodata is not None:
        mask = data != nodata
        if not mask.any():
            return {"min": 0, "max": 0, "mean": 0, "std": 0, "count": 0}
        valid = data[mask]
    else:
        valid = data[data > -9998]

    if len(valid) == 0:
        return {"min": 0, "max": 0, "mean": 0, "std": 0, "count": 0}

    stats = {
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "mean": float(np.mean(valid)),
        "std": float(np.std(valid)),
        "count": int(len(valid)),
    }
    ds = None
    return stats


def collect_output_rasters(outputs_dir):
    """Collect and categorize all output rasters."""
    categories = {
        "time_of_arrival": [],
        "spread_rate": [],
        "flin": [],
        "flame_length": [],
        "crown_fire": [],
        "velocity": [],
    }

    for pattern_name, file_patterns in [
        ("time_of_arrival", ["time_of_arrival*.tif", "time_of_arrival*.bil"]),
        ("spread_rate", ["spread_rate*.tif", "spread_rate*.bil"]),
        ("flin", ["flin*.tif", "flin*.bil"]),
        ("flame_length", ["flame_length*.tif", "flame_length*.bil"]),
        ("crown_fire", ["crown_fire*.tif", "crown_fire*.bil"]),
        ("velocity", ["velocity*.tif", "velocity*.bil"]),
    ]:
        for pat in file_patterns:
            files = sorted(glob.glob(os.path.join(outputs_dir, pat)))
            categories[pattern_name].extend(files)

    return categories


def compute_fire_metrics(fire_stats, raster_categories):
    """Compute aggregate fire behavior metrics."""
    metrics = {
        "total_area_acres": 0,
        "total_area_ha": 0,
        "max_spread_rate_ft_min": 0,
        "max_spread_rate_m_s": 0,
        "max_fireline_intensity_kw_m": 0,
        "max_flame_length_ft": 0,
        "max_flame_length_m": 0,
        "simulation_duration_hr": 0,
        "output_file_count": 0,
    }

    # From fire size stats CSV
    if fire_stats:
        areas = []
        for row in fire_stats:
            for key in row:
                if "Area(acres)" in key or "area" in key.lower():
                    areas.append(row[key])
                    break
        if areas:
            metrics["total_area_acres"] = max(areas)
            metrics["total_area_ha"] = max(areas) * ACRES_TO_HA

        times = []
        for row in fire_stats:
            for key in row:
                if "Time" in key and "sec" in key:
                    times.append(row[key])
                    break
        if times:
            metrics["simulation_duration_hr"] = max(times) / 3600.0

    # From raster statistics
    for category, files in raster_categories.items():
        metrics["output_file_count"] += len(files)
        for f in files:
            stats = parse_raster_stats(f)
            if stats is None:
                continue

            if category == "spread_rate":
                metrics["max_spread_rate_ft_min"] = max(
                    metrics["max_spread_rate_ft_min"], stats["max"])
                metrics["max_spread_rate_m_s"] = (
                    metrics["max_spread_rate_ft_min"] * FT_MIN_TO_M_S)

            elif category == "flin":
                metrics["max_fireline_intensity_kw_m"] = max(
                    metrics["max_fireline_intensity_kw_m"], stats["max"])

            elif category == "flame_length":
                metrics["max_flame_length_ft"] = max(
                    metrics["max_flame_length_ft"], stats["max"])
                metrics["max_flame_length_m"] = (
                    metrics["max_flame_length_ft"] * FT_TO_M)

    return metrics


def write_summary_csv(fire_stats, output_path):
    """Write summary CSV with fire progression data."""
    if not fire_stats:
        print("  No fire size stats to write")
        return

    with open(output_path, "w", newline="") as f:
        if fire_stats:
            writer = csv.DictWriter(f, fieldnames=fire_stats[0].keys())
            writer.writeheader()
            writer.writerows(fire_stats)

    print(f"  Summary CSV written to: {output_path}")


def validate_outputs(metrics, output_path):
    """Validate parsed outputs are sensible."""
    results = {"status": "ok", "warnings": []}

    if metrics["total_area_acres"] == 0:
        results["warnings"].append("Total burned area is 0 — fire may not have spread")

    if metrics["max_spread_rate_ft_min"] > 1000:
        results["warnings"].append(
            f"Max spread rate {metrics['max_spread_rate_ft_min']:.0f} ft/min "
            f"is very high — verify inputs")

    if metrics["max_flame_length_ft"] > 200:
        results["warnings"].append(
            f"Max flame length {metrics['max_flame_length_ft']:.0f} ft "
            f"is extremely high — verify fuel moisture")

    if not os.path.isfile(output_path):
        results["status"] = "error"
        results["warnings"].append(f"Output file not created: {output_path}")

    print(json.dumps(results, indent=2))
    return results


def process(args):
    """Main pipeline: validate → process → validate."""
    validate_inputs(args)

    print("Parsing ELMFIRE outputs...")

    # Parse fire size statistics
    fire_stats = parse_fire_size_stats(args.outputs_dir)
    if fire_stats:
        print(f"  Found {len(fire_stats)} fire size stat records")
    else:
        print("  No fire_size_stats CSV found")

    # Collect raster outputs
    raster_categories = collect_output_rasters(args.outputs_dir)
    for cat, files in raster_categories.items():
        if files:
            print(f"  {cat}: {len(files)} files")

    # Compute metrics
    metrics = compute_fire_metrics(fire_stats, raster_categories)
    print(f"\nFire behavior metrics:")
    print(f"  Total area: {metrics['total_area_acres']:.1f} acres "
          f"({metrics['total_area_ha']:.1f} ha)")
    print(f"  Max spread rate: {metrics['max_spread_rate_ft_min']:.1f} ft/min "
          f"({metrics['max_spread_rate_m_s']:.3f} m/s)")
    print(f"  Max fireline intensity: {metrics['max_fireline_intensity_kw_m']:.0f} kW/m")
    print(f"  Max flame length: {metrics['max_flame_length_ft']:.1f} ft "
          f"({metrics['max_flame_length_m']:.1f} m)")
    print(f"  Duration: {metrics['simulation_duration_hr']:.1f} hr")

    # Write outputs
    write_summary_csv(fire_stats, args.out)

    # Write metrics JSON
    metrics_path = args.out.replace(".csv", "_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"  Metrics JSON written to: {metrics_path}")

    # Validate
    print("\nValidating parsed outputs...")
    validate_outputs(metrics, args.out)

    return metrics


def main():
    parser = argparse.ArgumentParser(
        description="Parse ELMFIRE outputs to CSV and compute metrics"
    )
    parser.add_argument("--outputs_dir", required=True,
                        help="ELMFIRE outputs directory")
    parser.add_argument("--observed_perimeter", default=None,
                        help="Observed fire perimeter shapefile (optional)")
    parser.add_argument("--out", default="results.csv",
                        help="Output CSV path")

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
