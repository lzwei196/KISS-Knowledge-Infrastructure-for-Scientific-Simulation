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
  A negative count ("p -1 (mm/int)") is valid: |n| columns, flagged as
  integral data (CRHM ClassData.cpp). Filters ($ lines) must follow all
  observation declarations.

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
import math
import re
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
                          # (build_obs.py writes 'p'; see validated similkameen.obs)
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


# A filter argument is a constant when it only holds these characters
# (CRHM Classfilter::readargs, find_first_not_of("0123456789 //:.+-Ee_")).
_CONST_CHARS = set("0123456789 /:.+-Ee_")
# Filters that take no output variable ("$Sim(...)", "$ForceInterval(...)", ...).
_NO_TOVAR_FILTERS = {"Sim", "ForceInterval", "TimeShift"}
# Argument types of every filter CRHM knows (V = observation variable,
# C = constant), from the filter class headers (src/core/filter/Class*.h,
# default `argtypes`) and the name table in MacroClass::addfilter, pinned
# crhmcode commit b6f7e70. A name not in this table is dropped by CRHM
# ("name not recognised"), so the validator reports it as an error.
_FILTER_ARGTYPES = {
    "missing": "VCC", "missing0": "VCC", "missingC": "VCCC",
    "missingFlag": "VCC", "missingFlagAfter": "VCC", "missingrepl": "VCCV",
    "missinginter": "VCC", "ea": "VV", "rh": "VV", "RH_WtoI": "VV",
    "add": "VC", "sub": "VC", "mul": "VC", "div": "VC",
    "addV": "VV", "subV": "VV", "mulV": "VV", "divV": "VV",
    "refwind": "VCCC", "const": "C", "sine": "CCCC", "sin": "CCCC",
    "cos": "CCCC", "abs": "V", "square": "CCCC", "ramp": "CCCC",
    "pulse": "CC", "exp": "CCCC", "expV": "VCC", "log": "CCCC",
    "logV": "VCC", "pow": "CCCC", "powV": "VCC", "time": "C",
    "julian": "C", "random": "C", "poly": "CCCCCCC", "polyV": "VCCCCC",
    "smear": "VCC", "FtoC": "V", "KtoC": "V", "CtoK": "V", "replace": "V",
    "Sim": "CCC", "ForceInterval": "C", "TimeShift": "C",
}


