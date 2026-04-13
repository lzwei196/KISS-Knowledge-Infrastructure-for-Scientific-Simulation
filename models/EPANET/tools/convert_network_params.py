#!/usr/bin/env python3
"""
convert_network_params.py — Convert pipe/tank/valve parameters with unit validation.

Converts network physical parameters (pipe diameters, lengths, roughness,
tank geometry, valve settings) between unit systems and validates ranges
against engineering norms.

This tool is the "soil/parameter converter" equivalent for water distribution
systems — it maps physical infrastructure data to EPANET model parameters.

Usage:
    python convert_network_params.py \
        --pipes pipe_inventory.csv \
        --tanks tank_inventory.csv \
        --valves valve_inventory.csv \
        --source-units SI \
        --target-units US \
        --headloss H-W \
        --output params_report.csv

Pattern: validate → process → validate
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

# ── Conversion Constants ──────────────────────────────────────────────────────

CONVERSIONS = {
    "length": {
        ("m", "ft"): 3.28084,
        ("ft", "m"): 0.3048,
        ("km", "ft"): 3280.84,
        ("km", "m"): 1000.0,
        ("mi", "ft"): 5280.0,
        ("mi", "m"): 1609.34,
    },
    "pipe_diameter": {
        ("mm", "in"): 0.03937008,
        ("in", "mm"): 25.4,
        ("cm", "in"): 0.393701,
        ("cm", "mm"): 10.0,
        ("m", "in"): 39.3701,
        ("m", "mm"): 1000.0,
    },
    "tank_diameter": {
        ("m", "ft"): 3.28084,
        ("ft", "m"): 0.3048,
    },
    "elevation": {
        ("m", "ft"): 3.28084,
        ("ft", "m"): 0.3048,
    },
    "roughness_dw": {
        ("mm", "1e-3ft"): 0.00328084,   # mm to 10^-3 ft
        ("1e-3ft", "mm"): 304.8,         # 10^-3 ft to mm
    },
    "pressure": {
        ("m", "psi"): 1.42197,
        ("psi", "m"): 0.703070,
        ("kPa", "psi"): 0.145038,
        ("kPa", "m"): 0.101972,
        ("bar", "psi"): 14.5038,
        ("bar", "m"): 10.1972,
    },
    "flow": {
        ("m3/s", "LPS"): 1000.0,
        ("m3/s", "GPM"): 15850.3,
        ("LPS", "GPM"): 15.8503,
        ("GPM", "LPS"): 0.0630902,
        ("m3/h", "GPM"): 4.40287,
        ("m3/h", "LPS"): 0.277778,
    },
}

# ── Engineering Range Validation ──────────────────────────────────────────────

VALID_RANGES = {
    "pipe_diameter_in": (0.5, 120),        # inches
    "pipe_diameter_mm": (12, 3000),         # millimeters
    "pipe_length_ft": (1, 100000),          # feet
    "pipe_length_m": (0.3, 30000),          # meters
    "roughness_hw": (50, 160),              # Hazen-Williams C-factor
    "roughness_dw_mm": (0.0001, 10),        # Darcy-Weisbach roughness mm
    "roughness_dw_1e3ft": (0.000001, 0.03), # Darcy-Weisbach roughness 10^-3 ft
    "roughness_cm": (0.005, 0.030),         # Manning's n
    "tank_diameter_ft": (1, 500),           # feet
    "tank_diameter_m": (0.3, 150),          # meters
    "elevation_ft": (-500, 30000),          # feet
    "elevation_m": (-150, 9000),            # meters
    "minor_loss": (0, 50),                  # unitless K factor
}


def convert_value(value, param_type, from_unit, to_unit):
    """Convert a value between units. Returns converted value."""
    if from_unit == to_unit:
        return value
    key = (from_unit, to_unit)
    if param_type in CONVERSIONS and key in CONVERSIONS[param_type]:
        return value * CONVERSIONS[param_type][key]
    raise ValueError(f"No conversion for {param_type}: {from_unit} -> {to_unit}")


def validate_range(value, param_name, unit_suffix=""):
    """Check if a value falls within engineering norms."""
    range_key = f"{param_name}_{unit_suffix}" if unit_suffix else param_name
    if range_key in VALID_RANGES:
        lo, hi = VALID_RANGES[range_key]
        if value < lo or value > hi:
            return False, f"{range_key}={value:.4f} outside [{lo}, {hi}]"
    return True, ""


def validate_roughness_for_formula(roughness, headloss_formula, unit_system):
    """Validate roughness coefficient is appropriate for the headloss formula."""
    warnings = []

    if headloss_formula == "H-W":
        # Hazen-Williams C-factor: typically 50-160
        if roughness < 50 or roughness > 160:
            warnings.append(
                f"H-W roughness={roughness} outside typical range [50-160]. "
                f"Common mistake: using D-W roughness height with H-W formula."
            )
    elif headloss_formula == "D-W":
        if unit_system == "SI":
            # mm: typically 0.001 - 5
            if roughness > 10:
                warnings.append(
                    f"D-W roughness={roughness} mm seems too high. "
                    f"Common mistake: using H-W C-factor with D-W formula."
                )
        else:
            # 10^-3 ft: typically 0.001 - 0.03
            if roughness > 0.1:
                warnings.append(
                    f"D-W roughness={roughness} (10^-3 ft) seems too high."
                )
    elif headloss_formula == "C-M":
        # Manning's n: typically 0.005-0.030
        if roughness < 0.003 or roughness > 0.05:
            warnings.append(
                f"C-M roughness (Manning's n)={roughness} outside typical [0.005-0.030]."
            )

    return warnings


def process_pipes(pipes_csv, source_units, target_units, headloss):
    """Process pipe data with unit conversion and validation."""
    if not pipes_csv or not os.path.isfile(pipes_csv):
        return [], []

    results = []
    warnings = []

    # Determine units
    if source_units == "SI":
        src_len, src_diam = "m", "mm"
    else:
        src_len, src_diam = "ft", "in"

    if target_units == "SI":
        tgt_len, tgt_diam = "m", "mm"
    else:
        tgt_len, tgt_diam = "ft", "in"

    with open(pipes_csv, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("id", row.get("ID", ""))

            # Convert length
            length = float(row.get("length", row.get("Length", 0)))
            length_conv = convert_value(length, "length", src_len, tgt_len)
            ok, msg = validate_range(length_conv, "pipe_length", tgt_len)
            if not ok:
                warnings.append(f"Pipe {pid}: {msg}")

            # Convert diameter
            diam = float(row.get("diameter", row.get("Diam", 0)))
            diam_conv = convert_value(diam, "pipe_diameter", src_diam, tgt_diam)
            ok, msg = validate_range(diam_conv, "pipe_diameter", tgt_diam)
            if not ok:
                warnings.append(f"Pipe {pid}: {msg}")

            # Roughness (no spatial conversion for H-W/C-M, only for D-W)
            rough = float(row.get("roughness", row.get("Roughness", 100)))
            rough_warnings = validate_roughness_for_formula(
                rough, headloss, target_units
            )
            for w in rough_warnings:
                warnings.append(f"Pipe {pid}: {w}")

            # Minor loss (dimensionless)
            mloss = float(row.get("minor_loss", row.get("MinorLoss", 0)))
            ok, msg = validate_range(mloss, "minor_loss")
            if not ok:
                warnings.append(f"Pipe {pid}: {msg}")

            results.append({
                "id": pid,
                "node1": row.get("node1", row.get("Node1", "")),
                "node2": row.get("node2", row.get("Node2", "")),
                "length": round(length_conv, 2),
                "diameter": round(diam_conv, 2),
                "roughness": round(rough, 4),
                "minor_loss": round(mloss, 4),
                "status": row.get("status", row.get("Status", "Open")),
            })

    return results, warnings


def process_tanks(tanks_csv, source_units, target_units):
    """Process tank data with unit conversion and validation."""
    if not tanks_csv or not os.path.isfile(tanks_csv):
        return [], []

    results = []
    warnings = []

    if source_units == "SI":
        src_elev, src_diam = "m", "m"
    else:
        src_elev, src_diam = "ft", "ft"

    if target_units == "SI":
        tgt_elev, tgt_diam = "m", "m"
    else:
        tgt_elev, tgt_diam = "ft", "ft"

    with open(tanks_csv, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = row.get("id", row.get("ID", ""))

            elev = convert_value(
                float(row.get("elevation", row.get("Elev", 0))),
                "elevation", src_elev, tgt_elev
            )
            diam = convert_value(
                float(row.get("diameter", row.get("Diam", 0))),
                "tank_diameter", src_diam, tgt_diam
            )

            ok, msg = validate_range(diam, "tank_diameter", tgt_diam)
            if not ok:
                warnings.append(f"Tank {tid}: {msg}")

            init_lvl = float(row.get("init_level", row.get("InitLvl", 0)))
            min_lvl = float(row.get("min_level", row.get("MinLvl", 0)))
            max_lvl = float(row.get("max_level", row.get("MaxLvl", 0)))

            if min_lvl >= max_lvl:
                warnings.append(
                    f"Tank {tid}: min_level ({min_lvl}) >= max_level ({max_lvl})"
                )
            if init_lvl < min_lvl or init_lvl > max_lvl:
                warnings.append(
                    f"Tank {tid}: init_level ({init_lvl}) outside "
                    f"[{min_lvl}, {max_lvl}]"
                )

            results.append({
                "id": tid,
                "elevation": round(elev, 2),
                "init_level": round(init_lvl, 2),
                "min_level": round(min_lvl, 2),
                "max_level": round(max_lvl, 2),
                "diameter": round(diam, 2),
                "min_volume": float(row.get("min_volume", row.get("MinVol", 0))),
            })

    return results, warnings


def process_valves(valves_csv, source_units, target_units):
    """Process valve data with unit conversion and validation."""
    if not valves_csv or not os.path.isfile(valves_csv):
        return [], []

    results = []
    warnings = []

    if source_units == "SI":
        src_diam = "mm"
    else:
        src_diam = "in"

    if target_units == "SI":
        tgt_diam = "mm"
    else:
        tgt_diam = "in"

    with open(valves_csv, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vid = row.get("id", row.get("ID", ""))
            diam = convert_value(
                float(row.get("diameter", row.get("Diam", 0))),
                "pipe_diameter", src_diam, tgt_diam
            )
            vtype = row.get("type", row.get("Type", "PRV"))
            setting = float(row.get("setting", row.get("Setting", 0)))

            # Validate valve setting based on type
            if vtype in ("PRV", "PSV", "PBV"):
                if setting < 0:
                    warnings.append(f"Valve {vid}: negative pressure setting {setting}")
            elif vtype == "FCV":
                if setting < 0:
                    warnings.append(f"Valve {vid}: negative flow setting {setting}")

            results.append({
                "id": vid,
                "node1": row.get("node1", row.get("Node1", "")),
                "node2": row.get("node2", row.get("Node2", "")),
                "diameter": round(diam, 2),
                "type": vtype,
                "setting": setting,
                "minor_loss": float(row.get("minor_loss", row.get("MinorLoss", 0))),
            })

    return results, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert and validate network parameters for EPANET"
    )
    parser.add_argument("--pipes", help="Pipe inventory CSV")
    parser.add_argument("--tanks", help="Tank inventory CSV")
    parser.add_argument("--valves", help="Valve inventory CSV")
    parser.add_argument("--source-units", choices=["SI", "US"], default="SI",
                        help="Source data unit system")
    parser.add_argument("--target-units", choices=["SI", "US"], default="US",
                        help="Target EPANET unit system")
    parser.add_argument("--headloss", choices=["H-W", "D-W", "C-M"], default="H-W",
                        help="Headloss formula")
    parser.add_argument("--output", required=True, help="Output report file (JSON)")

    args = parser.parse_args()

    # ── Step 1: Validate inputs ───────────────────────────────────────────────
    print(f"[INFO] Converting parameters: {args.source_units} -> {args.target_units}")
    print(f"[INFO] Headloss formula: {args.headloss}")

    all_warnings = []

    # ── Step 2: Process each component type ───────────────────────────────────
    pipes, pipe_warnings = process_pipes(
        args.pipes, args.source_units, args.target_units, args.headloss
    )
    all_warnings.extend(pipe_warnings)

    tanks, tank_warnings = process_tanks(
        args.tanks, args.source_units, args.target_units
    )
    all_warnings.extend(tank_warnings)

    valves, valve_warnings = process_valves(
        args.valves, args.source_units, args.target_units
    )
    all_warnings.extend(valve_warnings)

    # ── Step 3: Write report ──────────────────────────────────────────────────
    report = {
        "source_units": args.source_units,
        "target_units": args.target_units,
        "headloss_formula": args.headloss,
        "pipes_count": len(pipes),
        "tanks_count": len(tanks),
        "valves_count": len(valves),
        "warnings_count": len(all_warnings),
        "warnings": all_warnings,
        "pipes": pipes,
        "tanks": tanks,
        "valves": valves,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    # ── Step 4: Validate and summarize ────────────────────────────────────────
    print(f"\n[SUMMARY]")
    print(f"  Pipes:    {len(pipes)}")
    print(f"  Tanks:    {len(tanks)}")
    print(f"  Valves:   {len(valves)}")
    print(f"  Warnings: {len(all_warnings)}")

    if all_warnings:
        print(f"\n[WARNINGS]")
        for w in all_warnings:
            print(f"  ⚠ {w}")

    print(f"\n[DONE] Report written: {args.output}")
    return 0 if not all_warnings else 1


if __name__ == "__main__":
    sys.exit(main())
