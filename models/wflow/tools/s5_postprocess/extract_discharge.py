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
    """Check input files.

    Raises ValueError so that EVERY failure (validation included) flows
    through the single failure path in main(): failed-status JSON on
    stdout, stream flush, os._exit(2)."""
    errors = []

    if not args.output_nc and not args.scalar_nc:
        errors.append("Must provide --output_nc (gridded) or --scalar_nc (scalar)")

    nc_path = args.output_nc or args.scalar_nc
    if nc_path and not os.path.exists(nc_path):
        errors.append(f"Output file not found: {nc_path}")

    if errors:
        raise ValueError("; ".join(errors))


def extract_from_gridded(output_nc, lat=None, lon=None, warmup_days=0):
    """Extract discharge from gridded output.

    If lat/lon provided, extract at nearest cell.
    Otherwise, find the cell with maximum mean discharge (assumed outlet).
    """
    import xarray as xr
    import pandas as pd

    ds = xr.open_dataset(output_nc)

    # Find discharge variable. Search order per format_spec.yaml outputs.primary:
    # q_river (this KI's primary routed-discharge name), q_av (wflow.jl native
    # averaged discharge), then generic fallbacks discharge, Q.
    q_var = None
    for name in ["q_river", "q_av", "discharge", "Q"]:
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
    for name in ["Q", "q_river", "discharge", "q_land", "run"]:
        if name in ds:
            q_var = name
            break

    if q_var is None:
        available = list(ds.data_vars)
        raise ValueError(
            f"No discharge variable in {scalar_nc}. "
            f"Available variables: {available}"
        )

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

    # Clean up — same CSV contract as the gridded path
    df = df.dropna(subset=["Q_m3s"])
    df = df[df["Q_m3s"] >= 0]

    stats = {
        "mean_Q_m3s": round(float(df["Q_m3s"].mean()), 2),
        "max_Q_m3s": round(float(df["Q_m3s"].max()), 2),
        "min_Q_m3s": round(float(df["Q_m3s"].min()), 2),
        "std_Q_m3s": round(float(df["Q_m3s"].std()), 2),
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

    # xarray import (inside the extract_* helpers) registers a broken 'gmt'
    # backend entrypoint in this environment (libgmt.so missing); normal
    # interpreter teardown then SIGSEGVs (rc=-11) AFTER correct output. Both
    # exit paths therefore end in os._exit() with explicit stream flushes.
    # Contract (applies after argparse succeeds; argparse errors keep the
    # argparse default: usage text on stderr, exit 2):
    #   filesystem side effects — the parent directory of --output (which is
    #     also the obs-format file's directory) may be created via
    #     os.makedirs(..., exist_ok=True); otherwise only the *.tmp files,
    #     the --output CSV, and (with --obs_format) the obs-format file are
    #     touched.
    #   ordering — the success JSON is fully serialized first; then ALL
    #     fallible content writes go to *.tmp paths; the final paths are
    #     touched only by the consecutive os.replace calls at the end
    #     (obs-format first when requested, then --output), each recorded in
    #     `materialized` immediately after it succeeds.
    #   exit 0 — reached only after every final file (the --output CSV, plus
    #            the obs-format file when requested) has been materialized by
    #            an atomic os.replace of a fully written *.tmp and the
    #            pre-serialized success JSON has been printed
    #   exit 2 — failed-status JSON printed (validation errors included);
    #            *.tmp leftovers AND every final path this invocation had
    #            already materialized (`materialized`) are removed
    #            best-effort, so no file produced by THIS invocation persists
    #            on the failure path. A file from an earlier successful run
    #            persists only if this invocation had not yet replaced it;
    #            if it had, the cleanup removes that path rather than
    #            restoring the earlier file.
    csv_tmp = args.output + ".tmp"
    # Obs-format path is '<output stem>_obs_format.txt'. os.path.splitext
    # strips only the final extension of the LAST path component, so
    # directory names containing '.csv' are never rewritten, and a filename
    # without an extension still yields a distinct path. Because splitext's
    # extension is either '' or starts with '.', stem + '_obs_format.txt'
    # can never equal --output itself.
    obs_path = (os.path.splitext(args.output)[0] + "_obs_format.txt") if args.obs_format else None
    obs_tmp = obs_path + ".tmp" if obs_path else None
    materialized = []
    try:
        validate_inputs(args)

        if args.output_nc:
            df, stats = extract_from_gridded(
                args.output_nc, args.lat, args.lon, args.warmup
            )
        else:
            df, stats = extract_from_scalar(args.scalar_nc, args.warmup)

        if args.obs_format:
            stats["obs_format_path"] = obs_path

        # Serialize the success JSON BEFORE any file write so nothing
        # fallible remains between materializing the finals and printing.
        result_json = json.dumps(
            {"status": "success", "output_csv": args.output, **stats}, indent=2
        )

        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

        # ALL fallible content writes target *.tmp paths ...
        df.to_csv(csv_tmp, index=False, float_format="%.3f")
        if args.obs_format:
            with open(obs_tmp, "w") as f:
                f.write("stcd\tdates\tz\tQ\tname\n")
                for _, row in df.iterrows():
                    f.write(f"wflow\t{row['date'].strftime('%Y-%m-%d')}\t0\t{row['Q_m3s']:.3f}\twflow_output\n")

        # ... then the finals are materialized by consecutive os.replace
        # calls, each recorded so the failure path can undo it.
        if args.obs_format:
            os.replace(obs_tmp, obs_path)
            materialized.append(obs_path)
        os.replace(csv_tmp, args.output)
        materialized.append(args.output)

        print(result_json)
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(0)
    except Exception as e:
        for leftover in (csv_tmp, obs_tmp, *materialized):
            if leftover and os.path.exists(leftover):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(2)


if __name__ == "__main__":
    main()
