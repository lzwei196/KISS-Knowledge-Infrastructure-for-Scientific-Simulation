#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      apply_deltas_forcing
Stage:        s3_apply_deltas
Description:  Apply CMIP6 monthly deltas to baseline CMFD/MSWX forcing to
              produce projected future VIC forcing files.

Takes the existing forcing_1d NetCDF output (baseline period) and applies
monthly change factors from the delta file:
  - Precipitation: P_future = P_baseline * delta_pr(month)
  - Temperature:   T_future = T_baseline + delta_T(month)
  - Wind, pressure, radiation, humidity: unchanged (pass-through)

The output is a new set of forcing_1d-format NetCDF files that can be fed
directly to process_forcing.py for VIC ASCII generation.

Inputs:
  - BASELINE_FORCING_DIR: Directory with forcing_1d NetCDF files (temp_*, prec_*, etc.)
  - DELTA_FILE:           NetCDF file with monthly deltas (from compute_climate_deltas)
  - GRID_NC:              Basin grid file (for cell matching)
  - OUTPUT_DIR:           Where to save projected forcing files
  - TARGET_YEARS:         Year range for the projected forcing (reuses baseline
                          annual cycle with deltas applied)

Outputs:
  - temp_{source}_{year}.nc, prec_{source}_{year}.nc, etc. in OUTPUT_DIR

Exit codes:  0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import re
import calendar
import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASELINE_FORCING_DIR = ""   # e.g., "outputs/{basin}/vic_temp/forcing/forcing_1d"
DELTA_FILE = ""             # e.g., "outputs/{basin}/climate_projection/{model}_deltas.nc"
GRID_NC = ""                # e.g., "outputs/{basin}/vic_temp/grid/basin_grid.nc"
OUTPUT_DIR = ""             # where to save projected forcing
TARGET_YEARS = []           # e.g., [2041, 2042, ..., 2070]
BASIN_NAME = ""
MODEL_NAME = ""
SCENARIO = ""

# Override from sys.argv
if len(sys.argv) >= 8:
    BASELINE_FORCING_DIR = sys.argv[1]
    DELTA_FILE = sys.argv[2]
    GRID_NC = sys.argv[3]
    OUTPUT_DIR = sys.argv[4]
    BASIN_NAME = sys.argv[5]
    MODEL_NAME = sys.argv[6]
    SCENARIO = sys.argv[7]
    if len(sys.argv) >= 10:
        TARGET_YEARS = list(range(int(sys.argv[8]), int(sys.argv[9]) + 1))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Variables that get delta adjustments
DELTA_VARS = {
    "prec": {"delta_key": "delta_pr", "method": "multiplicative"},
    "temp": {"delta_key": "delta_tasmax", "method": "additive_mean"},
    # For mean temperature, average of tasmax and tasmin deltas
}

# Variables that pass through unchanged
PASSTHROUGH_VARS = ["pres", "srad", "lrad", "wind", "shum"]

# Map forcing file prefixes to internal var names
FORCING_VAR_PREFIXES = {
    "temp": "temp",
    "prec": "prec",
    "pres": "pres",
    "srad": "srad",
    "lrad": "lrad",
    "wind": "wind",
    "shum": "shum",
}


def validate_inputs():
    """Check all preconditions."""
    errors = []

    if not BASELINE_FORCING_DIR or not Path(BASELINE_FORCING_DIR).is_dir():
        errors.append(f"BASELINE_FORCING_DIR not found: {BASELINE_FORCING_DIR}")

    if not DELTA_FILE or not Path(DELTA_FILE).exists():
        errors.append(f"DELTA_FILE not found: {DELTA_FILE}")

    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR not set")

    if not TARGET_YEARS:
        errors.append("TARGET_YEARS not set")

    if errors:
        for e in errors:
            logger.error(e)
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    logger.info("Input validation passed.")


def get_baseline_files(forcing_dir):
    """Discover baseline forcing files and group by variable.

    Returns dict: {var_prefix: [file_paths sorted by name]}
    """
    files = {}
    for f in sorted(Path(forcing_dir).glob("*.nc")):
        for prefix in FORCING_VAR_PREFIXES:
            if f.name.startswith(prefix + "_"):
                files.setdefault(prefix, []).append(f)
                break
    return files


