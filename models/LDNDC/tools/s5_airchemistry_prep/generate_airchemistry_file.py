#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_airchemistry_file
Stage:        s5_airchemistry_prep
Description:  Generate LDNDC airchem.txt with CO2 concentration and N deposition rates.
              CRITICAL: N deposition must be in kgN/ha/yr, NOT g/m2/yr (see dt_007).

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""
import sys, os, json, logging
from pathlib import Path

OUTPUT_PATH = ""
CO2_PPM = 400.0
NH4_DEP_KGNHA = 5.0
NO3_DEP_KGNHA = 3.0
START_YEAR = 2000
END_YEAR = 2010

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    if not OUTPUT_PATH:
        errors.append("OUTPUT_PATH not set")
    if CO2_PPM < 200 or CO2_PPM > 1200:
        errors.append(f"CO2_PPM={CO2_PPM} out of range [200,1200]")
    if NH4_DEP_KGNHA > 50:
        logger.warning(f"NH4_DEP={NH4_DEP_KGNHA} kgN/ha/yr is very high -- verify units (see dt_007)")
    if NO3_DEP_KGNHA > 50:
        logger.warning(f"NO3_DEP={NO3_DEP_KGNHA} kgN/ha/yr is very high -- verify units (see dt_007)")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    output = Path(OUTPUT_PATH)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#\tco2\tnh4_dep\tno3_dep"]
    for year in range(START_YEAR, END_YEAR + 1):
        lines.append(f"{year}-01-01\t{CO2_PPM:.1f}\t{NH4_DEP_KGNHA:.1f}\t{NO3_DEP_KGNHA:.1f}")
    output.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Generated airchem.txt at {output}")
    return str(output)

def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        OUTPUT_PATH = sys.argv[1]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"status": "success", "airchem_txt": output_path}))
    sys.exit(0)
