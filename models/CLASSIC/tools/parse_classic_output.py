#!/usr/bin/env python3
"""
parse_classic_output.py — Extract CLASSIC netCDF output to CSV/DataFrame.

CLASSIC produces netCDF output files in the output directory, organized by
temporal resolution (annual, monthly, daily, half-hourly). This tool:
  1. Scans the output directory for netCDF files
  2. Extracts specified variables for a given location
  3. Outputs CSV files suitable for analysis and plotting
  4. Computes basic diagnostics (means, trends, carbon balance)

CLASSIC output naming conventions:
  - *_yr.nc  : Annual output
  - *_mo.nc  : Monthly output
  - *_d.nc   : Daily output
  - *_hh.nc  : Half-hourly output
  - *_pft_*.nc : Per-PFT output
  - *_tile_*.nc : Per-tile output

Usage:
    python parse_classic_output.py \\
        --output_dir /path/to/classic/outputFiles \\
        --variables "gpp,npp,nep,rh,lai,mrro,hfss,hfls" \\
        --frequency monthly \\
        --csv_out results.csv

    python parse_classic_output.py \\
        --output_dir /path/to/classic/outputFiles \\
        --variables "all" \\
        --frequency annual \\
        --csv_out annual_results.csv \\
        --compute_diagnostics
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    print(json.dumps({"status": "error", "errors": ["netCDF4 not installed"]}))
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    pd = None

# Map frequency to file suffix
FREQ_SUFFIX = {
    "annual": "_yr",
    "monthly": "_mo",
    "daily": "_d",
    "halfhourly": "_hh",
}

# Key CLASSIC output variables and their descriptions
CLASSIC_OUTPUT_VARS = {
    "rss": {"long_name": "Net shortwave radiation", "units": "W/m2", "category": "energy"},
    "rls": {"long_name": "Net longwave radiation", "units": "W/m2", "category": "energy"},
    "hfss": {"long_name": "Sensible heat flux", "units": "W/m2", "category": "energy"},
    "hfls": {"long_name": "Latent heat flux", "units": "W/m2", "category": "energy"},
    "gpp": {"long_name": "Gross primary productivity", "units": "kgC/m2", "category": "carbon"},
    "npp": {"long_name": "Net primary productivity", "units": "kgC/m2", "category": "carbon"},
    "nep": {"long_name": "Net ecosystem productivity", "units": "kgC/m2", "category": "carbon"},
    "nbp": {"long_name": "Net biome productivity", "units": "kgC/m2", "category": "carbon"},
    "ra": {"long_name": "Autotrophic respiration", "units": "kgC/m2", "category": "carbon"},
    "rh": {"long_name": "Heterotrophic respiration", "units": "kgC/m2", "category": "carbon"},
    "mrro": {"long_name": "Total runoff", "units": "kg/m2/s", "category": "water"},
    "mrros": {"long_name": "Surface runoff", "units": "kg/m2/s", "category": "water"},
    "evspsbl": {"long_name": "Evapotranspiration", "units": "kg/m2/s", "category": "water"},
    "snw": {"long_name": "Snow water equivalent", "units": "kg/m2", "category": "snow"},
    "lai": {"long_name": "Leaf area index", "units": "m2/m2", "category": "vegetation"},
    "cVeg": {"long_name": "Vegetation carbon", "units": "kgC/m2", "category": "carbon"},
    "cSoil": {"long_name": "Soil carbon", "units": "kgC/m2", "category": "carbon"},
    "cLitter": {"long_name": "Litter carbon", "units": "kgC/m2", "category": "carbon"},
    "tsl": {"long_name": "Soil temperature", "units": "K", "category": "soil"},
    "mrsll": {"long_name": "Soil moisture per layer", "units": "kg/m2", "category": "soil"},
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isdir(args.output_dir):
        errors.append(f"Output directory not found: {args.output_dir}")

    if args.frequency not in FREQ_SUFFIX:
        errors.append(f"Unsupported frequency: {args.frequency}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def classic_time_to_datetime(time_values):
    """
    Convert CLASSIC time values ("day as %Y%m%d.%f") to datetime objects.

    The CLASSIC time encoding stores dates as float values where the integer
    part is YYYYMMDD and the fractional part is the fraction of the day.
    """
    datetimes = []
    for t in time_values:
        date_int = int(t)
        frac = t - date_int
        yr = date_int // 10000
        mo = (date_int % 10000) // 100
        dy = date_int % 100
        if mo < 1:
            mo = 1
        if dy < 1:
            dy = 1
        if mo > 12:
            mo = 12
        if dy > 31:
            dy = 28
        try:
            dt = datetime(yr, mo, dy) + timedelta(seconds=frac * 86400)
            datetimes.append(dt)
        except ValueError:
            # Handle invalid dates (e.g., Feb 30)
            dy = min(dy, 28)
            dt = datetime(yr, mo, dy) + timedelta(seconds=frac * 86400)
            datetimes.append(dt)
    return datetimes


def scan_output_files(output_dir, frequency):
    """Find all CLASSIC output files for a given frequency."""
    suffix = FREQ_SUFFIX[frequency]
    files = {}
    for f in os.listdir(output_dir):
        if f.endswith(".nc") and suffix in f:
            # Extract variable name from filename
            # Format is typically: shortname_freq.nc
            base = f.replace(".nc", "")
            var_name = base.replace(suffix, "").replace("_grid", "")
            files[var_name] = os.path.join(output_dir, f)
    return files


def extract_variable(nc_path, lat_idx=0, lon_idx=0):
    """
    Extract time series data from a CLASSIC output netCDF file.

    Returns (times, data, var_name, units)
    """
    ds = nc.Dataset(nc_path, "r")

    # Find data variable (not coordinates)
    data_var_name = None
    for vn in ds.variables:
        if vn not in ["lat", "lon", "time", "latitude", "longitude",
                       "tile", "layer", "ic", "icc", "icp1"]:
            v = ds.variables[vn]
            if "time" in v.dimensions:
                data_var_name = vn
                break

    if data_var_name is None:
        ds.close()
        return None, None, None, None

    var = ds.variables[data_var_name]
    units = getattr(var, "units", "")
    long_name = getattr(var, "long_name", data_var_name)

    # Read time
    time_var = ds.variables["time"]
    time_values = time_var[:]
    times = classic_time_to_datetime(time_values)

    # Extract data at location
    ndim = len(var.dimensions)
    if ndim == 3:  # (time, lat, lon)
        data = var[:, lat_idx, lon_idx]
    elif ndim == 4:  # (time, tile/layer, lat, lon)
        data = var[:, 0, lat_idx, lon_idx]
    elif ndim == 1:  # (time,) — scalar
        data = var[:]
    else:
        data = var[:, 0, lat_idx, lon_idx]

    ds.close()
    return times, np.array(data), data_var_name, units


def compute_diagnostics(all_data):
    """Compute summary diagnostics from extracted data."""
    diagnostics = {}

    for var_name, (times, data, units) in all_data.items():
        valid = data[~np.isnan(data)] if len(data) > 0 else np.array([])
        if len(valid) == 0:
            continue

        diag = {
            "mean": float(np.mean(valid)),
            "std": float(np.std(valid)),
            "min": float(np.min(valid)),
            "max": float(np.max(valid)),
            "units": units,
            "n_values": len(valid),
            "n_nan": int(np.sum(np.isnan(data))),
        }

        # Carbon budget check
        if var_name == "gpp":
            diag["annual_total_gC_m2"] = float(np.sum(valid) * 1000)
        if var_name == "nep":
            diag["cumulative_kgC_m2"] = float(np.sum(valid))

        diagnostics[var_name] = diag

    # Carbon balance check: NEP ≈ GPP - Ra - Rh
    if "gpp" in all_data and "ra" in all_data and "rh" in all_data and "nep" in all_data:
        gpp_sum = float(np.nansum(all_data["gpp"][1]))
        ra_sum = float(np.nansum(all_data["ra"][1]))
        rh_sum = float(np.nansum(all_data["rh"][1]))
        nep_sum = float(np.nansum(all_data["nep"][1]))
        expected_nep = gpp_sum - ra_sum - rh_sum
        diagnostics["_carbon_balance"] = {
            "GPP_total": gpp_sum,
            "Ra_total": ra_sum,
            "Rh_total": rh_sum,
            "NEP_total": nep_sum,
            "expected_NEP": expected_nep,
            "imbalance": nep_sum - expected_nep,
        }

    return diagnostics


def write_csv(all_data, csv_path):
    """Write extracted data to CSV."""
    if pd is None:
        # Manual CSV writing
        with open(csv_path, "w") as f:
            # Get common time axis
            first_key = list(all_data.keys())[0]
            times = all_data[first_key][0]
            header = "time," + ",".join(all_data.keys())
            f.write(header + "\n")
            for i, t in enumerate(times):
                vals = []
                for var_name in all_data:
                    _, data, _ = all_data[var_name]
                    if i < len(data):
                        vals.append(f"{data[i]:.6e}")
                    else:
                        vals.append("")
                f.write(f"{t.strftime('%Y-%m-%d %H:%M:%S')},{','.join(vals)}\n")
    else:
        # Use pandas
        df_dict = {}
        ref_times = None
        for var_name, (times, data, units) in all_data.items():
            if ref_times is None:
                ref_times = times
            df_dict[var_name] = data[:len(ref_times)]
        df = pd.DataFrame(df_dict, index=ref_times)
        df.index.name = "time"
        df.to_csv(csv_path)


def main():
    parser = argparse.ArgumentParser(
        description="Extract CLASSIC output to CSV"
    )
    parser.add_argument("--output_dir", required=True,
                        help="CLASSIC output directory")
    parser.add_argument("--variables", default="all",
                        help="Comma-separated variable names or 'all'")
    parser.add_argument("--frequency", default="monthly",
                        choices=["annual", "monthly", "daily", "halfhourly"])
    parser.add_argument("--csv_out", required=True,
                        help="Output CSV file path")
    parser.add_argument("--lat_idx", type=int, default=0,
                        help="Latitude index (default: 0 for single point)")
    parser.add_argument("--lon_idx", type=int, default=0,
                        help="Longitude index (default: 0 for single point)")
    parser.add_argument("--compute_diagnostics", action="store_true",
                        help="Compute and print summary diagnostics")

    args = parser.parse_args()
    validate_inputs(args)

    # Scan for available files
    available = scan_output_files(args.output_dir, args.frequency)
    if not available:
        print(json.dumps({
            "status": "error",
            "errors": [f"No {args.frequency} output files found in {args.output_dir}"]
        }))
        sys.exit(1)

    # Determine which variables to extract
    if args.variables == "all":
        target_vars = list(available.keys())
    else:
        target_vars = [v.strip() for v in args.variables.split(",")]

    # Extract data
    all_data = {}
    warnings = []
    for var_name in target_vars:
        if var_name in available:
            times, data, actual_name, units = extract_variable(
                available[var_name], args.lat_idx, args.lon_idx
            )
            if times is not None:
                all_data[var_name] = (times, data, units)
            else:
                warnings.append(f"Could not extract data from {available[var_name]}")
        else:
            warnings.append(f"Variable '{var_name}' not found in output files")

    if not all_data:
        print(json.dumps({
            "status": "error",
            "errors": ["No data extracted"],
            "warnings": warnings,
            "available_files": list(available.keys()),
        }))
        sys.exit(1)

    # Write CSV
    os.makedirs(os.path.dirname(os.path.abspath(args.csv_out)), exist_ok=True)
    write_csv(all_data, args.csv_out)

    result = {
        "status": "success",
        "csv_file": args.csv_out,
        "variables_extracted": list(all_data.keys()),
        "n_timesteps": len(list(all_data.values())[0][0]),
        "warnings": warnings,
    }

    # Diagnostics
    if args.compute_diagnostics:
        diags = compute_diagnostics(all_data)
        result["diagnostics"] = diags

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