def extract_yyyymm(filename):
    """Extract YYYYMM from forcing filename like temp_CMFD_V0200_B-01_03hr_025deg_198001_bengbu.nc.

    Looks for 6-digit patterns that look like YYYYMM (year 1900-2100, month 01-12).
    """
    matches = re.findall(r'(\d{6})', filename)
    for m in matches:
        year = int(m[:4])
        month = int(m[4:6])
        if 1900 <= year <= 2100 and 1 <= month <= 12:
            return year, month
    # Fallback: try 4-digit year pattern at end of non-version-number segments
    matches4 = re.findall(r'_(\d{4})(?:_|\.|$)', filename)
    for m in matches4:
        year = int(m)
        if 1900 <= year <= 2100:
            return year, None
    return None, None


REQUIRED_DELTAS = ("delta_pr", "delta_tasmax", "delta_tasmin")


def plan_base_years(target_years, baseline_years):
    """Pick the baseline year to recycle onto each target year.

    Leap and non-leap baseline years are cycled SEPARATELY, each list in order, so a leap
    target gets a leap baseline (real Feb 29), a non-leap target gets a non-leap baseline
    (no Feb 29 to drop or duplicate), and every baseline year of a kind is used before any
    is reused. Returns a list of (base_year, drop_feb29), one per target year.
    A leap target with no leap year in the baseline cannot be filled without inventing
    Feb 29 data, so it raises. Non-leap targets with only leap baselines drop Feb 29.
    """
    leap = [y for y in baseline_years if calendar.isleap(y)]
    normal = [y for y in baseline_years if not calendar.isleap(y)]
    i_leap = i_norm = 0
    plan = []
    for ty in target_years:
        if calendar.isleap(ty):
            if not leap:
                raise RuntimeError(
                    f"target year {ty} is a leap year but the baseline ({baseline_years[0]}-"
                    f"{baseline_years[-1]}) has no leap year; Feb 29 cannot be filled without "
                    f"inventing data. Use a baseline that contains at least one leap year.")
            plan.append((leap[i_leap % len(leap)], False)); i_leap += 1
        elif normal:
            plan.append((normal[i_norm % len(normal)], False)); i_norm += 1
        else:
            plan.append((leap[i_leap % len(leap)], True)); i_leap += 1
    return plan


def match_delta_cells(delta_ds, forcing_ds):
    """Match delta file cells to forcing grid cells.

    Returns an index array: delta_indices[i] = index into delta 'cell' dim
    for forcing lat/lon index i. Uses nearest-neighbour matching.
    """
    delta_lats = delta_ds.coords["cell_lat"].values
    delta_lons = delta_ds.coords["cell_lon"].values

    # Get forcing grid coordinates (handle lat/lon, y/x, latitude/longitude)
    if "latitude" in forcing_ds.dims:
        f_lats = forcing_ds["latitude"].values
        f_lons = forcing_ds["longitude"].values
    elif "lat" in forcing_ds.dims:
        f_lats = forcing_ds["lat"].values
        f_lons = forcing_ds["lon"].values
    elif "y" in forcing_ds.dims:
        f_lats = forcing_ds["y"].values
        f_lons = forcing_ds["x"].values
    else:
        raise ValueError("Cannot determine forcing grid coordinates")

    # Build 2D grid of forcing coordinates
    flon2d, flat2d = np.meshgrid(f_lons, f_lats)

    # For each forcing grid point, find nearest delta cell
    indices = np.full(flat2d.shape, -1, dtype=int)
    for i in range(flat2d.shape[0]):
        for j in range(flat2d.shape[1]):
            dists = np.sqrt(
                (delta_lats - flat2d[i, j]) ** 2 +
                (delta_lons - flon2d[i, j]) ** 2
            )
            indices[i, j] = np.argmin(dists)

    return indices, flat2d.shape


