#!/usr/bin/env python3
"""
update_rzx_paths.py
===================
Update DSSAT database path and project path in all .RZX files within a
scenario directory.

NEW TOOL: Not based on an existing function in rzwqm_file.py.

.RZX files contain a section titled "= DATABASE FILE LOCATIONS" (or similar).
The two path lines immediately following the database file locations header
(typically around lines 68-69, 0-indexed) contain:
    - Line 68: DSSAT database file path
    - Line 69: Project path

This tool reads each .RZX file, locates the database file locations section,
and replaces the two path lines with the new values.

Inputs:
    scenario_dir    - Directory containing .RZX file(s)
    dssat_db_path   - New DSSAT database file path
    project_path    - New project path

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
SCENARIO_DIR = ""       # Directory containing .RZX file(s)
DSSAT_DB_PATH = ""      # New DSSAT database file path
PROJECT_PATH = ""       # New project path

# Section header to search for in RZX files
DB_SECTION_MARKER = "= DATABASE FILE LOCATIONS"


def validate_inputs(scenario_dir, dssat_db_path, project_path):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not scenario_dir:
        errors.append("SCENARIO_DIR is required.")
    elif not os.path.isdir(scenario_dir):
        errors.append(f"SCENARIO_DIR does not exist: {scenario_dir}")

    if not dssat_db_path:
        errors.append("DSSAT_DB_PATH is required.")

    if not project_path:
        errors.append("PROJECT_PATH is required.")

    # Find .RZX files
    rzx_files = []
    if scenario_dir and os.path.isdir(scenario_dir):
        for f in os.listdir(scenario_dir):
            if f.upper().endswith('.RZX'):
                rzx_files.append(os.path.join(scenario_dir, f))

        if not rzx_files:
            errors.append(f"No .RZX files found in {scenario_dir}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'scenario_dir': scenario_dir,
        'dssat_db_path': dssat_db_path,
        'project_path': project_path,
        'rzx_files': rzx_files
    }


def _find_db_section_line(lines):
    """
    Find the line number of the DATABASE FILE LOCATIONS section header.
    Returns the 0-based index, or -1 if not found.
    """
    for i, line in enumerate(lines):
        if DB_SECTION_MARKER in line:
            return i
    return -1


def _update_single_rzx(rzx_path, dssat_db_path, project_path):
    """
    Update a single .RZX file's database and project paths.
    Returns (success, error_msg, was_modified).
    """
    try:
        with open(rzx_path, 'r', encoding='ISO-8859-1') as f:
            lines = [line.rstrip('\n') for line in f]

        marker_line = _find_db_section_line(lines)
        if marker_line == -1:
            # Try a broader search for common variations
            for i, line in enumerate(lines):
                if 'DATABASE FILE' in line.upper() and 'LOCATION' in line.upper():
                    marker_line = i
                    break

        if marker_line == -1:
            # Fall back to fixed line positions (68-69 are common)
            # Check if lines 68 and 69 look like paths
            if len(lines) > 69:
                line68 = lines[68].strip()
                line69 = lines[69].strip()
                # Heuristic: if they contain path separators or drive letters, treat as paths
                if (('/' in line68 or '\\' in line68 or ':' in line68) and
                        ('/' in line69 or '\\' in line69 or ':' in line69)):
                    marker_line = 67  # So +1 = 68, +2 = 69
                else:
                    return False, (
                        f"Cannot locate DATABASE FILE LOCATIONS section in {rzx_path}. "
                        f"No section header found and lines 68-69 do not look like paths."
                    ), False
            else:
                return False, (
                    f"Cannot locate DATABASE FILE LOCATIONS section in {rzx_path} "
                    f"and file has fewer than 70 lines."
                ), False

        # The two path lines follow the section header
        # Typically they are at marker_line + 1 and marker_line + 2
        # But we need to skip any additional comment lines (starting with '=')
        path_line_1 = marker_line + 1
        while path_line_1 < len(lines) and lines[path_line_1].strip().startswith('='):
            path_line_1 += 1

        path_line_2 = path_line_1 + 1
        while path_line_2 < len(lines) and lines[path_line_2].strip().startswith('='):
            path_line_2 += 1

        if path_line_2 >= len(lines):
            return False, (
                f"Could not find both path lines after DATABASE FILE LOCATIONS "
                f"section in {rzx_path}"
            ), False

        # Replace the path lines with RELATIVE paths.
        # RZWQM2 runs from the scenario directory as CWD, so DSSAT/ and ./ work.
        # Absolute paths cause "File not found" on some Linux configurations
        # because the Fortran binary concatenates paths differently than expected.
        lines[path_line_1] = 'DSSAT/'
        lines[path_line_2] = './'

        # Ensure nitrogen routines are ON (ISWNIT must be Y, not N)
        # Format: "Y  N  Y  N  N  N  N  C" where position 2 is ISWNIT
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Match the simulation control data line (8 fields, starts with Y/N)
            parts = stripped.split()
            if (len(parts) == 8 and parts[0] in ('Y', 'N') and parts[-1] in ('C', 'L')
                    and parts[1] in ('Y', 'N')):
                if parts[1] == 'N':
                    parts[1] = 'Y'
                    lines[i] = '  '.join(parts)
                break

        # Write back
        with open(rzx_path, 'w', encoding='ISO-8859-1') as f:
            for line in lines:
                f.write(line + '\n')

        return True, "", True

    except Exception as e:
        return False, f"Error processing {rzx_path}: {e}", False


def process(args):
    """
    Update all .RZX files in the scenario directory.
    Returns (success, error_msg, summary).
    """
    rzx_files = args['rzx_files']
    dssat_db_path = args['dssat_db_path']
    project_path = args['project_path']

    updated = []
    failed = []

    for rzx_path in rzx_files:
        ok, err, modified = _update_single_rzx(rzx_path, dssat_db_path, project_path)
        if ok:
            updated.append(rzx_path)
        else:
            failed.append({'file': rzx_path, 'error': err})

    if failed and not updated:
        return False, f"All RZX files failed: {json.dumps(failed)}", None

    summary = {
        'updated_files': updated,
        'failed_files': failed,
        'total_found': len(rzx_files),
        'total_updated': len(updated),
        'total_failed': len(failed),
        'dssat_db_path': dssat_db_path,
        'project_path': project_path
    }

    if failed:
        return True, f"Partial success: {len(failed)} files failed.", summary

    return True, "", summary


def validate_outputs(args):
    """Validate that updated .RZX files contain the new paths."""
    errors = []

    dssat_db_path = args['dssat_db_path']
    project_path = args['project_path']

    for rzx_path in args['rzx_files']:
        if not os.path.isfile(rzx_path):
            errors.append(f"RZX file missing after update: {rzx_path}")
            continue

        with open(rzx_path, 'r', encoding='ISO-8859-1') as f:
            content = f.read()

        if dssat_db_path not in content:
            errors.append(
                f"DSSAT database path not found in updated file: {rzx_path}"
            )
        if project_path not in content:
            errors.append(
                f"Project path not found in updated file: {rzx_path}"
            )

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    scenario_dir = sys.argv[1] if len(sys.argv) > 1 else SCENARIO_DIR
    dssat_db_path = sys.argv[2] if len(sys.argv) > 2 else DSSAT_DB_PATH
    project_path = sys.argv[3] if len(sys.argv) > 3 else PROJECT_PATH

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(scenario_dir, dssat_db_path, project_path)
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

    msg = (
        f"Updated {summary['total_updated']}/{summary['total_found']} RZX files. "
        f"DSSAT DB: {summary['dssat_db_path']}, Project: {summary['project_path']}."
    )
    if summary['total_failed'] > 0:
        msg += f" WARNING: {summary['total_failed']} files failed."

    print(json.dumps({
        "status": "SUCCESS",
        "summary": summary,
        "message": msg
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
