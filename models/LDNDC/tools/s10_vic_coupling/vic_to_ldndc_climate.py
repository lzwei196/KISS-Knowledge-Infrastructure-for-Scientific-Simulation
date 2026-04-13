#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      vic_to_ldndc_climate
Stage:        s10_vic_coupling
Description:  Convert VIC 7-col ASCII forcing files to LDNDC climate.txt format.
              Reads 3-hourly VIC forcing (8 records/day) and aggregates to daily.

CRITICAL unit conversions (see diagnostic triplets dt_005, dt_014):
  - Temperature: already in °C from process_forcing.py (do NOT subtract 273.15 again)
  - Precipitation: SUM across 8 sub-daily steps (NOT mean)
  - Vapor pressure: kPa → RH (%) via Tetens saturation formula
  - Wind: m/s → km/day (multiply by 86.4)
  - Radiation: mean SW (W/m²) × 0.0864 → MJ/m²/day

VIC forcing columns (7-col, 3-hourly, no header, 8 rows/day):
  0: air_temp  [°C]
  1: prec      [mm per 3-hour step]
  2: pressure  [kPa]
  3: swdown    [W/m²]
  4: lwdown    [W/m²]
  5: vp        [kPa]
  6: wind      [m/s]

LDNDC climate.txt output columns (tab-separated, one row per day):
  day  month  year  Tmax  Tmin  prec  rad  relhum  wind

Units: Tmax/Tmin [°C], prec [mm/day], rad [MJ/m²/day], relhum [%], wind [km/day]

Inputs (set below or pass as CLI args):
  VIC_FORCING_DIR : directory containing VIC forcing ASCII files
  LAT             : target grid cell latitude (to find correct file)
  LON             : target grid cell longitude
  START_DATE      : simulation start date (YYYY-MM-DD)
  END_DATE        : simulation end date (YYYY-MM-DD)
  OUTPUT_PATH     : output climate.txt path
  STEPS_PER_DAY   : 8 for 3-hourly (default), 24 for hourly

Usage:
  python vic_to_ldndc_climate.py <forcing_dir> <lat> <lon> <start> <end> <output>

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import re
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from ki_tools_common.humidity import saturation_vapor_pressure

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VIC_FORCING_DIR = ""      # e.g., "outputs/hefei_2000-2001/vic_temp/forcing/forcing_final"
LAT = 0.0                 # e.g., 31.1250
LON = 0.0                 # e.g., 116.6250
START_DATE = ""           # e.g., "2000-01-01"
END_DATE   = ""           # e.g., "2001-12-31"
OUTPUT_PATH = ""          # e.g., "outputs/chaohu/ldndc/climate.txt"
STEPS_PER_DAY = 8         # 8 for 3-hourly, 24 for hourly

# Override from CLI
if len(sys.argv) >= 7:
    VIC_FORCING_DIR = sys.argv[1]
    LAT             = float(sys.argv[2])
    LON             = float(sys.argv[3])
    START_DATE      = sys.argv[4]
    END_DATE        = sys.argv[5]
    OUTPUT_PATH     = sys.argv[6]
if len(sys.argv) >= 8:
    STEPS_PER_DAY = int(sys.argv[7])

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_forcing_file(forcing_dir, lat, lon):
    """
    Find VIC forcing file for the given lat/lon by scanning the directory.
    Matches files whose name contains both lat and lon as formatted floats.
    Tries tolerances of 0.001° to handle rounding differences.
    """
    d = Path(forcing_dir)
    candidates = list(d.iterdir())

    for tol in [0.001, 0.01, 0.05]:
        for f in candidates:
            name = f.name
            # Extract all float-like tokens from filename
            tokens = re.findall(r"-?\d+\.\d+", name)
            lats_in = [float(t) for t in tokens if 10 <= abs(float(t)) <= 90]
            lons_in = [float(t) for t in tokens if 90 < abs(float(t)) <= 180]
            if any(abs(la - lat) < tol for la in lats_in) and \
               any(abs(lo - lon) < tol for lo in lons_in):
                return f
    return None


