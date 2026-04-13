#!/usr/bin/env python3
"""
run_geotop.py - Execute the GEOtop model binary with monitoring and logging.

Wraps the GEOtop binary invocation with:
  - Pre-run validation of input directory structure
  - Timeout management
  - Log file monitoring
  - Exit code interpretation
  - Success/failure detection via marker files

Usage:
    python run_geotop.py \\
        --binary /path/to/build/geotop \\
        --sim-dir /path/to/simulation/folder \\
        --timeout 3600

    python run_geotop.py \\
        --binary /path/to/build/geotop \\
        --sim-dir /path/to/simulation/folder \\
        --timeout 7200 \\
        --log-tail 100
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def validate_inputs(args):
    """Validate binary and simulation directory before execution."""
    errors = []

    # Check binary exists and is executable
    if not os.path.isfile(args.binary):
        errors.append(f"Binary not found: {args.binary}")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"Binary not executable: {args.binary}. Run: chmod +x {args.binary}")

    sim_dir = Path(args.sim_dir)

    # Check simulation directory exists
    if not sim_dir.is_dir():
        errors.append(f"Simulation directory not found: {args.sim_dir}")
    else:
        # Check geotop.inpts exists
        inpts = sim_dir / "geotop.inpts"
        if not inpts.is_file():
            errors.append(f"Configuration file not found: {inpts}")

        # Check meteo directory and files
        meteo_dir = sim_dir / "meteo"
        if meteo_dir.is_dir():
            meteo_files = list(meteo_dir.glob("meteo*.txt"))
            if len(meteo_files) == 0:
                errors.append(f"No meteoXXXX.txt files in {meteo_dir}")
        else:
            # Check if MeteoFile path in inpts points elsewhere
            pass  # May be configured differently

        # Check soil directory and files
        soil_dir = sim_dir / "soil"
        if soil_dir.is_dir():
            soil_files = list(soil_dir.glob("soil*.txt"))
            if len(soil_files) == 0:
                errors.append(f"No soilXXXX.txt files in {soil_dir}")

    if args.timeout <= 0:
        errors.append(f"Timeout must be positive: {args.timeout}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def check_previous_run(sim_dir):
    """Check for artifacts from a previous run."""
    warnings = []
    sim_path = Path(sim_dir)

    # Check for success marker from previous run
    success_marker = sim_path / "_SUCCESSFUL_RUN"
    if success_marker.exists():
        warnings.append("Previous successful run detected. Output files may be overwritten.")

    # Check for recovery files
    rec_dir = sim_path / "rec"
    if rec_dir.is_dir():
        warnings.append("Recovery directory found. Set RecoverSim=1 in geotop.inpts to resume.")

    # Check for existing output
    output_dir = sim_path / "output-tabs"
    if output_dir.is_dir() and any(output_dir.iterdir()):
        warnings.append("Existing output files will be overwritten.")

    return warnings


def process(args):
    """Execute GEOtop and monitor the run."""
    sim_dir = Path(args.sim_dir)
    log_file = sim_dir / "geotop.log"

    # Clean up old success marker
    success_marker = sim_dir / "_SUCCESSFUL_RUN"
    if success_marker.exists():
        success_marker.unlink()

    # Build command
    cmd = [os.path.abspath(args.binary), os.path.abspath(args.sim_dir)]

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    print(f"Timeout: {args.timeout}s", file=sys.stderr)

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            cwd=os.path.dirname(args.binary),
        )
        elapsed = time.time() - start_time
        exit_code = result.returncode

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            "status": "timeout",
            "elapsed_s": elapsed,
            "timeout_s": args.timeout,
            "message": f"GEOtop exceeded timeout of {args.timeout}s",
        }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "status": "error",
            "elapsed_s": elapsed,
            "message": str(e),
        }

    # Read log file
    log_content = ""
    if log_file.is_file():
        with open(log_file) as f:
            log_content = f.read()

    # Check for success
    success = success_marker.exists()

    # Parse stdout/stderr
    stdout_tail = result.stdout[-2000:] if result.stdout else ""
    stderr_tail = result.stderr[-2000:] if result.stderr else ""
    log_tail = log_content[-args.log_tail * 80:] if log_content else ""

    # Detect common errors in log
    error_hints = []
    if "ERROR" in log_content.upper():
        for line in log_content.split("\n"):
            if "error" in line.lower() or "ERROR" in line:
                error_hints.append(line.strip())
    if exit_code == 9:
        error_hints.append("Exit code 9: Wrong number of arguments")
    if "NaN" in log_content or "nan" in log_content:
        error_hints.append("NaN detected in log - possible numerical instability")
    if "Richards" in log_content and ("not converging" in log_content.lower() or "diverge" in log_content.lower()):
        error_hints.append("Richards equation solver divergence - check soil parameters")

    # List output files
    output_files = []
    output_dir = sim_dir / "output-tabs"
    if output_dir.is_dir():
        output_files = [str(f.relative_to(sim_dir)) for f in sorted(output_dir.iterdir())]

    return {
        "status": "success" if success else ("completed" if exit_code == 0 else "failed"),
        "exit_code": exit_code,
        "elapsed_s": round(elapsed, 2),
        "success_marker": success,
        "log_file": str(log_file),
        "log_tail": log_tail,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "error_hints": error_hints[:10],
        "output_files": output_files,
    }


def validate_outputs(result, sim_dir):
    """Validate model outputs after execution."""
    warnings = []
    sim_path = Path(sim_dir)

    if result["status"] not in ("success", "completed"):
        warnings.append(f"Run did not succeed: status={result['status']}")
        print(json.dumps({"status": "error", "run_result": result, "warnings": warnings},
                          indent=2), file=sys.stderr)
        return

    # Check output files exist and have content
    output_dir = sim_path / "output-tabs"
    if output_dir.is_dir():
        for f in output_dir.iterdir():
            if f.stat().st_size == 0:
                warnings.append(f"Empty output file: {f.name}")
            elif f.suffix == ".txt":
                with open(f) as fh:
                    lines = fh.readlines()
                if len(lines) <= 1:
                    warnings.append(f"Output file has only header, no data: {f.name}")

    # Check basin.txt for mass balance errors
    basin_file = output_dir / "basin0001.txt" if output_dir.is_dir() else None
    if basin_file and basin_file.is_file():
        try:
            import pandas as pd
            df = pd.read_csv(basin_file)
            mbe_cols = [c for c in df.columns if "mass_balance" in c.lower() or "Mass_balance" in c]
            if mbe_cols:
                max_mbe = df[mbe_cols[0]].abs().max()
                if max_mbe > 1.0:
                    warnings.append(f"Mass balance error max = {max_mbe:.2f} mm. Check numerical settings.")
        except Exception:
            pass

    result["warnings"] = warnings
    print(json.dumps(result, indent=2), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Execute GEOtop model binary")
    parser.add_argument("--binary", required=True, help="Path to geotop executable")
    parser.add_argument("--sim-dir", required=True, help="Path to simulation folder")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds (default: 3600)")
    parser.add_argument("--log-tail", type=int, default=50, help="Number of log lines to capture at end")

    args = parser.parse_args()
    validate_inputs(args)

    pre_warnings = check_previous_run(args.sim_dir)
    if pre_warnings:
        print(json.dumps({"pre_run_warnings": pre_warnings}), file=sys.stderr)

    result = process(args)
    validate_outputs(result, args.sim_dir)

    # Print summary
    print(f"Status: {result['status']}")
    print(f"Elapsed: {result.get('elapsed_s', 0):.1f}s")
    if result.get("output_files"):
        print(f"Output files: {len(result['output_files'])}")
    if result.get("error_hints"):
        print("Errors:")
        for hint in result["error_hints"]:
            print(f"  - {hint}")


if __name__ == "__main__":
    main()
