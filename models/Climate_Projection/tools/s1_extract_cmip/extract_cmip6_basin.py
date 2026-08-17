#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      extract_cmip6_basin
Stage:        s1_extract_cmip
Description:  Extract CMIP6 bias-corrected data for a basin's VIC grid cells.

Reads the tab-separated CMIP6 text files (Cmip6BaisCorrect_for_China), matches
basin grid cells to CMIP6 cells by nearest-neighbour on the 0.25-degree grid,
and outputs per-variable NetCDF files clipped to the basin.

Inputs:
  - CMIP6_ROOT: Path to Cmip6BaisCorrect_for_China directory
  - GRID_NC:    VIC basin grid file (basin_grid.nc)
  - MODEL_NAME: CMIP6 model name (e.g., "ACCESS-CM2")
  - SCENARIO:   CMIP6 scenario ("r1", "126", "245", "585")
  - OUTPUT_DIR:  Where to write output NetCDF files

Outputs:
  - {MODEL}_{SCENARIO}_pr_{BASIN}.nc       — daily precipitation (mm/day)
  - {MODEL}_{SCENARIO}_tasmax_{BASIN}.nc   — daily max temperature (deg C)
  - {MODEL}_{SCENARIO}_tasmin_{BASIN}.nc   — daily min temperature (deg C)

Exit codes:  0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CMIP6_ROOT = ""        # e.g., "KISSPATH_DATA/CMIP_China/Cmip6BaisCorrect_for_China"
GRID_NC = ""           # e.g., "outputs/{basin}/vic_temp/grid/basin_grid.nc"
MODEL_NAME = ""        # e.g., "ACCESS-CM2"
SCENARIO = ""          # "r1", "126", "245", "585"
OUTPUT_DIR = ""        # where to save output
BASIN_NAME = ""        # for output filename, e.g., "bengbu"

# Override from sys.argv if provided
if len(sys.argv) >= 7:
    CMIP6_ROOT = sys.argv[1]
    GRID_NC = sys.argv[2]
    MODEL_NAME = sys.argv[3]
    SCENARIO = sys.argv[4]
    OUTPUT_DIR = sys.argv[5]
    BASIN_NAME = sys.argv[6]

