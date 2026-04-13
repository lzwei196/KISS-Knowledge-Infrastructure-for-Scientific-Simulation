#!/usr/bin/env python3
"""
run_geoclaw.py — Compile and execute a GeoClaw simulation with error checking.

Handles the full execution pipeline:
  1. Generate .data files from setrun.py
  2. Compile Fortran sources via Makefile (if needed)
  3. Run the xgeoclaw executable
  4. Verify output files were produced

CRITICAL REQUIREMENTS:
  - CLAW environment variable must be set to clawpack root
  - A Fortran compiler (gfortran) must be available
  - setrun.py must exist in the run directory
  - Topography files referenced in setrun.py must exist

Pattern: validate_inputs → process → validate_outputs
"""

import argparse
import json
import os
import subprocess
import sys
import time
import glob


def validate_inputs(args):
    """Phase 1: Validate environment and input files."""
    errors = []
    warnings = []

    # Check run directory
    if not os.path.isdir(args.run_dir):
        errors.append(f"Run directory not found: {args.run_dir}")

    # Check setrun.py
    setrun_path = os.path.join(args.run_dir, "setrun.py")
    if not os.path.isfile(setrun_path):
        errors.append(f"setrun.py not found in {args.run_dir}")

    # Check Makefile
    makefile_path = os.path.join(args.run_dir, "Makefile")
    if not os.path.isfile(makefile_path):
        if args.use_makefile:
            errors.append(f"Makefile not found in {args.run_dir} (required when --use-makefile)")
        else:
            warnings.append("No Makefile found — will attempt direct execution")

    # Check CLAW environment
    claw = os.environ.get("CLAW", "")
    if not claw:
        warnings.append(
            "CLAW environment variable not set. Will attempt to find clawpack via Python."
        )
    elif not os.path.isdir(claw):
        warnings.append(f"CLAW={claw} directory does not exist")

    # Check Fortran compiler
    if args.use_makefile:
        fc = os.environ.get("FC", "gfortran")
        try:
            subprocess.run([fc, "--version"], capture_output=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            errors.append(
                f"Fortran compiler '{fc}' not found. "
                "Install gfortran: sudo apt install gfortran"
            )

    # Check for existing output
    output_dir = os.path.join(args.run_dir, "_output")
    if os.path.isdir(output_dir) and not args.overwrite:
        existing_q = glob.glob(os.path.join(output_dir, "fort.q*"))
        if existing_q:
            warnings.append(
                f"Output directory already contains {len(existing_q)} fort.q files. "
                "Use --overwrite to replace."
            )

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return warnings


def process(args, input_warnings):
    """Phase 2: Compile and run GeoClaw."""
    warnings = list(input_warnings)
    run_dir = args.run_dir
    start_time = time.time()

    result = {
        "status": "running",
        "run_dir": run_dir,
        "warnings": warnings,
        "steps": [],
    }

    # Step 1: Generate .data files from setrun.py
    step_result = _run_setrun(run_dir, args.timeout)
    result["steps"].append(step_result)
    if step_result["status"] != "success":
        result["status"] = "error"
        result["error"] = "Failed to generate .data files from setrun.py"
        return result

    # Step 2: Compile (if using Makefile)
    if args.use_makefile:
        step_result = _compile(run_dir, args.timeout)
        result["steps"].append(step_result)
        if step_result["status"] != "success":
            result["status"] = "error"
            result["error"] = "Compilation failed"
            return result

    # Step 3: Run the executable
    step_result = _run_executable(run_dir, args.executable, args.timeout)
    result["steps"].append(step_result)
    if step_result["status"] != "success":
        result["status"] = "error"
        result["error"] = "Simulation failed"
        return result

    elapsed = time.time() - start_time
    result["status"] = "success"
    result["elapsed_seconds"] = round(elapsed, 2)
    result["warnings"] = warnings

    return result


def _run_setrun(run_dir, timeout):
    """Generate .data files by running setrun.py."""
    try:
        proc = subprocess.run(
            [sys.executable, "setrun.py"],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "step": "generate_data_files",
            "status": "success" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": proc.stdout[-500:] if proc.stdout else "",
            "stderr": proc.stderr[-500:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"step": "generate_data_files", "status": "error",
                "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"step": "generate_data_files", "status": "error", "error": str(e)}


def _compile(run_dir, timeout):
    """Compile Fortran sources using Makefile."""
    try:
        proc = subprocess.run(
            ["make", ".exe"],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "step": "compile",
            "status": "success" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": proc.stdout[-500:] if proc.stdout else "",
            "stderr": proc.stderr[-500:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"step": "compile", "status": "error",
                "error": f"Compilation timeout after {timeout}s"}
    except Exception as e:
        return {"step": "compile", "status": "error", "error": str(e)}


def _run_executable(run_dir, executable, timeout):
    """Run the GeoClaw executable."""
    output_dir = os.path.join(run_dir, "_output")
    os.makedirs(output_dir, exist_ok=True)

    # Find executable
    exe_path = None
    if executable:
        exe_path = executable
    else:
        # Look for common GeoClaw executable names
        candidates = ["xgeoclaw", "xgeo", "xclaw"]
        for cand in candidates:
            p = os.path.join(run_dir, cand)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                exe_path = p
                break

    if not exe_path or not os.path.isfile(exe_path):
        return {
            "step": "run_simulation",
            "status": "error",
            "error": f"Executable not found. Looked for: {exe_path or candidates}",
        }

    try:
        proc = subprocess.run(
            [exe_path],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "step": "run_simulation",
            "status": "success" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "executable": exe_path,
            "stdout_tail": proc.stdout[-1000:] if proc.stdout else "",
            "stderr_tail": proc.stderr[-1000:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "step": "run_simulation",
            "status": "error",
            "error": f"Simulation timeout after {timeout}s",
        }
    except Exception as e:
        return {"step": "run_simulation", "status": "error", "error": str(e)}


def validate_outputs(result):
    """Phase 3: Validate simulation outputs."""
    if result["status"] != "success":
        return result

    warnings = result.get("warnings", [])
    run_dir = result["run_dir"]
    output_dir = os.path.join(run_dir, "_output")

    # Check output directory exists
    if not os.path.isdir(output_dir):
        warnings.append("CRITICAL: _output directory was not created")
        result["warnings"] = warnings
        return result

    # Count output files
    q_files = sorted(glob.glob(os.path.join(output_dir, "fort.q*")))
    t_files = sorted(glob.glob(os.path.join(output_dir, "fort.t*")))
    a_files = sorted(glob.glob(os.path.join(output_dir, "fort.a*")))
    gauge_file = os.path.join(output_dir, "fort.gauge")

    result["output_files"] = {
        "fort_q": len(q_files),
        "fort_t": len(t_files),
        "fort_a": len(a_files),
        "gauge": os.path.isfile(gauge_file),
    }

    if len(q_files) == 0:
        warnings.append("CRITICAL: No fort.q files produced — simulation may have failed")
    elif len(q_files) == 1:
        warnings.append("WARNING: Only 1 fort.q file — only initial condition was written")

    # Check for NaN in last output
    if q_files:
        last_q = q_files[-1]
        try:
            with open(last_q, "r") as f:
                content = f.read(10000)
                if "nan" in content.lower() or "inf" in content.lower():
                    warnings.append(
                        "CRITICAL: NaN or Inf detected in final output. "
                        "Likely numerical instability — reduce CFL or increase resolution."
                    )
        except Exception:
            pass

    # Check total output size
    total_size = sum(
        os.path.getsize(f) for f in q_files + t_files + a_files
        if os.path.isfile(f)
    )
    result["total_output_size_mb"] = round(total_size / 1e6, 2)

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Compile and run a GeoClaw simulation"
    )
    parser.add_argument("--run-dir", required=True,
                        help="Directory containing setrun.py and Makefile")
    parser.add_argument("--use-makefile", action="store_true",
                        help="Use Makefile to compile (requires gfortran)")
    parser.add_argument("--executable", default=None,
                        help="Path to pre-compiled executable")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing output")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Max runtime in seconds (default: 3600)")
    parser.add_argument("--json-output", default=None,
                        help="Write result JSON to this file")

    args = parser.parse_args()

    # Phase 1: Validate inputs
    input_warnings = validate_inputs(args)

    # Phase 2: Process
    result = process(args, input_warnings)

    # Phase 3: Validate outputs
    result = validate_outputs(result)

    # Write JSON result
    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
