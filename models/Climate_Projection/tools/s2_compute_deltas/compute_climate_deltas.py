#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      compute_climate_deltas
Stage:        s2_compute_deltas
Description:  Compute monthly climate change signals (deltas) from CMIP6 data.

Compares CMIP6 future scenario vs CMIP6 historical (r1) to produce monthly
change factors for each basin grid cell:
  - Temperature: additive delta (deg C) → T_future = T_baseline + delta_T
  - Precipitation: multiplicative ratio → P_future = P_baseline * ratio_P

Inputs:
  - HIST_DIR:     Directory with extracted CMIP6 r1 (historical) NetCDF files
  - FUTURE_DIR:   Directory with extracted CMIP6 SSP NetCDF files
  - MODEL_NAME:   CMIP6 model name
  - SCENARIO:     Future SSP scenario ("126", "245", "585")
  - BASIN_NAME:   Basin identifier
  - REF_PERIOD:   Reference period tuple (start_year, end_year) for historical baseline
  - FUTURE_PERIOD: Future period tuple (start_year, end_year) for change signal
  - OUTPUT_DIR:   Where to save the delta file

Outputs:
  - {MODEL}_{SCENARIO}_deltas_{BASIN}_{future_start}-{future_end}.nc
    Variables: delta_pr (ratio), delta_tasmax (degC), delta_tasmin (degC)
    Dimensions: (month=12, cell=N)

Exit codes:  0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
import xarray as xr
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HIST_DIR = ""          # Directory with *_r1_*_{basin}.nc files
FUTURE_DIR = ""        # Directory with *_{scenario}_*_{basin}.nc files
MODEL_NAME = ""        # e.g., "ACCESS-CM2"
SCENARIO = ""          # "126", "245", "585"
BASIN_NAME = ""
REF_PERIOD = (1981, 2010)     # 30-year historical reference (within r1: 1961-2014)
FUTURE_PERIOD = (2041, 2070)  # 30-year future window
OUTPUT_DIR = ""

# Override from sys.argv if provided
if len(sys.argv) >= 9:
    HIST_DIR = sys.argv[1]
    FUTURE_DIR = sys.argv[2]
    MODEL_NAME = sys.argv[3]
    SCENARIO = sys.argv[4]
    BASIN_NAME = sys.argv[5]
    REF_PERIOD = (int(sys.argv[6].split("-")[0]), int(sys.argv[6].split("-")[1]))
    FUTURE_PERIOD = (int(sys.argv[7].split("-")[0]), int(sys.argv[7].split("-")[1]))
    OUTPUT_DIR = sys.argv[8]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Minimum precipitation threshold for ratio computation (mm/day)
# Prevents division by zero and unrealistic ratios in dry months
PR_FLOOR = 0.1  # mm/day


def validate_inputs():
    """Check all preconditions."""
    errors = []

    for label, d in [("HIST_DIR", HIST_DIR), ("FUTURE_DIR", FUTURE_DIR), ("OUTPUT_DIR", OUTPUT_DIR)]:
        if not d:
            errors.append(f"{label} not set")

    if SCENARIO not in ("126", "245", "585"):
        errors.append(f"Invalid scenario for future: {SCENARIO}")

    ref_start, ref_end = REF_PERIOD
    if ref_start < 1961 or ref_end > 2014 or ref_start >= ref_end:
        errors.append(f"REF_PERIOD {REF_PERIOD} must be within 1961-2014")

    fut_start, fut_end = FUTURE_PERIOD
    if fut_start < 2015 or fut_end > 2099 or fut_start >= fut_end:
        errors.append(f"FUTURE_PERIOD {FUTURE_PERIOD} must be within 2015-2099")

    if not MODEL_NAME:
        errors.append("MODEL_NAME not set")

    if errors:
        for e in errors:
            logger.error(e)
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    logger.info("Input validation passed.")


def load_variable(directory, model, scenario, var, basin):
    """Load a CMIP6 extracted variable NetCDF."""
    pattern = f"{model}_{scenario}_{var}_{basin}.nc"
    path = Path(directory) / pattern
    if not path.exists():
        raise FileNotFoundError(f"Expected file not found: {path}")
    ds = xr.open_dataset(path)
    return ds


def monthly_climatology(da, start_year, end_year):
    """Compute 12-month climatology (mean of each month) for a period.

    Args:
        da: xr.DataArray with 'time' dimension
        start_year, end_year: inclusive year range

    Returns:
        xr.DataArray with dims (month=12, cell=N)
    """
    subset = da.sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31"))
    return subset.groupby("time.month").mean("time")


