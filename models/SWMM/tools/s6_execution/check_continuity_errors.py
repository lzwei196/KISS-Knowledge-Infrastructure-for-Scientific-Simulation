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
import math
import os
import re
import sys


SECTION_TITLES = (
    ("Runoff Quantity Continuity", "runoff_continuity"),
    ("Flow Routing Continuity", "routing_continuity"),
    ("Quality Routing Continuity", "quality_continuity"),
    ("Node Flooding Summary", "flooding"),
    ("Conduit Surcharge Summary", "surcharging"),
    ("Link Surcharge Summary", "surcharging"),
    ("Outfall Loading Summary", "outfall_loading"),
)
CONTINUITY_KEYS = {"runoff_continuity": "runoff_error_pct",
                   "routing_continuity": "routing_error_pct",
                   "quality_continuity": "quality_error_pct"}


def is_heading(lines, index):
    """True when lines[index] is a section title boxed by '*' rule lines."""
    return (0 < index < len(lines) - 1
            and not lines[index].strip().startswith("***")
            and lines[index - 1].strip().startswith("***")
            and lines[index + 1].strip().startswith("***"))


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
        "continuity_sections": [],
        "continuity_errors": [],
        # Unit of the depth column in the runoff continuity table, as printed
        # by EPA report.c (report_writeRunoffError): "mm" (SI) or "inches" (US).
        "runoff_depth_units": None,
        "runoff_from_interface_file": False,
        "table_errors": [],
    }
    # Depth values are converted to mm; an unknown unit leaves them as None.
    depth_to_mm = None

    current_section = None
    flood_volume_units = None
    # Key of a continuity table whose "Continuity Error (%)" row has not been
    # read yet. Each block (e.g. each group of five pollutants) must have one.
    pending_balance = None
    expected_values = 1

    def close_block():
        if pending_balance is not None:
            results["continuity_errors"].append(
                f"Missing {pending_balance}: a continuity table has no Continuity Error row")

    # EPA writes raw single bytes such as 0xB3 ("cubed") in some table headers,
    # so the report is not valid UTF-8; latin-1 reads every byte.
    with open(rpt_path, "r", encoding="latin-1") as f:
        lines = f.read().splitlines()
    for index, line in enumerate(lines):
            line_stripped = line.strip()

            # EPA writes every section title between two '*' rule lines
            # (report.c / statsrpt.c), so only such a line can change the
            # section; a data row whose element ID contains a word like
            # "Summary" or "Continuity" cannot.
            if line_stripped.startswith("***"):
                continue
            if is_heading(lines, index):
                close_block()
                pending_balance = None
                current_section = None
                for title, section in SECTION_TITLES:
                    if line_stripped.startswith(title):
                        current_section = section
                        break
                key = CONTINUITY_KEYS.get(current_section)
                if key:
                    results["continuity_sections"].append(key)
                    pending_balance = key
                    # report_writeQualError writes one "    ----------" group per
                    # pollutant on the '*' line below the title (IDs above it
                    # use %14s with no separator, so long IDs can run
                    # together and cannot be counted). Each row has one value
                    # per pollutant; runoff and routing tables have one value.
                    expected_values = (lines[index + 1].count("----------")
                                       if key == "quality_error_pct" else 1)
                if current_section == "runoff_continuity":
                    header_tokens = line_stripped.split()
                    if header_tokens[-1:] == ["mm"]:
                        results["runoff_depth_units"], depth_to_mm = "mm", 1.0
                    elif header_tokens[-1:] == ["inches"]:
                        results["runoff_depth_units"], depth_to_mm = "inches", 25.4
                continue

            if (current_section == "runoff_continuity"
                    and line_stripped.startswith("Runoff supplied by interface file")):
                # report_writeRunoffError: with [FILES] USE RUNOFF the engine
                # prints this line and NO runoff balance. The balance is not
                # available; it is not required and no value is filled in.
                results["runoff_from_interface_file"] = True
                pending_balance = None
                if "runoff_error_pct" in results["continuity_sections"]:
                    results["continuity_sections"].remove("runoff_error_pct")
                continue

            if "Continuity Error (%)" in line and current_section in (
                    "runoff_continuity", "routing_continuity", "quality_continuity"):
                key = {"runoff_continuity": "runoff_error_pct",
                       "routing_continuity": "routing_error_pct",
                       "quality_continuity": "quality_error_pct"}[current_section]
                pending_balance = None
                try:
                    # EPA reports put '(%)' BEFORE the number, after a dotted leader.
                    tokens = line.split("(%)", 1)[1].strip().lstrip(".").split()
                    values = [float(token) for token in tokens]
                    if not values or not all(math.isfinite(v) for v in values):
                        raise ValueError("missing/non-finite continuity error")
                    if len(values) != expected_values:
                        raise ValueError(f"expected {expected_values} value(s), found {len(values)}")
                    worst = max(values, key=abs)
                    # EPA prints pollutants in blocks of five, each with its own
                    # "Continuity Error (%)" row: keep the worst over all blocks.
                    if results[key] is None or abs(worst) > abs(results[key]):
                        results[key] = worst
                except (ValueError, IndexError) as exc:
                    results["continuity_errors"].append(f"Invalid {key}: {line_stripped} ({exc})")
                continue

            # Parse continuity errors
            if current_section == "runoff_continuity":
                if "Total Precipitation" in line:
                    match = re.search(r"([\d.]+)\s*$", line_stripped)
                    if match and depth_to_mm is not None:
                        results["total_precipitation_mm"] = float(match.group(1)) * depth_to_mm
                elif "Total Runoff" in line or "Surface Runoff" in line:
                    match = re.search(r"([\d.]+)\s*$", line_stripped)
                    if match and depth_to_mm is not None:
                        results["total_runoff_mm"] = float(match.group(1)) * depth_to_mm
                elif "Total Infiltration" in line or "Infiltration Loss" in line:
                    match = re.search(r"([\d.]+)\s*$", line_stripped)
                    if match and depth_to_mm is not None:
                        results["total_infiltration_mm"] = float(match.group(1)) * depth_to_mm
                elif "Total Evaporation" in line or "Evaporation Loss" in line:
                    match = re.search(r"([\d.]+)\s*$", line_stripped)
                    if match and depth_to_mm is not None:
                        results["total_evaporation_mm"] = float(match.group(1)) * depth_to_mm
                elif "Peak Runoff" in line:
                    match = re.search(r"([\d.]+)", line_stripped.split("...")[-1] if "..." in line_stripped else line_stripped)
                    if match:
                        results["peak_runoff_cms"] = float(match.group(1))

            if current_section == "flooding":
                # statsrpt.c writeNodeFlooding row: ID, hours flooded, max rate,
                # days, hr:min, total flood volume, max ponded depth/volume.
                parts = line_stripped.split()
                if parts[:2] == ["Node", "Flooded"] and len(parts) >= 7:
                    flood_volume_units = " ".join(parts[5:7])
                elif len(parts) >= 2:
                    try:
                        float(parts[1])
                    except ValueError:
                        continue  # text/header line, not a node row
                    if len(parts) != 7:
                        # A node row we cannot split must not vanish silently.
                        results["table_errors"].append(f"Unreadable Node Flooding row: {line_stripped}")
                    else:
                        results["flooded_nodes"].append({
                            "node_id": parts[0],
                            "hours_flooded": parts[1],
                            "max_rate": parts[2],
                            "time_of_max": " ".join(parts[3:5]),
                            "total_volume": parts[5],
                            "total_volume_units": flood_volume_units,
                            "max_ponded": parts[6],
                        })

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
            # EPA diagnostics start with ERROR/WARNING; table columns such as
            # the LID continuity "Error" heading are not engine failures.
            if re.match(r"ERROR(?:\s+\d+)?\s*:", line_stripped, re.I):
                results["simulation_errors"].append(line_stripped)
            elif re.match(r"WARNING(?:\s+\d+)?\s*:", line_stripped, re.I):
                results["simulation_warnings"].append(line_stripped)

    close_block()
    return results


