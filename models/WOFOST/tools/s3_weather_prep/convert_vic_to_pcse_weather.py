#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      convert_vic_to_pcse_weather
Stage:        s3_weather_prep
Description:  Convert VIC forcing files (ASCII) to PCSE CSV weather format
              with correct unit conversions.

              CRITICAL UNIT CONVERSIONS:
                SW radiation:  W/m2 → kJ/m2/day  (multiply by 86.4)
                Precipitation: mm   → cm/day      (divide by 10)
                Temperature:   C    → C           (no change)
                Vapor pressure: kPa → kPa         (no change)
                Wind speed:    m/s  → m/s         (no change)

Inputs:
  - FORCING_DIR: directory with VIC forcing files
  - GRID_NC: VIC basin grid NetCDF
  - OUTPUT_DIR: output directory for PCSE CSV files
  - START_YEAR, END_YEAR: simulation period

Outputs:
  - CSV weather files per grid cell in OUTPUT_DIR

Exit codes:
  0 — success
  1 — input validation failed
  2 — processing error
  3 — output validation failed
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

FORCING_DIR = ""
GRID_NC = ""
OUTPUT_DIR = ""
START_YEAR = 2000
END_YEAR = 2010
FORCING_PREFIX = ""  # e.g., "huaihe_0.25deg_"
ANGSTROM_A = 0.18
ANGSTROM_B = 0.55


