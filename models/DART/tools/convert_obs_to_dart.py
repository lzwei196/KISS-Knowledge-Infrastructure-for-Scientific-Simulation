#!/usr/bin/env python3
"""
convert_obs_to_dart.py — Convert CSV observations to DART obs_seq text format.

CRITICAL:
  - DART obs error field is VARIANCE (sigma^2), NOT standard deviation.
    If you pass std dev, assimilation weights will be sqrt(sigma) wrong.
  - Longitude must be [0, 360] degrees. Negative longitudes (-180 to 0)
    must be converted by adding 360.
  - Pressure vertical coordinate must be in PASCALS, not hPa.
    Multiply hPa by 100.
  - Time is encoded as (days, seconds) from a reference calendar.
  - Missing data sentinel is -888888.0 (not NaN or -9999).

Output format: DART obs_seq ASCII file with header, copy metadata,
and observation records.

Usage:
  python convert_obs_to_dart.py \\
      --input observations.csv \\
      --output obs_seq.out \\
      --obs_type RAW_STATE_VARIABLE \\
      --error_variance 1.0 \\
      --location_type oned
  python convert_obs_to_dart.py \\
      --input weather_stations.csv \\
      --output obs_seq.out \\
      --obs_type RADIOSONDE_TEMPERATURE \\
      --error_variance 1.0 \\
      --location_type threed_sphere \\
      --vertical_coord pressure
"""

import argparse
import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


# DART observation type mapping (subset of common types)
OBS_TYPE_TABLE = {
    "RAW_STATE_VARIABLE": 1,
    "RAW_STATE_1D_INTEGRAL": 2,
    "RADIOSONDE_TEMPERATURE": 3,
    "RADIOSONDE_U_WIND_COMPONENT": 4,
    "RADIOSONDE_V_WIND_COMPONENT": 5,
    "RADIOSONDE_SPECIFIC_HUMIDITY": 6,
    "AIRCRAFT_TEMPERATURE": 7,
    "SAT_TEMPERATURE": 8,
    "LAND_SFC_TEMPERATURE": 9,
    "MARINE_SFC_TEMPERATURE": 10,
}

# DART vertical coordinate types
VERT_TYPES = {
    "undefined": -2,
    "surface": -1,
    "level": 1,
    "pressure": 2,
    "height": 3,
    "scale_height": 4,
}

# DART base date (day 0 = 1601-01-01 for Gregorian calendar)
DART_BASE_DATE = datetime(1601, 1, 1)


