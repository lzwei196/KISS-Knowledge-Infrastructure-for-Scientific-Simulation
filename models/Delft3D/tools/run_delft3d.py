#!/usr/bin/env python3
"""
run_delft3d.py — Execute Delft3D (DIMR) with preflight checks and monitoring

Wrapper for running Delft3D simulations via the DIMR (Deltares Integrated
Model Runner) executable. Performs preflight validation of input files,
monitors execution, and validates output.

Pipeline stage: s6 (execution)
Pattern: validate → process → validate

Supports:
  - Sequential execution (single process)
  - Parallel execution (MPI, multi-process)
  - D-Flow FM (dflowfm) standalone
  - Delft3D-FLOW (flow2d3d) standalone
  - Coupled simulations via DIMR
"""

import argparse
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

DIMR_BINARY = "dimr"
DFLOWFM_BINARY = "dflowfm"
FLOW2D3D_BINARY = "flow2d3d"
RUN_DIMR_SCRIPT = "run_dimr.sh"

MAX_RUNTIME_SECONDS = 86400 * 7  # 7 days
PROGRESS_CHECK_INTERVAL = 30  # seconds


# ──────────────────────────────────────────────────────────────────────
# Preflight validation
# ──────────────────────────────────────────────────────────────────────

def preflight_check(dimr_config, binary_dir, work_dir):
    """Validate all inputs before execution."""
    errors = []
    warnings = []

    # Check DIMR config exists
    config_path = os.path.join(work_dir, dimr_config)
    if not os.path.isfile(config_path):
        errors.append(f"DIMR config not found: {config_path}")
        return errors, warnings

    # Parse DIMR config
    try:
        tree = ET.parse(config_path)
        root = tree.getroot()
    except ET.ParseError as e:
        errors.append(f"DIMR config XML parse error: {e}")
        return errors, warnings

    # Check components
    components = root.findall(".//component")
    if not components:
        errors.append("No <component> elements found in DIMR config")
        return errors, warnings

    for comp in components:
        comp_name = comp.get("name", "unnamed")
        library = comp.findtext("library", "")
        input_file = comp.findtext("inputFile", "")
        comp_workdir = comp.findtext("workingDir", ".")

        print(f"  Component: {comp_name} (library={library})")

        # Check input file exists
        input_path = os.path.join(work_dir, comp_workdir, input_file)
        if input_file and not os.path.isfile(input_path):
            errors.append(f"Input file not found: {input_path}")
        else:
            print(f"    Input: {input_path} ✓")

        # Validate MDU/MDF if it's a flow component
        if library in ("dflowfm", "flow2d3d") and os.path.isfile(input_path):
            _validate_model_config(input_path, library, errors, warnings)

    # Check binary exists
    if binary_dir:
        dimr_path = os.path.join(binary_dir, DIMR_BINARY)
        run_script = os.path.join(binary_dir, RUN_DIMR_SCRIPT)
        if os.path.isfile(dimr_path):
            print(f"  Binary: {dimr_path} ✓")
        elif os.path.isfile(run_script):
            print(f"  Run script: {run_script} ✓")
        else:
            errors.append(f"Neither {DIMR_BINARY} nor {RUN_DIMR_SCRIPT} found in {binary_dir}")

    return errors, warnings


def _validate_model_config(config_path, engine, errors, warnings):
    """Validate MDU or MDF configuration file."""
    with open(config_path) as f:
        content = f.read()

    config_dir = os.path.dirname(config_path)

    if engine == "dflowfm":
        _validate_mdu(content, config_dir, errors, warnings)
    elif engine == "flow2d3d":
        _validate_mdf(content, config_dir, errors, warnings)


