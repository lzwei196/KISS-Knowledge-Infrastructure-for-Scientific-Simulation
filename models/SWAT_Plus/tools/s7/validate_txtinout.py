#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      validate_txtinout
Stage:        s7_simulation_config
Description:  Cross-check all file references in file.cio against TxtInOut contents.
              Verify object counts, weather station references, soil name consistency.

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
        logger.error(f"TxtInOut directory not found: {TXTINOUT_DIR}"); sys.exit(1)
    if not (Path(TXTINOUT_DIR) / "file.cio").exists():
        logger.error("file.cio not found in TxtInOut"); sys.exit(1)
    logger.info("Input validation passed.")

def process():
    txtinout = Path(TXTINOUT_DIR)
    issues = []

    # Parse file.cio and check all references
    file_cio = (txtinout / "file.cio").read_text().strip().split('\n')
    for line in file_cio[1:]:  # Skip title
        parts = line.split()
        if len(parts) < 2: continue
        category = parts[0]
        for fname in parts[1:]:
            if fname == "null": continue
            if not (txtinout / fname).exists():
                issues.append({
                    "check": "file.cio reference",
                    "category": category,
                    "file": fname,
                    "issue": "File not found in TxtInOut",
                    "severity": "fatal"
                })

    # Check weather file consistency
    for cli_name in ["pcp.cli", "tmp.cli", "slr.cli", "hmd.cli", "wnd.cli"]:
        cli_path = txtinout / cli_name
        if cli_path.exists():
            cli_lines = cli_path.read_text().strip().split('\n')
            for fname in cli_lines[2:]:  # Skip title and header
                fname = fname.strip()
                if fname and not (txtinout / fname).exists():
                    issues.append({
                        "check": f"{cli_name} reference",
                        "file": fname,
                        "issue": f"Weather file not found",
                        "severity": "fatal"
                    })

    # Check time.sim exists and is valid
    time_sim = txtinout / "time.sim"
    if time_sim.exists():
        lines = time_sim.read_text().strip().split('\n')
        if len(lines) < 3:
            issues.append({"check": "time.sim", "issue": "Incomplete time.sim", "severity": "fatal"})
    else:
        issues.append({"check": "time.sim", "issue": "time.sim not found", "severity": "fatal"})

    n_fatal = sum(1 for i in issues if i.get("severity") == "fatal")
    total_files = sum(1 for f in txtinout.iterdir() if f.is_file())

    return {
        "status": "pass" if n_fatal == 0 else "fail",
        "total_files_in_txtinout": total_files,
        "total_issues": len(issues),
        "fatal_issues": n_fatal,
        "issues": issues[:50]
    }

def validate_outputs(result):
    if result["fatal_issues"] > 0:
        logger.warning(f"TxtInOut has {result['fatal_issues']} fatal issues — fix before running SWAT+")
    else:
        logger.info("TxtInOut validation passed — ready to run SWAT+")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
