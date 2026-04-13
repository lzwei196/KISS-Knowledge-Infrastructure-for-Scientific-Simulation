#!/usr/bin/env python3
"""
create_breakpoint_file.py
=========================
Generate a RZWQM2 breakpoint rainfall file (.brk) from daily precipitation
data in a .met file.

Converts precipitation from mm (as stored in .met) to inches (divide by 25.4)
for the .brk format.  Each rainy day becomes a breakpoint event with 2
breakpoints (start at 0, full depth at computed clock time).

Uses create_breakpoint_file() from the RZWQM class in rzwqm_file.py.

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
        brk_file = os.path.join(project_path, "Meteorology", station_id + ".brk")
        if not os.path.isfile(met_file):
            errors.append(f"Met file not found: {met_file}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'project_path': project_path,
        'station_id': station_id,
        'met_file': met_file,
        'brk_file': brk_file
    }


def process(args):
    """
    Create the .brk file from .met precipitation data.
    Returns (success, error_msg, summary).
    """
    from rzwqm_file import RZWQM

    project_path = args['project_path']
    station_id = args['station_id']

    try:
        rz = RZWQM(project_path, station_id)

        # Count rain events in the met file before creating brk
        rain_data = rz.return_date_time_turple_for_met_variable(9)
        rain_events = sum(1 for _, precip in rain_data if precip > 0)
        total_rain_mm = sum(precip for _, precip in rain_data if precip > 0)

        # Create the breakpoint file
        rz.create_breakpoint_file()

        summary = {
            'rain_events': rain_events,
            'total_rain_mm': round(total_rain_mm, 2),
            'total_rain_inches': round(total_rain_mm / 25.4, 3),
            'brk_file': args['brk_file']
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(brk_file):
    """Validate the generated .brk file. Returns (valid, error_msg)."""
    errors = []

    if not os.path.isfile(brk_file):
        return False, f"Breakpoint file was not created: {brk_file}"

    with open(brk_file, 'r') as f:
        lines = [line.rstrip('\n') for line in f]

    # The header is 20 lines (19 comment/header lines + '1' for calendar code)
    if len(lines) < 20:
        errors.append(f"Breakpoint file too short: {len(lines)} lines.")
    else:
        # Check that it starts with the correct header
        if not lines[0].startswith("===="):
            errors.append("First line does not start with '===='.")
        # Calendar code line should be '1' at line index 19
        if lines[19].strip() != '1':
            errors.append(f"Calendar code line (20) expected '1', got '{lines[19].strip()}'.")

        # Check that there are event lines after header
        event_lines = lines[20:]
        if not event_lines:
            # This is acceptable if there were no rain days
            pass
        else:
            # Spot-check first event line format
            first_event = event_lines[0].split()
            if len(first_event) < 5:
                errors.append(
                    f"First event line has {len(first_event)} fields, expected 5 "
                    "(year, julian_day, num_breakpoints, midnight_flag, total_depth)."
                )

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
    valid, err = validate_outputs(args['brk_file'])
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "brk_file": args['brk_file'],
        "summary": summary,
        "message": (
            f"Breakpoint file created with {summary['rain_events']} rain events, "
            f"total precip {summary['total_rain_mm']} mm ({summary['total_rain_inches']} in)."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