def validate_inputs(args):
    """Pre-processing validation of all inputs."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.obs_type not in OBS_TYPE_TABLE:
        errors.append(
            f"Unknown obs_type '{args.obs_type}'. "
            f"Valid types: {list(OBS_TYPE_TABLE.keys())}"
        )

    if args.error_variance <= 0:
        errors.append(
            f"error_variance must be > 0, got {args.error_variance}. "
            f"Remember: this is VARIANCE (sigma^2), not std dev."
        )

    if args.location_type not in ("oned", "threed_sphere", "threed_cartesian"):
        errors.append(
            f"Unknown location_type '{args.location_type}'. "
            f"Valid: oned, threed_sphere, threed_cartesian"
        )

    if args.location_type == "threed_sphere":
        if args.vertical_coord not in VERT_TYPES:
            errors.append(
                f"Unknown vertical_coord '{args.vertical_coord}'. "
                f"Valid: {list(VERT_TYPES.keys())}"
            )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def datetime_to_dart_time(dt):
    """Convert datetime to DART (days, seconds) tuple.

    DART uses a modified Gregorian calendar with day 0 = 1601-01-01.
    """
    delta = dt - DART_BASE_DATE
    days = delta.days
    seconds = delta.seconds
    return days, seconds


def normalize_longitude(lon):
    """Convert longitude to [0, 360] range.

    CRITICAL: DART stores longitude in [0, 360] degrees internally
    (converted to radians). Negative longitudes cause location errors.
    """
    lon = np.asarray(lon, dtype=float)
    lon = np.where(lon < 0, lon + 360.0, lon)
    return lon


def pressure_hpa_to_pa(p_hpa):
    """Convert pressure from hPa (millibars) to Pascals.

    CRITICAL: DART vertical coordinate uses PASCALS.
    1 hPa = 100 Pa. Forgetting this conversion causes wrong
    vertical localization — observations at 500 hPa would be
    treated as 500 Pa (near top of atmosphere).
    """
    return np.asarray(p_hpa, dtype=float) * 100.0


def write_obs_seq_header(f, num_copies, num_qc, num_obs, obs_type_table):
    """Write obs_seq ASCII file header."""
    f.write(" obs_sequence\n")
    f.write("obs_kind_definitions\n")
    f.write(f"           {len(obs_type_table)}\n")
    for name, code in obs_type_table.items():
        f.write(f"          {code} {name}\n")
    f.write(f"  num_copies:            {num_copies}  num_qc:            {num_qc}\n")
    f.write(f"  num_obs:       {num_obs}  max_num_obs:       {num_obs}\n")


def write_obs_record_oned(f, key, value, error_var, obs_type_code, location,
                          days, seconds, prev_key, next_key):
    """Write a single observation record for 1D location."""
    f.write(f" OBS            {key}\n")
    f.write(f"   {value:20.14E}\n")  # observation value
    f.write(f"   {0.0:20.14E}\n")     # QC value
    f.write(f" obdef\n")
    f.write(f"loc1d\n")
    f.write(f"    {location:20.14E}\n")
    f.write(f"kind\n")
    f.write(f"          {obs_type_code}\n")
    f.write(f"    {seconds}     {days}\n")  # seconds then days
    f.write(f"    {error_var:20.14E}\n")    # error VARIANCE
    f.write(f"  {prev_key}          {next_key}          -1\n")


def write_obs_record_3dsphere(f, key, value, error_var, obs_type_code,
                              lon_rad, lat_rad, vloc, which_vert,
                              days, seconds, prev_key, next_key):
    """Write a single observation record for 3D sphere location."""
    f.write(f" OBS            {key}\n")
    f.write(f"   {value:20.14E}\n")
    f.write(f"   {0.0:20.14E}\n")
    f.write(f" obdef\n")
    f.write(f"loc3d\n")
    f.write(f"     {lon_rad:20.14E}     {lat_rad:20.14E}     {vloc:20.14E}     {which_vert}\n")
    f.write(f"kind\n")
    f.write(f"          {obs_type_code}\n")
    f.write(f"    {seconds}     {days}\n")
    f.write(f"    {error_var:20.14E}\n")
    f.write(f"  {prev_key}          {next_key}          -1\n")


def process(args):
    """Read CSV and convert to DART obs_seq records."""
    df = pd.read_csv(args.input)

    required_cols = ["time", "value"]
    for col in required_cols:
        if col not in df.columns:
            print(json.dumps({
                "status": "error",
                "errors": [f"Required column '{col}' not found in CSV. "
                           f"Available: {list(df.columns)}"]
            }), file=sys.stderr)
            sys.exit(1)

    # Parse times
    df["time"] = pd.to_datetime(df["time"])

    # Replace NaN/missing with DART sentinel
    df["value"] = df["value"].fillna(-888888.0)

    # Handle location columns
    if args.location_type == "oned":
        if "location" not in df.columns:
            # Default: evenly spaced on [0, 1)
            df["location"] = np.linspace(0, 1, len(df), endpoint=False)
    elif args.location_type == "threed_sphere":
        for col in ["lon", "lat"]:
            if col not in df.columns:
                print(json.dumps({
                    "status": "error",
                    "errors": [f"Column '{col}' required for threed_sphere"]
                }), file=sys.stderr)
                sys.exit(1)
        df["lon"] = normalize_longitude(df["lon"])
        if "vertical" not in df.columns:
            df["vertical"] = 0.0

    return df


def validate_outputs(df, args):
    """Post-processing validation of converted observations."""
    warnings = []

    # Check for all-missing observations
    valid_count = (df["value"] != -888888.0).sum()
    if valid_count == 0:
        warnings.append("CRITICAL: All observation values are missing (-888888.0)")

    # Check value ranges for known types
    if "TEMPERATURE" in args.obs_type:
        temp_max = df.loc[df["value"] != -888888.0, "value"].max()
        temp_min = df.loc[df["value"] != -888888.0, "value"].min()
        if temp_max < 100:
            warnings.append(
                f"WARNING: Temperature max={temp_max:.1f} — "
                f"likely in Celsius. DART models typically use Kelvin."
            )

    # Check location bounds for 3D sphere
    if args.location_type == "threed_sphere":
        lon_min, lon_max = df["lon"].min(), df["lon"].max()
        if lon_min < 0 or lon_max > 360:
            warnings.append(
                f"CRITICAL: Longitude range [{lon_min:.1f}, {lon_max:.1f}] "
                f"outside [0, 360]. DART will misplace observations."
            )
        lat_min, lat_max = df["lat"].min(), df["lat"].max()
        if lat_min < -90 or lat_max > 90:
            warnings.append(
                f"CRITICAL: Latitude range [{lat_min:.1f}, {lat_max:.1f}] "
                f"outside [-90, 90]."
            )
        if args.vertical_coord == "pressure":
            p_max = df["vertical"].max()
            if p_max < 2000:
                warnings.append(
                    f"CRITICAL: Pressure max={p_max:.0f} — "
                    f"likely in hPa, not Pa. Multiply by 100."
                )

    # Check error variance magnitude
    if args.error_variance < 0.001:
        warnings.append(
            f"WARNING: error_variance={args.error_variance} is very small. "
            f"Did you pass std dev instead of variance?"
        )

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert CSV observations to DART obs_seq text format"
    )
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--output", required=True, help="Output obs_seq file path")
    parser.add_argument("--obs_type", required=True,
                        help=f"Observation type: {list(OBS_TYPE_TABLE.keys())}")
    parser.add_argument("--error_variance", type=float, required=True,
                        help="Observation error VARIANCE (sigma^2, NOT std dev)")
    parser.add_argument("--location_type", default="oned",
                        help="Location module: oned, threed_sphere, threed_cartesian")
    parser.add_argument("--vertical_coord", default="undefined",
                        help="Vertical coordinate: undefined, surface, level, pressure, height")
    parser.add_argument("--pressure_in_hpa", action="store_true",
                        help="Convert pressure column from hPa to Pa")

    args = parser.parse_args()

    # Step 1: validate inputs
    validate_inputs(args)

    # Step 2: process
    df = process(args)

    # Step 3: validate outputs
    warnings = validate_outputs(df, args)

    # Step 4: write obs_seq file
    obs_type_code = OBS_TYPE_TABLE[args.obs_type]
    used_types = {args.obs_type: obs_type_code}
    num_obs = len(df)

    with open(args.output, "w") as f:
        write_obs_seq_header(f, num_copies=1, num_qc=1,
                             num_obs=num_obs, obs_type_table=used_types)
        f.write("observations\n")
        f.write("Quality Control\n")

        if num_obs > 0:
            f.write(f"  first:            1  last:       {num_obs}\n")
        else:
            f.write("  first:           -1  last:          -1\n")

        for i, row in df.iterrows():
            key = i + 1
            prev_key = key - 1 if key > 1 else -1
            next_key = key + 1 if key < num_obs else -1
            days, seconds = datetime_to_dart_time(row["time"])

            if args.location_type == "oned":
                write_obs_record_oned(
                    f, key, row["value"], args.error_variance,
                    obs_type_code, row["location"],
                    days, seconds, prev_key, next_key
                )
            elif args.location_type == "threed_sphere":
                lon_rad = np.deg2rad(row["lon"])
                lat_rad = np.deg2rad(row["lat"])
                vloc = row["vertical"]
                if args.vertical_coord == "pressure" and args.pressure_in_hpa:
                    vloc = vloc * 100.0
                which_vert = VERT_TYPES.get(args.vertical_coord, -2)
                write_obs_record_3dsphere(
                    f, key, row["value"], args.error_variance,
                    obs_type_code, lon_rad, lat_rad, vloc, which_vert,
                    days, seconds, prev_key, next_key
                )

    # Step 5: report
    result = {
        "status": "success",
        "output_file": args.output,
        "num_obs": num_obs,
        "obs_type": args.obs_type,
        "error_variance": args.error_variance,
        "location_type": args.location_type,
        "date_range": f"{df['time'].iloc[0]} to {df['time'].iloc[-1]}" if num_obs > 0 else "N/A",
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2), file=sys.stderr)
    print(f"Wrote {num_obs} observations to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