def process():
    """Compute monthly deltas for all three variables."""
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    ref_start, ref_end = REF_PERIOD
    fut_start, fut_end = FUTURE_PERIOD

    deltas = {}
    cell_lats = None
    cell_lons = None

    for var in ["pr", "tasmax", "tasmin"]:
        logger.info(f"Processing {var}...")

        # Load historical and future
        try:
            ds_hist = load_variable(HIST_DIR, MODEL_NAME, "r1", var, BASIN_NAME)
            ds_fut = load_variable(FUTURE_DIR, MODEL_NAME, SCENARIO, var, BASIN_NAME)
        except FileNotFoundError as e:
            logger.warning(f"Skipping {var}: {e}")
            continue

        da_hist = ds_hist[var]
        da_fut = ds_fut[var]

        # Get cell coordinates
        if cell_lats is None:
            cell_lats = da_hist.coords["cell_lat"].values
            cell_lons = da_hist.coords["cell_lon"].values

        # Compute monthly climatologies
        clim_hist = monthly_climatology(da_hist, ref_start, ref_end)
        clim_fut = monthly_climatology(da_fut, fut_start, fut_end)

        if var == "pr":
            # Multiplicative ratio for precipitation
            # Floor historical to avoid division by zero
            clim_hist_safe = clim_hist.where(clim_hist >= PR_FLOOR, PR_FLOOR)
            delta = clim_fut / clim_hist_safe
            # Cap extreme ratios (e.g., > 5x or < 0.1x)
            delta = delta.clip(min=0.1, max=5.0)
            delta_name = "delta_pr"
            delta_attrs = {
                "long_name": "Precipitation change ratio (future/historical)",
                "units": "ratio",
                "method": "multiplicative",
                "note": f"Apply as: P_projected = P_baseline * delta_pr. "
                        f"Capped at [0.1, 5.0]. Historical floor = {PR_FLOOR} mm/day.",
            }
        else:
            # Additive delta for temperature
            delta = clim_fut - clim_hist
            delta_name = f"delta_{var}"
            delta_attrs = {
                "long_name": f"{var} change (future - historical)",
                "units": "degC",
                "method": "additive",
                "note": f"Apply as: T_projected = T_baseline + delta_{var}",
            }

        deltas[delta_name] = (delta.values, delta_attrs)
        ds_hist.close()
        ds_fut.close()

        logger.info(f"  {delta_name}: monthly mean range = "
                    f"[{delta.values.min():.3f}, {delta.values.max():.3f}]")

    if not deltas:
        logger.error("No deltas computed — no variable files found")
        sys.exit(2)

    # Build output dataset
    months = np.arange(1, 13)
    data_vars = {}
    for name, (values, attrs) in deltas.items():
        data_vars[name] = xr.DataArray(
            values,
            dims=["month", "cell"],
            coords={
                "month": months,
                "cell_lat": ("cell", cell_lats),
                "cell_lon": ("cell", cell_lons),
            },
            attrs=attrs,
        )

    ds_out = xr.Dataset(
        data_vars,
        attrs={
            "source": f"CMIP6 delta change signals — {MODEL_NAME} {SCENARIO}",
            "basin": BASIN_NAME,
            "reference_period": f"{ref_start}-{ref_end}",
            "future_period": f"{fut_start}-{fut_end}",
            "method": "Delta change: multiplicative for precipitation, additive for temperature",
            "created": datetime.now().isoformat(),
        },
    )

    out_file = out_dir / f"{MODEL_NAME}_{SCENARIO}_deltas_{BASIN_NAME}_{fut_start}-{fut_end}.nc"
    ds_out.to_netcdf(out_file)
    ds_out.close()
    logger.info(f"Saved delta file: {out_file}")

    return str(out_file)


def validate_outputs(output_path):
    """Check output delta file."""
    errors = []
    p = Path(output_path)
    if not p.exists():
        errors.append(f"Output not created: {output_path}")
    else:
        ds = xr.open_dataset(output_path)
        for var in ["delta_pr", "delta_tasmax", "delta_tasmin"]:
            if var in ds:
                vals = ds[var].values
                if np.all(np.isnan(vals)):
                    errors.append(f"{var} is all NaN")
                if var == "delta_pr":
                    if np.any(vals < 0):
                        errors.append(f"{var} contains negative ratios")
        ds.close()

    if errors:
        for e in errors:
            logger.error(e)
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(3)

    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs()

    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)

    result = {
        "status": "success",
        "model": MODEL_NAME,
        "scenario": SCENARIO,
        "basin": BASIN_NAME,
        "reference_period": list(REF_PERIOD),
        "future_period": list(FUTURE_PERIOD),
        "output_file": output_path,
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)
