#!/usr/bin/env python3
"""run_daisy.py — Execution wrapper for the Daisy model.

Locates the Daisy binary, validates input files, runs the simulation,
and captures output/errors. Supports timeout protection and log parsing.

Usage:
    python run_daisy.py \\
        --dai-file test.dai \\
        --work-dir /tmp/daisy-run \\
        --binary /path/to/daisy \\
        --timeout 600
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(dai_file, work_dir, binary_path):
    """Validate that all required inputs exist before running.

    Returns
    -------
    dict
        Validated paths and metadata.
    """
    errors = []

    # Check binary
    if not os.path.isfile(binary_path):
        errors.append(f"Daisy binary not found: {binary_path}")
    elif not os.access(binary_path, os.X_OK):
        errors.append(f"Daisy binary not executable: {binary_path}")

    # Check .dai file
    if not os.path.isfile(dai_file):
        errors.append(f"Setup file not found: {dai_file}")

    # Check work directory
    if not os.path.isdir(work_dir):
        try:
            os.makedirs(work_dir, exist_ok=True)
        except OSError as e:
            errors.append(f"Cannot create work directory: {work_dir} ({e})")

    if errors:
        raise FileNotFoundError("Input validation failed:\n  " + "\n  ".join(errors))

    # Parse .dai file to find referenced files
    referenced_files = []
    if os.path.isfile(dai_file):
        with open(dai_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("(input file"):
                    # Extract filename from (input file "xxx.dai")
                    parts = line.split('"')
                    if len(parts) >= 2:
                        referenced_files.append(parts[1])
                elif line.startswith("(weather"):
                    parts = line.split('"')
                    if len(parts) >= 2:
                        referenced_files.append(parts[1])

    # Check referenced files (warnings only — they may be in lib/)
    for ref in referenced_files:
        ref_path = os.path.join(work_dir, ref)
        if not os.path.isfile(ref_path):
            print(f"NOTE: Referenced file '{ref}' not in work dir (may be in Daisy lib/)")

    return {
        "binary": binary_path,
        "dai_file": dai_file,
        "work_dir": work_dir,
        "referenced_files": referenced_files,
    }


def validate_outputs(work_dir, expected_outputs=None):
    """Validate simulation outputs after run.

    Returns
    -------
    dict
        Found output files and their sizes.
    """
    outputs = {}
    warnings = []

    # Find all .dlf files
    dlf_files = list(Path(work_dir).glob("*.dlf"))
    for dlf in dlf_files:
        size = dlf.stat().st_size
        outputs[dlf.name] = {
            "path": str(dlf),
            "size_bytes": size,
        }
        if size == 0:
            warnings.append(f"Empty output file: {dlf.name}")

    # Check daisy.log
    log_file = os.path.join(work_dir, "daisy.log")
    if os.path.isfile(log_file):
        outputs["daisy.log"] = {
            "path": log_file,
            "size_bytes": os.path.getsize(log_file),
        }
    else:
        warnings.append("daisy.log not found")

    # Check for checkpoint
    checkpoints = list(Path(work_dir).glob("checkpoint-*.dai"))
    if checkpoints:
        outputs["checkpoint"] = {
            "path": str(checkpoints[0]),
            "count": len(checkpoints),
        }

    if not dlf_files:
        warnings.append("No .dlf output files found — simulation may have failed")

    for w in warnings:
        print(f"WARNING: {w}")

    return outputs


# ---------------------------------------------------------------------------
# Binary locator
# ---------------------------------------------------------------------------

def find_daisy_binary(explicit_path=None, source_dir=None):
    """Locate the Daisy binary.

    Search order:
    1. Explicit path (--binary flag)
    2. Build directory within source
    3. System PATH
    """
    candidates = []

    if explicit_path:
        candidates.append(explicit_path)

    if source_dir:
        # Check common build locations
        for build_dir in [
            "build/linux-gcc-portable",
            "build/linux-gcc-native",
            "build/linux-clang-native",
            "build",
        ]:
            candidates.append(os.path.join(source_dir, build_dir, "daisy"))

    # Check system PATH
    system_daisy = shutil.which("daisy")
    if system_daisy:
        candidates.append(system_daisy)

    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    return None


# ---------------------------------------------------------------------------
# Log parser
# ---------------------------------------------------------------------------

def parse_daisy_log(log_path):
    """Parse daisy.log for errors and warnings.

    Returns
    -------
    dict
        Parsed log with errors, warnings, and summary.
    """
    result = {
        "errors": [],
        "warnings": [],
        "simulation_time": None,
        "success": False,
    }

    if not os.path.isfile(log_path):
        result["errors"].append("daisy.log not found")
        return result

    with open(log_path) as f:
        lines = f.readlines()

    for line in lines:
        line_lower = line.lower().strip()
        if "error" in line_lower:
            result["errors"].append(line.strip())
        elif "warning" in line_lower:
            result["warnings"].append(line.strip())
        elif "simulation" in line_lower and "done" in line_lower:
            result["success"] = True
        elif "done" == line_lower or "simulation ended" in line_lower:
            result["success"] = True

    return result


# ---------------------------------------------------------------------------
# Main execution pipeline
# ---------------------------------------------------------------------------

def process(dai_file, work_dir, binary_path, timeout=600, source_dir=None):
    """Run a Daisy simulation.

    Parameters
    ----------
    dai_file : str
        Path to the main .dai setup file.
    work_dir : str
        Working directory for the simulation run.
    binary_path : str or None
        Path to Daisy binary, or None to auto-detect.
    timeout : int
        Timeout in seconds.
    source_dir : str or None
        Path to Daisy source for binary search.

    Returns
    -------
    dict
        Run result with exit code, outputs, log parse, and timing.
    """
    # Step 1: Find binary
    binary = find_daisy_binary(binary_path, source_dir)
    if binary is None:
        raise FileNotFoundError(
            "Cannot find Daisy binary. Specify --binary or build from source first.")

    print(f"Using binary: {binary}")

    # Step 2: Validate inputs
    validated = validate_inputs(dai_file, work_dir, binary)

    # Step 3: Prepare working directory
    dai_basename = os.path.basename(dai_file)
    work_dai = os.path.join(work_dir, dai_basename)

    # Copy .dai file to work dir if not already there
    if os.path.abspath(dai_file) != os.path.abspath(work_dai):
        shutil.copy2(dai_file, work_dai)

    # Step 4: Run simulation
    cmd = [binary, dai_basename]
    print(f"Running: {' '.join(cmd)} in {work_dir}")

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        elapsed = timeout
        exit_code = -1
        stdout = ""
        stderr = f"Simulation timed out after {timeout} seconds"
    except Exception as e:
        elapsed = time.time() - start_time
        exit_code = -2
        stdout = ""
        stderr = str(e)

    print(f"Exit code: {exit_code}, elapsed: {elapsed:.1f}s")

    if stdout:
        print(f"STDOUT (first 500 chars):\n{stdout[:500]}")
    if stderr:
        print(f"STDERR (first 500 chars):\n{stderr[:500]}")

    # Step 5: Parse log
    log_path = os.path.join(work_dir, "daisy.log")
    log_parse = parse_daisy_log(log_path)

    # Step 6: Validate outputs
    outputs = validate_outputs(work_dir)

    run_result = {
        "binary": binary,
        "dai_file": dai_file,
        "work_dir": work_dir,
        "exit_code": exit_code,
        "elapsed_seconds": elapsed,
        "stdout": stdout[:2000],
        "stderr": stderr[:2000],
        "log": log_parse,
        "outputs": outputs,
    }

    # Summary
    n_dlf = len([k for k in outputs if k.endswith(".dlf")])
    if exit_code == 0 and n_dlf > 0:
        print(f"SUCCESS: {n_dlf} .dlf output files generated in {elapsed:.1f}s")
    elif exit_code == 0:
        print(f"Completed with exit code 0 but no .dlf files found")
    else:
        print(f"FAILED with exit code {exit_code}")
        if log_parse["errors"]:
            print(f"  Errors: {log_parse['errors'][:3]}")

    return run_result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run a Daisy simulation with validation and log parsing")
    parser.add_argument("--dai-file", required=True,
                        help="Path to main .dai setup file")
    parser.add_argument("--work-dir", default=".",
                        help="Working directory for simulation")
    parser.add_argument("--binary", default=None,
                        help="Path to Daisy binary (auto-detected if not given)")
    parser.add_argument("--source-dir", default=None,
                        help="Path to Daisy source tree (for binary search)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Timeout in seconds (default: 600)")
    parser.add_argument("--output-json", default=None,
                        help="Write run result to JSON file")

    args = parser.parse_args()

    result = process(
        dai_file=args.dai_file,
        work_dir=args.work_dir,
        binary_path=args.binary,
        timeout=args.timeout,
        source_dir=args.source_dir,
    )

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Result written to {args.output_json}")


if __name__ == "__main__":
    main()
