#!/usr/bin/env python3
"""
create_demand_nodes.py — Generate Pywr demand (output) node definitions.

Creates demand nodes for:
- Irrigation: estimated from basin area * crop water need
- Municipal: user-specified or population-based estimate
- Environmental: minimum environmental flow (Q90 rule or 10% MAF)
- Industrial: user-specified

Usage:
    python create_demand_nodes.py \
        --type environmental \
        --mean_annual_flow_m3s 150.0 \
        --output demands.json

    python create_demand_nodes.py \
        --type irrigation \
        --irrigated_area_km2 500 \
        --crop wheat \
        --output demands.json

    python create_demand_nodes.py \
        --type municipal \
        --population 500000 \
        --per_capita_lpd 200 \
        --output demands.json

Output:
    JSON with Pywr output node definitions and demand parameters.
    Exit codes: 0 = success, 2 = input error, 3 = runtime error
"""

import argparse
import json
import sys
from pathlib import Path


# ── Crop water requirement estimates (mm/season) ──
CROP_WATER_NEEDS = {
    "rice": {"seasonal_mm": 900, "months": [4, 5, 6, 7, 8, 9], "name": "Rice (paddy)"},
    "wheat": {"seasonal_mm": 450, "months": [10, 11, 12, 1, 2, 3, 4, 5], "name": "Winter wheat"},
    "maize": {"seasonal_mm": 500, "months": [5, 6, 7, 8, 9], "name": "Maize"},
    "soybean": {"seasonal_mm": 450, "months": [5, 6, 7, 8, 9], "name": "Soybean"},
    "cotton": {"seasonal_mm": 700, "months": [4, 5, 6, 7, 8, 9, 10], "name": "Cotton"},
    "generic": {"seasonal_mm": 500, "months": [4, 5, 6, 7, 8, 9], "name": "Generic crop"},
}


def create_environmental_demand(mean_annual_flow_m3s, method="percent_maf", percent=10.0):
    """
    Environmental flow demand.

    Methods:
    - percent_maf: X% of mean annual flow (default 10%)
    - q90: 90th percentile exceedance (needs flow data, approximated as 20% MAF)
    - tennant: 10% MAF Oct-Mar, 30% MAF Apr-Sep (Tennant method)
    """
    if method == "percent_maf":
        e_flow = mean_annual_flow_m3s * (percent / 100.0)
        monthly = [round(e_flow, 4)] * 12
        description = f"{percent}% of MAF ({mean_annual_flow_m3s:.1f} m3/s)"

    elif method == "q90":
        e_flow = mean_annual_flow_m3s * 0.20  # Q90 approx
        monthly = [round(e_flow, 4)] * 12
        description = f"Q90 approximation (20% MAF)"

    elif method == "tennant":
        low = round(mean_annual_flow_m3s * 0.10, 4)
        high = round(mean_annual_flow_m3s * 0.30, 4)
        # Oct-Mar: 10%, Apr-Sep: 30%
        monthly = [low, low, low, high, high, high,
                   high, high, high, low, low, low]
        e_flow = sum(monthly) / 12
        description = f"Tennant method (10% Oct-Mar, 30% Apr-Sep)"
    else:
        raise ValueError(f"Unknown method '{method}'")

    return {
        "name": "environmental_flow",
        "type": "output",
        "demand_type": "environmental",
        "method": method,
        "description": description,
        "mean_demand_m3s": round(float(e_flow), 4),
        "monthly_demand_m3s": monthly,
        "pywr_node": {
            "type": "Output",
            "name": "environmental_flow",
            "max_flow": {
                "type": "monthlyprofile",
                "values": monthly,
            },
            "cost": -1000.0,  # Highest priority (most negative)
            "comment": f"Environmental flow: {description}"
        }
    }


def create_irrigation_demand(irrigated_area_km2, crop="generic",
                              efficiency=0.55):
    """
    Irrigation demand from crop water needs.

    efficiency: irrigation efficiency (0.3-0.9, default 0.55 for surface irrigation)
    """
    crop_info = CROP_WATER_NEEDS.get(crop, CROP_WATER_NEEDS["generic"])
    seasonal_mm = crop_info["seasonal_mm"]
    active_months = crop_info["months"]

    # Total water need = seasonal_mm * area / efficiency
    area_m2 = irrigated_area_km2 * 1e6
    total_volume_m3 = (seasonal_mm / 1000.0) * area_m2 / efficiency
    n_active = len(active_months)
    daily_m3 = total_volume_m3 / (n_active * 30.44)  # approximate days
    daily_m3s = daily_m3 / 86400.0

    # Monthly profile
    monthly = [0.0] * 12
    for m in active_months:
        monthly[m - 1] = round(daily_m3s, 4)

    return {
        "name": "irrigation_demand",
        "type": "output",
        "demand_type": "irrigation",
        "crop": crop_info["name"],
        "irrigated_area_km2": irrigated_area_km2,
        "efficiency": efficiency,
        "seasonal_water_need_mm": seasonal_mm,
        "total_volume_mcm": round(total_volume_m3 / 1e6, 1),
        "mean_demand_m3s": round(float(sum(monthly) / max(n_active, 1)), 4),
        "monthly_demand_m3s": monthly,
        "pywr_node": {
            "type": "Output",
            "name": "irrigation_demand",
            "max_flow": {
                "type": "monthlyprofile",
                "values": monthly,
            },
            "cost": -800.0,  # High priority
            "comment": f"Irrigation: {crop_info['name']}, {irrigated_area_km2} km2"
        }
    }


