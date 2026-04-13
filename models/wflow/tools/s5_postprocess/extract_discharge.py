#!/usr/bin/env python3
"""
extract_discharge.py — Extract discharge timeseries from wflow output NetCDF.

wflow outputs discharge in two forms:
  1. output_scalar.nc — point/gauge output (Q at specified locations)
  2. output_grid.nc — gridded output (q_river at every cell)

This tool extracts discharge at the basin outlet (maximum Q cell or specified
coordinates) and produces:
  - CSV timeseries (date, Q_m3s)
  - JSON summary statistics
  - Optional: HydroCraft obs format for comparison plots

Usage:
    python extract_discharge.py \
      --output_nc /path/to/output_grid.nc \
      --lat 40.77 --lon 116.85 \
      --output /path/to/discharge.csv

    python extract_discharge.py \
      --scalar_nc /path/to/output_scalar.nc \
      --output /path/to/discharge.csv
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Check input files."""
    errors = []

    if not args.output_nc and not args.scalar_nc:
        errors.append("Must provide --output_nc (gridded) or --scalar_nc (scalar)")

    nc_path = args.output_nc or args.scalar_nc
    if nc_path and not os.path.exists(nc_path):
        errors.append(f"Output file not found: {nc_path}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def extract_from_gridded(output_nc, lat=None, lon=None, warmup_days=0):
    """Extract discharge from gridded output.

    If lat/lon provided, extract at nearest cell.
    Otherwise, find the cell with maximum mean discharge (assumed outlet).
    """
    import xarray as xr
    import pandas as pd

    ds = xr.open_dataset(output_nc)

    # Find discharge variable
    q_var = None
    for name in ["q_river", "Q", "discharge", "q_land", "run"]:
        if name in ds:
            q_var = name
            break

    if q_var is None:
        available = list(ds.data_vars)
        raise ValueError(
            f"No discharge variable found in {output_nc}. "
            f"Available variables: {available}"
        )

    q_data = ds[q_var]
    print(f"  Discharge variable: {q_var}, shape: {q_data.shape}", file=sys.stderr)

    # Apply warmup
    if warmup_days > 0:
        q_data = q_data.isel(time=slice(warmup_days, None))

    if lat is not None and lon is not None:
        # Extract at nearest cell
        if "y" in q_data.dims:
            q_point = q_data.sel(y=lat, x=lon, method="nearest")
        elif "lat" in q_data.dims:
            q_point = q_data.sel(lat=lat, lon=lon, method="nearest")
        else:
            raise ValueError("Cannot determine spatial coordinates")
    else:
        # Find outlet: cell with maximum mean discharge
        q_mean = q_data.mean(dim="time")
        if q_mean.ndim == 2:
            max_idx = q_mean.argmax()
            idx = np.unravel_index(max_idx.values, q_mean.shape)
            if "y" in q_data.dims:
                q_point = q_data.isel(y=idx[0], x=idx[1])
                lat = float(ds["y"][idx[0]])
                lon = float(ds["x"][idx[1]])
            else:
                q_point = q_data.isel(lat=idx[0], lon=idx[1])
                lat = float(ds["lat"][idx[0]])
                lon = float(ds["lon"][idx[1]])
            print(f"  Auto-detected outlet: {lat:.4f}N, {lon:.4f}E", file=sys.stderr)
        elif q_mean.ndim == 1:
            max_idx = q_mean.argmax()
            q_point = q_data.isel(station=max_idx)
        else:
            q_point = q_data

    # Convert to pandas Series
    times = q_point["time"].values
    values = q_point.values.flatten()

    # Create DataFrame
    df = pd.DataFrame({
        "date": pd.DatetimeIndex(times),
        "Q_m3s": values,
    })

    # Clean up
    df = df.dropna(subset=["Q_m3s"])
    df = df[df["Q_m3s"] >= 0]

    stats = {
        "mean_Q_m3s": round(float(df["Q_m3s"].mean()), 2),
        "max_Q_m3s": round(float(df["Q_m3s"].max()), 2),
        "min_Q_m3s": round(float(df["Q_m3s"].min()), 2),
        "std_Q_m3s": round(float(df["Q_m3s"].std()), 2),
        "n_days": len(df),
        "outlet_lat": lat,
        "outlet_lon": lon,
        "variable": q_var,
    }

    ds.close()
    return df, stats


def extract_from_scalar(scalar_nc, warmup_days=0):
    """Extract discharge from scalar output."""
    import xarray as xr
    import pandas as pd

    ds = xr.open_dataset(scalar_nc)

    q_var = None
    for name in ["Q", "q_river", "discharge"]:
        if name in ds:
            q_var = name
            break

    if q_var is None:
        raise ValueError(f"No discharge variable in {scalar_nc}")

    q_data = ds[q_var]
    if warmup_days > 0:
        q_data = q_data.isel(time=slice(warmup_days, None))

    times = q_data["time"].values
    values = q_data.values

    if values.ndim > 1:
        # Multiple gauges — take first or max
        values = values[:, 0] if values.shape[1] > 0 else values.flatten()

    df = pd.DataFrame({
        "date": pd.DatetimeIndex(times),
        "Q_m3s": values.flatten(),
    })

    stats = {
        "mean_Q_m3s": round(float(df["Q_m3s"].mean()), 2),
        "max_Q_m3s": round(float(df["Q_m3s"].max()), 2),
        "min_Q_m3s": round(float(df["Q_m3s"].min()), 2),
        "n_days": len(df),
        "variable": q_var,
    }

    ds.close()
    return df, stats


def main():
    parser = argparse.ArgumentParser(
        description="Extract discharge timeseries from wflow output"
    )
    parser.add_argument("--output_nc", type=str, default="")
    parser.add_argument("--scalar_nc", type=str, default="")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--warmup", type=int, default=365,
                        help="Warmup period in days to skip (default: 365)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output CSV path")
    parser.add_argument("--obs_format", action="store_true",
                        help="Also output in HydroCraft obs format (tab-separated)")
    args = parser.parse_args()

    validate_inputs(args)

    try:
        if args.output_nc:
            df, stats = extract_from_gridded(
                args.output_nc, args.lat, args.lon, args.warmup
            )
        else:
            df, stats = extract_from_scalar(args.scalar_nc, args.warmup)
    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    # Write CSV
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    df.to_csv(args.output, index=False, float_format="%.3f")

    # Write HydroCraft obs format if requested
    if args.obs_format:
        obs_path = args.output.replace(".csv", "_obs_format.txt")
        with open(obs_path, "w") as f:
            f.write("stcd\tdates\tz\tQ\tname\n")
            for _, row in df.iterrows():
                f.write(f"wflow\t{row['date'].strftime('%Y-%m-%d')}\t0\t{row['Q_m3s']:.3f}\twflow_output\n")
        stats["obs_format_path"] = obs_path

    result = {
        "status": "success",
        "output_csv": args.output,
        **stats,
    }

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
