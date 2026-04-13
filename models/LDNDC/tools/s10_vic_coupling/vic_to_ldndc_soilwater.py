#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      vic_to_ldndc_soilwater
Stage:        s10_vic_coupling
Description:  Extract VIC daily soil moisture for LDNDC initial conditions and
              dynamic soil water coupling. Maps VIC 3-layer mm depths to
              volumetric water content (cm³/cm³) per LDNDC soil horizon.

VIC result file format (22-column, tab-separated, 2-line header):
  Line 1: # SIMULATION: ...
  Line 2: # MODEL_VERSION: ...
  Line 3: YEAR MONTH DAY OUT_PREC OUT_RAINF OUT_SNOWF OUT_AIR_TEMP
           OUT_SWDOWN OUT_LWDOWN OUT_PRESSURE OUT_WIND OUT_DENSITY
           OUT_REL_HUMID OUT_QAIR OUT_VP OUT_VPD
           OUT_RUNOFF OUT_BASEFLOW OUT_EVAP OUT_SWE
           OUT_SOIL_MOIST_0 OUT_SOIL_MOIST_1 OUT_SOIL_MOIST_2 OUT_ALBEDO

  OUT_SOIL_MOIST_0/1/2 are in mm (total water depth per layer).

Conversion to volumetric: theta [cm³/cm³] = SM_mm / (depth_m × 1000)

Inputs (set below or pass as CLI args):
  VIC_RESULT_DIR   : directory with VIC flux output files (huaihe_fluxes_*.txt)
  LAT, LON         : target grid cell coordinates
  LAYER_DEPTHS_M   : VIC layer depths in metres (default: [0.1, 0.3, 1.5])
  START_DATE       : optional filter start date (YYYY-MM-DD)
  END_DATE         : optional filter end date (YYYY-MM-DD)
  OUTPUT_CSV       : path to write daily theta CSV

Output CSV columns: date, theta_layer1, theta_layer2, theta_layer3

Also returns JSON summary with mean/max/min theta per layer for LDNDC
initial condition setup (use mean-of-first-month as LDNDC initial SWC).

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VIC_RESULT_DIR   = ""                # e.g., "outputs/hefei_2000-2001/vic_result"
LAT              = 0.0               # e.g., 31.1250
LON              = 0.0               # e.g., 116.6250
LAYER_DEPTHS_M   = [0.1, 0.3, 1.5]  # VIC soil layer depths [m]
START_DATE       = ""                # optional: "2000-01-01"
END_DATE         = ""                # optional: "2001-12-31"
OUTPUT_CSV       = ""                # e.g., "outputs/chaohu/ldndc/soil_water.csv"

# Override from CLI
if len(sys.argv) >= 5:
    VIC_RESULT_DIR = sys.argv[1]
    LAT            = float(sys.argv[2])
    LON            = float(sys.argv[3])
    OUTPUT_CSV     = sys.argv[4]
if len(sys.argv) >= 6:
    START_DATE = sys.argv[5]
if len(sys.argv) >= 7:
    END_DATE = sys.argv[6]

