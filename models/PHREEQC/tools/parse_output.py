#!/usr/bin/env python3
"""
Parse PHREEQC output files (.pqo full output or .sel selected output)
and extract results to CSV or JSON.

Handles:
  - Selected output (.sel) tab-delimited files -> CSV
  - Full output (.pqo) -> extract speciation, SI, totals
  - Multiple simulation steps

Usage:
    python3 parse_output.py --input results.sel --output results.csv --format csv
    python3 parse_output.py --input output.pqo --output speciation.json --format json --extract speciation
"""
import argparse
import csv
import json
import os
import re
import sys


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    else:
        size = os.path.getsize(args.input)
        if size == 0:
            errors.append(f"Input file is empty: {args.input}")

    if args.format not in ("csv", "json"):
        errors.append(f"Unsupported output format: {args.format}")

    if args.extract and args.extract not in ("speciation", "si", "totals", "phases", "all"):
        errors.append(f"Unsupported extract mode: {args.extract}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def parse_selected_output(filepath):
    """
    Parse PHREEQC selected output (.sel) file.

    TRAP: .sel files are TAB-delimited, NOT comma-delimited.
    Using sep=',' will produce a single mangled column.
    """
    rows = []
    headers = None

    with open(filepath, "r") as f:
        for line_num, line in enumerate(f):
            # Skip empty lines
            if not line.strip():
                continue

            # Split by tabs
            parts = line.rstrip("\n").split("\t")

            if headers is None:
                # First non-empty line is header
                headers = [h.strip() for h in parts]
                continue

            # Data row
            row = {}
            for i, val in enumerate(parts):
                if i < len(headers):
                    key = headers[i]
                    val = val.strip()
                    # Try to convert to float
                    try:
                        row[key] = float(val)
                    except ValueError:
                        row[key] = val
            rows.append(row)

    return headers, rows


def parse_full_output_speciation(filepath):
    """Parse species distribution from full PHREEQC output (.pqo)."""
    solutions = []
    current_solution = None
    section = None

    with open(filepath, "r") as f:
        for line in f:
            stripped = line.strip()

            # Detect new solution block
            if "----------------------------Distribution of species---" in stripped:
                if current_solution:
                    solutions.append(current_solution)
                current_solution = {"species": [], "section": "distribution"}
                section = "header"
                continue

            if current_solution is None:
                continue

            # Parse species lines (format: Species  Molality  Activity  Log Molality  Log Activity  Log Gamma)
            if section == "header":
                if stripped.startswith("Species"):
                    section = "data"
                    continue
                if stripped.startswith("---") and len(stripped) > 10:
                    section = "data"
                    continue

            if section == "data":
                if not stripped or stripped.startswith("---"):
                    if stripped.startswith("-----"):
                        section = None
                        continue
                    continue

                # Try parsing species line
                parts = stripped.split()
                if len(parts) >= 5:
                    try:
                        species_data = {
                            "species": parts[0],
                            "molality": float(parts[1]),
                            "activity": float(parts[2]),
                            "log_molality": float(parts[3]),
                            "log_activity": float(parts[4]),
                        }
                        if len(parts) >= 6:
                            species_data["log_gamma"] = float(parts[5])
                        current_solution["species"].append(species_data)
                    except (ValueError, IndexError):
                        pass

    if current_solution:
        solutions.append(current_solution)

    return solutions


def parse_full_output_si(filepath):
    """Parse saturation indices from full PHREEQC output."""
    solutions = []
    current_si = None
    section = None

    with open(filepath, "r") as f:
        for line in f:
            stripped = line.strip()

            if "-----Saturation indices-----" in line or \
               "Phase" in stripped and "SI" in stripped and "log IAP" in stripped:
                if current_si:
                    solutions.append(current_si)
                current_si = {"phases": []}
                section = "header"
                continue

            if current_si is None:
                continue

            if section == "header":
                if stripped.startswith("Phase") or stripped.startswith("---"):
                    section = "data"
                    continue

            if section == "data":
                if not stripped or stripped.startswith("---"):
                    if not stripped:
                        section = None
                        continue
                    continue

                parts = stripped.split()
                if len(parts) >= 4:
                    try:
                        phase_data = {
                            "phase": parts[0],
                            "SI": float(parts[1]),
                            "log_IAP": float(parts[2]),
                            "log_K": float(parts[3]),
                        }
                        if len(parts) >= 5:
                            phase_data["formula"] = " ".join(parts[4:])
                        current_si["phases"].append(phase_data)
                    except (ValueError, IndexError):
                        pass

    if current_si:
        solutions.append(current_si)

    return solutions


def parse_full_output_totals(filepath):
    """Parse solution composition (element totals) from full output."""
    solutions = []
    current_totals = None
    section = None

    with open(filepath, "r") as f:
        for line in f:
            stripped = line.strip()

            if "----------------------------Solution composition---" in line:
                if current_totals:
                    solutions.append(current_totals)
                current_totals = {"elements": []}
                section = "header"
                continue

            if current_totals is None:
                continue

            if section == "header":
                if stripped.startswith("Elements") or stripped.startswith("---"):
                    section = "data"
                    continue

            if section == "data":
                if not stripped:
                    section = None
                    continue

                parts = stripped.split()
                if len(parts) >= 2:
                    try:
                        elem_data = {
                            "element": parts[0],
                            "molality": float(parts[1]),
                        }
                        if len(parts) >= 3:
                            try:
                                elem_data["moles"] = float(parts[2])
                            except ValueError:
                                pass
                        current_totals["elements"].append(elem_data)
                    except (ValueError, IndexError):
                        pass

    if current_totals:
        solutions.append(current_totals)

    return solutions


def parse_full_output_phases(filepath):
    """Parse phase assemblage results from full output."""
    solutions = []
    current = None
    section = None

    with open(filepath, "r") as f:
        for line in f:
            stripped = line.strip()

            if "Phase assemblage" in line:
                if current:
                    solutions.append(current)
                current = {"phases": []}
                section = "header"
                continue

            if current is None:
                continue

            if section == "header":
                if stripped.startswith("---") or stripped.startswith("Phase"):
                    section = "data"
                    continue

            if section == "data":
                if not stripped:
                    section = None
                    continue

                parts = stripped.split()
                if len(parts) >= 3:
                    try:
                        phase_data = {
                            "phase": parts[0],
                            "si_target": float(parts[1]) if len(parts) > 1 else None,
                        }
                        current["phases"].append(phase_data)
                    except (ValueError, IndexError):
                        pass

    if current:
        solutions.append(current)

    return solutions


def process(args):
    """Parse PHREEQC output."""
    results = {
        "status": "success",
        "warnings": [],
        "input_file": args.input,
        "output_format": args.format,
    }

    # Detect file type
    ext = os.path.splitext(args.input)[1].lower()
    is_selected = ext in (".sel", ".tsv") or args.selected

    if is_selected:
        headers, rows = parse_selected_output(args.input)
        results["parse_mode"] = "selected_output"
        results["num_rows"] = len(rows)
        results["columns"] = headers

        if args.format == "csv":
            output_text = _rows_to_csv(headers, rows)
        else:
            output_text = json.dumps({"headers": headers, "data": rows}, indent=2)

    else:
        # Full output parsing
        extract = args.extract or "all"
        parsed = {}

        if extract in ("speciation", "all"):
            parsed["speciation"] = parse_full_output_speciation(args.input)
        if extract in ("si", "all"):
            parsed["saturation_indices"] = parse_full_output_si(args.input)
        if extract in ("totals", "all"):
            parsed["totals"] = parse_full_output_totals(args.input)
        if extract in ("phases", "all"):
            parsed["phase_assemblage"] = parse_full_output_phases(args.input)

        results["parse_mode"] = f"full_output_{extract}"
        results["sections_parsed"] = list(parsed.keys())

        # Count records
        for key, val in parsed.items():
            results[f"num_{key}"] = len(val) if val else 0

        if args.format == "csv":
            # Flatten to CSV - use speciation or totals as primary
            if "speciation" in parsed and parsed["speciation"]:
                all_species = []
                for i, sol in enumerate(parsed["speciation"]):
                    for sp in sol["species"]:
                        sp["solution_step"] = i + 1
                        all_species.append(sp)
                if all_species:
                    headers = list(all_species[0].keys())
                    output_text = _rows_to_csv(headers, all_species)
                else:
                    output_text = ""
            elif "totals" in parsed and parsed["totals"]:
                all_elems = []
                for i, sol in enumerate(parsed["totals"]):
                    for elem in sol["elements"]:
                        elem["solution_step"] = i + 1
                        all_elems.append(elem)
                if all_elems:
                    headers = list(all_elems[0].keys())
                    output_text = _rows_to_csv(headers, all_elems)
                else:
                    output_text = ""
            else:
                output_text = ""
                results["warnings"].append("No data to flatten to CSV")
        else:
            output_text = json.dumps(parsed, indent=2)

    return results, output_text


def _rows_to_csv(headers, rows):
    """Convert list of dicts to CSV string."""
    import io
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def validate_outputs(results, output_text):
    """Post-processing validation."""
    if not output_text or not output_text.strip():
        results["warnings"].append("No output data extracted. Check if input file has expected format.")

    lines = output_text.count("\n") if output_text else 0
    results["output_lines"] = lines

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Parse PHREEQC output to CSV or JSON"
    )
    parser.add_argument("--input", required=True,
                        help="Input file (.pqo full output or .sel selected output)")
    parser.add_argument("--output", required=True,
                        help="Output file (.csv or .json)")
    parser.add_argument("--format", default="csv", choices=["csv", "json"],
                        help="Output format (csv or json, default csv)")
    parser.add_argument("--extract", default=None,
                        choices=["speciation", "si", "totals", "phases", "all"],
                        help="What to extract from full output (default: all)")
    parser.add_argument("--selected", action="store_true",
                        help="Force parsing as selected output (tab-delimited)")
    parser.add_argument("--json-output", default=None,
                        help="Path for JSON result summary")

    args = parser.parse_args()
    validate_inputs(args)
    results, output_text = process(args)
    results = validate_outputs(results, output_text)

    if output_text:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"Wrote output to {args.output} ({results.get('output_lines', 0)} lines)",
              file=sys.stderr)

    if args.json_output:
        os.makedirs(os.path.dirname(args.json_output) or ".", exist_ok=True)
        with open(args.json_output, "w") as f:
            json.dump(results, f, indent=2)
    else:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