def determine_verdict(results, threshold):
    """Determine PASS/WARN/FAIL verdict."""
    sections = results.get("continuity_sections", [])
    if (not sections or results.get("continuity_errors") or any(
            results.get(key) is None or not math.isfinite(results[key]) for key in sections)):
        return "FAIL", "Continuity balance is missing, unreadable, or non-finite"
    # Every balance the report printed counts, including quality routing
    # (missing ones already returned FAIL above).
    max_err = max(abs(results[key]) for key in sections)

    if results["simulation_errors"]:
        return "FAIL", f"Simulation errors found: {len(results['simulation_errors'])}"
    elif results.get("table_errors"):
        return "FAIL", f"Unreadable report table rows: {len(results['table_errors'])}"
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
        "continuity_errors": results["continuity_errors"],
        "table_errors": results["table_errors"],
        "runoff_from_interface_file": results["runoff_from_interface_file"],
        "hydrology_summary": {
            "total_precipitation_mm": results["total_precipitation_mm"],
            "total_runoff_mm": results["total_runoff_mm"],
            "total_infiltration_mm": results["total_infiltration_mm"],
            "total_evaporation_mm": results["total_evaporation_mm"],
            "peak_runoff_cms": results["peak_runoff_cms"],
            "report_depth_units": results["runoff_depth_units"],
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
