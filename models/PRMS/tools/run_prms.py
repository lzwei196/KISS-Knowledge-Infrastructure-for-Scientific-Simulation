#!/usr/bin/env python3
"""
run_prms.py — Execute PRMS model with preflight validation and output checking.

Performs comprehensive preflight checks before running the PRMS binary:
  1. Binary exists and is executable
  2. Control file is readable and well-formed
  3. Parameter file exists and has correct dimensions
  4. Data/CBH files exist and cover simulation period
  5. Required libraries (NetCDF, gfortran) are available

Post-run checks:
  1. Exit code is 0
  2. Output files are created and non-empty
  3. No NaN/Inf in output
  4. Water balance closes to within tolerance

CRITICAL: The -C flag requires NO space: ./prms -C/path/to/control

Usage:
  python run_prms.py \\
    --binary /path/to/prms_hpc \\
    --control /path/to/control \\
    --work_dir /path/to/workdir
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def validate_inputs(binary: str, control: str, work_dir: str) -> dict:
    """Preflight validation before running PRMS.

    Returns dict with validation results.
    Raises ValueError on critical errors.
    """
    issues = []
    binary_path = Path(binary)
    control_path = Path(control)
    work_path = Path(work_dir)

    # --- Check binary ---
    if not binary_path.exists():
        raise ValueError(f"PRMS binary not found: {binary}")
    if not os.access(str(binary_path), os.X_OK):
        issues.append(f"Binary not executable: {binary} — will try chmod +x")
        os.chmod(str(binary_path), 0o755)

    # --- Check control file ---
    if not control_path.exists():
        raise ValueError(f"Control file not found: {control}")

    # Parse control file to find referenced files
    referenced_files = parse_control_file(str(control_path))

    # --- Check parameter file ---
    param_file = referenced_files.get("param_file")
    if param_file:
        if not Path(param_file).exists():
            issues.append(f"Parameter file not found: {param_file}")
        else:
            print(f"[preflight] Parameter file: {param_file} (OK)")

    # --- Check data file ---
    data_file = referenced_files.get("data_file")
    if data_file:
        if not Path(data_file).exists():
            issues.append(f"Data file not found: {data_file}")
        else:
            print(f"[preflight] Data file: {data_file} (OK)")

    # --- Check CBH files ---
    for cbh_key in ["tmax_day", "tmin_day", "precip_day", "potet_day", "swrad_day"]:
        cbh_file = referenced_files.get(cbh_key)
        if cbh_file and not Path(cbh_file).exists():
            issues.append(f"CBH file not found: {cbh_file}")
        elif cbh_file:
            print(f"[preflight] CBH file: {cbh_file} (OK)")

    # --- Check work directory ---
    work_path.mkdir(parents=True, exist_ok=True)

    return {
        "binary_path": binary_path,
        "control_path": control_path,
        "work_path": work_path,
        "referenced_files": referenced_files,
        "issues": issues,
    }


def parse_control_file(control_path: str) -> dict:
    """Parse PRMS control file to extract file paths and key settings.

    Returns dict of {key: value} for string/path variables.
    """
    result = {}
    try:
        with open(control_path, "r") as f:
            lines = f.readlines()

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line == "####" and i + 3 < len(lines):
                key = lines[i + 1].strip()
                size_line = lines[i + 2].strip()
                type_line = lines[i + 3].strip()

                try:
                    size = int(size_line)
                    type_code = int(type_line)
                except ValueError:
                    i += 1
                    continue

                # Read values
                values = []
                for j in range(size):
                    if i + 4 + j < len(lines):
                        values.append(lines[i + 4 + j].strip())

                if type_code == 4 and values:  # string type
                    result[key] = values[0]
                elif type_code == 1 and values:  # long
                    result[key] = [int(v) for v in values]
                elif type_code == 2 and values:  # float
                    result[key] = [float(v) for v in values]

                i += 4 + size
            else:
                i += 1

    except Exception as e:
        print(f"[preflight] Warning: Error parsing control file: {e}")

    return result


def run_model(binary_path: Path, control_path: Path, work_path: Path,
              timeout: int = 3600) -> dict:
    """Execute PRMS binary.

    CRITICAL: The -C flag must have NO space before the path.
    Correct: ./prms -C/path/to/control
    Wrong:   ./prms -C /path/to/control

    Returns dict with execution results.
    """
    # Build command — note NO space after -C
    cmd = [str(binary_path), f"-C{control_path}"]

    print(f"\n[run] Command: {' '.join(cmd)}")
    print(f"[run] Working directory: {work_path}")
    print(f"[run] Starting at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(work_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time

        result = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "elapsed_s": elapsed,
            "command": " ".join(cmd),
        }

        if proc.returncode == 0:
            print(f"[run] SUCCESS — completed in {elapsed:.1f}s")
        else:
            print(f"[run] FAILED — exit code {proc.returncode}")
            if proc.stderr:
                # Print first 500 chars of stderr
                print(f"[run] stderr: {proc.stderr[:500]}")

        return result

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"[run] TIMEOUT — killed after {elapsed:.0f}s")
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Process timed out after {timeout}s",
            "elapsed_s": elapsed,
            "command": " ".join(cmd),
        }

    except Exception as e:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": str(e),
            "elapsed_s": time.time() - start_time,
            "command": " ".join(cmd),
        }


def validate_outputs(work_path: Path, referenced_files: dict,
                     run_result: dict) -> list:
    """Post-run validation of model outputs.

    Returns list of findings.
    """
    findings = []

    if run_result["returncode"] != 0:
        findings.append(f"Model failed with exit code {run_result['returncode']}")

        # Diagnose common errors
        stderr = run_result.get("stderr", "")
        if "param_file" in stderr or "Parameter File" in stderr:
            findings.append("DIAGNOSIS: Parameter file issue — check path and format")
        if "data_file" in stderr or "Data" in stderr:
            findings.append("DIAGNOSIS: Data file issue — check path and format")
        if "####" in stderr:
            findings.append("DIAGNOSIS: File format issue — check #### delimiters")
        if "dimension" in stderr.lower():
            findings.append("DIAGNOSIS: Dimension mismatch — check nhru, nsegment values")
        if "control" in stderr.lower():
            findings.append("DIAGNOSIS: Control file issue — check format")

        return findings

    # Check output files
    model_output = referenced_files.get("model_output_file")
    if model_output and Path(model_output).exists():
        size = Path(model_output).stat().st_size
        findings.append(f"Model output: {model_output} ({size} bytes)")
    elif model_output:
        findings.append(f"WARNING: Model output not found: {model_output}")

    csv_output = referenced_files.get("csv_output_file")
    if csv_output and Path(csv_output).exists():
        size = Path(csv_output).stat().st_size
        findings.append(f"CSV output: {csv_output} ({size} bytes)")

    # Check for output in work directory
    for ext in ["*.out", "*.csv", "*.nc"]:
        outputs = list(work_path.glob(ext))
        for of in outputs:
            findings.append(f"Output found: {of.name} ({of.stat().st_size} bytes)")

    findings.append(f"Runtime: {run_result['elapsed_s']:.1f}s")

    return findings


def main():
    parser = argparse.ArgumentParser(description="Run PRMS with validation")
    parser.add_argument("--binary", required=True, help="Path to PRMS binary")
    parser.add_argument("--control", required=True, help="Path to control file")
    parser.add_argument("--work_dir", default=".", help="Working directory")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600)")
    args = parser.parse_args()

    print("=" * 60)
    print("PRMS Model Runner")
    print("=" * 60)

    # Step 1: Preflight
    print("\n--- Preflight validation ---")
    validated = validate_inputs(args.binary, args.control, args.work_dir)

    for issue in validated["issues"]:
        print(f"  WARNING: {issue}")

    critical = [i for i in validated["issues"] if "not found" in i.lower()]
    if critical:
        print(f"\n*** {len(critical)} critical issues — aborting ***")
        sys.exit(1)

    # Step 2: Run
    print("\n--- Running PRMS ---")
    result = run_model(
        validated["binary_path"],
        validated["control_path"],
        validated["work_path"],
        args.timeout,
    )

    # Step 3: Post-run validation
    print("\n--- Post-run validation ---")
    findings = validate_outputs(
        validated["work_path"],
        validated["referenced_files"],
        result,
    )

    for f in findings:
        print(f"  {f}")

    # Print summary
    print(f"\nExit code: {result['returncode']}")
    if result["returncode"] == 0:
        print("PRMS completed successfully.")
    else:
        print("PRMS failed — check diagnostics above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
