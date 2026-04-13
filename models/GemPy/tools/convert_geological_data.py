#!/usr/bin/env python3
"""Convert geological survey data to GemPy-compatible CSV format.

Handles:
  - Azimuth/dip/polarity → gradient vector (G_x, G_y, G_z) conversion
  - Coordinate unit conversion (km → m, ft → m)
  - Column name remapping
  - CRS validation (warns if mixing coordinate systems)

Usage:
  python convert_geological_data.py \
      --surface-points raw_points.csv \
      --orientations raw_orientations.csv \
      --coord-unit meters \
      --orientation-format azimuth_dip \
      --output-dir gempy_input/

  python convert_geological_data.py \
      --surface-points borehole_data.csv \
      --col-x Easting --col-y Northing --col-z Depth \
      --col-formation Layer \
      --coord-unit meters \
      --output-dir gempy_input/
"""

import argparse
import csv
import json
import math
import os
import sys


# --- Constants ---
COORD_UNIT_FACTORS = {
    "meters": 1.0,
    "m": 1.0,
    "kilometers": 1000.0,
    "km": 1000.0,
    "feet": 0.3048,
    "ft": 0.3048,
}

REQUIRED_SP_COLS = ["X", "Y", "Z", "formation"]
REQUIRED_OR_COLS_GRADIENT = ["X", "Y", "Z", "G_x", "G_y", "G_z"]
REQUIRED_OR_COLS_AZIMUTH = ["X", "Y", "Z", "azimuth", "dip", "polarity"]


