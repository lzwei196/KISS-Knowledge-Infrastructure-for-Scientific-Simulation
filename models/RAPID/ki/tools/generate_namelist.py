#!/usr/bin/env python3
"""
generate_namelist.py — Assemble RAPID Fortran namelist file.

The RAPID namelist (default: ./rapid_namelist) is a Fortran namelist file with
section /NL_namelist/ containing all configuration: runtime options, temporal
parameters, file paths, and domain sizes.

CRITICAL:
  - ALL time parameters are in SECONDS
  - Boolean values use Fortran syntax: .true. / .false.
  - String values must be quoted with single quotes
  - ZS_TauM must be divisible by ZS_dtM, ZS_TauR, and ZS_dtR
  - IS_riv_tot and IS_riv_bas must match the actual file contents

Usage:
  python generate_namelist.py \\
    --rapid_connect rapid_connect.csv \\
    --riv_bas_id riv_bas_id.csv \\
    --k_file k.csv --x_file x.csv \\
    --vlat_file Vlat.nc \\
    --qout_file Qout.nc \\
    --tau_m 2592000 --dt_m 86400 \\
    --tau_r 10800 --dt_r 900 \\
    --output rapid_namelist
"""

import argparse
import json
import os
import sys

import numpy as np


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Check all referenced files exist and temporal parameters are consistent."""
    errors = []
    warnings = []

    # File existence
    for fpath, label in [
        (args.rapid_connect, "rapid_connect"),
        (args.riv_bas_id, "riv_bas_id"),
        (args.k_file, "k_file"),
        (args.x_file, "x_file"),
    ]:
        if not os.path.isfile(fpath):
            errors.append(f"{label} not found: {fpath}")

    if args.vlat_file and not os.path.isfile(args.vlat_file):
        warnings.append(f"Vlat file not found: {args.vlat_file} — will write path anyway")

    # Temporal consistency
    if args.tau_m % args.dt_m != 0:
        errors.append(f"ZS_TauM ({args.tau_m}) not divisible by ZS_dtM ({args.dt_m})")
    if args.tau_r % args.dt_r != 0:
        errors.append(f"ZS_TauR ({args.tau_r}) not divisible by ZS_dtR ({args.dt_r})")
    if args.tau_m % args.tau_r != 0:
        errors.append(f"ZS_TauM ({args.tau_m}) not divisible by ZS_TauR ({args.tau_r})")

    # Sanity checks
    if args.dt_r < 60:
        warnings.append(f"ZS_dtR = {args.dt_r}s — very small sub-step, did you pass minutes?")
    if args.tau_m < 86400:
        warnings.append(f"ZS_TauM = {args.tau_m}s — less than 1 day, is this intentional?")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)


def validate_outputs(namelist_path):
    """Verify the generated namelist is syntactically valid."""
    warnings = []

    with open(namelist_path) as f:
        content = f.read()

    # Check section markers
    if "&NL_namelist" not in content:
        warnings.append("Missing &NL_namelist section start")
    if "/" not in content.split("&NL_namelist")[-1][:500] if "&NL_namelist" in content else True:
        warnings.append("Missing section terminator /")

    # Check for required variables
    required = ["IS_riv_tot", "IS_riv_bas", "rapid_connect_file",
                 "ZS_TauM", "ZS_dtM", "ZS_TauR", "ZS_dtR"]
    for var in required:
        if var not in content:
            warnings.append(f"Missing required variable: {var}")

    # Check file paths are quoted
    import re
    file_vars = re.findall(r"(\w+_file)\s*=\s*(.+)", content)
    for var, val in file_vars:
        val = val.strip().rstrip(",")
        if not (val.startswith("'") and val.endswith("'")):
            warnings.append(f"{var} value not quoted with single quotes: {val}")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    line_count = len(content.strip().split("\n"))
    print(f"Namelist has {line_count} lines")
    return {"path": namelist_path, "line_count": line_count, "warnings": warnings}


# ---------------------------------------------------------------------------
# Domain analysis
# ---------------------------------------------------------------------------

def count_lines(filepath):
    """Count non-empty, non-comment lines in a CSV file."""
    count = 0
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                count += 1
    return count


def get_max_upstream(connect_file):
    """Read rapid_connect to determine IS_max_up."""
    max_up = 0
    with open(connect_file) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 3:
                n_up = int(parts[2])
                max_up = max(max_up, n_up)
    return max_up


def count_connect_reaches(connect_file):
    """Count total reaches in rapid_connect."""
    return count_lines(connect_file)


# ---------------------------------------------------------------------------
# Namelist generation
# ---------------------------------------------------------------------------

def fmt_bool(val):
    """Format Python bool as Fortran logical."""
    return ".true." if val else ".false."


def fmt_str(val):
    """Format string with single quotes for Fortran namelist."""
    return f"'{val}'"


def generate_namelist(args):
    """Generate the RAPID namelist content."""
    # Determine domain sizes
    is_riv_tot = count_connect_reaches(args.rapid_connect)
    is_riv_bas = count_lines(args.riv_bas_id)
    is_max_up = get_max_upstream(args.rapid_connect)

    print(f"Domain: IS_riv_tot={is_riv_tot}, IS_riv_bas={is_riv_bas}, IS_max_up={is_max_up}")

    # Compute derived values
    is_m = int(args.tau_m / args.dt_m)
    is_rp_m = int(args.tau_m / args.tau_r)

    lines = []
    lines.append("&NL_namelist")
    lines.append("")
    lines.append("!--- Runtime options ---")
    lines.append(f"BS_opt_Qinit       = {fmt_bool(args.use_qinit)}")
    lines.append(f"BS_opt_Qfinal      = {fmt_bool(args.save_qfinal)}")
    lines.append(f"BS_opt_V           = {fmt_bool(args.compute_volume)}")
    lines.append(f"BS_opt_dam         = .false.")
    lines.append(f"BS_opt_for         = .false.")
    lines.append(f"BS_opt_hum         = .false.")
    lines.append(f"BS_opt_uq          = .false.")
    lines.append(f"IS_opt_routing     = 1")
    lines.append(f"IS_opt_run         = 1")
    lines.append(f"IS_opt_phi         = 1")
    lines.append("")
    lines.append("!--- Temporal parameters (ALL IN SECONDS) ---")
    lines.append(f"ZS_TauM            = {args.tau_m}")
    lines.append(f"ZS_dtM             = {args.dt_m}")
    lines.append(f"ZS_TauO            = 0")
    lines.append(f"ZS_dtO             = 0")
    lines.append(f"ZS_TauR            = {args.tau_r}")
    lines.append(f"ZS_dtR             = {args.dt_r}")
    lines.append(f"ZS_dtF             = {args.tau_r}")
    lines.append("")
    lines.append("!--- Domain sizes ---")
    lines.append(f"IS_riv_tot         = {is_riv_tot}")
    lines.append(f"IS_riv_bas         = {is_riv_bas}")
    lines.append(f"IS_max_up          = {is_max_up}")
    lines.append("")
    lines.append("!--- Input files ---")
    lines.append(f"rapid_connect_file = {fmt_str(os.path.abspath(args.rapid_connect))}")
    lines.append(f"riv_bas_id_file    = {fmt_str(os.path.abspath(args.riv_bas_id))}")
    lines.append(f"k_file             = {fmt_str(os.path.abspath(args.k_file))}")
    lines.append(f"x_file             = {fmt_str(os.path.abspath(args.x_file))}")
    lines.append(f"Vlat_file          = {fmt_str(os.path.abspath(args.vlat_file))}")
    lines.append("")
    lines.append("!--- Output files ---")
    lines.append(f"Qout_file          = {fmt_str(os.path.abspath(args.qout_file))}")

    if args.compute_volume and args.v_file:
        lines.append(f"V_file             = {fmt_str(os.path.abspath(args.v_file))}")

    if args.use_qinit and args.qinit_file:
        lines.append(f"Qinit_file         = {fmt_str(os.path.abspath(args.qinit_file))}")

    if args.save_qfinal and args.qfinal_file:
        lines.append(f"Qfinal_file        = {fmt_str(os.path.abspath(args.qfinal_file))}")

    lines.append("")
    lines.append("!--- Observation files (for optimization) ---")
    lines.append(f"IS_obs_tot         = 0")
    lines.append(f"IS_obs_use         = 0")
    lines.append(f"IS_strt_opt        = 1")
    lines.append("")
    lines.append("!--- Human-induced flows ---")
    lines.append(f"IS_hum_tot         = 0")
    lines.append(f"IS_hum_use         = 0")
    lines.append("")
    lines.append("!--- Forcing flows ---")
    lines.append(f"IS_for_tot         = 0")
    lines.append(f"IS_for_use         = 0")
    lines.append("")
    lines.append("!--- Dam model ---")
    lines.append(f"IS_dam_tot         = 0")
    lines.append(f"IS_dam_use         = 0")
    lines.append("")
    lines.append("/")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Main pipeline: validate → generate → write → validate."""
    content = generate_namelist(args)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(content)
    print(f"Wrote namelist to {args.output}")

    report = validate_outputs(args.output)
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Assemble RAPID Fortran namelist from component files")

    # Required file paths
    parser.add_argument("--rapid_connect", required=True)
    parser.add_argument("--riv_bas_id", required=True)
    parser.add_argument("--k_file", required=True)
    parser.add_argument("--x_file", required=True)
    parser.add_argument("--vlat_file", required=True)
    parser.add_argument("--qout_file", required=True)

    # Optional file paths
    parser.add_argument("--v_file", default=None)
    parser.add_argument("--qinit_file", default=None)
    parser.add_argument("--qfinal_file", default=None)

    # Temporal parameters (seconds)
    parser.add_argument("--tau_m", type=int, required=True,
                        help="Total simulation time in seconds")
    parser.add_argument("--dt_m", type=int, default=86400,
                        help="Main time step in seconds (default: 86400 = 1 day)")
    parser.add_argument("--tau_r", type=int, default=10800,
                        help="Routing period in seconds (default: 10800 = 3h)")
    parser.add_argument("--dt_r", type=int, default=900,
                        help="Routing sub-step in seconds (default: 900 = 15min)")

    # Options
    parser.add_argument("--use_qinit", action="store_true")
    parser.add_argument("--save_qfinal", action="store_true")
    parser.add_argument("--compute_volume", action="store_true")

    # Output
    parser.add_argument("--output", required=True, help="Output namelist path")
    args = parser.parse_args()

    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
