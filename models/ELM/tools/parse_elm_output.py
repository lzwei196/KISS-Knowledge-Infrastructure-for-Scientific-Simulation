#!/usr/bin/env python3
"""
parse_elm_output.py — Extract ELM history variables from NetCDF to CSV/DataFrame.

Reads ELM history output files (*.elm.h0.*.nc, *.elm.h1.*.nc, etc.) and extracts
requested variables into a structured CSV or pandas DataFrame for analysis.

Handles:
  - Multi-file time series concatenation
  - Grid-cell extraction (for point or regional analysis)
  - Depth-resolved soil variables (H2OSOI, TSOI, etc.)
  - Unit documentation in output headers
  - Basic quality checks (NaN fraction, range validation)

Output format:
  - CSV with time index and one column per variable
  - Optional JSON metadata with statistics and quality flags

CRITICAL: ELM outputs runoff (QRUNOFF) in mm/s, not mm/day. Multiply by 86400
          for daily totals. This is a common source of 86400x errors (dt_020).

Usage:
    python parse_elm_output.py --input_dir /path/to/archive/lnd/hist/ \\
        --variables GPP NPP QRUNOFF FSH EFLX_LH_TOT \\
        --output timeseries.csv

    python parse_elm_output.py --input_file case.elm.h0.2000-01.nc \\
        --variables H2OSOI --lat 40.0 --lon 117.0 \\
        --output soil_moisture.csv
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

try:
    import netCDF4 as nc4
    HAS_NETCDF = True
except ImportError:
    HAS_NETCDF = False

try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False


# ---------------------------------------------------------------------------
# ELM variable metadata
# ---------------------------------------------------------------------------
ELM_VARIABLES = {
    # Carbon fluxes
    "GPP":           {"units": "gC/m2/s",  "long_name": "Gross primary production",
                      "multiply_for_daily": 86400.0},
    "NPP":           {"units": "gC/m2/s",  "long_name": "Net primary production",
                      "multiply_for_daily": 86400.0},
    "NEE":           {"units": "gC/m2/s",  "long_name": "Net ecosystem exchange",
                      "multiply_for_daily": 86400.0},
    "HR":            {"units": "gC/m2/s",  "long_name": "Heterotrophic respiration",
                      "multiply_for_daily": 86400.0},
    "AR":            {"units": "gC/m2/s",  "long_name": "Autotrophic respiration",
                      "multiply_for_daily": 86400.0},

    # Energy fluxes
    "FSH":           {"units": "W/m2",     "long_name": "Sensible heat flux"},
    "EFLX_LH_TOT":  {"units": "W/m2",     "long_name": "Total latent heat flux"},
    "FSA":           {"units": "W/m2",     "long_name": "Absorbed shortwave radiation"},
    "FIRA":          {"units": "W/m2",     "long_name": "Net longwave radiation"},
    "FIRE":          {"units": "W/m2",     "long_name": "Emitted longwave radiation"},
    "Rnet":          {"units": "W/m2",     "long_name": "Net radiation (FSA-FIRA)",
                      "derived": True},

    # Water fluxes
    "QRUNOFF":       {"units": "mm/s",     "long_name": "Total runoff",
                      "multiply_for_daily": 86400.0},
    "QOVER":         {"units": "mm/s",     "long_name": "Surface runoff",
                      "multiply_for_daily": 86400.0},
    "QDRAI":         {"units": "mm/s",     "long_name": "Subsurface drainage",
                      "multiply_for_daily": 86400.0},
    "QVEGE":         {"units": "mm/s",     "long_name": "Canopy evaporation",
                      "multiply_for_daily": 86400.0},
    "QVEGT":         {"units": "mm/s",     "long_name": "Canopy transpiration",
                      "multiply_for_daily": 86400.0},
    "QSOIL":         {"units": "mm/s",     "long_name": "Ground evaporation",
                      "multiply_for_daily": 86400.0},

    # Soil state (depth-resolved)
    "H2OSOI":        {"units": "mm3/mm3",  "long_name": "Volumetric soil moisture",
                      "depth_resolved": True},
    "TSOI":          {"units": "K",        "long_name": "Soil temperature",
                      "depth_resolved": True},
    "SOILICE":       {"units": "kg/m2",    "long_name": "Soil ice content",
                      "depth_resolved": True},
    "SOILLIQ":       {"units": "kg/m2",    "long_name": "Soil liquid water",
                      "depth_resolved": True},

    # Snow
    "H2OSNO":        {"units": "mm",       "long_name": "Snow water equivalent"},
    "SNOW_DEPTH":    {"units": "m",        "long_name": "Snow depth"},
    "FSNO":          {"units": "fraction", "long_name": "Snow cover fraction"},

    # Vegetation
    "TLAI":          {"units": "m2/m2",    "long_name": "Total leaf area index"},
    "TSAI":          {"units": "m2/m2",    "long_name": "Total stem area index"},
    "TV":            {"units": "K",        "long_name": "Vegetation temperature"},
    "TG":            {"units": "K",        "long_name": "Ground temperature"},

    # Ecosystem pools
    "TOTECOSYSC":    {"units": "gC/m2",    "long_name": "Total ecosystem carbon"},
    "TOTECOSYSN":    {"units": "gN/m2",    "long_name": "Total ecosystem nitrogen"},
    "TOTECOSYSP":    {"units": "gP/m2",    "long_name": "Total ecosystem phosphorus"},
    "TOTSOMC":       {"units": "gC/m2",    "long_name": "Total soil organic matter C"},
    "TOTVEGC":       {"units": "gC/m2",    "long_name": "Total vegetation carbon"},
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if args.input_dir:
        if not os.path.isdir(args.input_dir):
            errors.append(f"Input directory not found: {args.input_dir}")
    elif args.input_file:
        if not os.path.isfile(args.input_file):
            errors.append(f"Input file not found: {args.input_file}")
    else:
        errors.append("Either --input_dir or --input_file is required")

    if not args.variables:
        errors.append("At least one --variables must be specified")

    if errors:
        result = {"status": "error", "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)


def validate_outputs(df, variables, warnings):
    """Post-processing quality checks on extracted data."""
    for var in variables:
        if var not in df.columns:
            warnings.append(f"Variable '{var}' not found in output files")
            continue

        col = df[var]
        nan_frac = col.isna().sum() / len(col)
        if nan_frac > 0.1:
            warnings.append(
                f"{var}: {nan_frac*100:.1f}% NaN values"
            )

        if var in ELM_VARIABLES:
            meta = ELM_VARIABLES[var]
            # Check for suspiciously large values
            if "multiply_for_daily" in meta and var.startswith("Q"):
                # Runoff: check if already in mm/day instead of mm/s
                if col.max() > 1.0:
                    warnings.append(
                        f"{var}: max = {col.max():.4f} {meta['units']}. "
                        f"If this seems too large, data may already be in "
                        f"mm/day instead of mm/s (dt_020)"
                    )

    return warnings


# ---------------------------------------------------------------------------
# NetCDF reading
# ---------------------------------------------------------------------------
def find_history_files(input_dir, tape="h0"):
    """Find ELM history files matching a given tape number."""
    patterns = [
        f"*.elm.{tape}.*.nc",
        f"*.clm2.{tape}.*.nc",   # Legacy CLM naming
        f"*{tape}*.nc",
    ]
    files = []
    for pattern in patterns:
        found = sorted(glob.glob(os.path.join(input_dir, pattern)))
        if found:
            files = found
            break

    if not files:
        # Try any NetCDF file
        files = sorted(glob.glob(os.path.join(input_dir, "*.nc")))

    return files


def extract_point(ds, var_name, lat=None, lon=None):
    """Extract a variable at a specific lat/lon point.

    If lat/lon not specified, returns grid-averaged value.
    """
    if var_name not in ds.variables:
        return None

    var = ds.variables[var_name]
    data = np.array(var[:])

    # Handle different dimension orderings
    dims = var.dimensions

    if lat is not None and lon is not None:
        # Find nearest grid cell
        if "lat" in ds.variables:
            lats = np.array(ds.variables["lat"][:])
            lons = np.array(ds.variables["lon"][:])
        elif "LATIXY" in ds.variables:
            lats = np.array(ds.variables["LATIXY"][:])
            lons = np.array(ds.variables["LONGXY"][:])
        else:
            # Single point or unstructured
            return data.squeeze()

        if lats.ndim == 1 and lons.ndim == 1:
            lat_idx = np.argmin(np.abs(lats - lat))
            lon_idx = np.argmin(np.abs(lons - lon))
            if "time" in dims:
                if data.ndim == 3:
                    return data[:, lat_idx, lon_idx]
                elif data.ndim == 4:  # depth-resolved
                    return data[:, :, lat_idx, lon_idx]
            else:
                return data[lat_idx, lon_idx]
        elif lats.ndim == 2:
            # 2D coordinate arrays
            dist = np.sqrt((lats - lat)**2 + (lons - lon)**2)
            min_idx = np.unravel_index(np.argmin(dist), dist.shape)
            if "time" in dims:
                if data.ndim == 3:
                    return data[:, min_idx[0], min_idx[1]]
                elif data.ndim == 4:
                    return data[:, :, min_idx[0], min_idx[1]]
            else:
                return data[min_idx[0], min_idx[1]]

    # No lat/lon specified — spatial average
    if "time" in dims:
        time_axis = list(dims).index("time")
        spatial_axes = tuple(i for i in range(data.ndim) if i != time_axis)
        return np.nanmean(data, axis=spatial_axes)
    else:
        return np.nanmean(data)


def get_time_array(ds):
    """Extract time array from NetCDF dataset."""
    if "time" in ds.variables:
        time_var = ds.variables["time"]
        try:
            times = nc4.num2date(time_var[:], time_var.units,
                                 calendar=getattr(time_var, "calendar", "noleap"))
            return pd.DatetimeIndex([
                datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
                for t in times
            ])
        except Exception:
            return pd.RangeIndex(len(time_var[:]))
    return None


def read_elm_files(file_list, variables, lat=None, lon=None):
    """Read variables from a list of ELM history files."""
    all_data = {var: [] for var in variables}
    all_times = []

    for fpath in file_list:
        ds = nc4.Dataset(fpath, "r")
        times = get_time_array(ds)
        if times is not None:
            all_times.extend(times)

        for var in variables:
            data = extract_point(ds, var, lat=lat, lon=lon)
            if data is not None:
                if data.ndim == 0:
                    all_data[var].append(float(data))
                elif data.ndim == 1:
                    all_data[var].extend(data.tolist())
                elif data.ndim == 2:
                    # Depth-resolved: take surface layer for simple output
                    all_data[var].extend(data[:, 0].tolist())

        ds.close()

    return all_data, all_times


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------
def build_dataframe(data_dict, times, variables):
    """Assemble extracted data into a pandas DataFrame."""
    df_data = {}

    for var in variables:
        if var in data_dict and data_dict[var]:
            df_data[var] = data_dict[var]

    if not df_data:
        return pd.DataFrame()

    # Ensure all columns have same length
    max_len = max(len(v) for v in df_data.values())
    for var in df_data:
        while len(df_data[var]) < max_len:
            df_data[var].append(np.nan)

    df = pd.DataFrame(df_data)

    # Set time index
    if times and len(times) >= max_len:
        df.index = times[:max_len]
        df.index.name = "time"
    elif times:
        df.index = times[:len(df)] if len(times) >= len(df) else range(len(df))
        df.index.name = "time"

    return df


def compute_statistics(df, variables):
    """Compute summary statistics for each variable."""
    stats = {}
    for var in variables:
        if var in df.columns:
            col = df[var].dropna()
            if len(col) > 0:
                stats[var] = {
                    "mean": float(col.mean()),
                    "std": float(col.std()),
                    "min": float(col.min()),
                    "max": float(col.max()),
                    "n_valid": int(len(col)),
                    "n_nan": int(df[var].isna().sum()),
                }
                if var in ELM_VARIABLES:
                    stats[var]["units"] = ELM_VARIABLES[var]["units"]
                    stats[var]["long_name"] = ELM_VARIABLES[var]["long_name"]
    return stats


def convert_units_for_output(df, to_daily=False):
    """Optionally convert flux rates to daily totals.

    CRITICAL (dt_020): Only apply this conversion if user explicitly requests
    daily output. The default ELM output is in per-second rates.
    """
    if not to_daily:
        return df, {}

    conversions = {}
    for var in df.columns:
        if var in ELM_VARIABLES and "multiply_for_daily" in ELM_VARIABLES[var]:
            factor = ELM_VARIABLES[var]["multiply_for_daily"]
            old_units = ELM_VARIABLES[var]["units"]
            new_units = old_units.replace("/s", "/day")
            df[var] = df[var] * factor
            conversions[var] = f"{old_units} → {new_units} (×{factor})"

    return df, conversions


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process(args):
    """Main pipeline: find files → read → extract → validate → write."""
    warnings = []

    if not HAS_NETCDF:
        return {
            "status": "error",
            "errors": ["netCDF4 required. pip install netCDF4"],
        }

    # Find input files
    if args.input_dir:
        file_list = find_history_files(args.input_dir, tape=args.tape)
        if not file_list:
            return {
                "status": "error",
                "errors": [f"No history files found in {args.input_dir}"],
            }
    else:
        file_list = [args.input_file]

    # Read data
    data_dict, times = read_elm_files(
        file_list, args.variables,
        lat=args.lat, lon=args.lon
    )

    # Build DataFrame
    df = build_dataframe(data_dict, times, args.variables)

    if df.empty:
        return {
            "status": "error",
            "errors": ["No data extracted. Check variable names and file contents."],
        }

    # Optional unit conversion
    df, conversions = convert_units_for_output(df, to_daily=args.to_daily)

    # Validate
    warnings = validate_outputs(df, args.variables, warnings)

    # Statistics
    stats = compute_statistics(df, args.variables)

    # Write output
    if args.output.endswith(".csv"):
        df.to_csv(args.output)
    elif args.output.endswith(".json"):
        result_data = {
            "data": df.to_dict(orient="list"),
            "index": [str(t) for t in df.index],
            "statistics": stats,
        }
        with open(args.output, "w") as f:
            json.dump(result_data, f, indent=2)
    else:
        df.to_csv(args.output)

    result = {
        "status": "success",
        "output_file": args.output,
        "n_files_read": len(file_list),
        "n_timesteps": len(df),
        "variables_extracted": [v for v in args.variables if v in df.columns],
        "variables_missing": [v for v in args.variables if v not in df.columns],
        "time_range": {
            "start": str(df.index[0]) if len(df) > 0 else None,
            "end": str(df.index[-1]) if len(df) > 0 else None,
        },
        "statistics": stats,
        "unit_conversions": conversions,
        "warnings": warnings,
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Extract ELM history variables from NetCDF to CSV"
    )

    # Input
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input_dir",
                             help="Directory containing history files")
    input_group.add_argument("--input_file",
                             help="Single history file path")

    # Variables
    parser.add_argument("--variables", nargs="+", required=True,
                        help="Variable names to extract (e.g., GPP NPP QRUNOFF)")
    parser.add_argument("--tape", default="h0",
                        help="History tape number (h0, h1, ... h5)")

    # Spatial selection
    parser.add_argument("--lat", type=float, default=None,
                        help="Latitude for point extraction")
    parser.add_argument("--lon", type=float, default=None,
                        help="Longitude for point extraction")

    # Output
    parser.add_argument("--output", required=True,
                        help="Output file path (.csv or .json)")
    parser.add_argument("--to_daily", action="store_true",
                        help="Convert per-second rates to per-day totals")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    print(json.dumps(result, indent=2))

    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
