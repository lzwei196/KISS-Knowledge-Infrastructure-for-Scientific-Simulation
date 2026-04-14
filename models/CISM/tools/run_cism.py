#!/usr/bin/env python3
"""
run_cism.py -- Execute the CISM ice sheet model with preflight checks.

Wraps the cism_driver executable with:
  1. Preflight validation (config file, input NetCDF, binary exists)
  2. Execution with timeout and output capture
  3. Post-run output validation (output NetCDF exists, has expected vars)

CRITICAL:
  - Binary path: typically builds/mpi/cism_driver/cism_driver
  - Config file must end in .config
  - Input NetCDF must exist and match grid dimensions in config
  - For MPI runs: mpirun -n <nproc> cism_driver config.config
  - Output is written to the file specified in [CF output] name = ...

Usage:
    # Serial run
    python run_cism.py --binary ./cism_driver --config dome.config

    # MPI run
    python run_cism.py --binary ./cism_driver --config dome.config \
        --mpi --nproc 4

    # With build step
    python run_cism.py --source_dir /path/to/CISM --config dome.config --build
"""

import argparse
import subprocess
import sys
import os
import time
import configparser


# ---------------------------------------------------------------------------
# Config parser (CISM uses INI-like format with some quirks)
# ---------------------------------------------------------------------------

def parse_cism_config(config_path):
    """Parse CISM .config file and return dict of sections."""
    config = {}
    current_section = None

    with open(config_path) as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#") or line.startswith("!") or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
                config[current_section] = {}
            elif "=" in line and current_section:
                key, _, val = line.partition("=")
                config[current_section][key.strip()] = val.strip()
            elif ":" in line and current_section:
                key, _, val = line.partition(":")
                config[current_section][key.strip()] = val.strip()

    return config


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

def preflight_check(binary_path, config_path):
    """Run preflight checks before execution."""
    errors = []
    warnings = []

    # Check binary
    if not os.path.exists(binary_path):
        errors.append(f"Binary not found: {binary_path}")
    elif not os.access(binary_path, os.X_OK):
        errors.append(f"Binary not executable: {binary_path}")

    # Check config
    if not os.path.exists(config_path):
        errors.append(f"Config not found: {config_path}")
        for e in errors:
            print(f"PREFLIGHT ERROR: {e}")
        return False

    # Parse config
    config = parse_cism_config(config_path)

    # Check required sections (dt_014)
    required = ["grid", "time", "options", "CF input", "CF output"]
    for section in required:
        if section not in config:
            errors.append(
                f"Missing section [{section}] in config (dt_014: "
                f"misspelled section names are silently ignored)"
            )

    # Check input file
    if "CF input" in config:
        input_nc = config["CF input"].get("name", "")
        # Try relative to config directory
        config_dir = os.path.dirname(os.path.abspath(config_path))
        input_path = os.path.join(config_dir, input_nc)
        if not os.path.exists(input_path) and not os.path.exists(input_nc):
            errors.append(f"Input NetCDF not found: {input_nc}")

    # Check parameter sanity
    if "parameters" in config:
        flwa = config["parameters"].get("default_flwa", "")
        if flwa:
            try:
                flwa_val = float(flwa)
                if flwa_val < 1e-25:
                    warnings.append(
                        f"default_flwa={flwa_val} extremely small (dt_002)"
                    )
            except ValueError:
                pass

        geo = config["parameters"].get("geothermal", "")
        if geo:
            try:
                geo_val = float(geo)
                if geo_val > 0:
                    warnings.append(
                        f"geothermal={geo_val} positive -- should be "
                        f"negative (dt_003)"
                    )
            except ValueError:
                pass

    # Check dycore/evolution compatibility (dt_007)
    if "options" in config:
        dycore = int(config["options"].get("dycore", 0))
        evolution = int(config["options"].get("evolution", 0))
        if dycore == 2 and evolution == 0:
            errors.append(
                "dycore=2 (Glissade) with evolution=0 -- "
                "use evolution=3 or 4 (dt_007)"
            )

    for e in errors:
        print(f"PREFLIGHT ERROR: {e}")
    for w in warnings:
        print(f"PREFLIGHT WARNING: {w}")

    if errors:
        return False

    print("Preflight checks passed.")
    return True


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_cism(source_dir, serial=True):
    """Build CISM from source."""
    build_dir = os.path.join(source_dir, "builds", "serial")
    os.makedirs(build_dir, exist_ok=True)

    cmake_args = [
        "cmake",
        f"-DCISM_USE_TRILINOS:BOOL=OFF",
        f"-DCISM_MPI_MODE:BOOL={'OFF' if serial else 'ON'}",
        f"-DCISM_SERIAL_MODE:BOOL={'ON' if serial else 'OFF'}",
        f"-DCISM_BUILD_CISM_DRIVER:BOOL=ON",
        f"-DCISM_NETCDF_DIR=/usr",
        '-DCMAKE_Fortran_FLAGS=-g -O2 -ffree-line-length-none -fPIC -fno-range-check',
        f"-DCMAKE_Fortran_COMPILER=gfortran",
        f"-DCMAKE_C_COMPILER=gcc",
        f"-DCISM_EXTRA_LIBS=-lblas",
        source_dir,
    ]

    print(f"Building CISM in {build_dir}...")
    result = subprocess.run(
        cmake_args, cwd=build_dir,
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"CMake failed:\n{result.stderr[:1000]}")
        return None

    result = subprocess.run(
        ["make", f"-j{os.cpu_count() or 4}"],
        cwd=build_dir, capture_output=True, text=True, timeout=600
    )
    if result.returncode != 0:
        print(f"Make failed:\n{result.stderr[:1000]}")
        return None

    binary = os.path.join(build_dir, "cism_driver", "cism_driver")
    if os.path.exists(binary):
        print(f"Build successful: {binary}")
        return binary

    print("Build completed but binary not found.")
    return None


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_cism(binary_path, config_path, mpi=False, nproc=1, timeout=3600):
    """Execute cism_driver."""
    if mpi and nproc > 1:
        cmd = ["mpirun", "-n", str(nproc), binary_path, config_path]
    else:
        cmd = [binary_path, config_path]

    print(f"Running: {' '.join(cmd)}")
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=os.path.dirname(os.path.abspath(config_path)),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time

        print(f"Exit code: {result.returncode}")
        print(f"Runtime: {elapsed:.1f} seconds")

        if result.stdout:
            # Print last 50 lines of stdout
            stdout_lines = result.stdout.strip().split("\n")
            if len(stdout_lines) > 50:
                print(f"... ({len(stdout_lines) - 50} lines omitted)")
            for line in stdout_lines[-50:]:
                print(f"  {line}")

        if result.returncode != 0:
            print(f"STDERR:\n{result.stderr[:2000]}")
            return False, result.stdout, elapsed

        return True, result.stdout, elapsed

    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {timeout} seconds")
        return False, "", timeout
    except FileNotFoundError:
        print(f"Binary not found: {binary_path}")
        return False, "", 0


