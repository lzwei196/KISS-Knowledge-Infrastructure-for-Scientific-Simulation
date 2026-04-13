#!/usr/bin/env python3
"""
configure_snow_params.py — Configure SHAW snow parameters.

Generates Line G and Lines G1 of the SHAW site file for snow initialization.

Parameters:
- ISNOTMP: Snow threshold based on air temp (1) or wet bulb temp (2)
- SNOTMP: Maximum temperature for snow (C). Typical: 1.0-2.0 C
- ZMSPCM: Roughness with snow cover (cm). Typical: 0.15 cm
- Initial snow layers (if present): thickness, temperature, liquid water, density

Usage:
    python configure_snow_params.py \
        --nsp 0 \
        --snotmp 1.5 \
        [--init_snow_depth 0.0] \
        [--init_snow_temp -5.0] \
        [--init_snow_density 200.0] \
        --output snow_params.txt
"""

import argparse
from pathlib import Path


def generate_snow_config(args):
    """Generate SHAW snow configuration lines."""
    lines = []

    # Line G: ISNOTMP SNOTMP ZMSPCM ISNOPARM
    lines.append(f" {args.isnotmp}  {args.snotmp:.1f}  {args.zmspcm:.2f}  0")

    # Lines G1 (initial snow layers, if NSP > 0)
    if args.nsp > 0:
        if args.init_snow_depth > 0:
            # Distribute snow into layers
            layer_thickness = args.init_snow_depth / args.nsp
            for i in range(args.nsp):
                # DZSP TSPDT DLWDT RHOSP
                lines.append(
                    f" {layer_thickness:.3f}  {args.init_snow_temp:.1f}  "
                    f"0.000  {args.init_snow_density:.1f}"
                )
        else:
            # No initial snow but layers reserved
            for i in range(args.nsp):
                lines.append(f" 0.001  0.0  0.000  100.0")

    text = '\n'.join(lines)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(text + '\n')
        print(f"Snow params written: {output_path}")
    else:
        print(text)

    print(f"\nSnow configuration:")
    print(f"  Threshold type: {'air temp' if args.isnotmp == 1 else 'wet bulb temp'}")
    print(f"  Snow threshold: {args.snotmp:.1f} C")
    print(f"  Snow roughness: {args.zmspcm:.2f} cm")
    print(f"  Initial layers: {args.nsp}")
    if args.nsp > 0:
        print(f"  Initial depth: {args.init_snow_depth:.2f} m")
        print(f"  Initial density: {args.init_snow_density:.0f} kg/m3")

    return text


def main():
    parser = argparse.ArgumentParser(description="Configure SHAW snow parameters")
    parser.add_argument("--nsp", type=int, default=0,
                        help="Number of initial snow layers")
    parser.add_argument("--isnotmp", type=int, default=1, choices=[1, 2],
                        help="Snow threshold: 1=air temp, 2=wet bulb")
    parser.add_argument("--snotmp", type=float, default=1.5,
                        help="Max temp for snow (C)")
    parser.add_argument("--zmspcm", type=float, default=0.15,
                        help="Roughness with snow (cm)")
    parser.add_argument("--init_snow_depth", type=float, default=0.0,
                        help="Initial snow depth (m)")
    parser.add_argument("--init_snow_temp", type=float, default=-5.0,
                        help="Initial snow temperature (C)")
    parser.add_argument("--init_snow_density", type=float, default=200.0,
                        help="Initial snow density (kg/m3)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file")

    args = parser.parse_args()
    generate_snow_config(args)


if __name__ == "__main__":
    main()
