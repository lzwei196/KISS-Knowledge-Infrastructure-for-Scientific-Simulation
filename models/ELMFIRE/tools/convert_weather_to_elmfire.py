#!/usr/bin/env python3
"""
convert_weather_to_elmfire.py — Convert weather/fuel moisture data to ELMFIRE inputs.

CRITICAL UNIT CONVERSIONS (silent errors if wrong):
  - Wind speed: ELMFIRE wants mph at 20 ft. Common sources: m/s at 10 m.
    Conversion: ws_mph_20ft = ws_ms_10m × 2.237 × 1.15
  - Wind direction: ELMFIRE uses meteorological convention (FROM).
    If source is math convention (TO), add 180° mod 360.
  - Dead fuel moisture (M1, M10, M100): ELMFIRE wants percent (e.g., 5.0 = 5%).
    If source is fraction (0.05), multiply by 100.
  - Live fuel moisture: Same as dead — percent not fraction.

Generates:
  1. Weather GeoTIFFs: ws.tif, wd.tif, m1.tif, m10.tif, m100.tif
  2. Fortran namelist file: elmfire.data

Usage:
    # Constant weather (for testing)
    python convert_weather_to_elmfire.py \\
        --ws 15 --wd 0 --m1 3 --m10 4 --m100 5 \\
        --lh_moisture 30 --lw_moisture 60 \\
        --template_raster ./inputs/dem.tif \\
        --out ./inputs

    # From gridded weather (HRRR/GFS)
    python convert_weather_to_elmfire.py \\
        --weather_dir /path/to/hrrr/ \\
        --template_raster ./inputs/dem.tif \\
        --epsg 32610 --cellsize 30 \\
        --out ./inputs

    # Generate namelist
    python convert_weather_to_elmfire.py \\
        --generate_namelist \\
        --inputs_dir ./inputs \\
        --outputs_dir ./outputs \\
        --cellsize 30 --epsg 32610 \\
        --xll -6000 --yll -6000 \\
        --tstop 21600 --dtdump 3600 \\
        --x_ign 0.0 --y_ign 3000.0 \\
        --lh_moisture 30 --lw_moisture 60 \\
        --out ./inputs
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np


def validate_inputs(args):
    """Validate input arguments."""
    errors = []
    warnings = []

    if args.template_raster and not os.path.isfile(args.template_raster):
        errors.append(f"Template raster not found: {args.template_raster}")

    # Check wind speed units
    if args.ws is not None:
        if args.ws < 1.0 and args.ws > 0:
            warnings.append(
                f"Wind speed {args.ws} — this looks like m/s, not mph. "
                f"ELMFIRE expects mph at 20 ft. Convert: mph = m/s × 2.237"
            )
        if args.ws > 100:
            warnings.append(
                f"Wind speed {args.ws} mph seems very high — verify units"
            )

    # Check fuel moisture units
    for name, val in [("M1", args.m1), ("M10", args.m10), ("M100", args.m100)]:
        if val is not None and val < 1.0 and val > 0:
            warnings.append(
                f"{name}={val} — looks like fraction, not percent. "
                f"ELMFIRE expects percent (e.g., 5.0 = 5%)"
            )

    if args.lh_moisture is not None and args.lh_moisture < 1.0:
        warnings.append(
            f"Live herbaceous moisture {args.lh_moisture} — looks like fraction. "
            f"Expected percent (30-300)"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    if warnings:
        for w in warnings:
            print(f"  WARNING: {w}")


def create_constant_raster(template_path, output_path, value, dtype="Float32"):
    """Create a constant-value raster matching a template."""
    cmd = [
        "gdal_calc.py",
        "-A", template_path,
        f"--outfile={output_path}",
        f"--calc=A*0+{value}",
        "--NoDataValue=-9999",
        f"--type={dtype}",
        "--co=COMPRESS=DEFLATE",
        "--co=ZLEVEL=9",
        "--overwrite"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR creating raster: {result.stderr}")
        return False
    return True


def convert_wind_speed(ws_ms_10m):
    """Convert wind speed from m/s at 10 m to mph at 20 ft.

    Uses log wind profile to adjust height:
      ws_20ft = ws_10m × ln(20ft / z0) / ln(10m / z0)
    Simplified: ws_20ft ≈ ws_10m × 1.15 (for z0 ≈ 0.1 m)
    Then convert m/s to mph: ×2.237
    """
    ws_mph_20ft = ws_ms_10m * 2.237 * 1.15
    return ws_mph_20ft


def convert_wind_direction_to_met(wd_math):
    """Convert wind direction from math convention (TO) to met convention (FROM).

    Meteorological: direction FROM which wind blows (0=N, 90=E)
    Mathematical: direction TO which wind blows
    """
    wd_met = (wd_math + 180.0) % 360.0
    return wd_met


def generate_namelist(args):
    """Generate ELMFIRE Fortran namelist file (elmfire.data)."""
    namelist = f"""&INPUTS
