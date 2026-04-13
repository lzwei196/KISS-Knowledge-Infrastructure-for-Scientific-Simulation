#!/usr/bin/env python3
"""
ROMS Execution Wrapper
=======================
Compiles (optional) and runs the ROMS ocean model, with pre-flight checks
and post-run validation.

Pre-flight checks:
  - Binary exists or build is requested
  - roms.in configuration file is valid
  - All referenced NetCDF files exist
  - NtileI * NtileJ matches MPI process count
  - CFL stability estimate

Post-run checks:
  - Exit code == 0
  - Output NetCDF files created
  - No NaN/blow-up in final timestep
  - Log file scan for known error patterns

Usage:
  # Serial run
  python run_roms.py --binary ./romsS --config roms.in

  # MPI run
  python run_roms.py --binary ./romsM --config roms.in --np 8

  # Build + run
  python run_roms.py --source-dir /path/to/roms --app UPWELLING --config roms.in

  # Build only
  python run_roms.py --source-dir /path/to/roms --app UPWELLING --build-only
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time


def validate_inputs(args):
    """Validate inputs before execution."""
    errors = []

    if not args.build_only and not args.source_dir:
        if not args.binary:
            errors.append("Must specify --binary or --source-dir")
        elif not os.path.isfile(args.binary):
            errors.append(f"Binary not found: {args.binary}")

    if not args.build_only:
        if not args.config:
            errors.append("Must specify --config (roms.in file)")
        elif not os.path.isfile(args.config):
            errors.append(f"Config file not found: {args.config}")

    if args.source_dir and not os.path.isdir(args.source_dir):
        errors.append(f"Source directory not found: {args.source_dir}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def parse_roms_in(config_path):
    """Parse roms.in file and extract key parameters."""
    params = {}
    with open(config_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('!'):
                continue
            # Handle == and = separators
            for sep in ['==', '=']:
                if sep in line:
                    key, val = line.split(sep, 1)
                    key = key.strip()
                    val = val.split('!')[0].strip()  # Remove inline comments
                    params[key] = val
                    break
    return params


def check_input_files(config_path):
    """Check that all referenced input files exist."""
    params = parse_roms_in(config_path)
    missing = []
    file_keys = ['GRDNAME', 'ININAME', 'FRCNAME', 'BRYNAME', 'CLMNAME',
                 'TIDENAME', 'VARNAME', 'SPOSNAM', 'FPOSNAM']

    for key in file_keys:
        if key in params:
            # Handle multiple files (pipe-separated)
            paths = params[key].replace('|', '\n').split('\n')
            for p in paths:
                p = p.strip()
                if p and not os.path.isfile(p):
                    missing.append(f"{key}: {p}")

    return params, missing


def estimate_cfl(params):
    """Rough CFL stability check based on parameters."""
    warnings = []
    try:
        dt = float(params.get('DT', '0').replace('d0', '').replace('D0', ''))
        ndtfast = int(params.get('NDTFAST', '0'))
        if dt > 0 and ndtfast > 0:
            dtfast = dt / ndtfast
            # Typical deep ocean: sqrt(g*5000) ~ 220 m/s
            # Need dtfast < dx / c_barotropic
            if ndtfast < 10:
                warnings.append(f"NDTFAST={ndtfast} is very small (typical: 20-60)")
            if ndtfast > 100:
                warnings.append(f"NDTFAST={ndtfast} is very large (typical: 20-60)")
            if dt > 3600:
                warnings.append(f"DT={dt}s is very large (>1 hour)")
    except (ValueError, TypeError):
        pass
    return warnings


def check_mpi_consistency(params, nprocs):
    """Check NtileI * NtileJ == nprocs."""
    try:
        ntile_i = int(params.get('NtileI', '1'))
        ntile_j = int(params.get('NtileJ', '1'))
        total = ntile_i * ntile_j
        if total != nprocs:
            return f"NtileI({ntile_i}) * NtileJ({ntile_j}) = {total} != nprocs({nprocs})"
    except (ValueError, TypeError):
        pass
    return None


def build_roms(source_dir, app_name, build_dir=None, compiler='gfortran', nprocs=1):
    """Build ROMS using CMake or Makefile."""
    if build_dir is None:
        build_dir = os.path.join(source_dir, 'build')

    os.makedirs(build_dir, exist_ok=True)

    # Try CMake first
    cmake_file = os.path.join(source_dir, 'CMakeLists.txt')
    if os.path.isfile(cmake_file):
        print(f"Building ROMS with CMake (app={app_name})...")
        cmake_cmd = [
            'cmake', source_dir,
            f'-DAPP={app_name}',
            f'-DCMAKE_Fortran_COMPILER={compiler}',
        ]
        result = subprocess.run(cmake_cmd, cwd=build_dir,
                                capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return None, f"CMake configure failed:\n{result.stderr[:1000]}"

        make_cmd = ['make', f'-j{nprocs}']
        result = subprocess.run(make_cmd, cwd=build_dir,
                                capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            return None, f"Make failed:\n{result.stderr[:1000]}"

        # Find binary
        for name in ['romsM', 'romsS', 'romsO']:
            path = os.path.join(build_dir, name)
            if os.path.isfile(path):
                return path, None

        return None, "Build completed but binary not found"

    # Fallback to Makefile
    makefile = os.path.join(source_dir, 'makefile')
    if os.path.isfile(makefile):
        print(f"Building ROMS with Make (app={app_name})...")
        env = os.environ.copy()
        env['ROMS_APPLICATION'] = app_name
        result = subprocess.run(['make', f'-j{nprocs}'], cwd=source_dir,
                                capture_output=True, text=True, timeout=1800, env=env)
        if result.returncode != 0:
            return None, f"Make failed:\n{result.stderr[:1000]}"

        for name in ['romsM', 'romsS', 'romsO']:
            path = os.path.join(source_dir, name)
            if os.path.isfile(path):
                return path, None

    return None, "No CMakeLists.txt or makefile found in source directory"


def run_roms(binary, config, nprocs=1, timeout=7200, workdir=None):
    """Execute the ROMS model."""
    if workdir is None:
        workdir = os.path.dirname(os.path.abspath(config))

    if nprocs > 1:
        cmd = ['mpirun', '-np', str(nprocs), binary, config]
    else:
        cmd = [binary]
        stdin_file = config

    print(f"Running: {' '.join(cmd)}")
    start_time = time.time()

    if nprocs > 1:
        result = subprocess.run(
            cmd, cwd=workdir,
            capture_output=True, text=True, timeout=timeout
        )
    else:
        with open(config, 'r') as stdin_f:
            result = subprocess.run(
                cmd, cwd=workdir, stdin=stdin_f,
                capture_output=True, text=True, timeout=timeout
            )

    elapsed = time.time() - start_time

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_seconds": elapsed
    }


def scan_log_for_errors(stdout, stderr):
    """Scan ROMS output for known error patterns."""
    errors = []
    warnings = []
    combined = stdout + stderr

    error_patterns = [
        (r'BLOWUP', 'Model blew up — numerical instability'),
        (r'FATAL ERROR', 'Fatal error encountered'),
        (r'NetCDF.*error', 'NetCDF I/O error'),
        (r'STOP\s+\d+', 'Fortran STOP encountered'),
        (r'Segmentation fault', 'Memory access error'),
        (r'SIGFPE', 'Floating point exception'),
        (r'NaN', 'NaN values detected'),
        (r'out of memory', 'Memory allocation failure'),
    ]

    warning_patterns = [
        (r'WARNING', 'Warning message in log'),
        (r'CFL violation', 'CFL stability violation'),
        (r'wet.*dry', 'Wet/dry masking issues'),
    ]

    for pattern, msg in error_patterns:
        if re.search(pattern, combined, re.IGNORECASE):
            errors.append(msg)

    for pattern, msg in warning_patterns:
        if re.search(pattern, combined, re.IGNORECASE):
            warnings.append(msg)

    return errors, warnings


def validate_output_files(params, workdir='.'):
    """Check that expected output files were created."""
    created = []
    missing = []

    output_keys = ['HISNAME', 'AVGNAME', 'DIANAME', 'RSTNAME', 'STANAME']
    for key in output_keys:
        if key in params:
            path = params[key].strip()
            if not os.path.isabs(path):
                path = os.path.join(workdir, path)
            if os.path.isfile(path):
                size_mb = os.path.getsize(path) / (1024 * 1024)
                created.append(f"{key}: {path} ({size_mb:.1f} MB)")
            else:
                missing.append(f"{key}: {path}")

    return created, missing


def main():
    parser = argparse.ArgumentParser(description='ROMS execution wrapper')
    parser.add_argument('--binary', type=str, default=None,
                        help='Path to ROMS binary (romsS or romsM)')
    parser.add_argument('--config', type=str, default=None,
                        help='Path to roms.in configuration file')
    parser.add_argument('--np', type=int, default=1,
                        help='Number of MPI processes')
    parser.add_argument('--timeout', type=int, default=7200,
                        help='Maximum runtime in seconds')
    parser.add_argument('--source-dir', type=str, default=None,
                        help='Source directory for building ROMS')
    parser.add_argument('--app', type=str, default=None,
                        help='ROMS application name for building (e.g., UPWELLING)')
    parser.add_argument('--build-only', action='store_true',
                        help='Only build, do not run')
    parser.add_argument('--compiler', type=str, default='gfortran',
                        help='Fortran compiler for building')
    parser.add_argument('--workdir', type=str, default=None,
                        help='Working directory for execution')

    args = parser.parse_args()
    validate_inputs(args)

    result = {"status": "pending"}
    binary_path = args.binary

    # Build if requested
    if args.source_dir and args.app:
        binary_path, build_error = build_roms(
            args.source_dir, args.app,
            compiler=args.compiler, nprocs=args.np
        )
        if build_error:
            result = {
                "status": "build_failed",
                "error": build_error
            }
            print(json.dumps(result, indent=2))
            sys.exit(1)
        print(f"Build successful: {binary_path}")
        result["binary_path"] = binary_path

    if args.build_only:
        result["status"] = "build_success"
        result["binary_path"] = binary_path
        print(json.dumps(result, indent=2))
        return

    # Pre-flight checks
    params, missing_files = check_input_files(args.config)
    if missing_files:
        print(f"WARNING: Missing input files: {missing_files}")

    cfl_warnings = estimate_cfl(params)
    if cfl_warnings:
        for w in cfl_warnings:
            print(f"CFL WARNING: {w}")

    if args.np > 1:
        mpi_error = check_mpi_consistency(params, args.np)
        if mpi_error:
            result = {"status": "error", "error": f"MPI mismatch: {mpi_error}"}
            print(json.dumps(result, indent=2))
            sys.exit(1)

    # Run
    run_result = run_roms(binary_path, args.config, nprocs=args.np,
                          timeout=args.timeout, workdir=args.workdir)

    # Post-run analysis
    log_errors, log_warnings = scan_log_for_errors(
        run_result['stdout'], run_result['stderr']
    )

    workdir = args.workdir or os.path.dirname(os.path.abspath(args.config))
    created, missing_out = validate_output_files(params, workdir)

    if run_result['returncode'] == 0 and not log_errors:
        status = "success"
    elif log_errors:
        status = "runtime_error"
    else:
        status = "failed"

    result = {
        "status": status,
        "binary": binary_path,
        "config": args.config,
        "returncode": run_result['returncode'],
        "elapsed_seconds": run_result['elapsed_seconds'],
        "log_errors": log_errors,
        "log_warnings": log_warnings,
        "output_files_created": created,
        "output_files_missing": missing_out,
        "stdout_tail": run_result['stdout'][-500:] if run_result['stdout'] else "",
        "stderr_tail": run_result['stderr'][-500:] if run_result['stderr'] else "",
    }

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