def _validate_mdu(content, config_dir, errors, warnings):
    """Validate D-Flow FM MDU file."""
    # Check grid file reference
    net_match = re.search(r"NetFile\s*=\s*(.+?)[\s#]", content)
    if net_match:
        net_file = net_match.group(1).strip()
        net_path = os.path.join(config_dir, net_file)
        if not os.path.isfile(net_path):
            errors.append(f"Grid file not found: {net_path}")
        else:
            print(f"    Grid: {net_path} ✓")

    # Check external forcing file
    ext_match = re.search(r"ExtForceFileNew\s*=\s*(.+?)[\s#]", content)
    if ext_match:
        ext_file = ext_match.group(1).strip()
        ext_path = os.path.join(config_dir, ext_file)
        if not os.path.isfile(ext_path):
            errors.append(f"External forcing file not found: {ext_path}")
        else:
            print(f"    ExtForce: {ext_path} ✓")

    # Check time settings
    tstart_match = re.search(r"TStart\s*=\s*([\d.]+)", content)
    tstop_match = re.search(r"TStop\s*=\s*([\d.]+)", content)
    tunit_match = re.search(r"Tunit\s*=\s*(\w+)", content)

    if tstart_match and tstop_match:
        tstart = float(tstart_match.group(1))
        tstop = float(tstop_match.group(1))
        tunit = tunit_match.group(1) if tunit_match else "S"

        if tstop <= tstart:
            errors.append(f"TStop ({tstop}) <= TStart ({tstart})")

        # Convert to seconds
        multiplier = {"S": 1, "M": 60, "H": 3600}
        duration_s = (tstop - tstart) * multiplier.get(tunit.upper(), 1)
        duration_hr = duration_s / 3600

        print(f"    Duration: {duration_hr:.1f} hours (Tunit={tunit})")

        if duration_s > MAX_RUNTIME_SECONDS:
            warnings.append(
                f"Simulation duration {duration_hr:.0f} hours — may take very long"
            )

    # Check CFL
    cfl_match = re.search(r"CFLMax\s*=\s*([\d.]+)", content)
    if cfl_match:
        cfl = float(cfl_match.group(1))
        if cfl > 1.0:
            warnings.append(f"CFLMax={cfl} > 1.0 — simulation may be unstable")
        print(f"    CFL: {cfl}")


def _validate_mdf(content, config_dir, errors, warnings):
    """Validate Delft3D-FLOW MDF file."""
    # Check grid file
    grd_match = re.search(r"Filcco\s*=\s*#(.+?)#", content)
    if grd_match:
        grd_file = grd_match.group(1).strip()
        grd_path = os.path.join(config_dir, grd_file)
        if not os.path.isfile(grd_path):
            errors.append(f"Grid file not found: {grd_path}")
        else:
            print(f"    Grid: {grd_path} ✓")

    # Check depth file
    dep_match = re.search(r"Fildep\s*=\s*#(.+?)#", content)
    if dep_match:
        dep_file = dep_match.group(1).strip()
        dep_path = os.path.join(config_dir, dep_file)
        if not os.path.isfile(dep_path):
            errors.append(f"Depth file not found: {dep_path}")
        else:
            print(f"    Depth: {dep_path} ✓")


# ──────────────────────────────────────────────────────────────────────
# Execution
# ──────────────────────────────────────────────────────────────────────

