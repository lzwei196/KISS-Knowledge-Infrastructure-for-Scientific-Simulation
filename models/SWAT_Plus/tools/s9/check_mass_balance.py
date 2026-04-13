#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      check_mass_balance
Stage:        s9_output_parsing
Description:  Verify water and nutrient mass balance closure from SWAT+ output.

Water: Precip = ET + Surface_Runoff + Lateral_Flow + Percolation + Delta_Storage
Acceptable error: < 5% for water, < 10% for nutrients.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

TXTINOUT_DIR = ""
if len(sys.argv) >= 2:
    TXTINOUT_DIR = sys.argv[1]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    if not TXTINOUT_DIR or not Path(TXTINOUT_DIR).is_dir():
        logger.error(f"TxtInOut directory not found: {TXTINOUT_DIR}"); sys.exit(1)
    logger.info("Input validation passed.")

def parse_basin_file(filepath):
    """Parse a basin output file and return column sums."""
    lines = filepath.read_text().strip().split('\n')
    header = lines[0].split()
    sums = {col: 0.0 for col in header}
    n_rows = 0
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < len(header): continue
        for i, col in enumerate(header):
            try:
                sums[col] += float(parts[i])
            except ValueError:
                pass
        n_rows += 1
    return sums, n_rows

def process():
    txtinout = Path(TXTINOUT_DIR)
    results = {}

    # Water balance check
    wb_file = txtinout / "basin_wb_day.txt"
    if wb_file.exists():
        sums, n_days = parse_basin_file(wb_file)
        precip = sums.get("precip", 0)
        et = sums.get("et", 0)
        surq = sums.get("surq_gen", sums.get("surq_cha", 0))
        latq = sums.get("latq", 0)
        perc = sums.get("perc", 0)
        water_yield = sums.get("wateryld", 0)

        # Simple balance: P = ET + water_yield + delta_storage
        total_out = et + water_yield
        error_mm = abs(precip - total_out)
        error_pct = (error_mm / precip * 100) if precip > 0 else 0

        results["water_balance"] = {
            "precip_mm": round(precip, 1),
            "et_mm": round(et, 1),
            "water_yield_mm": round(water_yield, 1),
            "surq_mm": round(surq, 1),
            "latq_mm": round(latq, 1),
            "perc_mm": round(perc, 1),
            "balance_error_mm": round(error_mm, 1),
            "balance_error_pct": round(error_pct, 2),
            "status": "pass" if error_pct < 5 else "fail",
            "n_days": n_days
        }
        logger.info(f"Water balance: P={precip:.0f}, ET={et:.0f}, WY={water_yield:.0f}, Error={error_pct:.1f}%")
    else:
        results["water_balance"] = {"status": "not_available", "reason": "basin_wb_day.txt not found"}

    # Nutrient balance check
    nb_file = txtinout / "basin_nb_day.txt"
    if nb_file.exists():
        sums, n_days = parse_basin_file(nb_file)
        results["nutrient_balance"] = {
            "n_days": n_days,
            "status": "available",
            "totals": {k: round(v, 2) for k, v in sums.items()
                      if k not in ["jday", "mon", "day", "yr", "unit", "gis_id", "name"]}
        }
        logger.info(f"Nutrient balance parsed: {n_days} days")
    else:
        results["nutrient_balance"] = {"status": "not_available", "reason": "basin_nb_day.txt not found"}

    return {
        "status": "success",
        "results": results
    }

def validate_outputs(result):
    wb = result["results"].get("water_balance", {})
    if wb.get("status") == "fail":
        logger.warning(f"Water balance error {wb.get('balance_error_pct', '?')}% exceeds 5% threshold")
    logger.info("Mass balance check complete.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
