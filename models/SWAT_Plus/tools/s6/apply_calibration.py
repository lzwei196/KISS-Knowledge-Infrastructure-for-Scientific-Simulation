#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      apply_calibration
Stage:        s6_calibration_parameters
Description:  Validate calibration.cal parameters and verify names against SWAT+ variables.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

CALIBRATION_CAL_PATH = ""
TXTINOUT_DIR = ""
if len(sys.argv) >= 3:
    CALIBRATION_CAL_PATH = sys.argv[1]
    TXTINOUT_DIR = sys.argv[2]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

VALID_PARAMS = {"cn2","esco","epco","awc","k","surlag","alpha_bf","gw_delay","revap_co",
                "flo_min","revap_min","perco","lat_ttime","canmx","nperco","pperco","cdn",
                "sdnco","phoskd","usle_p","erorgn","erorgp","bio_min","petco_pmpt"}

def validate_inputs():
    if not CALIBRATION_CAL_PATH or not Path(CALIBRATION_CAL_PATH).exists():
        logger.error(f"calibration.cal not found: {CALIBRATION_CAL_PATH}"); sys.exit(1)
    logger.info("Input validation passed.")

def process():
    lines = Path(CALIBRATION_CAL_PATH).read_text().strip().split('\n')
    issues = []
    n_params = 0

    for line in lines[2:]:  # Skip title and header
        parts = line.split()
        if len(parts) < 3: continue
        pname = parts[0]
        chg_type = parts[1]
        try:
            chg_val = float(parts[2])
        except ValueError:
            issues.append({"param": pname, "issue": f"Cannot parse value: {parts[2]}", "severity": "fatal"})
            continue

        n_params += 1

        if pname not in VALID_PARAMS:
            issues.append({"param": pname, "issue": "Unknown parameter name — will be silently ignored by SWAT+", "severity": "fatal"})
        if chg_type not in ["absval", "abschg", "pctchg"]:
            issues.append({"param": pname, "issue": f"Invalid change type: {chg_type}", "severity": "fatal"})
        if pname in ["cn2", "awc"] and chg_type == "absval":
            issues.append({"param": pname, "issue": "absval destroys spatial variability — use pctchg", "severity": "degraded"})

    return {
        "status": "pass" if not any(i["severity"] == "fatal" for i in issues) else "fail",
        "n_parameters": n_params,
        "total_issues": len(issues),
        "issues": issues
    }

def validate_outputs(result):
    if result["total_issues"] > 0:
        logger.warning(f"Calibration file has {result['total_issues']} issues")
    logger.info("Validation complete.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