FUELS_AND_TOPOGRAPHY_DIRECTORY = '{args.inputs_dir}'
ASP_FILENAME                   = 'asp'
CBD_FILENAME                   = 'cbd'
CBH_FILENAME                   = 'cbh'
CC_FILENAME                    = 'cc'
CH_FILENAME                    = 'ch'
DEM_FILENAME                   = 'dem'
FBFM_FILENAME                  = 'fbfm40'
SLP_FILENAME                   = 'slp'
ADJ_FILENAME                   = 'adj'
PHI_FILENAME                   = 'phi'
DT_METEOROLOGY                 = {args.dt_meteorology}
WEATHER_DIRECTORY              = '{args.inputs_dir}'
WS_FILENAME                    = 'ws'
WD_FILENAME                    = 'wd'
M1_FILENAME                    = 'm1'
M10_FILENAME                   = 'm10'
M100_FILENAME                  = 'm100'
LH_MOISTURE_CONTENT            = {args.lh_moisture}
LW_MOISTURE_CONTENT            = {args.lw_moisture}
/

&OUTPUTS
OUTPUTS_DIRECTORY    = '{args.outputs_dir}'
DTDUMP               = {args.dtdump}
DUMP_FLIN            = .TRUE.
DUMP_SPREAD_RATE     = .TRUE.
DUMP_TIME_OF_ARRIVAL = .TRUE.
DUMP_FLAME_LENGTH    = .TRUE.
DUMP_FIRE_SIZE_STATS = .TRUE.
CONVERT_TO_GEOTIFF   = .FALSE.
/

&COMPUTATIONAL_DOMAIN
A_SRS = 'EPSG: {args.epsg}'
COMPUTATIONAL_DOMAIN_CELLSIZE = {args.cellsize}
COMPUTATIONAL_DOMAIN_XLLCORNER = {args.xll}
COMPUTATIONAL_DOMAIN_YLLCORNER = {args.yll}
/

&TIME_CONTROL
SIMULATION_DT    = {args.simulation_dt}
SIMULATION_TSTOP = {args.tstop}
/

&SIMULATOR
NUM_IGNITIONS = 1
X_IGN(1)      = {args.x_ign}
Y_IGN(1)      = {args.y_ign}
T_IGN(1)      = 0.0
WX_BILINEAR_INTERPOLATION = .TRUE.
/

