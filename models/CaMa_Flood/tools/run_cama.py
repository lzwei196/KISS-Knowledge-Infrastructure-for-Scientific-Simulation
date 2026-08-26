#!/usr/bin/env python3
"""
run_cama.py -- Execute CaMa-Flood binary with preflight checks and error handling.

This is Stage 3 of the CaMa-Flood pipeline.

Performs:
  1. Preflight verification (binary exists, map files exist, runoff files exist)
  2. Executes the CaMa-Flood run script
  3. Monitors for known error patterns (STOP 10, dimension mismatch, etc.)
  4. Reports success/failure with diagnostic triplet references

Usage:
    python run_cama.py \\
        --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh

    python run_cama.py \\
        --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh \\
        --dry_run

    python run_cama.py \\
        --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh \\
        --timeout 7200
"""

import argparse
import os
import re
import subprocess
import sys
import time

CAMA_ROOT = "KISSPATH_BINARIES/cmf_v420_pkg"
BINARY = os.path.join(CAMA_ROOT, "src", "MAIN_cmf")


def preflight_check(script_path):
    """Verify all prerequisites before running CaMa-Flood."""
    print("=" * 60)
    print("  PREFLIGHT CHECK")
    print("=" * 60)

    errors = []
    warnings = []

    # 1. Check binary exists and is executable
    if not os.path.isfile(BINARY):
        errors.append(f"CaMa-Flood binary not found: {BINARY}")
    elif not os.access(BINARY, os.X_OK):
        errors.append(f"CaMa-Flood binary not executable: {BINARY}")
    else:
        print(f"  OK    Binary: {BINARY}")

    # 2. Check run script exists
    if not os.path.isfile(script_path):
        errors.append(f"Run script not found: {script_path}")
        return errors, warnings  # Can't proceed without script
    else:
        print(f"  OK    Script: {script_path}")

    # 3. Parse run script for paths and validate them
    with open(script_path, "r") as f:
        script_content = f.read()

    # Check for macOS paths (legacy bug)
    if "/Volumes/" in script_content:
        errors.append(
            "Run script contains macOS paths (/Volumes/...). "
            "Fix: replace with KISSPATH_ROOT/... paths"
        )

    # Check for relative paths in namelist (STOP 10 risk)
    relative_patterns = [
        (r"CNEXTXY\s*=\s*'\.\.\/", "CNEXTXY uses relative path (../../) -- risk of STOP 10"),
        (r"CGRAREA\s*=\s*'\.\.\/", "CGRAREA uses relative path"),
        (r"CELEVTN\s*=\s*'\.\.\/", "CELEVTN uses relative path"),
        (r"CDIMINFO\s*=\s*'\.\.\/", "CDIMINFO uses relative path"),
        (r"CROFCDF\s*=\s*'\.\.\/", "CROFCDF uses relative path"),
    ]
    for pattern, msg in relative_patterns:
        if re.search(pattern, script_content):
            warnings.append(f"dt_cama_001: {msg}. Recommend absolute paths.")

    # Extract MAPDIR or map paths
    mapdir_match = re.search(r'MAPDIR="?([^"\n]+)"?', script_content)
    if mapdir_match:
        mapdir = mapdir_match.group(1).strip()
        if os.path.isdir(mapdir):
            essential_maps = ["nextxy.bin", "ctmare.bin", "elevtn.bin",
                              "nxtdst.bin", "rivlen.bin", "fldhgt.bin",
                              "rivwth_gwdlr.bin", "rivhgt.bin", "rivman.bin"]
            for mf in essential_maps:
                fpath = os.path.join(mapdir, mf)
                if not os.path.isfile(fpath):
                    errors.append(f"Missing map file: {fpath}")
            diminfo_files = [f for f in os.listdir(mapdir) if f.startswith("diminfo_")]
            if diminfo_files:
                print(f"  OK    Diminfo: {diminfo_files[0]}")
            else:
                errors.append(f"No diminfo file in {mapdir}")
            inpmat_files = [f for f in os.listdir(mapdir) if f.startswith("inpmat_")]
            if inpmat_files:
                print(f"  OK    Inpmat: {inpmat_files[0]}")
            else:
                errors.append(f"No inpmat file in {mapdir}")
            print(f"  OK    Map dir: {mapdir}")
        else:
            errors.append(f"Map directory not found: {mapdir}")

    # Extract runoff input directory
    indir_match = re.search(r'INDIR="?([^"\n]+)"?', script_content)
    if indir_match:
        indir = indir_match.group(1).strip()
        if os.path.isdir(indir):
            nc_files = [f for f in os.listdir(indir) if f.endswith(".nc")]
            if nc_files:
                print(f"  OK    Runoff dir: {indir} ({len(nc_files)} NC files)")
            else:
                errors.append(f"No NetCDF files in runoff directory: {indir}")
        else:
            errors.append(f"Runoff directory not found: {indir}")

    # Summary
    print()
    if errors:
        print(f"  PREFLIGHT FAILED: {len(errors)} error(s)")
        for e in errors:
            print(f"  ERROR: {e}")
    if warnings:
        print(f"  {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  WARN:  {w}")
    if not errors:
        print(f"  PREFLIGHT PASSED")

    return errors, warnings


