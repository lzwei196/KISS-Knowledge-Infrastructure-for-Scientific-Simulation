#!/usr/bin/env python3
"""
SWAP model execution wrapper with preflight checks and output validation.

Runs the SWAP binary in the specified working directory, validates that
required input files exist, and checks output files for completeness.

Usage:
    python run_swap.py \\
        --binary /path/to/swap \\
        --work-dir /path/to/case/ \\
        --swp-file swap.swp
"""

import argparse
import os
import subprocess
import sys
import time
import re
from pathlib import Path


def validate_inputs(binary, work_dir, swp_file):
    """
    Pre-flight checks before running SWAP.

    Verifies:
    1. Binary exists and is executable
    2. Working directory exists
    3. Main .swp file exists
    4. Referenced input files (.met, .crp, .dra, .bbc) exist
    5. All filenames are lowercase (Linux requirement)
    """
    errors = []
    warnings = []

    # Check binary
    if not os.path.isfile(binary):
        errors.append(f"SWAP binary not found: {binary}")
    elif not os.access(binary, os.X_OK):
        errors.append(f"SWAP binary not executable: {binary}")

    # Check work directory
    if not os.path.isdir(work_dir):
        errors.append(f"Working directory not found: {work_dir}")
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    # Check .swp file
    swp_path = os.path.join(work_dir, swp_file)
    if not os.path.isfile(swp_path):
        errors.append(f"Main input file not found: {swp_path}")
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    # Parse .swp file for referenced files
    with open(swp_path, "r") as f:
        content = f.read()

    # Extract METFIL
    met_match = re.search(r"METFIL\s*=\s*'([^']+)'", content)
    if met_match:
        met_file = met_match.group(1)
        # Check in PATHATM or work_dir
        pathatm_match = re.search(r"PATHATM\s*=\s*'([^']+)'", content)
        pathatm = pathatm_match.group(1) if pathatm_match else "./"
        if pathatm.startswith("./"):
            pathatm = work_dir

        met_path = os.path.join(pathatm, met_file)
        if not os.path.isfile(met_path):
            # Try without explicit extension — SWAP may append year extension
            found = False
            for ext in [".met", ""]:
                test = met_path + ext
                if os.path.isfile(test):
                    found = True
                    break
            if not found:
                errors.append(f"Meteorological file not found: {met_path}")

    # Extract crop files
    crop_matches = re.findall(r"CROPFIL\s*=\s*'([^']+)'", content)
    # Also from table format
    crop_table = re.findall(r"'(\w+)'\s+\d+\s*$", content, re.MULTILINE)
    for cf in set(crop_matches + crop_table):
        crp_path = os.path.join(work_dir, cf + ".crp")
        if not os.path.isfile(crp_path):
            pathcrop_match = re.search(r"PATHCROP\s*=\s*'([^']+)'", content)
            pathcrop = pathcrop_match.group(1).replace("./", work_dir + "/") if pathcrop_match else work_dir
            crp_path = os.path.join(pathcrop, cf + ".crp")
            if not os.path.isfile(crp_path):
                warnings.append(f"Crop file not found: {cf}.crp")

    # Extract drainage file
    dra_match = re.search(r"DRFIL\s*=\s*'([^']+)'", content)
    if dra_match:
        dra_file = dra_match.group(1) + ".dra"
        dra_path = os.path.join(work_dir, dra_file)
        if not os.path.isfile(dra_path):
            warnings.append(f"Drainage file not found: {dra_file}")

    # Check for uppercase filenames (Linux trap)
    for f_name in os.listdir(work_dir):
        if f_name != f_name.lower() and not f_name.startswith("."):
            warnings.append(f"Uppercase filename detected (Linux issue): {f_name}")

    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if errors:
        print(f"[FAIL] Preflight check failed with {len(errors)} errors")
        return False
    print(f"[OK] Preflight checks passed ({len(warnings)} warnings)")
    return True


