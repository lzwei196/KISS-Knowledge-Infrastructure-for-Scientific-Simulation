#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      parse_watercycle_output
Stage:        s9_output_parsing
Description:  Parse LDNDC watercycle output for ET, drainage, runoff, soil moisture.

Inputs:
  - output_dir: LDNDC output directory containing *watercycle*daily*.txt

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
    files = sorted(output_path.glob("*watercycle*daily*"))
    if not files:
        logger.error("No watercycle daily output files found")
        sys.exit(3)

    df = pd.read_csv(files[0], sep="\t")
    dt = pd.to_datetime(df["datetime"])
    df["year"] = dt.dt.year

    def _find_col(pattern):
        return next((c for c in df.columns if pattern.lower() in c.lower()), None)

    et_col = _find_col("evapotrans") or _find_col("et")
    drain_col = _find_col("drainage") or _find_col("percol")
    runoff_col = _find_col("runoff")
    sm_col = _find_col("soilwater") or _find_col("swc")

    years = {}
    for yr, grp in df.groupby("year"):
        entry = {}
        if et_col: entry["et_mm"] = round(float(grp[et_col].sum()), 1)
        if drain_col: entry["drainage_mm"] = round(float(grp[drain_col].sum()), 1)
        if runoff_col: entry["runoff_mm"] = round(float(grp[runoff_col].sum()), 1)
        if sm_col: entry["soil_water_mean_mm"] = round(float(grp[sm_col].mean()), 1)
        years[str(yr)] = entry

    avg = {}
    for key in ["et_mm", "drainage_mm", "runoff_mm"]:
        vals = [y.get(key, 0) for y in years.values()]
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
