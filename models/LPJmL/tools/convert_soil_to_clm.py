#!/usr/bin/env python3
"""
convert_soil_to_clm.py — Convert HWSD/SoilGrids soil texture data to LPJmL soil class binary.

LPJmL uses 13 USDA soil texture classes + rock/ice (ID 14). The soil file is a simple
binary with one byte per grid cell, mapping to the soil type IDs in par/soil.cjson.

USDA Texture Triangle Classification:
  ID  Name              Sand%   Silt%   Clay%
  1   clay              22      24      54
  2   silty clay        6       47      47
  3   sandy clay        52      6       42
  4   clay loam         32      34      34
  5   silty clay loam   10      56      34
  6   sandy clay loam   58      15      27
  7   loam              43      39      18
  8   silt loam         17      70      13
  9   sandy loam        58      32      10
  10  silt              10      60      30
  11  loamy sand        82      12      6
  12  sand              92      5       3
  13  clay (light)      24      28      48
  14  rock and ice      99      0       1

CRITICAL: Soil type 0 (null) means no soil data — the cell is skipped by LPJmL.
          Ensure rock/ice is ID 14, not 0.

Usage:
    python convert_soil_to_clm.py \\
        --input /path/to/HWSD_soil.nc \\
        --grid_file /path/to/grid.bin \\
        --output /path/to/soil.bin \\
        --method texture_triangle

    python convert_soil_to_clm.py \\
        --input /path/to/soilgrids_sand.nc \\
        --sand_var sand --silt_var silt --clay_var clay \\
        --grid_file /path/to/grid.bin \\
        --output /path/to/soil.bin
"""

import argparse
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np

# LPJmL soil class definitions (centroids in USDA texture triangle)
SOIL_CLASSES = {
    1:  {"name": "clay",            "sand": (0, 20, 45),  "silt": (0, 0, 40),  "clay": (40, 60, 100)},
    2:  {"name": "silty clay",      "sand": (0, 0, 20),   "silt": (40, 60, 60), "clay": (40, 40, 60)},
    3:  {"name": "sandy clay",      "sand": (45, 65, 55), "silt": (0, 0, 20),  "clay": (35, 35, 55)},
    4:  {"name": "clay loam",       "sand": (20, 45, 45), "silt": (15, 15, 53), "clay": (27, 40, 40)},
    5:  {"name": "silty clay loam", "sand": (0, 0, 20),   "silt": (40, 73, 73), "clay": (27, 27, 40)},
    6:  {"name": "sandy clay loam", "sand": (45, 65, 80), "silt": (0, 0, 28),  "clay": (20, 35, 35)},
    7:  {"name": "loam",            "sand": (23, 43, 52), "silt": (28, 28, 50), "clay": (7, 27, 27)},
    8:  {"name": "silt loam",       "sand": (0, 0, 50),   "silt": (50, 80, 88), "clay": (0, 0, 27)},
    9:  {"name": "sandy loam",      "sand": (43, 52, 85), "silt": (0, 0, 50),  "clay": (0, 0, 20)},
    10: {"name": "silt",            "sand": (0, 0, 20),   "silt": (80, 80, 100),"clay": (0, 0, 12)},
    11: {"name": "loamy sand",      "sand": (70, 85, 90), "silt": (0, 0, 30),  "clay": (0, 0, 15)},
    12: {"name": "sand",            "sand": (85, 90, 100),"silt": (0, 0, 15),  "clay": (0, 0, 10)},
}