# ---------------------------------------------------------------------------
# Post-run validation
# ---------------------------------------------------------------------------

def postrun_check(config_path):
    """Validate output file after model run."""
    config = parse_cism_config(config_path)

    if "CF output" not in config:
        print("No [CF output] section -- cannot validate output")
        return False

    output_nc = config["CF output"].get("name", "")
    config_dir = os.path.dirname(os.path.abspath(config_path))
    output_path = os.path.join(config_dir, output_nc)

    if not os.path.exists(output_path):
        print(f"Output file not found: {output_path}")
        return False

    try:
        import netCDF4
        ds = netCDF4.Dataset(output_path, "r")

        time_dim = ds.dimensions.get("time")
        if time_dim is None or len(time_dim) == 0:
            print("WARNING: Output has no time steps (dt_009: check frequency)")
            ds.close()
            return False

        print(f"Output validation:")
        print(f"  File: {output_path}")
        print(f"  Time steps: {len(time_dim)}")
        print(f"  Variables: {list(ds.variables.keys())}")

        # Check for expected variables
        expected_vars = config["CF output"].get("variables", "").split()
        missing = [v for v in expected_vars if v not in ds.variables]
        if missing:
            print(f"  WARNING: Missing expected output vars: {missing}")

        # Check for NaN
        for vname in ["thk", "uvel", "vvel"]:
            if vname in ds.variables:
                import numpy as np
                data = ds.variables[vname][-1]  # last timestep
                if np.any(np.isnan(data)):
                    print(f"  WARNING: {vname} contains NaN at final timestep")

        ds.close()
        print("Post-run validation passed.")
        return True

    except ImportError:
        print("netCDF4 not available -- skipping output validation")
        return True
    except Exception as e:
        print(f"Output validation error: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run CISM ice sheet model")
    parser.add_argument("--binary", help="Path to cism_driver binary")
    parser.add_argument("--config", required=True, help="Config file (.config)")
    parser.add_argument("--mpi", action="store_true", help="Use MPI")
    parser.add_argument("--nproc", type=int, default=1, help="MPI processes")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout (s)")
    parser.add_argument("--build", action="store_true", help="Build first")
    parser.add_argument("--source_dir", help="Source directory for building")
    parser.add_argument("--skip_preflight", action="store_true")

    args = parser.parse_args()

    # Build if requested
    if args.build and args.source_dir:
        binary = build_cism(args.source_dir, serial=not args.mpi)
        if binary is None:
            sys.exit(1)
        args.binary = binary

    if not args.binary:
        print("ERROR: --binary required (or use --build --source_dir)")
        sys.exit(1)

    # Preflight
    if not args.skip_preflight:
        if not preflight_check(args.binary, args.config):
            sys.exit(1)

    # Run
    success, stdout, elapsed = run_cism(
        args.binary, args.config,
        mpi=args.mpi, nproc=args.nproc, timeout=args.timeout
    )

    if not success:
        print("Model run FAILED")
        sys.exit(1)

    # Post-run validation
    postrun_check(args.config)

    print(f"\nCISM run completed in {elapsed:.1f} seconds")


if __name__ == "__main__":
    main()