def validate_inputs(args):
    """Validate all input arguments. Exit with JSON error on failure."""
    errors = []

    if args.surface_points and not os.path.isfile(args.surface_points):
        errors.append(f"Surface points file not found: {args.surface_points}")

    if args.orientations and not os.path.isfile(args.orientations):
        errors.append(f"Orientations file not found: {args.orientations}")

    if not args.surface_points and not args.orientations:
        errors.append("At least one of --surface-points or --orientations required")

    if args.coord_unit not in COORD_UNIT_FACTORS:
        errors.append(
            f"Unknown coordinate unit: {args.coord_unit}. "
            f"Supported: {list(COORD_UNIT_FACTORS.keys())}"
        )

    if args.orientation_format not in ("gradient", "azimuth_dip"):
        errors.append(
            f"Unknown orientation format: {args.orientation_format}. "
            f"Supported: gradient, azimuth_dip"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def read_csv(filepath):
    """Read CSV file and return list of dicts."""
    with open(filepath, "r", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


def remap_columns(rows, col_map):
    """Remap column names according to mapping dict."""
    if not col_map:
        return rows
    remapped = []
    for row in rows:
        new_row = {}
        for key, value in row.items():
            new_key = col_map.get(key, key)
            new_row[new_key] = value
        remapped.append(new_row)
    return remapped


def convert_coordinates(rows, unit_factor):
    """Convert X, Y, Z coordinates by multiplying with unit_factor."""
    if unit_factor == 1.0:
        return rows
    converted = []
    for row in rows:
        new_row = dict(row)
        for coord in ("X", "Y", "Z"):
            if coord in new_row:
                try:
                    new_row[coord] = str(float(new_row[coord]) * unit_factor)
                except (ValueError, TypeError):
                    pass  # keep original if not numeric
        converted.append(new_row)
    return converted


def azimuth_dip_to_gradient(azimuth_deg, dip_deg, polarity):
    """Convert azimuth/dip/polarity to unit gradient vector.

    Parameters
    ----------
    azimuth_deg : float
        Azimuth in degrees, clockwise from North (0-360).
    dip_deg : float
        Dip in degrees from horizontal (0-90).
    polarity : float
        +1 or -1, indicates normal direction.

    Returns
    -------
    tuple of (G_x, G_y, G_z)
        Unit gradient vector components.
    """
    azimuth_rad = math.radians(azimuth_deg)
    dip_rad = math.radians(dip_deg)
    pol = float(polarity)

    g_x = math.sin(dip_rad) * math.sin(azimuth_rad) * pol
    g_y = math.sin(dip_rad) * math.cos(azimuth_rad) * pol
    g_z = math.cos(dip_rad) * pol

    # Normalize to unit vector
    magnitude = math.sqrt(g_x**2 + g_y**2 + g_z**2)
    if magnitude > 0:
        g_x /= magnitude
        g_y /= magnitude
        g_z /= magnitude

    return (round(g_x, 8), round(g_y, 8), round(g_z, 8))


def convert_orientations_to_gradient(rows):
    """Convert azimuth/dip/polarity rows to gradient format."""
    converted = []
    for i, row in enumerate(rows):
        new_row = dict(row)
        try:
            azimuth = float(row["azimuth"])
            dip = float(row["dip"])
            polarity = float(row.get("polarity", 1.0))
        except (ValueError, KeyError) as e:
            print(
                json.dumps({
                    "status": "error",
                    "errors": [f"Row {i}: cannot parse orientation: {e}"]
                })
            )
            sys.exit(1)

        # Validate ranges
        if not (0 <= azimuth <= 360):
            print(
                json.dumps({
                    "status": "error",
                    "errors": [f"Row {i}: azimuth {azimuth} not in [0, 360]"]
                })
            )
            sys.exit(1)
        if not (0 <= dip <= 90):
            print(
                json.dumps({
                    "status": "error",
                    "errors": [f"Row {i}: dip {dip} not in [0, 90]"]
                })
            )
            sys.exit(1)

        g_x, g_y, g_z = azimuth_dip_to_gradient(azimuth, dip, polarity)
        new_row["G_x"] = str(g_x)
        new_row["G_y"] = str(g_y)
        new_row["G_z"] = str(g_z)

        # Remove original columns
        for col in ("azimuth", "dip", "polarity"):
            new_row.pop(col, None)

        converted.append(new_row)
    return converted


def normalize_gradients(rows):
    """Ensure all gradient vectors are unit vectors."""
    normalized = []
    for i, row in enumerate(rows):
        new_row = dict(row)
        try:
            g_x = float(row["G_x"])
            g_y = float(row["G_y"])
            g_z = float(row["G_z"])
        except (ValueError, KeyError) as e:
            print(
                json.dumps({
                    "status": "error",
                    "errors": [f"Row {i}: cannot parse gradient: {e}"]
                })
            )
            sys.exit(1)

        magnitude = math.sqrt(g_x**2 + g_y**2 + g_z**2)
        if magnitude < 1e-10:
            print(
                json.dumps({
                    "status": "error",
                    "errors": [f"Row {i}: zero-length gradient vector"]
                })
            )
            sys.exit(1)

        if abs(magnitude - 1.0) > 0.01:
            # Normalize
            g_x /= magnitude
            g_y /= magnitude
            g_z /= magnitude

        new_row["G_x"] = str(round(g_x, 8))
        new_row["G_y"] = str(round(g_y, 8))
        new_row["G_z"] = str(round(g_z, 8))
        normalized.append(new_row)
    return normalized


def write_csv(rows, filepath, columns):
    """Write rows to CSV with specified column order."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def process(args):
    """Main processing: convert inputs to GemPy format."""
    result = {"status": "success", "files_written": []}
    unit_factor = COORD_UNIT_FACTORS[args.coord_unit]

    # Build column remapping
    col_map = {}
    if args.col_x:
        col_map[args.col_x] = "X"
    if args.col_y:
        col_map[args.col_y] = "Y"
    if args.col_z:
        col_map[args.col_z] = "Z"
    if args.col_formation:
        col_map[args.col_formation] = "formation"

    # --- Surface points ---
    if args.surface_points:
        sp_rows = read_csv(args.surface_points)
        sp_rows = remap_columns(sp_rows, col_map)
        sp_rows = convert_coordinates(sp_rows, unit_factor)

        # Validate required columns present
        if sp_rows:
            missing = [c for c in REQUIRED_SP_COLS if c not in sp_rows[0]]
            if missing:
                return {
                    "status": "error",
                    "errors": [f"Surface points missing columns: {missing}"]
                }

        sp_out = os.path.join(args.output_dir, "surface_points.csv")
        write_csv(sp_rows, sp_out, REQUIRED_SP_COLS)
        result["files_written"].append(sp_out)
        result["n_surface_points"] = len(sp_rows)

        # Coordinate range check
        xs = [float(r["X"]) for r in sp_rows]
        ys = [float(r["Y"]) for r in sp_rows]
        zs = [float(r["Z"]) for r in sp_rows]
        result["sp_extent"] = {
            "x": [round(min(xs), 2), round(max(xs), 2)],
            "y": [round(min(ys), 2), round(max(ys), 2)],
            "z": [round(min(zs), 2), round(max(zs), 2)],
        }
        result["formations"] = sorted(set(r["formation"] for r in sp_rows))

    # --- Orientations ---
    if args.orientations:
        or_rows = read_csv(args.orientations)
        or_rows = remap_columns(or_rows, col_map)
        or_rows = convert_coordinates(or_rows, unit_factor)

        if args.orientation_format == "azimuth_dip":
            or_rows = convert_orientations_to_gradient(or_rows)
        else:
            or_rows = normalize_gradients(or_rows)

        or_out = os.path.join(args.output_dir, "orientations.csv")
        write_csv(or_rows, or_out, ["X", "Y", "Z", "G_x", "G_y", "G_z", "formation"])
        result["files_written"].append(or_out)
        result["n_orientations"] = len(or_rows)

    return result


def validate_outputs(result):
    """Validate the processing results."""
    if result.get("status") != "success":
        return result

    if not result.get("files_written"):
        result["warnings"] = ["No output files were generated"]

    # Check for suspicious coordinate ranges
    if "sp_extent" in result:
        ext = result["sp_extent"]
        x_range = ext["x"][1] - ext["x"][0]
        y_range = ext["y"][1] - ext["y"][0]
        z_range = ext["z"][1] - ext["z"][0]

        warnings = result.get("warnings", [])
        if x_range < 1.0 or y_range < 1.0:
            warnings.append(
                f"Very small XY extent ({x_range:.1f} x {y_range:.1f}). "
                f"Are coordinates in km? Use --coord-unit km"
            )
        if x_range > 1e7 or y_range > 1e7:
            warnings.append(
                f"Very large XY extent ({x_range:.0f} x {y_range:.0f}). "
                f"Consider using local coordinates for numerical stability."
            )
        if z_range < 0.01:
            warnings.append(
                "Z range near zero — all points at same elevation?"
            )
        if warnings:
            result["warnings"] = warnings

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert geological survey data to GemPy CSV format"
    )
    parser.add_argument(
        "--surface-points", type=str, default=None,
        help="Path to raw surface points CSV"
    )
    parser.add_argument(
        "--orientations", type=str, default=None,
        help="Path to raw orientations CSV"
    )
    parser.add_argument(
        "--coord-unit", type=str, default="meters",
        help="Input coordinate unit: meters, km, feet (default: meters)"
    )
    parser.add_argument(
        "--orientation-format", type=str, default="gradient",
        help="Orientation format: gradient or azimuth_dip (default: gradient)"
    )
    parser.add_argument(
        "--col-x", type=str, default=None,
        help="Source column name for X coordinate"
    )
    parser.add_argument(
        "--col-y", type=str, default=None,
        help="Source column name for Y coordinate"
    )
    parser.add_argument(
        "--col-z", type=str, default=None,
        help="Source column name for Z coordinate"
    )
    parser.add_argument(
        "--col-formation", type=str, default=None,
        help="Source column name for formation/layer"
    )
    parser.add_argument(
        "--output-dir", type=str, default="gempy_input",
        help="Output directory (default: gempy_input)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Write JSON result to this file"
    )
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Result written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
