#!/usr/bin/env python3
"""
convert_soil_to_lpjml.py — Convert HWSD or generic soil texture data
to LPJmL's 13-type soil classification.

Maps sand/silt/clay fractions from HWSD (Harmonized World Soil Database)
or any gridded soil texture dataset to LPJmL's 13 soil types using the
USDA soil texture triangle.

Usage:
    python convert_soil_to_lpjml.py --input hwsd_soil.nc \
        --sand_var T_SAND --silt_var T_SILT --clay_var T_CLAY \
        --output soil_13types.bin --grid grid.bin

Pattern: validate -> process -> validate
"""

import argparse
import struct
import sys
import os
import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

# LPJmL soil type classification based on USDA texture triangle
# Each type is defined by its sand/silt/clay percentage ranges
LPJML_SOIL_TYPES = {
    1: {"name": "clay", "sand": (0, 45), "clay": (40, 100)},
    2: {"name": "silty clay", "sand": (0, 20), "silt": (40, 60), "clay": (40, 60)},
    3: {"name": "sandy clay", "sand": (45, 65), "clay": (35, 55)},
    4: {"name": "clay loam", "sand": (20, 45), "silt": (15, 53), "clay": (27, 40)},
    5: {"name": "silty clay loam", "sand": (0, 20), "silt": (40, 73), "clay": (27, 40)},
    6: {"name": "sandy clay loam", "sand": (45, 80), "silt": (0, 28), "clay": (20, 35)},
    7: {"name": "loam", "sand": (23, 52), "silt": (28, 50), "clay": (7, 27)},
    8: {"name": "silt loam", "sand": (0, 50), "silt": (50, 88), "clay": (0, 27)},
    9: {"name": "sandy loam", "sand": (43, 85), "silt": (0, 50), "clay": (0, 20)},
    10: {"name": "silt", "sand": (0, 20), "silt": (80, 100), "clay": (0, 12)},
    11: {"name": "loamy sand", "sand": (70, 90), "silt": (0, 30), "clay": (0, 15)},
    12: {"name": "sand", "sand": (85, 100), "silt": (0, 15), "clay": (0, 10)},
    13: {"name": "rock and ice"},
}


def validate_inputs(input_path, sand_var, silt_var, clay_var):
    """Pre-processing validation."""
    errors = []
    if not os.path.exists(input_path):
        errors.append(f"Input file not found: {input_path}")
        return errors

    if nc is None:
        errors.append("netCDF4 not installed")
        return errors

    try:
        ds = nc.Dataset(input_path, "r")
        for var_name, label in [(sand_var, "sand"), (silt_var, "silt"), (clay_var, "clay")]:
            if var_name not in ds.variables:
                errors.append(f"{label} variable '{var_name}' not found in {input_path}")
        ds.close()
    except Exception as e:
        errors.append(f"Cannot open file: {e}")

    return errors


def classify_soil(sand, silt, clay):
    """
    Classify soil into LPJmL 13-type scheme using USDA texture triangle.

    Parameters:
        sand, silt, clay: float percentages (0-100), must sum to ~100

    Returns:
        int soil code (1-13), 0 for missing/invalid
    """
    # Normalize to ensure sum is 100
    total = sand + silt + clay
    if total < 1.0 or np.isnan(total):
        return 0  # missing data

    sand = sand / total * 100
    silt = silt / total * 100
    clay = clay / total * 100

    # Classification using simplified USDA rules
    if clay >= 40:
        if silt >= 40:
            return 2  # silty clay
        elif sand >= 45:
            return 3  # sandy clay
        else:
            return 1  # clay
    elif clay >= 27:
        if silt >= 40:
            return 5  # silty clay loam
        elif sand >= 45:
            return 6  # sandy clay loam
        else:
            return 4  # clay loam
    elif clay >= 7 and clay < 27:
        if silt >= 80:
            return 10  # silt
        elif silt >= 50:
            return 8  # silt loam
        elif sand >= 70:
            if sand >= 85:
                return 12  # sand
            else:
                return 11  # loamy sand
        elif sand >= 43:
            return 9  # sandy loam
        else:
            return 7  # loam
    else:  # clay < 7
        if silt >= 80:
            return 10  # silt
        elif silt >= 50:
            return 8  # silt loam
        elif sand >= 85:
            return 12  # sand
        elif sand >= 70:
            return 11  # loamy sand
        elif sand >= 43:
            return 9  # sandy loam
        else:
            return 8  # silt loam (default for low sand, low clay)

    return 7  # fallback: loam


# Vectorized version for numpy arrays
classify_soil_vec = np.vectorize(classify_soil)