def run_simulation(dimr_config, binary_dir, work_dir, nproc=1,
                   max_runtime=MAX_RUNTIME_SECONDS, log_file=None):
    """Execute Delft3D via DIMR."""

    # Build command
    if binary_dir:
        run_script = os.path.join(binary_dir, RUN_DIMR_SCRIPT)
        dimr_binary = os.path.join(binary_dir, DIMR_BINARY)

        if os.path.isfile(run_script):
            if nproc > 1:
                cmd = [run_script, "-m", dimr_config, "-c", str(nproc)]
            else:
                cmd = [run_script, "-m", dimr_config]
        elif os.path.isfile(dimr_binary):
            if nproc > 1:
                cmd = ["mpirun", "-np", str(nproc), dimr_binary, dimr_config]
            else:
                cmd = [dimr_binary, dimr_config]
        else:
            print(f"ERROR: No executable found in {binary_dir}", file=sys.stderr)
            return None, "No executable found"
    else:
        # Try system PATH
        if nproc > 1:
            cmd = ["mpirun", "-np", str(nproc), DIMR_BINARY, dimr_config]
        else:
            cmd = [DIMR_BINARY, dimr_config]

    print(f"\n[execute] Command: {' '.join(cmd)}")
    print(f"[execute] Working dir: {work_dir}")
    print(f"[execute] Processes: {nproc}")
    print(f"[execute] Max runtime: {max_runtime/3600:.1f} hours")
    print(f"[execute] Started at: {datetime.now().isoformat()}")

    # Set up environment
    env = os.environ.copy()
    if binary_dir:
        lib_dir = os.path.join(os.path.dirname(binary_dir), "lib")
        if os.path.isdir(lib_dir):
            env["LD_LIBRARY_PATH"] = lib_dir + ":" + env.get("LD_LIBRARY_PATH", "")

    # Run simulation
    start_time = time.time()

    if log_file:
        log_path = os.path.join(work_dir, log_file)
        with open(log_path, "w") as lf:
            proc = subprocess.Popen(
                cmd, cwd=work_dir, env=env,
                stdout=lf, stderr=subprocess.STDOUT,
                text=True
            )
    else:
        proc = subprocess.Popen(
            cmd, cwd=work_dir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True
        )

    # Monitor execution
    stdout_lines = []
    try:
        if log_file:
            # Monitor log file for progress
            while proc.poll() is None:
                elapsed = time.time() - start_time
                if elapsed > max_runtime:
                    proc.kill()
                    return None, f"Exceeded max runtime ({max_runtime}s)"
                time.sleep(min(PROGRESS_CHECK_INTERVAL, max_runtime - elapsed))
        else:
            for line in proc.stdout:
                stdout_lines.append(line)
                # Print progress indicators
                if "%" in line or "time" in line.lower() or "step" in line.lower():
                    print(f"  {line.rstrip()}")

                elapsed = time.time() - start_time
                if elapsed > max_runtime:
                    proc.kill()
                    return None, f"Exceeded max runtime ({max_runtime}s)"

        proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        return None, "Interrupted by user"

    elapsed = time.time() - start_time
    stdout_text = "".join(stdout_lines)

    print(f"\n[execute] Finished at: {datetime.now().isoformat()}")
    print(f"[execute] Duration: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"[execute] Return code: {proc.returncode}")

    if proc.returncode != 0:
        print(f"\n[execute] FAILED — last 20 lines of output:")
        for line in stdout_lines[-20:]:
            print(f"  {line.rstrip()}")
        return proc.returncode, stdout_text

    return proc.returncode, stdout_text


# ──────────────────────────────────────────────────────────────────────
# Post-execution validation
# ──────────────────────────────────────────────────────────────────────

def validate_output(work_dir, dimr_config):
    """Validate simulation output files exist and contain data."""
    warnings = []

    # Parse DIMR config to find output directories
    config_path = os.path.join(work_dir, dimr_config)
    tree = ET.parse(config_path)
    root = tree.getroot()

    for comp in root.findall(".//component"):
        comp_workdir = comp.findtext("workingDir", ".")
        input_file = comp.findtext("inputFile", "")
        library = comp.findtext("library", "")

        comp_dir = os.path.join(work_dir, comp_workdir)

        # Find output directory
        if library == "dflowfm":
            output_dir = os.path.join(comp_dir, "output")
            if not os.path.isdir(output_dir):
                output_dir = comp_dir  # fallback to component directory
        else:
            output_dir = comp_dir

        # Check for NetCDF output files
        nc_files = list(Path(output_dir).rglob("*_map.nc")) + \
                   list(Path(output_dir).rglob("*_his.nc")) + \
                   list(Path(output_dir).rglob("*.nc"))

        if not nc_files:
            warnings.append(f"No NetCDF output files found in {output_dir}")
            continue

        print(f"\n[validate_output] Found {len(nc_files)} NetCDF file(s):")
        for ncf in nc_files:
            size_mb = ncf.stat().st_size / 1024 / 1024
            print(f"  {ncf.name}: {size_mb:.1f} MB")

            if nc is not None and size_mb > 0:
                try:
                    ds = nc.Dataset(str(ncf), "r")
                    n_times = 0
                    for dim in ds.dimensions:
                        if "time" in dim.lower():
                            n_times = len(ds.dimensions[dim])
                            break

                    # Check key variables
                    key_vars = ["s1", "ucx", "ucy", "waterdepth", "sa1", "tem1"]
                    found_vars = [v for v in key_vars if v in ds.variables]

                    print(f"    Timesteps: {n_times}")
                    print(f"    Key vars: {', '.join(found_vars)}")

                    # Check for NaN/Inf
                    for vname in found_vars[:3]:
                        data = ds.variables[vname][-1]  # last timestep
                        if isinstance(data, np.ma.MaskedArray):
                            data = data.compressed()
                        n_nan = np.sum(np.isnan(data))
                        n_inf = np.sum(np.isinf(data))
                        if n_nan > 0:
                            warnings.append(f"{vname} has {n_nan} NaN values in last timestep")
                        if n_inf > 0:
                            warnings.append(f"{vname} has {n_inf} Inf values — numerical blowup!")

                    ds.close()
                except Exception as e:
                    warnings.append(f"Could not read {ncf.name}: {e}")

    if warnings:
        print("\n[validate_output] WARNINGS:")
        for w in warnings:
            print(f"  ⚠ {w}")
    else:
        print("\n[validate_output] Output validation passed.")

    return warnings


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Execute Delft3D simulation via DIMR"
    )
    parser.add_argument("--dimr_config", default="dimr_config.xml",
                        help="DIMR configuration XML file")
    parser.add_argument("--binary_dir",
                        help="Directory containing DIMR binary / run_dimr.sh")
    parser.add_argument("--work_dir", default=".",
                        help="Working directory for simulation")
    parser.add_argument("--nproc", type=int, default=1,
                        help="Number of MPI processes")
    parser.add_argument("--max_runtime", type=int, default=MAX_RUNTIME_SECONDS,
                        help="Maximum runtime in seconds")
    parser.add_argument("--log_file", default="simulation.log",
                        help="Log file name (in work_dir)")
    parser.add_argument("--skip_preflight", action="store_true",
                        help="Skip preflight checks")
    args = parser.parse_args()

    # Step 1: Preflight validation
    if not args.skip_preflight:
        print("=" * 60)
        print("[preflight] Validating inputs...")
        print("=" * 60)
        errors, warnings = preflight_check(
            args.dimr_config, args.binary_dir, args.work_dir
        )

        if errors:
            print("\n[preflight] ERRORS (cannot proceed):")
            for e in errors:
                print(f"  ✗ {e}")
            sys.exit(1)

        if warnings:
            print("\n[preflight] Warnings:")
            for w in warnings:
                print(f"  ⚠ {w}")

        print("\n[preflight] All checks passed.")

    # Step 2: Execute
    print("\n" + "=" * 60)
    print("[execute] Running Delft3D simulation...")
    print("=" * 60)

    returncode, output = run_simulation(
        args.dimr_config, args.binary_dir, args.work_dir,
        nproc=args.nproc, max_runtime=args.max_runtime,
        log_file=args.log_file
    )

    if returncode is None or returncode != 0:
        print(f"\n[FAILED] Simulation failed (return code: {returncode})")
        if output and isinstance(output, str):
            print(f"[FAILED] Last output: {output[:500]}")
        sys.exit(1)

    # Step 3: Validate output
    print("\n" + "=" * 60)
    print("[validate] Checking output files...")
    print("=" * 60)

    warnings = validate_output(args.work_dir, args.dimr_config)

    if warnings:
        print(f"\n[DONE] Simulation completed with {len(warnings)} warning(s)")
    else:
        print(f"\n[DONE] Simulation completed successfully")


if __name__ == "__main__":
    main()
