#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      validate_agromanagement
Stage:        s4_agromanagement
Description:  Validate agromanagement YAML structure, check crop/variety
              name existence, verify date ordering.

Inputs:
  - AGRO_YAML: path to agromanagement YAML file

Outputs:
  - JSON validation report on stdout

Exit codes:
  0 — all checks pass, 2 — some checks failed
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

AGRO_YAML = ""


def validate_inputs():
    if not AGRO_YAML or not Path(AGRO_YAML).exists():
        logger.error(f"Agromanagement YAML not found: {AGRO_YAML}")
        sys.exit(1)


def process():
    import yaml

    checks = []

    # Parse YAML
    try:
        with open(AGRO_YAML) as f:
            agro = yaml.safe_load(f)
        checks.append({"check": "yaml_parse", "status": "PASS"})
    except yaml.YAMLError as e:
        checks.append({"check": "yaml_parse", "status": "FAIL",
                       "message": f"YAML parse error: {e}. See dt_001."})
        return {"status": "FAIL", "checks": checks}

    # Structure validation
    if not isinstance(agro, list):
        checks.append({"check": "structure_list", "status": "FAIL",
                       "message": "Top-level must be a list"})
        return {"status": "FAIL", "checks": checks}

    checks.append({"check": "structure_list", "status": "PASS"})

    if len(agro) == 0:
        checks.append({"check": "non_empty", "status": "FAIL",
                       "message": "Agromanagement list is empty"})
        return {"status": "FAIL", "checks": checks}

    # Campaign structure
    campaign = agro[0]
    if not isinstance(campaign, dict):
        checks.append({"check": "campaign_dict", "status": "FAIL",
                       "message": "Campaign must be a dict with date key"})
        return {"status": "FAIL", "checks": checks}

    campaign_key = list(campaign.keys())[0]
    if not isinstance(campaign_key, date):
        checks.append({"check": "campaign_date", "status": "FAIL",
                       "message": f"Campaign key must be datetime.date, got {type(campaign_key).__name__}. "
                                  "YAML may have parsed the date as a string."})
    else:
        checks.append({"check": "campaign_date", "status": "PASS",
                       "value": str(campaign_key)})

    campaign_data = campaign[campaign_key]
    if not isinstance(campaign_data, dict):
        checks.append({"check": "campaign_data", "status": "FAIL",
                       "message": "Campaign value must be a dict with CropCalendar key"})
        return {"status": "FAIL", "checks": checks}

    # CropCalendar presence
    cc = campaign_data.get('CropCalendar')
    if cc is None:
        checks.append({"check": "crop_calendar_present", "status": "FAIL",
                       "message": "CropCalendar is None/missing — likely YAML indent error. See dt_002."})
    else:
        checks.append({"check": "crop_calendar_present", "status": "PASS"})

        # crop_name and variety_name
        crop_name = cc.get('crop_name')
        variety_name = cc.get('variety_name')

        if not crop_name:
            checks.append({"check": "crop_name", "status": "FAIL",
                           "message": "crop_name is empty or missing"})
        else:
            checks.append({"check": "crop_name", "status": "PASS", "value": crop_name})

            # Case sensitivity warning
            if crop_name != crop_name.lower():
                checks.append({"check": "crop_name_case", "status": "WARNING",
                               "message": f"crop_name='{crop_name}' has uppercase. "
                                          "PCSE crop names are usually lowercase (e.g., 'wheat'). See dt_010."})

        if not variety_name:
            checks.append({"check": "variety_name", "status": "FAIL",
                           "message": "variety_name is empty or missing"})
        else:
            checks.append({"check": "variety_name", "status": "PASS", "value": variety_name})

        # max_duration
        max_dur = cc.get('max_duration', 0)
        if max_dur <= 0:
            checks.append({"check": "max_duration", "status": "FAIL",
                           "message": "max_duration must be > 0"})
        elif max_dur < 100:
            checks.append({"check": "max_duration", "status": "WARNING",
                           "message": f"max_duration={max_dur} may be too short. See dt_014."})
        else:
            checks.append({"check": "max_duration", "status": "PASS", "value": max_dur})

        # Date ordering
        crop_start = cc.get('crop_start_date')
        if isinstance(campaign_key, date) and isinstance(crop_start, date):
            if campaign_key > crop_start:
                checks.append({"check": "date_ordering", "status": "FAIL",
                               "message": f"Campaign start ({campaign_key}) is AFTER crop start ({crop_start})"})
            else:
                checks.append({"check": "date_ordering", "status": "PASS"})

    n_fail = sum(1 for c in checks if c.get("status") == "FAIL")
    return {
        "status": "PASS" if n_fail == 0 else "FAIL",
        "file": AGRO_YAML,
        "summary": f"{sum(1 for c in checks if c.get('status') == 'PASS')} pass, {n_fail} fail",
        "checks": checks
    }


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        AGRO_YAML = sys.argv[1]
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["status"] == "PASS" else 2)
