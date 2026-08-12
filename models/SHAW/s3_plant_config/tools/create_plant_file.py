#!/usr/bin/env python3
"""
create_plant_file.py — Generate SHAW plant growth input file.

Creates temporal plant characteristics (height, LAI, biomass, rooting depth)
for common vegetation types. Uses AVHRR land cover class or user-specified
crop type to select appropriate growth curves.

Plant growth file format (one line per observation date):
    JDAY JYR PLTHGT DCHAR CLUMPNG PLTWGT PLTLAI ROOTDP

Usage:
    python create_plant_file.py \
        --crop_type grass \
        --start_year 2005 --end_year 2005 \
        --lat 46.75 \
        --output grass_growth.dat
"""

import argparse
import math
from pathlib import Path


# Plant type templates: (DOY, height_m, leaf_dim_cm, clumping, biomass_kg_m2, LAI, root_depth_m)
# These are simplified phenology curves for common vegetation types
PLANT_TEMPLATES = {
    'grass': {
        'itype': 1,     # transpiring plant
        'pintrcp': 0.25,  # mm per LAI
        'xangle': 1.0,   # random leaf orientation
        'canalb': 0.25,
        'tccrit': 0.0,
        'rstomo': 100.0,
        'rstexp': 5.0,
        'pleaf0': -300.0,
        'rleaf0': 1.7e5,
        'rroot0': 3.3e5,
        'root_fractions': [0.05, 0.10, 0.15, 0.18, 0.18, 0.15, 0.12, 0.05, 0.01, 0.01, 0.00],
        # Growth curve: (DOY, height, dchar, clump, biomass, LAI, rootdp)
        'growth': [
            (1,   0.05, 0.5, 1.0, 0.01, 0.1, 0.3),
            (90,  0.05, 0.5, 1.0, 0.01, 0.1, 0.3),
            (120, 0.15, 0.5, 1.0, 0.10, 0.5, 0.4),
            (150, 0.30, 0.5, 1.0, 0.30, 1.5, 0.5),
            (180, 0.40, 0.5, 1.0, 0.50, 2.5, 0.6),
            (210, 0.35, 0.5, 1.0, 0.40, 2.0, 0.6),
            (240, 0.25, 0.5, 1.0, 0.30, 1.5, 0.5),
            (270, 0.15, 0.5, 1.0, 0.15, 0.5, 0.4),
            (300, 0.05, 0.5, 1.0, 0.05, 0.1, 0.3),
            (365, 0.05, 0.5, 1.0, 0.01, 0.1, 0.3),
        ],
    },
    'wheat': {
        'itype': 1,
        'pintrcp': 0.25,
        'xangle': 0.5,
        'canalb': 0.23,
        'tccrit': 0.0,
        'rstomo': 100.0,
        'rstexp': 5.0,
        'pleaf0': -200.0,
        'rleaf0': 1.5e5,
        'rroot0': 3.0e5,
        'growth': [
            (1,   0.0, 2.0, 1.0, 0.00, 0.0, 0.0),
            (90,  0.05, 2.0, 1.0, 0.02, 0.1, 0.1),
            (110, 0.15, 2.0, 1.0, 0.10, 0.8, 0.3),
            (130, 0.40, 2.0, 1.0, 0.30, 2.5, 0.5),
            (150, 0.60, 2.0, 1.0, 0.50, 4.0, 0.7),
            (170, 0.80, 2.0, 1.0, 0.70, 4.5, 0.8),
            (190, 0.80, 2.0, 1.0, 0.60, 3.0, 0.8),
            (210, 0.70, 2.0, 1.0, 0.40, 1.0, 0.6),
            (230, 0.0, 2.0, 1.0, 0.00, 0.0, 0.0),
            (365, 0.0, 2.0, 1.0, 0.00, 0.0, 0.0),
        ],
    },
    'maize': {
        'itype': 1,
        'pintrcp': 0.25,
        'xangle': 0.5,
        'canalb': 0.23,
        'tccrit': 5.0,
        'rstomo': 100.0,
        'rstexp': 5.0,
        'pleaf0': -200.0,
        'rleaf0': 1.5e5,
        'rroot0': 2.5e5,
        'growth': [
            (1,   0.0, 5.0, 1.0, 0.00, 0.0, 0.0),
            (130, 0.0, 5.0, 1.0, 0.00, 0.0, 0.0),
            (150, 0.20, 5.0, 1.0, 0.05, 0.3, 0.2),
            (170, 0.80, 5.0, 1.0, 0.30, 1.5, 0.5),
            (190, 1.50, 5.0, 1.0, 0.60, 3.5, 0.8),
            (210, 2.00, 5.0, 1.0, 0.80, 4.5, 1.0),
            (230, 2.00, 5.0, 1.0, 0.70, 3.5, 1.0),
            (250, 1.80, 5.0, 1.0, 0.50, 2.0, 0.8),
            (270, 1.50, 5.0, 1.0, 0.30, 0.5, 0.5),
            (290, 0.0, 5.0, 1.0, 0.00, 0.0, 0.0),
            (365, 0.0, 5.0, 1.0, 0.00, 0.0, 0.0),
        ],
    },
    'soybean': {
        'itype': 1,
        'pintrcp': 0.25,
        'xangle': 1.0,
        'canalb': 0.23,
        'tccrit': 5.0,
        'rstomo': 100.0,
        'rstexp': 5.0,
        'pleaf0': -200.0,
        'rleaf0': 2.0e5,
        'rroot0': 4.0e5,
        'growth': [
            (1,   0.0, 3.0, 1.0, 0.00, 0.0, 0.0),
            (140, 0.0, 3.0, 1.0, 0.00, 0.0, 0.0),
            (160, 0.10, 3.0, 1.0, 0.03, 0.3, 0.1),
            (180, 0.30, 3.0, 1.0, 0.15, 1.5, 0.3),
            (200, 0.60, 3.0, 1.0, 0.35, 3.5, 0.5),
            (220, 0.70, 3.0, 1.0, 0.40, 4.0, 0.6),
            (240, 0.65, 3.0, 1.0, 0.35, 3.0, 0.6),
            (260, 0.50, 3.0, 1.0, 0.20, 1.5, 0.4),
            (280, 0.0, 3.0, 1.0, 0.00, 0.0, 0.0),
            (365, 0.0, 3.0, 1.0, 0.00, 0.0, 0.0),
        ],
    },
    'conifer': {
        # Korean Pine / Scots Pine — NE China evergreen needleleaf.
        # LAI calibrated to 2.0-3.5 range (Korean Pine: Dai et al. 2004,
        # Gower et al. 1997); JackPine BERMS validation used LAI=2.0.
        # Previous template had LAI=5.5 (overestimate by ~100%).
        'itype': 1,
        'pintrcp': 0.5,    # conifers intercept 0.5 mm per unit LAI (needles)
        'xangle': 1.0,     # random needle orientation
        'canalb': 0.10,    # dark conifer albedo (JackPine validated: 0.10)
        'tccrit': -5.0,    # evergreen: transpires to -5°C (JackPine validated)
        'rstomo': 150.0,   # stomatal resistance (JackPine validated: 150 s/m)
        'rstexp': 5.0,
        'pleaf0': -300.0,
        'rleaf0': 6.7e5,   # JackPine validated
        'rroot0': 1.7e6,   # JackPine validated
        # Evergreen: slight seasonal LAI variation (new shoot growth in summer)
        # Heights calibrated to Korean Pine 15-20 m in NE China
        'growth': [
            (1,   15.0, 0.3, 0.7, 5.0, 2.0, 1.0),
            (90,  15.0, 0.3, 0.7, 5.0, 2.0, 1.0),
            (120, 15.0, 0.3, 0.7, 5.2, 2.5, 1.0),
            (180, 15.0, 0.3, 0.7, 5.5, 3.0, 1.0),
            (240, 15.0, 0.3, 0.7, 5.5, 3.0, 1.0),
            (300, 15.0, 0.3, 0.7, 5.2, 2.5, 1.0),
            (365, 15.0, 0.3, 0.7, 5.0, 2.0, 1.0),
        ],
        # Root fractions for 11 soil nodes (0,2,5,10,15,20,30,50,60,90,120 cm)
        # Evergreen conifer: moderately deep roots, concentrated in top 60 cm
        'root_fractions': [0.02, 0.05, 0.10, 0.12, 0.15, 0.18, 0.20, 0.10, 0.05, 0.02, 0.01],
    },
    'dahurian_larch': {
        # Dahurian Larch (Larix gmelinii) — dominant in Greater Khingan Mts.
        # Deciduous NEEDLELEAF — unique: drops needles in autumn like broadleaf,
        # but needle dimensions like conifer. MCANFLG=1 required (seasonal LAI).
        # LAI peak 2.5-4.0 (He et al. 2012, Wirth et al. 1999).
        # Transpires only in growing season (leaf-out ~DOY 110, senescence ~DOY 260).
        'itype': 1,
        'pintrcp': 0.4,    # deciduous larch: intermediate between conifer and broadleaf
        'xangle': 1.0,     # random needle orientation
        'canalb': 0.12,    # slightly higher than evergreen conifer (brighter needles)
        'tccrit': 0.0,     # no transpiration when frozen (needles fully shed by Nov)
        'rstomo': 120.0,   # larch stomatal resistance (lower than pine: Kelliher 1993)
        'rstexp': 5.0,
        'pleaf0': -200.0,
        'rleaf0': 5.0e5,
        'rroot0': 1.5e6,
        # Growth curve: full leaf-off in winter, strong seasonal signal
        # Height ~15 m for mature Dahurian Larch in NE China
        'growth': [
            (1,   15.0, 0.3, 0.7, 0.5, 0.0, 1.2),   # bare in winter
            (100, 15.0, 0.3, 0.7, 0.5, 0.0, 1.2),   # still bare (cold spring)
            (115, 15.0, 0.3, 0.7, 1.0, 0.5, 1.2),   # leaf-out
            (140, 15.0, 0.3, 0.7, 2.0, 2.0, 1.2),   # rapid leaf development
            (175, 15.0, 0.3, 0.7, 3.0, 3.5, 1.2),   # peak LAI
            (220, 15.0, 0.3, 0.7, 3.0, 3.5, 1.2),   # full canopy
            (255, 15.0, 0.3, 0.7, 2.5, 2.5, 1.2),   # early senescence
            (275, 15.0, 0.3, 0.7, 1.5, 1.0, 1.2),   # rapid needle fall
            (295, 15.0, 0.3, 0.7, 0.5, 0.0, 1.2),   # fully deciduous
            (365, 15.0, 0.3, 0.7, 0.5, 0.0, 1.2),   # bare winter
        ],
        'root_fractions': [0.02, 0.05, 0.10, 0.15, 0.18, 0.18, 0.15, 0.10, 0.05, 0.01, 0.01],
    },
    'deciduous': {
        # Mongolian Oak (Quercus mongolica) + White Birch (Betula platyphylla)
        # — dominant deciduous broadleaf species in NE China (Changbai Mts, Khingan).
        # LAI peak 4.5-6.0 (Zhang et al. 2006); height 15-25 m for mature stands.
        # Stomatal resistance 150-250 s/m (oak higher, birch lower).
        'itype': 1,
        'pintrcp': 0.3,    # broadleaf: 0.3 mm/LAI (less interception per area than needles)
        'xangle': 0.8,     # slightly horizontal broad leaves
        'canalb': 0.18,    # deciduous broadleaf albedo
        'tccrit': 0.0,     # no transpiration below 0°C
        'rstomo': 200.0,   # oak/birch stomatal resistance (higher than larch)
        'rstexp': 5.0,
        'pleaf0': -200.0,
        'rleaf0': 2.5e5,
        'rroot0': 5.0e5,
        # NE China deciduous broadleaf: leaf-out later than temperate (cold spring)
        # Height calibrated to NE China mature hardwood stands: 18 m
        'growth': [
            (1,   18.0, 3.0, 0.8, 0.5, 0.0, 1.5),   # bare in winter
            (110, 18.0, 3.0, 0.8, 0.5, 0.0, 1.5),   # still bare
            (125, 18.0, 3.0, 0.8, 1.5, 1.5, 1.5),   # leaf-out (late May)
            (155, 18.0, 3.0, 0.8, 3.0, 4.0, 1.5),   # rapid growth
            (195, 18.0, 3.0, 0.8, 4.5, 5.5, 1.5),   # peak LAI
            (245, 18.0, 3.0, 0.8, 4.5, 5.5, 1.5),   # full canopy
            (270, 18.0, 3.0, 0.8, 3.0, 3.0, 1.5),   # early senescence (Sep)
            (295, 18.0, 3.0, 0.8, 1.0, 0.5, 1.5),   # leaf fall (Oct)
            (310, 18.0, 3.0, 0.8, 0.5, 0.0, 1.5),   # fully bare
            (365, 18.0, 3.0, 0.8, 0.5, 0.0, 1.5),   # bare winter
        ],
        # Deeper roots than conifers: oak/birch tap deeper moisture reserves
        'root_fractions': [0.02, 0.04, 0.08, 0.10, 0.12, 0.15, 0.18, 0.15, 0.10, 0.05, 0.01],
    },
    'sagebrush': {
        'itype': 1,
        'pintrcp': 0.25,
        'xangle': 1.0,
        'canalb': 0.15,
        'tccrit': -5.0,
        'rstomo': 300.0,
        'rstexp': 5.0,
        'pleaf0': -500.0,
        'rleaf0': 1.5e6,
        'rroot0': 2.0e6,
        'growth': [
            (1,   0.6, 0.5, 0.3, 0.3, 0.5, 0.8),
            (120, 0.6, 0.5, 0.3, 0.3, 0.5, 0.8),
            (150, 0.6, 0.5, 0.3, 0.4, 0.8, 1.0),
            (200, 0.6, 0.5, 0.3, 0.5, 1.0, 1.0),
            (250, 0.6, 0.5, 0.3, 0.4, 0.8, 1.0),
            (300, 0.6, 0.5, 0.3, 0.3, 0.5, 0.8),
            (365, 0.6, 0.5, 0.3, 0.3, 0.5, 0.8),
        ],
    },
    'bare': {
        'itype': 0,  # dead/no plant
        'pintrcp': 0.0,
        'xangle': 1.0,
        'canalb': 0.25,
        'tccrit': 0.0,
        'rstomo': 100.0,
        'rstexp': 5.0,
        'pleaf0': -100.0,
        'rleaf0': 1.0e5,
        'rroot0': 2.0e5,
        'growth': [
            (1,   0.0, 1.0, 1.0, 0.0, 0.0, 0.0),
            (365, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0),
        ],
    },
}


