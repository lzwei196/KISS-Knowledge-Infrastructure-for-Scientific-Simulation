#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      validate_soil_params
Stage:        s2_soil_params
Description:  Validate WOFOST soil parameter consistency: the 8 soil-hydraulic
              keys are present, no site keys (dt_v003), SMW < SMFCF < SM0,
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
import math
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SOIL_PARAMS_JSON = ""

# The keys convert_hwsd_to_pcse_soil.py writes (its validate_outputs() requires the same 8).
REQUIRED_SOIL_KEYS = ("SMW", "SMFCF", "SM0", "CRAIRC", "K0", "SOPE", "KSUB", "RDMSOL")
# Site parameters: supplied by WOFOST72SiteDataProvider in PCSE 6.0, never in soildata (dt_v003).
SITE_KEYS = ("IFUNRN", "NOTINF", "SSI", "SSMAX", "WAV", "SMLIM")


def validate_inputs():
    if not SOIL_PARAMS_JSON or not os.path.exists(SOIL_PARAMS_JSON):
        logger.error(f"Soil params file not found: {SOIL_PARAMS_JSON}")
        sys.exit(1)


def process():
    with open(SOIL_PARAMS_JSON) as f:
        sp = json.load(f)

    checks = []

    # Required keys. PCSE 6.0 (dt_v003): soildata holds ONLY the 8 soil-hydraulic keys that
    # convert_hwsd_to_pcse_soil.py writes. IFUNRN, NOTINF, SSI, SSMAX, WAV, SMLIM are SITE
    # parameters (WOFOST72SiteDataProvider); having them in the soil JSON as well raises
    # "Duplicate parameter found", so they are flagged here, not required.
    required = list(REQUIRED_SOIL_KEYS)
    for key in required:
        present = key in sp
        checks.append({
            "check": f"key_{key}_present",
            "status": "PASS" if present else "FAIL",
            "message": "" if present else f"Missing required key: {key}"
        })
    site_in_soil = [k for k in SITE_KEYS if k in sp]
    checks.append({
        "check": "no_site_keys_in_soil",
        "status": "PASS" if not site_in_soil else "FAIL",
        "values": f"site keys found: {site_in_soil}",
        "message": "" if not site_in_soil else (
            f"{site_in_soil} belong to the site data (WOFOST72SiteDataProvider), not soildata; "
            "PCSE 6.0 raises 'Duplicate parameter found' (dt_v003)")
    })

    def _num(key):
        """The value, or None when missing / not a finite number."""
        v = sp.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return float(v)
        return None

    # Every required key must hold a finite number (null, text, NaN, inf are unusable by PCSE).
    for key in required:
        if key in sp and _num(key) is None:
            checks.append({"check": f"key_{key}_finite_number", "status": "FAIL",
                           "values": f"{key}={sp.get(key)!r}",
                           "message": f"{key} must be a finite number"})
    # Volume fractions that must be > 0 (SMW, CRAIRC).
    for key in ("SMW", "CRAIRC"):
        v = _num(key)
        if v is not None and not v > 0:
            checks.append({"check": f"{key}_positive", "status": "FAIL",
                           "values": f"{key}={v}", "message": f"{key} ({v}) must be > 0"})
    # Percolation limits (cm/day) may be 0: PCSE's water balance uses limit(0, SOPE, ...) and
    # limit(0, KSUB, ...), and KSUB=0 is a valid way to switch off drainage to the subsoil.
    # Only negative values are rejected.
    for key in ("SOPE", "KSUB"):
        v = _num(key)
        if v is not None and v < 0:
            checks.append({"check": f"{key}_nonnegative", "status": "FAIL",
                           "values": f"{key}={v}", "message": f"{key} ({v}) must be >= 0"})

    def _skip(name, keys):
        checks.append({"check": name, "status": "FAIL",
                       "message": f"not checked: missing or non-numeric {keys}"})

    smw, smfcf, sm0, crairc = _num("SMW"), _num("SMFCF"), _num("SM0"), _num("CRAIRC")
    k0, rdmsol = _num("K0"), _num("RDMSOL")

    # Water limits ordering
    if smw is None or smfcf is None:
        _skip("SMW_lt_SMFCF", ["SMW", "SMFCF"])
    else:
        ok = smw < smfcf
        checks.append({
            "check": "SMW_lt_SMFCF",
            "status": "PASS" if ok else "FAIL",
            "values": f"SMW={smw}, SMFCF={smfcf}",
            "message": "" if ok else f"SMW ({smw}) must be < SMFCF ({smfcf})"
        })

    if smfcf is None or sm0 is None:
        _skip("SMFCF_lt_SM0", ["SMFCF", "SM0"])
    else:
        ok = smfcf < sm0
        checks.append({
            "check": "SMFCF_lt_SM0",
            "status": "PASS" if ok else "FAIL",
            "values": f"SMFCF={smfcf}, SM0={sm0}",
            "message": "" if ok else f"SMFCF ({smfcf}) must be < SM0 ({sm0})"
        })

    if sm0 is None:
        _skip("SM0_le_065", ["SM0"])
    else:
        ok = sm0 <= 0.65
        checks.append({
            "check": "SM0_le_065",
            "status": "PASS" if ok else "FAIL",
            "values": f"SM0={sm0}",
            "message": "" if ok else f"SM0 ({sm0}) > 0.65 — impossible porosity"
        })

    if crairc is None or sm0 is None or smfcf is None:
        _skip("CRAIRC_lt_air_at_FC", ["CRAIRC", "SM0", "SMFCF"])
    else:
        ok = crairc < (sm0 - smfcf)
        checks.append({
            "check": "CRAIRC_lt_air_at_FC",
            "status": "PASS" if ok else "FAIL",
            "values": f"CRAIRC={crairc}, SM0-SMFCF={sm0 - smfcf:.4f}",
            "message": "" if ok else f"CRAIRC ({crairc}) must be < SM0-SMFCF ({sm0 - smfcf:.4f})"
        })

    # K0: must be > 0 (zero means no water movement); outside [0.1, 200] cm/day is a warning
    if k0 is None:
        _skip("K0_range", ["K0"])
    else:
        ok = 0.1 <= k0 <= 200
        checks.append({
            "check": "K0_range",
            "status": "PASS" if ok else ("WARNING" if k0 > 0 else "FAIL"),
            "values": f"K0={k0}",
            "message": "" if ok else f"K0={k0} outside typical range [0.1, 200] cm/day"
        })

    # RDMSOL: must be > 0; outside [10, 300] cm is a warning
    if rdmsol is None:
        _skip("RDMSOL_range", ["RDMSOL"])
    else:
        ok = 10 <= rdmsol <= 300
        checks.append({
            "check": "RDMSOL_range",
            "status": "PASS" if ok else ("WARNING" if rdmsol > 0 else "FAIL"),
            "values": f"RDMSOL={rdmsol}",
            "message": "" if ok else f"RDMSOL={rdmsol} outside typical range [10, 300] cm"
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
