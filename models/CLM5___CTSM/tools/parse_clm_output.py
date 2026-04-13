#!/usr/bin/env python3
"""
parse_clm_output.py — Extract CLM5 history file variables to CSV and JSON.

Reads CLM5/CTSM NetCDF history files (h0, h1, etc.) and extracts selected
variables into analysis-friendly formats.

CLM5 HISTORY FILE CONVENTIONS:
  - h0 files: monthly averages (default), contains all default fields
  - h1-h9 files: user-configured frequency/variables (via hist_fincl)
  - As of CTSM5.4: split into hXa (accumulated) and hXi (instantaneous)
  - Variables are on the unstructured "landunit" grid unless hist_dov2xy=.true.
  - Time coordinate uses "days since YYYY-01-01" with noleap calendar
  - Fill value is typically 1e36 (CLM missing value)

KEY OUTPUT VARIABLES:
  - GPP (gC/m2/s), NPP (gC/m2/s), NEE (gC/m2/s)
  - EFLX_LH_TOT (W/m2), FSH (W/m2)
  - QRUNOFF (mm/s), QDRAI (mm/s)
  - H2OSOI (mm3/mm3 per layer), TSOI (K per layer)
  - TOTSOMC (gC/m2), TOTVEGC (gC/m2)
  - SNOW_DEPTH (m), FSNO (fraction)

CRITICAL: CLM5 fluxes are per-UNIT-AREA, not per-grid-cell. To get grid cell
totals, multiply by landunit area fraction. GPP/NPP are in gC/m2/s — multiply
by seconds in period for totals.

Usage:
    python parse_clm_output.py --history-dir /path/to/hist/ \\
        --variables GPP,QRUNOFF,EFLX_LH_TOT --output results.csv
    python parse_clm_output.py --history-file /path/to/file.h0.nc \\
        --variables GPP --output results.json --format json
"""

import argparse
import glob
import json
import os
import sys
import warnings

import numpy as np

try:
    import xarray as xr
except ImportError:
    xr = None

try:
    import pandas as pd
except ImportError:
    pd = None


# ---------------------------------------------------------------------------
# CLM5 variable metadata
# ---------------------------------------------------------------------------
CLM5_VARIABLES = {
    "GPP": {"long_name": "Gross Primary Production", "units": "gC/m2/s",
             "category": "carbon"},
    "NPP": {"long_name": "Net Primary Production", "units": "gC/m2/s",
             "category": "carbon"},
    "NEE": {"long_name": "Net Ecosystem Exchange", "units": "gC/m2/s",
             "category": "carbon"},
    "NEP": {"long_name": "Net Ecosystem Production", "units": "gC/m2/s",
             "category": "carbon"},
    "TOTSOMC": {"long_name": "Total Soil Organic C", "units": "gC/m2",
                 "category": "carbon"},
    "TOTVEGC": {"long_name": "Total Vegetation C", "units": "gC/m2",
                 "category": "carbon"},
    "TOTLITC": {"long_name": "Total Litter C", "units": "gC/m2",
                 "category": "carbon"},
    "EFLX_LH_TOT": {"long_name": "Total Latent Heat", "units": "W/m2",
                      "category": "energy"},
    "FSH": {"long_name": "Sensible Heat Flux", "units": "W/m2",
             "category": "energy"},
    "FSDS": {"long_name": "Downward Shortwave", "units": "W/m2",
              "category": "radiation"},
    "FSR": {"long_name": "Reflected Shortwave", "units": "W/m2",
             "category": "radiation"},
    "FIRE": {"long_name": "Emitted Longwave", "units": "W/m2",
              "category": "radiation"},
    "FLDS": {"long_name": "Downward Longwave", "units": "W/m2",
              "category": "radiation"},
    "QRUNOFF": {"long_name": "Total Runoff", "units": "mm/s",
                 "category": "hydrology"},
    "QDRAI": {"long_name": "Subsurface Drainage", "units": "mm/s",
               "category": "hydrology"},
    "QOVER": {"long_name": "Surface Runoff", "units": "mm/s",
               "category": "hydrology"},
    "H2OSNO": {"long_name": "Snow Water Equivalent", "units": "mm",
                "category": "hydrology"},
    "SNOW_DEPTH": {"long_name": "Snow Depth", "units": "m",
                    "category": "hydrology"},
    "H2OSOI": {"long_name": "Soil Moisture", "units": "mm3/mm3",
                "category": "hydrology"},
    "TSOI": {"long_name": "Soil Temperature", "units": "K",
              "category": "temperature"},
    "TSOI_10CM": {"long_name": "Soil Temp 0-10cm", "units": "K",
                   "category": "temperature"},
    "TSA": {"long_name": "2m Air Temperature", "units": "K",
             "category": "temperature"},
    "TV": {"long_name": "Vegetation Temperature", "units": "K",
            "category": "temperature"},
    "TG": {"long_name": "Ground Temperature", "units": "K",
            "category": "temperature"},
    "FSNO": {"long_name": "Snow Cover Fraction", "units": "fraction",
              "category": "hydrology"},
    "TLAI": {"long_name": "Total LAI", "units": "m2/m2",
              "category": "vegetation"},
    "ELAI": {"long_name": "Exposed LAI", "units": "m2/m2",
              "category": "vegetation"},
}

