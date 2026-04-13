#!/usr/bin/env python3
"""
run_wrf.py - Execute WRF model (real.exe and wrf.exe) with preflight checks.

Handles the complete execution pipeline: preflight validation, real.exe
(vertical interpolation), and wrf.exe (model integration), with runtime
monitoring and output verification.

Pipeline stage: S4 (Vertical Interpolation) + S6 (Model Execution)
Pattern: validate -> process -> validate

Usage:
    python run_wrf.py \
        --wrf-dir /path/to/WRF/test/em_real/ \
        --namelist /path/to/namelist.input \
        --np 4 \
        --timeout 3600
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# Required lookup tables that must be present in the run directory
REQUIRED_TABLES = [
    "LANDUSE.TBL",
    "VEGPARM.TBL",
    "SOILPARM.TBL",
    "GENPARM.TBL",
]

# Radiation tables required based on physics options
RADIATION_TABLE_MAP = {
    1: ["RRTM_DATA"],           # RRTM LW
    4: ["RRTMG_LW_DATA", "RRTMG_SW_DATA"],  # RRTMG
    3: ["CAM_ABS_DATA", "CAM_AEROPT_DATA"],  # CAM
}

# Known fatal patterns in rsl.error/rsl.out files
FATAL_PATTERNS = [
    r"FATAL CALLED",
    r"cfl",
    r"NaN",
    r"Segmentation fault",
    r"SIGSEGV",
    r"forrtl: severe",
    r"ERROR.*time step",
    r"WOULD GO OFF TOP",
]

# Success pattern in rsl.out.0000 or wrf log
SUCCESS_PATTERN = r"wrf: SUCCESS COMPLETE WRF"


def parse_namelist(namelist_path: str) -> dict:
    """Parse a Fortran namelist file into a nested dict."""
    config = {}
    current_group = None

    with open(namelist_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("!"):
                continue
            if line.startswith("&"):
                current_group = line[1:].strip().lower()
                config[current_group] = {}
                continue
            if line == "/" or line.startswith("/"):
                current_group = None
                continue
            if current_group and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip().lower()
                value = value.strip().rstrip(",")
                config[current_group][key] = value

    return config


def get_namelist_int(config: dict, group: str, key: str, default: int = 0) -> int:
    """Extract integer value from parsed namelist."""
    val = config.get(group, {}).get(key, str(default))
    try:
        return int(val.split(",")[0].strip())
    except (ValueError, AttributeError):
        return default


def get_namelist_float(config: dict, group: str, key: str, default: float = 0.0) -> float:
    """Extract float value from parsed namelist."""
    val = config.get(group, {}).get(key, str(default))
    try:
        return float(val.split(",")[0].strip().rstrip("."))
    except (ValueError, AttributeError):
        return default


def validate_inputs(wrf_dir: str, namelist_path: str, np_procs: int) -> dict:
    """
    Preflight checks before running WRF.

    Checks:
    1. Executables exist (real.exe, wrf.exe)
    2. Namelist is valid and consistent
    3. Input files exist (met_em.* or wrfinput)
    4. Required lookup tables present
    5. CFL condition for time step vs grid spacing
    6. Physics scheme consistency (num_soil_layers vs sf_surface_physics)
    7. MPI availability if np > 1
    """
    errors = []
    warnings = []

    # Check WRF directory
    if not os.path.isdir(wrf_dir):
        errors.append(f"WRF run directory does not exist: {wrf_dir}")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Check executables
    for exe in ["real.exe", "wrf.exe"]:
        exe_path = os.path.join(wrf_dir, exe)
        if not os.path.isfile(exe_path):
            # Also check in main/ subdirectory or parent
            alt_paths = [
                os.path.join(wrf_dir, "..", "main", exe),
                os.path.join(wrf_dir, "..", "..", "main", exe),
            ]
            found = False
            for alt in alt_paths:
                if os.path.isfile(alt):
                    found = True
                    break
            if not found:
                errors.append(f"Executable not found: {exe}")

    # Check namelist
    if not os.path.isfile(namelist_path):
        errors.append(f"Namelist not found: {namelist_path}")
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    config = parse_namelist(namelist_path)

    # CFL check: dt <= 6 * dx_km
    dx = get_namelist_float(config, "domains", "dx", 0)
    dt = get_namelist_int(config, "domains", "time_step", 0)
    if dx > 0 and dt > 0:
        dx_km = dx / 1000.0
        cfl_limit = 6.0 * dx_km
        if dt > cfl_limit:
            errors.append(
                f"CFL VIOLATION: time_step={dt}s exceeds 6*dx_km={cfl_limit:.0f}s "
                f"(dx={dx:.0f}m). Reduce time_step or increase dx."
            )
        elif dt > 0.8 * cfl_limit:
            warnings.append(
                f"Time step {dt}s is close to CFL limit ({cfl_limit:.0f}s). "
                f"Consider reducing for stability."
            )

    # Physics consistency: num_soil_layers vs sf_surface_physics
    sf_sfc = get_namelist_int(config, "physics", "sf_surface_physics", 0)
    num_soil = get_namelist_int(config, "physics", "num_soil_layers", 4)
    soil_layer_map = {1: 5, 2: 4, 3: 6, 4: 4, 5: 10}  # LSM -> expected layers
    if sf_sfc in soil_layer_map:
        expected = soil_layer_map[sf_sfc]
        if num_soil != expected:
            errors.append(
                f"SOIL LAYER MISMATCH: sf_surface_physics={sf_sfc} requires "
                f"num_soil_layers={expected}, but got {num_soil}. "
                f"This will cause segfault or garbage results."
            )

    # Nesting ratio must be odd for real data
    max_dom = get_namelist_int(config, "domains", "max_dom", 1)
    if max_dom > 1:
        ratio_str = config.get("domains", {}).get("parent_grid_ratio", "1")
        for r in ratio_str.split(","):
            r = r.strip()
            if r and int(r) > 1 and int(r) % 2 == 0:
                errors.append(
                    f"NESTING ERROR: parent_grid_ratio={r} is even. "
                    f"Must be odd (3, 5, 7) for real-data cases."
                )

    # Cumulus at fine resolution
    cu = get_namelist_int(config, "physics", "cu_physics", 0)
    if cu > 0 and dx > 0 and dx < 5000:
        warnings.append(
            f"cu_physics={cu} is ON but dx={dx:.0f}m < 5000m. "
            f"Cumulus parameterization should be OFF (cu_physics=0) at convection-permitting resolution."
        )

    # Check required tables
    for tbl in REQUIRED_TABLES:
        tbl_path = os.path.join(wrf_dir, tbl)
        if not os.path.isfile(tbl_path):
            warnings.append(f"Missing lookup table: {tbl} (may be needed at runtime)")

    # Radiation tables
    ra_lw = get_namelist_int(config, "physics", "ra_lw_physics", 0)
    ra_sw = get_namelist_int(config, "physics", "ra_sw_physics", 0)
    for ra_opt in [ra_lw, ra_sw]:
        if ra_opt in RADIATION_TABLE_MAP:
            for tbl in RADIATION_TABLE_MAP[ra_opt]:
                tbl_path = os.path.join(wrf_dir, tbl)
                if not os.path.isfile(tbl_path):
                    warnings.append(f"Missing radiation table: {tbl} (needed for ra_physics={ra_opt})")

    # Check input files (met_em for real.exe, wrfinput for wrf.exe)
    met_files = list(Path(wrf_dir).glob("met_em.*"))
    wrfinput = os.path.join(wrf_dir, "wrfinput_d01")
    if len(met_files) == 0 and not os.path.isfile(wrfinput):
        warnings.append("No met_em.* or wrfinput_d01 found. Need met_em for real.exe or wrfinput for wrf.exe.")

    # MPI check
    if np_procs > 1:
        mpirun = shutil.which("mpirun") or shutil.which("mpiexec")
        if not mpirun:
            errors.append("MPI requested (np > 1) but mpirun/mpiexec not found in PATH")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings, "config": config}


def run_executable(wrf_dir: str, exe_name: str, np_procs: int, timeout: int) -> dict:
    """Run a WRF executable with MPI support and monitoring."""
    exe_path = os.path.join(wrf_dir, exe_name)
    if not os.path.isfile(exe_path):
        # Try to find it via symlink or parent
        for alt in [os.path.join(wrf_dir, "..", "main", exe_name)]:
            if os.path.isfile(alt):
                exe_path = alt
                break

    if not os.path.isfile(exe_path):
        return {"status": "error", "message": f"Executable not found: {exe_name}"}

    # Build command
    if np_procs > 1:
        mpirun = shutil.which("mpirun") or shutil.which("mpiexec")
        cmd = [mpirun, "-np", str(np_procs), exe_path]
    else:
        cmd = [exe_path]

    print(f"  Command: {' '.join(cmd)}")
    print(f"  Working dir: {wrf_dir}")
    print(f"  Timeout: {timeout}s")

    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            cwd=wrf_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
        )
        elapsed = time.time() - start_time
        stdout = proc.stdout[:5000] if proc.stdout else ""
        stderr = proc.stderr[:5000] if proc.stderr else ""

        # Check rsl.out.0000 and rsl.error.0000 for MPI runs
        rsl_out = ""
        rsl_err = ""
        rsl_out_file = os.path.join(wrf_dir, "rsl.out.0000")
        rsl_err_file = os.path.join(wrf_dir, "rsl.error.0000")
        if os.path.isfile(rsl_out_file):
            with open(rsl_out_file) as f:
                rsl_out = f.read()
        if os.path.isfile(rsl_err_file):
            with open(rsl_err_file) as f:
                rsl_err = f.read()

        # Combine output for analysis
        all_output = stdout + stderr + rsl_out + rsl_err

        # Check for success
        success = bool(re.search(SUCCESS_PATTERN, all_output))

        # Check for fatal errors
        fatal_errors = []
        for pattern in FATAL_PATTERNS:
            matches = re.findall(pattern, all_output, re.IGNORECASE)
            if matches:
                fatal_errors.extend(matches[:3])

        if proc.returncode != 0 and not success:
            return {
                "status": "error",
                "returncode": proc.returncode,
                "elapsed_s": elapsed,
                "fatal_errors": fatal_errors,
                "output_tail": all_output[-1000:],
            }

        return {
            "status": "success" if success else "unknown",
            "returncode": proc.returncode,
            "elapsed_s": elapsed,
            "success_detected": success,
            "fatal_errors": fatal_errors,
            "output_tail": all_output[-500:],
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "timeout_s": timeout,
            "message": f"{exe_name} exceeded {timeout}s timeout",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


def validate_outputs(wrf_dir: str, config: dict) -> dict:
    """Validate WRF output files after execution."""
    errors = []
    warnings = []

    max_dom = get_namelist_int(config, "domains", "max_dom", 1)

    # Check for wrfinput files (produced by real.exe)
    for d in range(1, max_dom + 1):
        wrfinput = os.path.join(wrf_dir, f"wrfinput_d{d:02d}")
        if os.path.isfile(wrfinput):
            size_mb = os.path.getsize(wrfinput) / 1e6
            print(f"  wrfinput_d{d:02d}: {size_mb:.1f} MB")
            if size_mb < 0.01:
                errors.append(f"wrfinput_d{d:02d} is suspiciously small ({size_mb:.4f} MB)")

    # Check for wrfbdy (domain 1 only, produced by real.exe)
    wrfbdy = os.path.join(wrf_dir, "wrfbdy_d01")
    if os.path.isfile(wrfbdy):
        size_mb = os.path.getsize(wrfbdy) / 1e6
        print(f"  wrfbdy_d01: {size_mb:.1f} MB")

    # Check for wrfout files (produced by wrf.exe)
    wrfout_files = sorted(Path(wrf_dir).glob("wrfout_d*"))
    if wrfout_files:
        print(f"  Found {len(wrfout_files)} wrfout files")
        for wf in wrfout_files[:5]:
            size_mb = wf.stat().st_size / 1e6
            print(f"    {wf.name}: {size_mb:.1f} MB")
            if size_mb < 0.01:
                errors.append(f"{wf.name} is suspiciously small")
    else:
        warnings.append("No wrfout files found (wrf.exe may not have been run yet)")

    # Check rsl.error.0000 for warnings
    rsl_err_file = os.path.join(wrf_dir, "rsl.error.0000")
    if os.path.isfile(rsl_err_file):
        with open(rsl_err_file) as f:
            err_content = f.read()
        if "NaN" in err_content:
            errors.append("NaN detected in rsl.error.0000 - model produced invalid values")
        if "cfl" in err_content.lower():
            warnings.append("CFL warning detected - consider reducing time step")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "n_wrfout": len(wrfout_files),
    }


def main():
    parser = argparse.ArgumentParser(description="Execute WRF real.exe and wrf.exe with checks")
    parser.add_argument("--wrf-dir", required=True, help="WRF run/test directory")
    parser.add_argument("--namelist", default=None, help="Path to namelist.input")
    parser.add_argument("--np", type=int, default=1, help="Number of MPI processes")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout per executable (seconds)")
    parser.add_argument("--skip-real", action="store_true", help="Skip real.exe (use existing wrfinput)")
    parser.add_argument("--skip-wrf", action="store_true", help="Skip wrf.exe (only run real.exe)")
    args = parser.parse_args()

    wrf_dir = os.path.abspath(args.wrf_dir)
    namelist = args.namelist or os.path.join(wrf_dir, "namelist.input")

    print("=" * 60)
    print("WRF Execution Wrapper")
    print("=" * 60)
    print(f"  WRF dir:   {wrf_dir}")
    print(f"  Namelist:  {namelist}")
    print(f"  MPI procs: {args.np}")
    print(f"  Timeout:   {args.timeout}s")

    # Step 1: Preflight validation
    print("\n[1/4] Preflight checks...")
    v = validate_inputs(wrf_dir, namelist, args.np)
    for w in v["warnings"]:
        print(f"  WARNING: {w}")
    if not v["valid"]:
        for e in v["errors"]:
            print(f"  ERROR: {e}")
        sys.exit(1)
    print("  Preflight checks passed")

    config = v.get("config", {})

    # Step 2: Run real.exe
    if not args.skip_real:
        print("\n[2/4] Running real.exe...")
        real_result = run_executable(wrf_dir, "real.exe", args.np, args.timeout)
        print(f"  Status: {real_result['status']}")
        if real_result["status"] not in ("success", "unknown"):
            print(f"  real.exe failed: {json.dumps(real_result, indent=2)}")
            if not args.skip_wrf:
                print("  Aborting - real.exe must succeed before wrf.exe")
                sys.exit(1)
    else:
        print("\n[2/4] Skipping real.exe (--skip-real)")

    # Step 3: Run wrf.exe
    if not args.skip_wrf:
        print("\n[3/4] Running wrf.exe...")
        wrf_result = run_executable(wrf_dir, "wrf.exe", args.np, args.timeout)
        print(f"  Status: {wrf_result['status']}")
        if wrf_result["status"] not in ("success", "unknown"):
            print(f"  wrf.exe failed: {json.dumps(wrf_result, indent=2)}")
    else:
        print("\n[3/4] Skipping wrf.exe (--skip-wrf)")
        wrf_result = {"status": "skipped"}

    # Step 4: Validate outputs
    print("\n[4/4] Validating outputs...")
    vo = validate_outputs(wrf_dir, config)
    for w in vo["warnings"]:
        print(f"  WARNING: {w}")
    if not vo["valid"]:
        for e in vo["errors"]:
            print(f"  ERROR: {e}")

    final = {
        "real": real_result if not args.skip_real else {"status": "skipped"},
        "wrf": wrf_result,
        "output_validation": vo,
    }

    print("\nDONE")
    print(json.dumps(final, indent=2, default=str))


if __name__ == "__main__":
    main()