# Column indices in 22-col VIC output (0-indexed after skipping header lines)
# YEAR=0, MONTH=1, DAY=2, ..., SM_0=19, SM_1=20, SM_2=21
COL_YEAR  = 0
COL_MONTH = 1
COL_DAY   = 2
# VIC 22-col output column indices (0-indexed from YEAR):
# YEAR(0) MONTH(1) DAY(2) PREC(3) RAINF(4) SNOWF(5) AIRTEMP(6)
# SWDOWN(7) LWDOWN(8) PRES(9) WIND(10) DENSITY(11) RELHUM(12)
# QAIR(13) VP(14) VPD(15) RUNOFF(16) BASEFLOW(17) EVAP(18) SWE(19)
# SOIL_MOIST_0(20) SOIL_MOIST_1(21) SOIL_MOIST_2(22) ALBEDO(23)
COL_SM    = [20, 21, 22]   # OUT_SOIL_MOIST_0/1/2

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_result_file(result_dir, lat, lon):
    """Find VIC result flux file by lat/lon from filename."""
    d = Path(result_dir)
    for tol in [0.001, 0.01, 0.05]:
        for f in d.iterdir():
            name = f.name
            tokens = re.findall(r"-?\d+\.\d+", name)
            lats_in = [float(t) for t in tokens if 10 <= abs(float(t)) <= 90]
            lons_in = [float(t) for t in tokens if 90 < abs(float(t)) <= 180]
            if any(abs(la - lat) < tol for la in lats_in) and \
               any(abs(lo - lon) < tol for lo in lons_in):
                return f
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs():
    errors = []
    if not VIC_RESULT_DIR or not Path(VIC_RESULT_DIR).is_dir():
        errors.append(f"VIC_RESULT_DIR not found: {VIC_RESULT_DIR}")
    if not OUTPUT_CSV:
        errors.append("OUTPUT_CSV not set")
    if LAT == 0.0 and LON == 0.0:
        errors.append("LAT and LON must be non-zero")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process():
    result_file = find_result_file(VIC_RESULT_DIR, LAT, LON)
    if result_file is None:
        logger.error(f"No result file found for lat={LAT:.4f}, lon={LON:.4f} "
                     f"in {VIC_RESULT_DIR}")
        sys.exit(1)
    logger.info(f"Using result file: {result_file.name}")

    # Read data, skipping comment lines (# prefix) and the column-name header
    rows = []
    with open(result_file, "r") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("#") or line.startswith("YEAR"):
                continue
            if not line:
                continue
            parts = line.split()
            if len(parts) < 22:
                continue
            rows.append(parts)

    if not rows:
        logger.error("No data rows found in result file")
        sys.exit(2)

    # Date filter
    t_start = datetime.strptime(START_DATE, "%Y-%m-%d") if START_DATE else None
    t_end   = datetime.strptime(END_DATE,   "%Y-%m-%d") if END_DATE   else None

    # Layer thicknesses in mm
    depths_mm = [d * 1000.0 for d in LAYER_DEPTHS_M]

    output_rows = []
    sm_accum = [[] for _ in range(3)]

    for parts in rows:
        try:
            year  = int(parts[COL_YEAR])
            month = int(parts[COL_MONTH])
            day   = int(parts[COL_DAY])
            date  = datetime(year, month, day)
        except (ValueError, IndexError):
            continue

        if t_start and date < t_start:
            continue
        if t_end and date > t_end:
            continue

        thetas = []
        for i, sm_col in enumerate(COL_SM):
            try:
                sm_mm = float(parts[sm_col])
            except (ValueError, IndexError):
                sm_mm = 0.0
            # Volumetric: mm / mm_depth = cm³/cm³ (dimensionless)
            theta = sm_mm / depths_mm[i] if depths_mm[i] > 0 else 0.0
            # Clamp to physical range [0, 0.6]
            theta = min(0.60, max(0.0, theta))
            thetas.append(theta)
            sm_accum[i].append(theta)

        output_rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "theta_layer1": round(thetas[0], 4),
            "theta_layer2": round(thetas[1], 4),
            "theta_layer3": round(thetas[2], 4),
        })

    if not output_rows:
        logger.error("No rows matched the date filter")
        sys.exit(2)

    # Write CSV
    output_path = Path(OUTPUT_CSV)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["date", "theta_layer1", "theta_layer2", "theta_layer3"]
        )
        writer.writeheader()
        writer.writerows(output_rows)

    # Summary statistics for LDNDC initial conditions
    summary = {
        "n_days": len(output_rows),
        "layer_depths_m": LAYER_DEPTHS_M,
        "theta_stats": {}
    }
    layer_names = ["theta_layer1", "theta_layer2", "theta_layer3"]
    for i, name in enumerate(layer_names):
        vals = sm_accum[i]
        summary["theta_stats"][name] = {
            "mean":  round(float(np.mean(vals)), 4),
            "min":   round(float(np.min(vals)),  4),
            "max":   round(float(np.max(vals)),  4),
            "init":  round(float(np.mean(vals[:30])), 4),  # first-month mean
        }

    logger.info(f"Wrote {len(output_rows)} days → {output_path}")
    return str(output_path), summary


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_outputs(output_path):
    p = Path(output_path)
    if not p.exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)
    with open(p) as fh:
        lines = fh.readlines()
    if len(lines) < 2:
        logger.error("CSV has no data rows")
        sys.exit(3)
    logger.info(f"Output validation passed. Rows: {len(lines)-1}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path, summary = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        sys.exit(2)
    validate_outputs(output_path)
    result = {"status": "success", "soil_water_csv": output_path, **summary}
    print(json.dumps(result, indent=2))
    sys.exit(0)
