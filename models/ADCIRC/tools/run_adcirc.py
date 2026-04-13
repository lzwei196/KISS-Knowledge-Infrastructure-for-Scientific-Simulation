#!/usr/bin/env python3
"""
run_adcirc.py — Execute ADCIRC with preflight checks, domain decomposition,
and postflight validation.

Supports both serial (adcirc) and parallel (padcirc) execution modes.
For parallel runs, automatically handles adcprep domain decomposition.

Preflight checks:
  - Verifies fort.14 and fort.15 exist
  - Validates fort.15 critical parameters (DTDP, G, ICS consistency)
  - Checks fort.22 exists if NWS != 0
  - Verifies binary exists and is executable

Postflight checks:
  - Verifies output files were created (fort.63, fort.64, maxele.63)
  - Checks for NaN/Inf in output
  - Reports basic statistics

Usage:
    # Serial
    python run_adcirc.py --binary ./adcirc --work_dir /path/to/run

    # Parallel (4 processors)
    python run_adcirc.py --binary ./padcirc --adcprep ./adcprep \
        --work_dir /path/to/run --mode parallel --np 4

    # Dry run (preflight only)
    python run_adcirc.py --binary ./adcirc --work_dir /path/to/run --dry_run
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Preflight validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate execution prerequisites."""
    errors = []
    warnings = []

    # Check binary
    if not os.path.isfile(args.binary):
        errors.append(f"Binary not found: {args.binary}")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"Binary not executable: {args.binary}")

    # Check work directory
    if not os.path.isdir(args.work_dir):
        errors.append(f"Work directory not found: {args.work_dir}")

    # Check required input files
    fort14 = os.path.join(args.work_dir, "fort.14")
    fort15 = os.path.join(args.work_dir, "fort.15")

    if not os.path.isfile(fort14):
        errors.append(f"Grid file not found: {fort14}")
    else:
        # Basic fort.14 validation
        with open(fort14) as f:
            lines = f.readlines()
        if len(lines) < 3:
            errors.append("fort.14 is too short — invalid mesh")
        else:
            try:
                ne, nn = lines[1].strip().split()[:2]
                ne, nn = int(ne), int(nn)
                logger.info(f"Mesh: {nn} nodes, {ne} elements")
            except (ValueError, IndexError):
                errors.append("Cannot parse element/node count in fort.14 line 2")

    if not os.path.isfile(fort15):
        errors.append(f"Control file not found: {fort15}")
    else:
        # Parse critical fort.15 parameters
        params = parse_fort15_params(fort15)
        if params:
            validate_fort15_params(params, errors, warnings)

    # Check for meteorological forcing
    if not errors:
        params = parse_fort15_params(fort15) if os.path.isfile(fort15) else {}
        nws = params.get("NWS", 0)
        if nws != 0:
            fort22 = os.path.join(args.work_dir, "fort.22")
            if not os.path.isfile(fort22):
                errors.append(f"NWS={nws} but fort.22 not found")

    # Parallel mode checks
    if args.mode == "parallel":
        if args.np < 2:
            errors.append(f"Parallel mode requires --np >= 2, got {args.np}")
        if args.adcprep and not os.path.isfile(args.adcprep):
            errors.append(f"adcprep not found: {args.adcprep}")
        # Check MPI
        mpi_bin = shutil.which("mpirun") or shutil.which("mpiexec")
        if not mpi_bin:
            errors.append("mpirun/mpiexec not found — required for parallel mode")

    for w in warnings:
        logger.warning(w)

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} preflight error(s)")

    logger.info("Preflight checks passed")
    return params if not errors else {}


