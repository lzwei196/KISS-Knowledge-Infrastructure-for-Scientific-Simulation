#!/usr/bin/env python3
"""
Check SWMM simulation continuity errors from the .rpt report file.

Parses the SWMM report file and extracts:
  - Runoff quantity continuity error (%)
  - Flow routing continuity error (%)
  - Flooding summary (which nodes flooded, volumes)
  - Surcharging summary (which conduits surcharged)
  - Timestep critical events summary

Provides a verdict: PASS/WARN/FAIL based on error thresholds.
  - PASS: errors < threshold (default 10%)
  - WARN: errors between threshold and 2x threshold
  - FAIL: errors > 2x threshold or simulation errors

Outputs a JSON report to stdout.
"""

import argparse
import json
import os
import re
import sys


def parse_rpt_file(rpt_path):
    """Parse SWMM .rpt file for continuity errors and summaries."""
    results = {
        "runoff_error_pct": None,
        "routing_error_pct": None,
        "quality_error_pct": None,
        "total_precipitation_mm": None,
        "total_runoff_mm": None,
        "total_infiltration_mm": None,
        "total_evaporation_mm": None,
        "peak_runoff_cms": None,
        "flooded_nodes": [],
        "surcharging_links": [],
        "outfall_loading": [],
        "simulation_errors": [],
        "simulation_warnings": [],
    }

    current_section = None
    skip_header_lines = 0

    with open(rpt_path, "r") as f:
        for line in f:
            line_stripped = line.strip()

            # Track sections
            if "Runoff Quantity Continuity" in line:
                current_section = "runoff_continuity"
                continue
            elif "Flow Routing Continuity" in line:
                current_section = "routing_continuity"
                continue
            elif "Quality Routing Continuity" in line:
                current_section = "quality_continuity"
                continue
            elif "Node Flooding Summary" in line:
                current_section = "flooding"
                skip_header_lines = 4
                continue
            elif "Conduit Surcharge Summary" in line or "Link Surcharge Summary" in line:
                current_section = "surcharging"
                skip_header_lines = 4
                continue
            elif "Outfall Loading Summary" in line:
                current_section = "outfall_loading"
                skip_header_lines = 4
                continue
            elif line_stripped.startswith("***"):
                current_section = None
                continue

            if skip_header_lines > 0:
                skip_header_lines -= 1
                continue

            # Parse continuity errors
            if current_section == "runoff_continuity":
                if "Continuity Error" in line and "%" in line:
                    match = re.search(r"([-\d.]+)\s*%", line)
                    if match:
                        results["runoff_error_pct"] = float(match.group(1))
                elif "Total Precipitation" in line:
                    match = re.search(r"([\d.]+)\s*$", line_stripped)
                    if match:
                        results["total_precipitation_mm"] = float(match.group(1))
                elif "Total Runoff" in line:
                    match = re.search(r"([\d.]+)\s*$", line_stripped)
                    if match:
                        results["total_runoff_mm"] = float(match.group(1))
                elif "Total Infiltration" in line:
                    match = re.search(r"([\d.]+)\s*$", line_stripped)
                    if match:
                        results["total_infiltration_mm"] = float(match.group(1))
                elif "Total Evaporation" in line:
                    match = re.search(r"([\d.]+)\s*$", line_stripped)
                    if match:
                        results["total_evaporation_mm"] = float(match.group(1))
                elif "Peak Runoff" in line:
                    match = re.search(r"([\d.]+)", line_stripped.split("...")[-1] if "..." in line_stripped else line_stripped)
                    if match:
                        results["peak_runoff_cms"] = float(match.group(1))

            elif current_section == "routing_continuity":
                if "Continuity Error" in line and "%" in line:
                    match = re.search(r"([-\d.]+)\s*%", line)
                    if match:
                        results["routing_error_pct"] = float(match.group(1))

            elif current_section == "quality_continuity":
                if "Continuity Error" in line and "%" in line:
                    match = re.search(r"([-\d.]+)\s*%", line)
                    if match:
                        results["quality_error_pct"] = float(match.group(1))

            elif current_section == "flooding":
                if line_stripped and not line_stripped.startswith("-"):
                    parts = line_stripped.split()
                    if len(parts) >= 3 and parts[0] not in ("No", "Node", "Flooding"):
                        try:
                            float(parts[1])  # test if numeric
                            results["flooded_nodes"].append({
                                "node_id": parts[0],
                                "hours_flooded": parts[1] if len(parts) > 1 else "",
                                "max_rate": parts[2] if len(parts) > 2 else "",
                                "total_volume": parts[3] if len(parts) > 3 else "",
                            })
                        except (ValueError, IndexError):
                            pass

            elif current_section == "surcharging":
                if line_stripped and not line_stripped.startswith("-"):
                    parts = line_stripped.split()
                    if len(parts) >= 2 and parts[0] not in ("No", "Conduit", "Link"):
                        try:
                            float(parts[1])
                            results["surcharging_links"].append({
                                "link_id": parts[0],
                                "hours_surcharged": parts[1] if len(parts) > 1 else "",
                            })
                        except (ValueError, IndexError):
                            pass

            # Catch simulation errors/warnings
            if "ERROR" in line.upper() and "Continuity Error" not in line:
                results["simulation_errors"].append(line_stripped)
            elif "WARNING" in line.upper():
                results["simulation_warnings"].append(line_stripped)

    return results


