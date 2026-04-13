#!/usr/bin/env python3
"""
wflow_to_cama.py — Convert wflow runoff output to CaMa-Flood input format.

CRITICAL: wflow already performs internal river routing (kinematic wave or
local inertial). If you send ROUTED discharge to CaMa-Flood, you will
DOUBLE-COUNT routing and get wrong results.

Correct approach: Extract UNROUTED runoff components from wflow output
(overland_flow + subsurface_lateral_flow, BEFORE routing) and send those
to CaMa-Flood.

Output format: CaMa-Flood expects yearly NetCDF files with variable 'runoff'
in mm/day on the VIC/wflow grid (NOT on CaMa's 15-minute grid — the input
matrix (inpmat) handles the mapping).

Usage:
    python wflow_to_cama.py \
      --wflow_output /path/to/output_grid.nc \
      --output_dir /path/to/cama_input \
      --basin_name chaohe \
      --start_year 2000 --end_year 2010
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate."""
    errors = []
    if not os.path.exists(args.wflow_output):
        errors.append(f"wflow output not found: {args.wflow_output}")
    if args.start_year >= args.end_year:
        errors.append(f"start_year must be < end_year")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def process(args):
    """Convert wflow runoff to CaMa-Flood yearly NetCDF."""
    import xarray as xr
    import pandas as pd

    ds = xr.open_dataset(args.wflow_output)

    # Find runoff variable (UNROUTED — not q_river which is routed)
    runoff_var = None
    for name in ["runoff", "overland_flow", "run", "surface_runoff"]:
        if name in ds:
            runoff_var = name
            break

    if runoff_var is None:
        # Fall back to q_river but warn
        if "q_river" in ds:
            runoff_var = "q_river"
            print(
                "WARNING: Using q_river (routed). This may cause double-counting "
                "with CaMa-Flood routing. Prefer unrouted runoff variable.",
                file=sys.stderr,
            )
        else:
            available = list(ds.data_vars)
            return {
                "status": "failed",
                "error": f"No runoff variable found. Available: {available}",
            }

    runoff = ds[runoff_var]
    print(f"  Using variable: {runoff_var}", file=sys.stderr)

    # Get coordinates
    if "y" in ds.coords:
        lats = ds["y"].values
        lons = ds["x"].values
    elif "lat" in ds.coords:
        lats = ds["lat"].values
        lons = ds["lon"].values
    else:
        return {"status": "failed", "error": "Cannot determine coordinates"}

    os.makedirs(args.output_dir, exist_ok=True)
    output_files = []

    for year in range(args.start_year, args.end_year + 1):
        # Select year
        year_data = runoff.sel(
            time=slice(f"{year}-01-01", f"{year}-12-31")
        )

        if len(year_data.time) == 0:
            print(f"  WARNING: No data for year {year}", file=sys.stderr)
            continue

        # Create CaMa-Flood compatible NetCDF
        out_ds = xr.Dataset(
            {
                "runoff": (
                    ["time", "lat", "lon"],
                    year_data.values,
                    {
                        "units": "mm/day",
                        "long_name": "Total runoff",
                        "source": f"wflow {runoff_var}",
                    },
                ),
            },
            coords={
                "time": year_data.time.values,
                "lat": lats,
                "lon": lons,
            },
        )

        out_path = os.path.join(
            args.output_dir, f"{args.basin_name}_runoff_1d_{year}.nc"
        )
        out_ds.to_netcdf(out_path, encoding={
            "runoff": {"dtype": "float32", "zlib": True},
        })

        size_mb = os.path.getsize(out_path) / 1e6
        output_files.append({
            "year": year,
            "path": out_path,
            "size_mb": round(size_mb, 1),
            "n_days": len(year_data.time),
        })

    ds.close()

    return {
        "status": "success",
        "output_dir": args.output_dir,
        "files": output_files,
        "runoff_variable": runoff_var,
        "warning": "Ensure wflow runoff is UNROUTED to avoid double-counting with CaMa-Flood"
        if runoff_var == "q_river"
        else None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert wflow runoff to CaMa-Flood input format"
    )
    parser.add_argument("--wflow_output", type=str, required=True)
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--basin_name", type=str, required=True)
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    args = parser.parse_args()

    validate_inputs(args)

    try:
        result = process(args)
    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 2)


if __name__ == "__main__":
    main()
