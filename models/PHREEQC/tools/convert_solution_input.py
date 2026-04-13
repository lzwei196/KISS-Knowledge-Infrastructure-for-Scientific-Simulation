#!/usr/bin/env python3
"""
Convert water chemistry data (CSV) to PHREEQC SOLUTION input blocks.

Handles unit conversions from common laboratory formats (mg/L, ug/L)
to PHREEQC-compatible input. Supports multiple solutions from tabular data.

Usage:
    python3 convert_solution_input.py --input water_data.csv --output solutions.pqi \
        --units mg/L --database phreeqc.dat
"""
import argparse
import csv
import json
import os
import sys

# Standard PHREEQC element names and their atomic weights (g/mol)
ELEMENT_INFO = {
    "Ca": {"aw": 40.078, "aliases": ["calcium", "ca", "Ca2+"]},
    "Mg": {"aw": 24.305, "aliases": ["magnesium", "mg_elem", "Mg2+"]},
    "Na": {"aw": 22.990, "aliases": ["sodium", "na", "Na+"]},
    "K":  {"aw": 39.098, "aliases": ["potassium", "k", "K+"]},
    "Fe": {"aw": 55.845, "aliases": ["iron", "fe", "Fe2+", "Fe3+"]},
    "Mn": {"aw": 54.938, "aliases": ["manganese", "mn", "Mn2+"]},
    "Al": {"aw": 26.982, "aliases": ["aluminum", "al", "Al3+"]},
    "Si": {"aw": 28.086, "aliases": ["silicon", "si", "SiO2", "silica"]},
    "Cl": {"aw": 35.453, "aliases": ["chloride", "cl", "Cl-"]},
    "S(6)": {"aw": 32.065, "aliases": ["sulfate", "so4", "SO4", "S"]},
    "C(4)": {"aw": 12.011, "aliases": ["alkalinity", "hco3", "HCO3", "co3", "CO3", "DIC"]},
    "N(-3)": {"aw": 14.007, "aliases": ["ammonium", "nh4", "NH4"]},
    "N(5)": {"aw": 14.007, "aliases": ["nitrate", "no3", "NO3"]},
    "P":  {"aw": 30.974, "aliases": ["phosphate", "po4", "PO4"]},
    "F":  {"aw": 18.998, "aliases": ["fluoride", "f"]},
    "Sr": {"aw": 87.62,  "aliases": ["strontium", "sr", "Sr2+"]},
    "Ba": {"aw": 137.33, "aliases": ["barium", "ba", "Ba2+"]},
    "Li": {"aw": 6.941,  "aliases": ["lithium", "li", "Li+"]},
    "B":  {"aw": 10.811, "aliases": ["boron", "b"]},
    "Zn": {"aw": 65.38,  "aliases": ["zinc", "zn", "Zn2+"]},
    "Cu": {"aw": 63.546, "aliases": ["copper", "cu", "Cu2+"]},
    "Cd": {"aw": 112.41, "aliases": ["cadmium", "cd", "Cd2+"]},
    "Br": {"aw": 79.904, "aliases": ["bromide", "br", "Br-"]},
}

# Fields for pH, pe, temperature, density
META_FIELDS = {
    "pH":    {"aliases": ["ph", "pH"], "default": 7.0},
    "pe":    {"aliases": ["pe", "Eh"], "default": 4.0},
    "temp":  {"aliases": ["temperature", "temp", "T", "t_celsius"], "default": 25.0},
    "density": {"aliases": ["density", "rho"], "default": 1.0},
}

UNIT_CONVERSIONS = {
    "mg/L":  1.0,
    "ppm":   1.0,
    "ug/L":  0.001,
    "ppb":   0.001,
    "mol/L": None,  # requires molar mass multiplication
    "mmol/L": None,
    "meq/L": None,
}