def parse_fort15_params(filepath):
    """Extract key parameters from fort.15 control file.

    Returns dict of parameter name → value.
    """
    params = {}
    try:
        with open(filepath) as f:
            content = f.read()
            lines = content.split("\n")

        # Fort.15 is positional, but we can extract some values by pattern
        # Look for common parameter names in comments
        for line in lines:
            line = line.strip()
            # Try to match "VALUE ! PARAMETER_NAME" pattern
            match = re.match(r"^\s*([-\d.eE+]+)\s+.*!\s*(\w+)", line)
            if match:
                try:
                    val = float(match.group(1))
                    name = match.group(2).upper()
                    params[name] = val
                except ValueError:
                    pass

        # Also try to read DTDP from line 10 (typical position)
        if "DTDP" not in params and len(lines) > 10:
            for i, line in enumerate(lines[:30]):
                parts = line.strip().split()
                if len(parts) >= 1:
                    try:
                        val = float(parts[0])
                        # DTDP is typically 0.5-60 seconds
                        if "DTDP" not in params and 0.1 < val < 120 and i > 5:
                            # Heuristic: first float in range after line 5
                            pass
                    except ValueError:
                        pass

    except Exception as e:
        logger.warning(f"Could not parse fort.15: {e}")

    return params


def validate_fort15_params(params, errors, warnings):
    """Validate critical fort.15 parameters."""

    # Check G consistency with ICS
    g = params.get("G", 9.81)
    ics = params.get("ICS", 2)
    if ics == 2 and abs(g - 32.174) < 0.1:
        errors.append(
            "FATAL: G=32.174 (feet) with ICS=2 (spherical/degrees) — "
            "this will produce wrong results. Use G=9.81 for metric. (dt_002)"
        )

    # Check DTDP
    dtdp = params.get("DTDP", None)
    if dtdp is not None:
        if dtdp <= 0:
            errors.append(f"DTDP must be positive, got {dtdp}")
        elif dtdp > 60:
            warnings.append(
                f"DTDP={dtdp}s is large — verify CFL condition. "
                f"Typical range: 0.5-10s for coastal, 10-60s for deep ocean. (dt_006)"
            )

    # Check TAU0
    tau0 = params.get("TAU0", None)
    if tau0 is not None and tau0 > 0:
        if tau0 < 0.001:
            warnings.append(
                f"TAU0={tau0} is very small — may cause mass balance errors. "
                f"Consider TAU0=-3 for automatic spatial variation. (dt_005)"
            )
        elif tau0 > 0.1:
            warnings.append(
                f"TAU0={tau0} is large — may over-damp tidal signals. (dt_005)"
            )

    # Check H0
    h0 = params.get("H0", None)
    if h0 is not None:
        if h0 > 1.0:
            warnings.append(
                f"H0={h0}m is large — will underestimate inundation. "
                f"Typical: 0.01-0.1m. (dt_008)"
            )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def run_serial(binary, work_dir, timeout=None):
    """Run serial ADCIRC."""
    logger.info(f"Running serial: {binary}")
    start = time.time()

    result = subprocess.run(
        [binary],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    elapsed = time.time() - start
    logger.info(f"Completed in {elapsed:.1f}s (exit code {result.returncode})")

    if result.returncode != 0:
        logger.error(f"STDOUT:\n{result.stdout[-2000:]}")
        logger.error(f"STDERR:\n{result.stderr[-2000:]}")
        raise RuntimeError(f"ADCIRC exited with code {result.returncode}")

    return {
        "exit_code": result.returncode,
        "elapsed_s": round(elapsed, 1),
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-500:],
    }


def run_parallel(binary, adcprep, work_dir, np_count, timeout=None):
    """Run parallel ADCIRC with domain decomposition."""

    # Step 1: Partition mesh
    logger.info(f"Running adcprep --partmesh (np={np_count})")
    result = subprocess.run(
        [adcprep, "--np", str(np_count), "--partmesh"],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"adcprep --partmesh failed: {result.stderr[-500:]}"
        )

    # Step 2: Prepare per-processor files
    logger.info(f"Running adcprep --prepall (np={np_count})")
    result = subprocess.run(
        [adcprep, "--np", str(np_count), "--prepall"],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"adcprep --prepall failed: {result.stderr[-500:]}"
        )

    # Step 3: Run padcirc
    mpi_bin = shutil.which("mpirun") or shutil.which("mpiexec")
    logger.info(f"Running: {mpi_bin} -np {np_count} {binary}")
    start = time.time()

    result = subprocess.run(
        [mpi_bin, "-np", str(np_count), binary],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    elapsed = time.time() - start
    logger.info(f"Completed in {elapsed:.1f}s (exit code {result.returncode})")

    if result.returncode != 0:
        logger.error(f"STDOUT:\n{result.stdout[-2000:]}")
        logger.error(f"STDERR:\n{result.stderr[-2000:]}")
        raise RuntimeError(f"padcirc exited with code {result.returncode}")

    return {
        "exit_code": result.returncode,
        "elapsed_s": round(elapsed, 1),
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-500:],
    }


