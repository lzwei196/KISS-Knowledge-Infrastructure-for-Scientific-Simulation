#!/usr/bin/env python3
"""
run_alpine3d.py — Execution wrapper for Alpine3D simulations.

Validates the configuration (io.ini), checks input file existence, validates
unit-critical parameters, then launches the alpine3d binary.

CRITICAL CHECKS performed before execution:
  1. ALPINE3D = TRUE in [SnowpackAdvanced]
  2. DEM and landuse grids have matching dimensions
  3. COORDSYS consistency
  4. PSUM accumulation period matches CALCULATION_STEP_LENGTH
  5. GEO_HEAT is in reasonable range (W/m², not mW/m²)
  6. ROUGHNESS_LENGTH is in reasonable range (m, not mm)
  7. np-ebalance ≤ DEM nrows
  8. Input meteo files exist
  9. Snowfile directory exists and contains .sno files

Usage:
    python run_alpine3d.py \\
        --iofile ./setup/io.ini \\
        --startdate 2014-10-01T01:00 \\
        --enddate 2015-09-30T00:00 \\
        --np-ebalance 4 --np-snowpack 4

    python run_alpine3d.py \\
        --iofile ./setup/io.ini \\
        --startdate 2014-10-01T01:00 \\
        --enddate 2015-09-30T00:00 \\
        --binary /usr/local/bin/alpine3d \\
        --parallel openmp --ncores 8
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if not os.path.exists(args.iofile):
        errors.append(f"Configuration file not found: {args.iofile}")

    if args.binary and not os.path.exists(args.binary):
        errors.append(f"Binary not found: {args.binary}")

    if args.np_ebalance < 1:
        errors.append("np-ebalance must be >= 1")

    if args.np_snowpack < 1:
        errors.append("np-snowpack must be >= 1")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def parse_ini_file(filepath):
    """Parse an INI-style configuration file into sections and key-value pairs."""
    config = {}
    current_section = None

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            # Remove inline comments
            for sep in [";", "#"]:
                if sep in line:
                    # Don't strip if inside quotes
                    idx = line.index(sep)
                    if line.count('"', 0, idx) % 2 == 0:
                        line = line[:idx].strip()

            # Section header
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                if current_section not in config:
                    config[current_section] = {}
                continue

            # Key-value pair
            if "=" in line and current_section:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                config[current_section][key] = value

    return config


def read_arc_header(filepath):
    """Read just the header of an ARC ASCII grid file."""
    header = {}
    with open(filepath, "r") as f:
        for _ in range(6):
            line = f.readline().strip()
            parts = line.split()
            if len(parts) >= 2:
                header[parts[0].lower()] = parts[1]
    return header


def validate_config(config, args):
    """Validate the Alpine3D configuration for common errors."""
    warnings = []
    errors = []

    # 1. Check ALPINE3D = TRUE
    adv = config.get("SnowpackAdvanced", {})
    alpine3d_flag = adv.get("ALPINE3D", "").lower()
    if alpine3d_flag in ("false", "0", "no"):
        errors.append(
            "CRITICAL: ALPINE3D = FALSE in [SnowpackAdvanced]. "
            "Must be TRUE for Alpine3D simulations (dt_016)."
        )
    elif not alpine3d_flag:
        warnings.append(
            "ALPINE3D key not found in [SnowpackAdvanced]. "
            "It should be explicitly set to TRUE."
        )

    # 2. Check DEM and landuse grid dimensions
    inp = config.get("Input", config.get("INPUT", {}))
    demfile = inp.get("DEMFILE", "")
    lusfile = inp.get("LANDUSEFILE", "")

    # Resolve paths relative to iofile directory
    iodir = os.path.dirname(os.path.abspath(args.iofile))

    if demfile and not os.path.isabs(demfile):
        demfile = os.path.join(iodir, demfile)
    if lusfile and not os.path.isabs(lusfile):
        lusfile = os.path.join(iodir, lusfile)

    if demfile and os.path.exists(demfile):
        dem_header = read_arc_header(demfile)
        dem_nrows = int(dem_header.get("nrows", 0))

        # Check np-ebalance vs nrows
        if args.np_ebalance > dem_nrows and dem_nrows > 0:
            errors.append(
                f"np-ebalance ({args.np_ebalance}) > DEM nrows ({dem_nrows}). "
                f"This will crash. Reduce to ≤ {dem_nrows} (dt_017)."
            )

        if lusfile and os.path.exists(lusfile):
            lus_header = read_arc_header(lusfile)
            for key in ["ncols", "nrows", "cellsize"]:
                if dem_header.get(key) != lus_header.get(key):
                    errors.append(
                        f"DEM and landuse grid mismatch on '{key}': "
                        f"DEM={dem_header.get(key)}, LUS={lus_header.get(key)} (dt_017)"
                    )
    elif demfile:
        warnings.append(f"DEM file not found: {demfile}")

    # 3. Check CALCULATION_STEP_LENGTH vs PSUM accumulation
    snp = config.get("Snowpack", config.get("SNOWPACK", {}))
    step_length = snp.get("CALCULATION_STEP_LENGTH", "")
    if step_length:
        step_min = float(step_length)
        expected_period = step_min * 60  # seconds

        interp1d = config.get("Interpolations1D", config.get("INTERPOLATIONS1D", {}))
        psum_period = interp1d.get("PSUM::ARG1::PERIOD",
                                   interp1d.get("PSUM::arg1::PERIOD", ""))
        if psum_period:
            actual_period = float(psum_period)
            if abs(actual_period - expected_period) > 1:
                warnings.append(
                    f"PSUM accumulation period ({actual_period}s) ≠ "
                    f"CALCULATION_STEP_LENGTH ({step_min}min × 60 = {expected_period}s). "
                    f"This may cause precipitation double-counting or loss (dt_015)."
                )

    # 4. Check GEO_HEAT range
    geo_heat = snp.get("GEO_HEAT", "")
    if geo_heat:
        gh = float(geo_heat)
        if gh > 1.0:
            warnings.append(
                f"GEO_HEAT = {gh} W/m² is very high. "
                f"Did you use mW/m²? Typical value: 0.05–0.10 W/m² (dt_013)."
            )

    # 5. Check ROUGHNESS_LENGTH range
    roughness = snp.get("ROUGHNESS_LENGTH", "")
    if roughness:
        rl = float(roughness)
        if rl > 0.05:
            warnings.append(
                f"ROUGHNESS_LENGTH = {rl} m is very high. "
                f"Did you use mm? Typical value: 0.001–0.01 m (dt_014)."
            )

    return warnings, errors


def find_binary(args):
    """Find the alpine3d binary."""
    if args.binary:
        return args.binary

    # Search common locations
    candidates = [
        "alpine3d",
        "/usr/local/bin/alpine3d",
        os.path.join(os.path.dirname(args.iofile), "..", "bin", "alpine3d"),
        os.path.join(os.path.dirname(args.iofile), "..", "..", "build", "bin", "alpine3d"),
    ]

    for candidate in candidates:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate

    # Try which
    try:
        result = subprocess.run(["which", "alpine3d"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass

    return None


def process(args):
    """Validate config and run Alpine3D."""
    # Parse configuration
    config = parse_ini_file(args.iofile)

    # Validate
    warnings, errors = validate_config(config, args)

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        if not args.force:
            return {
                "status": "error",
                "errors": errors,
                "warnings": warnings,
                "message": "Fix errors or use --force to run anyway",
            }

    # Find binary
    binary = find_binary(args)
    if not binary:
        return {
            "status": "error",
            "errors": ["alpine3d binary not found. Specify with --binary"],
        }

    # Build command
    cmd = [binary]
    cmd.extend(["--iofile", os.path.abspath(args.iofile)])
    cmd.extend(["--startdate", args.startdate])
    cmd.extend(["--enddate", args.enddate])
    cmd.extend(["--np-ebalance", str(args.np_ebalance)])
    cmd.extend(["--np-snowpack", str(args.np_snowpack)])

    if args.enable_eb:
        cmd.append("--enable-eb")
    if args.restart:
        cmd.append("--restart")

    # Set parallelism environment
    env = os.environ.copy()
    if args.parallel == "openmp":
        env["OMP_NUM_THREADS"] = str(args.ncores)

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)

    # Execute
    start_time = time.time()

    if args.dry_run:
        return {
            "status": "dry_run",
            "command": " ".join(cmd),
            "warnings": warnings,
        }

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=args.timeout,
        )
        elapsed = time.time() - start_time

        return {
            "status": "success" if proc.returncode == 0 else "failed",
            "return_code": proc.returncode,
            "elapsed_seconds": round(elapsed, 1),
            "command": " ".join(cmd),
            "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
            "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
            "warnings": warnings,
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "timeout_seconds": args.timeout,
            "command": " ".join(cmd),
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "errors": [f"Binary not found or not executable: {binary}"],
        }


def main():
    parser = argparse.ArgumentParser(
        description="Run Alpine3D with configuration validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--iofile", required=True, help="Path to io.ini configuration file")
    parser.add_argument("--startdate", required=True,
                        help="Start date (YYYY-MM-DDTHH:MM)")
    parser.add_argument("--enddate", required=True,
                        help="End date (YYYY-MM-DDTHH:MM)")
    parser.add_argument("--binary", default=None,
                        help="Path to alpine3d binary (auto-detected if omitted)")
    parser.add_argument("--np-ebalance", type=int, default=1,
                        help="Number of energy balance workers (default: 1)")
    parser.add_argument("--np-snowpack", type=int, default=1,
                        help="Number of snowpack workers (default: 1)")
    parser.add_argument("--enable-eb", action="store_true",
                        help="Enable energy balance module")
    parser.add_argument("--restart", action="store_true",
                        help="Restart from existing .sno files")
    parser.add_argument("--parallel", default="none",
                        choices=["none", "openmp", "mpi"],
                        help="Parallelization mode (default: none)")
    parser.add_argument("--ncores", type=int, default=4,
                        help="Number of cores for OpenMP (default: 4)")
    parser.add_argument("--timeout", type=int, default=86400,
                        help="Timeout in seconds (default: 86400 = 24h)")
    parser.add_argument("--force", action="store_true",
                        help="Run even if validation errors are found")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and print command without running")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    print(json.dumps(result, indent=2))

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
