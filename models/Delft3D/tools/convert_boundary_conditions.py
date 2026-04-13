#!/usr/bin/env python3
"""
convert_boundary_conditions.py — Tide/river/sea data → Delft3D boundary files

Converts tidal constituents, river discharge time series, and open-sea
conditions into Delft3D-compatible boundary condition files.

Supports:
  - D-Flow FM: .ext (external forcing spec) + .pli (locations) + .bc (data)
  - Delft3D-FLOW: .bnd (locations) + .bch/.bca (data)

Pipeline stage: s4 (boundary conditions)
Pattern: validate → process → validate

Unit conversions:
  - Water level: ensure MSL reference (not chart datum, not local datum)
  - Discharge: m³/s (standard SI)
  - Velocity: m/s
  - Salinity: PSU (≈ g/kg)
  - Temperature: °C
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# Major tidal constituents with periods in hours
TIDAL_CONSTITUENTS = {
    "M2":  12.4206,   # Principal lunar semidiurnal
    "S2":  12.0000,   # Principal solar semidiurnal
    "N2":  12.6583,   # Larger lunar elliptic
    "K2":  11.9672,   # Lunisolar semidiurnal
    "K1":  23.9345,   # Lunisolar diurnal
    "O1":  25.8193,   # Lunar diurnal
    "P1":  24.0659,   # Solar diurnal
    "Q1":  26.8684,   # Larger lunar elliptic diurnal
    "M4":   6.2103,   # Shallow water overtide
    "MS4":  6.1033,   # Shallow water compound
    "MN4":  6.2692,   # Shallow water compound
    "SA": 8765.82,    # Solar annual
    "SSA": 4382.91,   # Solar semi-annual
}

EXPECTED_AMPLITUDE_RANGE = (0, 10)  # meters
EXPECTED_DISCHARGE_RANGE = (0, 300000)  # m³/s (Amazon ~200000)


# ──────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────

def validate_inputs(args):
    """Validate input arguments and file existence."""
    errors = []

    if args.tide_csv and not os.path.isfile(args.tide_csv):
        errors.append(f"Tide CSV not found: {args.tide_csv}")

    if args.discharge_csv and not os.path.isfile(args.discharge_csv):
        errors.append(f"Discharge CSV not found: {args.discharge_csv}")

    if args.boundary_pli and not os.path.isfile(args.boundary_pli):
        errors.append(f"Boundary PLI not found: {args.boundary_pli}")

    if not args.tide_csv and not args.discharge_csv and not args.tide_constituents:
        errors.append("Must provide --tide_csv, --discharge_csv, or --tide_constituents")

    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        errors.append(f"Date format error (use YYYY-MM-DD): {e}")

    os.makedirs(args.output_dir, exist_ok=True)

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print("[validate_inputs] All inputs valid.")


def validate_outputs(output_dir):
    """Validate generated boundary files for consistency."""
    warnings = []

    bc_files = list(Path(output_dir).glob("*.bc"))
    bnd_files = list(Path(output_dir).glob("*.bnd"))
    ext_files = list(Path(output_dir).glob("*.ext"))

    if not bc_files and not bnd_files:
        warnings.append("No boundary condition files generated")

    for bc_file in bc_files:
        with open(bc_file) as f:
            content = f.read()
            if "waterlevelbnd" in content:
                # Check for reasonable amplitudes
                lines = content.split("\n")
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        try:
                            amp = float(parts[1])
                            if amp > 15.0:
                                warnings.append(
                                    f"Tidal amplitude {amp:.1f} m in {bc_file.name} — "
                                    "unrealistically large (Bay of Fundy max ~16 m)"
                                )
                        except (ValueError, IndexError):
                            pass

    if warnings:
        print("[validate_outputs] WARNINGS:")
        for w in warnings:
            print(f"  ⚠ {w}")
    else:
        print("[validate_outputs] Boundary conditions within expected ranges.")

    return warnings


# ──────────────────────────────────────────────────────────────────────
# PLI (polyline) reader/writer
# ──────────────────────────────────────────────────────────────────────

def read_pli(pli_file):
    """Read Delft3D polyline file (.pli) — boundary locations."""
    boundaries = []
    with open(pli_file) as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("*"):
            i += 1
            continue

        # Boundary name
        name = line
        i += 1
        if i >= len(lines):
            break

        # Number of points
        parts = lines[i].strip().split()
        n_points = int(parts[0])
        n_cols = int(parts[1]) if len(parts) > 1 else 2
        i += 1

        points = []
        for j in range(n_points):
            if i + j >= len(lines):
                break
            pline = lines[i + j].strip().split()
            x = float(pline[0])
            y = float(pline[1])
            label = pline[2] if len(pline) > 2 else f"{name}_{j+1:04d}"
            points.append({"x": x, "y": y, "label": label})

        i += n_points
        boundaries.append({"name": name, "points": points})

    print(f"  Read PLI: {len(boundaries)} boundary(ies)")
    for b in boundaries:
        print(f"    {b['name']}: {len(b['points'])} points")

    return boundaries


def write_pli(output_file, boundaries):
    """Write Delft3D polyline file (.pli)."""
    with open(output_file, "w") as f:
        for b in boundaries:
            f.write(f"{b['name']}\n")
            f.write(f"    {len(b['points'])}    2\n")
            for p in b["points"]:
                f.write(f"{p['x']:.9E}  {p['y']:.9E} {p['label']}\n")

    print(f"  Written: {output_file}")


# ──────────────────────────────────────────────────────────────────────
# D-Flow FM boundary files
# ──────────────────────────────────────────────────────────────────────

def write_bc_harmonic(output_file, boundaries, constituents):
    """Write .bc file with harmonic tidal boundary conditions."""
    with open(output_file, "w") as f:
        f.write("[General]\n")
        f.write("    fileVersion           = 1.01\n")
        f.write("    fileType              = boundConds\n\n")

        for bnd in boundaries:
            for point in bnd["points"]:
                f.write("[Forcing]\n")
                f.write(f"    Name                  = {point['label']}\n")
                f.write("    Function              = harmonic\n")
                f.write("    Quantity              = harmonic component\n")
                f.write("    Unit                  = minutes\n")
                f.write("    Quantity              = waterlevelbnd amplitude\n")
                f.write("    Unit                  = m\n")
                f.write("    Quantity              = waterlevelbnd phase\n")
                f.write("    Unit                  = deg\n")

                # Mean water level (A0)
                f.write(f"    0.0  0.0  0.0\n")

                # Tidal constituents
                for name, period_hr in TIDAL_CONSTITUENTS.items():
                    if name in constituents:
                        amp = constituents[name].get("amplitude", 0.0)
                        phase = constituents[name].get("phase", 0.0)
                        period_min = period_hr * 60.0
                        f.write(f"    {period_min:.2f}  {amp:.4f}  {phase:.2f}\n")

                f.write("\n")

    print(f"  Written: {output_file}")


def write_bc_timeseries(output_file, boundaries, time_seconds, values,
                        quantity="waterlevelbnd", unit="m"):
    """Write .bc file with time-series boundary conditions."""
    with open(output_file, "w") as f:
        f.write("[General]\n")
        f.write("    fileVersion           = 1.01\n")
        f.write("    fileType              = boundConds\n\n")

        for bnd in boundaries:
            for point in bnd["points"]:
                f.write("[Forcing]\n")
                f.write(f"    Name                  = {point['label']}\n")
                f.write("    Function              = timeseries\n")
                f.write("    Time-interpolation    = linear\n")
                f.write("    Quantity              = time\n")
                f.write("    Unit                  = seconds since reference\n")
                f.write(f"    Quantity              = {quantity}\n")
                f.write(f"    Unit                  = {unit}\n")

                for i in range(len(time_seconds)):
                    f.write(f"    {time_seconds[i]:.1f}  {values[i]:.6f}\n")

                f.write("\n")

    print(f"  Written: {output_file}")


def write_ext(output_file, boundary_entries):
    """Write .ext external forcing specification file for D-Flow FM."""
    with open(output_file, "w") as f:
        f.write("# External forcing file for D-Flow FM\n")
        f.write("# Generated by convert_boundary_conditions.py\n\n")

        for entry in boundary_entries:
            f.write("[Boundary]\n")
            f.write(f"    quantity              = {entry['quantity']}\n")
            f.write(f"    locationFile          = {entry['pli_file']}\n")
            f.write(f"    forcingFile           = {entry['bc_file']}\n")
            f.write("\n")

    print(f"  Written: {output_file}")


# ──────────────────────────────────────────────────────────────────────
# Delft3D-FLOW boundary files
# ──────────────────────────────────────────────────────────────────────

def write_bnd(output_file, boundary_defs):
    """Write .bnd boundary definition file for Delft3D-FLOW."""
    with open(output_file, "w") as f:
        for bdef in boundary_defs:
            name = bdef["name"]
            btype = bdef.get("type", "Z")  # Z=water level, C=current
            forcing = bdef.get("forcing", "H")  # H=harmonic, T=time series
            m1, n1 = bdef["start"]
            m2, n2 = bdef["end"]
            f.write(f"{name:20s} {btype} {forcing}  {m1:5d} {n1:5d} "
                    f"{m2:5d} {n2:5d}  0.00\n")

    print(f"  Written: {output_file}")


def write_bch(output_file, time_minutes, values, ref_date_str):
    """Write .bch time series boundary file for Delft3D-FLOW."""
    with open(output_file, "w") as f:
        f.write(f"table-name           'Boundary Section : 1'\n")
        f.write(f"contents             'regular   '\n")
        f.write(f"location             'Boundary Section : 1'\n")
        f.write(f"time-function        'non-equidistant'\n")
        f.write(f"reference-time       {ref_date_str}\n")
        f.write(f"time-unit            'minutes'\n")
        f.write(f"interpolation        'linear'\n")
        f.write(f"parameter 'time                '  unit '[min]'\n")
        f.write(f"parameter 'water elevation (z)  end A'  unit '[m]'\n")
        f.write(f"parameter 'water elevation (z)  end B'  unit '[m]'\n")
        f.write(f"records-in-table     {len(time_minutes)}\n")

        for i in range(len(time_minutes)):
            val = values[i] if np.ndim(values) == 1 else values[i]
            f.write(f" {time_minutes[i]:14.4f}  {val:.6f}  {val:.6f}\n")

    print(f"  Written: {output_file}")


# ──────────────────────────────────────────────────────────────────────
# Processing
# ──────────────────────────────────────────────────────────────────────

def process_tidal_constituents(args):
    """Generate harmonic boundary conditions from tidal constituent specification."""
    print("[process] Generating tidal boundary conditions")

    # Parse constituent string: "M2:1.5:30,S2:0.5:60,..."
    constituents = {}
    for part in args.tide_constituents.split(","):
        fields = part.strip().split(":")
        name = fields[0]
        amp = float(fields[1]) if len(fields) > 1 else 1.0
        phase = float(fields[2]) if len(fields) > 2 else 0.0
        constituents[name] = {"amplitude": amp, "phase": phase}
        print(f"  Constituent {name}: amp={amp:.3f} m, phase={phase:.1f}°")

    # Read or create boundary locations
    if args.boundary_pli:
        boundaries = read_pli(args.boundary_pli)
    else:
        # Create simple boundary at domain edge
        boundaries = [{
            "name": "OpenBoundary",
            "points": [
                {"x": 0.0, "y": 0.0, "label": "OB_0001"},
                {"x": 1.0, "y": 0.0, "label": "OB_0002"},
            ]
        }]

    # Write .bc file
    bc_file = os.path.join(args.output_dir, "tidal_boundary.bc")
    write_bc_harmonic(bc_file, boundaries, constituents)

    # Write .ext file
    pli_name = os.path.basename(args.boundary_pli) if args.boundary_pli else "boundary.pli"
    ext_entries = [{
        "quantity": "waterlevelbnd",
        "pli_file": pli_name,
        "bc_file": os.path.basename(bc_file),
    }]
    ext_file = os.path.join(args.output_dir, "boundary.ext")
    write_ext(ext_file, ext_entries)

    return boundaries


def process_tide_csv(args):
    """Generate boundary conditions from observed tide gauge CSV."""
    if pd is None:
        print("ERROR: pandas not installed", file=sys.stderr)
        sys.exit(1)

    print(f"[process] Reading tide CSV: {args.tide_csv}")
    df = pd.read_csv(args.tide_csv, parse_dates=[0])

    date_col = df.columns[0]
    value_col = df.columns[1]

    # Filter by date range
    df[date_col] = pd.to_datetime(df[date_col])
    t_start = datetime.strptime(args.start_date, "%Y-%m-%d")
    t_end = datetime.strptime(args.end_date, "%Y-%m-%d")
    mask = (df[date_col] >= t_start) & (df[date_col] <= t_end)
    df = df[mask]

    time_seconds = (df[date_col] - t_start).dt.total_seconds().values
    values = df[value_col].values

    print(f"  {len(values)} records, WL range: [{np.min(values):.3f}, {np.max(values):.3f}] m")

    # Read boundary locations
    if args.boundary_pli:
        boundaries = read_pli(args.boundary_pli)
    else:
        boundaries = [{
            "name": "TideBoundary",
            "points": [{"x": 0.0, "y": 0.0, "label": "TB_0001"}]
        }]

    # Write .bc file
    bc_file = os.path.join(args.output_dir, "tide_boundary.bc")
    write_bc_timeseries(bc_file, boundaries, time_seconds, values)

    # Write .ext file
    pli_name = os.path.basename(args.boundary_pli) if args.boundary_pli else "boundary.pli"
    ext_file = os.path.join(args.output_dir, "boundary.ext")
    write_ext(ext_file, [{
        "quantity": "waterlevelbnd",
        "pli_file": pli_name,
        "bc_file": os.path.basename(bc_file),
    }])

    return boundaries


def process_discharge_csv(args):
    """Generate discharge boundary conditions from river flow CSV."""
    if pd is None:
        print("ERROR: pandas not installed", file=sys.stderr)
        sys.exit(1)

    print(f"[process] Reading discharge CSV: {args.discharge_csv}")
    df = pd.read_csv(args.discharge_csv, parse_dates=[0])

    date_col = df.columns[0]
    q_col = df.columns[1]

    df[date_col] = pd.to_datetime(df[date_col])
    t_start = datetime.strptime(args.start_date, "%Y-%m-%d")
    t_end = datetime.strptime(args.end_date, "%Y-%m-%d")
    mask = (df[date_col] >= t_start) & (df[date_col] <= t_end)
    df = df[mask]

    time_seconds = (df[date_col] - t_start).dt.total_seconds().values
    discharge = df[q_col].values

    # Validate discharge
    if np.any(discharge < 0):
        print("  WARNING: Negative discharge values detected — clipping to 0")
        discharge = np.maximum(discharge, 0)

    print(f"  {len(discharge)} records, Q range: [{np.min(discharge):.1f}, "
          f"{np.max(discharge):.1f}] m³/s")

    # Write .bc file
    if args.boundary_pli:
        boundaries = read_pli(args.boundary_pli)
    else:
        boundaries = [{
            "name": "RiverInflow",
            "points": [{"x": 0.0, "y": 0.0, "label": "RI_0001"}]
        }]

    bc_file = os.path.join(args.output_dir, "discharge_boundary.bc")
    write_bc_timeseries(bc_file, boundaries, time_seconds, discharge,
                        quantity="dischargebnd", unit="m3/s")

    # Also write .dis file for Delft3D-FLOW compatibility
    dis_file = os.path.join(args.output_dir, "discharge.dis")
    ref_str = args.start_date.replace("-", "")
    time_minutes = time_seconds / 60.0

    with open(dis_file, "w") as f:
        f.write(f"table-name           'Discharge : 1'\n")
        f.write(f"contents             'regular   '\n")
        f.write(f"location             'River Inflow'\n")
        f.write(f"time-function        'non-equidistant'\n")
        f.write(f"reference-time       {ref_str}\n")
        f.write(f"time-unit            'minutes'\n")
        f.write(f"interpolation        'linear'\n")
        f.write(f"parameter 'time                '  unit '[min]'\n")
        f.write(f"parameter 'flux/discharge rate  '  unit '[m**3/s]'\n")
        f.write(f"records-in-table     {len(time_minutes)}\n")
        for i in range(len(time_minutes)):
            f.write(f" {time_minutes[i]:14.4f}  {discharge[i]:.4f}\n")

    print(f"  Written: {dis_file}")

    return boundaries


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert tide/discharge data to Delft3D boundary conditions"
    )
    parser.add_argument("--tide_csv", help="Observed tide gauge CSV (time, water_level)")
    parser.add_argument("--discharge_csv", help="River discharge CSV (time, Q_m3s)")
    parser.add_argument("--tide_constituents",
                        help="Harmonic constituents: M2:amp:phase,S2:amp:phase,...")
    parser.add_argument("--boundary_pli", help="Boundary polyline file (.pli)")
    parser.add_argument("--start_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--format", choices=["dflowfm", "flow2d3d"], default="dflowfm",
                        help="Output format (D-Flow FM or Delft3D-FLOW)")
    args = parser.parse_args()

    # Step 1: Validate
    validate_inputs(args)

    # Step 2: Process
    if args.tide_constituents:
        process_tidal_constituents(args)
    if args.tide_csv:
        process_tide_csv(args)
    if args.discharge_csv:
        process_discharge_csv(args)

    # Step 3: Validate outputs
    warnings = validate_outputs(args.output_dir)

    n_files = len(list(Path(args.output_dir).glob("*")))
    if warnings:
        print(f"\n[DONE] {n_files} boundary files generated with {len(warnings)} warning(s)")
    else:
        print(f"\n[DONE] {n_files} boundary files generated successfully")


if __name__ == "__main__":
    main()
