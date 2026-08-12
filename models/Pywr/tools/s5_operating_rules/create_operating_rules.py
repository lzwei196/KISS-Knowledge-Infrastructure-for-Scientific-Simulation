#!/usr/bin/env python3
"""
create_operating_rules.py — Generate reservoir operating rules as Pywr parameters.

Generates monthly control curves and release rules based on:
- Reservoir purpose (flood_control, irrigation, hydropower, multipurpose)
- Regional flood/dry season definition
- Reservoir capacity and dam height

Usage:
    python create_operating_rules.py \
        --reservoir_json reservoir_props.json \
        --purpose multipurpose \
        --region china_east \
        --output operating_rules.json

    python create_operating_rules.py \
        --capacity_mcm 2275 --dam_height_m 88 \
        --purpose flood_control \
        --flood_months 6,7,8,9 \
        --output operating_rules.json

Output:
    JSON with Pywr parameter definitions (ControlCurveParameter, MonthlyProfileParameter).
    Exit codes: 0 = success, 2 = input error, 3 = runtime error
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np


# ── Regional flood season definitions ──
FLOOD_SEASONS = {
    "china_east": {"flood_months": [6, 7, 8, 9], "name": "East China (Meiyu + typhoon)"},
    "china_north": {"flood_months": [7, 8, 9], "name": "North China (summer monsoon)"},
    "china_south": {"flood_months": [4, 5, 6, 7, 8, 9], "name": "South China (long wet season)"},
    "china_west": {"flood_months": [6, 7, 8, 9], "name": "West China / Tibetan Plateau"},
    "tropical": {"flood_months": [5, 6, 7, 8, 9, 10], "name": "Tropical (wet season)"},
    "temperate_nh": {"flood_months": [3, 4, 5, 6], "name": "Temperate NH (snowmelt + spring rain)"},
    "default": {"flood_months": [6, 7, 8, 9], "name": "Default (June-September)"},
}


def get_monthly_control_curve(purpose, flood_months, capacity_m3):
    """
    Generate monthly target storage levels as fraction of capacity.

    Flood control: low during flood season (reserve capacity for flood retention)
    Irrigation: high before irrigation season, drawn down during
    Hydropower: keep as full as possible (maximize head)
    Multipurpose: compromise between flood control and supply
    """
    # Initialize all months at 80% capacity
    monthly_targets = [0.80] * 12  # Jan=0..Dec=11

    flood_set = set(m - 1 for m in flood_months)  # Convert to 0-indexed

    if purpose == "flood_control":
        for i in range(12):
            if i in flood_set:
                monthly_targets[i] = 0.55  # Reserve 45% for flood storage
            else:
                monthly_targets[i] = 0.85  # Fill up outside flood season
        # Pre-drawdown: month before flood season
        pre_flood = min(flood_set)
        if pre_flood > 0:
            monthly_targets[pre_flood - 1] = 0.70
        # Post-flood refill
        post_flood = max(flood_set) + 1
        if post_flood < 12:
            monthly_targets[post_flood] = 0.75

    elif purpose == "irrigation":
        # Fill before dry season, draw down during
        dry_set = set(range(12)) - flood_set
        for i in range(12):
            if i in flood_set:
                monthly_targets[i] = 0.85  # Wet season: filling
            else:
                monthly_targets[i] = 0.60  # Dry season: drawing down

    elif purpose == "hydropower":
        # Keep as full as possible, slight drawdown during flood peak
        for i in range(12):
            if i in flood_set:
                monthly_targets[i] = 0.80  # Slight reserve
            else:
                monthly_targets[i] = 0.95  # Near full for maximum head

    elif purpose == "multipurpose":
        # Compromise: moderate flood reserve, adequate supply
        for i in range(12):
            if i in flood_set:
                monthly_targets[i] = 0.65
            else:
                monthly_targets[i] = 0.85
        # Extra drawdown during peak flood month
        peak_flood = flood_months[len(flood_months) // 2] - 1
        monthly_targets[peak_flood] = 0.55

    else:
        raise ValueError(f"Unknown purpose '{purpose}'. "
                         f"Use: flood_control, irrigation, hydropower, multipurpose")

    # Convert fraction to volume (m3)
    monthly_volumes = [round(f * capacity_m3, 0) for f in monthly_targets]

    return monthly_targets, monthly_volumes


def build_pywr_parameters(name, purpose, monthly_targets, monthly_volumes,
                          capacity_m3, min_volume_m3, flood_months):
    """Build Pywr parameter definitions for operating rules."""

    node_name = name.replace(" ", "_")

    parameters = {}

    # 1. Monthly control curve (target storage as fraction)
    parameters[f"{node_name}_control_curve"] = {
        "type": "monthlyprofile",
        "values": monthly_targets,
        "comment": f"Monthly target storage fraction for {purpose} operation"
    }

    # 2. Monthly control curve in volume (m3)
    parameters[f"{node_name}_target_volume"] = {
        "type": "monthlyprofile",
        "values": monthly_volumes,
        "comment": "Monthly target storage volume (m3)"
    }

    # 3. Flood season indicator (1 during flood, 0 otherwise)
    flood_indicator = [1 if (m + 1) in flood_months else 0 for m in range(12)]
    parameters[f"{node_name}_flood_season"] = {
        "type": "monthlyprofile",
        "values": flood_indicator,
        "comment": "Flood season indicator (1=flood, 0=dry)"
    }

    # 4. Maximum release profile (m3/s)
    # During flood season: higher max release (flood discharge)
    # During dry season: moderate release (minimum flow + supply)
    base_release = capacity_m3 / (365.25 * 86400)  # Mean annual release ≈ capacity/year
    max_release_profile = []
    for m in range(12):
        if (m + 1) in flood_months:
            max_release_profile.append(round(base_release * 3.0, 2))  # 3x during flood
        else:
            max_release_profile.append(round(base_release * 1.0, 2))  # 1x during dry

    parameters[f"{node_name}_max_release_m3s"] = {
        "type": "monthlyprofile",
        "values": max_release_profile,
        "comment": "Maximum release rate (m3/s) by month"
    }

    # 5. Minimum release (environmental flow, 10% of mean)
    min_release = round(base_release * 0.10, 4)
    parameters[f"{node_name}_min_release_m3s"] = {
        "type": "constant",
        "value": min_release,
        "comment": "Minimum environmental release (m3/s)"
    }

    # 6. Control curve index parameter (for Pywr ControlCurveParameter)
    # Above curve: prefer releasing (cost > 0) to maintain target
    # Below curve: prefer storing (cost < 0) to refill
    # NOTE: above_curve_cost MUST exceed the magnitude of the downstream release
    # benefit (assemble_pywr_model builds the downstream output node with cost=-10),
    # otherwise the LP will keep releasing water past the target and the control
    # curve never "holds" the reservoir at its monthly level (see triplet dt_pywr_006).
    parameters[f"{node_name}_above_curve_cost"] = {
        "type": "constant",
        "value": 50.0,
        "comment": "Cost when storage is above control curve (encourage release; must exceed |downstream cost|=10)"
    }
    parameters[f"{node_name}_below_curve_cost"] = {
        "type": "constant",
        "value": -500.0,
        "comment": "Cost when storage is below control curve (encourage filling)"
    }

    return parameters


def build_rule_curves_visualization_data(monthly_targets, flood_months, capacity_m3):
    """Build data for plotting rule curves."""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    viz = []
    for i, (month, target) in enumerate(zip(months, monthly_targets)):
        viz.append({
            "month": month,
            "month_num": i + 1,
            "target_fraction": target,
            "target_volume_mcm": round(target * capacity_m3 / 1e6, 1),
            "is_flood_season": (i + 1) in flood_months,
        })
    return viz


def main():
    parser = argparse.ArgumentParser(
        description="Generate reservoir operating rules for Pywr"
    )

    parser.add_argument("--reservoir_json", type=str, default=None,
                        help="Reservoir properties JSON from build_reservoir_properties.py")
    parser.add_argument("--capacity_mcm", type=float, default=None,
                        help="Reservoir capacity in MCM (manual override)")
    parser.add_argument("--dam_height_m", type=float, default=None,
                        help="Dam height in meters (manual override)")
    parser.add_argument("--name", type=str, default="reservoir",
                        help="Reservoir name (default: reservoir)")

    parser.add_argument("--purpose", type=str, default="multipurpose",
                        choices=["flood_control", "irrigation", "hydropower", "multipurpose"],
                        help="Reservoir purpose (default: multipurpose)")
    parser.add_argument("--region", type=str, default="default",
                        choices=list(FLOOD_SEASONS.keys()),
                        help="Regional flood season definition")
    parser.add_argument("--flood_months", type=str, default=None,
                        help="Custom flood months (comma-separated, e.g., '6,7,8,9')")

    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path (default: stdout)")

    args = parser.parse_args()

    try:
        # Load capacity
        if args.reservoir_json:
            with open(args.reservoir_json, "r") as f:
                res_data = json.load(f)
            capacity_mcm = res_data["storage"]["max_volume_mcm"]
            min_volume_m3 = res_data["storage"]["min_volume_m3"]
            name = res_data.get("name", args.name)
        elif args.capacity_mcm:
            capacity_mcm = args.capacity_mcm
            min_volume_m3 = capacity_mcm * 1e6 * 0.10
            name = args.name
        else:
            print(json.dumps({"error": "Provide --reservoir_json or --capacity_mcm"}))
            sys.exit(2)

        capacity_m3 = capacity_mcm * 1e6

        # Determine flood season
        if args.flood_months:
            flood_months = [int(m.strip()) for m in args.flood_months.split(",")]
        else:
            flood_months = FLOOD_SEASONS[args.region]["flood_months"]

        # Generate control curves
        monthly_targets, monthly_volumes = get_monthly_control_curve(
            args.purpose, flood_months, capacity_m3
        )

        # Build Pywr parameters
        parameters = build_pywr_parameters(
            name, args.purpose, monthly_targets, monthly_volumes,
            capacity_m3, min_volume_m3, flood_months
        )

        # Build visualization data
        viz_data = build_rule_curves_visualization_data(
            monthly_targets, flood_months, capacity_m3
        )

        result = {
            "status": "OK",
            "reservoir_name": name,
            "purpose": args.purpose,
            "capacity_mcm": capacity_mcm,
            "capacity_m3": capacity_m3,
            "flood_season": {
                "months": flood_months,
                "region": args.region,
                "description": FLOOD_SEASONS.get(args.region, {}).get("name", "custom"),
            },
            "monthly_targets": {
                "fractions": monthly_targets,
                "volumes_m3": monthly_volumes,
            },
            "pywr_parameters": parameters,
            "visualization": viz_data,
        }

        output_str = json.dumps(result, indent=2, ensure_ascii=False)

        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w") as f:
                f.write(output_str)
            print(f"Wrote operating rules to {args.output}")
        else:
            print(output_str)

        sys.exit(0)

    except Exception as e:
        print(json.dumps({"error": str(e), "status": "FAIL"}))
        sys.exit(3)


if __name__ == "__main__":
    main()
