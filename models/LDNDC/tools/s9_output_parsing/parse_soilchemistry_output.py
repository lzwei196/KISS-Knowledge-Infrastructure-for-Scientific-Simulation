#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      parse_soilchemistry_output
Stage:        s9_output_parsing
Description:  Parse LDNDC soilchemistry output for GHG fluxes and nutrient leaching.
              CRITICAL: N2O output is in kgN/ha, NOT kg N2O/ha (dt_012).
              Multiply by 44/28 for kg N2O/ha, by 44/28*298 for CO2-eq.

Inputs:
  - output_dir: LDNDC output directory containing *soilchemistry*daily*.txt

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""
import sys
import os
import json
import logging
from pathlib import Path

import pandas as pd
import numpy as np

OUTPUT_DIR = ""

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    if not OUTPUT_DIR or not Path(OUTPUT_DIR).is_dir():
        logger.error(f"OUTPUT_DIR not found: {OUTPUT_DIR}")
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    output_path = Path(OUTPUT_DIR)
    sc_files = sorted(output_path.glob("*soilchemistry*daily*"))
    if not sc_files:
        sc_files = sorted(output_path.glob("*soilchem*daily*"))
    if not sc_files:
        logger.error("No soilchemistry daily output files found")
        sys.exit(3)

    df = pd.read_csv(sc_files[0], sep="\t")
    dt = pd.to_datetime(df["datetime"])
    df["year"] = dt.dt.year

    # Column name mapping (LDNDC uses [unit] suffix)
    def _find_col(pattern):
        matches = [c for c in df.columns if pattern.lower() in c.lower()]
        return matches[0] if matches else None

    n2o_col = _find_col("n2o_emis")
    co2h_col = _find_col("co2_emis_hetero") or _find_col("co2_hetero")
    co2a_col = _find_col("co2_emis_auto") or _find_col("co2_auto")
    ch4_col = _find_col("ch4_emis")
    no3_col = _find_col("no3_leach")
    no_col = _find_col("no_emis")

    years = {}
    for yr, grp in df.groupby("year"):
        entry = {}
        if n2o_col: entry["n2o_kgN_ha"] = round(float(grp[n2o_col].sum()), 4)
        if co2h_col: entry["co2_hetero_kgC_ha"] = round(float(grp[co2h_col].sum()), 1)
        if co2a_col: entry["co2_auto_kgC_ha"] = round(float(grp[co2a_col].sum()), 1)
        if ch4_col: entry["ch4_kgC_ha"] = round(float(grp[ch4_col].sum()), 4)
        if no3_col: entry["no3_leach_kgN_ha"] = round(float(grp[no3_col].sum()), 2)
        if no_col: entry["no_emis_kgN_ha"] = round(float(grp[no_col].sum()), 3)
        # CO2-equivalent
        n2o_val = entry.get("n2o_kgN_ha", 0)
        co2h_val = entry.get("co2_hetero_kgC_ha", 0)
        ch4_val = entry.get("ch4_kgC_ha", 0)
        entry["total_ghg_co2eq"] = round(
            n2o_val * (44 / 28) * 298 + co2h_val * (44 / 12) + ch4_val * (16 / 12) * 28, 1
        )
        years[str(yr)] = entry

    n_years = len(years)
    avg = {}
    for key in ["n2o_kgN_ha", "co2_hetero_kgC_ha", "ch4_kgC_ha", "no3_leach_kgN_ha", "total_ghg_co2eq"]:
        vals = [y.get(key, 0) for y in years.values()]
        avg[f"avg_{key}"] = round(np.mean(vals), 3) if vals else 0

    return {
        "file": str(sc_files[0]),
        "n_days": len(df),
        "years": years,
        "averages": avg,
    }


def validate_outputs(result):
    if result["n_days"] < 30:
        logger.error(f"Only {result['n_days']} data rows — expected at least 365")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        OUTPUT_DIR = sys.argv[1]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps({"status": "success", **result}))
    sys.exit(0)
