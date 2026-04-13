#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      check_simulation_status
Stage:        s6_execution
Description:  Diagnose WOFOST simulation issues: check if DVS reached maturity,
              detect zero yield, analyze water stress patterns.

Inputs:
  - OUTPUT_CSV: WOFOST daily output CSV

Outputs:
  - JSON diagnostic report on stdout

Exit codes:
  0 — simulation looks healthy, 2 — issues detected
"""

import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_CSV = ""


def validate_inputs():
    if not OUTPUT_CSV or not Path(OUTPUT_CSV).exists():
        logger.error(f"Output CSV not found: {OUTPUT_CSV}")
        sys.exit(1)


def process():
    import pandas as pd

    df = pd.read_csv(OUTPUT_CSV, index_col='day', parse_dates=True)
    diagnostics = []

    # 1. DVS progression
    if 'DVS' in df.columns:
        final_dvs = df['DVS'].iloc[-1]
        max_dvs = df['DVS'].max()
        dvs_at_half = df['DVS'].iloc[len(df) // 2] if len(df) > 1 else 0

        if final_dvs >= 2.0:
            diagnostics.append({"check": "maturity", "status": "OK",
                               "message": f"Crop reached maturity (DVS={final_dvs:.2f})"})
        elif final_dvs >= 1.0:
            diagnostics.append({"check": "maturity", "status": "WARNING",
                               "message": f"Flowered but not matured (DVS={final_dvs:.2f}). "
                                          "TSUM2 too high or max_duration too short? See dt_006, dt_014."})
        elif final_dvs > 0.3:
            diagnostics.append({"check": "maturity", "status": "PROBLEM",
                               "message": f"DVS stuck at {final_dvs:.2f}. "
                                          "Possible vernalization issue. See dt_005."})
        else:
            diagnostics.append({"check": "maturity", "status": "CRITICAL",
                               "message": f"DVS={final_dvs:.2f} — crop barely developed. "
                                          "Check sowing date and temperature."})

    # 2. Yield
    if 'TWSO' in df.columns:
        twso = df['TWSO'].iloc[-1]
        if twso <= 0:
            diagnostics.append({"check": "yield", "status": "CRITICAL",
                               "message": "Zero yield. Likely causes: (1) IRRAD in MJ not kJ (see dt_003), "
                                          "(2) DVS never reached grain fill, (3) severe stress."})
        elif twso < 500:
            diagnostics.append({"check": "yield", "status": "WARNING",
                               "message": f"Very low yield ({twso:.0f} kg/ha). Check weather units and soil params."})
        elif twso > 15000:
            diagnostics.append({"check": "yield", "status": "WARNING",
                               "message": f"Very high yield ({twso:.0f} kg/ha). "
                                          "If using PP mode, this is expected. If WLP, check soil params."})
        else:
            diagnostics.append({"check": "yield", "status": "OK",
                               "message": f"Yield {twso:.0f} kg/ha — within normal range"})

    # 3. LAI
    if 'LAI' in df.columns:
        lai_max = df['LAI'].max()
        if lai_max < 0.1:
            diagnostics.append({"check": "lai", "status": "CRITICAL",
                               "message": f"Max LAI={lai_max:.2f} — crop never established"})
        elif lai_max > 10:
            diagnostics.append({"check": "lai", "status": "WARNING",
                               "message": f"Max LAI={lai_max:.2f} — unusually high, check SLATB"})
        else:
            diagnostics.append({"check": "lai", "status": "OK",
                               "message": f"Max LAI={lai_max:.2f}"})

    # 4. Water stress (if SM available)
    if 'SM' in df.columns:
        sm_min = df['SM'].min()
        sm_mean = df['SM'].mean()
        diagnostics.append({"check": "soil_moisture", "status": "INFO",
                           "message": f"SM range: {sm_min:.3f} - {df['SM'].max():.3f}, mean={sm_mean:.3f}"})

    # 5. Duration
    n_days = len(df)
    diagnostics.append({"check": "duration", "status": "INFO",
                       "message": f"Simulation ran for {n_days} days "
                                  f"({df.index[0].date()} to {df.index[-1].date()})"})

    has_problems = any(d["status"] in ("CRITICAL", "PROBLEM") for d in diagnostics)

    result = {
        "status": "ISSUES_FOUND" if has_problems else "HEALTHY",
        "file": OUTPUT_CSV,
        "diagnostics": diagnostics,
    }
    return result


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        OUTPUT_CSV = sys.argv[1]
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Failed: {e}")
        sys.exit(2)
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["status"] == "HEALTHY" else 2)