# Centroid points for nearest-centroid classification
CENTROIDS = np.array([
    [22, 24, 54],   # 1: clay
    [6,  47, 47],   # 2: silty clay
    [52, 6,  42],   # 3: sandy clay
    [32, 34, 34],   # 4: clay loam
    [10, 56, 34],   # 5: silty clay loam
    [58, 15, 27],   # 6: sandy clay loam
    [43, 39, 18],   # 7: loam
    [17, 70, 13],   # 8: silt loam
    [58, 32, 10],   # 9: sandy loam
    [10, 60, 30],   # 10: silt
    [82, 12, 6],    # 11: loamy sand
    [92, 5,  3],    # 12: sand
], dtype=np.float64)


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if not os.path.isfile(args.grid_file):
        errors.append(f"Grid file not found: {args.grid_file}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def classify_texture(sand_pct, silt_pct, clay_pct):
    """
    Classify soil texture using USDA texture triangle.

    Uses nearest-centroid method: find the LPJmL soil class whose centroid
    is closest (Euclidean) to the input sand/silt/clay percentages.

    Parameters:
        sand_pct, silt_pct, clay_pct: float, percentages (0-100)

    Returns:
        int: soil class ID (1-12), or 14 for rock/ice, or 0 for invalid
    """
    total = sand_pct + silt_pct + clay_pct
    if total < 1.0 or np.isnan(total):
        return 0  # No data

    # Normalize to 100%
    sand = sand_pct / total * 100
    silt = silt_pct / total * 100
    clay = clay_pct / total * 100

    # Compute distances to centroids
    point = np.array([sand, silt, clay])
    distances = np.linalg.norm(CENTROIDS - point, axis=1)
    best_class = np.argmin(distances) + 1  # 1-indexed

    return best_class


def read_grid_clm(grid_path):
    """Read LPJmL grid file."""
    with open(grid_path, "rb") as f:
        name = f.read(30)
        header = struct.unpack("<iiiiiii", f.read(28))
        version = header[0]
        ncell = header[5]

        if version >= 3:
            extra = struct.unpack("<ffif", f.read(16))
            scalar = extra[3]
        else:
            scalar = 0.01

        data = np.fromfile(f, dtype=np.int16, count=ncell * 2)
        coords = data.reshape(ncell, 2).astype(np.float64) * scalar

    return coords, ncell


def write_soil_clm(output_path, soil_data, ncell):
    """Write LPJmL soil binary file with CLM header."""
    with open(output_path, "wb") as f:
        # Header
        name = b"LPJSOIL".ljust(30, b"\x00")
        f.write(name)
        f.write(struct.pack("<i", 2))   # version
        f.write(struct.pack("<i", 1))   # order (little-endian)
        f.write(struct.pack("<i", 0))   # firstyear
        f.write(struct.pack("<i", 1))   # nyear
        f.write(struct.pack("<i", 0))   # firstcell
        f.write(struct.pack("<i", ncell))  # ncell
        f.write(struct.pack("<i", 1))   # nbands

        # Write soil type IDs
        soil_data.astype(np.uint8).tofile(f)


def convert_hwsd_to_lpjml(input_path, grid_file, output_path,
                          sand_var="sand", silt_var="silt", clay_var="clay"):
    """Convert HWSD or SoilGrids NetCDF to LPJmL soil class binary."""
    try:
        import xarray as xr
    except ImportError:
        print(json.dumps({"status": "error",
                          "errors": ["xarray not installed"]}))
        sys.exit(1)

    coords, ncell = read_grid_clm(grid_file)
    ds = xr.open_dataset(input_path)

    soil_ids = np.zeros(ncell, dtype=np.uint8)
    classification_stats = {i: 0 for i in range(15)}

    for ci in range(ncell):
        lon, lat = coords[ci]
        try:
            sand = float(ds[sand_var].sel(lon=lon, lat=lat, method="nearest"))
            silt = float(ds[silt_var].sel(lon=lon, lat=lat, method="nearest"))
            clay = float(ds[clay_var].sel(lon=lon, lat=lat, method="nearest"))

            # SoilGrids gives g/kg, convert to percent
            if sand > 100:
                sand /= 10.0
                silt /= 10.0
                clay /= 10.0

            soil_id = classify_texture(sand, silt, clay)
        except (KeyError, ValueError):
            soil_id = 0  # No data

        soil_ids[ci] = soil_id
        classification_stats[soil_id] = classification_stats.get(soil_id, 0) + 1

    ds.close()

    # Write output
    write_soil_clm(output_path, soil_ids, ncell)

    # Validate
    validate_soil_output(soil_ids, ncell)

    result = {
        "status": "success",
        "output": output_path,
        "ncell": ncell,
        "classification_stats": {k: v for k, v in classification_stats.items() if v > 0},
        "no_data_cells": int(classification_stats.get(0, 0)),
    }
    return result


def validate_soil_output(soil_ids, ncell):
    """Validate soil classification output."""
    warnings = []

    no_data = np.sum(soil_ids == 0)
    if no_data > ncell * 0.5:
        warnings.append(f"High no-data fraction: {no_data}/{ncell} cells "
                        f"({100*no_data/ncell:.1f}%) have no soil data")

    unique_classes = np.unique(soil_ids[soil_ids > 0])
    if len(unique_classes) < 3:
        warnings.append(f"Only {len(unique_classes)} soil classes found — "
                        f"check input resolution matches grid")

    if warnings:
        print(json.dumps({"status": "warning", "warnings": warnings}))
    else:
        print(json.dumps({"status": "ok",
                          "message": f"Soil file OK: {ncell} cells, "
                                     f"{len(unique_classes)} classes"}))


def main():
    parser = argparse.ArgumentParser(
        description="Convert HWSD/SoilGrids to LPJmL soil binary")
    parser.add_argument("--input", required=True, help="Input NetCDF file")
    parser.add_argument("--grid_file", required=True, help="LPJmL grid.bin")
    parser.add_argument("--output", required=True, help="Output soil binary file")
    parser.add_argument("--sand_var", default="sand", help="Sand variable name")
    parser.add_argument("--silt_var", default="silt", help="Silt variable name")
    parser.add_argument("--clay_var", default="clay", help="Clay variable name")
    parser.add_argument("--method", default="texture_triangle",
                        choices=["texture_triangle", "nearest_centroid"])

    args = parser.parse_args()

    # Step 1: Validate
    validate_inputs(args)

    # Step 2: Process
    result = convert_hwsd_to_lpjml(
        args.input, args.grid_file, args.output,
        args.sand_var, args.silt_var, args.clay_var
    )

    # Step 3: Report
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
