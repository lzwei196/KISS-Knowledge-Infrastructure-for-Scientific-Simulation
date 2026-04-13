#!/usr/bin/env python3
"""
Execute ParFlow simulation with MPI, error handling, and output validation.

ParFlow can be run in three ways:
1. Python pftools API: python run_script.py
2. TCL script: tclsh run_script.tcl
3. Direct: mpirun -np N parflow run_name

This tool handles process monitoring, exit code checking, and output validation.

Usage:
    python run_parflow.py \
        --run_dir outputs/parflow_run/run/ \
        --run_name chaohe_test \
        --nprocs 4

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import subprocess
import sys
import time
import glob


PARFLOW_DIR = os.environ.get(
    "PARFLOW_DIR",
    "/mnt/disk1/Hydrocraft_server/model/parflow/install"
)
PARFLOW_BIN = os.path.join(PARFLOW_DIR, "bin", "parflow")


def validate_inputs(run_dir, run_name):
    errors = []
    if not os.path.isdir(run_dir):
        errors.append(f"Run directory not found: {run_dir}")
    # Check for run script
    py_script = os.path.join(run_dir, f"run_{run_name}.py")
    tcl_script = os.path.join(run_dir, f"{run_name}.tcl")
    if not os.path.exists(py_script) and not os.path.exists(tcl_script):
        errors.append(f"No run script found: {py_script} or {tcl_script}")
    return errors


def process(run_dir, run_name, nprocs=1, method="python", timeout_hours=48):
    """
    Execute ParFlow and monitor the run.

    Parameters
    ----------
    run_dir : str
        Directory containing run script and input files.
    run_name : str
        ParFlow run name (base name for input/output files).
    nprocs : int
        Number of MPI processes.
    method : str
        'python' (pftools), 'tcl', or 'direct' (parflow binary).
    timeout_hours : float
        Maximum runtime before killing the process.
    """
    start_time = time.time()

    # Set environment
    env = os.environ.copy()
    env["PARFLOW_DIR"] = PARFLOW_DIR
    pf_bin_dir = os.path.join(PARFLOW_DIR, "bin")
    if pf_bin_dir not in env.get("PATH", ""):
        env["PATH"] = pf_bin_dir + ":" + env.get("PATH", "")

    # Determine command
    if method == "python":
        py_script = os.path.join(run_dir, f"run_{run_name}.py")
        cmd = [sys.executable, py_script]
    elif method == "tcl":
        tcl_script = os.path.join(run_dir, f"{run_name}.tcl")
        cmd = ["tclsh", tcl_script]
    else:
        # Direct MPI execution
        if nprocs > 1:
            mpirun = os.environ.get("MPIRUN", "mpirun")
            cmd = [mpirun, "-np", str(nprocs), PARFLOW_BIN, run_name]
        else:
            cmd = [PARFLOW_BIN, run_name]

    # Log file
    log_file = os.path.join(run_dir, f"{run_name}.run.log")

    print(f"Starting ParFlow: {' '.join(cmd)}")
    print(f"Working directory: {run_dir}")
    print(f"Log file: {log_file}")

    try:
        with open(log_file, "w") as log_f:
            proc = subprocess.Popen(
                cmd,
                cwd=run_dir,
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
            )

            # Wait for completion
            timeout_sec = int(timeout_hours * 3600)
            proc.wait(timeout=timeout_sec)
            exit_code = proc.returncode

    except subprocess.TimeoutExpired:
        proc.kill()
        elapsed = time.time() - start_time
        return {
            "status": "error",
            "message": f"ParFlow timed out after {elapsed/3600:.1f} hours",
            "log_file": log_file,
        }
    except FileNotFoundError as e:
        return {
            "status": "error",
            "message": f"Command not found: {e}",
            "log_file": log_file,
        }

    elapsed = time.time() - start_time

    # Check outputs
    press_files = sorted(glob.glob(os.path.join(run_dir, f"{run_name}.out.press.*.pfb")))
    satur_files = sorted(glob.glob(os.path.join(run_dir, f"{run_name}.out.satur.*.pfb")))
    clm_files = sorted(glob.glob(os.path.join(run_dir, f"{run_name}.out.clm_output.*.pfb")))
    kinsol_log = os.path.join(run_dir, f"{run_name}.out.kinsol.log")

    # Parse kinsol.log for convergence stats
    convergence_stats = None
    if os.path.exists(kinsol_log):
        try:
            with open(kinsol_log) as f:
                lines = f.readlines()
            total_iters = 0
            max_iters = 0
            timestep_count = 0
            for line in lines:
                if "KINSol" in line and "nni" in line:
                    # Parse iteration count
                    parts = line.strip().split()
                    for j, p in enumerate(parts):
                        if p == "nni" and j + 1 < len(parts):
                            try:
                                iters = int(parts[j + 1].rstrip(","))
                                total_iters += iters
                                max_iters = max(max_iters, iters)
                                timestep_count += 1
                            except ValueError:
                                pass
            if timestep_count > 0:
                convergence_stats = {
                    "total_nonlinear_iterations": total_iters,
                    "mean_iterations_per_step": round(total_iters / timestep_count, 1),
                    "max_iterations_per_step": max_iters,
                    "total_timesteps": timestep_count,
                }
        except Exception:
            pass

    # Read last 20 lines of log
    log_tail = ""
    try:
        with open(log_file) as f:
            lines = f.readlines()
            log_tail = "".join(lines[-20:])
    except Exception:
        pass

    success = exit_code == 0 and len(press_files) > 0

    result = {
        "status": "success" if success else "error",
        "exit_code": exit_code,
        "runtime_seconds": round(elapsed, 1),
        "runtime_minutes": round(elapsed / 60, 1),
        "log_file": log_file,
        "kinsol_log": kinsol_log if os.path.exists(kinsol_log) else None,
        "output_files": {
            "pressure": len(press_files),
            "saturation": len(satur_files),
            "clm_output": len(clm_files),
        },
        "convergence": convergence_stats,
        "log_tail": log_tail,
    }

    if not success:
        result["message"] = (
            f"ParFlow exited with code {exit_code}. "
            f"Pressure files: {len(press_files)}. "
            f"Check {log_file} for details."
        )

    return result


def main():
    parser = argparse.ArgumentParser(description="Run ParFlow simulation")
    parser.add_argument("--run_dir", required=True)
    parser.add_argument("--run_name", required=True)
    parser.add_argument("--nprocs", type=int, default=1)
    parser.add_argument("--method", choices=["python", "tcl", "direct"],
                        default="python")
    parser.add_argument("--timeout_hours", type=float, default=48)
    args = parser.parse_args()

    errs = validate_inputs(args.run_dir, args.run_name)
    if errs:
        print(json.dumps({"status": "error", "errors": errs}))
        sys.exit(1)

    result = process(args.run_dir, args.run_name, args.nprocs,
                     args.method, args.timeout_hours)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