def determine_verdict(results, threshold):
    """Determine PASS/WARN/FAIL verdict."""
    runoff_err = abs(results.get("runoff_error_pct") or 0)
    routing_err = abs(results.get("routing_error_pct") or 0)
    max_err = max(runoff_err, routing_err)

    if results["simulation_errors"]:
        return "FAIL", f"Simulation errors found: {len(results['simulation_errors'])}"
    elif max_err > threshold * 2:
        return "FAIL", f"Continuity error {max_err:.2f}% exceeds 2x threshold ({threshold*2}%)"
    elif max_err > threshold:
        return "WARN", f"Continuity error {max_err:.2f}% exceeds threshold ({threshold}%)"
    elif results["flooded_nodes"]:
        return "WARN", f"{len(results['flooded_nodes'])} node(s) experienced flooding"
    else:
        return "PASS", "All checks passed"


def main():
    parser = argparse.ArgumentParser(
        description="Check SWMM simulation continuity errors from .rpt file"
    )
    parser.add_argument("--rpt", required=True, help="SWMM report file (.rpt)")
    parser.add_argument("--threshold", type=float, default=10.0,
                        help="Continuity error threshold %% (default: 10)")
    args = parser.parse_args()

    if not os.path.isfile(args.rpt):
        print(f"ERROR: Report file not found: {args.rpt}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing {args.rpt}...", file=sys.stderr)
    results = parse_rpt_file(args.rpt)

    verdict, reason = determine_verdict(results, args.threshold)

    report = {
        "runoff_error_pct": results["runoff_error_pct"],
        "routing_error_pct": results["routing_error_pct"],
        "quality_error_pct": results["quality_error_pct"],
        "n_flooded": len(results["flooded_nodes"]),
        "n_surcharged": len(results["surcharging_links"]),
        "n_errors": len(results["simulation_errors"]),
        "n_warnings": len(results["simulation_warnings"]),
        "flooded_nodes": results["flooded_nodes"],
        "surcharging_links": results["surcharging_links"],
        "simulation_errors": results["simulation_errors"],
        "hydrology_summary": {
            "total_precipitation_mm": results["total_precipitation_mm"],
            "total_runoff_mm": results["total_runoff_mm"],
            "total_infiltration_mm": results["total_infiltration_mm"],
            "total_evaporation_mm": results["total_evaporation_mm"],
            "peak_runoff_cms": results["peak_runoff_cms"],
        },
        "verdict": verdict,
        "reason": reason,
        "threshold_pct": args.threshold,
    }

    print(json.dumps(report, indent=2))

    if verdict == "PASS":
        print(f"\nPASS: {reason}", file=sys.stderr)
    elif verdict == "WARN":
        print(f"\nWARN: {reason}", file=sys.stderr)
    else:
        print(f"\nFAIL: {reason}", file=sys.stderr)

    sys.exit(0 if verdict in ("PASS", "WARN") else 1)


if __name__ == "__main__":
    main()
