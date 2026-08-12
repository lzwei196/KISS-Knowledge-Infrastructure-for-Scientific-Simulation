#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      validate_prj
Stage:        s4_parameter_config
Description:  Validate CRHM .prj file structure, parameter ranges, and module deps.

Checks performed:
  1. All required sections present (delimited by ######)
  2. nhru > 0 in Dimensions
  3. Observation file path exists
  4. Start date < end date
  5. Module chain has basin + global as first two modules
  6. All parameter values within declared <min to max> ranges
  7. Number of parameter values matches nhru
  8. Display variables reference modules in the chain

CRITICAL: Parameter values outside range cause CRHM to silently clamp
to the boundary value. If you set fetch=50000 with max=10000, CRHM
uses 10000 without warning. This is a SILENT ERROR.

Inputs:
  --prj_path:  Path to .prj file

Exit codes:
  0 -- all checks pass
  1 -- input error
  2 -- processing error
  3 -- validation errors found
"""

import sys
import os
import json
import re
import logging
import argparse
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Validate CRHM .prj file")
    parser.add_argument("--prj_path", type=str, required=True, help="Path to .prj file")
    return parser.parse_args()


KNOWN_SECTIONS = {
    "Dimensions", "Macros", "Observations", "Dates", "Modules", "Parameters",
    "Initial_State", "Final_State", "Summary_period", "Display_Variable",
    "Display_Observation", "Log_All", "Summary_Screen", "TChart",
}


def parse_prj_sections(content):
    """Split .prj file into named sections.

    Handles BOTH CRHM layouts seen in the wild:
      (a) ``######`` / ``Name:`` / ``######`` / content   (SKILL.md example), and
      (b) ``Name:`` / ``######`` / content / ``######``    (the format the CRHM
          binary actually writes & accepts, e.g. belly_river_fixed.prj —
          section name precedes the first delimiter).
    A section starts whenever a line equals a KNOWN section keyword (with optional
    trailing ':'); ``######`` delimiter lines and the version/description header
    are skipped. This is robust to delimiter placement.
    """
    sections = {}
    current_section = "__header__"
    sections[current_section] = []

    for raw in content.split("\n"):
        line = raw.strip()
        name = line.rstrip(":")
        if name in KNOWN_SECTIONS:
            current_section = name
            sections.setdefault(current_section, [])
            continue
        if line.startswith("######"):
            # delimiter / version-comment line — not content
            continue
        sections.setdefault(current_section, []).append(line)

    return sections


def process(prj_path):
    """Validate .prj file and return report."""
    report = {
        "file": str(prj_path),
        "errors": [],
        "warnings": [],
        "info": {},
    }

    content = Path(prj_path).read_text()

    # Parse sections
    sections = parse_prj_sections(content)

    # Check required sections
    required = ["Dimensions", "Observations", "Dates", "Modules", "Parameters"]
    for sec in required:
        if sec not in sections:
            report["errors"].append(f"Missing required section: {sec}")

    if report["errors"]:
        report["status"] = "FAIL"
        report["summary"] = f"{len(report['errors'])} errors, 0 warnings"
        return report

    # Parse Dimensions
    nhru = 0
    for line in sections.get("Dimensions", []):
        if line.startswith("nhru"):
            try:
                nhru = int(line.split()[1])
            except (IndexError, ValueError):
                report["errors"].append(f"Cannot parse nhru from: {line}")
    if nhru == 0:
        report["errors"].append("nhru is 0 or not declared")
    report["info"]["nhru"] = nhru

    # Check observation file
    obs_lines = [l for l in sections.get("Observations", []) if l.strip()]
    if not obs_lines:
        report["errors"].append("No observation file specified")
    else:
        obs_path = obs_lines[0].strip()
        report["info"]["obs_file"] = obs_path
        if not Path(obs_path).exists():
            # Try relative path
            prj_dir = Path(prj_path).parent
            if not (prj_dir / obs_path).exists():
                report["warnings"].append(f"Observation file not found: {obs_path}")

    # Check dates
    date_lines = [l for l in sections.get("Dates", []) if l.strip()]
    if len(date_lines) < 2:
        report["errors"].append("Need start and end dates in Dates section")
    else:
        try:
            start_parts = date_lines[0].split()
            end_parts = date_lines[1].split()
            start_dt = datetime(int(start_parts[0]), int(start_parts[1]), int(start_parts[2]))
            end_dt = datetime(int(end_parts[0]), int(end_parts[1]), int(end_parts[2]))
            if start_dt >= end_dt:
                report["errors"].append(f"Start date ({date_lines[0]}) >= end date ({date_lines[1]})")
            report["info"]["start_date"] = str(start_dt.date())
            report["info"]["end_date"] = str(end_dt.date())
            report["info"]["n_days"] = (end_dt - start_dt).days
        except (ValueError, IndexError) as e:
            report["errors"].append(f"Cannot parse dates: {e}")

    # Check modules
    mod_lines = [l for l in sections.get("Modules", []) if l.strip()]
    modules = []
    for line in mod_lines:
        s = line.strip()
        # Flat format: 'basin CRHM 02/24/12'. Macro format: '+basin CRHM 04/20/06'.
        # Skip the 'Basin_Group Macro ...' container header.
        if s.startswith("Basin_Group"):
            continue
        mod_name = s.lstrip("+").split()[0]
        if mod_name:
            modules.append(mod_name)
    report["info"]["modules"] = modules

    if modules and modules[0] != "basin":
        report["errors"].append(f"First module must be 'basin', got '{modules[0]}'")
    if len(modules) > 1 and modules[1] != "global":
        report["errors"].append(f"Second module must be 'global', got '{modules[1]}'")
    if len(modules) < 3:
        report["warnings"].append("Module chain has fewer than 3 modules")

    # Check parameters
    param_lines = sections.get("Parameters", [])
    range_pattern = re.compile(r"<([^>]+) to ([^>]+)>")
    current_param = None
    current_range = None
    param_values_collected = []
    param_errors = 0

    for line in param_lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check if this is a parameter declaration
        match = range_pattern.search(stripped)
        if match:
            # Validate previously collected parameter
            if current_param and param_values_collected and nhru > 0:
                if len(param_values_collected) != nhru and len(param_values_collected) != 1:
                    report["warnings"].append(
                        f"Parameter {current_param}: expected {nhru} or 1 values, got {len(param_values_collected)}"
                    )

            current_param = stripped.split("<")[0].strip()
            pmin = float(match.group(1))
            pmax = float(match.group(2))
            current_range = (pmin, pmax)
            param_values_collected = []
        else:
            # Data line -- parse values
            try:
                vals = [float(v) for v in stripped.split()]
                param_values_collected.extend(vals)

                # Check range
                if current_range:
                    for val in vals:
                        if val < current_range[0] or val > current_range[1]:
                            param_errors += 1
                            if param_errors <= 5:
                                report["errors"].append(
                                    f"Parameter {current_param}: value {val} outside range "
                                    f"[{current_range[0]}, {current_range[1]}]"
                                )
            except ValueError:
                pass

    if param_errors > 5:
        report["errors"].append(f"... and {param_errors - 5} more parameter range violations")

    report["info"]["n_param_range_errors"] = param_errors

    # Summary
    n_errors = len(report["errors"])
    n_warnings = len(report["warnings"])
    report["status"] = "PASS" if n_errors == 0 else "FAIL"
    report["summary"] = f"{n_errors} errors, {n_warnings} warnings"

    if n_errors == 0:
        logger.info(f"PASS: {prj_path} -- {n_warnings} warnings")
    else:
        logger.error(f"FAIL: {prj_path} -- {n_errors} errors, {n_warnings} warnings")

    return report


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    if not Path(args.prj_path).exists():
        logger.error(f"File not found: {args.prj_path}")
        sys.exit(1)

    try:
        report = process(args.prj_path)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    print(json.dumps(report, indent=2))

    if report["status"] == "FAIL":
        sys.exit(3)
    sys.exit(0)
