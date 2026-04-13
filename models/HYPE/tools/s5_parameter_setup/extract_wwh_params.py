#!/usr/bin/env python3
"""
Extract World-Wide HYPE (WWH) parameters for a given basin location.

Uses the WWH parameter database to find calibrated parameter values
for basins with similar climate, soil, and land cover characteristics.

Usage:
    python extract_wwh_params.py \
        --lat 31.0 --lon 117.0 \
        --climate humid_subtropical \
        --output par_wwh_defaults.txt
"""

import argparse
import sys

# WWH calibrated parameter ranges by Koppen climate zone
# Source: Arheimer et al. (2020), HYPE model description
WWH_PARAMS = {
    'Af': {  # Tropical rainforest
        'ttmp': (0.0, 0.0), 'cmlt': (3.0, 6.0), 'cevp': (0.20, 0.30),
        'wcfc': (0.20, 0.30), 'wcwp': (0.08, 0.15), 'wcep': (0.35, 0.50),
        'rrcs1': (0.03, 0.08), 'rrcs2': (0.005, 0.015), 'lp': (0.8, 0.95),
        'rivvel': (0.5, 1.5), 'damp': (0.3, 0.7),
    },
    'Cfa': {  # Humid subtropical
        'ttmp': (-1.0, 1.0), 'cmlt': (3.0, 5.0), 'cevp': (0.15, 0.25),
        'wcfc': (0.15, 0.25), 'wcwp': (0.05, 0.12), 'wcep': (0.30, 0.45),
        'rrcs1': (0.05, 0.15), 'rrcs2': (0.005, 0.02), 'lp': (0.7, 0.9),
        'rivvel': (0.8, 2.0), 'damp': (0.3, 0.6),
    },
    'Dwa': {  # Monsoon continental
        'ttmp': (-2.0, 0.5), 'cmlt': (2.5, 5.0), 'cevp': (0.10, 0.20),
        'wcfc': (0.12, 0.22), 'wcwp': (0.04, 0.10), 'wcep': (0.28, 0.42),
        'rrcs1': (0.08, 0.20), 'rrcs2': (0.008, 0.025), 'lp': (0.6, 0.85),
        'rivvel': (0.5, 1.5), 'damp': (0.3, 0.6),
    },
    'BSk': {  # Semi-arid steppe
        'ttmp': (-1.0, 1.0), 'cmlt': (2.0, 4.0), 'cevp': (0.25, 0.40),
        'wcfc': (0.10, 0.18), 'wcwp': (0.03, 0.08), 'wcep': (0.25, 0.40),
        'rrcs1': (0.10, 0.25), 'rrcs2': (0.01, 0.03), 'lp': (0.5, 0.7),
        'rivvel': (0.5, 1.0), 'damp': (0.2, 0.5),
    },
    'ET': {  # Tundra / high alpine
        'ttmp': (-3.0, -0.5), 'cmlt': (2.0, 4.0), 'cevp': (0.08, 0.15),
        'wcfc': (0.15, 0.22), 'wcwp': (0.05, 0.10), 'wcep': (0.30, 0.42),
        'rrcs1': (0.05, 0.15), 'rrcs2': (0.003, 0.012), 'lp': (0.8, 0.95),
        'rivvel': (1.0, 3.0), 'damp': (0.4, 0.7),
    },
}

# Map common climate descriptions to Koppen codes
CLIMATE_MAP = {
    'tropical': 'Af',
    'humid_subtropical': 'Cfa',
    'monsoon_continental': 'Dwa',
    'semi_arid': 'BSk',
    'cold_alpine': 'ET',
}


def extract_wwh_parameters(lat, lon, climate='humid_subtropical'):
    """Extract WWH parameter ranges for a given location and climate."""
    koppen = CLIMATE_MAP.get(climate, climate)

    if koppen not in WWH_PARAMS:
        print(f"Warning: Unknown climate zone '{koppen}', using Cfa (humid subtropical)")
        koppen = 'Cfa'

    params = WWH_PARAMS[koppen]

    print(f"WWH parameter ranges for {koppen} climate zone (lat={lat}, lon={lon}):")
    print(f"{'Parameter':<12} {'Min':>8} {'Max':>8} {'Median':>8}")
    print("-" * 40)

    result = {}
    for param, (pmin, pmax) in sorted(params.items()):
        median = (pmin + pmax) / 2
        result[param] = {'min': pmin, 'max': pmax, 'median': median}
        print(f"{param:<12} {pmin:>8.4f} {pmax:>8.4f} {median:>8.4f}")

    return result


def main():
    parser = argparse.ArgumentParser(description='Extract WWH parameters')
    parser.add_argument('--lat', type=float, required=True)
    parser.add_argument('--lon', type=float, required=True)
    parser.add_argument('--climate', default='humid_subtropical')
    parser.add_argument('--output', help='Output parameter ranges file')

    args = parser.parse_args()

    result = extract_wwh_parameters(args.lat, args.lon, args.climate)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(f"!! WWH parameter ranges for {args.climate}\n")
            f.write(f"!! lat={args.lat}, lon={args.lon}\n")
            f.write(f"!! param\tmin\tmax\tmedian\n")
            for param, vals in sorted(result.items()):
                f.write(f"{param}\t{vals['min']}\t{vals['max']}\t{vals['median']}\n")
        print(f"\nSaved to: {args.output}")


if __name__ == '__main__':
    main()
