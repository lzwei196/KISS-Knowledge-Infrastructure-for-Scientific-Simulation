#!/usr/bin/env python3
"""
extract_spatial_output.py — Extract gridded fields from wflow output for visualization.

Extracts spatial maps of annual/monthly means for:
  - Runoff (mm/day or mm/year)
  - Actual evapotranspiration (mm/day or mm/year)
  - Soil moisture / saturated water depth (mm)
  - Snow water equivalent (mm)
  - Discharge (m3/s)

Outputs: GeoTIFF rasters and/or per-variable NetCDF for use with
HydroCraft plotting tools.

Usage:
    python extract_spatial_output.py \
      --output_nc /path/to/output_grid.nc \
      --variables runoff,actevap,satwaterdepth \
      --aggregation annual_mean \
      --output_dir /path/to/spatial_maps/
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate inputs."""
    errors = []

    if not os.path.exists(args.output_nc):
        errors.append(f"Output file not found: {args.output_nc}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def process(args):
    """Extract spatial fields."""
    import xarray as xr

    ds = xr.open_dataset(args.output_nc)

    # Determine available variables
    available_vars = list(ds.data_vars)
    requested_vars = [v.strip() for v in args.variables.split(",")]

    # Map common aliases
    alias_map = {
        "runoff": ["runoff", "run", "overland_flow"],
        "actevap": ["actevap", "actual_evaporation", "et", "aet"],
        "soilmoisture": ["satwaterdepth", "soilmoisture", "ssf", "ustorelayerdepth"],
        "snow": ["snow", "snowwater", "swe", "snowpack"],
        "q_river": ["q_river", "Q", "discharge"],
    }

    results = {}
    os.makedirs(args.output_dir, exist_ok=True)

    for var_name in requested_vars:
        # Find matching variable
        actual_var = None
        if var_name in available_vars:
            actual_var = var_name
        else:
            for alias_group, aliases in alias_map.items():
                if var_name in aliases:
                    for alias in aliases:
                        if alias in available_vars:
                            actual_var = alias
                            break
                    break

        if actual_var is None:
            print(f"  WARNING: Variable '{var_name}' not found. Available: {available_vars}",
                  file=sys.stderr)
            results[var_name] = {"status": "not_found"}
            continue

        data = ds[actual_var]

        # Skip warmup period
        if "time" in data.dims and args.warmup > 0:
            data = data.isel(time=slice(args.warmup, None))

        # Aggregate
        if args.aggregation == "annual_mean":
            spatial = data.mean(dim="time")
            unit_suffix = "/day"
        elif args.aggregation == "annual_sum":
            spatial = data.sum(dim="time")
            unit_suffix = "/year"
        elif args.aggregation == "monthly_mean":
            # Group by month
            spatial = data.groupby("time.month").mean()
            unit_suffix = "/day (monthly)"
        elif args.aggregation == "last_timestep":
            spatial = data.isel(time=-1)
            unit_suffix = ""
        else:
            spatial = data.mean(dim="time")
            unit_suffix = "/day"

        # Save as NetCDF
        out_nc = os.path.join(args.output_dir, f"{var_name}_{args.aggregation}.nc")
        spatial.to_netcdf(out_nc)

        # Compute statistics
        vals = spatial.values
        vals_valid = vals[np.isfinite(vals) & (vals != 0)]

        stats = {
            "status": "extracted",
            "variable": actual_var,
            "aggregation": args.aggregation,
            "output_path": out_nc,
            "mean": round(float(np.mean(vals_valid)), 4) if len(vals_valid) > 0 else None,
            "min": round(float(np.min(vals_valid)), 4) if len(vals_valid) > 0 else None,
            "max": round(float(np.max(vals_valid)), 4) if len(vals_valid) > 0 else None,
            "unit_note": unit_suffix,
        }

        results[var_name] = stats
        print(f"  {var_name}: mean={stats['mean']}, range=[{stats['min']}, {stats['max']}]",
              file=sys.stderr)

    ds.close()
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Extract gridded fields from wflow output"
    )
    parser.add_argument("--output_nc", type=str, required=True)
    parser.add_argument("--variables", type=str,
                        default="runoff,actevap,satwaterdepth",
                        help="Comma-separated variable names")
    parser.add_argument("--aggregation", type=str, default="annual_mean",
                        choices=["annual_mean", "annual_sum", "monthly_mean", "last_timestep"])
    parser.add_argument("--warmup", type=int, default=365,
                        help="Warmup days to skip")
    parser.add_argument("--output_dir", type=str, required=True)
    args = parser.parse_args()

    validate_inputs(args)

    try:
        results = process(args)
    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    result = {
        "status": "success",
        "variables": results,
        "output_dir": args.output_dir,
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