def create_municipal_demand(population, per_capita_lpd=200.0):
    """
    Municipal water demand from population and per-capita use.

    per_capita_lpd: liters per person per day (typically 150-300 in China)
    """
    daily_m3 = population * per_capita_lpd / 1000.0
    demand_m3s = daily_m3 / 86400.0

    # Slight seasonal variation: +10% summer, -10% winter
    monthly_factors = [0.90, 0.90, 0.95, 1.0, 1.05, 1.10,
                       1.10, 1.10, 1.05, 1.0, 0.95, 0.90]
    monthly = [round(demand_m3s * f, 4) for f in monthly_factors]

    return {
        "name": "municipal_demand",
        "type": "output",
        "demand_type": "municipal",
        "population": population,
        "per_capita_lpd": per_capita_lpd,
        "mean_demand_m3s": round(float(demand_m3s), 4),
        "annual_volume_mcm": round(daily_m3 * 365.25 / 1e6, 1),
        "monthly_demand_m3s": monthly,
        "pywr_node": {
            "type": "Output",
            "name": "municipal_demand",
            "max_flow": {
                "type": "monthlyprofile",
                "values": monthly,
            },
            "cost": -900.0,  # Very high priority (just below environmental)
            "comment": f"Municipal: {population:,} people, {per_capita_lpd} L/day"
        }
    }


def create_industrial_demand(demand_m3s):
    """Industrial demand (constant or user-specified)."""
    monthly = [round(demand_m3s, 4)] * 12

    return {
        "name": "industrial_demand",
        "type": "output",
        "demand_type": "industrial",
        "mean_demand_m3s": demand_m3s,
        "annual_volume_mcm": round(demand_m3s * 86400 * 365.25 / 1e6, 1),
        "monthly_demand_m3s": monthly,
        "pywr_node": {
            "type": "Output",
            "name": "industrial_demand",
            "max_flow": demand_m3s,
            "cost": -700.0,
            "comment": f"Industrial: {demand_m3s:.2f} m3/s constant"
        }
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate Pywr demand nodes"
    )

    parser.add_argument("--type", type=str, required=True,
                        choices=["environmental", "irrigation", "municipal",
                                 "industrial", "all"],
                        help="Demand type to generate")

    # Environmental flow params
    parser.add_argument("--mean_annual_flow_m3s", type=float, default=None,
                        help="Mean annual flow at outlet (m3/s)")
    parser.add_argument("--eflow_method", type=str, default="percent_maf",
                        choices=["percent_maf", "q90", "tennant"],
                        help="Environmental flow method")
    parser.add_argument("--eflow_percent", type=float, default=10.0,
                        help="Percent of MAF for environmental flow (default: 10)")

    # Irrigation params
    parser.add_argument("--irrigated_area_km2", type=float, default=None,
                        help="Irrigated area in km2")
    parser.add_argument("--crop", type=str, default="generic",
                        choices=list(CROP_WATER_NEEDS.keys()),
                        help="Crop type for irrigation demand estimate")
    parser.add_argument("--irrigation_efficiency", type=float, default=0.55,
                        help="Irrigation efficiency (default: 0.55)")

    # Municipal params
    parser.add_argument("--population", type=int, default=None,
                        help="Population served")
    parser.add_argument("--per_capita_lpd", type=float, default=200.0,
                        help="Per-capita water use (L/person/day, default: 200)")

    # Industrial params
    parser.add_argument("--industrial_m3s", type=float, default=None,
                        help="Industrial demand (m3/s)")

    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file (default: stdout)")

    args = parser.parse_args()

    try:
        demands = []

        if args.type in ("environmental", "all"):
            if args.mean_annual_flow_m3s is None:
                print(json.dumps({"error": "Environmental demand requires --mean_annual_flow_m3s"}))
                sys.exit(2)
            demands.append(create_environmental_demand(
                args.mean_annual_flow_m3s, args.eflow_method, args.eflow_percent
            ))

        if args.type in ("irrigation", "all"):
            if args.irrigated_area_km2 is None and args.type == "irrigation":
                print(json.dumps({"error": "Irrigation demand requires --irrigated_area_km2"}))
                sys.exit(2)
            if args.irrigated_area_km2:
                demands.append(create_irrigation_demand(
                    args.irrigated_area_km2, args.crop, args.irrigation_efficiency
                ))

        if args.type in ("municipal", "all"):
            if args.population is None and args.type == "municipal":
                print(json.dumps({"error": "Municipal demand requires --population"}))
                sys.exit(2)
            if args.population:
                demands.append(create_municipal_demand(
                    args.population, args.per_capita_lpd
                ))

        if args.type in ("industrial", "all"):
            if args.industrial_m3s:
                demands.append(create_industrial_demand(args.industrial_m3s))

        result = {
            "status": "OK",
            "demand_count": len(demands),
            "total_mean_demand_m3s": round(
                sum(d["mean_demand_m3s"] for d in demands), 4
            ),
            "demands": demands,
        }

        output_str = json.dumps(result, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w") as f:
                f.write(output_str)
            print(f"Wrote {len(demands)} demand definitions to {args.output}")
        else:
            print(output_str)

        sys.exit(0)

    except Exception as e:
        print(json.dumps({"error": str(e), "status": "FAIL"}))
        sys.exit(3)


if __name__ == "__main__":
    main()
