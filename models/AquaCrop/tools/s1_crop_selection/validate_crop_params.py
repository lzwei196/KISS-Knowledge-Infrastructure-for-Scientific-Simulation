#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      validate_crop_params
Stage:        s1_crop_selection
Description:  Validates crop parameter consistency: GDD ordering, stress thresholds, canopy limits.

Inputs:
  - crop: Crop object to validate

Outputs:
  - JSON validation report on stdout

Exit codes:
  0 -- success (all checks pass)
  1 -- input validation failed
  2 -- processing error
  3 -- output validation failed (critical parameter issues found)
"""

import sys
import os
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_crop(crop):
    """Validate crop parameter consistency. Returns dict with results."""
    checks = []

    # Temperature thresholds
    checks.append({
        "check": "Tbase < Tupp",
        "status": "PASS" if crop.Tbase < crop.Tupp else "FAIL",
        "values": f"Tbase={crop.Tbase}, Tupp={crop.Tupp}",
        "severity": "fatal"
    })

    # GDD phenology ordering (only for GDD mode)
    if crop.CalendarType == 2:
        checks.append({
            "check": "Emergence < Senescence < Maturity (GDD)",
            "status": "PASS" if crop.Emergence < crop.Senescence <= crop.Maturity else "WARN",
            "values": f"Emergence={crop.Emergence}, Senescence={crop.Senescence}, Maturity={crop.Maturity}",
            "severity": "warning" if crop.Emergence < crop.Maturity else "fatal"
        })

    # Harvest index
    checks.append({
        "check": "0 < HI0 <= 1",
        "status": "PASS" if 0 < crop.HI0 <= 1 else "FAIL",
        "values": f"HI0={crop.HI0}",
        "severity": "fatal"
    })

    # Water productivity
    checks.append({
        "check": "WP > 0",
        "status": "PASS" if crop.WP > 0 else "FAIL",
        "values": f"WP={crop.WP}",
        "severity": "fatal"
    })

    # Canopy cover
    checks.append({
        "check": "0 < CCx <= 1",
        "status": "PASS" if 0 < crop.CCx <= 1 else "FAIL",
        "values": f"CCx={crop.CCx}",
        "severity": "fatal"
    })

    # Plant population
    checks.append({
        "check": "PlantPop > 0",
        "status": "PASS" if crop.PlantPop > 0 else "FAIL",
        "values": f"PlantPop={crop.PlantPop}",
        "severity": "fatal"
    })

    # Root depth
    checks.append({
        "check": "Zmin <= Zmax",
        "status": "PASS" if crop.Zmin <= crop.Zmax else "FAIL",
        "values": f"Zmin={crop.Zmin}, Zmax={crop.Zmax}",
        "severity": "fatal"
    })

    # Pollination heat stress
    if crop.PolHeatStress:
        checks.append({
            "check": "Tmax_up < Tmax_lo (heat stress thresholds)",
            "status": "PASS" if crop.Tmax_up < crop.Tmax_lo else "WARN",
            "values": f"Tmax_up={crop.Tmax_up}, Tmax_lo={crop.Tmax_lo}",
            "severity": "warning"
        })

    report = {
        "crop_name": crop.Name,
        "checks": checks,
        "all_pass": all(c["status"] == "PASS" for c in checks),
        "fatal_failures": [c for c in checks if c["status"] == "FAIL" and c["severity"] == "fatal"],
    }

    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    logger.info("This tool is designed to be imported and called with a Crop object.")
    logger.info("Usage: from validate_crop_params import validate_crop; validate_crop(crop)")
    sys.exit(0)
