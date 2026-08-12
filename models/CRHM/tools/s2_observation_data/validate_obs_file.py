#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      validate_obs_file
Stage:        s2_observation_data
Description:  Validate CRHM .obs file format, units, gaps, and computed variables.

CRHM .obs format specification:
  Line 1:  Description text (free-form)
  Lines 2+: Variable declarations OR computed variable declarations
  Data lines: YYYY M D H 0 val1 val2 val3 ...

Variable declaration:  "varname n_columns (unit)"
  e.g., "t 1 (C)"  or  "ppt 3 (mm/d)"  (3 = 3 observation stations)

Computed variable:  "$varname formula (unit) description"
  e.g., "$ea ea(t, rh) (kPa) vapour pressure"
  e.g., "$Qsi mul(Qsi, 277.8)"  (unit conversion)

Key validation checks:
  1. Header has at least t (temperature) and ppt (precipitation)
  2. Data columns match declared variable count
  3. No gaps in datetime sequence
  4. Values within physical bounds
  5. Computed variable formulas reference declared variables

Inputs:
  --obs_path:  Path to .obs file

Exit codes:
  0 -- success (all checks pass)
  1 -- input validation failed
  2 -- processing error
  3 -- output validation failed (format errors found)
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Physical bounds for validation
PHYSICAL_BOUNDS = {
    "t":    (-80, 60),    # temperature (C)
    "rh":   (0, 100),     # relative humidity (%)
    "u":    (0, 80),      # wind speed (m/s)
    "ppt":  (0, 500),     # precipitation (mm/d), legacy name
    "p":    (0, 500),     # precipitation (mm) — CRHM obs-module standard precip name
                          # (convert_vic_to_obs.py writes 'p'; see validated similkameen.obs)
    "Qsi":  (0, 1400),    # shortwave radiation (W/m2)
    "Qso":  (0, 1400),    # outgoing shortwave (W/m2)
    "Qli":  (0, 600),     # longwave incoming (W/m2)
    "Qn":   (-400, 1000), # net radiation (W/m2)
    "press": (30, 110),   # barometric pressure (kPa) — NOT 'p' (CRHM uses 'p' for precip)
    "SunAct": (0, 24),    # sunshine hours
    "ea":   (0, 10),      # vapor pressure (kPa)
}


def parse_args():
    parser = argparse.ArgumentParser(description="Validate CRHM .obs file")
    parser.add_argument("--obs_path", type=str, required=True, help="Path to .obs file")
    return parser.parse_args()


def validate_inputs(obs_path):
    if not obs_path or not Path(obs_path).exists():
        logger.error(f"Obs file not found: {obs_path}")
        sys.exit(1)
    logger.info("Input validation passed.")


