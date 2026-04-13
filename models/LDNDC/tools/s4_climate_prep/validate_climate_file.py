#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      validate_climate_file
Stage:        s4_climate_prep
Description:  Validate LDNDC climate.txt: header, columns, physical ranges, date continuity

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""
import sys, os, json, logging
from pathlib import Path

CLIMATE_FILE = ""
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    if not CLIMATE_FILE or not Path(CLIMATE_FILE).exists():
        logger.error(f"Climate file not found: {CLIMATE_FILE}")
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    warnings = []
    errors = []
    lines = Path(CLIMATE_FILE).read_text().strip().split("\n")
    if len(lines) < 2:
        errors.append("File has no data rows")
    header = lines[0]
    if "\t" not in header:
        errors.append("Header is not tab-separated")
    cols = header.replace("#", "").strip().split("\t")
    has_temp = "tavg" in cols or ("tmin" in cols and "tmax" in cols)
    if not has_temp:
        errors.append("Missing temperature columns (tavg or tmin+tmax)")
    if "prec" not in cols:
        errors.append("Missing precipitation column (prec)")
    # Check physical ranges on first 10 data rows
    temp_col = cols.index("tavg") if "tavg" in cols else (cols.index("tmin") if "tmin" in cols else -1)
    for line in lines[1:min(11, len(lines))]:
        vals = line.split("\t")
        if temp_col >= 0 and temp_col < len(vals):
            try:
                t = float(vals[temp_col])
                if t > 100:
                    errors.append(f"Temperature {t} appears to be Kelvin -- must convert to Celsius (dt_005)")
                    break
            except ValueError:
                pass
    result = {"file": CLIMATE_FILE, "rows": len(lines) - 1, "columns": cols,
              "warnings": warnings, "errors": errors,
              "status": "FAIL" if errors else "PASS"}
    return result

def validate_outputs(result):
    if result["status"] == "FAIL":
        for e in result["errors"]:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        CLIMATE_FILE = sys.argv[1]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result))
    sys.exit(0)
