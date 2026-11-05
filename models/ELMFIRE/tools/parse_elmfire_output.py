#!/usr/bin/env python3
"""
parse_elmfire_output.py — Parse ELMFIRE outputs to CSV and compute fire behavior metrics.

Reads:
  - time_of_arrival GeoTIFFs → fire perimeter progression
  - vs_* (ELMFIRE's spread-rate output; older name spread_rate*) → rate of spread statistics
  - flin GeoTIFFs → fireline intensity statistics
  - flame_length GeoTIFFs → flame length statistics
  - fire_size_stats CSV → cumulative burned area (if missing - ELMFIRE's own scripts
    delete it - the area is counted from the time_of_arrival raster: cells with a
    time of arrival >= 0 times the cell area)

Outputs:
  - summary.csv: time series of fire area, max ROS, max FLIN, max FL
  - metrics.json: aggregate fire behavior metrics
  - Optionally: comparison with observed fire perimeters

Metrics with no valid source are null in the metrics JSON (before this fix they were
reported as 0, which reads as a real value).

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
    # Only ELMFIRE's own fire_size_stats file (another CSV in the folder, e.g. this
    # tool's results.csv, is not fire statistics)
    csv_files = sorted(glob.glob(os.path.join(outputs_dir, "fire_size_stats*.csv")))

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
        ("spread_rate", ["vs_*.tif", "vs_*.bil", "spread_rate*.tif", "spread_rate*.bil"]),
        ("flin", ["flin*.tif", "flin*.bil"]),
        ("flame_length", ["flame_length*.tif", "flame_length*.bil"]),
        ("crown_fire", ["crown_fire*.tif", "crown_fire*.bil"]),
        ("velocity", ["velocity*.tif", "velocity*.bil"]),
    ]:
        for pat in file_patterns:
            files = sorted(glob.glob(os.path.join(outputs_dir, pat)))
            categories[pattern_name].extend(files)

    return categories


def burned_area_from_toa(toa_files, notes, read_errors=None):
    """Burned area (acres) counted from the time_of_arrival raster: cells with a time
    of arrival >= 0 times the cell area. Used only when fire_size_stats gives no area
    (ELMFIRE's own scripts delete that CSV). Only one fire case and a north-up grid in
    metres are supported; otherwise None with a note. This is a raster cell count,
    close to but not the same number as ELMFIRE's own fire area statistic."""
    if read_errors is None:
        read_errors = []
    if not HAS_GDAL or not toa_files:
        notes.append("no time_of_arrival raster to count burned cells from")
        return None
    # ELMFIRE names it time_of_arrival_<case>_<time>.(bil|tif)
    parsed = []
    for f in toa_files:
        m = re.match(r"time_of_arrival_(\d+)_(\d+)\.", os.path.basename(f))
        if m:
            parsed.append((int(m.group(1)), int(m.group(2)), f))
    cases = {c for c, _, _ in parsed}
    if len(cases) != 1:
        notes.append(f"time_of_arrival rasters for {len(cases)} fire cases; burned area from the "
                     "raster is only done for one case")
        return None
    last_time = max(t for _, t, _ in parsed)
    cands = sorted(f for _, t, f in parsed if t == last_time)
    path = next((f for f in cands if f.endswith(".tif")), cands[0])
    try:
        ds = gdal.Open(path)
        band = ds.GetRasterBand(1)
        data = band.ReadAsArray().astype(float)
        nodata = band.GetNoDataValue()
        gt = ds.GetGeoTransform()
        srs = ds.GetSpatialRef()
        ds = None
    except Exception as exc:  # GDAL raises RuntimeError on unreadable files
        notes.append(f"cannot read {path}: {exc}")
        read_errors.append(path)
        return None
    if gt[2] != 0 or gt[4] != 0:
        notes.append(f"{path}: rotated grid, burned area not counted")
        return None
    # acreage needs a grid in metres: a projected/local CRS whose linear unit is 1 m
    if srs is None or srs.IsGeographic() or abs(srs.GetLinearUnits() - 1.0) > 1e-9:
        notes.append(f"{path}: grid units not known to be metres, burned area not counted")
        return None
    valid = np.isfinite(data)
    if nodata is not None:
        valid &= data != nodata
    burned = valid & (data >= 0)
    acres = float(burned.sum() * abs(gt[1] * gt[5]) / 4046.8564224)
    notes.append(f"total_area_acres counted from {os.path.basename(path)} "
                 f"({int(burned.sum())} burned cells; no usable fire_size_stats area)")
    return acres


def compute_fire_metrics(fire_stats, raster_categories, notes=None, read_errors=None):
    """Compute aggregate fire behavior metrics.

    A metric with no valid source stays None (not 0) and a note says why.
    """
    if notes is None:
        notes = []
    if read_errors is None:
        read_errors = []
    metrics = {
        "total_area_acres": None,
        "total_area_ha": None,
        "max_spread_rate_ft_min": None,
        "max_spread_rate_m_s": None,
        "max_fireline_intensity_kw_m": None,
        "max_flame_length_ft": None,
        "max_flame_length_m": None,
        "simulation_duration_hr": None,
        "output_file_count": 0,
    }

    def finite(v):
        return isinstance(v, float) and np.isfinite(v)

    # From fire size stats CSV: total area column ("Total fire area (ac)" in ELMFIRE
    # 2025, older "Area(acres)"), duration "tstop (h)" (older "Time ... sec")
    if fire_stats:
        areas, times = [], []
        for row in fire_stats:
            for key, val in row.items():
                k = key.strip().lower()
                if k in ("total fire area (ac)", "area(acres)") and finite(val):
                    areas.append(val)
                elif k == "tstop (h)" and finite(val):
                    times.append(val)
                elif "time" in k and "sec" in k and "wall" not in k and finite(val):
                    times.append(val / 3600.0)
        if areas:
            metrics["total_area_acres"] = max(areas)
            metrics["total_area_ha"] = max(areas) * ACRES_TO_HA
            notes.append("total_area_acres from fire_size_stats (ELMFIRE's fire area)")
        else:
            notes.append("fire_size_stats has no total fire area column/value")
        if times:
            metrics["simulation_duration_hr"] = max(times)
        else:
            notes.append("simulation_duration_hr: no tstop column in fire_size_stats")
    else:
        notes.append("simulation_duration_hr: no fire_size_stats CSV (not taken from the "
                     "time of arrival, which ends when the fire stops)")

    if metrics["total_area_acres"] is None:
        acres = burned_area_from_toa(raster_categories.get("time_of_arrival", []), notes, read_errors)
        if acres is not None:
            metrics["total_area_acres"] = acres
            metrics["total_area_ha"] = acres * ACRES_TO_HA

    # From raster statistics
    for category, files in raster_categories.items():
        metrics["output_file_count"] += len(files)
        for f in files:
            try:
                stats = parse_raster_stats(f)
            except Exception as exc:
                notes.append(f"cannot read {f}: {exc}")
                read_errors.append(f)
                continue
            if stats is None:
                # discovered but not read: GDAL missing or gdal.Open returned None
                notes.append(f"cannot read {f}" + ("" if HAS_GDAL else " (GDAL/osgeo not available)"))
                read_errors.append(f)
                continue
            if stats["count"] == 0 or not np.isfinite(stats["max"]):
                continue

            if category == "spread_rate":
                cur = metrics["max_spread_rate_ft_min"]
                metrics["max_spread_rate_ft_min"] = stats["max"] if cur is None else max(cur, stats["max"])
                metrics["max_spread_rate_m_s"] = metrics["max_spread_rate_ft_min"] * FT_MIN_TO_M_S

            elif category == "flin":
                cur = metrics["max_fireline_intensity_kw_m"]
                metrics["max_fireline_intensity_kw_m"] = stats["max"] if cur is None else max(cur, stats["max"])

            elif category == "flame_length":
                cur = metrics["max_flame_length_ft"]
                metrics["max_flame_length_ft"] = stats["max"] if cur is None else max(cur, stats["max"])
                metrics["max_flame_length_m"] = metrics["max_flame_length_ft"] * FT_TO_M

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


def validate_outputs(metrics, output_path, expect_csv=True, notes=None, read_errors=None):
    """Validate parsed outputs are sensible. notes: where each value came from / why
    it is missing (from compute_fire_metrics)."""
    results = {"status": "ok", "warnings": list(notes or [])}

    if read_errors:
        results["status"] = "error"
        results["warnings"].append(f"Output rasters found but not readable: {read_errors}")
    if metrics["total_area_acres"] is None:
        results["status"] = "error"
        results["warnings"].append("Burned area not available (see the notes above)")
    elif metrics["total_area_acres"] == 0:
        results["warnings"].append("Total burned area is 0 — fire may not have spread")
    for k in ("max_spread_rate_ft_min", "max_fireline_intensity_kw_m", "max_flame_length_ft"):
        if metrics.get(k) is None:
            results["warnings"].append(f"{k}: no valid output raster for it (null in the metrics)")

    if (metrics["max_spread_rate_ft_min"] or 0) > 1000:
        results["warnings"].append(
            f"Max spread rate {metrics['max_spread_rate_ft_min']:.0f} ft/min "
            f"is very high — verify inputs")

    if (metrics["max_flame_length_ft"] or 0) > 200:
        results["warnings"].append(
            f"Max flame length {metrics['max_flame_length_ft']:.0f} ft "
            f"is extremely high — verify fuel moisture")

    if expect_csv and not os.path.isfile(output_path):
        results["status"] = "error"
        results["warnings"].append(f"Output file not created: {output_path}")
    elif not expect_csv:
        old = (f" (the existing {output_path} is NOT from this parse and was left unchanged)"
               if os.path.isfile(output_path) else "")
        results["warnings"].append(f"No fire_size_stats CSV, so no time series written to "
                                   f"{output_path}; metrics JSON only{old}")

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
    notes, read_errors = [], []
    metrics = compute_fire_metrics(fire_stats, raster_categories, notes, read_errors)
    def _f(v, fmt):
        return "n/a" if v is None else format(v, fmt)
    print(f"\nFire behavior metrics:")
    print(f"  Total area: {_f(metrics['total_area_acres'], '.1f')} acres "
          f"({_f(metrics['total_area_ha'], '.1f')} ha)")
    for n in notes:
        print(f"  note: {n}")
    print(f"  Max spread rate: {_f(metrics['max_spread_rate_ft_min'], '.1f')} ft/min "
          f"({_f(metrics['max_spread_rate_m_s'], '.3f')} m/s)")
    print(f"  Max fireline intensity: {_f(metrics['max_fireline_intensity_kw_m'], '.0f')} kW/m")
    print(f"  Max flame length: {_f(metrics['max_flame_length_ft'], '.1f')} ft "
          f"({_f(metrics['max_flame_length_m'], '.1f')} m)")
    print(f"  Duration: {_f(metrics['simulation_duration_hr'], '.1f')} hr")

    # Write outputs
    write_summary_csv(fire_stats, args.out)

    # Write metrics JSON
    metrics_path = args.out.replace(".csv", "_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"  Metrics JSON written to: {metrics_path}")

    # Validate
    print("\nValidating parsed outputs...")
    v = validate_outputs(metrics, args.out, expect_csv=bool(fire_stats), notes=notes,
                         read_errors=read_errors)
    if v["status"] != "ok":
        sys.exit(1)

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
