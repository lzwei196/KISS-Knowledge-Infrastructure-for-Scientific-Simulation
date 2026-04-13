#!/usr/bin/env python3
"""
output_parser.py — Parse HexWatershed output JSON into CSV and summary statistics.

This tool reads the watershed JSON files produced by HexWatershed and extracts
cell-level, segment-level, and subbasin-level data into CSV format for analysis.
It also computes summary statistics and validates output consistency.

CRITICAL: Flow accumulation (`dAccumulation`) is in CELL COUNT, not area.
To convert to drainage area (m²), multiply by mean cell area.

CRITICAL: Slopes are unitless ratios (Δz / Δd), NOT degrees or percent.
To convert to degrees: atan(slope) * 180/π
To convert to percent: slope * 100

Usage:
    python output_parser.py --input /data/output/hexwatershed \
        --output /data/results/ --format csv

    python output_parser.py --input /data/output/hexwatershed \
        --output /data/results/ --format csv --compute-area
"""

import argparse
import csv
import json
import math
import os
import sys


def validate_inputs(args):
    """Validate all input arguments before processing."""
    errors = []

    if not os.path.isdir(args.input):
        errors.append(f"Input directory not found: {args.input}")
    else:
        json_files = [f for f in os.listdir(args.input)
                      if f.startswith("watershed_") and f.endswith(".json")]
        if not json_files:
            errors.append(
                f"No watershed JSON files found in {args.input}. "
                f"Expected files like watershed_00001.json"
            )

    if args.format not in ("csv", "json", "both"):
        errors.append(f"Invalid format '{args.format}'. Must be: csv, json, both")

    if errors:
        result = {"status": "error", "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    return args


def parse_watershed_json(filepath):
    """
    Parse a single watershed JSON file.

    Returns list of cell dicts with extracted fields.
    """
    with open(filepath, "r") as f:
        data = json.load(f)

    # Handle both GeoJSON and raw JSON formats
    if "type" in data and data["type"] == "FeatureCollection":
        features = data.get("features", [])
        cells = []
        for feat in features:
            props = feat.get("properties", {})
            cells.append(props)
    elif isinstance(data, list):
        cells = data
    elif "aCells" in data:
        cells = data["aCells"]
    else:
        cells = [data]

    return cells


def extract_cell_data(cells, compute_area=False):
    """
    Extract cell-level data from parsed watershed JSON.

    Returns list of dicts with standardized field names.
    """
    rows = []
    total_area = 0.0
    mean_cell_area = 0.0

    # First pass: compute mean cell area if needed
    if compute_area:
        areas = [c.get("dArea", 0) for c in cells if c.get("dArea", 0) > 0]
        mean_cell_area = sum(areas) / len(areas) if areas else 0.0

    for cell in cells:
        row = {
            "cell_id": cell.get("lCellID", -1),
            "longitude_deg": cell.get("dLongitude_center_degree", 0),
            "latitude_deg": cell.get("dLatitude_center_degree", 0),
            "elevation_filled_m": cell.get("dElevation_mean", -9999),
            "elevation_raw_m": cell.get("dElevation_raw", -9999),
            "area_m2": cell.get("dArea", 0),
            "accumulation_cells": cell.get("dAccumulation", 0),
            "slope_ratio": cell.get("dSlope_between", 0),
            "slope_within_ratio": cell.get("dSlope_within", 0),
            "distance_to_downslope_m": cell.get("dDistance_to_downslope", 0),
            "distance_to_channel_m": cell.get("dDistance_to_channel", 0),
            "distance_to_outlet_m": cell.get("dDistance_to_watershed_outlet", 0),
            "downslope_cell_id": cell.get("lCellID_downslope", -1),
            "stream_segment": cell.get("lStream_segment", 0),
            "subbasin": cell.get("lSubbasin", 0),
            "hillslope": cell.get("lHillslope", 0),
            "is_stream": 1 if cell.get("iFlag_stream", 0) == 1 else 0,
            "is_confluence": 1 if cell.get("iFlag_confluence", 0) == 1 else 0,
            "is_outlet": 1 if cell.get("iFlag_outlet", 0) == 1 else 0,
            "watershed_id": cell.get("lWatershed", 0),
        }

        # Derived fields
        if compute_area and mean_cell_area > 0:
            row["drainage_area_m2"] = row["accumulation_cells"] * mean_cell_area
            row["drainage_area_km2"] = row["drainage_area_m2"] / 1e6

        if row["slope_ratio"] > 0:
            row["slope_degrees"] = round(math.degrees(math.atan(row["slope_ratio"])), 4)
            row["slope_percent"] = round(row["slope_ratio"] * 100, 4)

        rows.append(row)

    return rows


def compute_summary_statistics(rows):
    """Compute watershed-level summary statistics from cell data."""
    if not rows:
        return {"status": "error", "message": "No cells to summarize"}

    n_cells = len(rows)
    areas = [r["area_m2"] for r in rows if r["area_m2"] > 0]
    elevations = [r["elevation_filled_m"] for r in rows if r["elevation_filled_m"] > -9999]
    slopes = [r["slope_ratio"] for r in rows if r["slope_ratio"] > 0]
    accum = [r["accumulation_cells"] for r in rows]
    stream_cells = [r for r in rows if r["is_stream"] == 1]
    confluence_cells = [r for r in rows if r["is_confluence"] == 1]
    outlet_cells = [r for r in rows if r["is_outlet"] == 1]

    total_area = sum(areas) if areas else 0
    mean_cell_area = total_area / len(areas) if areas else 0

    # Stream length approximation: n_stream_cells * mean_cell_resolution
    mean_resolution = math.sqrt(mean_cell_area) if mean_cell_area > 0 else 0
    stream_length_m = len(stream_cells) * mean_resolution

    # Drainage density (km/km²)
    total_area_km2 = total_area / 1e6
    stream_length_km = stream_length_m / 1000
    drainage_density = stream_length_km / total_area_km2 if total_area_km2 > 0 else 0

    stats = {
        "n_cells": n_cells,
        "n_stream_cells": len(stream_cells),
        "n_confluences": len(confluence_cells),
        "n_outlets": len(outlet_cells),
        "total_area_m2": round(total_area, 2),
        "total_area_km2": round(total_area_km2, 4),
        "mean_cell_area_m2": round(mean_cell_area, 2),
        "elevation_min_m": round(min(elevations), 2) if elevations else None,
        "elevation_max_m": round(max(elevations), 2) if elevations else None,
        "elevation_mean_m": round(sum(elevations) / len(elevations), 2) if elevations else None,
        "elevation_range_m": round(max(elevations) - min(elevations), 2) if elevations else None,
        "slope_mean_ratio": round(sum(slopes) / len(slopes), 6) if slopes else None,
        "slope_max_ratio": round(max(slopes), 6) if slopes else None,
        "slope_mean_degrees": round(math.degrees(math.atan(sum(slopes) / len(slopes))), 4) if slopes else None,
        "accumulation_max_cells": max(accum) if accum else 0,
        "stream_length_approx_km": round(stream_length_km, 2),
        "drainage_density_km_per_km2": round(drainage_density, 4),
        "stream_density_ratio": round(len(stream_cells) / n_cells, 4) if n_cells > 0 else 0,
    }

    # Unique subbasins and segments
    subbasins = set(r["subbasin"] for r in rows if r["subbasin"] > 0)
    segments = set(r["stream_segment"] for r in rows if r["stream_segment"] > 0)
    stats["n_subbasins"] = len(subbasins)
    stats["n_segments"] = len(segments)

    return stats


def write_csv(rows, filepath):
    """Write cell data to CSV."""
    if not rows:
        return

    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

    fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def process(args):
    """Parse all watershed outputs and generate summaries."""
    result = {"status": "success", "warnings": [], "watersheds": []}

    # Find watershed JSON files
    json_files = sorted([
        f for f in os.listdir(args.input)
        if f.startswith("watershed_") and f.endswith(".json")
        and "characteristics" not in f
    ])

    os.makedirs(args.output, exist_ok=True)

    all_rows = []

    for jf in json_files:
        filepath = os.path.join(args.input, jf)
        watershed_name = os.path.splitext(jf)[0]

        try:
            cells = parse_watershed_json(filepath)
            rows = extract_cell_data(cells, compute_area=args.compute_area)
            stats = compute_summary_statistics(rows)

            # Write per-watershed CSV
            csv_path = os.path.join(args.output, f"{watershed_name}.csv")
            write_csv(rows, csv_path)

            # Write per-watershed stats
            stats_path = os.path.join(args.output, f"{watershed_name}_stats.json")
            with open(stats_path, "w") as f:
                json.dump(stats, f, indent=2)

            result["watersheds"].append({
                "name": watershed_name,
                "csv_path": csv_path,
                "stats_path": stats_path,
                "n_cells": stats.get("n_cells", 0),
                "area_km2": stats.get("total_area_km2", 0),
            })

            all_rows.extend(rows)

        except Exception as e:
            result["warnings"].append(f"Error parsing {jf}: {str(e)}")

    # Write combined CSV
    if all_rows:
        combined_csv = os.path.join(args.output, "all_watersheds.csv")
        write_csv(all_rows, combined_csv)
        result["combined_csv"] = combined_csv

    # Overall summary
    result["n_watersheds"] = len(result["watersheds"])
    result["n_total_cells"] = len(all_rows)

    # Also parse characteristics files if present
    char_files = [
        f for f in os.listdir(args.input)
        if "characteristics" in f and f.endswith(".txt")
    ]
    if char_files:
        result["characteristics_files"] = char_files

    return result


def validate_outputs(result):
    """Check outputs for common issues."""
    if result.get("status") != "success":
        return result

    if result.get("n_watersheds", 0) == 0:
        result["warnings"].append(
            "No watershed data parsed. Check input directory for watershed_*.json files."
        )

    if result.get("n_total_cells", 0) == 0:
        result["warnings"].append(
            "No cells extracted from any watershed. Check JSON format."
        )

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse HexWatershed output JSON into CSV and statistics"
    )
    parser.add_argument(
        "--input", type=str, required=True,
        help="Path to HexWatershed output directory (containing watershed_*.json)"
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="Path to output directory for CSV and stats files"
    )
    parser.add_argument(
        "--format", type=str, default="csv",
        help="Output format: csv, json, both (default: csv)"
    )
    parser.add_argument(
        "--compute-area", action="store_true",
        help="Convert accumulation (cells) to drainage area (m², km²)"
    )

    args = parser.parse_args()
    args = validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
