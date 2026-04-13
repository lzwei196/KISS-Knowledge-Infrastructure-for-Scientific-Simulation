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

    df = pd.read_csv(WEATHER_CSV, comment='#')

    # Auto-detect header section (skip lines starting with ##)
    if 'DAY' not in df.columns:
        # Try reading with comment character
        with open(WEATHER_CSV) as f:
            lines = f.readlines()
        data_start = 0
        for i, line in enumerate(lines):
            if line.strip().startswith('DAY'):
                data_start = i
                break
        df = pd.read_csv(WEATHER_CSV, skiprows=data_start)

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

    # === RAIN UNIT CHECK (THE #2 SILENT ERROR) ===
    if 'RAIN' in df.columns:
        rain_max = df['RAIN'].max()
        rain_mean = df['RAIN'].mean()

        if rain_max > 50:
            checks.append({
                "check": "RAIN_units",
                "status": "FAIL",
                "value": f"max={rain_max:.1f}",
                "message": f"RAIN max={rain_max:.1f} — LIKELY IN mm/day! "
                           f"PCSE needs cm/day. Divide by 10. See dt_004."
            })
        else:
            checks.append({
                "check": "RAIN_units",
                "status": "PASS",
                "value": f"max={rain_max:.2f}, mean={rain_mean:.3f} cm/day"
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
        df['DAY'] = pd.to_datetime(df['DAY'])
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
