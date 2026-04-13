#!/usr/bin/env python3
"""
Assign LID controls to SWMM subcatchments.

Maps LID (Low Impact Development) controls to subcatchments, specifying
the number of units, area per unit, and other deployment parameters.
Validates that total LID area does not exceed subcatchment area.

Input formats:
  - JSON: list of {subcatchment, lid_control, number, area_per_unit, ...}
  - CSV: same columns in tabular form

Each assignment contains:
  - subcatchment: subcatchment ID
  - lid_control: LID control name
  - number: number of LID units
  - area_per_unit: area of each unit (m^2)
  - surface_width: width of outflow surface (m, optional)
  - init_saturation: initial saturation (0-100%, optional)
  - from_impervious: percentage of impervious area treated (0-100%, optional)
  - to_pervious: route outflow to pervious area (0 or 1, optional)

Outputs:
  - JSON file with validated LID usage definitions
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path


def load_assignments(path):
    """Load LID assignments from JSON or CSV."""
    ext = Path(path).suffix.lower()
    assignments = []

    if ext == ".json":
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            assignments = data
        elif isinstance(data, dict) and "assignments" in data:
            assignments = data["assignments"]
        else:
            print(f"ERROR: Unexpected JSON structure in {path}", file=sys.stderr)
            sys.exit(1)
    elif ext == ".csv":
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                assignments.append({
                    "subcatchment": row["subcatchment"].strip(),
                    "lid_control": row["lid_control"].strip(),
                    "number": int(row.get("number", 1)),
                    "area_per_unit": float(row.get("area_per_unit", 100)),
                    "surface_width": float(row.get("surface_width", 0)),
                    "init_saturation": float(row.get("init_saturation", 0)),
                    "from_impervious": float(row.get("from_impervious", 0)),
                    "to_pervious": int(row.get("to_pervious", 0)),
                })
    else:
        print(f"ERROR: Unsupported format: {ext} (use .json or .csv)", file=sys.stderr)
        sys.exit(1)

    return assignments


def validate_assignments(assignments, subcatchment_areas=None):
    """Validate LID assignments."""
    issues = []
    warnings = []

    # Group by subcatchment to check total area
    from collections import defaultdict
    sc_lid_areas = defaultdict(float)

    for i, asgn in enumerate(assignments):
        prefix = f"Assignment {i+1} ({asgn.get('subcatchment', '?')}/{asgn.get('lid_control', '?')})"

        # Required fields
        if not asgn.get("subcatchment"):
            issues.append(f"{prefix}: Missing subcatchment ID")
        if not asgn.get("lid_control"):
            issues.append(f"{prefix}: Missing lid_control name")

        # Number of units
        n = asgn.get("number", 0)
        if n <= 0:
            issues.append(f"{prefix}: number must be > 0 (got {n})")

        # Area per unit
        area = asgn.get("area_per_unit", 0)
        if area <= 0:
            issues.append(f"{prefix}: area_per_unit must be > 0 (got {area})")
        elif area < 1:
            warnings.append(f"{prefix}: Very small area_per_unit ({area} m^2)")

        # Total LID area for this subcatchment
        total_lid_area = n * area
        sc_lid_areas[asgn.get("subcatchment", "")] += total_lid_area

        # Init saturation range
        init_sat = asgn.get("init_saturation", 0)
        if init_sat < 0 or init_sat > 100:
            issues.append(f"{prefix}: init_saturation must be 0-100 (got {init_sat})")

        # From impervious range
        from_imp = asgn.get("from_impervious", 0)
        if from_imp < 0 or from_imp > 100:
            issues.append(f"{prefix}: from_impervious must be 0-100 (got {from_imp})")

        # To pervious boolean
        to_perv = asgn.get("to_pervious", 0)
        if to_perv not in (0, 1):
            warnings.append(f"{prefix}: to_pervious should be 0 or 1 (got {to_perv})")

    # Check total LID area vs subcatchment area
    if subcatchment_areas:
        for sc_id, lid_area in sc_lid_areas.items():
            sc_area_m2 = subcatchment_areas.get(sc_id)
            if sc_area_m2 is not None and lid_area > sc_area_m2:
                issues.append(
                    f"Subcatchment {sc_id}: Total LID area ({lid_area:.1f} m^2) "
                    f"exceeds subcatchment area ({sc_area_m2:.1f} m^2)"
                )
            elif sc_area_m2 is not None and lid_area > sc_area_m2 * 0.8:
                warnings.append(
                    f"Subcatchment {sc_id}: LID covers {lid_area/sc_area_m2*100:.0f}% "
                    f"of subcatchment area"
                )

    return issues, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Assign LID controls to SWMM subcatchments"
    )
    parser.add_argument("--assignments", required=True,
                        help="LID assignments file (JSON or CSV)")
    parser.add_argument("--output", required=True,
                        help="Output JSON path")
    parser.add_argument("--subcatchment_areas", default=None,
                        help="CSV with subcatchment areas (id, area_m2) for validation")
    args = parser.parse_args()

    if not os.path.isfile(args.assignments):
        print(f"ERROR: File not found: {args.assignments}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading LID assignments from {args.assignments}...")
    assignments = load_assignments(args.assignments)
    print(f"  {len(assignments)} assignments loaded")

    # Load subcatchment areas if provided
    sc_areas = None
    if args.subcatchment_areas:
        sc_areas = {}
        with open(args.subcatchment_areas, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sc_id = row.get("id", row.get("subcatchment", ""))
                area = float(row.get("area_m2", row.get("area_ha", 0)) or 0)
                if "area_ha" in row and "area_m2" not in row:
                    area = area * 10000  # ha to m^2
                sc_areas[sc_id] = area

    # Validate
    issues, warnings = validate_assignments(assignments, sc_areas)

    # Normalize assignments
    normalized = []
    for asgn in assignments:
        normalized.append({
            "subcatchment": asgn.get("subcatchment", ""),
            "lid_control": asgn.get("lid_control", ""),
            "number": int(asgn.get("number", 1)),
            "area_per_unit": float(asgn.get("area_per_unit", 100)),
            "surface_width": float(asgn.get("surface_width", 0)),
            "init_saturation": float(asgn.get("init_saturation", 0)),
            "from_impervious": float(asgn.get("from_impervious", 0)),
            "to_pervious": int(asgn.get("to_pervious", 0)),
            "report_file": asgn.get("report_file", ""),
        })

    output = {
        "lid_usage": normalized,
        "metadata": {
            "n_assignments": len(normalized),
            "n_subcatchments": len(set(a["subcatchment"] for a in normalized)),
            "n_lid_controls": len(set(a["lid_control"] for a in normalized)),
        },
        "validation": {
            "valid": len(issues) == 0,
            "n_issues": len(issues),
            "n_warnings": len(warnings),
            "issues": issues,
            "warnings": warnings,
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nLID usage written: {output_path}")
    if issues:
        print(f"  {len(issues)} issue(s):", file=sys.stderr)
        for issue in issues:
            print(f"    - {issue}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"  All {len(normalized)} assignments valid")


if __name__ == "__main__":
    main()
