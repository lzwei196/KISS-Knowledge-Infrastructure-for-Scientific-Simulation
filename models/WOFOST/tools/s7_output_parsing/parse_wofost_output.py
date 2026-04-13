#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      parse_wofost_output
Stage:        s7_output_parsing
Description:  Parse WOFOST engine output into structured DataFrame with
              proper column names, units annotation, and key metrics.

Inputs:
  - OUTPUT_CSV: WOFOST daily output CSV from run_wofost_simulation

Outputs:
  - JSON with parsed metrics and column descriptions on stdout

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

OUTPUT_CSV = ""

# WOFOST output variable descriptions and units
VARIABLE_INFO = {
    'DVS': {'description': 'Development stage', 'unit': '-', 'range': '0-2'},
    'LAI': {'description': 'Leaf area index', 'unit': 'm2/m2', 'range': '0-10'},
    'TAGP': {'description': 'Total above-ground production', 'unit': 'kg/ha', 'range': '0-30000'},
    'TWSO': {'description': 'Total weight storage organs (yield)', 'unit': 'kg/ha', 'range': '0-20000'},
    'TWLV': {'description': 'Total weight leaves', 'unit': 'kg/ha', 'range': '0-5000'},
    'TWST': {'description': 'Total weight stems', 'unit': 'kg/ha', 'range': '0-15000'},
    'TWRT': {'description': 'Total weight roots', 'unit': 'kg/ha', 'range': '0-5000'},
    'TRA': {'description': 'Transpiration rate', 'unit': 'cm/day', 'range': '0-1'},
    'RD': {'description': 'Rooting depth', 'unit': 'cm', 'range': '0-300'},
    'SM': {'description': 'Volumetric soil moisture', 'unit': 'cm3/cm3', 'range': '0-0.6'},
    'WWLOW': {'description': 'Available water below rooting zone', 'unit': 'cm', 'range': '0-100'},
}


def process():
    import pandas as pd

    df = pd.read_csv(OUTPUT_CSV, index_col='day', parse_dates=True)

    # Extract metrics
    metrics = {}
    columns_found = []

    for col in df.columns:
        info = VARIABLE_INFO.get(col, {'description': 'Unknown', 'unit': '?', 'range': '?'})
        col_data = {
            'description': info['description'],
            'unit': info['unit'],
            'min': round(float(df[col].min()), 3),
            'max': round(float(df[col].max()), 3),
            'mean': round(float(df[col].mean()), 3),
            'final': round(float(df[col].iloc[-1]), 3),
        }
        columns_found.append({col: col_data})

    # Key derived metrics
    yield_kgha = float(df['TWSO'].iloc[-1]) if 'TWSO' in df.columns else 0
    tagp = float(df['TAGP'].iloc[-1]) if 'TAGP' in df.columns else 0
    harvest_index = yield_kgha / tagp if tagp > 0 else 0
    final_dvs = float(df['DVS'].iloc[-1]) if 'DVS' in df.columns else 0
    lai_max = float(df['LAI'].max()) if 'LAI' in df.columns else 0

    # Find phenology dates
    doe = doa = dom = None
    if 'DVS' in df.columns:
        emerged = df[df['DVS'] > 0]
        if len(emerged) > 0:
            doe = str(emerged.index[0].date())
        anthesis = df[df['DVS'] >= 1.0]
        if len(anthesis) > 0:
            doa = str(anthesis.index[0].date())
        maturity = df[df['DVS'] >= 2.0]
        if len(maturity) > 0:
            dom = str(maturity.index[0].date())

    result = {
        "status": "success",
        "file": OUTPUT_CSV,
        "n_days": len(df),
        "period": f"{df.index[0].date()} to {df.index[-1].date()}",
        "yield_kgha": round(yield_kgha, 1),
        "total_biomass_kgha": round(tagp, 1),
        "harvest_index": round(harvest_index, 3),
        "lai_max": round(lai_max, 2),
        "final_dvs": round(final_dvs, 3),
        "maturity_reached": final_dvs >= 2.0,
        "phenology": {
            "emergence": doe,
            "anthesis": doa,
            "maturity": dom,
        },
        "columns": columns_found,
    }

    return result


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        OUTPUT_CSV = sys.argv[1]
    if not OUTPUT_CSV or not Path(OUTPUT_CSV).exists():
        logger.error(f"Output CSV not found: {OUTPUT_CSV}")
        sys.exit(1)
    try:
        result = process()
    except Exception as e:
        logger.error(f"Failed: {e}")
        sys.exit(2)
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0)
