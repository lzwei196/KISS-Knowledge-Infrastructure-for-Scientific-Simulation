#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_calibration_file
Stage:        s6_calibration_parameters
Description:  Create calibration.cal with parameter adjustments for SWAT+.
              Change types: absval (set), abschg (add), pctchg (percent change).

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

PARAMETER_SET = {}  # {"cn2": {"change_type": "pctchg", "value": -10}, ...}
OUTPUT_DIR = ""

if len(sys.argv) >= 3:
    PARAMETER_SET = json.loads(sys.argv[1])
    OUTPUT_DIR = sys.argv[2]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Valid SWAT+ calibration parameters with ranges and recommended change types
VALID_PARAMS = {
    "cn2":       {"range": (-50, 50), "recommended_type": "pctchg", "obj_typ": "hru"},
    "esco":      {"range": (0, 1), "recommended_type": "absval", "obj_typ": "hru"},
    "epco":      {"range": (0, 1), "recommended_type": "absval", "obj_typ": "hru"},
    "awc":       {"range": (-50, 50), "recommended_type": "pctchg", "obj_typ": "hru"},
    "k":         {"range": (-50, 50), "recommended_type": "pctchg", "obj_typ": "hru"},
    "surlag":    {"range": (0.05, 24), "recommended_type": "absval", "obj_typ": "bsn"},
    "alpha_bf":  {"range": (0, 1), "recommended_type": "absval", "obj_typ": "aqu"},
    "gw_delay":  {"range": (0, 500), "recommended_type": "absval", "obj_typ": "aqu"},
    "revap_co":  {"range": (0.02, 0.2), "recommended_type": "absval", "obj_typ": "aqu"},
    "flo_min":   {"range": (0, 5000), "recommended_type": "absval", "obj_typ": "aqu"},
    "revap_min": {"range": (0, 500), "recommended_type": "absval", "obj_typ": "aqu"},
    "perco":     {"range": (0, 1), "recommended_type": "absval", "obj_typ": "hru"},
    "lat_ttime": {"range": (0, 180), "recommended_type": "absval", "obj_typ": "hru"},
    "canmx":     {"range": (0, 100), "recommended_type": "absval", "obj_typ": "hru"},
    "nperco":    {"range": (0, 1), "recommended_type": "absval", "obj_typ": "bsn"},
    "pperco":    {"range": (10, 17.5), "recommended_type": "absval", "obj_typ": "bsn"},
    "cdn":       {"range": (0, 3), "recommended_type": "absval", "obj_typ": "bsn"},
    "sdnco":     {"range": (0, 1), "recommended_type": "absval", "obj_typ": "bsn"},
    "phoskd":    {"range": (100, 200), "recommended_type": "absval", "obj_typ": "bsn"},
    "usle_p":    {"range": (0, 1), "recommended_type": "absval", "obj_typ": "hru"},
}

# Recommended starting calibration presets by climate zone
# Based on validated Bengbu (humid subtropical, NSE=0.757) and literature
CALIBRATION_PRESETS = {
    "humid_subtropical": {
        "cn2": {"change_type": "pctchg", "value": -50},   # Reduce excessive surface runoff
        "esco": {"change_type": "absval", "value": 0.15},  # Allow deeper ET extraction
        "cn3_swf": {"change_type": "absval", "value": 0.0}, # Disable wet-season CN3 amplification
        "perco": {"change_type": "absval", "value": 0.75},  # Enhance deep percolation
    },
    "semi_arid": {
        "cn2": {"change_type": "pctchg", "value": -20},
        "esco": {"change_type": "absval", "value": 0.50},
        "perco": {"change_type": "absval", "value": 0.30},
    },
    "tropical": {
        "cn2": {"change_type": "pctchg", "value": -40},
        "esco": {"change_type": "absval", "value": 0.20},
        "perco": {"change_type": "absval", "value": 0.60},
    },
    "continental": {
        "cn2": {"change_type": "pctchg", "value": -30},
        "esco": {"change_type": "absval", "value": 0.30},
        "alpha_bf": {"change_type": "absval", "value": 0.05},
    },
    "default": {
        "cn2": {"change_type": "pctchg", "value": -30},
        "esco": {"change_type": "absval", "value": 0.30},
    },
}


def validate_inputs():
    errors = []
    if not PARAMETER_SET:
        errors.append("No parameters provided")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    for pname, pconfig in PARAMETER_SET.items():
        if pname not in VALID_PARAMS:
            errors.append(f"Unknown parameter: {pname}")
        if "change_type" not in pconfig:
            errors.append(f"Missing change_type for {pname}")
        elif pconfig["change_type"] not in ["absval", "abschg", "pctchg"]:
            errors.append(f"Invalid change_type for {pname}: {pconfig['change_type']}")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    cal_path = output_dir / "calibration.cal"
    warnings = []

    with open(cal_path, 'w') as f:
        f.write("calibration.cal: written by SWAT+ knowledge infrastructure\n")
        f.write("  cal_parm       chg_typ     chg_val     conds     lyr1      lyr2      "
                "year1     year2     day1      day2      obj_typ\n")

        for pname, pconfig in PARAMETER_SET.items():
            chg_type = pconfig["change_type"]
            chg_val = pconfig.get("value", 0)
            obj_typ = VALID_PARAMS.get(pname, {}).get("obj_typ", "hru")

            # Warn if using absval for spatially variable params
            if pname in ["cn2", "awc", "k"] and chg_type == "absval":
                warnings.append(f"WARNING: Using absval for {pname} destroys spatial variability. Use pctchg instead.")

            f.write(f"  {pname:<14s} {chg_type:<11s} {chg_val:<12.3f} {'null':>9s} "
                    f"{'0':>9s} {'0':>9s} {'0':>9s} {'0':>9s} {'0':>9s} {'0':>9s} {obj_typ:>10s}\n")

    for w in warnings:
        logger.warning(w)

    logger.info(f"Wrote calibration.cal with {len(PARAMETER_SET)} parameters")
    return {
        "status": "success",
        "calibration_cal": str(cal_path),
        "n_parameters": len(PARAMETER_SET),
        "warnings": warnings
    }

def validate_outputs(result):
    if not Path(result["calibration_cal"]).exists():
        logger.error("calibration.cal not created"); sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
