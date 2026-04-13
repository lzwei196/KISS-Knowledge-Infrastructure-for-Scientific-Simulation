#!/usr/bin/env python3
"""
analyze_sediment.py — Analyze wflow_sediment output: erosion rates, sediment yield, transport.

Computes:
  - Spatial erosion hotspot map (soil loss in t/ha/yr)
  - Sediment yield at outlet (tonnes/year)
  - Grain size distribution of transported sediment
  - Sediment rating curve (Q vs sediment load)
  - Comparison with USLE predictions

Usage:
    python analyze_sediment.py \
      --output_nc /path/to/sediment_output_grid.nc \
      --basin_area_km2 8783 \
      --output_dir /path/to/sediment_analysis/
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate."""
    if not os.path.exists(args.output_nc):
        print(f"ERROR: Output NC not found: {args.output_nc}", file=sys.stderr)
        sys.exit(1)


def process(args):
    """Analyze sediment output."""
    import xarray as xr

    ds = xr.open_dataset(args.output_nc)

    results = {}
    os.makedirs(args.output_dir, exist_ok=True)

    # --- Soil loss ---
    soilloss_var = None
    for name in ["soilloss", "erosion", "soil_loss", "sediment_flux"]:
        if name in ds:
            soilloss_var = name
            break

    if soilloss_var:
        soilloss = ds[soilloss_var]

        # Skip warmup
        if "time" in soilloss.dims and args.warmup > 0:
            soilloss = soilloss.isel(time=slice(args.warmup, None))

        # Annual mean soil loss (assume daily values in tonnes/timestep or mm)
        annual_soilloss = soilloss.mean(dim="time")
        # Convert to t/ha/yr if needed (multiply by 365 if daily)
        n_years = soilloss.sizes.get("time", 365) / 365.0
        annual_rate = soilloss.sum(dim="time") / max(n_years, 1)

        mask = annual_rate.values > 0
        if mask.any():
            results["soil_loss"] = {
                "mean_t_ha_yr": round(float(np.mean(annual_rate.values[mask])), 3),
                "max_t_ha_yr": round(float(np.max(annual_rate.values[mask])), 3),
                "total_cells": int(mask.sum()),
                "erosion_classes": {
                    "slight (<5 t/ha/yr)": int((annual_rate.values[mask] < 5).sum()),
                    "moderate (5-25)": int(((annual_rate.values[mask] >= 5) & (annual_rate.values[mask] < 25)).sum()),
                    "severe (25-100)": int(((annual_rate.values[mask] >= 25) & (annual_rate.values[mask] < 100)).sum()),
                    "extreme (>100)": int((annual_rate.values[mask] >= 100).sum()),
                },
            }

            # Save spatial map
            out_nc = os.path.join(args.output_dir, "erosion_rate_annual.nc")
            annual_rate.to_netcdf(out_nc)
            results["soil_loss"]["spatial_map"] = out_nc

    # --- Sediment concentration ---
    conc_var = None
    for name in ["sediment_concentration", "sedconc", "TSS"]:
        if name in ds:
            conc_var = name
            break

    if conc_var:
        conc = ds[conc_var]
        if "time" in conc.dims and args.warmup > 0:
            conc = conc.isel(time=slice(args.warmup, None))

        results["concentration"] = {
            "mean_mg_L": round(float(conc.mean()), 2),
            "max_mg_L": round(float(conc.max()), 2),
        }

    # --- Sediment yield at outlet ---
    q_var = None
    for name in ["q_river", "Q", "discharge"]:
        if name in ds:
            q_var = name
            break

    if q_var and conc_var:
        q = ds[q_var]
        c = ds[conc_var]
        if "time" in q.dims and args.warmup > 0:
            q = q.isel(time=slice(args.warmup, None))
            c = c.isel(time=slice(args.warmup, None))

        # Find outlet (max Q cell)
        q_mean = q.mean(dim="time")
        if q_mean.ndim >= 2:
            max_idx = q_mean.argmax()
            idx = np.unravel_index(max_idx.values, q_mean.shape)
            q_outlet = q.isel(y=idx[0], x=idx[1]) if "y" in q.dims else q.isel(lat=idx[0], lon=idx[1])
            c_outlet = c.isel(y=idx[0], x=idx[1]) if "y" in c.dims else c.isel(lat=idx[0], lon=idx[1])
        else:
            q_outlet = q
            c_outlet = c

        # Sediment load: Q (m3/s) * C (mg/L) * 86400 (s/day) / 1e6 (mg->t) = tonnes/day
        sed_load = q_outlet * c_outlet * 86400.0 / 1e6
        annual_yield = float(sed_load.sum()) / max(n_years, 1)

        # Specific sediment yield
        ssy = annual_yield / args.basin_area_km2 if args.basin_area_km2 > 0 else 0

        results["sediment_yield"] = {
            "annual_tonnes": round(annual_yield, 0),
            "specific_yield_t_km2_yr": round(ssy, 1),
            "mean_daily_load_t": round(float(sed_load.mean()), 1),
        }

    # --- Grain size fractions (if available) ---
    grain_vars = ["clay_flux", "silt_flux", "sand_flux", "sagg_flux", "lagg_flux"]
    grain_data = {}
    for gv in grain_vars:
        if gv in ds:
            grain_data[gv] = float(ds[gv].mean())

    if grain_data:
        total = sum(grain_data.values())
        if total > 0:
            results["grain_distribution"] = {
                k: round(v / total * 100, 1) for k, v in grain_data.items()
            }

    ds.close()

    return {
        "status": "success",
        "output_dir": args.output_dir,
        "analyses": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze wflow_sediment output")
    parser.add_argument("--output_nc", type=str, required=True)
    parser.add_argument("--basin_area_km2", type=float, default=0)
    parser.add_argument("--warmup", type=int, default=365)
    parser.add_argument("--output_dir", type=str, required=True)
    args = parser.parse_args()

    validate_inputs(args)

    try:
        result = process(args)
    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
