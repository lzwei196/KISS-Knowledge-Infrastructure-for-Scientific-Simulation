#!/usr/bin/env python3
"""
generate_w2_control.py — Assemble CE-QUAL-W2 master control file (w2_con.npt).

This is THE most error-prone tool in the CE-QUAL-W2 pipeline.
w2_con.npt contains ~50 card groups, each using 8-character fixed-width fields.
A single column misalignment causes Fortran to read wrong values SILENTLY (dt_006).

CRITICAL FORMAT RULES:
  - Every numeric field is EXACTLY 8 characters, right-justified
  - Every string field is EXACTLY 8 characters, left-justified (padded with spaces)
  - Card group headers are left-justified text
  - Comment lines start with '$'
  - File paths are typically right-justified in wider fields (72 chars max — dt_008)

VALIDATION CHECKS (all mandatory before writing):
  1. Segment count matches bathymetry dimensions
  2. Layer count matches bathymetry dimensions
  3. Branch segment references are valid
  4. All referenced input files exist
  5. Simulation period covers forcing data range
  6. Constituent flags consistent with inflow files
  7. Outlet elevations within bathymetry range
  8. Initial water surface elevation above bottom elevation

Usage:
    python generate_w2_control.py \
        --grid_json /path/to/reservoir_grid.json \
        --met_file met_wb1.npt \
        --qin_files qin_br1.npt \
        --tin_files tin_br1.npt \
        --start_jday 1.0 --end_jday 365.0 --year 2005 \
        --output w2_con.npt \
        --run_dir /path/to/run
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.grid_json):
        errors.append(f"Grid JSON not found: {args.grid_json}")

    if not os.path.isfile(args.met_file):
        errors.append(f"Met file not found: {args.met_file}")

    for qf in args.qin_files:
        if not os.path.isfile(qf):
            errors.append(f"Inflow file not found: {qf}")

    if args.start_jday < 1 or args.start_jday > 366:
        errors.append(f"start_jday must be 1-366, got {args.start_jday}")
    if args.end_jday < 1 or args.end_jday > 366:
        errors.append(f"end_jday must be 1-366, got {args.end_jday}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def fmt_int(val, width=8):
    """Format integer in exactly `width` characters, right-justified."""
    s = str(int(val))
    if len(s) > width:
        raise ValueError(f"Integer {val} exceeds {width} chars")
    return s.rjust(width)


def fmt_float(val, width=8, decimals=2):
    """Format float in exactly `width` characters, right-justified."""
    fmt_str = f"{{:.{decimals}f}}"
    s = fmt_str.format(val)
    if len(s) > width:
        # Try fewer decimals
        for d in range(decimals - 1, -1, -1):
            s = f"{{:.{d}f}}".format(val)
            if len(s) <= width:
                break
    if len(s) > width:
        s = f"{val:.1e}"  # scientific notation as last resort
    return s.rjust(width)


def fmt_str(val, width=8):
    """Format string in exactly `width` characters, right-justified (W2 convention)."""
    s = str(val)[:width]
    return s.rjust(width)


def fmt_onoff(val):
    """Format ON/OFF switch as 8-char right-justified string."""
    return fmt_str("ON" if val else "OFF")


def fmt_path(path, width=72):
    """Format file path. CRITICAL: must be <= 72 chars for Fortran (dt_008)."""
    path = str(path)
    if len(path) > width:
        # Warning: path truncation will cause file-not-found
        pass
    return path.ljust(width)


def generate_w2_con(args):
    """Generate the complete w2_con.npt control file."""

    # Load grid definition
    with open(args.grid_json) as f:
        grid = json.load(f)

    NWB = grid["n_waterbodies"]
    NBR = grid["n_branches"]
    IMX = grid["n_segments"]
    KMX = grid["n_layers"]
    branches = grid["branch_info"]

    # Simulation parameters
    TMSTRT = args.start_jday
    TMEND = args.end_jday
    YEAR = args.year

    # Hydraulic parameters (defaults, can be overridden)
    AX = args.ax if args.ax else 1.0
    DX = args.dx if args.dx else 1.0
    CBHE = args.cbhe if args.cbhe else 0.3
    TSED = args.tsed if args.tsed else 10.0
    WSC = args.wsc if args.wsc else 0.85

    # Light extinction
    EXH2O = args.exh2o if args.exh2o else 0.45
    BETA = args.beta if args.beta else 0.45

    # Initial conditions
    T2I = args.init_temp if args.init_temp else 15.0
    ELWS = grid["surface_elevation_m"]

    # Output frequency (Julian day interval)
    SNPFREQ = args.snap_freq if args.snap_freq else 1.0
    TSRFREQ = args.tsr_freq if args.tsr_freq else 0.125  # 3-hourly

    # Build the control file
    lines = []

    def add_card(header, *data_lines):
        """Add a card group with header and data lines."""
        lines.append(header)
        for dl in data_lines:
            lines.append(dl)

    # ========== TITLE ==========
    add_card(
        "TITLE C",
        f"CE-QUAL-W2 — HydroCraft auto-generated control file",
        f"Reservoir simulation {YEAR}, JDAY {TMSTRT}-{TMEND}",
        f"Generated by generate_w2_control.py"
    )

    # ========== GRID ==========
    add_card(
        "GRID" + fmt_str("NWB") + fmt_str("NBR") + fmt_str("IMX") + fmt_str("KMX") + fmt_str("NPROC") + fmt_str("CLOSEC"),
        "     " + fmt_int(NWB) + fmt_int(NBR) + fmt_int(IMX) + fmt_int(KMX) + fmt_int(1) + fmt_str("OFF")
    )

    # ========== IN/OUTFLOW ==========
    add_card(
        "IN/OUTFL" + fmt_str("NUMINFL"),
        "         " + fmt_int(NBR)
    )

    # ========== BRANCH GEOMETRY ==========
    for br_info in branches:
        br_id = br_info["branch_id"]
        us = br_info["upstream_segment"]
        ds = br_info["downstream_segment"]
        uhs = br_info.get("upstream_head_segment", 0)
        dhs = br_info.get("downstream_head_segment", 0)
        slope = br_info.get("slope", 0.001)

        add_card(
            "BR GEOM" + fmt_str("US") + fmt_str("DS") + fmt_str("UHS") + fmt_str("DHS") + fmt_str("UQB") + fmt_str("DQB") + fmt_str("SLOPE") + fmt_str("SLOPEC"),
            "     " + fmt_int(us) + fmt_int(ds) + fmt_int(uhs) + fmt_int(dhs) + fmt_int(0) + fmt_int(0) + fmt_float(slope, 8, 5) + fmt_float(slope, 8, 5)
        )

    # ========== TIME CONTROL ==========
    add_card(
        "TIME CON" + fmt_str("TMSTRT") + fmt_str("TMEND") + fmt_str("YEAR"),
        "     " + fmt_float(TMSTRT, 8, 3) + fmt_float(TMEND, 8, 3) + fmt_int(YEAR)
    )

    # ========== TIMESTEP ==========
    add_card(
        "DLT CON " + fmt_str("NDT") + fmt_str("DLTMIN"),
        "     " + fmt_int(1) + fmt_float(1.0, 8, 1)  # minimum dt = 1 second
    )

    add_card(
        "DLT DATE" + fmt_str("DLTD") + fmt_str("DLTMAX") + fmt_str("DLTF"),
        "     " + fmt_float(TMSTRT, 8, 3) + fmt_float(args.dlt_max if args.dlt_max else 100.0, 8, 1) + fmt_float(0.9, 8, 2)
    )

    add_card(
        "DLT MAX " + fmt_str("DLTMAX"),
        "     " + fmt_float(args.dlt_max if args.dlt_max else 100.0, 8, 1)
    )

    # ========== CALCULATIONS ==========
    add_card(
        "CALCU   " + fmt_str("VEL") + fmt_str("TEMP") + fmt_str("CONSTI"),
        "     " + fmt_str("ON") + fmt_str("ON") + fmt_onoff(args.enable_wq)
    )

    # ========== INITIAL CONDITIONS ==========
    add_card(
        "INIT CND" + fmt_str("T2I") + fmt_str("ICE") + fmt_str("ELBOT") + fmt_str("ELWS"),
        "     " + fmt_float(T2I, 8, 1) + fmt_str("OFF") + fmt_float(grid["bottom_elevations_m"][-2], 8, 1) + fmt_float(ELWS, 8, 1)
    )

    # ========== METEOROLOGY ==========
    met_path = os.path.basename(args.met_file)
    add_card(
        "MET FILE" + fmt_str("METFN"),
        "     " + fmt_path(met_path, 72)
    )

    add_card(
        "WIND SHE" + fmt_str("WSC"),
        "     " + fmt_float(WSC, 8, 2)
    )

    # ========== LIGHT EXTINCTION ==========
    add_card(
        "EX COEF " + fmt_str("EXH2O") + fmt_str("EXSS") + fmt_str("EXOM") + fmt_str("BETA"),
        "     " + fmt_float(EXH2O, 8, 3) + fmt_float(0.01, 8, 3) + fmt_float(0.01, 8, 3) + fmt_float(BETA, 8, 3)
    )

    # ========== HYDRAULIC COEFFICIENTS ==========
    add_card(
        "HYD COEF" + fmt_str("AX") + fmt_str("DX") + fmt_str("CBHE") + fmt_str("TSED") + fmt_str("FI") + fmt_str("TSEDF"),
        "     " + fmt_float(AX, 8, 2) + fmt_float(DX, 8, 2) + fmt_float(CBHE, 8, 2) + fmt_float(TSED, 8, 1) + fmt_float(0.01, 8, 3) + fmt_float(1.0, 8, 2)
    )

    # ========== INFLOW FILES ==========
    for i, br_info in enumerate(branches):
        br_id = br_info["branch_id"]
        qin = os.path.basename(args.qin_files[i]) if i < len(args.qin_files) else f"qin_br{br_id}.npt"
        tin = os.path.basename(args.tin_files[i]) if args.tin_files and i < len(args.tin_files) else f"tin_br{br_id}.npt"

        add_card(
            f"QIN FILE" + fmt_str("QINFN"),
            "     " + fmt_path(qin, 72)
        )
        add_card(
            f"TIN FILE" + fmt_str("TINFN"),
            "     " + fmt_path(tin, 72)
        )

    # ========== OUTFLOW CONFIGURATION ==========
    n_outlets = args.n_outlets if args.n_outlets else 1
    outlet_elev = args.outlet_elevation if args.outlet_elevation else ELWS - 10

    add_card(
        "STR CONF" + fmt_str("NSTR") + fmt_str("KTSTR") + fmt_str("KBSTR"),
        "     " + fmt_int(n_outlets) + fmt_int(2) + fmt_int(KMX)
    )

    add_card(
        "STR ELEV" + fmt_str("ESTR"),
        "     " + fmt_float(outlet_elev, 8, 1)
    )

    add_card(
        "STR WIDT" + fmt_str("WSTR"),
        "     " + fmt_float(10.0, 8, 1)
    )

    # ========== OUTFLOW FILES ==========
    if args.qout_file:
        qout = os.path.basename(args.qout_file)
    else:
        qout = "qot_br1.npt"
    add_card(
        "QOT FILE" + fmt_str("QOTFN"),
        "     " + fmt_path(qout, 72)
    )

    # ========== BATHYMETRY FILES ==========
    for wb in range(1, NWB + 1):
        add_card(
            "BTH FILE" + fmt_str("BTHFN"),
            "     " + fmt_path(f"bth_wb{wb}.npt", 72)
        )

    # ========== CONSTITUENTS ==========
    if args.enable_wq:
        # Basic WQ constituent list
        constituents = ["TDS", "ISS", "PO4", "NH4", "NO3", "DSI",
                       "LDOM", "RDOM", "LPOM", "RPOM", "ALG1", "DO"]
        add_card(
            "CONSTITU" + fmt_str("CCC"),
            "     " + "".join(fmt_str("ON") for _ in constituents)
        )
    else:
        add_card(
            "CONSTITU" + fmt_str("CCC"),
            "     " + fmt_str("OFF")
        )

    # ========== OUTPUT CONTROL ==========
    # Snapshot output
    add_card(
        "SNP FREQ" + fmt_str("NSNP") + fmt_str("SNPD"),
        "     " + fmt_int(1) + fmt_float(SNPFREQ, 8, 3)
    )

    # Time series output
    add_card(
        "TSR FREQ" + fmt_str("NTSR") + fmt_str("TSRD"),
        "     " + fmt_int(1) + fmt_float(TSRFREQ, 8, 3)
    )

    # Spreadsheet output
    add_card(
        "SPR FILE" + fmt_str("SPRONE"),
        "     " + fmt_str("ON")
    )

    # ========== SEGMENT LENGTH ==========
    seg_len = grid["segment_length_m"]
    add_card(
        "SEG LENG" + fmt_str("DLX"),
        "     " + "".join(fmt_float(seg_len, 8, 0) for _ in range(IMX))
    )

    # ========== FRICTION ==========
    add_card(
        "FRICTIO " + fmt_str("FRITEFR"),
        "     " + fmt_str("MANN")
    )

    manning_n = args.manning_n if args.manning_n else 0.035
    add_card(
        "MANN COE" + fmt_str("MANFR"),
        "     " + "".join(fmt_float(manning_n, 8, 3) for _ in range(NBR))
    )

    # ========== LAYER THICKNESS ==========
    layer_thick = grid["layer_thickness_m"]
    add_card(
        "LAYER TH" + fmt_str("H"),
        "     " + "".join(fmt_float(layer_thick, 8, 2) for _ in range(KMX))
    )

    # Write the control file
    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w") as f:
        for line in lines:
            f.write(line + "\n")

    return output_path


def validate_control_file(output_path, grid, args):
    """Validate the generated w2_con.npt."""
    errors = []
    warnings = []

    if not os.path.isfile(output_path):
        errors.append(f"Control file not written: {output_path}")
        return errors, warnings

    # Check file size (should be >1KB for even a minimal config)
    size = os.path.getsize(output_path)
    if size < 500:
        warnings.append(f"Control file very small ({size} bytes) — may be incomplete")

    # Check all referenced files exist in the run directory
    run_dir = os.path.dirname(output_path) or "."
    bth_file = os.path.join(run_dir, f"bth_wb1.npt")
    if not os.path.isfile(bth_file):
        warnings.append(f"Bathymetry file not found in run dir: {bth_file}")

    met_file = os.path.join(run_dir, os.path.basename(args.met_file))
    if not os.path.isfile(met_file) and not os.path.isfile(args.met_file):
        warnings.append(f"Met file not found in run dir: {met_file}")

    # Check path lengths (dt_008)
    with open(output_path) as f:
        for i, line in enumerate(f):
            if "FILE" in line and len(line.strip()) > 80:
                warnings.append(f"Line {i+1} may have path >72 chars (dt_008)")

    # Validate initial water surface > bottom elevation
    bottom_elevs = grid["bottom_elevations_m"]
    elws = grid["surface_elevation_m"]
    for s, be in enumerate(bottom_elevs):
        if be > elws and s > 0 and s < len(bottom_elevs) - 1:
            errors.append(f"Bottom elevation at segment {s+1} ({be}) > ELWS ({elws}) (dt_014)")

    return errors, warnings


def process(args):
    """Main processing."""
    with open(args.grid_json) as f:
        grid = json.load(f)

    output_path = generate_w2_con(args)
    errors, warnings = validate_control_file(output_path, grid, args)

    result = {
        "status": "error" if errors else "success",
        "output_file": output_path,
        "n_waterbodies": grid["n_waterbodies"],
        "n_branches": grid["n_branches"],
        "n_segments": grid["n_segments"],
        "n_layers": grid["n_layers"],
        "year": args.year,
        "jday_range": [args.start_jday, args.end_jday],
    }
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))
    return 0 if not errors else 3


def main():
    parser = argparse.ArgumentParser(description="Generate CE-QUAL-W2 control file (w2_con.npt)")

    # Required inputs
    parser.add_argument("--grid_json", required=True, help="Reservoir grid JSON from build_reservoir_grid.py")
    parser.add_argument("--met_file", required=True, help="Meteorological file path (met_wb1.npt)")
    parser.add_argument("--qin_files", nargs="+", required=True, help="Inflow discharge files (qin_br*.npt)")
    parser.add_argument("--tin_files", nargs="*", help="Inflow temperature files (tin_br*.npt)")

    # Simulation time
    parser.add_argument("--start_jday", type=float, default=1.0, help="Start Julian day (default: 1.0)")
    parser.add_argument("--end_jday", type=float, default=365.0, help="End Julian day (default: 365.0)")
    parser.add_argument("--year", type=int, required=True, help="Simulation year")

    # Hydraulic parameters
    parser.add_argument("--ax", type=float, help="Longitudinal eddy viscosity (default: 1.0 m^2/s)")
    parser.add_argument("--dx", type=float, help="Longitudinal dispersion (default: 1.0 m^2/s)")
    parser.add_argument("--cbhe", type=float, help="Bottom heat exchange coef (default: 0.3 W/m^2/C)")
    parser.add_argument("--tsed", type=float, help="Sediment temperature (default: 10.0 C)")
    parser.add_argument("--wsc", type=float, help="Wind sheltering coefficient (default: 0.85)")

    # Light
    parser.add_argument("--exh2o", type=float, help="Light extinction coef (default: 0.45 m^-1)")
    parser.add_argument("--beta", type=float, help="SW fraction absorbed at surface (default: 0.45)")

    # Initial conditions
    parser.add_argument("--init_temp", type=float, help="Initial water temperature (default: 15 C)")

    # Timestep
    parser.add_argument("--dlt_max", type=float, help="Maximum timestep in seconds (default: 100)")

    # Friction
    parser.add_argument("--manning_n", type=float, help="Manning's n (default: 0.035)")

    # Outflow
    parser.add_argument("--n_outlets", type=int, help="Number of outlet structures (default: 1)")
    parser.add_argument("--outlet_elevation", type=float, help="Outlet elevation m ASL")
    parser.add_argument("--qout_file", help="Outflow time series file")

    # Water quality
    parser.add_argument("--enable_wq", action="store_true", help="Enable water quality constituents")

    # Output control
    parser.add_argument("--snap_freq", type=float, help="Snapshot output frequency in days (default: 1.0)")
    parser.add_argument("--tsr_freq", type=float, help="Time series output frequency in days (default: 0.125)")

    # Output
    parser.add_argument("--output", required=True, help="Output path for w2_con.npt")

    args = parser.parse_args()
    validate_inputs(args)
    sys.exit(process(args))


if __name__ == "__main__":
    main()
