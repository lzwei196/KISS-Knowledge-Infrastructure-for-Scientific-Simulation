#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      validate_soil_params
Stage:        s2_soil_params
Description:  Validate WOFOST soil parameter consistency: SMW < SMFCF < SM0,
              CRAIRC < SM0-SMFCF, K0 > 0, RDMSOL > 0.

Inputs:
  - SOIL_PARAMS_JSON: path to soil parameters JSON file

Outputs:
  - JSON validation report on stdout

Exit codes:
  0 — all checks pass
  1 — input validation failed
  2 — some checks failed
"""

import sys
import os
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SOIL_PARAMS_JSON = ""


def validate_inputs():
    if not SOIL_PARAMS_JSON or not os.path.exists(SOIL_PARAMS_JSON):
        logger.error(f"Soil params file not found: {SOIL_PARAMS_JSON}")
        sys.exit(1)


def process():
    with open(SOIL_PARAMS_JSON) as f:
        sp = json.load(f)

    checks = []

    # Required keys
    required = ["SMW", "SMFCF", "SM0", "CRAIRC", "K0", "SOPE", "KSUB",
                 "RDMSOL", "IFUNRN", "WAV", "SSI", "SSMAX", "SMLIM", "NOTINF"]
    for key in required:
        present = key in sp
        checks.append({
            "check": f"key_{key}_present",
            "status": "PASS" if present else "FAIL",
            "message": "" if present else f"Missing required key: {key}"
        })

    # Water limits ordering
    smw = sp.get("SMW", 0)
    smfcf = sp.get("SMFCF", 0)
    sm0 = sp.get("SM0", 0)
    crairc = sp.get("CRAIRC", 0)

    ok = smw < smfcf
    checks.append({
        "check": "SMW_lt_SMFCF",
        "status": "PASS" if ok else "FAIL",
        "values": f"SMW={smw}, SMFCF={smfcf}",
        "message": "" if ok else f"SMW ({smw}) must be < SMFCF ({smfcf})"
    })

    ok = smfcf < sm0
    checks.append({
        "check": "SMFCF_lt_SM0",
        "status": "PASS" if ok else "FAIL",
        "values": f"SMFCF={smfcf}, SM0={sm0}",
        "message": "" if ok else f"SMFCF ({smfcf}) must be < SM0 ({sm0})"
    })

    ok = sm0 <= 0.65
    checks.append({
        "check": "SM0_le_065",
        "status": "PASS" if ok else "FAIL",
        "values": f"SM0={sm0}",
        "message": "" if ok else f"SM0 ({sm0}) > 0.65 — impossible porosity"
    })

    ok = crairc < (sm0 - smfcf)
    checks.append({
        "check": "CRAIRC_lt_air_at_FC",
        "status": "PASS" if ok else "FAIL",
        "values": f"CRAIRC={crairc}, SM0-SMFCF={sm0 - smfcf:.4f}",
        "message": "" if ok else f"CRAIRC ({crairc}) must be < SM0-SMFCF ({sm0 - smfcf:.4f})"
    })

    # K0 range
    k0 = sp.get("K0", 0)
    ok = 0.1 <= k0 <= 200
    checks.append({
        "check": "K0_range",
        "status": "PASS" if ok else "WARNING",
        "values": f"K0={k0}",
        "message": "" if ok else f"K0={k0} outside typical range [0.1, 200] cm/day"
    })

    # RDMSOL range
    rdmsol = sp.get("RDMSOL", 0)
    ok = 10 <= rdmsol <= 300
    checks.append({
        "check": "RDMSOL_range",
        "status": "PASS" if ok else "WARNING",
        "values": f"RDMSOL={rdmsol}",
        "message": "" if ok else f"RDMSOL={rdmsol} outside typical range [10, 300] cm"
    })

    # WAV non-negative
    wav = sp.get("WAV", 0)
    ok = wav >= 0
    checks.append({
        "check": "WAV_nonnegative",
        "status": "PASS" if ok else "FAIL",
        "values": f"WAV={wav}",
        "message": "" if ok else f"WAV ({wav}) must be >= 0"
    })

    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    return {
        "status": "PASS" if n_fail == 0 else "FAIL",
        "summary": f"{sum(1 for c in checks if c['status'] == 'PASS')} pass, {n_fail} fail",
        "checks": checks
    }


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        SOIL_PARAMS_JSON = sys.argv[1]

    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 2)
