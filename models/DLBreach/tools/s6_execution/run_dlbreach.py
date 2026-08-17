#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
==========================================
Tool ID:      run_dlbreach
Stage:        s6_execution
Description:  Execute the DLBreach model binary, monitor progress, and
              capture output. DLBreach reads casename.txt from its working
              directory and produces casename.out.

              The binary prompts for the case name on stdin. This tool
              automates that interaction.

              Supports:
              - Native Linux binary (compiled from Fortran source)
              - Windows .exe via Wine

Inputs:
  --casename:       Case name (without .txt extension)
  --work_dir:       Working directory containing casename.txt
  --dlbreach_path:  Path to DLBreach binary (auto-detected if omitted)
  --timeout:        Maximum runtime in seconds (default 300)

Outputs:
  - JSON with output_file, exit_code, peak_breach_q, runtime_sec

Exit codes:
  0 -- success
  1 -- input file not found
  2 -- execution failed
  3 -- output file missing or empty
"""

import sys
import os
import json
import time
import shutil
import argparse
import logging
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path("KISSPATH_ROOT")
DEFAULT_BINARY_PATHS = [
    # Fortran binary (via wine on Linux) — validated against Wu 2016 (50 test cases)
    # Banqiao: peak Q = 71,783 m³/s (literature: ~78,000), breach width 302m
    # IMPORTANT: Do NOT use dlbreach.py (Python reimplementation) — it has simplified
    # erosion physics that produce ~10x lower peak Q than the Fortran original.
    PROJECT_ROOT / "model" / "dlbreach" / "bin" / "DLBreach_Barrier.exe",
    PROJECT_ROOT / "model" / "dlbreach" / "bin" / "DLBreach.exe",
]


def find_binary(user_path=None):
    """Locate DLBreach binary."""
    if user_path:
        p = Path(user_path)
        if p.exists():
            return str(p)
    for p in DEFAULT_BINARY_PATHS:
        if p.exists():
            return str(p)
    result = shutil.which("DLBreach") or shutil.which("dlbreach") or shutil.which("DLBreach.exe")
    return result


def parse_peak_discharge(output_file):
    """Parse the output file to find peak breach discharge."""
    max_q = 0.0
    max_q_time = 0.0
    n_lines = 0
    final_breach_width = 0.0
    final_breach_bottom = 0.0

    with open(output_file) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                continue
            parts = stripped.split()
            if len(parts) >= 13:
                try:
                    t = float(parts[0])
                    q = float(parts[1])
                    if q > max_q:
                        max_q = q
                        max_q_time = t
                    final_breach_width = float(parts[7])  # top width
                    final_breach_bottom = float(parts[5])  # bottom elevation
                    n_lines += 1
                except (ValueError, IndexError):
                    continue

    return {
        "peak_breach_q_m3s": round(max_q, 2),
        "peak_time_hr": round(max_q_time, 4),
        "final_breach_top_width_m": round(final_breach_width, 2),
        "final_breach_bottom_elev_m": round(final_breach_bottom, 2),
        "output_lines": n_lines,
    }


def main():
    parser = argparse.ArgumentParser(description="Run DLBreach model")
    parser.add_argument("--casename", type=str, required=True, help="Case name (no .txt)")
    parser.add_argument("--work_dir", type=str, required=True, help="Working directory")
    parser.add_argument("--dlbreach_path", type=str, help="Path to DLBreach binary")
    parser.add_argument("--timeout", type=int, default=300, help="Max runtime (seconds)")
    parser.add_argument("--output", type=str, help="Output JSON path")
    args = parser.parse_args()

    result = {
        "casename": args.casename,
        "output_file": None,
        "binary_path": None,
        "exit_code": None,
        "runtime_sec": None,
        "peak_results": None,
        "stdout": None,
        "stderr": None,
        "status": "error",
        "errors": [],
    }

    work_dir = Path(args.work_dir)
    input_file = work_dir / f"{args.casename}.txt"
    output_file = work_dir / f"{args.casename}.out"

    # Check input file exists
    if not input_file.exists():
        result["errors"].append(f"Input file not found: {input_file}")
        logger.error(f"Input file not found: {input_file}")
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Find binary
    binary_path = find_binary(args.dlbreach_path)
    if not binary_path:
        result["errors"].append("DLBreach binary not found")
        logger.error("DLBreach binary not found")
        print(json.dumps(result, indent=2))
        sys.exit(2)

    result["binary_path"] = binary_path

    # Determine execution method
    if binary_path.lower().endswith(".exe"):
        wine = shutil.which("wine")
        if wine:
            cmd = [wine, binary_path]
        else:
            result["errors"].append("Windows .exe found but Wine not installed")
            print(json.dumps(result, indent=2))
            sys.exit(2)
    else:
        if not os.access(binary_path, os.X_OK):
            os.chmod(binary_path, 0o755)
        cmd = [binary_path]

    # Copy binary to work_dir if not already there (DLBreach reads from CWD)
    binary_in_workdir = work_dir / Path(binary_path).name
    if not binary_in_workdir.exists():
        shutil.copy2(binary_path, binary_in_workdir)
        if not binary_path.lower().endswith(".exe"):
            os.chmod(str(binary_in_workdir), 0o755)

    # Remove old output if exists
    if output_file.exists():
        output_file.unlink()

    # Run DLBreach
    logger.info(f"Running DLBreach: {' '.join(cmd)} in {work_dir}")
    logger.info(f"Input: {input_file.name}, Expected output: {output_file.name}")

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            input=f"{args.casename}\n",
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        elapsed = time.time() - start_time
        result["exit_code"] = proc.returncode
        result["runtime_sec"] = round(elapsed, 2)
        result["stdout"] = proc.stdout[-2000:] if proc.stdout else ""
        result["stderr"] = proc.stderr[-2000:] if proc.stderr else ""

        logger.info(f"DLBreach finished in {elapsed:.1f}s, exit code: {proc.returncode}")

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        result["runtime_sec"] = round(elapsed, 2)
        result["errors"].append(f"Timed out after {args.timeout}s")
        logger.error(f"DLBreach timed out after {args.timeout}s")
        print(json.dumps(result, indent=2))
        sys.exit(2)
    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"Execution error: {e}")
        print(json.dumps(result, indent=2))
        sys.exit(2)

    # Check output
    if output_file.exists() and output_file.stat().st_size > 0:
        result["output_file"] = str(output_file)
        result["peak_results"] = parse_peak_discharge(str(output_file))
        result["status"] = "success"
        logger.info(f"Output: {output_file} ({output_file.stat().st_size} bytes)")
        logger.info(f"Peak breach Q: {result['peak_results']['peak_breach_q_m3s']} m3/s "
                     f"at t={result['peak_results']['peak_time_hr']} hr")
    else:
        result["errors"].append("Output file not generated or empty")
        result["status"] = "no_output"
        logger.error("Output file not generated")
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        sys.exit(3)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2))

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
