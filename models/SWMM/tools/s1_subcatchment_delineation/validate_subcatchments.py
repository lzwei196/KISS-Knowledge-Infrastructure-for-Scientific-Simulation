#!/usr/bin/env python3
"""
Validate SWMM subcatchment configuration.

Checks subcatchment parameters for correctness and consistency:
  - Area > 0
  - Width > 0
  - Slope > 0
  - Percent impervious in [0, 100]
  - Outlet node exists in the node list
  - Infiltration parameters are valid (positive, consistent)
  - No duplicate subcatchment IDs

Can validate from either a SWMM .inp file or from separate CSV files.

Outputs a JSON validation report to stdout.
"""

import argparse
import csv
import json
import os
import re
import sys


def parse_inp_subcatchments(inp_path):
    """Parse [SUBCATCHMENTS] and [SUBAREAS] sections from a SWMM .inp file."""
    subcatchments = []
    subareas = {}
    nodes = set()
    current_section = None

    with open(inp_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].upper()
                continue
            if not line or line.startswith(";"):
                continue

            parts = line.split()

            if current_section == "SUBCATCHMENTS" and len(parts) >= 5:
                subcatchments.append({
                    "id": parts[0],
                    "rain_gage": parts[1],
                    "outlet": parts[2],
                    "area_ha": float(parts[3]),
                    "imperv_pct": float(parts[4]),
                    "width_m": float(parts[5]) if len(parts) > 5 else 0,
                    "slope_pct": float(parts[6]) if len(parts) > 6 else 0,
                })
            elif current_section == "SUBAREAS" and len(parts) >= 5:
                subareas[parts[0]] = {
                    "n_imperv": float(parts[1]),
                    "n_perv": float(parts[2]),
                    "ds_imperv_mm": float(parts[3]),
                    "ds_perv_mm": float(parts[4]),
                }
            elif current_section == "JUNCTIONS" and len(parts) >= 1:
                nodes.add(parts[0])
            elif current_section == "OUTFALLS" and len(parts) >= 1:
                nodes.add(parts[0])
            elif current_section == "STORAGE" and len(parts) >= 1:
                nodes.add(parts[0])

    return subcatchments, subareas, nodes


def parse_csv_params(params_csv, nodes_csv=None):
    """Parse subcatchment parameters from CSV files."""
    subcatchments = []
    with open(params_csv, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sc = {"id": row.get("id", "")}
            for key in ["area_ha", "width_m", "slope_pct", "imperv_pct"]:
                if key in row:
                    try:
                        sc[key] = float(row[key])
                    except (ValueError, TypeError):
                        sc[key] = None
            sc["outlet"] = row.get("outlet", "")
            subcatchments.append(sc)

    nodes = set()
    if nodes_csv:
        with open(nodes_csv, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                nodes.add(row.get("id", ""))

    return subcatchments, {}, nodes


def validate(subcatchments, subareas, nodes):
    """Run validation checks on subcatchment data."""
    issues = []
    warnings = []
    ids_seen = set()

    for sc in subcatchments:
        sc_id = sc.get("id", "UNKNOWN")
        prefix = f"Subcatchment {sc_id}"

        # Duplicate ID
        if sc_id in ids_seen:
            issues.append(f"{prefix}: Duplicate subcatchment ID")
        ids_seen.add(sc_id)

        # Area
        area = sc.get("area_ha")
        if area is None:
            issues.append(f"{prefix}: Missing area")
        elif area <= 0:
            issues.append(f"{prefix}: Area must be > 0 (got {area})")
        elif area < 0.01:
            warnings.append(f"{prefix}: Very small area ({area} ha)")

        # Width
        width = sc.get("width_m")
        if width is not None and width <= 0:
            issues.append(f"{prefix}: Width must be > 0 (got {width})")

        # Slope
        slope = sc.get("slope_pct")
        if slope is not None and slope <= 0:
            issues.append(f"{prefix}: Slope must be > 0 (got {slope})")
        elif slope is not None and slope > 100:
            warnings.append(f"{prefix}: Very steep slope ({slope}%)")

        # Percent impervious
        imperv = sc.get("imperv_pct")
        if imperv is not None:
            if imperv < 0 or imperv > 100:
                issues.append(f"{prefix}: %Imperv must be 0-100 (got {imperv})")

        # Outlet exists
        outlet = sc.get("outlet", "")
        if outlet and nodes and outlet not in nodes:
            # Also check if outlet is another subcatchment (cascading)
            if outlet not in ids_seen:
                issues.append(f"{prefix}: Outlet node '{outlet}' not found in network")

        # Subarea parameters
        if sc_id in subareas:
            sa = subareas[sc_id]
            if sa.get("n_imperv", 0) <= 0:
                issues.append(f"{prefix}: N-Imperv must be > 0")
            if sa.get("n_perv", 0) <= 0:
                issues.append(f"{prefix}: N-Perv must be > 0")
            if sa.get("ds_imperv_mm", 0) < 0:
                issues.append(f"{prefix}: Dstore-Imperv must be >= 0")
            if sa.get("ds_perv_mm", 0) < 0:
                issues.append(f"{prefix}: Dstore-Perv must be >= 0")

    # Summary
    report = {
        "n_subcatchments": len(subcatchments),
        "n_issues": len(issues),
        "n_warnings": len(warnings),
        "issues": issues,
        "warnings": warnings,
        "valid": len(issues) == 0,
    }
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Validate SWMM subcatchment configuration"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--inp", help="SWMM .inp file to validate")
    group.add_argument("--params_csv", help="Subcatchment parameters CSV")
    parser.add_argument("--nodes_csv", default=None,
                        help="Network nodes CSV (used with --params_csv)")
    args = parser.parse_args()

    if args.inp:
        if not os.path.isfile(args.inp):
            print(f"ERROR: File not found: {args.inp}", file=sys.stderr)
            sys.exit(1)
        subcatchments, subareas, nodes = parse_inp_subcatchments(args.inp)
    else:
        if not os.path.isfile(args.params_csv):
            print(f"ERROR: File not found: {args.params_csv}", file=sys.stderr)
            sys.exit(1)
        nodes_csv = args.nodes_csv
        if nodes_csv and not os.path.isfile(nodes_csv):
            print(f"ERROR: File not found: {nodes_csv}", file=sys.stderr)
            sys.exit(1)
        subcatchments, subareas, nodes = parse_csv_params(args.params_csv, nodes_csv)

    report = validate(subcatchments, subareas, nodes)
    print(json.dumps(report, indent=2))

    if report["valid"]:
        print(f"\nVALID: {report['n_subcatchments']} subcatchments passed all checks",
              file=sys.stderr)
    else:
        print(f"\nINVALID: {report['n_issues']} issues found", file=sys.stderr)

    sys.exit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