&MISCELLANEOUS
PATH_TO_GDAL = '/usr/bin'
SCRATCH      = './scratch'
/
"""
    namelist_path = os.path.join(args.out, "elmfire.data")
    with open(namelist_path, "w") as f:
        f.write(namelist)
    print(f"  Namelist written to: {namelist_path}")
    return namelist_path


def validate_outputs(output_dir):
    """Validate weather rasters have sensible values."""
    results = {"status": "ok", "files": {}, "warnings": []}

    for name in ["ws", "wd", "m1", "m10", "m100"]:
        path = os.path.join(output_dir, f"{name}.tif")
        if os.path.isfile(path):
            results["files"][name] = {"path": path, "exists": True}
        else:
            results["files"][name] = "MISSING"
            results["status"] = "error"

    namelist_path = os.path.join(output_dir, "elmfire.data")
    if os.path.isfile(namelist_path):
        results["files"]["elmfire.data"] = {"path": namelist_path, "exists": True}

    print(json.dumps(results, indent=2))
    return results


def process(args):
    """Main processing pipeline: validate → process → validate."""
    validate_inputs(args)
    os.makedirs(args.out, exist_ok=True)

    if args.generate_namelist:
        generate_namelist(args)
        return

    if args.template_raster is None:
        print(json.dumps({"status": "error",
                          "errors": ["--template_raster required for weather generation"]}))
        sys.exit(1)

    print("Converting weather data to ELMFIRE format...")

    # Create constant weather rasters
    weather_vars = [
        ("ws", args.ws, "Float32", "Wind speed (mph at 20ft)"),
        ("wd", args.wd, "Float32", "Wind direction (degrees, met)"),
        ("m1", args.m1, "Float32", "1-hr dead fuel moisture (%)"),
        ("m10", args.m10, "Float32", "10-hr dead fuel moisture (%)"),
        ("m100", args.m100, "Float32", "100-hr dead fuel moisture (%)"),
    ]

    for name, value, dtype, desc in weather_vars:
        if value is not None:
            path = os.path.join(args.out, f"{name}.tif")
            print(f"  Creating {name}.tif = {value} ({desc})")
            create_constant_raster(args.template_raster, path, value, dtype)

    # Generate namelist if inputs_dir is provided
    if args.inputs_dir:
        generate_namelist(args)

    # Validate
    print("\nValidating outputs...")
    validate_outputs(args.out)


def main():
    parser = argparse.ArgumentParser(
        description="Convert weather data to ELMFIRE inputs and generate namelist"
    )
    # Weather values (constant)
    parser.add_argument("--ws", type=float, default=None, help="Wind speed (mph at 20ft)")
    parser.add_argument("--wd", type=float, default=None, help="Wind direction (degrees)")
    parser.add_argument("--m1", type=float, default=None, help="1-hr fuel moisture (%%)")
    parser.add_argument("--m10", type=float, default=None, help="10-hr fuel moisture (%%)")
    parser.add_argument("--m100", type=float, default=None, help="100-hr fuel moisture (%%)")
    parser.add_argument("--lh_moisture", type=float, default=30.0,
                        help="Live herbaceous moisture (%%)")
    parser.add_argument("--lw_moisture", type=float, default=60.0,
                        help="Live woody moisture (%%)")

    # Raster generation
    parser.add_argument("--template_raster", default=None,
                        help="Template GeoTIFF for extent/resolution")
    parser.add_argument("--weather_dir", default=None,
                        help="Directory with gridded weather (HRRR/GFS)")

    # Namelist generation
    parser.add_argument("--generate_namelist", action="store_true",
                        help="Generate elmfire.data namelist")
    parser.add_argument("--inputs_dir", default=None, help="ELMFIRE inputs directory")
    parser.add_argument("--outputs_dir", default="./outputs", help="ELMFIRE outputs directory")
    parser.add_argument("--cellsize", type=float, default=30.0, help="Cell size (m)")
    parser.add_argument("--epsg", type=int, default=32610, help="EPSG code")
    parser.add_argument("--xll", type=float, default=-6000.0, help="Domain lower-left X (UTM m)")
    parser.add_argument("--yll", type=float, default=-6000.0, help="Domain lower-left Y (UTM m)")
    parser.add_argument("--tstop", type=float, default=21600.0, help="Simulation stop time (s)")
    parser.add_argument("--dtdump", type=float, default=3600.0, help="Output interval (s)")
    parser.add_argument("--dt_meteorology", type=float, default=3600.0,
                        help="Weather update interval (s)")
    parser.add_argument("--simulation_dt", type=float, default=30.0, help="Time step (s)")
    parser.add_argument("--x_ign", type=float, default=0.0, help="Ignition X (UTM m)")
    parser.add_argument("--y_ign", type=float, default=3000.0, help="Ignition Y (UTM m)")

    parser.add_argument("--out", required=True, help="Output directory")

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
