#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      compare_wofost_dssat
Stage:        s8_yield_analysis
Description:  Compare WOFOST and DSSAT gridded yield outputs for multi-model
              ensemble analysis. Merges by lat/lon, computes ensemble mean,
              model spread, and correlation statistics.

Inputs:
  - WOFOST_CSV: WOFOST gridded yield CSV (lat, lon, twso_kgha)
  - DSSAT_CSV: DSSAT gridded yield CSV (lat, lon, hwam_kgha)
  - OUTPUT_FILE: ensemble comparison CSV

Outputs:
  - CSV with per-cell WOFOST yield, DSSAT yield, ensemble mean, spread

Exit codes:
  0 — success, 1 — input error, 2 — processing error
"""

import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

WOFOST_CSV = ""
DSSAT_CSV = ""
OUTPUT_FILE = ""


def validate_inputs():
    errors = []
    if not WOFOST_CSV or not Path(WOFOST_CSV).exists():
        errors.append(f"WOFOST CSV not found: {WOFOST_CSV}")
    if not DSSAT_CSV or not Path(DSSAT_CSV).exists():
        errors.append(f"DSSAT CSV not found: {DSSAT_CSV}")
    if not OUTPUT_FILE:
        errors.append("OUTPUT_FILE not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import pandas as pd
    import numpy as np

    wofost = pd.read_csv(WOFOST_CSV)
    dssat = pd.read_csv(DSSAT_CSV)

    # Standardize column names
    wofost_yield_col = 'twso_kgha'
    dssat_yield_col = None
    for col in ['hwam_kgha', 'HWAM', 'hwam', 'yield_kgha', 'TWSO']:
        if col in dssat.columns:
            dssat_yield_col = col
            break

    if dssat_yield_col is None:
        logger.error(f"Cannot find yield column in DSSAT CSV. Columns: {list(dssat.columns)}")
        sys.exit(2)

    # Round coordinates for matching
    wofost['lat_r'] = wofost['lat'].round(4)
    wofost['lon_r'] = wofost['lon'].round(4)
    dssat['lat_r'] = dssat['lat'].round(4)
    dssat['lon_r'] = dssat['lon'].round(4)

    # Merge
    merged = wofost.merge(dssat[['lat_r', 'lon_r', dssat_yield_col]],
                          on=['lat_r', 'lon_r'], how='inner')

    if len(merged) == 0:
        logger.error("No matching grid cells between WOFOST and DSSAT!")
        logger.info(f"WOFOST lat range: {wofost['lat'].min():.4f} - {wofost['lat'].max():.4f}")
        logger.info(f"DSSAT lat range: {dssat['lat'].min():.4f} - {dssat['lat'].max():.4f}")
        sys.exit(2)

    # Ensemble statistics
    merged['yield_wofost'] = merged[wofost_yield_col]
    merged['yield_dssat'] = merged[dssat_yield_col]
    merged['yield_ensemble_mean'] = (merged['yield_wofost'] + merged['yield_dssat']) / 2
    merged['yield_spread'] = abs(merged['yield_wofost'] - merged['yield_dssat'])
    merged['yield_cv'] = merged[['yield_wofost', 'yield_dssat']].std(axis=1) / \
                          merged[['yield_wofost', 'yield_dssat']].mean(axis=1)

    # Save
    output_cols = ['lat', 'lon', 'yield_wofost', 'yield_dssat',
                   'yield_ensemble_mean', 'yield_spread', 'yield_cv']
    os.makedirs(os.path.dirname(OUTPUT_FILE) or '.', exist_ok=True)
    merged[output_cols].to_csv(OUTPUT_FILE, index=False)

    # Statistics
    corr = merged['yield_wofost'].corr(merged['yield_dssat'])
    bias = merged['yield_wofost'].mean() - merged['yield_dssat'].mean()

    result = {
        "status": "success",
        "output_file": OUTPUT_FILE,
        "n_matched_cells": len(merged),
        "n_wofost_cells": len(wofost),
        "n_dssat_cells": len(dssat),
        "wofost_mean_yield": round(merged['yield_wofost'].mean(), 1),
        "dssat_mean_yield": round(merged['yield_dssat'].mean(), 1),
        "ensemble_mean_yield": round(merged['yield_ensemble_mean'].mean(), 1),
        "mean_spread": round(merged['yield_spread'].mean(), 1),
        "correlation": round(corr, 3),
        "bias_wofost_minus_dssat": round(bias, 1),
    }

    logger.info(f"Ensemble: {len(merged)} cells, WOFOST={result['wofost_mean_yield']}, "
                f"DSSAT={result['dssat_mean_yield']}, corr={corr:.3f}")

    return result


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        WOFOST_CSV = sys.argv[1]
        DSSAT_CSV = sys.argv[2]
        OUTPUT_FILE = sys.argv[3]

    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Failed: {e}")
        sys.exit(2)
    print(json.dumps(result, indent=2))
    sys.exit(0)
