#!/usr/bin/env python3
"""
configure_residue.py — Configure SHAW crop residue layer parameters.

Generates Lines H and H1 of the SHAW site file for surface residue.

Residue affects:
- Soil temperature (insulation from residue)
- Soil moisture (reduced evaporation)
- Snow melt (insulation under snow)
- Infiltration (reduced sealing)

Typical residue properties by crop:
    Crop          Thickness(cm)  Load(kg/ha)  Cover  RESTKB  RESCOF
    Wheat stubble    2-3          4000-8000    0.70   4.0     50000
    Corn stalks      3-5          6000-10000   0.80   8.5     50000
    Soybean          1-2          2000-4000    0.50   4.0     30000
    Grassland        1-3          3000-6000    0.90   4.0     50000
    No-till corn     5-8          8000-12000   0.90   8.5     50000

Usage:
    python configure_residue.py \
        --crop_type wheat \
        --output residue_params.txt \
        [--nrchang 0]
"""

import argparse
from pathlib import Path


# Residue properties by crop type
RESIDUE_TEMPLATES = {
    'wheat': {
        'zrthik': 2.5,      # cm
        'rload': 6000.0,    # kg/ha
        'cover': 0.70,      # fraction
        'albres': 0.25,
        'rescof': 50000.0,  # s/m
        'restkb': 4.0,
    },
    'corn': {
        'zrthik': 5.0,
        'rload': 8000.0,
        'cover': 0.80,
        'albres': 0.25,
        'rescof': 50000.0,
        'restkb': 8.5,  # larger elements
    },
    'maize': {  # alias for corn
        'zrthik': 5.0,
        'rload': 8000.0,
        'cover': 0.80,
        'albres': 0.25,
        'rescof': 50000.0,
        'restkb': 8.5,
    },
    'soybean': {
        'zrthik': 1.5,
        'rload': 3000.0,
        'cover': 0.50,
        'albres': 0.25,
        'rescof': 30000.0,
        'restkb': 4.0,
    },
    'grass': {
        'zrthik': 2.0,
        'rload': 4000.0,
        'cover': 0.90,
        'albres': 0.25,
        'rescof': 50000.0,
        'restkb': 4.0,
    },
    'forest_litter': {
        'zrthik': 3.0,
        'rload': 10000.0,
        'cover': 0.95,
        'albres': 0.15,
        'rescof': 30000.0,
        'restkb': 4.0,
    },
    'none': {
        'zrthik': 0.0,
        'rload': 0.0,
        'cover': 0.0,
        'albres': 0.25,
        'rescof': 50000.0,
        'restkb': 4.0,
    },
}


def generate_residue_config(args):
    """Generate SHAW residue configuration lines."""
    template = RESIDUE_TEMPLATES[args.crop_type]

    # Allow overrides
    zrthik = args.zrthik if args.zrthik is not None else template['zrthik']
    rload = args.rload if args.rload is not None else template['rload']
    cover = args.cover if args.cover is not None else template['cover']
    albres = template['albres']
    rescof = template['rescof']
    restkb = template['restkb']

    lines = []

    # Line H: NRCHANG GMCDT
    gmcdt = 0.0  # let model estimate from matric potential
    lines.append(f" {args.nrchang}  {gmcdt:.2f}")

    if args.nrchang == 0:
        # Static residue: Line H1
        lines.append(
            f" {zrthik:.1f}  {rload:.0f}.  {cover:.2f}  {albres:.2f}  "
            f"{rescof:.0f}.  {restkb:.1f}"
        )
    # If NRCHANG=1, a separate residue change file is needed (Line H2)

    text = '\n'.join(lines)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(text + '\n')
        print(f"Residue params written: {output_path}")
    else:
        print(text)

    print(f"\nResidue configuration ({args.crop_type}):")
    print(f"  Thickness: {zrthik:.1f} cm")
    print(f"  Load: {rload:.0f} kg/ha")
    print(f"  Cover: {cover:.0f}%")
    print(f"  RESTKB: {restkb:.1f} (wind transfer parameter)")
    print(f"  Changing: {'yes' if args.nrchang == 1 else 'no (static)'}")

    return text


def main():
    parser = argparse.ArgumentParser(description="Configure SHAW residue parameters")
    parser.add_argument("--crop_type", type=str, required=True,
                        choices=list(RESIDUE_TEMPLATES.keys()),
                        help="Crop residue type")
    parser.add_argument("--nrchang", type=int, default=0, choices=[0, 1],
                        help="0=static residue, 1=changing residue")
    parser.add_argument("--zrthik", type=float, default=None,
                        help="Override thickness (cm)")
    parser.add_argument("--rload", type=float, default=None,
                        help="Override load (kg/ha)")
    parser.add_argument("--cover", type=float, default=None,
                        help="Override cover fraction")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file")

    args = parser.parse_args()
    generate_residue_config(args)


if __name__ == "__main__":
    main()
