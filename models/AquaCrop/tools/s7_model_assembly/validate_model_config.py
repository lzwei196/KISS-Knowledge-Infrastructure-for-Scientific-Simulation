#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      validate_model_config
Stage:        s7_model_assembly
Description:  Pre-flight checks on assembled model: date consistency,
              weather coverage, soil-crop compatibility.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_config(model):
    """Validate assembled AquaCropModel. Returns dict with results."""
    import pandas as pd
    checks = []

    # Date format
    for attr, name in [('sim_start_time', 'sim_start_time'), ('sim_end_time', 'sim_end_time')]:
        val = getattr(model, attr)
        checks.append({
            "check": f"{name} format YYYY/MM/DD",
            "status": "PASS" if '/' in val and '-' not in val else "FAIL",
            "values": val,
            "severity": "fatal"
        })

    # Weather coverage
    w = model.weather_df
    start = pd.Timestamp(model.sim_start_time.replace('/', '-'))
    end = pd.Timestamp(model.sim_end_time.replace('/', '-'))
    checks.append({
        "check": "Weather covers simulation period",
        "status": "PASS" if w['Date'].min() <= start and w['Date'].max() >= end else "WARN",
        "values": f"weather: {w['Date'].min()} to {w['Date'].max()}, sim: {start} to {end}",
        "severity": "warning"
    })

    # Soil depth
    if hasattr(model.soil, 'zSoil') and hasattr(model.crop, 'Zmax'):
        checks.append({
            "check": "Soil depth >= crop max root depth",
            "status": "PASS" if model.soil.zSoil >= model.crop.Zmax else "WARN",
            "values": f"soil={model.soil.zSoil}m, crop.Zmax={model.crop.Zmax}m",
            "severity": "warning"
        })

    report = {
        "checks": checks,
        "all_pass": all(c["status"] == "PASS" for c in checks),
    }
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    logger.info("Usage: from validate_model_config import validate_config; validate_config(model)")
    sys.exit(0)