def _check_filter(line, line_no, known_obs, errors, warnings):
    """Check one '$' filter line the way CRHM MacroClass::addfilter and
    Classfilter::readargs parse it. Returns the output variable name, or None.
    Checks: known filter name, argument count and type (V/C), and that every
    variable argument is an observation declared earlier (or the output of an
    earlier filter); otherwise CRHM stops with 'unknown variable'."""
    if line.startswith("$$"):
        return None  # CRHM comment line
    body = line[1:].strip()
    bb = body.find("(")
    if bb < 0:
        errors.append(f"Line {line_no}: filter has no '(' argument list: {line}")
        return None
    head = body[:bb].split()
    if len(head) >= 2:
        to_var, func = head[0], head[1]
    elif len(head) == 1:
        to_var, func = None, head[0]
        if func not in _NO_TOVAR_FILTERS:
            errors.append(f"Line {line_no}: filter {func!r} has no output variable")
            return None
    else:
        errors.append(f"Line {line_no}: filter has no function name: {line}")
        return None
    ee = body.find(")", bb)
    if ee < 0:
        errors.append(f"Line {line_no}: filter argument list is not closed: {line}")
        return None
    argtypes = _FILTER_ARGTYPES.get(func)
    if argtypes is None:
        errors.append(f"Line {line_no}: filter {func!r} is not a CRHM filter name "
                      "(CRHM drops it: 'name not recognised')")
        return None
    toks = body[bb + 1:ee].replace(",", " ").split()
    if len(toks) < len(argtypes):
        errors.append(f"Line {line_no}: filter {func!r} needs {len(argtypes)} "
                      f"argument(s) ({argtypes}), got {len(toks)}")
    for k, (tok, want) in enumerate(zip(toks, argtypes)):
        is_const = set(tok) <= _CONST_CHARS
        if want == "C" and not is_const:
            hint = f"; use {func}V for two variables" if func + "V" in _FILTER_ARGTYPES else ""
            errors.append(f"Line {line_no}: filter {func!r} argument {k+1} must be a "
                          f"constant, got {tok!r}{hint}")
        elif want == "V" and is_const:
            errors.append(f"Line {line_no}: filter {func!r} argument {k+1} must be an "
                          f"observation variable, got constant {tok!r}")
        elif want == "V" and tok not in known_obs:
            errors.append(
                f"Line {line_no}: filter {func!r} uses unknown variable {tok!r} "
                "(not declared above this line)")
    if len(toks) > len(argtypes):
        # readargs stops after len(argtypes) tokens, so CRHM runs and ignores the rest
        warnings.append(f"Line {line_no}: filter {func!r} takes {len(argtypes)} "
                        f"argument(s) ({argtypes}), got {len(toks)}; CRHM ignores the rest")
    return to_var


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
    # CRHM reads the .obs file as plain bytes (std::ifstream). Header comments in
    # shipped files (e.g. the Bad Lake fixture) hold non-UTF-8 bytes such as a
    # Latin-1 degree sign, so do not fail on them; numeric fields are ASCII.
    with open(obs_path, "r", encoding="utf-8", errors="replace") as f:
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
    separator_seen = False
    known_obs = set()      # declared observations + outputs of earlier filters
    filter_seen = False    # a filter with an output variable was declared

    for i, line in enumerate(lines[1:], start=1):
        stripped = line.strip()
        if not stripped:
            continue
        # CRHM ClassData.cpp (pinned b6f7e70): a header line starting with '#'
        # ends the header (one '#' is enough; "####..." is only the usual
        # style), and a line starting with '/' is a comment.
        if stripped.startswith("#"):
            separator_seen = True
            data_start_idx = i + 1
            break
        if stripped.startswith("/"):
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
            # Computed variable (CRHM "filter"): "$varname func(args) (unit) description"
            results["computed_variables"].append(stripped)
            to_var = _check_filter(stripped, i + 1, known_obs, results["errors"], results["warnings"])
            if to_var:
                known_obs.add(to_var)
                filter_seen = True
        else:
            # Regular variable declaration
            parts = stripped.split()
            if len(parts) >= 2:
                try:
                    n_cols = int(parts[1])
                    var_name = parts[0]
                    # CRHM ClassData.cpp (pinned commit b6f7e70) accepts a negative
                    # count: |n| is the column count and the minus sign flags
                    # integral (interval-total) data. Zero columns is not valid.
                    if n_cols == 0:
                        results["errors"].append(f"Line {i+1}: column count must not be zero")
                    if filter_seen:
                        results["errors"].append(
                            f"Line {i+1}: observation {var_name!r} declared after a filter; "
                            "CRHM requires filters ($ lines) to follow all observations")
                    unit = ""
                    if len(parts) >= 3:
                        unit = " ".join(parts[2:])
                    results["variables"].append({
                        "name": var_name,
                        "n_columns": abs(n_cols),
                        "integral": n_cols < 0,
                        "unit": unit,
                    })
                    known_obs.add(var_name)
                    total_data_cols += abs(n_cols)
                except ValueError:
                    results["warnings"].append(f"Line {i+1}: Cannot parse variable declaration: {stripped}")

    results["n_columns_expected"] = total_data_cols
    if not separator_seen:
        results["errors"].append("Missing mandatory header separator (a line starting with '#', usually ####) before observation data")

    if data_start_idx is None:
        results["errors"].append("No data rows found in file")
        return results

    # Check required variables
    var_names = [v["name"] for v in results["variables"]]
    if "t" not in var_names:
        results["errors"].append("CRITICAL: Temperature variable 't' not declared in header")
    # CRHM reads p as interval precipitation and ppt as daily precipitation.
    if "p" not in var_names and "ppt" not in var_names:
        results["errors"].append("CRITICAL: Precipitation variable 'p' (or legacy 'ppt') not declared in header")
    for var in results["variables"]:
        if var["name"] in ("p", "ppt"):
            match = re.search(r"\(([^)]*)\)", var["unit"])
            unit = match.group(1).lower().replace(" ", "") if match else ""
            allowed = {"mm", "mm/int", "mm/interval"} if var["name"] == "p" else {"mm/d", "mm/day"}
            if unit not in allowed:
                results["errors"].append(f"{var['name']} has invalid precipitation unit {var['unit']!r}; pressure must be named press")

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
            results["errors"].append(f"Line {i+1}: Too few columns ({len(parts)})")
            continue

        # Parse datetime (YYYY M D H 0)
        try:
            year, month, day, hour, minute = map(int, parts[:5])
            if hour == 24 and minute == 0:
                dt = datetime(year, month, day) + timedelta(days=1)
            else:
                dt = datetime(year, month, day, hour, minute)
        except (ValueError, IndexError) as e:
            results["errors"].append(f"Line {i+1}: Invalid datetime: {e}")
            continue

        results["n_data_rows"] += 1

        if results["date_range"]["start"] is None:
            results["date_range"]["start"] = dt.isoformat()

        # Check for gaps
        if prev_dt is not None:
            gap = dt - prev_dt
            if gap.total_seconds() <= 0:
                results["errors"].append(f"Line {i+1}: observation times must increase")
            if results["timestep_hours"] is None:
                results["timestep_hours"] = gap.total_seconds() / 3600
            else:
                expected_gap = timedelta(hours=results["timestep_hours"])
                if gap != expected_gap:
                    results["n_gaps"] += 1
                    if results["n_gaps"] <= 5:
                        results["errors"].append(
                            f"Gap at {dt}: expected {expected_gap}, got {gap}"
                        )

        prev_dt = dt

        # Check column count
        data_cols = parts[5:]  # skip YYYY M D H 0
        if len(data_cols) != total_data_cols:
            col_count_errors += 1
            if col_count_errors <= 3:
                results["errors"].append(
                    f"Line {i+1}: Expected {total_data_cols} data columns, got {len(data_cols)}"
                )

        # Check value bounds
        col_idx = 0
        for var in results["variables"]:
            for j in range(var["n_columns"]):
                if col_idx < len(data_cols):
                    try:
                        val = float(data_cols[col_idx])
                        if not math.isfinite(val):
                            raise ValueError("non-finite observation")
                        if var["name"] in PHYSICAL_BOUNDS:
                            lo, hi = PHYSICAL_BOUNDS[var["name"]]
                            if val < lo or val > hi:
                                key = f"{var['name']}_out_of_bounds"
                                if key not in results["value_bounds"]:
                                    results["value_bounds"][key] = 0
                                results["value_bounds"][key] += 1
                    except ValueError:
                        results["errors"].append(f"Line {i+1}: invalid {var['name']} value {data_cols[col_idx]!r}")
                col_idx += 1

    if prev_dt:
        results["date_range"]["end"] = prev_dt.isoformat()
    if results["n_data_rows"] < 2:
        results["errors"].append("At least two observation rows are required to establish the timestep")

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
