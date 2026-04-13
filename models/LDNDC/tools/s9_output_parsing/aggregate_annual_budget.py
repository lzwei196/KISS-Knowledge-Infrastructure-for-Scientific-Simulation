#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      aggregate_annual_budget
Stage:        s9_output_parsing
Description:  Compute annual C/N budgets from all LDNDC output files.
              Combines soilchemistry + physiology + watercycle + yearly summary.

Inputs:
  - output_dir: LDNDC output directory

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""
import sys, os, json, logging
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


def _parse_file(pattern):
    """Find and parse a tab-separated LDNDC output file."""
    files = sorted(Path(OUTPUT_DIR).glob(pattern))
    if not files:
        return None
    df = pd.read_csv(files[0], sep="\t")
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["year"] = df["datetime"].dt.year
    return df


def _find_col(df, pattern):
    return next((c for c in df.columns if pattern.lower() in c.lower()), None)


def process():
    sc = _parse_file("*soilchemistry*daily*")
    ph = _parse_file("*physiology*daily*")
    wc = _parse_file("*watercycle*daily*")

    if sc is None:
        logger.error("No soilchemistry output found")
        sys.exit(3)

    # Also try yearly summary
    yearly_files = sorted(Path(OUTPUT_DIR).glob("*soilchemistry*yearly*"))
    yearly_data = {}
    if yearly_files:
        ydf = pd.read_csv(yearly_files[0], sep="\t")
        for _, row in ydf.iterrows():
            yr_col = _find_col(ydf, "year")
            if yr_col is None:
                yr_col = "datetime"
            yr = str(row[yr_col])[:4]
            yearly_data[yr] = {c: round(float(row[c]), 4) for c in ydf.columns
                               if c not in ("source", "id", "datetime", yr_col)}

    years_list = sorted(sc["year"].unique())
    budget = {}

    for yr in years_list:
        entry = {}
        sc_yr = sc[sc.year == yr]

        # GHG
        n2o_col = _find_col(sc, "n2o_emis")
        if n2o_col: entry["n2o_kgN_ha"] = round(float(sc_yr[n2o_col].sum()), 3)
        ch4_col = _find_col(sc, "ch4_emis")
        if ch4_col: entry["ch4_kgC_ha"] = round(float(sc_yr[ch4_col].sum()), 4)
        co2h_col = _find_col(sc, "co2_emis_hetero") or _find_col(sc, "co2_hetero")
        if co2h_col: entry["co2_hetero_kgC_ha"] = round(float(sc_yr[co2h_col].sum()), 0)
        no3_col = _find_col(sc, "no3_leach")
        if no3_col: entry["no3_leach_kgN_ha"] = round(float(sc_yr[no3_col].sum()), 2)

        # Physiology
        if ph is not None:
            ph_yr = ph[ph.year == yr]
            gpp_col = _find_col(ph, "gpp")
            if gpp_col: entry["gpp_gCm2"] = round(float(ph_yr[gpp_col].sum()), 0)

        # Water cycle
        if wc is not None:
            wc_yr = wc[wc.year == yr]
            et_col = _find_col(wc, "evapotrans") or _find_col(wc, "et")
            if et_col: entry["et_mm"] = round(float(wc_yr[et_col].sum()), 0)

        # Yearly summary data
        if str(yr) in yearly_data:
            entry["yearly_summary"] = yearly_data[str(yr)]

        # GHG CO2-equivalent
        n2o_v = entry.get("n2o_kgN_ha", 0)
        co2h_v = entry.get("co2_hetero_kgC_ha", 0)
        ch4_v = entry.get("ch4_kgC_ha", 0)
        entry["total_ghg_co2eq"] = round(
            n2o_v * (44/28) * 298 + co2h_v * (44/12) + ch4_v * (16/12) * 28, 0
        )

        budget[str(yr)] = entry

    # Averages
    n = len(budget)
    avg = {}
    for key in ["n2o_kgN_ha", "co2_hetero_kgC_ha", "ch4_kgC_ha", "no3_leach_kgN_ha", "total_ghg_co2eq"]:
        vals = [b.get(key, 0) for b in budget.values()]
        avg[key] = round(sum(vals) / n, 3) if n else 0

    return {"years": budget, "period_avg": avg, "n_years": n}


def validate_outputs(result):
    if result["n_years"] < 1:
        logger.error("No complete years in output")
        sys.exit(3)
    logger.info(f"Output validation passed ({result['n_years']} years).")


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
