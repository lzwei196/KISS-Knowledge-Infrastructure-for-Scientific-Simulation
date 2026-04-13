#!/usr/bin/env python3
"""
run_noahmp.py — Stage s6: Noah-MP Execution Wrapper

Compiles the Noah-MP HRLDAS driver (if needed), performs preflight validation
of all required input files, runs the model, and validates output.

Execution sequence:
  1. validate_inputs:  Check source, namelist, forcing files, parameter table
  2. compile:          Build HRLDAS binary if not already compiled
  3. preflight:        Verify namelist consistency, forcing file coverage
  4. execute:          Run the model binary
  5. validate_outputs: Check output files were created and are non-empty

Pattern: validate → compile → preflight → execute → validate
"""

import os
import sys
import json
import argparse
import subprocess
import shutil
import re
from datetime import datetime, timedelta


def validate_inputs(args):
    """Validate all input paths and configurations."""
    errors = []

    if not os.path.isdir(args.source_dir):
        errors.append(f"Source directory not found: {args.source_dir}")

    if not os.path.isfile(args.namelist):
        errors.append(f"Namelist file not found: {args.namelist}")

    if not os.path.isdir(args.run_dir):
        os.makedirs(args.run_dir, exist_ok=True)

    if errors:
        print("INPUT VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


def find_binary(source_dir):
    """Find compiled Noah-MP binary in source tree."""
    # Common binary locations
    candidates = [
        os.path.join(source_dir, "drivers", "hrldas", "NoahmpDriverMainMod.exe"),
        os.path.join(source_dir, "drivers", "hrldas", "noahmp.exe"),
        os.path.join(source_dir, "drivers", "hrldas", "hrldas.exe"),
        os.path.join(source_dir, "run", "noahmp.exe"),
    ]

    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    # Search for any .exe file in hrldas driver directory
    hrldas_dir = os.path.join(source_dir, "drivers", "hrldas")
    if os.path.isdir(hrldas_dir):
        for f in os.listdir(hrldas_dir):
            if f.endswith(".exe"):
                fpath = os.path.join(hrldas_dir, f)
                if os.access(fpath, os.X_OK):
                    return fpath

    return None


def compile_noahmp(source_dir, user_build_options=None):
    """Compile Noah-MP HRLDAS driver."""
    hrldas_dir = os.path.join(source_dir, "drivers", "hrldas")

    if not os.path.isdir(hrldas_dir):
        # Try repo subdirectory
        hrldas_dir = os.path.join(source_dir, "repo", "drivers", "hrldas")
    if not os.path.isdir(hrldas_dir):
        raise FileNotFoundError(f"HRLDAS driver directory not found under {source_dir}")

    # Check for user_build_options
    ubo_path = os.path.join(hrldas_dir, "user_build_options")
    if not os.path.isfile(ubo_path):
        # Create a default user_build_options for gfortran + NetCDF
        print("  Creating default user_build_options for gfortran...")
        ubo_content = create_default_build_options()
        with open(ubo_path, 'w') as f:
            f.write(ubo_content)

    # Also need utility and src Makefiles
    util_dir = os.path.join(os.path.dirname(os.path.dirname(hrldas_dir)), "utility")
    src_dir = os.path.join(os.path.dirname(os.path.dirname(hrldas_dir)), "src")

    print(f"  Compiling Noah-MP in {hrldas_dir}...")
    print(f"  Utility dir: {util_dir}")
    print(f"  Source dir: {src_dir}")

    # Clean first
    for d in [util_dir, src_dir, hrldas_dir]:
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "Makefile")):
            subprocess.run(["make", "clean"], cwd=d, capture_output=True)

    # Build order: utility -> src -> driver
    for build_dir, label in [(util_dir, "utility"), (src_dir, "src"), (hrldas_dir, "driver")]:
        if not os.path.isdir(build_dir):
            print(f"  WARNING: {label} directory not found: {build_dir}")
            continue
        if not os.path.isfile(os.path.join(build_dir, "Makefile")):
            print(f"  WARNING: No Makefile in {label} directory")
            continue

        print(f"  Building {label}...")
        result = subprocess.run(
            ["make", "-j4"],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=600
        )

        if result.returncode != 0:
            print(f"  BUILD FAILED ({label}):", file=sys.stderr)
            # Show last 30 lines of stderr
            lines = result.stderr.strip().split('\n')
            for line in lines[-30:]:
                print(f"    {line}", file=sys.stderr)
            raise RuntimeError(f"Compilation failed in {label}")

    binary = find_binary(os.path.dirname(os.path.dirname(hrldas_dir)))
    if binary is None:
        raise RuntimeError("Binary not found after compilation")

    print(f"  Binary compiled: {binary}")
    return binary