def adjust_phenology_for_latitude(growth_curve, lat):
    """
    Shift phenology dates based on latitude.
    Higher latitudes: later spring, earlier fall.
    Southern hemisphere: shift by 6 months.
    """
    adjusted = []
    # Latitude adjustment: ~2 days per degree from 45N baseline
    lat_shift = (abs(lat) - 45.0) * 2.0

    for (doy, *rest) in growth_curve:
        if lat < 0:
            # Southern hemisphere: shift by 182 days
            new_doy = (doy + 182) % 365
            if new_doy == 0:
                new_doy = 365
        else:
            new_doy = doy + int(lat_shift)
            new_doy = max(1, min(365, new_doy))
        adjusted.append((new_doy, *rest))

    # Sort by DOY
    adjusted.sort(key=lambda x: x[0])

    # SHAW requires the growth file to cover DOY 1 and DOY 365 exactly.
    # Ensure first entry is DOY 1 and last is DOY 365.
    if adjusted[0][0] > 1:
        adjusted.insert(0, (1,) + adjusted[0][1:])
    if adjusted[-1][0] < 365:
        adjusted.append((365,) + adjusted[-1][1:])

    return adjusted


def write_plant_growth_file(template, start_year, end_year, lat, output_path):
    """Write SHAW plant growth file."""
    growth = template['growth']
    growth = adjust_phenology_for_latitude(growth, lat)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        for year in range(start_year, end_year + 1):
            yr = year % 100
            for (doy, height, dchar, clump, biomass, lai, rootdp) in growth:
                f.write(
                    f" {doy:3d}  {yr:2d}  {height:.2f}  {dchar:.1f}  "
                    f"{clump:.1f}  {biomass:.2f}  {lai:.2f}  {rootdp:.2f}\n"
                )

    print(f"Plant growth file written: {output_path}")
    print(f"  Crop type: {template.get('name', 'unknown')}")
    print(f"  Years: {start_year}-{end_year}")
    print(f"  Observations per year: {len(growth)}")