def vp_sat_kpa(t_c):
    """Tetens saturation vapour pressure (kPa) for temperature T in °C."""
    return saturation_vapor_pressure(t_c) / 10.0  # hPa -> kPa (ki_tools_common)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs():
    errors = []
    if not VIC_FORCING_DIR or not Path(VIC_FORCING_DIR).is_dir():
        errors.append(f"VIC_FORCING_DIR not found: {VIC_FORCING_DIR}")
    if not START_DATE or not END_DATE:
        errors.append("START_DATE and END_DATE must be set (YYYY-MM-DD)")
    if not OUTPUT_PATH:
        errors.append("OUTPUT_PATH not set")
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
    forcing_file = find_forcing_file(VIC_FORCING_DIR, LAT, LON)
    if forcing_file is None:
        logger.error(
            f"No forcing file found for lat={LAT:.4f}, lon={LON:.4f} "
            f"in {VIC_FORCING_DIR}"
        )
        sys.exit(1)
    logger.info(f"Using forcing file: {forcing_file.name}")

    # Load all data (no header in VIC forcing ASCII)
    data = np.loadtxt(str(forcing_file))
    if data.ndim == 1:
        data = data.reshape(1, -1)

    n_cols = data.shape[1]
    if n_cols < 7:
        logger.error(f"Expected 7 columns, got {n_cols}")
        sys.exit(2)

    # Compute number of days
    start = datetime.strptime(START_DATE, "%Y-%m-%d")
    end   = datetime.strptime(END_DATE,   "%Y-%m-%d")
    n_days = (end - start).days + 1
    n_rows_expected = n_days * STEPS_PER_DAY

    if data.shape[0] < n_rows_expected:
        logger.warning(
            f"File has {data.shape[0]} rows, expected {n_rows_expected} "
            f"({n_days} days × {STEPS_PER_DAY} steps). "
            f"Using available data ({data.shape[0] // STEPS_PER_DAY} days)."
        )
        n_days = data.shape[0] // STEPS_PER_DAY

    # Extract columns
    col_T    = data[:, 0]   # °C
    col_P    = data[:, 1]   # mm / 3-hr step
    col_SW   = data[:, 3]   # W/m²
    col_VP   = data[:, 5]   # kPa
    col_Wind = data[:, 6]   # m/s

    output_path = Path(OUTPUT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["day\tmonth\tyear\tTmax\tTmin\tprec\trad\trelhum\twind"]

    for d in range(n_days):
        i0 = d * STEPS_PER_DAY
        i1 = i0 + STEPS_PER_DAY

        T_day    = col_T[i0:i1]
        P_day    = col_P[i0:i1]
        SW_day   = col_SW[i0:i1]
        VP_day   = col_VP[i0:i1]
        Wind_day = col_Wind[i0:i1]

        # Temperature [°C]
        tmax = float(np.max(T_day))
        tmin = float(np.min(T_day))

        # Precipitation [mm/day] — SUM (not mean!)
        prec = float(np.sum(P_day))

        # Global radiation [MJ/m²/day]: mean SW × seconds_in_day / 1e6
        # mean(W/m²) × 86400 s/day / 1e6 J/MJ = × 0.0864
        rad = float(np.mean(SW_day) * 0.0864)

        # Relative humidity [%]: mean(VP / VP_sat(T))
        rh_vals = []
        for t_c, vp_k in zip(T_day, VP_day):
            es = vp_sat_kpa(t_c)
            rh = 100.0 * vp_k / es if es > 0 else 50.0
            rh = min(100.0, max(0.0, rh))
            rh_vals.append(rh)
        relhum = float(np.mean(rh_vals))

        # Wind [km/day]: mean(m/s) × 86400 s/day / 1000 m/km = × 86.4
        wind = float(np.mean(Wind_day) * 86.4)

        cur = start + timedelta(days=d)
        lines.append(
            f"{cur.day}\t{cur.month}\t{cur.year}\t"
            f"{tmax:.2f}\t{tmin:.2f}\t{prec:.3f}\t"
            f"{rad:.3f}\t{relhum:.1f}\t{wind:.2f}"
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Wrote {n_days} days to {output_path}")
    return str(output_path)


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_outputs(output_path):
    p = Path(output_path)
    if not p.exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)

    lines = p.read_text(encoding="utf-8").strip().split("\n")
    if len(lines) < 2:
        logger.error("climate.txt has no data rows")
        sys.exit(3)

    # Check for Kelvin temperatures (dt_005)
    first_data = lines[1].split("\t")
    if len(first_data) >= 5:
        try:
            tmax = float(first_data[3])
            if tmax > 100:
                logger.error(
                    f"Tmax={tmax} looks like Kelvin — subtract 273.15! (dt_005)"
                )
                sys.exit(3)
        except ValueError:
            pass

    # Check radiation range
    if len(first_data) >= 7:
        try:
            rad = float(first_data[6])
            if rad > 50:
                logger.warning(
                    f"rad={rad} MJ/m²/day seems high — check W/m² → MJ/m²/day conversion"
                )
        except ValueError:
            pass

    logger.info(f"Output validation passed. Lines: {len(lines)-1} days.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"status": "success", "climate_txt": output_path}))
    sys.exit(0)