def create_default_build_options():
    """Create default user_build_options for gfortran."""
    # Detect NetCDF paths
    nf_fflags = ""
    nf_flibs = ""
    try:
        nf_fflags = subprocess.check_output(
            ["nf-config", "--fflags"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        nf_flibs = subprocess.check_output(
            ["nf-config", "--flibs"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Try pkg-config
        try:
            nf_fflags = subprocess.check_output(
                ["pkg-config", "--cflags", "netcdf-fortran"], text=True, stderr=subprocess.DEVNULL
            ).strip()
            nf_flibs = subprocess.check_output(
                ["pkg-config", "--libs", "netcdf-fortran"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (FileNotFoundError, subprocess.CalledProcessError):
            nf_fflags = "-I/usr/include"
            nf_flibs = "-lnetcdff -lnetcdf"

    return f"""# user_build_options for Noah-MP HRLDAS (auto-generated)
# Compiler
COMPILERF90 = gfortran
FREESOURCE  = -ffree-form -ffree-line-length-none
F90FLAGS    = -g -O2 -fbacktrace -fbounds-check -cpp
MODFLAG     = -J

# Linker
LDFLAGS     =
LIBS        =

# NetCDF
NETCDFMOD   = {nf_fflags}
NETCDFLIB   = {nf_flibs}

# Preprocessor
CPP         = cpp
CPPFLAGS    = -P -traditional-cpp

# MPI (disabled for single-point offline)
# COMPILERF90 = mpif90
# CPPFLAGS   += -DMPP_LAND
"""


def parse_namelist(namelist_path):
    """Parse key values from namelist.hrldas."""
    config = {}
    with open(namelist_path, 'r') as f:
        content = f.read()

    # Extract simple key=value pairs
    patterns = {
        "start_year": r"start_year\s*=\s*(\d+)",
        "start_month": r"start_month\s*=\s*(\d+)",
        "start_day": r"start_day\s*=\s*(\d+)",
        "start_hour": r"start_hour\s*=\s*(\d+)",
        "khour": r"khour\s*=\s*(\d+)",
        "kday": r"kday\s*=\s*(\d+)",
        "forcing_timestep": r"forcing_timestep\s*=\s*(\d+)",
        "noah_timestep": r"noah_timestep\s*=\s*(\d+)",
        "output_timestep": r"output_timestep\s*=\s*(\d+)",
        "NSOIL": r"NSOIL\s*=\s*(\d+)",
        "indir": r"indir\s*=\s*['\"]([^'\"]+)['\"]",
        "outdir": r"outdir\s*=\s*['\"]([^'\"]+)['\"]",
        "hrldas_setup_file": r"hrldas_setup_file\s*=\s*['\"]([^'\"]+)['\"]",
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, content, re.IGNORECASE)
        if m:
            config[key] = m.group(1)

    return config


def preflight_check(namelist_path, run_dir):
    """Verify all required files exist and namelist is consistent."""
    warnings = []
    errors = []

    config = parse_namelist(namelist_path)

    # Check NSOIL
    nsoil = int(config.get("NSOIL", 0))
    if nsoil < 1:
        errors.append("NSOIL not set or < 1 in namelist")

    # Check timesteps
    forcing_ts = int(config.get("forcing_timestep", 0))
    noah_ts = int(config.get("noah_timestep", 0))
    output_ts = int(config.get("output_timestep", 0))

    if forcing_ts <= 0:
        errors.append("forcing_timestep not set or <= 0")
    if noah_ts <= 0:
        errors.append("noah_timestep not set or <= 0")
    if forcing_ts > 0 and noah_ts > 0 and forcing_ts % noah_ts != 0:
        warnings.append(f"forcing_timestep ({forcing_ts}) not multiple of noah_timestep ({noah_ts})")
    if output_ts > 0 and noah_ts > 0 and output_ts % noah_ts != 0:
        warnings.append(f"output_timestep ({output_ts}) not multiple of noah_timestep ({noah_ts})")

    # Check simulation length
    khour = int(config.get("khour", 0))
    kday = int(config.get("kday", 0))
    if khour <= 0 and kday <= 0:
        errors.append("Neither khour nor kday is set in namelist")

    # Check setup file
    setup_file = config.get("hrldas_setup_file", "")
    if setup_file:
        setup_path = os.path.join(run_dir, setup_file) if not os.path.isabs(setup_file) else setup_file
        if not os.path.isfile(setup_path):
            errors.append(f"Setup file not found: {setup_path}")

    # Check forcing directory
    indir = config.get("indir", ".")
    indir_path = os.path.join(run_dir, indir) if not os.path.isabs(indir) else indir
    if not os.path.isdir(indir_path):
        errors.append(f"Forcing directory not found: {indir_path}")
    else:
        ldasin_files = [f for f in os.listdir(indir_path) if "LDASIN" in f]
        if len(ldasin_files) == 0:
            warnings.append(f"No LDASIN files found in {indir_path}")
        else:
            # Estimate expected number
            if khour > 0:
                expected = khour * 3600 // max(forcing_ts, 3600)
            elif kday > 0:
                expected = kday * 86400 // max(forcing_ts, 3600)
            else:
                expected = 0
            if expected > 0 and len(ldasin_files) < expected * 0.9:
                warnings.append(
                    f"Only {len(ldasin_files)} LDASIN files found, expected ~{expected}"
                )

    # Check parameter table
    table_path = os.path.join(run_dir, "NoahmpTable.TBL")
    if not os.path.isfile(table_path):
        warnings.append(f"NoahmpTable.TBL not found in {run_dir}")

    return errors, warnings, config


def execute(binary, run_dir, timeout=7200):
    """Run the Noah-MP binary."""
    print(f"  Running: {binary}")
    print(f"  CWD: {run_dir}")

    result = subprocess.run(
        [binary],
        cwd=run_dir,
        capture_output=True,
        text=True,
        timeout=timeout
    )

    return result


def validate_outputs(run_dir, config):
    """Validate output files were created."""
    errors = []

    outdir = config.get("outdir", ".")
    outdir_path = os.path.join(run_dir, outdir) if not os.path.isabs(outdir) else outdir

    if not os.path.isdir(outdir_path):
        errors.append(f"Output directory not found: {outdir_path}")
        return errors, []

    ldasout = [f for f in os.listdir(outdir_path) if "LDASOUT" in f]
    restart = [f for f in os.listdir(outdir_path) if "RESTART" in f]

    if len(ldasout) == 0:
        errors.append("No LDASOUT output files found")

    # Check first output is non-empty
    if ldasout:
        first = os.path.join(outdir_path, sorted(ldasout)[0])
        if os.path.getsize(first) < 1000:
            errors.append(f"First output file suspiciously small: {first} ({os.path.getsize(first)} bytes)")

    return errors, ldasout


def main():
    parser = argparse.ArgumentParser(
        description="Compile and run Noah-MP HRLDAS offline driver"
    )
    parser.add_argument("--source_dir", required=True, help="Path to Noah-MP source")
    parser.add_argument("--run_dir", required=True, help="Run directory")
    parser.add_argument("--namelist", required=True, help="Path to namelist.hrldas")
    parser.add_argument("--binary", default=None, help="Path to pre-compiled binary")
    parser.add_argument("--skip_compile", action="store_true", help="Skip compilation")
    parser.add_argument("--timeout", type=int, default=7200, help="Runtime timeout (seconds)")
    parser.add_argument("--output_json", default=None, help="Output result JSON path")

    args = parser.parse_args()

    print("=" * 60)
    print("Noah-MP Execution Wrapper")
    print("=" * 60)

    # Step 1: Validate inputs
    validate_inputs(args)

    # Step 2: Find or compile binary
    binary = args.binary
    if binary and os.path.isfile(binary):
        print(f"  Using provided binary: {binary}")
    elif not args.skip_compile:
        binary = find_binary(args.source_dir)
        if binary:
            print(f"  Found existing binary: {binary}")
        else:
            print("  No binary found, compiling...")
            try:
                binary = compile_noahmp(args.source_dir)
            except Exception as e:
                print(f"  COMPILATION FAILED: {e}", file=sys.stderr)
                result = {
                    "status": "compile_failed",
                    "error": str(e),
                    "binary_path": None,
                }
                if args.output_json:
                    with open(args.output_json, 'w') as f:
                        json.dump(result, f, indent=2)
                sys.exit(1)
    else:
        binary = find_binary(args.source_dir)

    if not binary or not os.path.isfile(binary):
        print("ERROR: No binary available", file=sys.stderr)
        sys.exit(1)

    # Step 3: Copy required files to run directory
    os.makedirs(args.run_dir, exist_ok=True)
    nml_dest = os.path.join(args.run_dir, "namelist.hrldas")
    if not os.path.isfile(nml_dest):
        shutil.copy2(args.namelist, nml_dest)

    # Copy parameter table if available
    src_base = args.source_dir
    if os.path.isdir(os.path.join(src_base, "repo")):
        src_base = os.path.join(src_base, "repo")
    param_table = os.path.join(src_base, "parameters", "NoahmpTable.TBL")
    if os.path.isfile(param_table):
        dest_table = os.path.join(args.run_dir, "NoahmpTable.TBL")
        if not os.path.isfile(dest_table):
            shutil.copy2(param_table, dest_table)

    # Step 4: Preflight check
    print("\n--- Preflight Check ---")
    pf_errors, pf_warnings, config = preflight_check(nml_dest, args.run_dir)
    for w in pf_warnings:
        print(f"  WARNING: {w}")
    if pf_errors:
        for e in pf_errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        print("  Preflight FAILED — aborting execution", file=sys.stderr)
        sys.exit(1)
    print("  Preflight: PASSED")

    # Step 5: Execute
    print("\n--- Executing Noah-MP ---")
    try:
        run_result = execute(binary, args.run_dir, args.timeout)
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after {args.timeout}s", file=sys.stderr)
        sys.exit(1)

    stdout_preview = run_result.stdout[:2000] if run_result.stdout else ""
    stderr_preview = run_result.stderr[:2000] if run_result.stderr else ""

    if run_result.returncode != 0:
        print(f"  Model exited with code {run_result.returncode}", file=sys.stderr)
        print(f"  STDERR: {stderr_preview}", file=sys.stderr)
    else:
        print(f"  Model completed successfully (exit code 0)")

    # Step 6: Validate outputs
    print("\n--- Output Validation ---")
    out_errors, ldasout_files = validate_outputs(args.run_dir, config)
    if out_errors:
        for e in out_errors:
            print(f"  ERROR: {e}", file=sys.stderr)
    print(f"  Output files: {len(ldasout_files)} LDASOUT files")

    # Summary
    result = {
        "status": "completed" if run_result.returncode == 0 else "failed",
        "binary_path": binary,
        "return_code": run_result.returncode,
        "n_output_files": len(ldasout_files),
        "stdout_preview": stdout_preview[:500],
        "stderr_preview": stderr_preview[:500],
    }

    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nResult written to {args.output_json}")

    print(f"\nFinal status: {result['status']}")
    return run_result.returncode


if __name__ == "__main__":
    sys.exit(main())
