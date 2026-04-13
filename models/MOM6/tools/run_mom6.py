#!/usr/bin/env python3
"""
run_mom6.py — MOM6 execution wrapper with preflight checks and output validation.

Validates configuration files, runs the MOM6 binary via MPI, monitors ocean.stats
for blowups, and reports run status.

Pipeline stage: S6 (Model Execution)
Pattern: validate → process → validate
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Required files for a MOM6 run
REQUIRED_FILES = ["MOM_input", "input.nml", "diag_table"]
REQUIRED_DIRS = ["INPUT"]
OPTIONAL_FILES = ["MOM_override"]

# Physical sanity checks for ocean.stats
ENERGY_BLOWUP_THRESHOLD = 1e10   # J/kg — unrealistically high energy
CFL_WARNING_THRESHOLD = 0.8      # CFL > 0.8 is dangerous
CFL_BLOWUP_THRESHOLD = 1.0      # CFL > 1.0 = unstable


def validate_preflight(run_dir: str, binary: str, nprocs: int) -> dict:
    """Pre-validate: check binary, config files, and input data exist."""
    run_dir = Path(run_dir)
    report = {"valid": True, "warnings": [], "errors": []}

    # Check binary
    if not os.path.isfile(binary):
        report["errors"].append(f"MOM6 binary not found: {binary}")
        report["valid"] = False
    elif not os.access(binary, os.X_OK):
        report["errors"].append(f"MOM6 binary not executable: {binary}")
        report["valid"] = False

    # Check required files
    for fname in REQUIRED_FILES:
        fpath = run_dir / fname
        if not fpath.is_file():
            report["errors"].append(f"Missing required file: {fpath}")
            report["valid"] = False

    # Check required directories
    for dname in REQUIRED_DIRS:
        dpath = run_dir / dname
        if not dpath.is_dir():
            report["errors"].append(f"Missing required directory: {dpath}")
            report["valid"] = False
        else:
            # Check INPUT has at least some files
            input_files = list(dpath.iterdir())
            if not input_files:
                report["warnings"].append(f"{dpath} is empty — no grid/topo files")

    # Check MPI availability
    mpirun = _find_mpirun()
    if mpirun is None and nprocs > 1:
        report["errors"].append("mpirun/mpiexec not found — cannot run parallel")
        report["valid"] = False

    # Parse MOM_input for basic sanity
    mom_input = run_dir / "MOM_input"
    if mom_input.is_file():
        params = _parse_mom_input(mom_input)
        dt = params.get("DT")
        if dt and float(dt) <= 0:
            report["errors"].append(f"DT = {dt} is invalid (must be > 0)")
            report["valid"] = False
        if dt and float(dt) < 1:
            report["warnings"].append(f"DT = {dt} is very small — long run time")

        nk = params.get("NK")
        if nk and int(nk) <= 0:
            report["errors"].append(f"NK = {nk} is invalid (must be > 0)")
            report["valid"] = False

    # Parse input.nml for run length
    nml_path = run_dir / "input.nml"
    if nml_path.is_file():
        nml = _parse_input_nml(nml_path)
        if nml.get("input_filename") == "r":
            # Restart mode — check RESTART files
            restart_dir = run_dir / "INPUT"
            res_files = list(restart_dir.glob("MOM.res*.nc"))
            if not res_files:
                report["errors"].append("input_filename='r' but no MOM.res*.nc in INPUT/")
                report["valid"] = False

    for e in report["errors"]:
        log.error(e)
    for w in report["warnings"]:
        log.warning(w)

    if report["valid"]:
        log.info("Preflight checks PASSED")

    return report


def _find_mpirun() -> str:
    """Find MPI launcher command."""
    for cmd in ["mpirun", "mpiexec", "srun"]:
        try:
            result = subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _parse_mom_input(path: Path) -> dict:
    """Parse MOM_input file for key=value parameters."""
    params = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("!") or line.startswith("#"):
                continue
            # Remove inline comments
            if "!" in line:
                line = line[:line.index("!")]
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                params[key] = val
    return params


def _parse_input_nml(path: Path) -> dict:
    """Extract key settings from input.nml."""
    result = {}
    with open(path) as f:
        content = f.read()

    # Extract input_filename
    m = re.search(r"input_filename\s*=\s*['\"](\w+)['\"]", content)
    if m:
        result["input_filename"] = m.group(1)

    # Extract days/months
    m = re.search(r"days\s*=\s*(\d+)", content)
    if m:
        result["days"] = int(m.group(1))

    m = re.search(r"months\s*=\s*(\d+)", content)
    if m:
        result["months"] = int(m.group(1))

    return result


def run_model(run_dir: str, binary: str, nprocs: int,
              timeout: int = 86400, log_file: str = "mom6_run.log") -> dict:
    """Execute MOM6 binary via MPI."""
    run_dir = Path(run_dir)
    binary = os.path.abspath(binary)

    mpirun = _find_mpirun()
    if nprocs > 1 and mpirun:
        cmd = [mpirun, "-np", str(nprocs), binary]
    else:
        cmd = [binary]

    log.info(f"Command: {' '.join(cmd)}")
    log.info(f"Working directory: {run_dir}")

    log_path = run_dir / log_file
    start_time = time.time()

    try:
        with open(log_path, "w") as lf:
            proc = subprocess.run(
                cmd,
                cwd=str(run_dir),
                stdout=lf,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        elapsed = time.time() - start_time
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        log.error(f"MOM6 timed out after {timeout} seconds")
        returncode = -1
    except Exception as e:
        elapsed = time.time() - start_time
        log.error(f"MOM6 execution failed: {e}")
        returncode = -2

    result = {
        "command": " ".join(cmd),
        "returncode": returncode,
        "elapsed_seconds": round(elapsed, 1),
        "log_file": str(log_path),
        "success": returncode == 0,
    }

    if returncode == 0:
        log.info(f"MOM6 completed successfully in {elapsed:.1f}s")
    else:
        log.error(f"MOM6 failed with return code {returncode}")
        # Print tail of log
        if log_path.is_file():
            with open(log_path) as f:
                lines = f.readlines()
            tail = lines[-20:] if len(lines) > 20 else lines
            log.error("Last lines of log:\n" + "".join(tail))

    return result


def validate_output(run_dir: str) -> dict:
    """Post-validate: check ocean.stats and output files."""
    run_dir = Path(run_dir)
    report = {"valid": True, "warnings": [], "stats": {}}

    # Check ocean.stats
    stats_file = run_dir / "ocean.stats"
    if not stats_file.is_file():
        report["warnings"].append("ocean.stats not found — cannot verify run")
        report["valid"] = False
        return report

    with open(stats_file) as f:
        lines = f.readlines()

    if len(lines) < 2:
        report["warnings"].append("ocean.stats has < 2 lines — run may have failed immediately")
        report["valid"] = False
        return report

    # Parse last line for energy and CFL
    last_line = lines[-1].strip()
    report["stats"]["last_line"] = last_line
    report["stats"]["n_timesteps"] = len(lines) - 1  # header line

    # Try to extract energy
    en_match = re.search(r"En\s+([\d.Ee+-]+)", last_line)
    if en_match:
        energy = float(en_match.group(1))
        report["stats"]["final_energy"] = energy
        if energy > ENERGY_BLOWUP_THRESHOLD:
            report["warnings"].append(
                f"Energy blowup detected: {energy:.3e} > {ENERGY_BLOWUP_THRESHOLD}"
            )
            report["valid"] = False

    # Try to extract CFL
    cfl_match = re.search(r"CFL\s+([\d.Ee+-]+)", last_line)
    if cfl_match:
        cfl = float(cfl_match.group(1))
        report["stats"]["max_cfl"] = cfl
        if cfl > CFL_BLOWUP_THRESHOLD:
            report["warnings"].append(f"CFL > 1.0 ({cfl:.3f}) — numerically unstable")
            report["valid"] = False
        elif cfl > CFL_WARNING_THRESHOLD:
            report["warnings"].append(f"CFL = {cfl:.3f} — approaching instability")

    # Check for truncation events
    trunc_match = re.search(r"Truncs\s+(\d+)", last_line)
    if trunc_match:
        truncs = int(trunc_match.group(1))
        report["stats"]["truncations"] = truncs
        if truncs > 0:
            report["warnings"].append(f"{truncs} velocity truncation events occurred")

    # Check restart files
    restart_dir = run_dir / "RESTART"
    if restart_dir.is_dir():
        restart_files = list(restart_dir.glob("*.nc"))
        report["stats"]["restart_files"] = len(restart_files)
    else:
        report["warnings"].append("RESTART/ directory not found")

    # Check diagnostic output files
    diag_files = list(run_dir.glob("*.nc"))
    report["stats"]["diagnostic_files"] = len(diag_files)

    for w in report["warnings"]:
        log.warning(w)

    if report["valid"]:
        log.info("Output validation PASSED")

    return report


def main():
    parser = argparse.ArgumentParser(description="MOM6 execution wrapper")
    parser.add_argument("--run-dir", default=".", help="Run directory (default: .)")
    parser.add_argument("--binary", default="./MOM6", help="MOM6 binary path")
    parser.add_argument("-n", "--nprocs", type=int, default=1,
                        help="Number of MPI processes (default: 1)")
    parser.add_argument("--timeout", type=int, default=86400,
                        help="Timeout in seconds (default: 86400)")
    parser.add_argument("--skip-run", action="store_true",
                        help="Skip execution, only validate existing output")
    parser.add_argument("--json-report", default=None,
                        help="Write run report to JSON")
    args = parser.parse_args()

    full_report = {}

    # Step 1: Preflight
    if not args.skip_run:
        log.info("=== Step 1: Preflight validation ===")
        preflight = validate_preflight(args.run_dir, args.binary, args.nprocs)
        full_report["preflight"] = preflight
        if not preflight["valid"]:
            log.error("Preflight failed — aborting")
            if args.json_report:
                with open(args.json_report, "w") as f:
                    json.dump(full_report, f, indent=2)
            sys.exit(1)

        # Step 2: Run
        log.info("=== Step 2: Executing MOM6 ===")
        run_result = run_model(args.run_dir, args.binary, args.nprocs, args.timeout)
        full_report["execution"] = run_result

        if not run_result["success"]:
            log.error("MOM6 run failed")

    # Step 3: Validate output
    log.info("=== Step 3: Output validation ===")
    output_report = validate_output(args.run_dir)
    full_report["output"] = output_report

    if args.json_report:
        with open(args.json_report, "w") as f:
            json.dump(full_report, f, indent=2)
        log.info(f"Report written to {args.json_report}")

    success = full_report.get("execution", {}).get("success", True) and output_report["valid"]
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
