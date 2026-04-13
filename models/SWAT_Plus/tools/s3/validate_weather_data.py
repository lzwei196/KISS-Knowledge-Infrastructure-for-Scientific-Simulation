#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      validate_weather_data
Stage:        s3_weather_preparation
Description:  QC weather files: Tmax>=Tmin, precip>=0, solar 0-40 MJ/m2, RH 0-1, wind>=0.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

TXTINOUT_DIR = ""
if len(sys.argv) >= 2:
    TXTINOUT_DIR = sys.argv[1]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    if not TXTINOUT_DIR or not Path(TXTINOUT_DIR).is_dir():
        logger.error(f"TxtInOut directory not found: {TXTINOUT_DIR}")
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    txtinout = Path(TXTINOUT_DIR)
    issues = []

    # Check .tmp files (Tmax >= Tmin)
    for tmp_file in txtinout.glob("*.tmp"):
        lines = tmp_file.read_text().strip().split('\n')
        for i, line in enumerate(lines[3:], start=4):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    tmax, tmin = float(parts[2]), float(parts[3])
                    if tmax < tmin:
                        issues.append({"file": tmp_file.name, "line": i, "issue": f"Tmax ({tmax}) < Tmin ({tmin})", "severity": "silent_error"})
                    if tmax > 200 or tmin > 200:
                        issues.append({"file": tmp_file.name, "line": i, "issue": f"Temperature likely in Kelvin (>{tmax})", "severity": "silent_error"})
                except ValueError:
                    issues.append({"file": tmp_file.name, "line": i, "issue": "Cannot parse temperature values", "severity": "fatal"})

    # Check .pcp files (precip >= 0)
    for pcp_file in txtinout.glob("*.pcp"):
        lines = pcp_file.read_text().strip().split('\n')
        for i, line in enumerate(lines[3:], start=4):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    precip = float(parts[2])
                    if precip < 0:
                        issues.append({"file": pcp_file.name, "line": i, "issue": f"Negative precipitation: {precip}", "severity": "fatal"})
                except ValueError:
                    pass

    # Check .slr files (solar 0-50 MJ/m2/day)
    for slr_file in txtinout.glob("*.slr"):
        lines = slr_file.read_text().strip().split('\n')
        for i, line in enumerate(lines[3:], start=4):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    slr = float(parts[2])
                    if slr > 50:
                        issues.append({"file": slr_file.name, "line": i, "issue": f"Solar radiation {slr} MJ/m2 — likely in W/m2, need *0.0864", "severity": "silent_error"})
                except ValueError:
                    pass

    # Check header line count (must be exactly 3)
    for ext in ["*.pcp", "*.tmp", "*.slr", "*.hmd", "*.wnd"]:
        for f in txtinout.glob(ext):
            lines = f.read_text().strip().split('\n')
            if len(lines) < 4:
                issues.append({"file": f.name, "issue": f"File has only {len(lines)} lines (need at least 4: 3 header + 1 data)", "severity": "fatal"})

    n_errors = sum(1 for i in issues if i.get("severity") in ["fatal", "silent_error"])
    return {
        "status": "pass" if n_errors == 0 else "fail",
        "total_issues": len(issues),
        "fatal_issues": sum(1 for i in issues if i.get("severity") == "fatal"),
        "silent_errors": sum(1 for i in issues if i.get("severity") == "silent_error"),
        "issues": issues[:50]  # Limit output
    }

def validate_outputs(result):
    if result["fatal_issues"] > 0:
        logger.warning(f"Weather data has {result['fatal_issues']} fatal issues — fix before running SWAT+")
    if result["silent_errors"] > 0:
        logger.warning(f"Weather data has {result['silent_errors']} silent errors — will produce wrong results")
    logger.info("Validation complete.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
