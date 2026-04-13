#!/usr/bin/env python3
"""
Convert HWSD (Harmonized World Soil Database) soil data to GSFLOW PRMS parameters.

Usage:
    python convert_soil_params.py \
        --hwsd /path/to/HWSD_China_Geo.img \
        --shapefile /path/to/basin.shp \
        --output /path/to/soil.params \
        --n-hru 128

Pipeline Stage: s2 (Soil Parameters)
Follows: validate → process → validate pattern

Key GSFLOW soil parameters derived:
    - soil_moist_max: maximum soil moisture capacity (inches)
    - soil_rechr_max: maximum recharge zone capacity (inches)
    - soil_type: soil type index (1=sand, 2=loam, 3=clay)
    - sat_threshold: saturated threshold (inches)
    - ssr2gw_rate: subsurface-to-groundwater transfer rate
    - slowcoef_lin: linear interflow coefficient
    - hru_percent_imperv: impervious fraction
"""

import os
import sys
import argparse
import numpy as np

try:
    import rasterio
    from rasterio.mask import mask as rio_mask
except ImportError:
    rasterio = None

try:
    import geopandas as gpd
except ImportError:
    gpd = None


# ── Soil Property Lookup Tables ──────────────────────────────────────────
# HWSD texture classes → GSFLOW soil parameters
# References: Rawls et al. (1982), Saxton & Rawls (2006)
SOIL_TEXTURE_PARAMS = {
    # texture_class: (soil_type, porosity, fc, wp, ksat_mm_hr, depth_mm)
    "sand":         (1, 0.43, 0.10, 0.05, 210.0, 1500),
    "loamy_sand":   (1, 0.44, 0.15, 0.07, 61.0,  1500),
    "sandy_loam":   (2, 0.45, 0.21, 0.10, 26.0,  1500),
    "loam":         (2, 0.46, 0.27, 0.12, 13.0,  1500),
    "silt_loam":    (2, 0.47, 0.33, 0.13, 6.8,   1500),
    "silt":         (2, 0.46, 0.35, 0.12, 3.4,   1500),
    "sandy_clay_loam": (3, 0.39, 0.26, 0.15, 4.3, 1200),
    "clay_loam":    (3, 0.41, 0.32, 0.20, 2.3,   1200),
    "silty_clay_loam": (3, 0.43, 0.37, 0.22, 1.5, 1200),
    "sandy_clay":   (3, 0.38, 0.31, 0.24, 1.2,   1000),
    "silty_clay":   (3, 0.36, 0.37, 0.27, 0.9,   1000),
    "clay":         (3, 0.38, 0.40, 0.27, 0.6,   1000),
}

# HWSD numeric code → texture class
HWSD_CODE_MAP = {
    1: "sand", 2: "loamy_sand", 3: "sandy_loam", 4: "silt_loam",
    5: "silt", 6: "loam", 7: "sandy_clay_loam", 8: "clay_loam",
    9: "silty_clay_loam", 10: "sandy_clay", 11: "silty_clay", 12: "clay",
    13: "loam",  # organic soils → default to loam
}

MM_TO_INCHES = 1.0 / 25.4


