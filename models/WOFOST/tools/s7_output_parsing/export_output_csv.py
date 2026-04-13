#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      export_output_csv
Stage:        s7_output_parsing
Description:  Export WOFOST simulation output to analysis-ready CSV with
              lat/lon identifiers for gridded runs.

Inputs:
  - OUTPUT_CSV: raw WOFOST output CSV
  - LAT, LON: grid cell coordinates
  - EXPORT_FILE: output file path

Outputs:
  - CSV with date, lat, lon, and WOFOST variables

Exit codes:
  0 — success, 2 — processing error
"""

import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_CSV = ""
LAT = 0.0
LON = 0.0
EXPORT_FILE = ""


def process():
    import pandas as pd

    df = pd.read_csv(OUTPUT_CSV, index_col='day', parse_dates=True)
    df['lat'] = LAT
    df['lon'] = LON

    # Reorder columns: lat, lon first
    cols = ['lat', 'lon'] + [c for c in df.columns if c not in ('lat', 'lon')]
    df = df[cols]

    os.makedirs(os.path.dirname(EXPORT_FILE) or '.', exist_ok=True)
    df.to_csv(EXPORT_FILE)
    logger.info(f"Exported: {EXPORT_FILE} ({len(df)} rows)")

    return {"status": "success", "output_file": EXPORT_FILE, "n_rows": len(df)}


if __name__ == "__main__":
    if len(sys.argv) >= 5:
        OUTPUT_CSV = sys.argv[1]
        LAT = float(sys.argv[2])
        LON = float(sys.argv[3])
        EXPORT_FILE = sys.argv[4]

    if not OUTPUT_CSV or not Path(OUTPUT_CSV).exists():
        logger.error(f"Not found: {OUTPUT_CSV}")
        sys.exit(1)
    if not EXPORT_FILE:
        logger.error("EXPORT_FILE not set")
        sys.exit(1)

    try:
        result = process()
    except Exception as e:
        logger.error(f"Failed: {e}")
        sys.exit(2)
    print(json.dumps(result, indent=2))
    sys.exit(0)
