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
    "KISSPATH_BINARIES/parflow/install"
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
    # Absolute: the child runs with cwd=run_dir, so a relative script path
    # would be resolved twice (run_dir/run_dir/...).
    run_dir = os.path.abspath(run_dir)

    # Set environment. A generated Python run script carries its own
    # PARFLOW_DIR default (chosen and checked by s7 --parflow_dir); only
    # override it when the caller exported PARFLOW_DIR. tcl/direct need it.
    env = os.environ.copy()
    if method != "python" or "PARFLOW_DIR" in os.environ:
        pf_dir = os.environ.get("PARFLOW_DIR", PARFLOW_DIR)
        env["PARFLOW_DIR"] = pf_dir
        pf_bin_dir = os.path.join(pf_dir, "bin")
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

    # Snapshot existing outputs BEFORE launch. After the run, a file counts
    # only if it is new or changed (mtime_ns / size / inode) during this
    # invocation, so old outputs in a reused folder never make a success.
    out_patterns = {k: f"{run_name}.out.{k}.*.pfb" for k in ("press", "satur", "clm_output")}
    out_patterns["clm_var"] = f"{run_name}.out.qflx_evap_tot.*.pfb"

    def _sig(f):
        st = os.stat(f)
        return (st.st_mtime_ns, st.st_size, st.st_ino)

    before = {}
    for pat in out_patterns.values():
        for f in glob.glob(os.path.join(run_dir, pat)):
            before[f] = _sig(f)

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
    # Only files written by THIS invocation count (see snapshot above).
    def _fresh(pattern):
        found = sorted(glob.glob(os.path.join(run_dir, pattern)))
        fresh = [f for f in found if f not in before or _sig(f) != before[f]]
        return fresh, len(found) - len(fresh)
    press_files, stale_press = _fresh(out_patterns["press"])
    satur_files, _ = _fresh(out_patterns["satur"])
    clm_files, _ = _fresh(out_patterns["clm_output"])
    if not clm_files:
        # ParFlow 3.13 with PrintCLM writes one file per CLM variable
        # (<run>.out.qflx_evap_tot.NNNNN.pfb ...) instead of clm_output.*;
        # count those dumps (one per dump time) so CLM output is reported.
        clm_files, _ = _fresh(f"{run_name}.out.qflx_evap_tot.*.pfb")
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
            "old_pressure_files_ignored": stale_press,
        },
        "convergence": convergence_stats,
        "log_tail": log_tail,
    }

    if not success:
        result["message"] = (
            f"ParFlow exited with code {exit_code}. "
            f"New pressure files from this run: {len(press_files)} "
            f"(old ones ignored: {stale_press}). "
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
    # Honest exit code: a failed run must not look like success to a caller.
    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
