#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      transfer_mpr_params
Stage:        s10_regionalize
Description:  Transfer calibrated MPR global parameters to a new (ungauged) basin.

THIS IS THE KEY TOOL that makes mHM uniquely valuable in HydroCraft.

MPR (Multiscale Parameter Regionalization) works because:
1. Global parameters encode PROCESS UNDERSTANDING (how soil texture maps to Ksat)
2. They are NOT location-specific values
3. When applied to a new basin with its own L0 data (soil, geology, land cover),
   the transfer functions automatically derive locally appropriate parameters

CRITICAL REQUIREMENTS for successful transfer:
- SAME L0 data sources must be used for both calibration and prediction basins
  (e.g., both must use HWSD soil, GLiM geology, AVHRR land cover)
- If different data sources are used, the transfer functions may not be valid
- Climate similarity helps but is NOT strictly required

Inputs:
  - CALIBRATED_PARAM_NML: path to calibrated mhm_parameter.nml
  - TARGET_RUN_DIR: directory of the new basin (with all input data ready)
  - SOURCE_BASIN_NAME: name of the calibration basin (for documentation)
  - TARGET_BASIN_NAME: name of the target basin

Outputs:
  - Updated mhm_parameter.nml in TARGET_RUN_DIR with calibrated values
  - transfer_report.json documenting the transfer

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import re
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CALIBRATED_PARAM_NML = ""
TARGET_RUN_DIR = ""
SOURCE_BASIN_NAME = ""
TARGET_BASIN_NAME = ""

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Transfer MPR parameters")
    parser.add_argument("--calibrated_nml", required=True, help="Calibrated mhm_parameter.nml")
    parser.add_argument("--target_dir", required=True, help="Target basin run directory")
    parser.add_argument("--source_basin", default="unknown")
    parser.add_argument("--target_basin", default="unknown")
    args = parser.parse_args()
    CALIBRATED_PARAM_NML = args.calibrated_nml
    TARGET_RUN_DIR = args.target_dir
    SOURCE_BASIN_NAME = args.source_basin
    TARGET_BASIN_NAME = args.target_basin

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_nml_parameters(nml_path):
    """Parse mhm_parameter.nml and extract parameter values."""
    params = {}
    current_group = None

    with open(nml_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('!'):
                continue

            # Detect namelist group
            if line.startswith('&'):
                current_group = line[1:].strip()
                continue
            if line == '/':
                current_group = None
                continue

            # Parse parameter line: name = lower, upper, value, FLAG, SCALING
            match = re.match(
                r'(\w[\w(),:]*)\s*=\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(\d+)\s*,\s*(\d+)',
                line
            )
            if match:
                name = match.group(1).strip()
                params[f"{current_group}/{name}" if current_group else name] = {
                    "group": current_group,
                    "name": name,
                    "lower": float(match.group(2)),
                    "upper": float(match.group(3)),
                    "value": float(match.group(4)),
                    "flag": int(match.group(5)),
                    "scaling": int(match.group(6)),
                }

    return params


def validate_inputs():
    errors = []
    if not CALIBRATED_PARAM_NML or not Path(CALIBRATED_PARAM_NML).exists():
        errors.append(f"Calibrated parameter file not found: {CALIBRATED_PARAM_NML}")
    if not TARGET_RUN_DIR or not Path(TARGET_RUN_DIR).exists():
        errors.append(f"Target run directory not found: {TARGET_RUN_DIR}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    # Parse calibrated parameters
    cal_params = parse_nml_parameters(CALIBRATED_PARAM_NML)
    logger.info(f"Parsed {len(cal_params)} parameters from calibrated file")

    # Count calibrated (FLAG=1) parameters
    calibrated = {k: v for k, v in cal_params.items() if v["flag"] == 1}
    fixed = {k: v for k, v in cal_params.items() if v["flag"] == 0}
    logger.info(f"  Calibrated (FLAG=1): {len(calibrated)}")
    logger.info(f"  Fixed (FLAG=0): {len(fixed)}")

    # Copy calibrated parameter file to target
    target_nml = Path(TARGET_RUN_DIR) / "mhm_parameter.nml"

    # Backup existing if present
    if target_nml.exists():
        backup = target_nml.with_suffix(".nml.bak")
        shutil.copy2(target_nml, backup)
        logger.info(f"Backed up existing: {backup}")

    shutil.copy2(CALIBRATED_PARAM_NML, target_nml)
    logger.info(f"Transferred calibrated parameters to {target_nml}")

    # Verify target has required input data
    target_dir = Path(TARGET_RUN_DIR)
    checks = {
        "mhm.nml": target_dir / "mhm.nml",
        "soil_classdefinition.txt": target_dir / "input" / "morph" / "soil_classdefinition.txt",
        "geology_classdefinition.txt": target_dir / "input" / "morph" / "geology_classdefinition.txt",
        "dem.asc": target_dir / "input" / "morph" / "dem.asc",
    }

    warnings = []
    for name, path in checks.items():
        if not path.exists():
            warnings.append(f"Missing in target: {name} ({path})")
            logger.warning(f"  WARNING: {name} not found at {path}")

    # Generate transfer report
    report = {
        "status": "success",
        "source_basin": SOURCE_BASIN_NAME,
        "target_basin": TARGET_BASIN_NAME,
        "calibrated_nml_source": str(CALIBRATED_PARAM_NML),
        "target_nml_path": str(target_nml),
        "n_parameters_total": len(cal_params),
        "n_calibrated": len(calibrated),
        "n_fixed": len(fixed),
        "calibrated_parameters": {
            k: {"value": v["value"], "lower": v["lower"], "upper": v["upper"]}
            for k, v in sorted(calibrated.items())
        },
        "warnings": warnings,
        "transfer_note": (
            "MPR global parameters transferred. These parameters encode process "
            "understanding through transfer functions, not location-specific values. "
            "The local L0 data (soil, geology, land cover) in the target basin "
            "will be used to derive spatially distributed parameters via MPR. "
            "CRITICAL: Both calibration and target basins must use the SAME "
            "L0 data sources (HWSD, GLiM, AVHRR) for valid transfer."
        ),
    }

    report_path = target_dir / "transfer_report.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))
    return str(report_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Transfer report not created: {output_path}")
        sys.exit(3)

    # Verify the target has a valid mhm_parameter.nml
    report = json.load(open(output_path))
    target_nml = Path(report["target_nml_path"])
    if not target_nml.exists():
        logger.error(f"Parameter file not at target: {target_nml}")
        sys.exit(3)

    # Parse and verify parameters are within bounds
    params = parse_nml_parameters(str(target_nml))
    for key, p in params.items():
        if p["value"] < p["lower"] or p["value"] > p["upper"]:
            logger.warning(f"Parameter {key} value {p['value']} outside [{p['lower']}, {p['upper']}]")

    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
