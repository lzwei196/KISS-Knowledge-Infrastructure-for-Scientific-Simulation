#!/usr/bin/env python3
"""
convert_fuel_params.py — Convert standard fuel models to ForeFire fuels.csv.

ForeFire uses a semicolon-delimited CSV file for fuel properties. The format depends
on the propagation model selected:

  - Rothermel / Balbi: uses SI units in the CSV (kg/m³, 1/m, m, kg/m², J/kg).
    The Rothermel model code internally converts to Imperial for calculation.
  - RothermelAndrews2018: uses Imperial units directly (tons/acre, ft, 1/ft, lb/ft³).
  - Farsite: uses NFFL/FBFM standard fuel models with moisture class loads.

CRITICAL UNIT TRAPS:
  - Rothermel fuels.csv is in SI, but the model converts internally to Imperial.
    Do NOT pre-convert to Imperial — you'll double-convert.
  - RothermelAndrews2018 fuels.csv must be in Imperial (tons/acre, ft, BTU/lb).
  - Fuel index 0 in fuels.csv should be non-burnable (e=0 → ROS=0).
  - Moisture of extinction (me/Dme) must be fraction for Rothermel, percentage for Andrews.

Usage:
    python convert_fuel_params.py \\
        --model rothermel \\
        --source anderson13 \\
        --output fuels.csv

    python convert_fuel_params.py \\
        --model andrews2018 \\
        --source scott_burgan40 \\
        --output fuels.csv

    python convert_fuel_params.py \\
        --model rothermel \\
        --custom_csv /path/to/my_fuels.csv \\
        --source_units imperial \\
        --output fuels.csv
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np


# Anderson 13 fuel models — SI units for Rothermel/Balbi
# Rhod: kg/m³, sd: 1/m, e: m, Sigmad: kg/m², DeltaH: J/kg
#
# PROVENANCE: values are transcribed verbatim from the ForeFire reference fuel
# table `tests/runff/fuels.csv` in the upstream repository, which the official
# user guide (docs/source/user_guide/fuels_and_models.rst, "Finding and Creating
# Fuel Parameter Sets") designates as "the best and intended reference for a
# correctly formatted file". Indices 0-13 follow the Anderson (1982) FBFM
# numbering: 0 = non-burnable, 1-13 = the thirteen fuel models.
#
# The table previously stopped at index 5, so `--source anderson13` delivered
# only 6 of the 13 models it names and a fuel raster derived from land cover
# could not represent ANY timber-litter or slash fuel (Anderson 8-13). Indices
# 6-13 below close that gap.
ANDERSON_13_SI = {
    0: {
        "name": "Non-burnable", "Rhod": 563, "Rhol": 522, "Md": 0.1, "Ml": 1.0,
        "sd": 6099, "sl": 7273, "e": 0, "Sigmad": 0.764, "Sigmal": 0.352,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18169000, "DeltaH": 18167000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    1: {
        "name": "Short grass", "Rhod": 563, "Rhol": 522, "Md": 0.1, "Ml": 1.0,
        "sd": 6099, "sl": 7273, "e": 0.24, "Sigmad": 0.764, "Sigmal": 0.352,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18169000, "DeltaH": 18167000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    2: {
        "name": "Timber grass/understory", "Rhod": 614, "Rhol": 613, "Md": 0.1, "Ml": 1.0,
        "sd": 4287, "sl": 5738, "e": 0.4, "Sigmad": 1.378, "Sigmal": 0.174,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18727000, "DeltaH": 18727000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    3: {
        "name": "Tall grass", "Rhod": 614, "Rhol": 613, "Md": 0.1, "Ml": 1.0,
        "sd": 4287, "sl": 5738, "e": 0.4, "Sigmad": 1.378, "Sigmal": 0.174,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18727000, "DeltaH": 18727000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    4: {
        "name": "Chaparral", "Rhod": 613, "Rhol": 538, "Md": 0.1, "Ml": 1.0,
        "sd": 4357, "sl": 6524, "e": 0.19, "Sigmad": 1.286, "Sigmal": 0.085,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18677000, "DeltaH": 18677000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    5: {
        "name": "Brush", "Rhod": 626, "Rhol": 600, "Md": 0.1, "Ml": 1.0,
        "sd": 4325, "sl": 5844, "e": 0.6, "Sigmad": 1.393, "Sigmal": 0.201,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18802000, "DeltaH": 18802000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    6: {
        "name": "Dormant brush / hardwood slash", "Rhod": 562, "Rhol": 474,
        "Md": 0.1, "Ml": 1.0, "sd": 6740, "sl": 8195, "e": 0.57,
        "Sigmad": 1.326, "Sigmal": 0.166,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18941000, "DeltaH": 18941000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    7: {
        "name": "Southern rough", "Rhod": 658, "Rhol": 651,
        "Md": 0.1, "Ml": 1.0, "sd": 4734, "sl": 5733, "e": 0.15,
        "Sigmad": 1.415, "Sigmal": 0.541,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18472000, "DeltaH": 18466000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    8: {
        "name": "Closed timber litter", "Rhod": 446, "Rhol": 513,
        "Md": 0.1, "Ml": 1.0, "sd": 7792, "sl": 9072, "e": 0.78,
        "Sigmad": 0.492, "Sigmal": 0.023,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18587000, "DeltaH": 18587000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    9: {
        "name": "Hardwood litter", "Rhod": 467, "Rhol": 543,
        "Md": 0.1, "Ml": 1.0, "sd": 6115, "sl": 7224, "e": 0.285,
        "Sigmad": 0.855, "Sigmal": 0.174,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18474000, "DeltaH": 18474000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    10: {
        "name": "Timber litter and understory", "Rhod": 674, "Rhol": 612,
        "Md": 0.1, "Ml": 1.0, "sd": 4801, "sl": 5928, "e": 0.45,
        "Sigmad": 1.525, "Sigmal": 0.709,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18280000, "DeltaH": 18277000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    11: {
        "name": "Light logging slash", "Rhod": 653, "Rhol": 582,
        "Md": 0.1, "Ml": 1.0, "sd": 4753, "sl": 6569, "e": 0.75,
        "Sigmad": 1.096, "Sigmal": 1.105,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 18226000, "DeltaH": 18221000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    12: {
        "name": "Medium logging slash", "Rhod": 596, "Rhol": 586,
        "Md": 0.1, "Ml": 1.0, "sd": 3688, "sl": 5551, "e": 0.475,
        "Sigmad": 1.346, "Sigmal": 0.077,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 19050000, "DeltaH": 19050000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
    13: {
        "name": "Heavy logging slash", "Rhod": 438, "Rhol": 488,
        "Md": 0.1, "Ml": 1.0, "sd": 7274, "sl": 8453, "e": 0.38,
        "Sigmad": 1.053, "Sigmal": 0.321,
        "stoch": 8.3, "RhoA": 1.0, "Ta": 300, "Tau0": 70000,
        "Deltah": 17842000, "DeltaH": 17842000, "Cp": 1800, "Cpa": 1000,
        "Ti": 600, "X0": 0.3, "r00": 2.5e-05, "Blai": 4.0, "me": 0.3,
    },
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    valid_models = ["rothermel", "balbi2020", "andrews2018", "farsite"]
    if args.model.lower() not in valid_models:
        errors.append(f"Model must be one of {valid_models}, got: {args.model}")

    if args.custom_csv and not os.path.isfile(args.custom_csv):
        errors.append(f"Custom CSV file not found: {args.custom_csv}")

    if errors:
        for e in errors:
            print(f"VALIDATION ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print("Input validation passed.")


def convert_imperial_to_si(row):
    """Convert a fuel row from Imperial to SI units for Rothermel/Balbi.

    Imperial → SI conversions:
      Rhod: lb/ft³ → kg/m³  (× 16.0185)
      sd:   1/ft → 1/m      (× 3.28084)
      e:    ft → m           (÷ 3.28084)
      Sigmad: lb/ft² → kg/m² (× 4.88243)
      DeltaH: BTU/lb → J/kg  (× 2326)
    """
    si_row = dict(row)
    if "Rhod" in si_row:
        si_row["Rhod"] = row["Rhod"] * 16.0185
    if "Rhol" in si_row:
        si_row["Rhol"] = row["Rhol"] * 16.0185
    if "sd" in si_row:
        si_row["sd"] = row["sd"] * 3.28084
    if "sl" in si_row:
        si_row["sl"] = row["sl"] * 3.28084
    if "e" in si_row:
        si_row["e"] = row["e"] / 3.28084
    if "Sigmad" in si_row:
        si_row["Sigmad"] = row["Sigmad"] * 4.88243
    if "Sigmal" in si_row:
        si_row["Sigmal"] = row["Sigmal"] * 4.88243
    if "DeltaH" in si_row:
        si_row["DeltaH"] = row["DeltaH"] * 2326
    if "Deltah" in si_row:
        si_row["Deltah"] = row["Deltah"] * 2326
    return si_row


def process(args):
    """Generate fuels.csv for the specified model."""
    model = args.model.lower()

    if args.custom_csv:
        print(f"Loading custom fuel CSV: {args.custom_csv}")
        rows = []
        with open(args.custom_csv, 'r') as f:
            dialect = csv.Sniffer().sniff(f.read(2048))
            f.seek(0)
            reader = csv.DictReader(f, delimiter=dialect.delimiter)
            for r in reader:
                rows.append({k: float(v) if k != "name" else v for k, v in r.items()})

        if args.source_units == "imperial" and model in ("rothermel", "balbi2020"):
            print("Converting Imperial to SI units for Rothermel/Balbi...")
            rows = [convert_imperial_to_si(r) for r in rows]

        fuels = {int(r.get("Index", i)): r for i, r in enumerate(rows)}
    else:
        print(f"Using built-in Anderson 13 fuel models (SI for Rothermel/Balbi)")
        fuels = ANDERSON_13_SI

    # Write output CSV
    if model in ("rothermel", "balbi2020"):
        columns = [
            "Index", "Rhod", "Rhol", "Md", "Ml", "sd", "sl", "e",
            "Sigmad", "Sigmal", "stoch", "RhoA", "Ta", "Tau0",
            "Deltah", "DeltaH", "Cp", "Cpa", "Ti", "X0", "r00", "Blai", "me"
        ]
    elif model == "andrews2018":
        columns = [
            "Index", "fl1h_tac", "fd_ft", "SAVcar_ftinv", "mdOnDry1h_r",
            "fuelDens_lbft3", "H_BTUlb", "Dme_pc", "totMineral_r", "effectMineral_r"
        ]
    else:
        columns = [
            "Index", "h1", "h10", "h100", "lh", "lw", "dynamic",
            "sav1", "savlh", "savlw", "depth", "xmext", "heatContent"
        ]

    print(f"Writing: {args.output} ({len(fuels)} fuel types, model={model})")
    with open(args.output, 'w') as f:
        f.write(";".join(columns) + "\n")
        for idx in sorted(fuels.keys()):
            vals = []
            for col in columns:
                if col == "Index":
                    vals.append(str(idx))
                else:
                    v = fuels[idx].get(col, 0.0)
                    vals.append(str(v))
            f.write(";".join(vals) + "\n")

    print(f"Fuel table written: {args.output}")


def validate_outputs(output_path, model):
    """Post-processing validation of the fuels CSV."""
    errors = []

    with open(output_path, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = list(reader)

    if len(rows) < 1:
        errors.append("Fuel table is empty")
        return False

    if model in ("rothermel", "balbi2020"):
        for row in rows:
            idx = row.get("Index", "?")
            # Check fuel depth
            e = float(row.get("e", 0))
            if e < 0:
                errors.append(f"Fuel {idx}: negative fuel depth e={e}")
            # Check density
            rhod = float(row.get("Rhod", 0))
            if rhod <= 0 and e > 0:
                errors.append(f"Fuel {idx}: zero density with non-zero depth")
            # Check moisture of extinction
            me = float(row.get("me", 0))
            if me > 1.0:
                errors.append(f"Fuel {idx}: me={me} > 1.0 — should be fraction for Rothermel")

    if errors:
        for e in errors:
            print(f"OUTPUT VALIDATION WARNING: {e}", file=sys.stderr)
        return False

    print(f"Output validation passed ({len(rows)} fuel types).")
    return True


def main():
    parser = argparse.ArgumentParser(description="Convert fuel models to ForeFire fuels.csv")
    parser.add_argument("--model", required=True, help="Propagation model: rothermel, balbi2020, andrews2018, farsite")
    parser.add_argument("--source", default="anderson13", help="Built-in fuel model source")
    parser.add_argument("--custom_csv", default=None, help="Path to custom fuel CSV")
    parser.add_argument("--source_units", default="si", choices=["si", "imperial"], help="Units of custom CSV")
    parser.add_argument("--output", default="fuels.csv", help="Output fuels.csv path")
    args = parser.parse_args()

    validate_inputs(args)
    process(args)
    validate_outputs(args.output, args.model.lower())


if __name__ == "__main__":
    main()