# ---------------------------------------------------------------------------
# CMIP6 file naming convention
# ---------------------------------------------------------------------------
CMIP6_FILE_MAP = {
    "pr":     "Cor_{model}_PreDaily.txt",
    "tasmax": "Cor_{model}_tasmaxDaily.txt",
    "tasmin": "Cor_{model}_tasminDaily.txt",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    """Check all preconditions."""
    errors = []

    if not CMIP6_ROOT or not Path(CMIP6_ROOT).is_dir():
        errors.append(f"CMIP6_ROOT not found: {CMIP6_ROOT}")

    if not GRID_NC or not Path(GRID_NC).exists():
        errors.append(f"Grid NC file not found: {GRID_NC}")

    if SCENARIO not in ("r1", "126", "245", "585"):
        errors.append(f"Invalid scenario: {SCENARIO}. Must be r1, 126, 245, or 585.")

    if not MODEL_NAME:
        errors.append("MODEL_NAME not set")

    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR not set")

    if not BASIN_NAME:
        errors.append("BASIN_NAME not set")

    # Check that CMIP6 files exist for this model
    if Path(CMIP6_ROOT).is_dir():
        pr_dir = Path(CMIP6_ROOT) / "pr" / SCENARIO
        pr_file = pr_dir / CMIP6_FILE_MAP["pr"].format(model=MODEL_NAME)
        if not pr_file.exists():
            errors.append(f"CMIP6 pr file not found: {pr_file}")

    if errors:
        for e in errors:
            logger.error(e)
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    logger.info("Input validation passed.")


def read_cmip6_lonlat(cmip6_file):
    """Read lon/lat arrays from the first two rows of a CMIP6 text file.

    Returns (lons, lats) as 1D numpy arrays of length N_cells.
    """
    with open(cmip6_file, 'r') as f:
        line1 = f.readline().strip().split('\t')
        line2 = f.readline().strip().split('\t')

    # Skip first 3 columns (NaN, NaN, NaN)
    lons = np.array([float(x) for x in line1[3:]])
    lats = np.array([float(x) for x in line2[3:]])
    return lons, lats


def find_matching_columns(cmip6_lons, cmip6_lats, basin_lons, basin_lats, tol=0.26):
    """Find CMIP6 column indices matching basin grid cells.

    Both grids are 0.25-degree, so matches should be exact or within tol.
    Returns list of (basin_idx, cmip6_col_idx) tuples and unmatched basin cells.
    """
    matches = []
    unmatched = []

    for bi, (blon, blat) in enumerate(zip(basin_lons, basin_lats)):
        # Euclidean distance on the flat grid
        dists = np.sqrt((cmip6_lons - blon) ** 2 + (cmip6_lats - blat) ** 2)
        min_idx = np.argmin(dists)
        min_dist = dists[min_idx]

        if min_dist <= tol:
            matches.append((bi, min_idx))
        else:
            unmatched.append((bi, blon, blat, min_dist))

    return matches, unmatched


def read_cmip6_data(cmip6_file, col_indices):
    """Read CMIP6 data for specific columns (0-based into the data columns).

    Returns (dates, data) where dates is array of datetime, data is (N_days, N_cells).
    The col_indices are 0-based relative to the data columns (after Year/Month/Day).
    """
    logger.info(f"Reading {cmip6_file} ...")

    # Read only needed columns: 0=year, 1=month, 2=day, then data columns offset by 3
    usecols = [0, 1, 2] + [idx + 3 for idx in col_indices]

    df = pd.read_csv(
        cmip6_file, sep='\t', header=None, skiprows=2,
        usecols=usecols, dtype={0: int, 1: int, 2: int},
        engine='c', low_memory=False
    )

    # Build dates from first 3 columns
    years = df.iloc[:, 0].values
    months = df.iloc[:, 1].values
    days = df.iloc[:, 2].values
    dates = pd.to_datetime(
        {'year': years, 'month': months, 'day': days}
    )

    # Data columns (everything after year/month/day)
    data = df.iloc[:, 3:].values.astype(np.float32)

    logger.info(f"  Read {len(dates)} days x {data.shape[1]} cells")
    return dates, data


def process():
    """Extract CMIP6 data for basin grid cells and save as NetCDF."""
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Read basin grid (handle both lat/lon and y/x dimension naming)
    ds_grid = xr.open_dataset(GRID_NC)
    if 'lat' in ds_grid.dims or 'lat' in ds_grid.coords:
        lat_vals = ds_grid['lat'].values
        lon_vals = ds_grid['lon'].values
    elif 'y' in ds_grid.dims or 'y' in ds_grid.coords:
        lat_vals = ds_grid['y'].values
        lon_vals = ds_grid['x'].values
    else:
        logger.error("Cannot parse grid file — expected 'lat'/'lon' or 'y'/'x' dimensions")
        sys.exit(2)

    if 'mask' in ds_grid:
        mask = ds_grid['mask'].values
        valid = np.argwhere(~np.isnan(mask) & (mask > 0))
        basin_lats = lat_vals[valid[:, 0]]
        basin_lons = lon_vals[valid[:, 1]]
    else:
        lon2d, lat2d = np.meshgrid(lon_vals, lat_vals)
        basin_lats = lat2d.ravel()
        basin_lons = lon2d.ravel()
    ds_grid.close()

    n_basin_cells = len(basin_lats)
    logger.info(f"Basin has {n_basin_cells} grid cells")

    # 2. Read CMIP6 lon/lat from the first variable file
    pr_file = Path(CMIP6_ROOT) / "pr" / SCENARIO / CMIP6_FILE_MAP["pr"].format(model=MODEL_NAME)
    cmip6_lons, cmip6_lats = read_cmip6_lonlat(pr_file)
    logger.info(f"CMIP6 grid: {len(cmip6_lons)} cells")

    # 3. Match basin cells to CMIP6 columns
    matches, unmatched = find_matching_columns(cmip6_lons, cmip6_lats, basin_lons, basin_lats)
    logger.info(f"Matched: {len(matches)}/{n_basin_cells} cells")

    if unmatched:
        logger.warning(f"Unmatched cells: {len(unmatched)}")
        for bi, blon, blat, d in unmatched[:5]:
            logger.warning(f"  Cell ({blat:.4f}, {blon:.4f}) nearest CMIP6 at {d:.4f} deg")

    if len(matches) == 0:
        logger.error("No CMIP6 cells match the basin grid. Is the basin inside China?")
        sys.exit(2)

    # Extract column indices for CMIP6 data
    # Multiple VIC cells (0.25°) may map to same CMIP6 cell (0.5°) — handle many-to-one
    basin_indices = [m[0] for m in matches]
    cmip6_col_indices = [m[1] for m in matches]
    matched_lats = basin_lats[basin_indices]
    matched_lons = basin_lons[basin_indices]

    # Deduplicate CMIP6 columns for efficient reading
    unique_cmip6_cols = sorted(set(cmip6_col_indices))
    col_remap = {orig: new for new, orig in enumerate(unique_cmip6_cols)}
    # For each basin cell, which column in the deduplicated data to use
    basin_to_unique = [col_remap[c] for c in cmip6_col_indices]
    logger.info(f"Unique CMIP6 columns to read: {len(unique_cmip6_cols)} (from {len(cmip6_col_indices)} basin cells)")

    # 4. Process each variable
    output_files = []
    variables = {"pr": "precipitation", "tasmax": "tasmax", "tasmin": "tasmin"}

    for var, long_name in variables.items():
        var_dir = Path(CMIP6_ROOT) / var / SCENARIO
        file_pattern = CMIP6_FILE_MAP.get(var)
        if file_pattern is None:
            logger.warning(f"No file pattern for variable {var}, skipping")
            continue

        cmip6_file = var_dir / file_pattern.format(model=MODEL_NAME)
        if not cmip6_file.exists():
            logger.warning(f"File not found: {cmip6_file}, skipping variable {var}")
            continue

        dates, data_unique = read_cmip6_data(cmip6_file, unique_cmip6_cols)

        # Expand back to basin cell dimension (many-to-one: some columns reused)
        data = data_unique[:, basin_to_unique]

        # Build NetCDF dataset
        units = "mm/day" if var == "pr" else "degC"
        ds = xr.Dataset(
            {
                var: xr.DataArray(
                    data,
                    dims=["time", "cell"],
                    coords={
                        "time": dates,
                        "cell_lat": ("cell", matched_lats),
                        "cell_lon": ("cell", matched_lons),
                    },
                    attrs={
                        "long_name": long_name,
                        "units": units,
                        "cmip6_model": MODEL_NAME,
                        "scenario": SCENARIO,
                    },
                )
            },
            attrs={
                "source": f"CMIP6 Bias-Corrected for China — {MODEL_NAME} {SCENARIO}",
                "basin": BASIN_NAME,
                "created": datetime.now().isoformat(),
            },
        )

        out_file = out_dir / f"{MODEL_NAME}_{SCENARIO}_{var}_{BASIN_NAME}.nc"
        ds.to_netcdf(out_file)
        ds.close()
        output_files.append(str(out_file))
        logger.info(f"Saved: {out_file}")

    return output_files


def validate_outputs(output_files):
    """Check that output NetCDF files were created with valid data."""
    errors = []
    for f in output_files:
        p = Path(f)
        if not p.exists():
            errors.append(f"Output file not created: {f}")
            continue
        if p.stat().st_size < 1000:
            errors.append(f"Output file suspiciously small: {f} ({p.stat().st_size} bytes)")

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
        "output_files": output_files,
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)