def apply_delta_to_variable(ds, var_name, delta_ds, delta_key, method, cell_indices, grid_shape):
    """Apply monthly delta to a forcing variable.

    Args:
        ds: xr.Dataset with forcing data
        var_name: name of the data variable in ds
        delta_ds: xr.Dataset with delta data
        delta_key: variable name in delta_ds (e.g., "delta_pr")
        method: "multiplicative" or "additive" or "additive_mean"
        cell_indices: 2D array mapping grid (i,j) to delta cell index
        grid_shape: (n_lat, n_lon)

    Returns: modified xr.Dataset
    """
    if delta_key not in delta_ds:
        raise RuntimeError(f"Delta variable {delta_key} not found in delta file")

    da = ds[var_name].copy()
    delta_vals = delta_ds[delta_key].values  # shape: (12, n_cells)

    # Get time dimension
    times = da.coords["time"].values
    months = pd.DatetimeIndex(times).month  # 1-12

    # Apply deltas month by month
    data = da.values.copy()  # shape: (time, lat, lon) or (time, y, x)

    for t_idx in range(len(times)):
        m = months[t_idx]  # 1-12
        delta_month = delta_vals[m - 1, :]  # shape: (n_cells,)

        # Map delta to grid
        delta_grid = delta_month[cell_indices]  # shape: (n_lat, n_lon)

        if method == "multiplicative":
            data[t_idx] = data[t_idx] * delta_grid
            # Ensure non-negative for precipitation
            data[t_idx] = np.maximum(data[t_idx], 0.0)
        elif method == "additive":
            data[t_idx] = data[t_idx] + delta_grid
        elif method == "additive_mean":
            # Average of tasmax and tasmin deltas
            if not ("delta_tasmax" in delta_ds and "delta_tasmin" in delta_ds):
                raise RuntimeError("additive_mean needs both delta_tasmax and delta_tasmin")
            d_max = delta_ds["delta_tasmax"].values[m - 1, :]
            d_min = delta_ds["delta_tasmin"].values[m - 1, :]
            delta_mean = (d_max + d_min) / 2.0
            delta_grid = delta_mean[cell_indices]
            data[t_idx] = data[t_idx] + delta_grid

    da.values = data
    ds[var_name] = da
    return ds


