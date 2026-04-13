#!/usr/bin/env python3
"""
convert_lsm_to_vlat.py — Convert LSM runoff to RAPID lateral inflow (Vlat) NetCDF.

RAPID expects lateral inflow as accumulated volume (m³) over the routing period
(ZS_TauR), stored in a NetCDF variable named 'Vlat' with dimensions (time, rivid).

Supported LSM formats:
  - VIC: ASCII or NetCDF runoff (mm/time_step) on grid cells
  - GLDAS: NetCDF runoff (kg/m²/s) on 0.25° grid
  - Generic: NetCDF with runoff variable in kg/m²/s or mm/s

CRITICAL UNIT TRAP:
  - RAPID Vlat is VOLUME (m³), not rate (m³/s)
  - If you pass m³/s as Vlat, RAPID divides by TauR again → discharge ~10800× too small
  - Conversion: Vlat_m3 = runoff_kg_m2_s × catch_area_m2 × TauR_s

Usage:
  python convert_lsm_to_vlat.py \\
    --runoff_nc /path/to/lsm_runoff.nc \\
    --runoff_var Qs_acc \\
    --runoff_units kg/m2/s \\
    --catchment_file /path/to/rapid_catchment_file.csv \\
    --connectivity /path/to/rapid_connect.csv \\
    --riv_bas_id /path/to/riv_bas_id.csv \\
    --tau_r 10800 \\
    --output /path/to/Vlat.nc
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import netCDF4 as nc
import numpy as np


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Check all inputs exist and parameters are physically reasonable."""
    errors = []

    if not os.path.isfile(args.runoff_nc):
        errors.append(f"Runoff file not found: {args.runoff_nc}")

    if args.catchment_file and not os.path.isfile(args.catchment_file):
        errors.append(f"Catchment file not found: {args.catchment_file}")

    if not os.path.isfile(args.riv_bas_id):
        errors.append(f"riv_bas_id file not found: {args.riv_bas_id}")

    if args.tau_r <= 0:
        errors.append(f"ZS_TauR must be positive, got {args.tau_r}")

    if args.tau_r < 60:
        errors.append(f"ZS_TauR = {args.tau_r}s is suspiciously small — did you pass minutes instead of seconds?")

    valid_units = ["kg/m2/s", "mm/s", "mm/day", "mm/3hr", "m3/s", "m3"]
    if args.runoff_units not in valid_units:
        errors.append(f"Unrecognized runoff_units '{args.runoff_units}'. Expected one of: {valid_units}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Warnings
    if args.runoff_units == "m3/s":
        print("WARNING: runoff_units='m3/s' — will multiply by TauR to get m³ volume. "
              "Make sure this is per-reach runoff rate, not grid-cell rate.",
              file=sys.stderr)

    if args.runoff_units == "m3":
        print("WARNING: runoff_units='m3' — assuming input is already volume. "
              "No unit conversion applied.",
              file=sys.stderr)


def validate_outputs(vlat_data, riv_ids, tau_r):
    """Post-processing validation of the generated Vlat array."""
    warnings = []
    n_time, n_riv = vlat_data.shape

    # Check for NaN
    nan_count = np.isnan(vlat_data).sum()
    if nan_count > 0:
        warnings.append(f"Vlat contains {nan_count} NaN values — check runoff input coverage")

    # Check for negative values
    neg_count = (vlat_data < 0).sum()
    if neg_count > 0:
        warnings.append(f"Vlat contains {neg_count} negative values — physically impossible for runoff")

    # Check magnitude: Vlat in m³ per TauR period
    max_vlat = np.nanmax(vlat_data)
    if max_vlat > 1e9:
        warnings.append(f"Max Vlat = {max_vlat:.2e} m³ — suspiciously large, check unit conversion")

    # Equivalent peak rate for sanity
    peak_rate_m3s = max_vlat / tau_r
    if peak_rate_m3s > 1e5:
        warnings.append(f"Peak equivalent rate = {peak_rate_m3s:.1f} m³/s — "
                        "exceeds 100,000 m³/s, only plausible for Amazon-scale rivers")

    # Check for all-zero reaches
    zero_reaches = np.where(np.nanmax(vlat_data, axis=0) == 0)[0]
    if len(zero_reaches) > n_riv * 0.5:
        warnings.append(f"{len(zero_reaches)}/{n_riv} reaches have zero Vlat — "
                        "check spatial mapping between LSM grid and catchments")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return {"n_time": n_time, "n_riv": n_riv, "max_vlat_m3": float(max_vlat),
            "nan_count": int(nan_count), "warnings": warnings}


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------

def convert_runoff_to_vlat_m3(runoff, units, catch_area_m2, tau_r_s):
    """
    Convert runoff in various units to Vlat in m³ (volume over TauR period).

    Parameters
    ----------
    runoff : np.ndarray, shape (n_time, n_riv)
        Runoff values in source units.
    units : str
        One of: kg/m2/s, mm/s, mm/day, mm/3hr, m3/s, m3
    catch_area_m2 : np.ndarray, shape (n_riv,)
        Catchment area for each reach in m².
    tau_r_s : float
        Routing period ZS_TauR in seconds.

    Returns
    -------
    vlat : np.ndarray, shape (n_time, n_riv)
        Lateral inflow volume in m³ per TauR period.
    """
    if units == "kg/m2/s":
        # kg/m²/s = mm/s for water (density ≈ 1000 kg/m³)
        # Vlat = runoff_kg_m2_s × area_m2 × TauR_s / 1000
        # The /1000 converts mm to m: (kg/m²/s) × m² × s = kg/s × s = kg = 1e-3 m³
        # Actually: kg/m²/s × m² × s = kg. Then kg / 1000 kg/m³ = m³
        vlat = runoff * catch_area_m2[np.newaxis, :] * tau_r_s / 1000.0

    elif units == "mm/s":
        # mm/s × area_m² × TauR_s / 1000 (mm→m)
        vlat = runoff * catch_area_m2[np.newaxis, :] * tau_r_s / 1000.0

    elif units == "mm/day":
        # mm/day → mm/s: ÷ 86400
        # Then same as mm/s
        vlat = runoff / 86400.0 * catch_area_m2[np.newaxis, :] * tau_r_s / 1000.0

    elif units == "mm/3hr":
        # mm/3hr → mm/s: ÷ 10800
        vlat = runoff / 10800.0 * catch_area_m2[np.newaxis, :] * tau_r_s / 1000.0

    elif units == "m3/s":
        # Rate → volume: × TauR
        vlat = runoff * tau_r_s

    elif units == "m3":
        # Already volume
        vlat = runoff.copy()

    else:
        raise ValueError(f"Unsupported units: {units}")

    return vlat


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def read_riv_bas_id(filepath):
    """Read reach IDs from riv_bas_id CSV (one ID per line)."""
    ids = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                ids.append(int(line))
    return np.array(ids)


def read_catchment_areas(filepath, riv_ids):
    """
    Read catchment areas from CSV: reach_id, area_m2
    Returns array aligned with riv_ids ordering.
    """
    area_dict = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split()
                if len(parts) >= 2:
                    area_dict[int(parts[0])] = float(parts[1])

    areas = np.zeros(len(riv_ids))
    for i, rid in enumerate(riv_ids):
        if rid in area_dict:
            areas[i] = area_dict[rid]
        else:
            print(f"WARNING: No catchment area for reach {rid}, using 0", file=sys.stderr)
    return areas


def read_runoff_netcdf(filepath, var_name, n_riv):
    """Read runoff from NetCDF. Returns (data, times) arrays."""
    ds = nc.Dataset(filepath, "r")

    if var_name not in ds.variables:
        available = list(ds.variables.keys())
        ds.close()
        raise KeyError(f"Variable '{var_name}' not in {filepath}. Available: {available}")

    data = ds.variables[var_name][:]
    if data.ndim == 1:
        data = data.reshape(1, -1)

    # Try to read time
    times = None
    if "time" in ds.variables:
        times = nc.num2date(ds.variables["time"][:],
                            ds.variables["time"].units,
                            ds.variables["time"].calendar
                            if hasattr(ds.variables["time"], "calendar") else "standard")

    ds.close()
    return np.array(data, dtype=np.float64), times


def write_vlat_netcdf(filepath, vlat, riv_ids, times, tau_r):
    """Write Vlat NetCDF in RAPID-expected format."""
    n_time, n_riv = vlat.shape

    ds = nc.Dataset(filepath, "w", format="NETCDF4")

    # Dimensions
    ds.createDimension("rivid", n_riv)
    ds.createDimension("time", None)  # unlimited

    # rivid variable
    v_riv = ds.createVariable("rivid", "i4", ("rivid",))
    v_riv[:] = riv_ids
    v_riv.long_name = "unique identifier for each river reach"
    v_riv.units = "1"

    # time variable
    v_time = ds.createVariable("time", "f8", ("time",))
    v_time.units = "seconds since 2000-01-01 00:00:00"
    v_time.calendar = "standard"
    if times is not None:
        ref = datetime(2000, 1, 1)
        v_time[:] = np.array([(t - ref).total_seconds() for t in times])
    else:
        v_time[:] = np.arange(n_time) * tau_r

    # Vlat variable
    v_vlat = ds.createVariable("Vlat", "f4", ("time", "rivid"),
                                fill_value=-9999.0)
    v_vlat[:] = vlat
    v_vlat.long_name = "lateral inflow volume"
    v_vlat.units = "m3"

    # Global attributes
    ds.Conventions = "CF-1.6"
    ds.history = f"Created by convert_lsm_to_vlat.py on {datetime.now().isoformat()}"
    ds.featureType = "timeSeries"

    ds.close()
    print(f"Wrote {filepath}: {n_time} time steps, {n_riv} reaches")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Main processing pipeline: validate → convert → write → validate."""
    # Read inputs
    riv_ids = read_riv_bas_id(args.riv_bas_id)
    n_riv = len(riv_ids)
    print(f"Read {n_riv} reach IDs from {args.riv_bas_id}")

    # Read catchment areas
    if args.catchment_file:
        catch_area = read_catchment_areas(args.catchment_file, riv_ids)
    else:
        # If no catchment file, assume 1 m² (user must provide m³ or m³/s)
        catch_area = np.ones(n_riv)
        if args.runoff_units not in ("m3/s", "m3"):
            print("ERROR: --catchment_file required when runoff_units is area-based",
                  file=sys.stderr)
            sys.exit(1)

    # Read runoff
    runoff, times = read_runoff_netcdf(args.runoff_nc, args.runoff_var, n_riv)
    print(f"Read runoff: shape={runoff.shape}, units={args.runoff_units}")

    # Convert to Vlat (m³)
    vlat = convert_runoff_to_vlat_m3(runoff, args.runoff_units, catch_area, args.tau_r)

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    write_vlat_netcdf(args.output, vlat, riv_ids, times, args.tau_r)

    # Validate output
    report = validate_outputs(vlat, riv_ids, args.tau_r)
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Convert LSM runoff to RAPID Vlat NetCDF (lateral inflow volume in m³)")
    parser.add_argument("--runoff_nc", required=True, help="Path to LSM runoff NetCDF")
    parser.add_argument("--runoff_var", default="Runoff", help="NetCDF variable name for runoff")
    parser.add_argument("--runoff_units", required=True,
                        choices=["kg/m2/s", "mm/s", "mm/day", "mm/3hr", "m3/s", "m3"],
                        help="Units of the runoff variable")
    parser.add_argument("--catchment_file", default=None,
                        help="CSV with reach_id and catchment_area_m2")
    parser.add_argument("--riv_bas_id", required=True,
                        help="RAPID riv_bas_id file (one reach ID per line)")
    parser.add_argument("--connectivity", default=None,
                        help="RAPID rapid_connect file (for validation only)")
    parser.add_argument("--tau_r", type=float, default=10800,
                        help="Routing period ZS_TauR in seconds (default: 10800 = 3hr)")
    parser.add_argument("--output", required=True, help="Output Vlat NetCDF path")
    args = parser.parse_args()

    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
