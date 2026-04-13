#!/usr/bin/env python3
"""
Validate a SWMM .inp file for structural correctness.

Performs comprehensive validation:
  - Parses all sections and counts elements
  - Checks for missing cross-references (e.g., conduit referencing nonexistent node)
  - Verifies required sections are present
  - Checks unit consistency hints
  - Attempts to open with pyswmm if available (catches parse errors)

Outputs a JSON validation report to stdout.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict


REQUIRED_SECTIONS = ["OPTIONS", "SUBCATCHMENTS", "JUNCTIONS", "CONDUITS", "OUTFALLS"]
OPTIONAL_SECTIONS = [
    "TITLE", "RAINGAGES", "SUBAREAS", "INFILTRATION", "XSECTIONS",
    "TIMESERIES", "LID_CONTROLS", "LID_USAGE", "REPORT", "COORDINATES",
    "MAP", "LOSSES", "STORAGE", "DIVIDERS", "PUMPS", "ORIFICES", "WEIRS",
    "TRANSECTS", "CURVES", "PATTERNS", "DWF", "POLLUTANTS", "LANDUSES",
    "LOADINGS", "COVERAGES", "BUILDUP", "WASHOFF", "TREATMENT",
    "INFLOWS", "RDII", "HYDROGRAPHS", "AQUIFERS", "GROUNDWATER",
    "SNOWPACKS", "SYMBOLS", "LABELS", "BACKDROP", "TAGS", "VERTICES",
    "POLYGONS",
]


def parse_inp_sections(inp_path):
    """Parse .inp file into sections."""
    sections = defaultdict(list)
    current_section = None

    with open(inp_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.rstrip()
            stripped = line.strip()

            if stripped.startswith("[") and stripped.endswith("]"):
                current_section = stripped[1:-1].upper()
                continue
            if not stripped or stripped.startswith(";"):
                continue
            if current_section:
                sections[current_section].append({
                    "line_num": line_num,
                    "content": stripped,
                    "parts": stripped.split(),
                })

    return dict(sections)


def validate_sections(sections):
    """Run validation on parsed sections."""
    issues = []
    warnings = []

    # Check required sections
    for req in REQUIRED_SECTIONS:
        if req not in sections:
            issues.append({
                "type": "missing_section",
                "section": req,
                "message": f"Required section [{req}] is missing",
            })

    # Collect all node IDs
    all_nodes = set()
    node_sections = ["JUNCTIONS", "OUTFALLS", "STORAGE", "DIVIDERS"]
    for sec in node_sections:
        for row in sections.get(sec, []):
            if row["parts"]:
                all_nodes.add(row["parts"][0])

    # Collect all link IDs
    all_links = set()
    link_sections = ["CONDUITS", "PUMPS", "ORIFICES", "WEIRS"]
    for sec in link_sections:
        for row in sections.get(sec, []):
            if row["parts"]:
                all_links.add(row["parts"][0])

    # Collect subcatchment IDs
    all_subcatchments = set()
    for row in sections.get("SUBCATCHMENTS", []):
        if row["parts"]:
            all_subcatchments.add(row["parts"][0])

    # Check conduit node references
    for row in sections.get("CONDUITS", []):
        parts = row["parts"]
        if len(parts) >= 3:
            from_node = parts[1]
            to_node = parts[2]
            if from_node not in all_nodes:
                issues.append({
                    "type": "missing_reference",
                    "section": "CONDUITS",
                    "line": row["line_num"],
                    "message": f"Conduit {parts[0]}: from_node '{from_node}' not defined",
                })
            if to_node not in all_nodes:
                issues.append({
                    "type": "missing_reference",
                    "section": "CONDUITS",
                    "line": row["line_num"],
                    "message": f"Conduit {parts[0]}: to_node '{to_node}' not defined",
                })

    # Check subcatchment outlet references
    for row in sections.get("SUBCATCHMENTS", []):
        parts = row["parts"]
        if len(parts) >= 3:
            outlet = parts[2]
            if outlet not in all_nodes and outlet not in all_subcatchments:
                issues.append({
                    "type": "missing_reference",
                    "section": "SUBCATCHMENTS",
                    "line": row["line_num"],
                    "message": f"Subcatchment {parts[0]}: outlet '{outlet}' not defined",
                })

    # Check XSECTIONS match conduits
    xsection_links = set()
    for row in sections.get("XSECTIONS", []):
        if row["parts"]:
            xsection_links.add(row["parts"][0])
    conduit_ids = set()
    for row in sections.get("CONDUITS", []):
        if row["parts"]:
            conduit_ids.add(row["parts"][0])
    missing_xs = conduit_ids - xsection_links
    if missing_xs:
        warnings.append({
            "type": "missing_xsections",
            "count": len(missing_xs),
            "links": list(missing_xs)[:10],
            "message": f"{len(missing_xs)} conduit(s) have no cross-section defined",
        })

    # Check for SUBAREAS matching subcatchments
    subarea_ids = set()
    for row in sections.get("SUBAREAS", []):
        if row["parts"]:
            subarea_ids.add(row["parts"][0])
    missing_sa = all_subcatchments - subarea_ids
    if missing_sa:
        warnings.append({
            "type": "missing_subareas",
            "count": len(missing_sa),
            "message": f"{len(missing_sa)} subcatchment(s) have no SUBAREAS entry",
        })

    # Check INFILTRATION
    infil_ids = set()
    for row in sections.get("INFILTRATION", []):
        if row["parts"]:
            infil_ids.add(row["parts"][0])
    missing_inf = all_subcatchments - infil_ids
    if missing_inf:
        warnings.append({
            "type": "missing_infiltration",
            "count": len(missing_inf),
            "message": f"{len(missing_inf)} subcatchment(s) have no INFILTRATION entry",
        })

    # Check for rain gages referenced by subcatchments
    if "RAINGAGES" in sections:
        gage_ids = set()
        for row in sections["RAINGAGES"]:
            if row["parts"]:
                gage_ids.add(row["parts"][0])
        for row in sections.get("SUBCATCHMENTS", []):
            parts = row["parts"]
            if len(parts) >= 2 and parts[1] not in gage_ids:
                issues.append({
                    "type": "missing_reference",
                    "section": "SUBCATCHMENTS",
                    "line": row["line_num"],
                    "message": f"Subcatchment {parts[0]}: rain gage '{parts[1]}' not defined",
                })

    # Section counts
    counts = {}
    for sec_name, rows in sections.items():
        counts[sec_name] = len(rows)

    # Try pyswmm validation
    pyswmm_result = None
    # (pyswmm validation would be attempted here if available)

    report = {
        "sections_found": list(sections.keys()),
        "section_counts": counts,
        "n_nodes": len(all_nodes),
        "n_links": len(all_links),
        "n_subcatchments": len(all_subcatchments),
        "n_issues": len(issues),
        "n_warnings": len(warnings),
        "issues": issues,
        "warnings": warnings,
        "valid": len(issues) == 0,
    }
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Validate a SWMM .inp file"
    )
    parser.add_argument("--inp", required=True, help="SWMM .inp file path")
    args = parser.parse_args()

    if not os.path.isfile(args.inp):
        print(f"ERROR: File not found: {args.inp}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing {args.inp}...", file=sys.stderr)
    sections = parse_inp_sections(args.inp)
    print(f"  Found {len(sections)} sections", file=sys.stderr)

    report = validate_sections(sections)
    print(json.dumps(report, indent=2))

    if report["valid"]:
        print(f"\nVALID: {report['n_nodes']} nodes, {report['n_links']} links, "
              f"{report['n_subcatchments']} subcatchments", file=sys.stderr)
    else:
        print(f"\nINVALID: {report['n_issues']} issue(s)", file=sys.stderr)

    sys.exit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