def validate_inputs(hwsd_path, shapefile, n_hru):
    """Validate all inputs before processing."""
    errors = []

    if hwsd_path and not os.path.isfile(hwsd_path):
        errors.append(f"HWSD raster not found: {hwsd_path}")

    if shapefile and not os.path.isfile(shapefile):
        errors.append(f"Shapefile not found: {shapefile}")

    if rasterio is None:
        errors.append("rasterio not installed. Run: pip install rasterio")

    if gpd is None:
        errors.append("geopandas not installed. Run: pip install geopandas")

    if n_hru < 1:
        errors.append(f"n_hru must be >= 1, got {n_hru}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False
    return True


def extract_soil_classes(hwsd_path, shapefile, n_hru=1):
    """
    Extract dominant soil texture class for each HRU from HWSD raster.

    For lumped (n_hru=1): returns basin-average soil class.
    For distributed: would require HRU shapefile with multiple polygons.
    """
    basin = gpd.read_file(shapefile)

    with rasterio.open(hwsd_path) as src:
        # Reproject basin to match raster CRS if needed
        if basin.crs != src.crs:
            basin = basin.to_crs(src.crs)

        # Mask raster with basin boundary
        out_image, out_transform = rio_mask(src, basin.geometry, crop=True, nodata=-9999)
        soil_data = out_image[0]

    # Remove nodata
    valid = soil_data[soil_data > 0]
    if len(valid) == 0:
        print("WARNING: No valid soil data in basin. Using default (loam).", file=sys.stderr)
        return [6] * n_hru  # Default: loam

    # Get dominant soil class for each HRU
    # For lumped: mode of all cells
    from scipy import stats
    dominant = int(stats.mode(valid, keepdims=True).mode[0])

    soil_classes = [dominant] * n_hru
    print(f"  Dominant soil texture code: {dominant} → {HWSD_CODE_MAP.get(dominant, 'unknown')}")
    return soil_classes


def soil_class_to_params(soil_code):
    """
    Convert HWSD soil code to GSFLOW parameter set.

    Returns dict of parameter_name → value.

    TRAP: GSFLOW expects soil moisture in INCHES, not mm.
    HWSD depths are in mm → must convert.
    """
    texture = HWSD_CODE_MAP.get(soil_code, "loam")
    soil_type, porosity, fc, wp, ksat, depth = SOIL_TEXTURE_PARAMS[texture]

    # Available water capacity (field capacity - wilting point)
    awc = fc - wp

    # Soil moisture max = AWC × depth (mm) → convert to inches
    soil_moist_max = awc * depth * MM_TO_INCHES

    # Recharge zone = top 300mm of soil
    recharge_depth = min(300, depth)
    soil_rechr_max = awc * recharge_depth * MM_TO_INCHES

    # Saturated threshold
    sat_threshold = porosity * depth * MM_TO_INCHES

    # Subsurface-to-groundwater rate (fraction/day)
    # Higher Ksat → faster drainage
    ssr2gw_rate = min(0.8, ksat / 500.0)

    # Linear interflow coefficient
    slowcoef_lin = min(0.5, ksat / 1000.0)

    return {
        "soil_type": soil_type,
        "soil_moist_max": round(soil_moist_max, 4),
        "soil_rechr_max": round(soil_rechr_max, 4),
        "sat_threshold": round(sat_threshold, 4),
        "ssr2gw_rate": round(ssr2gw_rate, 6),
        "slowcoef_lin": round(slowcoef_lin, 6),
        "fastcoef_lin": round(min(0.9, ksat / 200.0), 6),
        "soil2gw_max": round(min(2.0, ksat * 24 / 1000.0 * MM_TO_INCHES), 6),
        "ksat_mm_hr": ksat,  # For reference only
    }


def write_params_file(output_path, params_per_hru, n_hru):
    """
    Write GSFLOW PRMS parameter file for soil parameters.

    Format:
        Parameter file header
        ** Dimensions **
        ####
        nhru
        N
        ####
        ** Parameters **
        ####
        param_name
        1
        nhru
        N
        2  (data type: 2=float, 1=int)
        value1
        value2
        ...
        ####
    """
    with open(output_path, "w") as f:
        f.write("GSFLOW soil parameters from HWSD\n")
        f.write("** Dimensions **\n")
        f.write("####\n")
        f.write("nhru\n")
        f.write(f"{n_hru}\n")
        f.write("nssr\n")
        f.write(f"{n_hru}\n")
        f.write("####\n")
        f.write("** Parameters **\n")

        # Write each parameter
        float_params = [
            "soil_moist_max", "soil_rechr_max", "sat_threshold",
            "ssr2gw_rate", "slowcoef_lin", "fastcoef_lin", "soil2gw_max"
        ]
        int_params = ["soil_type"]

        for param_name in int_params:
            f.write("####\n")
            f.write(f"{param_name}\n")
            f.write("1\n")
            f.write("nhru\n")
            f.write(f"{n_hru}\n")
            f.write("1\n")  # data type 1 = integer
            for hru_params in params_per_hru:
                f.write(f"{hru_params[param_name]}\n")

        for param_name in float_params:
            f.write("####\n")
            f.write(f"{param_name}\n")
            f.write("1\n")
            dim_name = "nssr" if param_name in ("ssr2gw_rate", "slowcoef_lin", "fastcoef_lin") else "nhru"
            f.write(f"{dim_name}\n")
            f.write(f"{n_hru}\n")
            f.write("2\n")  # data type 2 = float
            for hru_params in params_per_hru:
                f.write(f"{hru_params[param_name]}\n")

        f.write("####\n")

    print(f"  Wrote soil parameters to {output_path}")


def validate_outputs(output_path, n_hru):
    """Validate the generated parameter file."""
    errors = []

    if not os.path.isfile(output_path):
        errors.append(f"Output file not created: {output_path}")
        return False

    with open(output_path) as f:
        content = f.read()

    # Check for required parameters
    required = ["soil_moist_max", "soil_rechr_max", "soil_type", "ssr2gw_rate"]
    for param in required:
        if param not in content:
            errors.append(f"Missing parameter: {param}")

    # Check soil_moist_max values are reasonable (0.5 - 30 inches)
    lines = content.split("\n")
    in_smm = False
    smm_values = []
    for i, line in enumerate(lines):
        if line.strip() == "soil_moist_max":
            in_smm = True
            continue
        if in_smm and line.strip() == "####":
            in_smm = False
        if in_smm:
            try:
                val = float(line.strip())
                smm_values.append(val)
            except ValueError:
                pass

    for val in smm_values:
        if val < 0.1:
            errors.append(f"soil_moist_max too low: {val} inches (check mm→inches conversion)")
        if val > 50:
            errors.append(f"soil_moist_max too high: {val} inches (still in mm?)")

    if errors:
        for e in errors:
            print(f"WARNING: {e}", file=sys.stderr)
        return False

    print("  Soil parameter validation PASSED")
    return True


def main():
    parser = argparse.ArgumentParser(description="Convert HWSD to GSFLOW soil parameters")
    parser.add_argument("--hwsd", required=True, help="Path to HWSD raster")
    parser.add_argument("--shapefile", required=True, help="Basin boundary shapefile")
    parser.add_argument("--output", required=True, help="Output .params file path")
    parser.add_argument("--n-hru", type=int, default=1, help="Number of HRUs")
    args = parser.parse_args()

    print("=" * 60)
    print("GSFLOW Soil Parameter Converter (HWSD → PRMS .params)")
    print("=" * 60)

    # ── Step 1: Validate ──
    if not validate_inputs(args.hwsd, args.shapefile, args.n_hru):
        sys.exit(1)

    # ── Step 2: Extract soil classes ──
    print(f"\n[1/3] Extracting soil classes from HWSD")
    soil_classes = extract_soil_classes(args.hwsd, args.shapefile, args.n_hru)

    # ── Step 3: Convert to GSFLOW parameters ──
    print(f"\n[2/3] Converting soil classes to GSFLOW parameters")
    params_per_hru = []
    for hru_idx, code in enumerate(soil_classes):
        params = soil_class_to_params(code)
        params_per_hru.append(params)
        if hru_idx == 0:
            print(f"  HRU 1: texture={HWSD_CODE_MAP.get(code, 'unknown')}, "
                  f"soil_moist_max={params['soil_moist_max']} in, "
                  f"soil_type={params['soil_type']}")

    # ── Step 4: Write parameter file ──
    print(f"\n[3/3] Writing parameter file")
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    write_params_file(args.output, params_per_hru, args.n_hru)

    # ── Step 5: Validate outputs ──
    validate_outputs(args.output, args.n_hru)

    print(f"\nDone! Soil parameters written to {args.output}")


if __name__ == "__main__":
    main()
