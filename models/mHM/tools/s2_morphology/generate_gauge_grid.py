#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      generate_gauge_grid
Stage:        s2_morphology
Description:  Generate idgauges.asc grid with gauge location marked.

The idgauges.asc grid has the gauge ID at the gauge cell and 0 elsewhere.
NODATA (-9999) where the domain has nodata.

CRITICAL: The gauge ID must match the evaluation_gauges namelist in mhm.nml
and the gauge filename (e.g., Gauge_id=398 -> file 00398.txt).

Inputs:
  - CONFIG_PATH: config.json
  - DOMAIN_INFO_PATH: domain_info.json
  - GAUGE_LAT, GAUGE_LON: gauge coordinates
  - GAUGE_ID: integer gauge ID

Outputs:
  - idgauges.asc in input/morph/
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = ""
DOMAIN_INFO_PATH = ""
GAUGE_LAT = 0.0
GAUGE_LON = 0.0
GAUGE_ID = 1

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--domain_info", required=True)
    parser.add_argument("--gauge_lat", type=float, required=True)
    parser.add_argument("--gauge_lon", type=float, required=True)
    parser.add_argument("--gauge_id", type=int, default=1)
    args = parser.parse_args()
    CONFIG_PATH = args.config
    DOMAIN_INFO_PATH = args.domain_info
    GAUGE_LAT = args.gauge_lat
    GAUGE_LON = args.gauge_lon
    GAUGE_ID = args.gauge_id


def write_ascii_grid(filepath, data, header):
    with open(filepath, 'w') as f:
        f.write(f"ncols         {header['ncols']}\n")
        f.write(f"nrows         {header['nrows']}\n")
        f.write(f"xllcorner     {header['xllcorner']}\n")
        f.write(f"yllcorner     {header['yllcorner']}\n")
        f.write(f"cellsize      {header['cellsize']}\n")
        f.write(f"NODATA_value  {header['NODATA_value']}\n")
        nodata = header['NODATA_value']
        for row in data:
            vals = [str(int(nodata)) if np.isnan(v) or v == nodata else str(int(v)) for v in row]
            f.write(" ".join(vals) + "\n")


def validate_inputs():
    errors = []
    if not CONFIG_PATH or not Path(CONFIG_PATH).exists():
        errors.append(f"Config not found: {CONFIG_PATH}")
    if not DOMAIN_INFO_PATH or not Path(DOMAIN_INFO_PATH).exists():
        errors.append(f"Domain info not found: {DOMAIN_INFO_PATH}")
    if GAUGE_LAT == 0 and GAUGE_LON == 0:
        errors.append("GAUGE_LAT and GAUGE_LON must be set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    config = json.load(open(CONFIG_PATH))
    domain_info = json.load(open(DOMAIN_INFO_PATH))
    header = domain_info["header_L0"]
    morph_dir = Path(config["output_dir"]) / "input" / "morph"

    nrows = header["nrows"]
    ncols = header["ncols"]
    xll = header["xllcorner"]
    yll = header["yllcorner"]
    cs = header["cellsize"]

    # Create zero grid
    gauge_grid = np.zeros((nrows, ncols), dtype=np.int32)

    # Find the cell containing the gauge
    col = int((GAUGE_LON - xll) / cs)
    row = int((yll + nrows * cs - GAUGE_LAT) / cs)

    # Clamp to grid
    col = max(0, min(ncols - 1, col))
    row = max(0, min(nrows - 1, row))

    gauge_grid[row, col] = GAUGE_ID
    logger.info(f"Gauge {GAUGE_ID} placed at row={row}, col={col} "
               f"(lat={GAUGE_LAT}, lon={GAUGE_LON})")

    # Apply nodata mask from DEM
    dem_path = morph_dir / "dem.asc"
    if dem_path.exists():
        with open(dem_path) as f:
            for _ in range(6):
                f.readline()
            dem_data = [[float(x) for x in line.split()] for line in f]
            dem_arr = np.array(dem_data)
            gauge_grid[dem_arr == -9999] = -9999

    # Ensure gauge cell is not nodata
    if gauge_grid[row, col] == -9999:
        logger.warning("Gauge location falls on NODATA cell! Searching nearby...")
        found = False
        for r in range(1, 5):
            for dr in range(-r, r+1):
                for dc in range(-r, r+1):
                    nr, nc = row + dr, col + dc
                    if 0 <= nr < nrows and 0 <= nc < ncols and gauge_grid[nr, nc] != -9999:
                        gauge_grid[nr, nc] = GAUGE_ID
                        logger.info(f"  Moved gauge to row={nr}, col={nc}")
                        found = True
                        break
                if found:
                    break
            if found:
                break

    write_ascii_grid(morph_dir / "idgauges.asc", gauge_grid.astype(float), header)

    result = {
        "status": "success",
        "gauge_id": GAUGE_ID,
        "gauge_row": row,
        "gauge_col": col,
        "file": "idgauges.asc",
    }
    print(json.dumps(result, indent=2))
    return str(morph_dir / "idgauges.asc")


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Missing: {output_path}")
        sys.exit(3)


if __name__ == "__main__":
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
