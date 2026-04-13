#!/usr/bin/env python3
"""
met_quality_check.py
====================
Quality-check a RZWQM2 .met file.

Corrections applied:
  - Swap Tmin/Tmax if Tmin > Tmax (inverted).
  - Cap RH at 100 if RH > 100.

Uses rzwqm_met_quality_check() from the RZWQM class in rzwqm_file.py.

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
PROJECT_PATH = ""       # RZWQM2 project root path (contains Meteorology/ folder)
STATION_ID = ""         # Station or grid identifier (becomes filename stem)

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))


def validate_inputs(project_path, station_id):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not project_path:
        errors.append("PROJECT_PATH is required.")
    elif not os.path.isdir(project_path):
        errors.append(f"PROJECT_PATH does not exist: {project_path}")

    if not station_id:
        errors.append("STATION_ID is required.")

    if not errors:
        met_file = os.path.join(project_path, "Meteorology", station_id + ".met")
        if not os.path.isfile(met_file):
            errors.append(f"Met file not found: {met_file}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'project_path': project_path,
        'station_id': station_id,
        'met_file': met_file
    }


def process(args):
    """
    Run quality check on the .met file: fix inverted Tmin/Tmax, cap RH at 100.
    Returns (success, error_msg, corrections_summary).

    Accepts args dict with keys: project_path, station_id, met_file.
    If only met_file is provided, derives the other two from the path.
    """
    from rzwqm_file import RZWQM

    met_file = args.get('met_file', '')
    project_path = args.get('project_path', '')
    station_id = args.get('station_id', '')

    # Derive missing keys from met_file path if needed
    # Expected structure: {project_path}/Meteorology/{station_id}.met
    if met_file and (not project_path or not station_id):
        met_path = os.path.abspath(met_file)
        if os.path.basename(os.path.dirname(met_path)) == "Meteorology":
            project_path = project_path or os.path.dirname(os.path.dirname(met_path))
            station_id = station_id or os.path.splitext(os.path.basename(met_path))[0]
    elif project_path and station_id and not met_file:
        met_file = os.path.join(project_path, "Meteorology", station_id + ".met")

    if not met_file or not os.path.isfile(met_file):
        return False, f"Met file not found: {met_file}", None
    if not project_path:
        return False, "Cannot determine project_path from met_file path", None

    # Ensure trailing separator for RZWQM class
    if not project_path.endswith(('/', '\\')):
        project_path = project_path + '/'

    try:
        # Read the met file to count corrections before applying
        with open(met_file, encoding="ISO-8859-1") as f:
            lines = [line.rstrip('\n') for line in f]

        data_lines = lines[36:]
        tmin_tmax_swaps = 0
        rh_caps = 0
        for line in data_lines:
            parts = line.split()
            if len(parts) >= 10:
                try:
                    tmin = float(parts[2])
                    tmax = float(parts[3])
                    rh = float(parts[7])
                    if tmin > tmax:
                        tmin_tmax_swaps += 1
                    if rh > 100:
                        rh_caps += 1
                except ValueError:
                    continue

        # Apply the quality check (modifies file in-place)
        rz = RZWQM(project_path, station_id)
        rz.rzwqm_met_quality_check()

        summary = {
            'tmin_tmax_swaps': tmin_tmax_swaps,
            'rh_capped_at_100': rh_caps,
            'total_corrections': tmin_tmax_swaps + rh_caps
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(met_file):
    """Validate that the corrected .met file has no remaining issues."""
    errors = []

    if not os.path.isfile(met_file):
        return False, "Met file disappeared after processing."

    with open(met_file, encoding="ISO-8859-1") as f:
        lines = [line.rstrip('\n') for line in f]

    if len(lines) < 37:
        errors.append("Met file has fewer than 37 lines (header + at least 1 data line).")
        return False, "; ".join(errors)

    data_lines = lines[36:]
    remaining_issues = 0
    for i, line in enumerate(data_lines):
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            tmin = float(parts[2])
            tmax = float(parts[3])
            rh = float(parts[7])
            if tmin > tmax:
                remaining_issues += 1
            if rh > 100:
                remaining_issues += 1
        except ValueError:
            continue

    if remaining_issues > 0:
        errors.append(f"{remaining_issues} QC issues remain after correction.")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    project_path = sys.argv[1] if len(sys.argv) > 1 else PROJECT_PATH
    station_id = sys.argv[2] if len(sys.argv) > 2 else STATION_ID

    # Ensure project_path ends with separator for RZWQM class compatibility
    if project_path and not project_path.endswith(('/', '\\')):
        project_path = project_path + '/'

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(project_path, station_id)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(args['met_file'])
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "met_file": args['met_file'],
        "corrections": summary,
        "message": (
            f"QC complete. {summary['tmin_tmax_swaps']} Tmin/Tmax swaps, "
            f"{summary['rh_capped_at_100']} RH caps applied."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
