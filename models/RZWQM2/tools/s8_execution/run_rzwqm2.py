#!/usr/bin/env python3
"""
run_rzwqm2.py
=============
Execute the RZWQM2 binary from a scenario directory.

Platform support:
  - Windows: RZWQMRelease.exe (run directly)
  - Linux:   main_ryzen (may need patchelf for interpreter, needs AVX2)

The binary reads ipnames.dat from its current working directory (CWD),
so execution must happen from inside the scenario directory.

Before running, this tool validates:
  1. The binary exists and is executable
  2. ipnames.dat exists in the scenario directory
  3. All input files referenced by ipnames.dat exist
  4. On Linux: AVX2 CPU support is available

After running, it checks for the .ana output file.

Inputs:
    scenario_dir    - Scenario directory containing ipnames.dat
    binary_path     - Path to RZWQM2 executable
    timeout         - Max execution time in seconds (default: 3600)

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error (model failed)
    3 - Output validation error
"""

import sys
import os
import json
import subprocess
import platform

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
SCENARIO_DIR = ""       # Scenario directory containing ipnames.dat
BINARY_PATH = "KISSPATH_HOME/RZWQM2/RZWQM2/linux/main_ryzen_patched"  # RZWQM2 executable (also copied into each scenario dir)
TIMEOUT = "3600"        # Max execution time in seconds

# ---------------------------------------------------------------------------
# No data_prep_tools import needed — this tool is standalone
# ---------------------------------------------------------------------------


def validate_inputs(scenario_dir, binary_path, timeout_raw):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not scenario_dir:
        errors.append("SCENARIO_DIR is required.")
    elif not os.path.isdir(scenario_dir):
        errors.append(f"SCENARIO_DIR does not exist: {scenario_dir}")

    if not binary_path:
        errors.append("BINARY_PATH is required.")
    elif not os.path.isfile(binary_path):
        errors.append(f"BINARY_PATH does not exist: {binary_path}")
    elif not os.access(binary_path, os.X_OK):
        errors.append(f"BINARY_PATH is not executable: {binary_path}")

    timeout = 3600
    if timeout_raw:
        try:
            timeout = int(timeout_raw)
        except ValueError:
            errors.append(f"TIMEOUT must be an integer, got: {timeout_raw}")

    # Check ipnames.dat exists
    ipnames_path = None
    if scenario_dir:
        ipnames_path = os.path.join(scenario_dir, 'ipnames.dat')
        if not os.path.isfile(ipnames_path):
            alt_path = os.path.join(scenario_dir, 'IPNAMES.DAT')
            if os.path.isfile(alt_path):
                ipnames_path = alt_path
            else:
                errors.append(f"ipnames.dat not found in scenario directory: {scenario_dir}")

    # Validate files referenced by ipnames.dat
    ana_path = None
    if ipnames_path and os.path.isfile(ipnames_path):
        with open(ipnames_path, encoding="ISO-8859-1") as f:
            lines = [line.rstrip('\n') for line in f]

        input_file_names = [
            'cntrl.dat', 'RZWQM.dat', '.met file', '.brk file',
            'RZINIT.dat', 'plgen.dat', '.sno file'
        ]
        for i in range(min(7, len(lines))):
            path = lines[i].strip().replace('\\', '/').replace('//', '/')
            if not os.path.isabs(path):
                path = os.path.join(scenario_dir, path)
            if not os.path.isfile(path):
                name = input_file_names[i] if i < len(input_file_names) else f"line {i}"
                errors.append(f"File referenced by ipnames.dat line {i} ({name}) not found: {lines[i].strip()}")

        # Extract .ana output path (line 7)
        if len(lines) > 7:
            ana_ref = lines[7].strip().replace('\\', '/').replace('//', '/')
            if not os.path.isabs(ana_ref):
                ana_path = os.path.join(scenario_dir, ana_ref)
            else:
                ana_path = ana_ref
            # Ensure output directory exists
            ana_dir = os.path.dirname(ana_path)
            if ana_dir and not os.path.isdir(ana_dir):
                errors.append(f"Analysis output directory does not exist: {ana_dir}")

    # Check AVX2 on Linux
    if platform.system() == 'Linux' and binary_path and 'ryzen' in binary_path.lower():
        try:
            with open('/proc/cpuinfo') as f:
                cpuinfo = f.read()
            if 'avx2' not in cpuinfo:
                errors.append(
                    "CPU does not support AVX2 instructions. "
                    "The main_ryzen binary requires AVX2 (Intel Haswell+ or AMD Zen+). "
                    "See diagnostic triplet dt_007."
                )
        except FileNotFoundError:
            pass  # Not on Linux or /proc not available

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'scenario_dir': scenario_dir,
        'binary_path': os.path.abspath(binary_path),
        'timeout': timeout,
        'ipnames_path': ipnames_path,
        'ana_path': ana_path
    }


def process(args):
    """
    Run RZWQM2 binary from the scenario directory.
    Returns (success, error_msg, summary).
    """
    scenario_dir = args['scenario_dir']
    binary_path = args['binary_path']
    timeout = args['timeout']

    try:
        result = subprocess.run(
            [binary_path],
            cwd=scenario_dir,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        stdout_lines = result.stdout.strip().split('\n') if result.stdout else []
        stderr_lines = result.stderr.strip().split('\n') if result.stderr else []

        summary = {
            'return_code': result.returncode,
            'stdout_lines': len(stdout_lines),
            'stderr_lines': len(stderr_lines),
            'last_stdout': stdout_lines[-1] if stdout_lines else "(empty)",
        }

        if result.returncode != 0:
            # Check for known failure patterns
            full_output = result.stdout + result.stderr
            if 'SIGSEGV' in full_output or 'segmentation fault' in full_output.lower():
                return False, (
                    f"RZWQM2 crashed with segfault (return code {result.returncode}). "
                    f"Check diagnostic triplets dt_002 (RZX paths), dt_006 (DSSAT init), "
                    f"dt_007 (AVX2/ARM). Last output: {summary['last_stdout']}"
                ), summary
            return False, (
                f"RZWQM2 exited with return code {result.returncode}. "
                f"Last output: {summary['last_stdout']}"
            ), summary

        return True, "", summary

    except subprocess.TimeoutExpired:
        return False, f"RZWQM2 execution timed out after {timeout} seconds.", None
    except Exception as e:
        return False, f"Failed to execute RZWQM2: {e}", None


def validate_outputs(args):
    """Verify that .ana output file was created."""
    errors = []

    ana_path = args.get('ana_path')
    if ana_path:
        if not os.path.isfile(ana_path):
            errors.append(f".ana output file was not created: {ana_path}")
        else:
            size = os.path.getsize(ana_path)
            if size == 0:
                errors.append(f".ana output file is empty: {ana_path}")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    scenario_dir = sys.argv[1] if len(sys.argv) > 1 else SCENARIO_DIR
    binary_path = sys.argv[2] if len(sys.argv) > 2 else BINARY_PATH
    timeout_raw = sys.argv[3] if len(sys.argv) > 3 else TIMEOUT

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(scenario_dir, binary_path, timeout_raw)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err, "summary": summary}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(args)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "ana_file": args.get('ana_path', ''),
        "summary": summary,
        "message": (
            f"RZWQM2 completed successfully (return code 0). "
            f"{summary['stdout_lines']} stdout lines."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