def validate_outputs(soil_codes, ncell):
    """Post-processing validation: check soil type distribution."""
    warnings = []

    valid = soil_codes[(soil_codes >= 1) & (soil_codes <= 13)]
    invalid = soil_codes[(soil_codes < 1) | (soil_codes > 13)]

    if len(invalid) > ncell * 0.5:
        warnings.append(
            f"WARNING: {len(invalid)}/{ncell} cells have invalid soil codes. "
            "Check input data coverage."
        )

    # Check for unrealistic distribution
    unique, counts = np.unique(valid, return_counts=True)
    for code, count in zip(unique, counts):
        frac = count / ncell * 100
        if frac > 80:
            warnings.append(
                f"WARNING: Soil type {code} ({LPJML_SOIL_TYPES[code]['name']}) "
                f"covers {frac:.1f}% of cells. May indicate classification error."
            )

    print(f"Soil type distribution ({len(valid)} valid cells):")
    for code, count in zip(unique, counts):
        name = LPJML_SOIL_TYPES.get(int(code), {}).get("name", "unknown")
        print(f"  {code:2d} {name:20s}: {count:6d} ({count/ncell*100:5.1f}%)")

    return warnings


def process(input_path, sand_var, silt_var, clay_var, output_path,
            grid_path=None, rock_threshold=95.0):
    """Main conversion: soil texture -> LPJmL soil codes."""

    # Step 1: Validate inputs
    errors = validate_inputs(input_path, sand_var, silt_var, clay_var)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    # Step 2: Read soil texture data
    ds = nc.Dataset(input_path, "r")
    sand = ds.variables[sand_var][:].flatten()
    silt = ds.variables[silt_var][:].flatten()
    clay = ds.variables[clay_var][:].flatten()
    ds.close()

    # Handle masked arrays
    if hasattr(sand, "filled"):
        sand = sand.filled(np.nan)
    if hasattr(silt, "filled"):
        silt = silt.filled(np.nan)
    if hasattr(clay, "filled"):
        clay = clay.filled(np.nan)

    ncell = len(sand)
    print(f"Processing {ncell} cells")

    # Check if fractions are in 0-1 or 0-100 range
    max_sand = np.nanmax(sand)
    if max_sand <= 1.0:
        print("Detected fractions in 0-1 range, converting to 0-100%")
        sand *= 100
        silt *= 100
        clay *= 100

    # Step 3: Classify
    soil_codes = classify_soil_vec(sand, silt, clay)

    # Mark rock/ice where sand is extremely high and no real soil
    rock_mask = (sand > rock_threshold) & (clay < 2)
    soil_codes[rock_mask] = 13

    # Mark missing data as 0
    missing = np.isnan(sand) | np.isnan(silt) | np.isnan(clay)
    soil_codes[missing] = 0

    # Step 4: Validate outputs
    warnings = validate_outputs(soil_codes, ncell)
    for w in warnings:
        print(w, file=sys.stderr)

    # Step 5: Write binary output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Write as CLM file with header
    with open(output_path, "wb") as f:
        # Simple header for soil data
        f.write(b"LPJSOIL")
        f.write(struct.pack("<i", 3))       # version
        f.write(struct.pack("<i", 1))       # order
        f.write(struct.pack("<i", 0))       # firstyear (not applicable)
        f.write(struct.pack("<i", 1))       # nyear
        f.write(struct.pack("<i", 0))       # firstcell
        f.write(struct.pack("<i", ncell))   # ncell
        f.write(struct.pack("<i", 1))       # nbands
        f.write(struct.pack("<f", 0.5))     # cellsize_lon
        f.write(struct.pack("<f", 0.5))     # cellsize_lat
        f.write(struct.pack("<i", 0))       # datatype (byte)
        f.write(struct.pack("<f", 1.0))     # scalar
        f.write(struct.pack("<i", 1))       # nstep

        soil_codes.astype(np.uint8).tofile(f)

    print(f"Written: {output_path} ({os.path.getsize(output_path)} bytes)")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Convert HWSD soil texture to LPJmL 13-type soil codes"
    )
    parser.add_argument("--input", required=True, help="Input NetCDF with soil texture")
    parser.add_argument("--sand_var", default="T_SAND", help="Sand percentage variable")
    parser.add_argument("--silt_var", default="T_SILT", help="Silt percentage variable")
    parser.add_argument("--clay_var", default="T_CLAY", help="Clay percentage variable")
    parser.add_argument("--output", required=True, help="Output CLM binary file")
    parser.add_argument("--grid", default=None, help="Grid file for cell selection")
    parser.add_argument("--rock_threshold", type=float, default=95.0,
                        help="Sand %% threshold for rock/ice classification")

    args = parser.parse_args()

    success = process(
        input_path=args.input,
        sand_var=args.sand_var,
        silt_var=args.silt_var,
        clay_var=args.clay_var,
        output_path=args.output,
        grid_path=args.grid,
        rock_threshold=args.rock_threshold,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
