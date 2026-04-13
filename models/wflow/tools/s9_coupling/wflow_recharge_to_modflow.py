#!/usr/bin/env python3
"""
wflow_recharge_to_modflow.py — Extract groundwater recharge from wflow for MODFLOW.

wflow_sbm computes percolation below the root zone, which can serve as the
recharge boundary condition for MODFLOW groundwater models.

UNIT CONVERSION:
  wflow recharge: mm/day
  MODFLOW recharge: m/day (FloPy RCH package)
  Conversion: divide by 1000

Usage:
    python wflow_recharge_to_modflow.py \
      --wflow_output /path/to/output_grid.nc \
      --output /path/to/recharge_modflow.nc \
      --start_year 2000 --end_year 2010
"""

import argparse
import json
import os
import sys

import numpy as np


def process(args):
    """Extract recharge and convert units."""
    import xarray as xr

    ds = xr.open_dataset(args.wflow_output)

    # Find recharge/percolation variable
    rch_var = None
    for name in ["recharge", "percolation", "perc", "actleakage",
                  "transfer", "gwrecharge"]:
        if name in ds:
            rch_var = name
            break

    if rch_var is None:
        available = list(ds.data_vars)
        return {
            "status": "failed",
            "error": f"No recharge variable found. Available: {available}. "
                     "Ensure wflow output includes recharge/percolation.",
        }

    rch = ds[rch_var]
    print(f"  Recharge variable: {rch_var}", file=sys.stderr)

    # Convert mm/day -> m/day for MODFLOW
    rch_m_day = rch / 1000.0

    # Skip warmup
    if args.warmup > 0 and "time" in rch_m_day.dims:
        rch_m_day = rch_m_day.isel(time=slice(args.warmup, None))

    # Compute statistics
    mean_rch = float(rch_m_day.mean())
    max_rch = float(rch_m_day.max())

    # Save output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    out_ds = xr.Dataset({
        "recharge": (rch_m_day.dims, rch_m_day.values, {
            "units": "m/day",
            "long_name": "Groundwater recharge from wflow_sbm",
            "source_variable": rch_var,
            "conversion": "mm/day -> m/day (divided by 1000)",
        }),
    }, coords=rch_m_day.coords)

    out_ds.to_netcdf(args.output, encoding={
        "recharge": {"dtype": "float32", "zlib": True},
    })

    ds.close()

    return {
        "status": "success",
        "output_path": args.output,
        "source_variable": rch_var,
        "units": "m/day (MODFLOW-compatible)",
        "mean_recharge_m_day": round(mean_rch, 6),
        "max_recharge_m_day": round(max_rch, 6),
        "mean_recharge_mm_day": round(mean_rch * 1000, 3),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Extract wflow recharge for MODFLOW"
    )
    parser.add_argument("--wflow_output", type=str, required=True)
    parser.add_argument("--output", type=str, required=True)
    parser.add_argument("--warmup", type=int, default=365)
    args = parser.parse_args()

    if not os.path.exists(args.wflow_output):
        print(f"ERROR: Not found: {args.wflow_output}", file=sys.stderr)
        sys.exit(1)

    try:
        result = process(args)
    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 2)


if __name__ == "__main__":
    main()