# ---------------------------------------------------------------------------
# Postflight validation
# ---------------------------------------------------------------------------
def validate_outputs(work_dir):
    """Validate ADCIRC output files after execution."""
    results = {}
    warnings = []

    # Check for expected output files
    expected_files = [
        "fort.63",    # Water surface elevation (global)
        "fort.64",    # Velocity (global)
        "maxele.63",  # Maximum elevation
    ]
    optional_files = [
        "fort.61",    # Elevation at stations
        "fort.62",    # Velocity at stations
        "fort.73",    # Wind velocity
        "fort.74",    # Atmospheric pressure
        "maxvel.63",  # Maximum velocity
        "maxwvel.63", # Maximum wind velocity
    ]

    for fname in expected_files:
        fpath = os.path.join(work_dir, fname)
        if os.path.isfile(fpath):
            size_mb = os.path.getsize(fpath) / (1024 * 1024)
            results[fname] = {"exists": True, "size_mb": round(size_mb, 2)}
            logger.info(f"  {fname}: {size_mb:.2f} MB")
        else:
            results[fname] = {"exists": False}
            warnings.append(f"Expected output not found: {fname}")

    for fname in optional_files:
        fpath = os.path.join(work_dir, fname)
        if os.path.isfile(fpath):
            size_mb = os.path.getsize(fpath) / (1024 * 1024)
            results[fname] = {"exists": True, "size_mb": round(size_mb, 2)}

    # Quick check for NaN in maxele.63
    maxele_path = os.path.join(work_dir, "maxele.63")
    if os.path.isfile(maxele_path):
        try:
            with open(maxele_path) as f:
                content = f.read(50000)  # First 50KB
            if "NaN" in content or "Inf" in content or "nan" in content:
                warnings.append(
                    "NaN/Inf detected in maxele.63 — "
                    "likely CFL violation or unstable parameters (dt_006, dt_016)"
                )
        except Exception:
            pass

    for w in warnings:
        logger.warning(w)

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def process(args):
    """Main pipeline: validate → execute → validate."""

    # Step 1: Preflight
    params = validate_inputs(args)

    if args.dry_run:
        logger.info("Dry run — skipping execution")
        return

    # Step 2: Execute
    if args.mode == "serial":
        run_info = run_serial(
            args.binary, args.work_dir, timeout=args.timeout
        )
    else:
        run_info = run_parallel(
            args.binary, args.adcprep or "",
            args.work_dir, args.np,
            timeout=args.timeout,
        )

    # Step 3: Postflight
    output_info = validate_outputs(args.work_dir)

    # Step 4: Write summary
    summary = {
        "mode": args.mode,
        "binary": args.binary,
        "np": args.np if args.mode == "parallel" else 1,
        "elapsed_s": run_info["elapsed_s"],
        "exit_code": run_info["exit_code"],
        "outputs": output_info,
    }

    summary_path = os.path.join(args.work_dir, "run_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Summary written to {summary_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Execute ADCIRC with preflight checks and validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--binary", required=True,
                        help="Path to adcirc or padcirc binary")
    parser.add_argument("--adcprep", default=None,
                        help="Path to adcprep binary (required for parallel)")
    parser.add_argument("--work_dir", required=True,
                        help="Working directory containing fort.* files")
    parser.add_argument("--mode", choices=["serial", "parallel"],
                        default="serial",
                        help="Execution mode (default: serial)")
    parser.add_argument("--np", type=int, default=4,
                        help="Number of processors for parallel (default: 4)")
    parser.add_argument("--timeout", type=int, default=None,
                        help="Timeout in seconds (default: no timeout)")
    parser.add_argument("--dry_run", action="store_true",
                        help="Preflight checks only, do not execute")

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