def validate_inputs(args):
    """Validate input arguments and files."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.units not in UNIT_CONVERSIONS:
        errors.append(f"Unsupported unit: {args.units}. Use one of: {list(UNIT_CONVERSIONS.keys())}")

    if args.database and not os.path.isfile(args.database):
        errors.append(f"Database file not found: {args.database}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def match_column(col_name, element_info):
    """Match a CSV column name to a PHREEQC element."""
    col_lower = col_name.strip().lower()
    for elem, info in element_info.items():
        if col_lower == elem.lower():
            return elem
        for alias in info["aliases"]:
            if col_lower == alias.lower():
                return elem
    return None


def match_meta(col_name, meta_fields):
    """Match a CSV column name to a metadata field."""
    col_lower = col_name.strip().lower()
    for field, info in meta_fields.items():
        for alias in info["aliases"]:
            if col_lower == alias.lower():
                return field
    return None


def convert_eh_to_pe(eh_mv, temp_c=25.0):
    """Convert Eh (mV) to pe. pe = Eh(V) * F / (2.303 * R * T_K)."""
    R = 8.314  # J/(mol*K)
    F = 96485.0  # C/mol
    T_K = temp_c + 273.15
    pe = (eh_mv / 1000.0) * F / (2.303 * R * T_K)
    return pe


def process(args):
    """Read CSV and produce PHREEQC SOLUTION blocks."""
    results = {
        "status": "success",
        "solutions": [],
        "warnings": [],
        "unit_conversions_applied": [],
    }

    with open(args.input, "r", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        if not columns:
            results["status"] = "error"
            results["errors"] = ["CSV file has no header row"]
            return results, ""

        # Map columns to elements and meta fields
        col_map = {}
        meta_map = {}
        unmapped = []
        for col in columns:
            elem = match_column(col, ELEMENT_INFO)
            if elem:
                col_map[col] = elem
            else:
                meta = match_meta(col, META_FIELDS)
                if meta:
                    meta_map[col] = meta
                else:
                    unmapped.append(col)

        if unmapped:
            results["warnings"].append(f"Unmapped columns (ignored): {unmapped}")

        if not col_map:
            results["status"] = "error"
            results["errors"] = ["No recognizable element columns found in CSV"]
            return results, ""

        # Process each row as a solution
        output_lines = []
        solution_num = 0
        for row in reader:
            solution_num += 1

            # Get meta values
            meta_vals = {}
            for col, field in meta_map.items():
                try:
                    val = float(row[col])
                    meta_vals[field] = val
                except (ValueError, KeyError):
                    meta_vals[field] = META_FIELDS[field]["default"]

            # Fill defaults for missing meta
            for field, info in META_FIELDS.items():
                if field not in meta_vals:
                    meta_vals[field] = info["default"]

            # Handle Eh -> pe conversion
            if "pe" in meta_vals and any("eh" in c.lower() for c in meta_map):
                eh_val = meta_vals["pe"]
                temp = meta_vals.get("temp", 25.0)
                meta_vals["pe"] = convert_eh_to_pe(eh_val, temp)
                results["unit_conversions_applied"].append(
                    f"Solution {solution_num}: Eh {eh_val} mV -> pe {meta_vals['pe']:.4f}"
                )

            # Build SOLUTION block
            label = row.get("label", row.get("name", row.get("id", f"Sample_{solution_num}")))
            output_lines.append(f"SOLUTION {solution_num}  {label}")
            output_lines.append(f"    temp    {meta_vals['temp']:.1f}")
            output_lines.append(f"    pH      {meta_vals['pH']:.2f}")
            output_lines.append(f"    pe      {meta_vals['pe']:.4f}")
            output_lines.append(f"    density {meta_vals['density']:.4f}")
            output_lines.append(f"    units   {args.units}")

            # Add element concentrations
            elements_added = []
            for col, elem in col_map.items():
                try:
                    val = float(row[col])
                except (ValueError, KeyError):
                    continue
                if val <= 0:
                    continue

                # Unit conversion for ug/L -> mg/L
                if args.units in ("ug/L", "ppb"):
                    val_converted = val * 0.001
                    output_lines.append(f"    {elem:8s}  {val_converted:.6f}  # converted from {val} {args.units}")
                    results["unit_conversions_applied"].append(
                        f"Solution {solution_num}, {elem}: {val} {args.units} -> {val_converted:.6f} mg/L"
                    )
                else:
                    output_lines.append(f"    {elem:8s}  {val:.6f}")
                elements_added.append(elem)

            # Add charge balance on Cl if not explicitly provided
            if args.charge_balance and args.charge_balance in elements_added:
                # Replace the line for the charge-balance element
                for i, line in enumerate(output_lines):
                    if line.strip().startswith(args.charge_balance):
                        output_lines[i] = output_lines[i].rstrip() + "  charge"
                        break

            output_lines.append("")
            results["solutions"].append({
                "number": solution_num,
                "label": label,
                "elements": elements_added,
                "pH": meta_vals["pH"],
                "temp": meta_vals["temp"],
            })

        output_lines.append("END")
        output_text = "\n".join(output_lines) + "\n"
        return results, output_text


def validate_outputs(results, output_text):
    """Post-processing validation."""
    if results["status"] != "success":
        return results

    n = len(results["solutions"])
    if n == 0:
        results["status"] = "error"
        results["errors"] = ["No valid solutions produced"]
        return results

    # Check each solution has at least one element
    for sol in results["solutions"]:
        if not sol["elements"]:
            results["warnings"].append(
                f"Solution {sol['number']} ({sol['label']}) has no element data"
            )

    results["summary"] = {
        "total_solutions": n,
        "output_lines": len(output_text.splitlines()),
    }
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convert water chemistry CSV to PHREEQC SOLUTION blocks"
    )
    parser.add_argument("--input", required=True, help="Input CSV file with water chemistry data")
    parser.add_argument("--output", required=True, help="Output PHREEQC input file (.pqi)")
    parser.add_argument("--units", default="mg/L",
                        help="Input concentration units (mg/L, ug/L, ppm, ppb, mol/L, mmol/L, meq/L)")
    parser.add_argument("--database", default=None, help="Path to PHREEQC database file (for validation)")
    parser.add_argument("--charge-balance", default=None,
                        help="Element to use for charge balance (e.g., Cl)")
    parser.add_argument("--json-output", default=None, help="Path for JSON result summary")

    args = parser.parse_args()
    validate_inputs(args)
    results, output_text = process(args)
    results = validate_outputs(results, output_text)

    if results["status"] == "success":
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"Wrote {len(results['solutions'])} solutions to {args.output}", file=sys.stderr)

    if args.json_output:
        os.makedirs(os.path.dirname(args.json_output) or ".", exist_ok=True)
        with open(args.json_output, "w") as f:
            json.dump(results, f, indent=2)
    else:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
