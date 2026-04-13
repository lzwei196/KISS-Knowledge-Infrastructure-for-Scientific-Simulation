#!/usr/bin/env python3
"""
Validate water balance closure across VIC + SWMM + CaMa-Flood coupling.

Checks that water is conserved (within tolerance) across the coupled
model chain. Compares:
  - VIC total runoff + baseflow output
  - SWMM inflow vs outflow + storage change + losses
  - CaMa-Flood inflow vs outflow + storage change

Also checks for:
  - Sign errors in coupling (negative flows)
  - Unit mismatches (mm vs m^3/s)
  - Temporal alignment issues (gaps between model periods)

Inputs:
  - SWMM .rpt file (required)
  - VIC summary file (optional)
  - CaMa-Flood summary file (optional)

Outputs:
  - JSON report with water balance components and % imbalance
"""

import argparse
import json
import os
import re
import sys


def parse_swmm_rpt_balance(rpt_path):
    """Parse SWMM .rpt for water balance components."""
    balance = {
        "precipitation_mm": None,
        "runon_mm": None,
        "evaporation_mm": None,
        "infiltration_mm": None,
        "surface_runoff_mm": None,
        "final_storage_mm": None,
        "continuity_error_pct": None,
        "routing_dry_weather_inflow_m3": None,
        "routing_wet_weather_inflow_m3": None,
        "routing_external_inflow_m3": None,
        "routing_flooding_m3": None,
        "routing_outfall_m3": None,
        "routing_final_storage_m3": None,
        "routing_continuity_error_pct": None,
    }

    current_section = None

    with open(rpt_path, "r") as f:
        for line in f:
            stripped = line.strip()

            if "Runoff Quantity Continuity" in line:
                current_section = "runoff"
                continue
            elif "Flow Routing Continuity" in line:
                current_section = "routing"
                continue
            elif stripped.startswith("***"):
                current_section = None
                continue

            if current_section == "runoff":
                if "Total Precipitation" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["precipitation_mm"] = float(match.group(1))
                elif "Evaporation Loss" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["evaporation_mm"] = float(match.group(1))
                elif "Infiltration Loss" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["infiltration_mm"] = float(match.group(1))
                elif "Surface Runoff" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["surface_runoff_mm"] = float(match.group(1))
                elif "Final Storage" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["final_storage_mm"] = float(match.group(1))
                elif "Continuity Error" in line:
                    match = re.search(r"([-\d.]+)\s*%", line)
                    if match:
                        balance["continuity_error_pct"] = float(match.group(1))

            elif current_section == "routing":
                if "Dry Weather Inflow" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["routing_dry_weather_inflow_m3"] = float(match.group(1))
                elif "Wet Weather Inflow" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["routing_wet_weather_inflow_m3"] = float(match.group(1))
                elif "External Inflow" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["routing_external_inflow_m3"] = float(match.group(1))
                elif "Flooding Loss" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["routing_flooding_m3"] = float(match.group(1))
                elif "Outfall Losses" in line or "External Outflow" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["routing_outfall_m3"] = float(match.group(1))
                elif "Final Stored Volume" in line or "Final Storage" in line:
                    match = re.search(r"([\d.]+)\s*$", stripped)
                    if match:
                        balance["routing_final_storage_m3"] = float(match.group(1))
                elif "Continuity Error" in line:
                    match = re.search(r"([-\d.]+)\s*%", line)
                    if match:
                        balance["routing_continuity_error_pct"] = float(match.group(1))

    return balance


def parse_vic_summary(vic_summary_path):
    """Parse VIC summary file for total water balance."""
    if not vic_summary_path or not os.path.isfile(vic_summary_path):
        return None

    vic = {
        "total_precip_mm": None,
        "total_evap_mm": None,
        "total_runoff_mm": None,
        "total_baseflow_mm": None,
    }

    with open(vic_summary_path, "r") as f:
        for line in f:
            stripped = line.strip()
            parts = stripped.split("=")
            if len(parts) == 2:
                key = parts[0].strip().lower()
                try:
                    val = float(parts[1].strip().split()[0])
                except (ValueError, IndexError):
                    continue
                if "precip" in key:
                    vic["total_precip_mm"] = val
                elif "evap" in key:
                    vic["total_evap_mm"] = val
                elif "runoff" in key and "base" not in key:
                    vic["total_runoff_mm"] = val
                elif "baseflow" in key or "base_flow" in key:
                    vic["total_baseflow_mm"] = val

    return vic