def run_swap(binary, work_dir, swp_file, timeout=300):
    """
    Execute SWAP binary.

    Parameters
    ----------
    binary : str
        Path to SWAP executable
    work_dir : str
        Working directory containing input files
    swp_file : str
        Name of main .swp input file
    timeout : int
        Maximum runtime in seconds

    Returns
    -------
    dict : Execution result with returncode, stdout, stderr, elapsed
    """
    print(f"[RUN] Starting SWAP: {binary}")
    print(f"      Working dir: {work_dir}")
    print(f"      Config file: {swp_file}")

    start_time = time.time()

    try:
        result = subprocess.run(
            [binary],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time

        output = {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_seconds": round(elapsed, 2),
        }

        if result.returncode == 0:
            print(f"[OK] SWAP completed successfully in {elapsed:.1f}s")
        else:
            print(f"[FAIL] SWAP exited with code {result.returncode}")
            if result.stderr:
                print(f"STDERR: {result.stderr[:500]}")
            if result.stdout:
                print(f"STDOUT: {result.stdout[:500]}")

        return output

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"[FAIL] SWAP timed out after {timeout}s")
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Timeout after {timeout}s",
            "elapsed_seconds": round(elapsed, 2),
        }
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[FAIL] SWAP execution error: {e}")
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": str(e),
            "elapsed_seconds": round(elapsed, 2),
        }


def validate_outputs(work_dir, swp_file):
    """
    Post-execution validation of SWAP output files.

    Checks:
    1. Output files were created (.blc, .inc, .vap, etc.)
    2. Water balance closure (from .blc file)
    3. No error files (.dwb.csv)
    """
    errors = []
    warnings = []

    # Parse OUTFIL from .swp
    swp_path = os.path.join(work_dir, swp_file)
    outfil = "result"
    with open(swp_path, "r") as f:
        for line in f:
            m = re.search(r"OUTFIL\s*=\s*'([^']+)'", line)
            if m:
                outfil = m.group(1)
                break

    # Check expected output files
    expected = {
        ".blc": "Detailed water balance",
        ".inc": "Water balance increments",
    }

    # Also check optional files based on switches
    with open(swp_path, "r") as f:
        content = f.read()

    switch_file_map = {
        "SWVAP = 1": (".vap", "Soil profiles"),
        "SWBAL = 1": (".bal", "Yearly water balance"),
        "SWWBA = 1": (".wba", "Daily water balance"),
        "SWSBA = 1": (".sba", "Solute balance"),
        "SWATE = 1": (".ate", "Temperature profiles"),
    }

    for switch, (ext, desc) in switch_file_map.items():
        if switch.replace(" ", "") in content.replace(" ", ""):
            expected[ext] = desc

    for ext, desc in expected.items():
        fpath = os.path.join(work_dir, outfil + ext)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            if size == 0:
                warnings.append(f"{outfil}{ext} is empty (0 bytes)")
            else:
                print(f"  [OK] {outfil}{ext} ({size:,} bytes) — {desc}")
        else:
            warnings.append(f"Expected output not found: {outfil}{ext} ({desc})")

    # Check for error files
    for f_name in os.listdir(work_dir):
        if f_name.lower().endswith(".dwb.csv"):
            errors.append(f"Water balance error file found: {f_name}")

    # Parse water balance from .blc if available
    blc_path = os.path.join(work_dir, outfil + ".blc")
    if os.path.isfile(blc_path):
        try:
            with open(blc_path, "r") as f:
                blc_content = f.read()
            # Look for Sum lines
            sum_in = re.findall(r"Sum\s*:\s*([\d.]+)", blc_content)
            if len(sum_in) >= 2:
                s_in = float(sum_in[0])
                s_out = float(sum_in[1])
                diff = abs(s_in - s_out)
                print(f"  [INFO] Water balance: In={s_in:.2f} cm, Out={s_out:.2f} cm, "
                      f"Diff={diff:.2f} cm")
                if diff > 1.0:
                    warnings.append(
                        f"Large water balance discrepancy: {diff:.2f} cm "
                        f"(check storage change)"
                    )
        except Exception as e:
            warnings.append(f"Could not parse .blc file: {e}")

    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if errors:
        print(f"[FAIL] Output validation failed with {len(errors)} errors")
        return False
    print(f"[OK] Output validation passed ({len(warnings)} warnings)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Run SWAP model with validation")
    parser.add_argument("--binary", type=str, required=True,
                        help="Path to SWAP executable")
    parser.add_argument("--work-dir", type=str, required=True,
                        help="Working directory with input files")
    parser.add_argument("--swp-file", type=str, default="swap.swp",
                        help="Name of main .swp configuration file")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Maximum runtime in seconds")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Skip preflight validation")
    args = parser.parse_args()

    # Preflight
    if not args.skip_preflight:
        if not validate_inputs(args.binary, args.work_dir, args.swp_file):
            sys.exit(1)

    # Execute
    result = run_swap(args.binary, args.work_dir, args.swp_file, args.timeout)

    if result["returncode"] != 0:
        sys.exit(1)

    # Validate outputs
    validate_outputs(args.work_dir, args.swp_file)


if __name__ == "__main__":
    main()