def process():
    """Apply deltas to all baseline forcing files."""
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load delta file
    delta_ds = xr.open_dataset(DELTA_FILE)
    logger.info(f"Loaded deltas: {list(delta_ds.data_vars)}")
    missing_deltas = [k for k in REQUIRED_DELTAS if k not in delta_ds]
    if missing_deltas:
        # e.g. the 5 China models that carry precipitation only: without them temp (or prec)
        # would pass through unchanged while being labelled as projected.
        raise RuntimeError(
            f"delta file {DELTA_FILE} lacks {missing_deltas}; all of {list(REQUIRED_DELTAS)} are "
            f"needed (precipitation-only GCMs cannot drive this tool)")

    # Discover baseline files
    baseline_files = get_baseline_files(BASELINE_FORCING_DIR)
    if not baseline_files:
        logger.error(f"No forcing files found in {BASELINE_FORCING_DIR}")
        sys.exit(2)

    logger.info(f"Baseline variables: {list(baseline_files.keys())}")
    missing_vars = [v for v in FORCING_VAR_PREFIXES if v not in baseline_files]
    if missing_vars:
        raise RuntimeError(
            f"no baseline files for variable(s) {missing_vars} in {BASELINE_FORCING_DIR}; all 7 VIC "
            f"variables {list(FORCING_VAR_PREFIXES)} are required (check file prefixes)")

    # Group baseline files by variable and year-month
    # Structure: {var_prefix: {(year, month): filepath}}
    baseline_by_ym = {}
    baseline_years = set()
    for var, flist in baseline_files.items():
        baseline_by_ym[var] = {}
        for f in flist:
            y, m = extract_yyyymm(f.name)
            if y is not None and m is None:
                # The output name is made by replacing YYYYMM; annual files have none, so every
                # target year would overwrite the same file. Only monthly files are supported.
                raise RuntimeError(
                    f"{f.name}: annual (no YYYYMM) baseline files are not supported; this tool "
                    f"needs one forcing_1d file per variable per month")
            if y is not None:
                baseline_years.add(y)
                baseline_by_ym[var][(y, m)] = f

    baseline_years = sorted(baseline_years)
    n_baseline = len(baseline_years)
    logger.info(f"Baseline years: {baseline_years} ({n_baseline} years)")

    if not TARGET_YEARS:
        logger.error("TARGET_YEARS is empty")
        sys.exit(2)

    # Match delta cells to forcing grid (using first file)
    first_file = list(baseline_files.values())[0][0]
    ds_sample = xr.open_dataset(first_file)
    cell_indices, grid_shape = match_delta_cells(delta_ds, ds_sample)
    ds_sample.close()

    output_files = []

    missing_months = []
    plan = plan_base_years(TARGET_YEARS, baseline_years)
    for target_year, (base_year, drop_feb29) in zip(TARGET_YEARS, plan):
        # Leap and non-leap baseline years cycle separately (see plan_base_years)

        for var_prefix in baseline_files.keys():
            ym_dict = baseline_by_ym.get(var_prefix, {})
            # Process each month
            for month in range(1, 13):
                base_file = ym_dict.get((base_year, month))
                if base_file is None:
                    logger.error(f"No baseline file for {var_prefix} {base_year}-{month:02d}")
                    missing_months.append(f"{var_prefix} {base_year}-{month:02d}")
                    continue

                # Read baseline
                ds = xr.open_dataset(base_file)
                # Filter out spatial_ref and other non-data vars
                data_vars = [v for v in ds.data_vars if v != "spatial_ref"]
                if not data_vars:
                    ds.close()
                    continue
                data_var = data_vars[0]

                # Apply delta if applicable
                if var_prefix == "prec":
                    ds = apply_delta_to_variable(
                        ds, data_var, delta_ds, "delta_pr", "multiplicative",
                        cell_indices, grid_shape
                    )
                elif var_prefix == "temp":
                    ds = apply_delta_to_variable(
                        ds, data_var, delta_ds, "delta_tasmax", "additive_mean",
                        cell_indices, grid_shape
                    )
                # Other variables: pass through unchanged

                # Update time coordinates to target year. plan_base_years() matched leap
                # status, so only a leap baseline recycled onto a non-leap target needs Feb 29
                # dropped (never remapped onto Feb 28, which would duplicate time stamps).
                old_times = pd.DatetimeIndex(ds.coords["time"].values)
                if drop_feb29:
                    keep = ~((old_times.month == 2) & (old_times.day == 29))
                    ds = ds.isel(time=np.where(keep)[0])
                    old_times = old_times[keep]
                new_times = old_times.map(lambda t: t.replace(year=target_year))
                if new_times.has_duplicates:
                    raise RuntimeError(f"duplicate time stamps after recycling {base_file.name} onto {target_year}")
                ds.coords["time"] = new_times

                # Update attributes
                ds.attrs["projected_year"] = target_year
                ds.attrs["cmip6_model"] = MODEL_NAME
                ds.attrs["scenario"] = SCENARIO
                ds.attrs["delta_method"] = "multiplicative for prec, additive_mean for temp"

                # Save with same naming convention (replace YYYYMM)
                base_yyyymm = f"{base_year}{month:02d}"
                target_yyyymm = f"{target_year}{month:02d}"
                out_name = base_file.name.replace(base_yyyymm, target_yyyymm)
                out_path = out_dir / out_name
                ds.to_netcdf(out_path)
                ds.close()
                output_files.append(str(out_path))

        logger.info(f"  Year {target_year} done (baseline: {base_year})")

    delta_ds.close()
    if missing_months:
        raise RuntimeError(
            f"{len(missing_months)} baseline variable-month file(s) missing, projected forcing "
            f"would have gaps: {missing_months[:6]}")
    logger.info(f"Generated {len(output_files)} projected forcing files")

    return output_files


def validate_outputs(output_files):
    """Check output forcing files."""
    errors = []
    if not output_files:
        errors.append("No output files generated")

    for f in output_files[:3]:  # spot-check first 3
        p = Path(f)
        if not p.exists():
            errors.append(f"Missing: {f}")
        elif p.stat().st_size < 100:
            errors.append(f"Empty: {f}")

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
        output_files = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_files)

    result = {
        "status": "success",
        "model": MODEL_NAME,
        "scenario": SCENARIO,
        "basin": BASIN_NAME,
        "target_years": TARGET_YEARS,
        "n_files": len(output_files),
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)
