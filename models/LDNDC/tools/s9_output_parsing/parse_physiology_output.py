#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      parse_physiology_output
Stage:        s9_output_parsing
Description:  Parse LDNDC physiology output for GPP, NPP, yield, LAI, biomass.

Inputs:
  - output_dir: LDNDC output directory containing *physiology*daily*.txt

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


def process():
    output_path = Path(OUTPUT_DIR)
    files = sorted(output_path.glob("*physiology*daily*"))
    if not files:
        logger.error("No physiology daily output files found")
        sys.exit(3)

    df = pd.read_csv(files[0], sep="\t")
    dt = pd.to_datetime(df["datetime"])
    df["year"] = dt.dt.year

    def _find_col(*patterns):
        """Find first column matching any of the patterns (case-insensitive)."""
        for p in patterns:
            for c in df.columns:
                if p.lower() in c.lower():
                    return c
        return None

    # LDNDC column mapping:
    #   GPP = dC_co2_upt[kgCm-2] (daily CO2 uptake = gross photosynthesis)
    #   NPP = GPP - respiration (dC_maintenance_resp + dC_growth_resp + dC_transport_resp)
    #   LAI = lai[-]
    #   Biomass = DW_above[kgDWm-2]
    gpp_col = _find_col("dC_co2_upt", "co2_upt", "gpp")
    resp_maint_col = _find_col("dC_maintenance_resp")
    resp_growth_col = _find_col("dC_growth_resp")
    resp_transport_col = _find_col("dC_transport_resp")
    lai_col = _find_col("lai[-]", "lai")
    biomass_col = _find_col("DW_above", "aboveground", "biomass")

    years = {}
    for yr, grp in df.groupby("year"):
        entry = {}
        if gpp_col:
            # LDNDC stores dC_co2_upt in kgC/m²/day — sum to annual, convert to gC/m²
            gpp_annual = float(grp[gpp_col].sum()) * 1000.0  # kgC → gC
            entry["gpp_gCm2"] = round(gpp_annual, 1)
        if gpp_col and resp_maint_col and resp_growth_col:
            # NPP = GPP - total respiration
            resp = 0.0
            for rc in [resp_maint_col, resp_growth_col, resp_transport_col]:
                if rc: resp += float(grp[rc].sum())
            npp_annual = (float(grp[gpp_col].sum()) - resp) * 1000.0
            entry["npp_gCm2"] = round(npp_annual, 1)
        if lai_col: entry["lai_max"] = round(float(grp[lai_col].max()), 2)
        if biomass_col: entry["biomass_max_kgDWm2"] = round(float(grp[biomass_col].max()), 3)
        years[str(yr)] = entry

    avg = {}
    for key in ["gpp_gCm2", "npp_gCm2", "lai_max"]:
        vals = [y.get(key, 0) for y in years.values() if key in y]
        avg[f"avg_{key}"] = round(np.mean(vals), 1) if vals else 0

    return {"file": str(files[0]), "n_days": len(df), "years": years, "averages": avg}


def validate_outputs(result):
    if result["n_days"] < 30:
        logger.error(f"Only {result['n_days']} data rows")
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