def run_simulation(script_path, timeout=3600):
    """Execute the CaMa-Flood run script and monitor output."""
    print("\n" + "=" * 60)
    print("  EXECUTING CaMa-Flood")
    print("=" * 60)

    start_time = time.time()

    try:
        result = subprocess.run(
            ["bash", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(script_path),
        )
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"\n  TIMEOUT after {elapsed:.0f}s (limit: {timeout}s)")
        print("  The simulation may need more time. Try: --timeout {larger_value}")
        return False, "TIMEOUT"
    except Exception as e:
        print(f"\n  ERROR: {e}")
        return False, str(e)

    elapsed = time.time() - start_time

    # Print last N lines of output
    stdout_lines = result.stdout.strip().split("\n") if result.stdout else []
    stderr_lines = result.stderr.strip().split("\n") if result.stderr else []

    print(f"\n  Elapsed time: {elapsed:.1f}s")
    print(f"  Exit code: {result.returncode}")

    if stdout_lines:
        print(f"\n  --- Last 20 lines of output ---")
        for line in stdout_lines[-20:]:
            print(f"  {line}")

    # Check for known error patterns
    full_output = result.stdout + (result.stderr or "")
    diagnostics = check_error_patterns(full_output)

    if result.returncode != 0:
        print(f"\n  SIMULATION FAILED (exit code {result.returncode})")
        if stderr_lines:
            print(f"\n  --- STDERR ---")
            for line in stderr_lines[-10:]:
                print(f"  {line}")
        if diagnostics:
            print(f"\n  Matched diagnostic triplets:")
            for d in diagnostics:
                print(f"    {d}")
        return False, full_output

    # Verify output files were created
    print(f"\n  SIMULATION COMPLETED SUCCESSFULLY in {elapsed:.1f}s")
    return True, full_output


def check_error_patterns(output):
    """Check CaMa-Flood output for known error patterns."""
    diagnostics = []

    patterns = [
        ("STOP 10", "dt_cama_001: File open failure. Use absolute paths in namelist."),
        ("Dimension mismatch", "dt_cama_002/003: Grid dimension mismatch. Check diminfo and inpmat."),
        ("Error reading", "Map file read error. Verify all .bin files exist in map directory."),
        ("SIGFPE", "Floating point exception. Check for zero-area cells in ctmare.bin."),
        ("SIGSEGV", "Segmentation fault. Check map file sizes match diminfo dimensions."),
        ("NaN", "NaN values detected. Check runoff input data for invalid values."),
    ]

    for pattern, message in patterns:
        if pattern.lower() in output.lower():
            diagnostics.append(message)

    return diagnostics


def verify_outputs(script_path):
    """Check that expected output files were produced."""
    print("\n  --- Output Verification ---")

    with open(script_path, "r") as f:
        content = f.read()

    rdir_match = re.search(r'RDIR="?([^"\n]+)"?', content)
    if not rdir_match:
        print("  Cannot determine output directory from script")
        return

    rdir = rdir_match.group(1).strip()
    # Expand env variables
    rdir = os.path.expandvars(rdir)

    if not os.path.isdir(rdir):
        print(f"  WARNING: Output directory does not exist: {rdir}")
        return

    nc_files = sorted([f for f in os.listdir(rdir) if f.endswith(".nc") and f.startswith("o_")])
    restart_files = sorted([f for f in os.listdir(rdir) if f.startswith("restart")])

    if nc_files:
        print(f"  Output files ({len(nc_files)}):")
        for f in nc_files[:10]:
            size = os.path.getsize(os.path.join(rdir, f))
            print(f"    {f} ({size/1024:.1f} KB)")
        if len(nc_files) > 10:
            print(f"    ... and {len(nc_files) - 10} more")
    else:
        print("  WARNING: No output NetCDF files found")

    if restart_files:
        print(f"  Restart files ({len(restart_files)}):")
        for f in restart_files[:5]:
            print(f"    {f}")

    # Quick sanity check on output magnitudes
    try:
        import xarray as xr
        outflw_files = [f for f in nc_files if "outflw" in f]
        if outflw_files:
            last_outflw = os.path.join(rdir, outflw_files[-1])
            ds = xr.open_dataset(last_outflw)
            max_q = float(ds["outflw"].max().values)
            mean_q = float(ds["outflw"].mean().values)
            ds.close()
            print(f"\n  Discharge sanity check ({outflw_files[-1]}):")
            print(f"    Max:  {max_q:.1f} m3/s")
            print(f"    Mean: {mean_q:.1f} m3/s")
            if max_q < 1.0:
                print(f"    WARNING: Max discharge < 1 m3/s. Possible dt_cama_002/007 issue.")
            elif max_q > 1e6:
                print(f"    WARNING: Max discharge > 1e6 m3/s. Possible unit mismatch (dt_cama_009).")
    except Exception:
        pass

    print(f"\n  Output directory: {rdir}")


def main():
    parser = argparse.ArgumentParser(
        description="Execute CaMa-Flood simulation with error handling.",
    )
    parser.add_argument("--script", required=True,
                        help="Path to CaMa-Flood run script (*.sh)")
    parser.add_argument("--dry_run", action="store_true",
                        help="Run preflight checks only, do not execute")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600 = 1 hour)")
    parser.add_argument("--skip_preflight", action="store_true",
                        help="Skip preflight checks (not recommended)")

    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"  CaMa-Flood Execution Manager")
    print(f"  Script: {args.script}")
    print(f"{'='*60}")

    # Preflight
    if not args.skip_preflight:
        errors, warnings = preflight_check(args.script)
        if errors:
            print(f"\nAborting due to {len(errors)} preflight error(s).")
            print("Fix the errors above and re-run.")
            sys.exit(1)

    if args.dry_run:
        print("\n  DRY RUN: Preflight passed. Would execute now.")
        sys.exit(0)

    # Execute
    success, output = run_simulation(args.script, timeout=args.timeout)

    # Verify outputs
    if success:
        verify_outputs(args.script)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