CLM5_FILL_VALUE = 1.0e36


def validate_inputs(args):
    """Validate input paths and parameters."""
    errors = []

    if args.history_dir and not os.path.isdir(args.history_dir):
        errors.append(f"History directory does not exist: {args.history_dir}")

    if args.history_file and not os.path.exists(args.history_file):
        errors.append(f"History file does not exist: {args.history_file}")

    if not args.history_dir and not args.history_file:
        errors.append("Either --history-dir or --history-file required")

    if args.variables:
        unknown = [v for v in args.variables.split(",")
                    if v.strip() not in CLM5_VARIABLES]
        if unknown:
            errors.append(
                f"Unknown variables: {unknown}. "
                f"Known: {', '.join(sorted(CLM5_VARIABLES.keys()))}"
            )

    if xr is None:
        errors.append("xarray is required but not installed")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def find_history_files(history_dir, tape="h0"):
    """Find CLM5 history files matching a given tape pattern.

    Handles both old naming (*.clm2.h0.*.nc) and new split naming
    (*.clm2.h0a.*.nc, *.clm2.h0i.*.nc).
    """
    patterns = [
        os.path.join(history_dir, f"*.clm2.{tape}.*.nc"),
        os.path.join(history_dir, f"*.clm2.{tape}a.*.nc"),
        os.path.join(history_dir, f"*.{tape}.*.nc"),
    ]

    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))

    files = sorted(set(files))
    return files


def extract_variables(ds, var_names):
    """Extract selected variables from an xarray Dataset.

    Handles multi-dimensional variables (e.g., soil layers) by
    extracting surface/mean values where appropriate.
    """
    extracted = {}

    for var in var_names:
        if var not in ds:
            continue

        da = ds[var]

        # Replace fill values with NaN
        data = da.values.copy().astype(float)
        data[np.abs(data) > 1e35] = np.nan

        # Handle spatial dimensions
        # CLM5 may have (time, lndgrid) or (time, lat, lon) or (time, column, levgrnd)
        dims = da.dims

        if "levgrnd" in dims or "levsoi" in dims:
            # Multi-layer variable — extract surface layer and column mean
            layer_dim = "levgrnd" if "levgrnd" in dims else "levsoi"
            layer_idx = list(dims).index(layer_dim)

            # Surface layer (index 0)
            surface = np.take(data, 0, axis=layer_idx)
            extracted[f"{var}_surface"] = _spatial_mean(surface)

            # Column mean (all layers)
            col_mean = np.nanmean(data, axis=layer_idx)
            extracted[f"{var}_mean"] = _spatial_mean(col_mean)
        else:
            extracted[var] = _spatial_mean(data)

    return extracted


def _spatial_mean(data):
    """Compute spatial mean, preserving time dimension."""
    if data.ndim == 1:
        return data
    elif data.ndim == 2:
        return np.nanmean(data, axis=1)
    elif data.ndim == 3:
        return np.nanmean(data, axis=(1, 2))
    return data


def extract_time(ds):
    """Extract time coordinate as pandas DatetimeIndex.

    CLM5 uses noleap calendar — handle conversion carefully.
    """
    if "time" in ds.coords:
        try:
            time_vals = ds["time"].values
            if hasattr(time_vals[0], 'year'):
                # cftime objects — convert to string then to pandas
                time_str = [str(t) for t in time_vals]
                return pd.to_datetime(time_str, format="mixed")
            else:
                return pd.DatetimeIndex(time_vals)
        except Exception:
            # Fallback: use integer indices
            return np.arange(len(ds["time"]))
    return None


def compute_annual_totals(df, var, units):
    """Convert flux rates to annual totals where appropriate.

    GPP/NPP/NEE in gC/m2/s → gC/m2/yr (multiply by seconds per year)
    QRUNOFF in mm/s → mm/yr
    """
    seconds_per_year = 365.0 * 86400.0

    if units.endswith("/s"):
        annual = df[var].resample("YE").mean() * seconds_per_year
        return annual
    else:
        annual = df[var].resample("YE").mean()
        return annual


