#!/usr/bin/env python3
"""
initialize_scenario.py
======================
Create a new RZWQM2 scenario by copying an existing template scenario and
updating its ipnames.dat with new file paths and simulation dates.

Uses initialize_scneario_based_on_existing() from rzwqm_file.py.

The function copies the template directory, updates ipnames.dat paths
(cntrl.dat, rzwqm.dat, rzinit.dat, plgen.dat, .sno, .met, .brk, .ana),
and sets the simulation start/end dates.

Inputs:
    project_path    - RZWQM2 project root path (contains scenario dirs)
    template_name   - Name of the existing template scenario directory
    new_name        - Name for the new scenario
    start_date      - Simulation start date (YYYY-MM-DD)
    end_date        - Simulation end date (YYYY-MM-DD)
    copy_snow       - Whether to copy .sno file (default: True)
    copy_met        - Whether to update .met/.brk paths (default: False)

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json
from datetime import datetime

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
# Canonical template: /home/server/RZWQM2/RZWQM2/template_bengbu/
# This is a clean Bengbu wheat project with all required files, DSSAT databases,
# and pre-patched Linux binary. ALL new projects should start by copying this.
PROJECT_PATH = "/home/server/RZWQM2/RZWQM2/template_bengbu/"  # Template project root
TEMPLATE_NAME = "bengbu_wheat"  # Scenario dir inside PROJECT_PATH to copy from
NEW_NAME = ""           # New scenario name (REQUIRED)
START_DATE = ""         # Simulation start date, YYYY-MM-DD (REQUIRED)
END_DATE = ""           # Simulation end date, YYYY-MM-DD (REQUIRED)
OUTPUT_DIR = ""         # Output project directory (OPTIONAL). If set, the new scenario is
                        # created here instead of inside PROJECT_PATH. The tool creates the
                        # standard project structure: OUTPUT_DIR/{NEW_NAME}/, Meteorology/, Analysis/.
COPY_SNOW = "True"      # Copy .sno file (True/False)
COPY_MET = "False"       # Update .met/.brk paths for new name (True/False)

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))


def _parse_bool(val):
    """Parse string to boolean."""
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ('true', '1', 'yes')


def validate_inputs(project_path, template_name, new_name, start_date_str, end_date_str,
                    output_dir='', copy_snow_str='True', copy_met_str='False'):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not project_path:
        errors.append("PROJECT_PATH is required.")
    elif not os.path.isdir(project_path):
        errors.append(f"PROJECT_PATH does not exist: {project_path}")

    if not template_name:
        errors.append("TEMPLATE_NAME is required.")

    if not new_name:
        errors.append("NEW_NAME is required.")

    if template_name and new_name and template_name == new_name and not output_dir:
        errors.append("NEW_NAME must differ from TEMPLATE_NAME (unless OUTPUT_DIR is set).")

    # Validate template directory exists
    if project_path and template_name:
        template_dir = os.path.join(project_path, template_name)
        if not os.path.isdir(template_dir):
            errors.append(f"Template scenario directory not found: {template_dir}")

    # Validate dates
    start_date = None
    end_date = None
    if not start_date_str:
        errors.append("START_DATE is required (YYYY-MM-DD).")
    else:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except ValueError:
            errors.append(f"START_DATE '{start_date_str}' is not valid YYYY-MM-DD.")

    if not end_date_str:
        errors.append("END_DATE is required (YYYY-MM-DD).")
    else:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        except ValueError:
            errors.append(f"END_DATE '{end_date_str}' is not valid YYYY-MM-DD.")

    if start_date and end_date and start_date > end_date:
        errors.append("START_DATE must be on or before END_DATE.")

    copy_snow = _parse_bool(copy_snow_str)
    copy_met = _parse_bool(copy_met_str)

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'project_path': project_path,
        'template_name': template_name,
        'new_name': new_name,
        'start_date': start_date,
        'end_date': end_date,
        'output_dir': output_dir,
        'copy_snow': copy_snow,
        'copy_met': copy_met
    }


def process(args):
    """
    Initialize a new scenario from the template.

    Two modes:
    1. OUTPUT_DIR set: Direct shutil.copytree to a new project directory.
       Creates OUTPUT_DIR/{new_name}/, Meteorology/, Analysis/ — a self-contained
       project that can be moved anywhere.
    2. OUTPUT_DIR not set: Use rzwqm_file library to clone within the same project root.

    Returns (success, error_msg, summary).
    """
    import shutil
    import glob

    project_path = args['project_path']
    template_name = args['template_name']
    new_name = args['new_name']
    start_date = args['start_date']
    end_date = args['end_date']
    copy_snow = args['copy_snow']
    copy_met = args['copy_met']
    output_dir = args.get('output_dir', '')

    try:
        template_scenario_dir = os.path.join(project_path, template_name)

        if output_dir:
            # --- Mode 1: Copy to a separate output directory ---
            os.makedirs(output_dir, exist_ok=True)
            new_dir = os.path.join(output_dir, new_name)

            # Copy scenario directory
            if os.path.exists(new_dir):
                shutil.rmtree(new_dir)
            shutil.copytree(template_scenario_dir, new_dir)

            # Create Meteorology/ and Analysis/ dirs
            met_dir = os.path.join(output_dir, 'Meteorology')
            ana_dir = os.path.join(output_dir, 'Analysis')
            os.makedirs(met_dir, exist_ok=True)
            os.makedirs(ana_dir, exist_ok=True)

            # Copy .sno file with new name
            template_met_dir = os.path.join(project_path, 'Meteorology')
            sno_dest = os.path.join(met_dir, new_name + '.sno')
            if not os.path.isfile(sno_dest):
                # Try template Meteorology/ first
                sno_sources = glob.glob(os.path.join(template_met_dir, '*.sno')) if os.path.isdir(template_met_dir) else []
                if not sno_sources:
                    # Fall back to .sno files in the scenario dir
                    sno_sources = glob.glob(os.path.join(new_dir, '*.sno'))
                if sno_sources:
                    shutil.copy2(sno_sources[0], sno_dest)

            # Clean output files from the copied scenario
            for pattern in ('*.OUT', '*.out', '*.PLT', '*.plt', '*.LOG', '*.log',
                            'PModel.log', 'DSSATWTH.WTH', 'STATE.BIN', 'stdout.txt',
                            'strace_out.txt', 'test.out', '*.bak', '*.bak2'):
                for f in glob.glob(os.path.join(new_dir, pattern)):
                    os.remove(f)

            # Update IPNAMES.DAT paths to point to the new project root
            ipnames_path = None
            for name in ('IPNAMES.DAT', 'ipnames.dat'):
                p = os.path.join(new_dir, name)
                if os.path.isfile(p):
                    ipnames_path = p
                    break

            if ipnames_path:
                # Ensure output_dir ends with /
                root = output_dir if output_dir.endswith('/') else output_dir + '/'
                sd = start_date.strftime('%-d  %-m  %Y')
                ed = end_date.strftime('%-d  %-m  %Y')
                new_lines = [
                    f"{root}{new_name}//cntrl.dat",
                    f"{root}{new_name}//rzwqm.dat",
                    f"{root}Meteorology//{new_name}.met",
                    f"{root}Meteorology//{new_name}.brk",
                    f"{root}{new_name}//rzinit.dat",
                    f"{root}{new_name}//plgen.dat",
                    f"{root}Meteorology//{new_name}.sno",
                    f"{root}Analysis//{new_name}.ana",
                    f"{sd}  {ed}",
                ]
                with open(ipnames_path, 'r', encoding='ISO-8859-1') as f:
                    old_lines = f.readlines()
                # Preserve comment/control lines after line 8
                remaining = old_lines[9:] if len(old_lines) > 9 else []
                with open(ipnames_path, 'w', encoding='ISO-8859-1') as f:
                    for line in new_lines:
                        f.write(line + '\n')
                    for line in remaining:
                        f.write(line)

            # Update RZX paths to relative (DSSAT/ and ./).
            # The two path lines are at fixed positions in the .RZX file:
            # they follow the "DATABASE FILE LOCATIONS" section header.
            # Typically at lines 68-69 (0-indexed). Do NOT use string matching
            # on 'DSSAT' — that catches comment lines like "RZWQM-DSSAT CONTROL FILE".
            for rzx in glob.glob(os.path.join(new_dir, '*DSSAT.RZX')):
                with open(rzx, 'r', encoding='ISO-8859-1') as f:
                    rzx_lines = [l.rstrip('\n') for l in f]
                # Find DATABASE FILE LOCATIONS marker
                marker = -1
                for idx, l in enumerate(rzx_lines):
                    if 'DATABASE FILE LOCATION' in l.upper():
                        marker = idx
                        break
                if marker >= 0:
                    # Path lines are the next two non-comment lines after the marker
                    p1 = marker + 1
                    while p1 < len(rzx_lines) and rzx_lines[p1].strip().startswith('='):
                        p1 += 1
                    p2 = p1 + 1
                    while p2 < len(rzx_lines) and rzx_lines[p2].strip().startswith('='):
                        p2 += 1
                    if p2 < len(rzx_lines):
                        rzx_lines[p1] = 'DSSAT/'
                        rzx_lines[p2] = './'
                elif len(rzx_lines) > 69:
                    # Fallback: fixed positions 68-69
                    rzx_lines[68] = 'DSSAT/'
                    rzx_lines[69] = './'
                with open(rzx, 'w', encoding='ISO-8859-1') as f:
                    for l in rzx_lines:
                        f.write(l + '\n')

            effective_project_path = output_dir
        else:
            # --- Mode 2: Clone within same project root (legacy) ---
            from rzwqm_file import initialize_scneario_based_on_existing
            initialize_scneario_based_on_existing(
                project_path, template_name, new_name,
                copy_snow, (start_date, end_date), copy_met
            )
            new_dir = os.path.join(project_path, new_name)
            met_dir = os.path.join(project_path, 'Meteorology')
            effective_project_path = project_path

        # Ensure .sno file exists in Meteorology/ with the new name
        met_dir = os.path.join(effective_project_path, 'Meteorology')
        os.makedirs(met_dir, exist_ok=True)
        sno_dest = os.path.join(met_dir, new_name + '.sno')
        if not os.path.isfile(sno_dest) or os.path.getsize(sno_dest) == 0:
            sno_sources = glob.glob(os.path.join(new_dir, '*.sno'))
            if sno_sources:
                shutil.copy2(sno_sources[0], sno_dest)

        # Verify binary exists in new scenario (copied from template)
        binary_found = None
        for name in ('main_ryzen_patched', 'main_ryzen', 'RZWQMRelease.exe'):
            bp = os.path.join(new_dir, name)
            if os.path.isfile(bp):
                os.chmod(bp, 0o755)
                binary_found = name
                break

        summary = {
            'new_scenario_dir': new_dir,
            'project_root': effective_project_path,
            'template_used': template_name,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'snow_copied': copy_snow,
            'met_paths_updated': copy_met,
            'binary': binary_found or 'NOT FOUND — copy manually'
        }
        return True, "", summary

    except Exception as e:
        import traceback
        return False, f"Processing error: {e}\n{traceback.format_exc()}", None


def validate_outputs(args):
    """Validate the new scenario was created correctly."""
    errors = []

    effective_root = args.get('output_dir') or args['project_path']
    new_dir = os.path.join(effective_root, args['new_name'])
    if not os.path.isdir(new_dir):
        return False, f"New scenario directory was not created: {new_dir}"

    # Check ipnames.dat exists and has correct paths (case-insensitive)
    ipnames_path = os.path.join(new_dir, 'ipnames.dat')
    if not os.path.isfile(ipnames_path):
        # Try uppercase (IPNAMES.DAT) — the template uses this
        ipnames_path = os.path.join(new_dir, 'IPNAMES.DAT')
    if not os.path.isfile(ipnames_path):
        errors.append(f"ipnames.dat/IPNAMES.DAT not found in new scenario: {new_dir}")
    else:
        with open(ipnames_path, encoding="ISO-8859-1") as f:
            lines = [line.rstrip('\n') for line in f]

        if len(lines) < 9:
            errors.append(f"ipnames.dat has only {len(lines)} lines, expected at least 9.")

    # Check essential files exist (case-insensitive: rzwqm.dat or RZWQM.dat)
    for fname_pair in [('rzwqm.dat', 'RZWQM.dat'), ('cntrl.dat', 'CNTRL.DAT')]:
        found = False
        for fname in fname_pair:
            if os.path.isfile(os.path.join(new_dir, fname)):
                found = True
                break
        if not found:
            errors.append(f"Expected file not found: {fname_pair[0]} (checked both cases)")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    project_path = sys.argv[1] if len(sys.argv) > 1 else PROJECT_PATH
    template_name = sys.argv[2] if len(sys.argv) > 2 else TEMPLATE_NAME
    new_name = sys.argv[3] if len(sys.argv) > 3 else NEW_NAME
    start_date_str = sys.argv[4] if len(sys.argv) > 4 else START_DATE
    end_date_str = sys.argv[5] if len(sys.argv) > 5 else END_DATE
    output_dir = sys.argv[6] if len(sys.argv) > 6 else OUTPUT_DIR
    copy_snow_str = sys.argv[7] if len(sys.argv) > 7 else COPY_SNOW
    copy_met_str = sys.argv[8] if len(sys.argv) > 8 else COPY_MET

    # Ensure project_path ends with separator for RZWQM class compatibility
    if project_path and not project_path.endswith(('/', '\\')):
        project_path = project_path + '/'

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(
        project_path, template_name, new_name,
        start_date_str, end_date_str, output_dir, copy_snow_str, copy_met_str
    )
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
            f"Scenario '{args['new_name']}' created from template "
            f"'{args['template_name']}' ({summary['start_date']} to {summary['end_date']})."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