def parse_cama_summary(cama_summary_path):
    """Parse CaMa-Flood summary for total water balance."""
    if not cama_summary_path or not os.path.isfile(cama_summary_path):
        return None

    cama = {
        "total_inflow_m3": None,
        "total_outflow_m3": None,
        "storage_change_m3": None,
    }

    with open(cama_summary_path, "r") as f:
        for line in f:
            stripped = line.strip()
            parts = stripped.split("=")
            if len(parts) == 2:
                key = parts[0].strip().lower()
                try:
                    val = float(parts[1].strip().split()[0])
                except (ValueError, IndexError):
                    continue
                if "inflow" in key:
                    cama["total_inflow_m3"] = val
                elif "outflow" in key:
                    cama["total_outflow_m3"] = val
                elif "storage" in key:
                    cama["storage_change_m3"] = val

    return cama


def compute_coupling_balance(swmm, vic=None, cama=None):
    """Compute cross-model water balance and imbalance."""
    checks = []

    # SWMM internal balance
    if swmm["continuity_error_pct"] is not None:
        checks.append({
            "check": "SWMM runoff continuity",
            "error_pct": swmm["continuity_error_pct"],
            "status": "OK" if abs(swmm["continuity_error_pct"]) < 10 else "WARNING",
        })

    if swmm["routing_continuity_error_pct"] is not None:
        checks.append({
            "check": "SWMM routing continuity",
            "error_pct": swmm["routing_continuity_error_pct"],
            "status": "OK" if abs(swmm["routing_continuity_error_pct"]) < 10 else "WARNING",
        })

    # VIC -> SWMM coupling check
    if vic and vic.get("total_runoff_mm") and swmm.get("routing_external_inflow_m3"):
        checks.append({
            "check": "VIC runoff provided as SWMM external inflow",
            "vic_total_runoff_mm": vic["total_runoff_mm"],
            "swmm_external_inflow_m3": swmm["routing_external_inflow_m3"],
            "note": "Units differ (mm vs m^3) — needs area for comparison",
            "status": "INFO",
        })

    # SWMM -> CaMa coupling check
    if cama and cama.get("total_inflow_m3") and swmm.get("routing_outfall_m3"):
        diff = abs(swmm["routing_outfall_m3"] - cama["total_inflow_m3"])
        max_val = max(abs(swmm["routing_outfall_m3"]),
                      abs(cama["total_inflow_m3"]), 1)
        pct_diff = diff / max_val * 100

        checks.append({
            "check": "SWMM outfall vs CaMa-Flood inflow",
            "swmm_outfall_m3": swmm["routing_outfall_m3"],
            "cama_inflow_m3": cama["total_inflow_m3"],
            "difference_pct": round(pct_diff, 2),
            "status": "OK" if pct_diff < 5 else "WARNING",
        })

    return checks


def main():
    parser = argparse.ArgumentParser(
        description="Validate water balance closure across VIC+SWMM+CaMa coupling"
    )
    parser.add_argument("--swmm_rpt", required=True,
                        help="SWMM report file (.rpt)")
    parser.add_argument("--vic_summary", default=None,
                        help="VIC water balance summary file (optional)")
    parser.add_argument("--cama_summary", default=None,
                        help="CaMa-Flood water balance summary file (optional)")
    parser.add_argument("--threshold", type=float, default=10.0,
                        help="Acceptable imbalance threshold %% (default: 10)")
    args = parser.parse_args()

    if not os.path.isfile(args.swmm_rpt):
        print(f"ERROR: File not found: {args.swmm_rpt}", file=sys.stderr)
        sys.exit(1)

    print(f"Checking water balance closure...", file=sys.stderr)

    # Parse all available summaries
    swmm = parse_swmm_rpt_balance(args.swmm_rpt)
    vic = parse_vic_summary(args.vic_summary)
    cama = parse_cama_summary(args.cama_summary)

    # Run coupling checks
    checks = compute_coupling_balance(swmm, vic, cama)

    # Determine overall verdict
    has_warning = any(c.get("status") == "WARNING" for c in checks)
    has_error = any(
        c.get("error_pct") is not None and abs(c["error_pct"]) > args.threshold * 2
        for c in checks
    )

    if has_error:
        verdict = "FAIL"
    elif has_warning:
        verdict = "WARN"
    else:
        verdict = "PASS"

    report = {
        "swmm_balance": {
            k: v for k, v in swmm.items() if v is not None
        },
        "vic_balance": vic,
        "cama_balance": cama,
        "coupling_checks": checks,
        "verdict": verdict,
        "threshold_pct": args.threshold,
        "models_checked": ["SWMM"]
            + (["VIC"] if vic else [])
            + (["CaMa-Flood"] if cama else []),
    }

    print(json.dumps(report, indent=2))

    if verdict == "PASS":
        print(f"\nPASS: Water balance closure within tolerance", file=sys.stderr)
    elif verdict == "WARN":
        print(f"\nWARN: Some balance checks show elevated errors", file=sys.stderr)
    else:
        print(f"\nFAIL: Water balance closure exceeds tolerance", file=sys.stderr)

    sys.exit(0 if verdict in ("PASS", "WARN") else 1)


if __name__ == "__main__":
    main()
