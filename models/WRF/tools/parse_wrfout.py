#!/usr/bin/env python3
"""
parse_wrfout.py - Extract variables from WRF output (wrfout) NetCDF files to CSV.

Reads wrfout_d0N_YYYY-MM-DD_HH:MM:SS files and extracts time series of selected
variables at specified locations, or spatial fields at specified times.

Pipeline stage: S7 (Output Extraction & Analysis)
Pattern: validate -> process -> validate

Usage:
    # Extract time series at a point
    python parse_wrfout.py \
        --input /path/to/wrfout_d01_* \
        --output /path/to/output.csv \
        --mode timeseries \
        --lat 32.5 --lon 117.0 \
        --variables T2,PSFC,RAINC,RAINNC,U10,V10

    # Extract spatial field at a time
    python parse_wrfout.py \
        --input /path/to/wrfout_d01_2020-06-15_12:00:00 \
        --output /path/to/field.csv \
        --mode spatial \
        --variables T2
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Variable metadata: name -> (description, units, post-processing notes)
# ---------------------------------------------------------------------------
WRF_OUTPUT_VARIABLES = {
    # 2D surface variables
    "T2":       ("2-m Temperature", "K", "Direct output; subtract 273.15 for Celsius"),
    "Q2":       ("2-m Specific Humidity", "kg kg-1", "Multiply by 1000 for g/kg"),
    "PSFC":     ("Surface Pressure", "Pa", "Divide by 100 for hPa"),
    "U10":      ("10-m U-wind", "m s-1", "Grid-relative; see note on rotation"),
    "V10":      ("10-m V-wind", "m s-1", "Grid-relative; see note on rotation"),
    "TSK":      ("Skin Temperature", "K", "Land surface skin temperature"),
    "RAINC":    ("Cumulus Precip", "mm", "Accumulated from start; need diff for rate"),
    "RAINNC":   ("Grid-scale Precip", "mm", "Accumulated from start; need diff for rate"),
    "SWDOWN":   ("Downward SW Radiation", "W m-2", "Instantaneous at output time"),
    "GLW":      ("Downward LW Radiation", "W m-2", "Instantaneous"),
    "HFX":      ("Sensible Heat Flux", "W m-2", "Positive upward"),
    "LH":       ("Latent Heat Flux", "W m-2", "Positive upward"),
    "PBLH":     ("PBL Height", "m", "Diagnosed by PBL scheme"),
    "SNOWH":    ("Snow Depth", "m", "Physical snow depth"),
    "SNOW":     ("Snow Water Equivalent", "kg m-2", "SWE"),
    "SST":      ("Sea Surface Temperature", "K", "Only over water"),
    # 3D variables
    "T":        ("Perturbation Potential Temp", "K", "ADD 300 for full theta!"),
    "U":        ("U-wind (staggered)", "m s-1", "Staggered on X-face"),
    "V":        ("V-wind (staggered)", "m s-1", "Staggered on Y-face"),
    "W":        ("Vertical velocity", "m s-1", "Staggered on Z-face"),
    "QVAPOR":   ("Water Vapor Mixing Ratio", "kg kg-1", ""),
    "QCLOUD":   ("Cloud Water Mixing Ratio", "kg kg-1", ""),
    "QRAIN":    ("Rain Water Mixing Ratio", "kg kg-1", ""),
    "P":        ("Perturbation Pressure", "Pa", "Add PB for full pressure"),
    "PB":       ("Base-state Pressure", "Pa", ""),
    "PH":       ("Pert. Geopotential", "m2 s-2", "Staggered Z; add PHB"),
    "PHB":      ("Base Geopotential", "m2 s-2", ""),
}

# Derived variables that require computation
DERIVED_VARIABLES = {
    "WIND10":   ("10-m Wind Speed", "m s-1", "sqrt(U10^2 + V10^2)"),
    "TOTAL_PRECIP": ("Total Precipitation", "mm", "RAINC + RAINNC"),
    "PRECIP_RATE":  ("Precipitation Rate", "mm hr-1", "diff(RAINC+RAINNC)/dt"),
    "T2C":      ("2-m Temperature", "C", "T2 - 273.15"),
    "RH2":      ("2-m Relative Humidity", "%", "From T2, Q2, PSFC"),
    "THETA":    ("Full Potential Temperature", "K", "T + 300"),
    "PRESSURE": ("Full Pressure", "Pa", "P + PB"),
    "HEIGHT":   ("Geopotential Height", "m", "(PH + PHB) / 9.81"),
    "TEMP":     ("Actual Temperature", "K", "theta * (P/P0)^(Rd/cp)"),
}


def validate_inputs(input_paths: list, variables: list, mode: str,
                    lat: float = None, lon: float = None) -> dict:
    """Validate inputs before processing."""
    errors = []
    warnings = []

    if not input_paths:
        errors.append("No input files specified")
    else:
        for p in input_paths:
            if not os.path.isfile(p):
                errors.append(f"Input file not found: {p}")

    all_known = set(WRF_OUTPUT_VARIABLES.keys()) | set(DERIVED_VARIABLES.keys())
    for v in variables:
        if v not in all_known:
            warnings.append(f"Variable '{v}' not in known list; will attempt extraction anyway")

    if mode == "timeseries" and (lat is None or lon is None):
        errors.append("Timeseries mode requires --lat and --lon")

    try:
        import netCDF4  # noqa: F401
    except ImportError:
        errors.append("netCDF4 not installed. Run: pip install netCDF4")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def find_nearest_point(lats_2d, lons_2d, target_lat, target_lon):
    """Find the nearest grid point (j, i) to target lat/lon."""
    dist = np.sqrt((lats_2d - target_lat) ** 2 + (lons_2d - target_lon) ** 2)
    j, i = np.unravel_index(np.argmin(dist), dist.shape)
    actual_lat = float(lats_2d[j, i])
    actual_lon = float(lons_2d[j, i])
    distance_deg = float(dist[j, i])
    return j, i, actual_lat, actual_lon, distance_deg


def destagger(data, axis):
    """Destagger a field along the given axis (average adjacent points)."""
    slices_lo = [slice(None)] * data.ndim
    slices_hi = [slice(None)] * data.ndim
    slices_lo[axis] = slice(None, -1)
    slices_hi[axis] = slice(1, None)
    return 0.5 * (data[tuple(slices_lo)] + data[tuple(slices_hi)])


def compute_derived(ds, var_name, time_idx, j=None, i=None):
    """Compute a derived variable."""
    R_D = 287.0
    CP = 1003.5
    P0 = 100000.0

    if var_name == "WIND10":
        u10 = ds.variables["U10"][time_idx, j, i] if j is not None else ds.variables["U10"][time_idx]
        v10 = ds.variables["V10"][time_idx, j, i] if j is not None else ds.variables["V10"][time_idx]
        return np.sqrt(u10 ** 2 + v10 ** 2)

    elif var_name == "TOTAL_PRECIP":
        rc = ds.variables["RAINC"][time_idx, j, i] if j is not None else ds.variables["RAINC"][time_idx]
        rnc = ds.variables["RAINNC"][time_idx, j, i] if j is not None else ds.variables["RAINNC"][time_idx]
        return rc + rnc

    elif var_name == "T2C":
        t2 = ds.variables["T2"][time_idx, j, i] if j is not None else ds.variables["T2"][time_idx]
        return t2 - 273.15

    elif var_name == "THETA":
        t_pert = ds.variables["T"][time_idx]
        return t_pert + 300.0

    elif var_name == "PRESSURE":
        p = ds.variables["P"][time_idx]
        pb = ds.variables["PB"][time_idx]
        return p + pb

    elif var_name == "HEIGHT":
        ph = ds.variables["PH"][time_idx]
        phb = ds.variables["PHB"][time_idx]
        return destagger((ph + phb) / 9.81, axis=0)

    elif var_name == "TEMP":
        t_pert = ds.variables["T"][time_idx]
        p = ds.variables["P"][time_idx]
        pb = ds.variables["PB"][time_idx]
        theta = t_pert + 300.0
        pressure = p + pb
        return theta * (pressure / P0) ** (R_D / CP)

    elif var_name == "RH2":
        t2 = ds.variables["T2"][time_idx, j, i] if j is not None else ds.variables["T2"][time_idx]
        q2 = ds.variables["Q2"][time_idx, j, i] if j is not None else ds.variables["Q2"][time_idx]
        psfc = ds.variables["PSFC"][time_idx, j, i] if j is not None else ds.variables["PSFC"][time_idx]
        # Tetens formula for saturation vapor pressure
        es = 611.2 * np.exp(17.67 * (t2 - 273.15) / (t2 - 29.65))
        # Actual vapor pressure from specific humidity
        e = q2 * psfc / (0.622 + 0.378 * q2)
        return np.clip(100.0 * e / es, 0, 100)

    return None


def extract_timeseries(input_paths: list, output_path: str, variables: list,
                       lat: float, lon: float) -> dict:
    """
    Extract time series at a point from multiple wrfout files.

    UNIT TRAPS:
    - T is perturbation potential temperature (T' = theta - 300). Add 300 for theta!
    - RAINC/RAINNC are accumulated from simulation start. Difference for rates.
    - U/V at 3D levels are staggered; must destagger before interpolation.
    - Pressure is split: P (perturbation) + PB (base state) = total pressure.
    - U10/V10 are grid-relative. For earth-relative, rotate by map factor (COSALPHA, SINALPHA).
    """
    import netCDF4 as nc

    records = []
    point_info = None

    for fpath in sorted(input_paths):
        ds = nc.Dataset(fpath, "r")

        # Get grid coordinates
        xlat = ds.variables["XLAT"][0, :, :]
        xlon = ds.variables["XLONG"][0, :, :]
        j, i, actual_lat, actual_lon, dist = find_nearest_point(xlat, xlon, lat, lon)

        if point_info is None:
            point_info = {
                "requested_lat": lat, "requested_lon": lon,
                "actual_lat": actual_lat, "actual_lon": actual_lon,
                "grid_j": int(j), "grid_i": int(i),
                "distance_deg": dist,
            }
            if dist > 0.5:
                print(f"  WARNING: Nearest grid point is {dist:.3f} deg from target")

        # Get times
        times_var = ds.variables["Times"]
        ntimes = times_var.shape[0]

        for ti in range(ntimes):
            time_str = "".join(c.decode("utf-8") if isinstance(c, bytes) else c
                               for c in times_var[ti, :])
            record = {"datetime": time_str.strip()}

            for var in variables:
                try:
                    if var in DERIVED_VARIABLES:
                        val = compute_derived(ds, var, ti, j, i)
                    elif var in ds.variables:
                        v = ds.variables[var]
                        ndims = len(v.dimensions)
                        if ndims == 3:  # (time, south_north, west_east)
                            val = float(v[ti, j, i])
                        elif ndims == 4:  # (time, bottom_top, south_north, west_east)
                            # Extract surface level (k=0)
                            val = float(v[ti, 0, j, i])
                        else:
                            val = float(v[ti])
                    else:
                        val = np.nan
                    record[var] = round(float(val), 6) if not np.isnan(val) else ""
                except Exception as e:
                    record[var] = ""

            records.append(record)
        ds.close()

    # Write CSV
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if records:
        fieldnames = ["datetime"] + variables
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

    return {
        "status": "success",
        "n_records": len(records),
        "n_files": len(input_paths),
        "point": point_info,
        "output": output_path,
    }


def extract_spatial(input_path: str, output_path: str, variables: list) -> dict:
    """
    Extract 2D spatial field from a single wrfout file.

    Outputs CSV with columns: lat, lon, var1, var2, ...
    """
    import netCDF4 as nc

    ds = nc.Dataset(input_path, "r")
    xlat = ds.variables["XLAT"][0, :, :]
    xlon = ds.variables["XLONG"][0, :, :]
    ny, nx = xlat.shape

    records = []
    for jj in range(ny):
        for ii in range(nx):
            record = {
                "lat": round(float(xlat[jj, ii]), 5),
                "lon": round(float(xlon[jj, ii]), 5),
            }
            for var in variables:
                try:
                    if var in DERIVED_VARIABLES:
                        field = compute_derived(ds, var, 0)
                        if field is not None and field.ndim >= 2:
                            val = float(field[jj, ii]) if field.ndim == 2 else float(field[0, jj, ii])
                        else:
                            val = np.nan
                    elif var in ds.variables:
                        v = ds.variables[var]
                        ndims = len(v.dimensions)
                        if ndims == 3:
                            val = float(v[0, jj, ii])
                        elif ndims == 4:
                            val = float(v[0, 0, jj, ii])
                        else:
                            val = np.nan
                    else:
                        val = np.nan
                    record[var] = round(float(val), 6)
                except Exception:
                    record[var] = ""
            records.append(record)
    ds.close()

    # Write CSV
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    fieldnames = ["lat", "lon"] + variables
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    return {
        "status": "success",
        "grid_size": f"{ny} x {nx}",
        "n_records": len(records),
        "output": output_path,
    }


def validate_outputs(output_path: str, expected_vars: list) -> dict:
    """Validate the output CSV file."""
    errors = []
    warnings = []

    if not os.path.isfile(output_path):
        errors.append(f"Output file not created: {output_path}")
        return {"valid": False, "errors": errors, "warnings": warnings}

    size = os.path.getsize(output_path)
    if size == 0:
        errors.append("Output file is empty")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Read and check header
    with open(output_path) as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        n_rows = sum(1 for _ in reader)

    for var in expected_vars:
        if var not in headers:
            warnings.append(f"Expected variable '{var}' not in output headers")

    if n_rows == 0:
        errors.append("Output file has header but no data rows")

    print(f"  Output: {output_path}")
    print(f"  Columns: {', '.join(headers)}")
    print(f"  Rows: {n_rows}")
    print(f"  Size: {size / 1024:.1f} KB")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings, "n_rows": n_rows}


def main():
    parser = argparse.ArgumentParser(description="Extract WRF output variables to CSV")
    parser.add_argument("--input", nargs="+", required=True, help="wrfout file(s)")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--mode", choices=["timeseries", "spatial"], default="timeseries")
    parser.add_argument("--variables", required=True,
                        help="Comma-separated variable names (e.g., T2,PSFC,RAINC)")
    parser.add_argument("--lat", type=float, help="Target latitude (for timeseries)")
    parser.add_argument("--lon", type=float, help="Target longitude (for timeseries)")
    args = parser.parse_args()

    variables = [v.strip() for v in args.variables.split(",")]
    input_paths = args.input

    print("=" * 60)
    print("WRF Output Parser")
    print("=" * 60)
    print(f"  Mode:      {args.mode}")
    print(f"  Variables: {', '.join(variables)}")
    print(f"  Input:     {len(input_paths)} file(s)")
    print(f"  Output:    {args.output}")

    # Step 1: Validate
    print("\n[1/3] Validating inputs...")
    v = validate_inputs(input_paths, variables, args.mode, args.lat, args.lon)
    if not v["valid"]:
        for e in v["errors"]:
            print(f"  ERROR: {e}")
        sys.exit(1)
    for w in v["warnings"]:
        print(f"  WARNING: {w}")

    # Step 2: Extract
    print("\n[2/3] Extracting data...")
    if args.mode == "timeseries":
        result = extract_timeseries(input_paths, args.output, variables, args.lat, args.lon)
    else:
        result = extract_spatial(input_paths[0], args.output, variables)

    if result["status"] != "success":
        print(f"EXTRACTION FAILED: {result}")
        sys.exit(1)

    # Step 3: Validate output
    print("\n[3/3] Validating output...")
    vo = validate_outputs(args.output, variables)
    if not vo["valid"]:
        for e in vo["errors"]:
            print(f"  ERROR: {e}")
        sys.exit(1)

    print("\nDONE - Extraction successful")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
