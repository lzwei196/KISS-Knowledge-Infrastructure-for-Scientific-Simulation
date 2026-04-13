#!/usr/bin/env python3
"""
configure_wq.py — Configure CE-QUAL-W2 water quality constituents and kinetic rates.

CRITICAL (dt_015): Constituent ON/OFF flags in w2_con.npt MUST match the number of
columns in cin_br*.npt inflow files. If a constituent is ON but missing from inflow,
or OFF but present, the model reads the wrong columns SILENTLY.

Recommended configurations:
  1. "temperature_only": No WQ, fastest setup
  2. "basic_wq": T + DO + TDS + ISS
  3. "nutrients": T + DO + nutrients (NH4, NO3, PO4) + organic matter
  4. "eutrophication": Above + algae groups
  5. "full": All constituents including zooplankton, macrophytes

Usage:
    python configure_wq.py \
        --preset nutrients \
        --output wq_config.json
"""

import argparse
import json
import os
import sys


# Default kinetic rate coefficients (literature values)
DEFAULT_RATES = {
    "TDS": {"settling_velocity": 0.0},
    "ISS": {"settling_velocity": 1.0},  # m/day
    "PO4": {"sediment_release_rate": 0.01},  # g/m^2/day
    "NH4": {"nitrification_rate": 0.05, "sediment_release_rate": 0.05},
    "NO3": {"denitrification_rate": 0.05},
    "DSI": {},
    "LDOM": {"decay_rate": 0.05},
    "RDOM": {"decay_rate": 0.001},
    "LPOM": {"decay_rate": 0.05, "settling_velocity": 0.3},
    "RPOM": {"decay_rate": 0.001, "settling_velocity": 0.3},
    "ALG1": {"growth_rate": 2.0, "mortality_rate": 0.1, "settling_velocity": 0.2,
             "half_sat_p": 0.003, "half_sat_n": 0.014},
    "ALG2": {"growth_rate": 1.5, "mortality_rate": 0.1, "settling_velocity": 0.1,
             "half_sat_p": 0.005, "half_sat_n": 0.025},
    "DO": {"SOD": 0.5, "reaeration_formula": "LAKE"},  # SOD g/m^2/day
    "ZOO1": {"grazing_rate": 0.5},
    "CBOD1": {"decay_rate": 0.04, "settling_velocity": 0.1},
}

PRESETS = {
    "temperature_only": [],
    "basic_wq": ["TDS", "ISS", "DO"],
    "nutrients": ["TDS", "ISS", "PO4", "NH4", "NO3", "LDOM", "RDOM", "LPOM", "RPOM", "DO"],
    "eutrophication": ["TDS", "ISS", "PO4", "NH4", "NO3", "DSI", "LDOM", "RDOM",
                       "LPOM", "RPOM", "ALG1", "ALG2", "DO"],
    "full": list(DEFAULT_RATES.keys()),
}


def process(args):
    """Main processing."""
    if args.preset:
        active = PRESETS.get(args.preset, PRESETS["nutrients"])
    elif args.constituents:
        active = [c.strip().upper() for c in args.constituents.split(",")]
    else:
        active = []

    # Build rate configuration
    rates = {}
    for c in active:
        rates[c] = DEFAULT_RATES.get(c, {})

    # SOD override
    if args.sod and "DO" in active:
        rates["DO"]["SOD"] = args.sod

    # Algal growth rate override
    if args.algal_growth_rate and "ALG1" in active:
        rates["ALG1"]["growth_rate"] = args.algal_growth_rate

    config = {
        "preset": args.preset or "custom",
        "active_constituents": active,
        "n_active": len(active),
        "rates": rates,
        "enable_wq": len(active) > 0,
        "constituent_flags": {c: True for c in active},
    }

    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(config, f, indent=2)

    result = {
        "status": "success",
        "output_file": output_path,
        "preset": config["preset"],
        "n_active_constituents": len(active),
        "active_constituents": active,
    }
    print(json.dumps(result, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Configure CE-QUAL-W2 water quality")
    parser.add_argument("--preset", choices=list(PRESETS.keys()),
                       help="Preset configuration")
    parser.add_argument("--constituents", help="Comma-separated constituent names")
    parser.add_argument("--sod", type=float, help="Sediment oxygen demand (g/m^2/day)")
    parser.add_argument("--algal_growth_rate", type=float, help="Max algal growth rate (1/day)")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    sys.exit(process(args))


if __name__ == "__main__":
    main()