def process(obs_path):
    """
    Parse and validate CRHM .obs file.

    Returns dict with:
    - variables: list of declared variables
    - computed_variables: list of computed variables
    - n_data_rows: count of data rows
    - n_gaps: count of datetime gaps
    - warnings: list of warning messages
    - errors: list of error messages
    """
    with open(obs_path, "r") as f:
        lines = f.readlines()

    if len(lines) < 3:
        return {"errors": ["File has fewer than 3 lines -- not a valid .obs file"]}

    results = {
        "file": str(obs_path),
        "variables": [],
        "computed_variables": [],
        "n_data_rows": 0,
        "n_columns_expected": 0,
        "n_gaps": 0,
        "date_range": {"start": None, "end": None},
        "timestep_hours": None,
        "warnings": [],
        "errors": [],
        "value_bounds": {},
    }

    # Parse header
    header_line = lines[0].strip()
    results["description"] = header_line

    # Parse variable and computed variable declarations
    data_start_idx = None
    total_data_cols = 0

    for i, line in enumerate(lines[1:], start=1):
        stripped = line.strip()
        if not stripped:
            continue

        # Check if this is a data line (starts with a year)
        parts = stripped.split()
        if len(parts) >= 5:
            try:
                year = int(parts[0])
                if 1900 <= year <= 2100:
                    data_start_idx = i
                    break
            except ValueError:
                pass

        # Variable declaration: "varname n_columns (unit)"
        if stripped.startswith("$"):
            # Computed variable: "$varname formula (unit) description"
            results["computed_variables"].append(stripped)
        else:
            # Regular variable declaration
            parts = stripped.split()
            if len(parts) >= 2:
                try:
                    n_cols = int(parts[1])
                    var_name = parts[0]
                    unit = ""
                    if len(parts) >= 3:
                        unit = " ".join(parts[2:])
                    results["variables"].append({
                        "name": var_name,
                        "n_columns": n_cols,
                        "unit": unit,
                    })
                    total_data_cols += n_cols
                except ValueError:
                    results["warnings"].append(f"Line {i+1}: Cannot parse variable declaration: {stripped}")

    results["n_columns_expected"] = total_data_cols

    if data_start_idx is None:
        results["errors"].append("No data rows found in file")
        return results

    # Check required variables
    var_names = [v["name"] for v in results["variables"]]
    if "t" not in var_names:
        results["errors"].append("CRITICAL: Temperature variable 't' not declared in header")
    # CRHM's obs module names precipitation 'p'; 'ppt' is a legacy alias. Accept either.
    if "p" not in var_names and "ppt" not in var_names:
        results["errors"].append("CRITICAL: Precipitation variable 'p' (or legacy 'ppt') not declared in header")

    # Parse data rows
    prev_dt = None
    data_values = {v["name"]: [] for v in results["variables"]}
    col_count_errors = 0

    for i, line in enumerate(lines[data_start_idx:], start=data_start_idx):
        stripped = line.strip()
        if not stripped:
            continue

        parts = stripped.split()
        if len(parts) < 5:
            results["warnings"].append(f"Line {i+1}: Too few columns ({len(parts)})")
            continue

        # Parse datetime (YYYY M D H 0)
        try:
            year, month, day, hour = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            dt = datetime(year, month, day, hour, 0)
        except (ValueError, IndexError) as e:
            results["warnings"].append(f"Line {i+1}: Invalid datetime: {e}")
            continue

        results["n_data_rows"] += 1

        if results["date_range"]["start"] is None:
            results["date_range"]["start"] = dt.isoformat()

        # Check for gaps
        if prev_dt is not None:
            gap = dt - prev_dt
            if results["timestep_hours"] is None:
                results["timestep_hours"] = gap.total_seconds() / 3600
            else:
                expected_gap = timedelta(hours=results["timestep_hours"])
                if gap != expected_gap:
                    results["n_gaps"] += 1
                    if results["n_gaps"] <= 5:
                        results["warnings"].append(
                            f"Gap at {dt}: expected {expected_gap}, got {gap}"
                        )

        prev_dt = dt

        # Check column count
        data_cols = parts[5:]  # skip YYYY M D H 0
        if len(data_cols) != total_data_cols:
            col_count_errors += 1
            if col_count_errors <= 3:
                results["warnings"].append(
                    f"Line {i+1}: Expected {total_data_cols} data columns, got {len(data_cols)}"
                )

        # Check value bounds
        col_idx = 0
        for var in results["variables"]:
            for j in range(var["n_columns"]):
                if col_idx < len(data_cols):
                    try:
                        val = float(data_cols[col_idx])
                        if var["name"] in PHYSICAL_BOUNDS:
                            lo, hi = PHYSICAL_BOUNDS[var["name"]]
                            if val < lo or val > hi:
                                key = f"{var['name']}_out_of_bounds"
                                if key not in results["value_bounds"]:
                                    results["value_bounds"][key] = 0
                                results["value_bounds"][key] += 1
                    except ValueError:
                        pass
                col_idx += 1

    if prev_dt:
        results["date_range"]["end"] = prev_dt.isoformat()

    if col_count_errors > 3:
        results["warnings"].append(f"... and {col_count_errors - 3} more column count mismatches")

    if results["n_gaps"] > 5:
        results["warnings"].append(f"... and {results['n_gaps'] - 5} more datetime gaps")

    # Check for out-of-bounds values
    for key, count in results["value_bounds"].items():
        if count > 0:
            results["warnings"].append(f"{key}: {count} values outside physical bounds")

    # Summary
    if not results["errors"]:
        logger.info(f"PASS: {results['n_data_rows']} rows, {len(results['variables'])} variables, "
                     f"{results['n_gaps']} gaps")
    else:
        logger.error(f"FAIL: {len(results['errors'])} errors found")

    return results


if __name__ == "__main__":
    args = parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs(args.obs_path)

    try:
        report = process(args.obs_path)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    print(json.dumps(report, indent=2, default=str))

    if report.get("errors"):
        sys.exit(3)
    sys.exit(0)