def process(args):
    """Main processing pipeline."""
    var_names = [v.strip() for v in args.variables.split(",")]

    # Find files
    if args.history_file:
        files = [args.history_file]
    else:
        files = find_history_files(args.history_dir, tape=args.tape)

    if not files:
        return {
            "status": "error",
            "errors": [f"No history files found in {args.history_dir}"],
        }

    # Open multi-file dataset
    try:
        ds = xr.open_mfdataset(files, combine="by_coords", decode_times=True)
    except Exception:
        try:
            ds = xr.open_mfdataset(
                files, combine="by_coords",
                use_cftime=True, decode_times=True
            )
        except Exception as e:
            return {
                "status": "error",
                "errors": [f"Failed to open history files: {e}"],
            }

    # Extract time
    times = extract_time(ds)

    # Extract variables
    data = extract_variables(ds, var_names)

    ds.close()

    # Build DataFrame
    if pd is not None and times is not None:
        df = pd.DataFrame(data, index=times)
        df.index.name = "time"
    else:
        df = None

    return {
        "data": data,
        "dataframe": df,
        "times": times,
        "n_files": len(files),
        "files": files[:10],
        "variables_found": list(data.keys()),
        "variables_missing": [v for v in var_names if v not in data
                              and f"{v}_surface" not in data],
    }


def validate_outputs(result):
    """Validate extracted data for reasonableness."""
    warnings_list = []
    data = result.get("data", {})

    for var, values in data.items():
        if values is None:
            continue
        arr = np.array(values, dtype=float)
        n_nan = np.sum(np.isnan(arr))
        n_total = len(arr)

        if n_nan == n_total:
            warnings_list.append(f"{var}: all values are NaN")
        elif n_nan > 0.5 * n_total:
            warnings_list.append(
                f"{var}: {n_nan}/{n_total} values are NaN ({100*n_nan/n_total:.0f}%)"
            )

        # Physical bounds checks
        base_var = var.replace("_surface", "").replace("_mean", "")
        if base_var in CLM5_VARIABLES:
            meta = CLM5_VARIABLES[base_var]
            finite_vals = arr[np.isfinite(arr)]
            if len(finite_vals) > 0:
                if meta["units"] == "K":
                    if np.min(finite_vals) < 150 or np.max(finite_vals) > 400:
                        warnings_list.append(
                            f"{var}: temperature outside 150-400 K range"
                        )
                elif meta["units"] == "mm/s":
                    if np.any(finite_vals < -0.001):
                        warnings_list.append(f"{var}: negative runoff detected")

    result["warnings"] = warnings_list
    return result


def write_output(result, args):
    """Write results to file."""
    df = result.get("dataframe")

    if args.format == "csv" and df is not None:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        df.to_csv(args.output)
        print(f"CSV written to {args.output}", file=sys.stderr)
    elif args.format == "json":
        # Convert numpy arrays to lists for JSON serialization
        output_data = {
            "status": "success",
            "n_files": result["n_files"],
            "variables_found": result["variables_found"],
            "variables_missing": result["variables_missing"],
            "warnings": result.get("warnings", []),
            "data": {},
        }
        for var, values in result["data"].items():
            if values is not None:
                output_data["data"][var] = np.where(
                    np.isfinite(values), values, None
                ).tolist()

        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2, default=str)
        print(f"JSON written to {args.output}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Extract CLM5 history variables to CSV/JSON"
    )
    parser.add_argument("--history-dir", type=str, default=None)
    parser.add_argument("--history-file", type=str, default=None)
    parser.add_argument(
        "--variables", type=str, required=True,
        help="Comma-separated variable names (e.g., GPP,QRUNOFF,EFLX_LH_TOT)"
    )
    parser.add_argument("--tape", type=str, default="h0",
                        help="History tape to read (default: h0)")
    parser.add_argument("--output", type=str, required=True)
    parser.add_argument("--format", type=str, default="csv",
                        choices=["csv", "json"])

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    if result.get("status") == "error":
        print(json.dumps(result, indent=2, default=str))
        sys.exit(1)

    result = validate_outputs(result)
    result["status"] = "success"

    write_output(result, args)

    # Print summary to stdout
    summary = {
        "status": "success",
        "n_files": result["n_files"],
        "variables_found": result["variables_found"],
        "variables_missing": result["variables_missing"],
        "warnings": result.get("warnings", []),
        "output": args.output,
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
