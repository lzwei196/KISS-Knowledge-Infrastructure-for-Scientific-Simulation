#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      compute_gridded_yield
Stage:        s8_yield_analysis
Description:  Aggregate single-cell WOFOST outputs into a gridded yield CSV
              for spatial analysis and visualization.

Inputs:
  - CELL_OUTPUTS_DIR: directory with per-cell WOFOST output CSVs
  - GRID_NC: basin grid NetCDF for cell coordinates
  - OUTPUT_FILE: gridded yield CSV path

Outputs:
  - CSV with lat, lon, twso_kgha, tagp_kgha, lai_max, dvs_final

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import logging
from pathlib import Path
import glob

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CELL_OUTPUTS_DIR = ""
GRID_NC = ""
OUTPUT_FILE = ""


def validate_inputs():
    errors = []
    if not CELL_OUTPUTS_DIR or not Path(CELL_OUTPUTS_DIR).is_dir():
        errors.append(f"CELL_OUTPUTS_DIR not found: {CELL_OUTPUTS_DIR}")
    if not OUTPUT_FILE:
        errors.append("OUTPUT_FILE not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import pandas as pd

    # Find all cell output CSVs
    csv_files = glob.glob(os.path.join(CELL_OUTPUTS_DIR, "daily_output_*.csv"))
    if not csv_files:
        csv_files = glob.glob(os.path.join(CELL_OUTPUTS_DIR, "*.csv"))

    logger.info(f"Found {len(csv_files)} cell output files")

    results = []
    for csv_file in csv_files:
        try:
            # Extract lat/lon from filename
            basename = os.path.basename(csv_file).replace('.csv', '')
            parts = basename.split('_')
            # Try to find lat/lon in filename
            lat = lon = None
            for i in range(len(parts) - 1):
                try:
                    lat = float(parts[-2])
                    lon = float(parts[-1])
                    break
                except (ValueError, IndexError):
                    continue

            if lat is None or lon is None:
                # Read from file content if available
                df = pd.read_csv(csv_file, index_col='day', parse_dates=True)
                if 'lat' in df.columns:
                    lat = df['lat'].iloc[0]
                    lon = df['lon'].iloc[0]
                else:
                    logger.warning(f"Cannot extract lat/lon from {csv_file}, skipping")
                    continue
            else:
                df = pd.read_csv(csv_file, index_col='day', parse_dates=True)

            twso = float(df['TWSO'].iloc[-1]) if 'TWSO' in df.columns else 0
            tagp = float(df['TAGP'].iloc[-1]) if 'TAGP' in df.columns else 0
            lai_max = float(df['LAI'].max()) if 'LAI' in df.columns else 0
            dvs_final = float(df['DVS'].iloc[-1]) if 'DVS' in df.columns else 0

            results.append({
                'lat': lat,
                'lon': lon,
                'twso_kgha': round(twso, 1),
                'tagp_kgha': round(tagp, 1),
                'lai_max': round(lai_max, 2),
                'dvs_final': round(dvs_final, 3),
                'harvest_index': round(twso / tagp, 3) if tagp > 0 else 0,
                'maturity_reached': dvs_final >= 2.0,
            })

        except Exception as e:
            logger.warning(f"Error processing {csv_file}: {e}")
            continue

    gridded = pd.DataFrame(results)

    os.makedirs(os.path.dirname(OUTPUT_FILE) or '.', exist_ok=True)
    gridded.to_csv(OUTPUT_FILE, index=False)

    # Summary statistics
    n_cells = len(gridded)
    n_mature = gridded['maturity_reached'].sum() if 'maturity_reached' in gridded else 0
    mean_yield = gridded['twso_kgha'].mean() if n_cells > 0 else 0
    n_zero = (gridded['twso_kgha'] <= 0).sum() if n_cells > 0 else 0

    logger.info(f"Gridded yield: {n_cells} cells, mean={mean_yield:.0f} kg/ha, "
                f"mature={n_mature}/{n_cells}, zero_yield={n_zero}")

    if n_zero > 0:
        logger.warning(f"{n_zero} cells have zero yield! Check weather units (dt_003, dt_004)")

    result = {
        "status": "success",
        "output_file": OUTPUT_FILE,
        "n_cells": n_cells,
        "n_mature": int(n_mature),
        "n_zero_yield": int(n_zero),
        "mean_yield_kgha": round(mean_yield, 1),
        "yield_range": f"{gridded['twso_kgha'].min():.0f} - {gridded['twso_kgha'].max():.0f}"
        if n_cells > 0 else "N/A",
    }
    return result


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        CELL_OUTPUTS_DIR = sys.argv[1]
        OUTPUT_FILE = sys.argv[2]
    if len(sys.argv) >= 4:
        GRID_NC = sys.argv[3]

    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Failed: {e}")
        sys.exit(2)
    print(json.dumps(result, indent=2))
    sys.exit(0)
