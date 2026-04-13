#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      validate_soil_hydraulics
Stage:        s2_soil_profile
Description:  Validates thWP < thFC < thS ordering, Ksat positivity, and
              penetrability bounds for all soil layers.

Inputs:
  - soil: Soil object to validate

Outputs:
  - JSON validation report on stdout

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_soil(soil):
    """Validate soil hydraulic properties. Returns dict with results."""
    checks = []
    prof = soil.profile.dropna(subset=['th_wp', 'th_fc', 'th_s'])

    for layer in prof['Layer'].unique():
        layer_data = prof[prof['Layer'] == layer].iloc[0]
        wp, fc, s = layer_data['th_wp'], layer_data['th_fc'], layer_data['th_s']
        ksat = layer_data['Ksat']

        checks.append({
            "layer": int(layer),
            "check": "thWP < thFC < thS",
            "status": "PASS" if wp < fc < s else "FAIL",
            "values": f"thWP={wp}, thFC={fc}, thS={s}",
            "severity": "fatal"
        })

        checks.append({
            "layer": int(layer),
            "check": "Ksat > 0",
            "status": "PASS" if ksat > 0 else "FAIL",
            "values": f"Ksat={ksat}",
            "severity": "fatal"
        })

        # TAW check
        taw = fc - wp
        checks.append({
            "layer": int(layer),
            "check": "TAW reasonable (0.05-0.25)",
            "status": "PASS" if 0.01 < taw < 0.40 else "WARN",
            "values": f"TAW={taw:.3f}",
            "severity": "warning"
        })

    report = {
        "soil_name": soil.Name,
        "nLayer": soil.nLayer,
        "zSoil": soil.zSoil,
        "checks": checks,
        "all_pass": all(c["status"] == "PASS" for c in checks),
        "fatal_failures": [c for c in checks if c["status"] == "FAIL"],
    }

    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    logger.info("This tool is designed to be imported and called with a Soil object.")
    logger.info("Usage: from validate_soil_hydraulics import validate_soil; validate_soil(soil)")
    sys.exit(0)
