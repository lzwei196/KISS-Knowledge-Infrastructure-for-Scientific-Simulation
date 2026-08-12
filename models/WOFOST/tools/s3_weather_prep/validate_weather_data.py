#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      validate_weather_data
Stage:        s3_weather_prep
Description:  Validate PCSE weather data for correct units and completeness.
              Catches the two most common silent errors:
                1. IRRAD in MJ instead of kJ (1000x off)
                2. RAIN in mm instead of cm (10x off)

Inputs:
  - WEATHER_CSV: path to PCSE-format CSV weather file

Outputs:
  - JSON validation report on stdout

Exit codes:
  0 — all checks pass
  2 — some checks failed (warnings or errors)
"""

import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

WEATHER_CSV = ""


def validate_inputs():
    if not WEATHER_CSV or not Path(WEATHER_CSV).exists():
        logger.error(f"Weather CSV not found: {WEATHER_CSV}")
        sys.exit(1)


def process():
    import pandas as pd

    # PCSE CSVWeatherDataProvider files carry a "## Site Characteristics" meta
    # block whose lines (e.g. "Country = 'unknown'") are not comma-delimited and
    # are NOT prefixed with '#', so a naive read_csv(comment='#') raises a
    # tokenizing error. Locate the "DAY,..." column header and skip everything
    # above it; fall back to a plain read for already-clean generic CSVs.
    with open(WEATHER_CSV) as f:
        lines = f.readlines()
    data_start = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith('DAY'):
            data_start = i
            break
    if data_start is not None:
        df = pd.read_csv(WEATHER_CSV, skiprows=data_start)
    else:
        df = pd.read_csv(WEATHER_CSV, comment='#')

    checks = []

    # === IRRAD UNIT CHECK (THE #1 SILENT ERROR) ===
    if 'IRRAD' in df.columns:
        irrad_max = df['IRRAD'].max()
        irrad_mean = df['IRRAD'].mean()

        if irrad_max < 100:
            checks.append({
                "check": "IRRAD_units",
                "status": "FAIL",
                "value": f"max={irrad_max:.1f}",
                "message": f"IRRAD max={irrad_max:.1f} — LIKELY IN MJ/m2/day! "
                           f"PCSE needs kJ/m2/day. Multiply by 1000. See dt_003."
            })
        elif irrad_max > 50000:
            checks.append({
                "check": "IRRAD_units",
                "status": "FAIL",
                "value": f"max={irrad_max:.1f}",
                "message": f"IRRAD max={irrad_max:.1f} — unreasonably high. Check units."
            })
        else:
            checks.append({
                "check": "IRRAD_units",
                "status": "PASS",
                "value": f"max={irrad_max:.0f}, mean={irrad_mean:.0f} kJ/m2/day"
            })

    # === RAIN UNIT CHECK ===
    # KDT 5.0 fix (2026-06-08): the previous check FAILED any file with
    # RAIN max > 50, claiming "LIKELY IN mm/day! PCSE needs cm/day. Divide by 10",
    # which is BACKWARDS. The PCSE CSVWeatherDataProvider RAIN column convention is
    # mm/day — the provider divides /10 -> cm internally. This is the ground truth
    # per create_csv_weather_file.py's docstring, SKILL.md ("the RAIN column is
    # mm/day"), and the CORRECTIVE triplets dt_016 / dt_009_csv_rain_mm_not_cm
    # that supersede the old dt_004 cm/day belief. The old check rejected every
    # correctly-authored weather file containing a >50 mm/day rain day (common in
    # any humid or Mediterranean-storm climate) and would have wrongly PASSED the
    # actual bug (column written in cm/day, 10x too low). Validate the mm/day
    # convention instead: flag only implausibly HIGH (data spike) or, over a long
    # record, implausibly LOW maxima (column likely still in cm/day).
    if 'RAIN' in df.columns:
        rain_max = df['RAIN'].max()
        rain_mean = df['RAIN'].mean()

        if rain_max > 500:
            checks.append({
                "check": "RAIN_units",
                "status": "FAIL",
                "value": f"max={rain_max:.1f}",
                "message": f"RAIN max={rain_max:.1f} mm/day — unreasonably high; "
                           f"check for a data error or wrong units."
            })
        elif len(df) > 60 and rain_max < 5:
            checks.append({
                "check": "RAIN_units",
                "status": "WARNING",
                "value": f"max={rain_max:.2f}",
                "message": f"RAIN max={rain_max:.2f} over a long record — column may "
                           f"still be in cm/day (PCSE CSV expects mm/day; multiply "
                           f"by 10). See dt_016 / dt_009_csv_rain_mm_not_cm."
            })
        else:
            checks.append({
                "check": "RAIN_units",
                "status": "PASS",
                "value": f"max={rain_max:.2f}, mean={rain_mean:.3f} mm/day"
            })

    # === TEMPERATURE CHECKS ===
    if 'TMIN' in df.columns and 'TMAX' in df.columns:
        tmin_max = df['TMIN'].max()
        tmax_max = df['TMAX'].max()
        temp_swap = (df['TMIN'] > df['TMAX']).sum()

        if tmax_max > 200:
            checks.append({
                "check": "TEMP_units",
                "status": "FAIL",
                "value": f"TMAX max={tmax_max:.1f}",
                "message": "Temperature likely in Kelvin — subtract 273.15"
            })
        elif temp_swap > 0:
            checks.append({
                "check": "TMIN_le_TMAX",
                "status": "FAIL",
                "value": f"{temp_swap} days with TMIN > TMAX",
                "message": f"TMIN > TMAX on {temp_swap} days — columns may be swapped"
            })
        else:
            checks.append({
                "check": "TEMP_checks",
                "status": "PASS",
                "value": f"TMIN range [{df['TMIN'].min():.1f}, {tmin_max:.1f}], "
                         f"TMAX range [{df['TMAX'].min():.1f}, {tmax_max:.1f}]"
            })

    # === VAP CHECK ===
    if 'VAP' in df.columns:
        vap_max = df['VAP'].max()
        if vap_max > 10:
            checks.append({
                "check": "VAP_units",
                "status": "WARNING",
                "value": f"max={vap_max:.2f}",
                "message": f"VAP max={vap_max:.2f} — may be in hPa instead of kPa (divide by 10)"
            })
        else:
            checks.append({
                "check": "VAP_units",
                "status": "PASS",
                "value": f"max={vap_max:.2f} kPa"
            })

    # === DATE COMPLETENESS ===
    if 'DAY' in df.columns:
        # PCSE DAY column is YYYYMMDD; parse explicitly so integer dates are not
        # misread as nanoseconds-since-epoch (which collapsed all dates to 1970).
        _day = df['DAY'].astype(str).str.replace('-', '', regex=False)
        df['DAY'] = pd.to_datetime(_day, format='%Y%m%d', errors='coerce')
        expected_range = pd.date_range(df['DAY'].min(), df['DAY'].max())
        missing_days = len(expected_range) - len(df)

        if missing_days > 0:
            checks.append({
                "check": "date_completeness",
                "status": "FAIL",
                "value": f"{missing_days} missing days",
                "message": f"{missing_days} days missing between {df['DAY'].min().date()} and {df['DAY'].max().date()}"
            })
        else:
            checks.append({
                "check": "date_completeness",
                "status": "PASS",
                "value": f"{len(df)} days, {df['DAY'].min().date()} to {df['DAY'].max().date()}"
            })

    n_fail = sum(1 for c in checks if c.get("status") == "FAIL")
    return {
        "status": "PASS" if n_fail == 0 else "FAIL",
        "file": WEATHER_CSV,
        "n_records": len(df),
        "summary": f"{sum(1 for c in checks if c.get('status') == 'PASS')} pass, {n_fail} fail",
        "checks": checks
    }


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        WEATHER_CSV = sys.argv[1]

    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["status"] == "PASS" else 2)
