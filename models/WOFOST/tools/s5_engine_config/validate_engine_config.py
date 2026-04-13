#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      validate_engine_config
Stage:        s5_engine_config
Description:  Cross-validate engine configuration: check mode vs available
              parameters, verify weather coverage spans agromanagement dates.

Exit codes: 0 — pass, 2 — fail
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SIMULATION_MODE = "WLP_FD"
SOIL_PARAMS_JSON = ""
WEATHER_FIRST_DATE = ""
WEATHER_LAST_DATE = ""
AGRO_CAMPAIGN_START = ""
MAX_DURATION = 365


def process():
    checks = []

    # Mode vs soil data
    if SIMULATION_MODE in ("WLP_FD", "WLP_CWB"):
        if SOIL_PARAMS_JSON and Path(SOIL_PARAMS_JSON).exists():
            with open(SOIL_PARAMS_JSON) as f:
                sp = json.load(f)
            required_soil = ["SMW", "SMFCF", "SM0", "K0"]
            missing = [k for k in required_soil if k not in sp]
            if missing:
                checks.append({"check": "soil_for_wlp", "status": "FAIL",
                               "message": f"WLP mode requires soil params: missing {missing}. See dt_008."})
            else:
                checks.append({"check": "soil_for_wlp", "status": "PASS"})
        else:
            checks.append({"check": "soil_for_wlp", "status": "FAIL",
                           "message": f"WLP mode selected but no soil params file. See dt_008."})
    else:
        checks.append({"check": "soil_for_pp", "status": "PASS",
                       "message": "PP mode — soil not required"})

    # Weather coverage
    if WEATHER_FIRST_DATE and AGRO_CAMPAIGN_START:
        w_first = date.fromisoformat(WEATHER_FIRST_DATE)
        a_start = date.fromisoformat(AGRO_CAMPAIGN_START)
        if w_first > a_start:
            checks.append({"check": "weather_coverage_start", "status": "FAIL",
                           "message": f"Weather starts {w_first} but campaign starts {a_start}. "
                                      "Weather must cover campaign start. See dt_011."})
        else:
            checks.append({"check": "weather_coverage_start", "status": "PASS"})

    if WEATHER_LAST_DATE and AGRO_CAMPAIGN_START:
        w_last = date.fromisoformat(WEATHER_LAST_DATE)
        a_start = date.fromisoformat(AGRO_CAMPAIGN_START)
        from datetime import timedelta
        expected_end = a_start + timedelta(days=MAX_DURATION + 30)
        if w_last < expected_end:
            checks.append({"check": "weather_coverage_end", "status": "WARNING",
                           "message": f"Weather ends {w_last} but simulation may need data until ~{expected_end}"})
        else:
            checks.append({"check": "weather_coverage_end", "status": "PASS"})

    n_fail = sum(1 for c in checks if c.get("status") == "FAIL")
    return {"status": "PASS" if n_fail == 0 else "FAIL", "checks": checks}


if __name__ == "__main__":
    if len(sys.argv) >= 5:
        SIMULATION_MODE = sys.argv[1]
        SOIL_PARAMS_JSON = sys.argv[2]
        WEATHER_FIRST_DATE = sys.argv[3]
        WEATHER_LAST_DATE = sys.argv[4]
    if len(sys.argv) >= 6:
        AGRO_CAMPAIGN_START = sys.argv[5]

    try:
        result = process()
    except Exception as e:
        logger.error(f"Failed: {e}")
        sys.exit(2)
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["status"] == "PASS" else 2)
