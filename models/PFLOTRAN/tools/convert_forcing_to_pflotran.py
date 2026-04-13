#!/usr/bin/env python3
"""
convert_forcing_to_pflotran.py — Convert global forcing data to PFLOTRAN boundary conditions.

Converts precipitation/recharge data from global datasets (CMFD, ERA5, MSWX)
to PFLOTRAN-compatible boundary condition format. Handles critical unit
conversions from meteorological units (mm/day, mm/yr) to PFLOTRAN's internal
SI units (m/s).

Inputs:
    --forcing-file   : NetCDF or CSV with precipitation/recharge time series
    --source-type    : Data source type (cmfd, era5, mswx, csv)
    --lat / --lon    : Target location for spatial extraction
    --infiltration-fraction : Fraction of precip that becomes recharge (0-1)
    --output         : Output CSV path for PFLOTRAN FLOW_CONDITION dataset

Outputs:
    CSV file with columns: time_s, recharge_m_per_s
    Suitable for use in PFLOTRAN FLOW_CONDITION with LIQUID_FLUX NEUMANN type.

Unit Conversions (CRITICAL):
    - mm/day   → m/s : multiply by 1.1574074e-8
    - mm/yr    → m/s : multiply by 3.1710e-11
    - mm/3hr   → m/s : multiply by 9.2593e-8
    - m/day    → m/s : multiply by 1.1574074e-5

Usage:
    python convert_forcing_to_pflotran.py \\
        --forcing-file /data/forcing/Data_forcing_01dy_010deg/prec_CMFD_V0106_B-01_01dy_010deg_2001.nc \\
        --source-type cmfd \\
        --lat 32.9 --lon 117.3 \\
        --infiltration-fraction 0.15 \\
        --output recharge_bengbu.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import CMFD_PRECIP_KGM2S_TO_MMDAY

# ──────────────────────────────────────────────────────────────────────
# Unit conversion constants
# ──────────────────────────────────────────────────────────────────────
MM_PER_DAY_TO_M_PER_S = 1.0 / (1000.0 * CMFD_PRECIP_KGM2S_TO_MMDAY)   # 1.1574e-8
MM_PER_YR_TO_M_PER_S = 1.0 / (1000.0 * 3.15576e7)   # 3.171e-11
MM_PER_3HR_TO_M_PER_S = 1.0 / (1000.0 * 10800.0)    # 9.259e-8
M_PER_DAY_TO_M_PER_S = 1.0 / 86400.0                 # 1.1574e-5
SECONDS_PER_DAY = 86400.0
SECONDS_PER_YEAR = 3.15576e7


def validate_inputs(args):
    """Validate all input parameters before processing.

    Returns:
        dict with 'valid' (bool) and 'errors' (list of str)
    """
    errors = []

    if not os.path.isfile(args.forcing_file):
        errors.append(f"Forcing file not found: {args.forcing_file}")

    if args.source_type not in ("cmfd", "era5", "mswx", "csv"):
        errors.append(f"Unknown source type: {args.source_type}")

    if not (-90 <= args.lat <= 90):
        errors.append(f"Latitude out of range: {args.lat}")
    if not (-180 <= args.lon <= 360):
        errors.append(f"Longitude out of range: {args.lon}")

    if not (0 < args.infiltration_fraction <= 1.0):
        errors.append(
            f"Infiltration fraction must be in (0, 1]: {args.infiltration_fraction}"
        )

    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "errors": []}


def read_cmfd_precipitation(filepath, lat, lon):
    """Read CMFD precipitation NetCDF and extract nearest-grid time series.

    CMFD precipitation is in mm/day (daily) or mm/3hr (3-hourly).

    Returns:
        times: list of datetime objects
        precip_mm_per_day: numpy array of precipitation in mm/day
    """
    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required. Install with: pip install netCDF4")
        sys.exit(1)

    ds = nc.Dataset(filepath, "r")

    # CMFD variable names
    lat_var = ds.variables.get("latitude") or ds.variables.get("lat")
    lon_var = ds.variables.get("longitude") or ds.variables.get("lon")
    prec_var = ds.variables.get("prec") or ds.variables.get("precipitation")

    if prec_var is None:
        # Try common CMFD names
        for name in ["prcp", "pre", "tp", "PREC"]:
            if name in ds.variables:
                prec_var = ds.variables[name]
                break

    if prec_var is None:
        raise ValueError(f"No precipitation variable found in {filepath}")

    lats = lat_var[:]
    lons = lon_var[:]

    # Find nearest grid point
    lat_idx = int(np.argmin(np.abs(lats - lat)))
    lon_idx = int(np.argmin(np.abs(lons - lon)))

    dist_km = np.sqrt(
        ((lats[lat_idx] - lat) * 111.0) ** 2
        + ((lons[lon_idx] - lon) * 111.0 * np.cos(np.radians(lat))) ** 2
    )
    if dist_km > 20:
        print(f"WARNING: Nearest grid point is {dist_km:.1f} km from target")

    # Extract time
    time_var = ds.variables["time"]
    times = nc.num2date(time_var[:], time_var.units, time_var.calendar)

    # Extract precipitation
    precip = prec_var[:, lat_idx, lon_idx]
    precip = np.array(precip, dtype=float)

    # Determine if 3-hourly or daily from time steps
    if len(times) > 1:
        dt_hours = (times[1] - times[0]).total_seconds() / 3600
        if dt_hours < 12:  # 3-hourly
            # Convert mm/3hr to mm/day for consistency
            precip = precip * (24.0 / dt_hours)
            print(f"  Detected {dt_hours:.0f}-hourly data, converted to mm/day")
        else:
            print("  Detected daily data (mm/day)")

    ds.close()

    return [t for t in times], precip


def read_era5_precipitation(filepath, lat, lon):
    """Read ERA5 precipitation (m/timestep cumulative) and convert to mm/day."""
    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required.")
        sys.exit(1)

    ds = nc.Dataset(filepath, "r")

    lats = ds.variables["latitude"][:]
    lons = ds.variables["longitude"][:]
    lat_idx = int(np.argmin(np.abs(lats - lat)))
    lon_idx = int(np.argmin(np.abs(lons - lon)))

    time_var = ds.variables["time"]
    times = nc.num2date(time_var[:], time_var.units)

    # ERA5 'tp' is in meters per hour (cumulative). Convert to mm/day.
    tp = ds.variables["tp"][:, lat_idx, lon_idx]
    tp = np.array(tp, dtype=float)
    precip_mm_day = tp * 1000.0 * 24.0  # m/hr → mm/day

    ds.close()
    return [t for t in times], precip_mm_day


def read_csv_forcing(filepath):
    """Read CSV with columns: date, precip_mm_day.

    Expected format:
        date,precip_mm_day
        2001-01-01,2.5
        2001-01-02,0.0
        ...
    """
    times = []
    precip = []

    with open(filepath, "r") as f:
        header = f.readline().strip()
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= 2:
                times.append(datetime.strptime(parts[0].strip(), "%Y-%m-%d"))
                precip.append(float(parts[1].strip()))

    return times, np.array(precip)


def convert_to_pflotran_recharge(times, precip_mm_day, infiltration_fraction,
                                  reference_time=None):
    """Convert precipitation (mm/day) to PFLOTRAN recharge (m/s).

    CRITICAL UNIT CONVERSION:
        recharge (m/s) = precip (mm/day) * infiltration_fraction * 1.1574e-8

    Args:
        times: list of datetime
        precip_mm_day: numpy array in mm/day
        infiltration_fraction: fraction of precip becoming recharge (0-1)
        reference_time: datetime for t=0 (defaults to first time)

    Returns:
        time_seconds: numpy array of elapsed seconds from reference
        recharge_m_s: numpy array of recharge in m/s
    """
    if reference_time is None:
        reference_time = times[0]

    time_seconds = np.array([
        (t - reference_time).total_seconds() for t in times
    ])

    # CRITICAL: mm/day → m/s conversion
    recharge_m_s = precip_mm_day * infiltration_fraction * MM_PER_DAY_TO_M_PER_S

    return time_seconds, recharge_m_s


def validate_outputs(time_seconds, recharge_m_s):
    """Validate output recharge values are physically reasonable.

    Returns:
        dict with 'valid' (bool), 'warnings' (list), 'stats' (dict)
    """
    warnings = []
    stats = {
        "n_timesteps": len(time_seconds),
        "duration_years": float(time_seconds[-1] / SECONDS_PER_YEAR) if len(time_seconds) > 0 else 0,
        "mean_recharge_mm_yr": float(np.mean(recharge_m_s) / MM_PER_YR_TO_M_PER_S),
        "max_recharge_mm_yr": float(np.max(recharge_m_s) / MM_PER_YR_TO_M_PER_S),
        "min_recharge_mm_yr": float(np.min(recharge_m_s) / MM_PER_YR_TO_M_PER_S),
    }

    # Check for NaN
    nan_count = int(np.sum(np.isnan(recharge_m_s)))
    if nan_count > 0:
        warnings.append(f"Found {nan_count} NaN values in recharge")

    # Check for negative values
    neg_count = int(np.sum(recharge_m_s < 0))
    if neg_count > 0:
        warnings.append(f"Found {neg_count} negative recharge values (discharge)")

    # Check magnitude: recharge > 10000 mm/yr is suspicious
    if stats["max_recharge_mm_yr"] > 10000:
        warnings.append(
            f"Max recharge {stats['max_recharge_mm_yr']:.0f} mm/yr seems too high — "
            "check unit conversion (did you forget to convert mm/day to m/s?)"
        )

    # Check if recharge is zero everywhere
    if np.all(recharge_m_s == 0):
        warnings.append("All recharge values are zero — check input data")

    # Check for unit error: if mean > 1e-4 m/s, likely mm/day not converted
    if np.mean(recharge_m_s) > 1e-4:
        warnings.append(
            "UNIT ERROR DETECTED: Mean recharge > 1e-4 m/s "
            "(~3000 m/yr). Values appear to be in mm/day not m/s."
        )

    valid = len(warnings) == 0 or all("WARNING" not in w for w in warnings)
    return {"valid": valid, "warnings": warnings, "stats": stats}


def write_pflotran_dataset(output_path, time_seconds, recharge_m_s):
    """Write PFLOTRAN-compatible dataset CSV.

    Format:
        time_s,recharge_m_per_s
        0.0,3.17e-09
        86400.0,5.21e-09
        ...

    This file can be referenced in PFLOTRAN input via:
        FLOW_CONDITION recharge
          TYPE
            LIQUID_FLUX NEUMANN
          /
          LIQUID_FLUX FILE recharge.csv
        END
    """
    with open(output_path, "w") as f:
        for t, r in zip(time_seconds, recharge_m_s):
            f.write(f"{t:.1f} {r:.6e}\n")

    print(f"  Written {len(time_seconds)} timesteps to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to PFLOTRAN recharge boundary conditions"
    )
    parser.add_argument("--forcing-file", required=True, help="Path to forcing data")
    parser.add_argument(
        "--source-type",
        required=True,
        choices=["cmfd", "era5", "mswx", "csv"],
        help="Data source type",
    )
    parser.add_argument("--lat", type=float, required=True, help="Target latitude")
    parser.add_argument("--lon", type=float, required=True, help="Target longitude")
    parser.add_argument(
        "--infiltration-fraction",
        type=float,
        default=0.15,
        help="Fraction of precipitation that becomes recharge (default: 0.15)",
    )
    parser.add_argument("--output", required=True, help="Output CSV path")

    args = parser.parse_args()

    print("=" * 60)
    print("PFLOTRAN Forcing Converter")
    print("=" * 60)

    # Step 1: Validate inputs
    print("\n[1/4] Validating inputs...")
    validation = validate_inputs(args)
    if not validation["valid"]:
        for err in validation["errors"]:
            print(f"  ERROR: {err}")
        sys.exit(1)
    print("  All inputs valid.")

    # Step 2: Read forcing data
    print(f"\n[2/4] Reading {args.source_type} forcing data...")
    if args.source_type == "cmfd":
        times, precip_mm_day = read_cmfd_precipitation(
            args.forcing_file, args.lat, args.lon
        )
    elif args.source_type == "era5":
        times, precip_mm_day = read_era5_precipitation(
            args.forcing_file, args.lat, args.lon
        )
    elif args.source_type == "csv":
        times, precip_mm_day = read_csv_forcing(args.forcing_file)
    else:
        print(f"  MSWX reader not yet implemented, use CSV export")
        sys.exit(1)

    print(f"  Read {len(times)} timesteps")
    print(f"  Precip range: {np.min(precip_mm_day):.2f} – {np.max(precip_mm_day):.2f} mm/day")
    print(f"  Precip mean: {np.mean(precip_mm_day):.2f} mm/day")

    # Step 3: Convert to PFLOTRAN recharge
    print(f"\n[3/4] Converting to PFLOTRAN recharge (infiltration fraction = {args.infiltration_fraction})...")
    time_s, recharge_m_s = convert_to_pflotran_recharge(
        times, precip_mm_day, args.infiltration_fraction
    )
    print(f"  Recharge range: {np.min(recharge_m_s):.3e} – {np.max(recharge_m_s):.3e} m/s")
    print(f"  Recharge mean: {np.mean(recharge_m_s):.3e} m/s = "
          f"{np.mean(recharge_m_s) / MM_PER_YR_TO_M_PER_S:.1f} mm/yr")

    # Step 4: Validate and write output
    print("\n[4/4] Validating outputs...")
    result = validate_outputs(time_s, recharge_m_s)
    for w in result["warnings"]:
        print(f"  WARNING: {w}")
    print(f"  Stats: {json.dumps(result['stats'], indent=4)}")

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    write_pflotran_dataset(args.output, time_s, recharge_m_s)

    print("\nDone.")


if __name__ == "__main__":
    main()