def main():
    parser = argparse.ArgumentParser(description="Generate SHAW plant growth file")
    parser.add_argument("--crop_type", type=str, required=True,
                        choices=list(PLANT_TEMPLATES.keys()),
                        help="Vegetation type")
    parser.add_argument("--print_root_fractions", action="store_true",
                        help="Print root distribution fractions for .sit file")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--lat", type=float, default=45.0,
                        help="Latitude for phenology adjustment")
    parser.add_argument("--output", type=str, required=True,
                        help="Output plant growth file")

    args = parser.parse_args()

    template = PLANT_TEMPLATES[args.crop_type]
    template['name'] = args.crop_type

    write_plant_growth_file(template, args.start_year, args.end_year,
                            args.lat, args.output)

    # Also print the site file plant parameters for reference
    print(f"\nSite file plant parameters (for .sit Line F):")
    print(f"  ITYPE: {template['itype']}")
    print(f"  PINTRCP: {template['pintrcp']}")
    print(f"  XANGLE: {template['xangle']}")
    print(f"  CANALB: {template['canalb']}")
    print(f"  RSTOMO: {template['rstomo']}")
    if args.print_root_fractions and 'root_fractions' in template:
        rf = template['root_fractions']
        print(f"\nRoot fractions (for .sit after F1, MCANFLG=0 only):")
        print("  " + "  ".join(f"{v:.2f}" for v in rf))


if __name__ == "__main__":
    main()