def validate_inputs():
    errors = []
    if not FORCING_DIR or not Path(FORCING_DIR).is_dir():
        errors.append(f"FORCING_DIR not found: {FORCING_DIR}")
    if not GRID_NC or not Path(GRID_NC).exists():
        errors.append(f"GRID_NC not found: {GRID_NC}")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR not set")
    if START_YEAR >= END_YEAR:
        errors.append(f"START_YEAR ({START_YEAR}) must be < END_YEAR ({END_YEAR})")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_files):
    errors = []
    if not output_files:
        errors.append("No output files were created")

    # Check first file for correct units
    if output_files:
        import pandas as pd
        sample = pd.read_csv(output_files[0], comment='#')
        if 'IRRAD' in sample.columns:
            max_irrad = sample['IRRAD'].max()
            if max_irrad < 100:
                errors.append(f"IRRAD max={max_irrad} — likely in MJ, should be kJ (multiply by 1000)")
            if max_irrad > 50000:
                errors.append(f"IRRAD max={max_irrad} — unreasonably high, check units")
        if 'RAIN' in sample.columns:
            max_rain = sample['RAIN'].max()
            if max_rain > 50:
                errors.append(f"RAIN max={max_rain} — likely in mm, should be cm (divide by 10)")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def process():
    """Convert VIC forcing to PCSE weather CSVs."""
    import numpy as np

    # Try to import xarray for grid reading
    try:
        import xarray as xr
        grid = xr.open_dataset(GRID_NC)
        lats = grid['lat'].values
        lons = grid['lon'].values
        logger.info(f"Grid: {len(lats)} cells")
    except Exception as e:
        logger.error(f"Failed to read grid NetCDF: {e}")
        sys.exit(2)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_files = []

    for lat, lon in zip(lats, lons):
        # Find VIC forcing file for this cell
        lat_str = f"{lat:.4f}"
        lon_str = f"{lon:.4f}"
        forcing_file = Path(FORCING_DIR) / f"{FORCING_PREFIX}{lat_str}_{lon_str}"

        if not forcing_file.exists():
            # Try alternative naming
            forcing_file = Path(FORCING_DIR) / f"forcing_{lat_str}_{lon_str}"
        if not forcing_file.exists():
            logger.warning(f"No forcing file for ({lat}, {lon}), skipping")
            continue

        # Read VIC forcing (columns: PREC TMAX TMIN WIND SW LW VP PRESS)
        try:
            data = np.loadtxt(str(forcing_file))
        except Exception as e:
            logger.warning(f"Failed to read {forcing_file}: {e}")
            continue

        # Determine timestep (3-hourly or daily)
        start_date = date(START_YEAR, 1, 1)
        end_date = date(END_YEAR, 12, 31)
        n_days = (end_date - start_date).days + 1

        if data.shape[0] == n_days:
            steps_per_day = 1
        elif data.shape[0] == n_days * 8:
            steps_per_day = 8  # 3-hourly
        elif data.shape[0] == n_days * 24:
            steps_per_day = 24  # hourly
        else:
            logger.warning(f"Unexpected row count {data.shape[0]} for ({lat},{lon}), expected {n_days} days")
            steps_per_day = max(1, data.shape[0] // n_days)

        # Aggregate to daily if sub-daily
        # VIC columns: 0=PREC, 1=TMAX, 2=TMIN, 3=WIND, 4=SW, 5=LW, 6=VP, 7=PRESS
        n_actual_days = data.shape[0] // steps_per_day

        # Write CSV header
        output_csv = Path(OUTPUT_DIR) / f"weather_{lat_str}_{lon_str}.csv"
        with open(output_csv, 'w') as f:
            f.write(f"## Site Characteristics\n")
            f.write(f"Country    = VIC_grid_cell\n")
            f.write(f"Station    = {lat_str}_{lon_str}\n")
            f.write(f"Description = VIC forcing converted to PCSE format\n")
            f.write(f"Source     = VIC forcing ({FORCING_DIR})\n")
            f.write(f"Contact    = hydrocraft@hohai.edu.cn\n")
            f.write(f"Longitude  = {lon}; decimal degrees\n")
            f.write(f"Latitude   = {lat}; decimal degrees\n")
            f.write(f"Elevation  = -999; meters\n")
            f.write(f"AngstromA  = {ANGSTROM_A}; Angstrom A\n")
            f.write(f"AngstromB  = {ANGSTROM_B}; Angstrom B\n")
            f.write(f"HasSunshine = False\n")
            f.write(f"\n")
            f.write(f"## Daily weather observations\n")
            f.write(f"DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN,SNOWDEPTH\n")

            for d in range(n_actual_days):
                current_date = start_date + timedelta(days=d)
                idx_start = d * steps_per_day
                idx_end = (d + 1) * steps_per_day
                day_data = data[idx_start:idx_end]

                if steps_per_day > 1:
                    prec_mm = day_data[:, 0].sum()
                    tmax_c = day_data[:, 1].max()
                    tmin_c = day_data[:, 2].min()
                    wind_ms = day_data[:, 3].mean()
                    sw_wm2 = day_data[:, 4].mean()
                    vap_kpa = day_data[:, 6].mean()
                else:
                    prec_mm = day_data[0]
                    tmax_c = day_data[1]
                    tmin_c = day_data[2]
                    wind_ms = day_data[3]
                    sw_wm2 = day_data[4]
                    vap_kpa = day_data[6]

                # CRITICAL UNIT CONVERSIONS
                irrad_kj = sw_wm2 * 86.4    # W/m2 → kJ/m2/day
                rain_cm = prec_mm / 10.0      # mm → cm

                f.write(f"{current_date},{irrad_kj:.1f},{tmin_c:.1f},{tmax_c:.1f},"
                        f"{vap_kpa:.3f},{wind_ms:.1f},{rain_cm:.4f},-999\n")

        output_files.append(str(output_csv))
        logger.info(f"  Created: {output_csv}")

    logger.info(f"Converted {len(output_files)} cells.")
    return output_files


if __name__ == "__main__":
    if len(sys.argv) >= 5:
        FORCING_DIR = sys.argv[1]
        GRID_NC = sys.argv[2]
        OUTPUT_DIR = sys.argv[3]
        START_YEAR = int(sys.argv[4])
    if len(sys.argv) >= 6:
        END_YEAR = int(sys.argv[5])
    if len(sys.argv) >= 7:
        FORCING_PREFIX = sys.argv[6]

    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    validate_outputs(result)
    print(json.dumps({"status": "success", "files_created": len(result)}, indent=2))
    sys.exit(0)
