#!/usr/bin/env python3
"""
update_ipnames_paths.py
=======================
Update all file paths in ipnames.dat for a given RZWQM2 scenario.

Follows the mass_updating_ipnames_directory() pattern from rzwqm_file.py.
Updates paths for:
    Line 0: cntrl.dat
    Line 1: rzwqm.dat
    Line 2: .met file
    Line 3: .brk file
    Line 4: rzinit.dat
    Line 5: plgen.dat
    Line 6: .sno file
    Line 7: .ana file

The paths are constructed as:
    new_root + station_id + //file.dat   (for scenario files)
    new_root + Meteorology// + station_id + .ext (for met/brk/sno)
    new_root + Analysis// + station_id + .ana (for analysis)

Inputs:
    project_path    - Current RZWQM2 project root
    station_id      - Station or grid identifier
    new_root        - New root directory for all paths

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
PROJECT_PATH = ""       # Current RZWQM2 project root
STATION_ID = ""         # Station or grid identifier
NEW_ROOT = ""           # New root directory to use in all paths
START_DATE = ""         # Simulation start date (YYYY-MM-DD), optional
END_DATE = ""           # Simulation end date (YYYY-MM-DD), optional

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))


def validate_inputs(project_path, station_id, new_root, start_date='', end_date=''):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    from datetime import datetime
    errors = []

    if not project_path:
        errors.append("PROJECT_PATH is required.")
    elif not os.path.isdir(project_path):
        errors.append(f"PROJECT_PATH does not exist: {project_path}")

    if not station_id:
        errors.append("STATION_ID is required.")

    if not new_root:
        errors.append("NEW_ROOT is required.")

    # Parse optional simulation dates
    parsed_start = parsed_end = None
    if start_date and end_date:
        try:
            parsed_start = datetime.strptime(start_date.strip(), '%Y-%m-%d')
            parsed_end = datetime.strptime(end_date.strip(), '%Y-%m-%d')
            if parsed_start >= parsed_end:
                errors.append("START_DATE must be before END_DATE.")
        except ValueError as e:
            errors.append(f"Date parse error: {e}")

    if not errors:
        ipnames_path = os.path.join(project_path, station_id, 'ipnames.dat')
        if not os.path.isfile(ipnames_path):
            # Try uppercase
            alt_path = os.path.join(project_path, station_id, 'IPNAMES.DAT')
            if os.path.isfile(alt_path):
                ipnames_path = alt_path
            else:
                errors.append(f"ipnames.dat not found: {ipnames_path}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'project_path': project_path,
        'station_id': station_id,
        'new_root': new_root,
        'ipnames_path': ipnames_path,
        'start_date': parsed_start,
        'end_date': parsed_end,
    }


def process(args):
    """
    Update all paths in ipnames.dat.
    Returns (success, error_msg, summary).
    """
    from rzwqm_file import RZWQM

    project_path = args['project_path']
    station_id = args['station_id']
    new_root = args['new_root']

    # Ensure new_root ends with separator
    if not new_root.endswith(('/', '\\')):
        new_root = new_root + '/'

    try:
        rz = RZWQM(project_path, station_id)
        ip = rz.ipnames

        # Store old paths for summary
        old_paths = ip[:8] if len(ip) >= 8 else ip[:]

        # Update paths — detect actual file case on disk for Linux compat
        scenario_dir = os.path.join(new_root, station_id)

        def _pick(directory, *candidates):
            """Return first filename that exists on disk; default to first."""
            for name in candidates:
                if os.path.isfile(os.path.join(directory, name)):
                    return name
            return candidates[0]

        dat_name = _pick(scenario_dir, 'rzwqm.dat', 'RZWQM.dat')
        init_name = _pick(scenario_dir, 'rzinit.dat', 'RZINIT.dat')

        ip[0] = new_root + station_id + "//cntrl.dat"
        ip[1] = new_root + station_id + "//" + dat_name
        ip[2] = new_root + 'Meteorology//' + station_id + '.met'
        ip[3] = new_root + 'Meteorology//' + station_id + '.brk'
        ip[4] = new_root + station_id + "//" + init_name
        ip[5] = new_root + station_id + "//plgen.dat"
        ip[6] = new_root + 'Meteorology//' + station_id + '.sno'
        ip[7] = new_root + "Analysis" + "//" + station_id + ".ana"

        # Update simulation dates if provided (line 8: DD MM YYYY DD MM YYYY)
        dates_updated = False
        if args.get('start_date') and args.get('end_date'):
            sd = args['start_date']
            ed = args['end_date']
            ip[8] = f"{sd.day}  {sd.month}  {sd.year}  {ed.day}  {ed.month}  {ed.year}"
            dates_updated = True

        # Write back
        with open(rz.ipnames_path, 'w') as file:
            for line in ip:
                file.write(line + '\n')

        new_paths = ip[:8]

        summary = {
            'ipnames_path': rz.ipnames_path,
            'new_root': new_root,
            'station_id': station_id,
            'lines_updated': 9 if dates_updated else 8,
            'dates_updated': dates_updated,
            'new_paths': new_paths
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(args):
    """Validate the updated ipnames.dat."""
    errors = []

    ipnames_path = args['ipnames_path']
    station_id = args['station_id']
    new_root = args['new_root']

    if not new_root.endswith(('/', '\\')):
        new_root = new_root + '/'

    if not os.path.isfile(ipnames_path):
        return False, f"ipnames.dat no longer exists: {ipnames_path}"

    with open(ipnames_path, encoding="ISO-8859-1") as f:
        lines = [line.rstrip('\n') for line in f]

    if len(lines) < 8:
        errors.append(f"ipnames.dat has only {len(lines)} lines, expected at least 8.")
    else:
        # Verify the new root is present in the first 8 lines
        # Use a normalized check (strip slashes)
        new_root_norm = new_root.rstrip('/\\')
        for i in range(8):
            if new_root_norm not in lines[i].replace('\\', '/').replace('//', '/'):
                # More lenient check: just see if the new_root prefix appears somewhere
                if new_root.rstrip('/') not in lines[i]:
                    errors.append(
                        f"Line {i} does not contain new root path. Got: '{lines[i]}'"
                    )

        # Verify station_id appears in paths
        for i in range(8):
            if station_id not in lines[i]:
                errors.append(
                    f"Line {i} does not contain station_id '{station_id}'."
                )

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    project_path = sys.argv[1] if len(sys.argv) > 1 else PROJECT_PATH
    station_id = sys.argv[2] if len(sys.argv) > 2 else STATION_ID
    new_root = sys.argv[3] if len(sys.argv) > 3 else NEW_ROOT
    start_date = sys.argv[4] if len(sys.argv) > 4 else START_DATE
    end_date = sys.argv[5] if len(sys.argv) > 5 else END_DATE

    # Ensure project_path ends with separator for RZWQM class compatibility
    if project_path and not project_path.endswith(('/', '\\')):
        project_path = project_path + '/'

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(project_path, station_id, new_root, start_date, end_date)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(args)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "summary": summary,
        "message": (
            f"Updated {summary['lines_updated']} path lines in "
            f"{summary['ipnames_path']} to root '{summary['new_root']}'."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
