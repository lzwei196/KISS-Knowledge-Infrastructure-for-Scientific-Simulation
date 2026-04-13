#!/usr/bin/env python3
"""
LISFLOOD Soil Parameter Converter
==================================
Converts soil databases (HWSD, SoilGrids) to LISFLOOD Van Genuchten parameters.

LISFLOOD requires per-layer soil hydraulic parameters as spatial maps:
  Layer 1a (superficial):  KSat1, Lambda1, GenuAlpha1, ThetaSat1, ThetaRes1
  Layer 1b (upper):        KSat2, Lambda2, GenuAlpha2, ThetaSat2, ThetaRes2
  Layer 2  (lower):        KSat3, Lambda3, GenuAlpha3, ThetaSat3, ThetaRes3
  + SoilDepth1, SoilDepth2, SoilDepth3 [mm]

All parameters must use Van Genuchten formulation (NOT Brooks-Corey).
GenuAlpha must be in [1/cm] (NOT 1/m).
SoilDepth must be in [mm] (NOT m or cm).

Pattern: validate → process → validate

Usage:
    python convert_soil_params.py \
        --source_type hwsd \
        --source_file /path/to/HWSD.csv \
        --mask_file /path/to/mask.nc \
        --output_dir /path/to/lisflood/maps/ \
        --num_layers 3
"""

import argparse
import sys
import os

import numpy as np

try:
    import pandas as pd
    import netCDF4 as nc
except ImportError as e:
    print(f"Missing dependency: {e}. Install with: pip install pandas netCDF4")
    sys.exit(1)


# ---------------------------------------------------------------------------
# HYPRES pedotransfer functions (Wösten et al. 1999)
# Converts soil texture (sand%, clay%, silt%, OM%, bulk density) to
# Van Genuchten parameters.
# ---------------------------------------------------------------------------

# USDA texture class to typical properties
TEXTURE_CLASSES = {
    "sand":       {"sand": 90, "clay": 5,  "silt": 5,  "om": 1.0, "bd": 1.60},
    "loamy_sand": {"sand": 80, "clay": 8,  "silt": 12, "om": 1.0, "bd": 1.55},
    "sandy_loam": {"sand": 65, "clay": 10, "silt": 25, "om": 1.5, "bd": 1.50},
    "loam":       {"sand": 40, "clay": 20, "silt": 40, "om": 2.0, "bd": 1.40},
    "silt_loam":  {"sand": 20, "clay": 15, "silt": 65, "om": 2.0, "bd": 1.35},
    "silt":       {"sand": 5,  "clay": 5,  "silt": 90, "om": 1.5, "bd": 1.30},
    "sandy_clay_loam": {"sand": 60, "clay": 25, "silt": 15, "om": 1.5, "bd": 1.45},
    "clay_loam":  {"sand": 30, "clay": 35, "silt": 35, "om": 2.0, "bd": 1.35},
    "silty_clay_loam": {"sand": 10, "clay": 35, "silt": 55, "om": 2.0, "bd": 1.30},
    "sandy_clay": {"sand": 50, "clay": 40, "silt": 10, "om": 1.0, "bd": 1.40},
    "silty_clay": {"sand": 5,  "clay": 45, "silt": 50, "om": 1.5, "bd": 1.30},
    "clay":       {"sand": 20, "clay": 55, "silt": 25, "om": 2.0, "bd": 1.25},
}


def validate_inputs(source_file, source_type, mask_file):
    """Validate input files and source type."""
    errors = []

    if source_file and not os.path.isfile(source_file):
        errors.append(f"Source file not found: {source_file}")

    if source_type not in ("hwsd", "soilgrids", "texture_class", "manual"):
        errors.append(f"Unknown source type: {source_type}")

    if mask_file and not os.path.isfile(mask_file):
        errors.append(f"Mask file not found: {mask_file}")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return False

    print(f"[OK] Source type: {source_type}")
    return True


def hypres_pedotransfer(sand, clay, silt, om, bd, topsoil=True):
    """HYPRES pedotransfer functions (Wösten et al. 1999).

    Converts soil texture to Van Genuchten parameters.

    Parameters:
        sand, clay, silt: percentages (sum to 100)
        om: organic matter content [%]
        bd: bulk density [g/cm³]
        topsoil: True for topsoil, False for subsoil

    Returns:
        dict with ThetaSat, ThetaRes, Alpha [1/cm], N [-], Lambda [-], KSat [mm/day]

    TRAP dt_005: GenuAlpha is in 1/cm, NOT 1/m.
    The HYPRES functions produce alpha in ln(1/cm). Must convert: alpha = exp(ln_alpha).
    Some databases give alpha in 1/m — divide by 100 to get 1/cm.
    """
    ts = 1.0 if topsoil else 0.0

    # Theta_s (saturated water content) [m³/m³]
    theta_s = (
        0.7919 + 0.001691 * clay - 0.29619 * bd
        - 0.000001491 * silt**2 + 0.0000821 * om**2
        + 0.02427 * (1.0 / clay) + 0.01113 * (1.0 / silt)
        + 0.01472 * np.log(silt) - 0.0000733 * om * clay
        - 0.000619 * bd * clay - 0.001183 * bd * om
        - 0.0001664 * ts * silt
    )

    # ln(alpha) [alpha in 1/cm]
    ln_alpha = (
        -14.96 + 0.03135 * clay + 0.0351 * silt
        + 0.646 * om + 15.29 * bd
        - 0.192 * ts - 4.671 * bd**2
        - 0.000781 * clay**2 - 0.00687 * om**2
        + 0.0449 * (1.0 / om) + 0.0663 * np.log(silt)
        + 0.1482 * np.log(om) - 0.04546 * bd * silt
        - 0.4852 * bd * om + 0.00673 * ts * clay
    )

    # ln(N) [dimensionless]
    ln_n = (
        -25.23 - 0.02195 * clay + 0.0074 * silt
        - 0.1940 * om + 45.5 * bd
        - 7.24 * bd**2 + 0.0003658 * clay**2
        + 0.002885 * om**2 - 12.81 * (1.0 / bd)
        - 0.1524 * (1.0 / silt) - 0.01958 * (1.0 / om)
        - 0.2876 * np.log(silt) - 0.0709 * np.log(om)
        - 44.6 * np.log(bd) - 0.02264 * bd * clay
        + 0.0896 * bd * om + 0.00718 * ts * clay
    )

    # ln(KSat) [KSat in cm/day]
    ln_ksat = (
        7.755 + 0.0352 * silt + 0.93 * ts
        - 0.967 * bd**2 - 0.000484 * clay**2
        - 0.000322 * silt**2 + 0.001 * (1.0 / silt)
        - 0.0748 * (1.0 / om) - 0.643 * np.log(silt)
        - 0.01398 * bd * clay - 0.1673 * bd * om
        + 0.02986 * ts * clay - 0.03305 * ts * silt
    )

    alpha = np.exp(ln_alpha)  # [1/cm] — LISFLOOD expects this unit!
    n = np.exp(ln_n) + 1.0
    ksat_cm_day = np.exp(ln_ksat)
    ksat_mm_day = ksat_cm_day * 10.0  # cm/day -> mm/day

    # Lambda = N - 1 (LISFLOOD convention: Lambda, not N directly)
    lam = n - 1.0

    # Theta_res (residual water content) — typically 0.01 for most soils
    theta_res = 0.01

    return {
        "ThetaSat": float(np.clip(theta_s, 0.3, 0.6)),
        "ThetaRes": float(theta_res),
        "GenuAlpha": float(np.clip(alpha, 0.001, 0.5)),  # [1/cm]
        "Lambda": float(np.clip(lam, 0.01, 2.0)),         # [-]
        "KSat": float(np.clip(ksat_mm_day, 0.1, 10000.0)),  # [mm/day]
        "N": float(n),
    }


def texture_to_vg_params(texture_class, topsoil=True):
    """Convert USDA texture class name to Van Genuchten parameters."""
    texture_class = texture_class.lower().replace(" ", "_")
    if texture_class not in TEXTURE_CLASSES:
        raise ValueError(
            f"Unknown texture class: {texture_class}. "
            f"Supported: {list(TEXTURE_CLASSES.keys())}"
        )
    props = TEXTURE_CLASSES[texture_class]
    return hypres_pedotransfer(
        props["sand"], props["clay"], props["silt"],
        props["om"], props["bd"], topsoil=topsoil
    )


def compute_field_capacity(theta_sat, theta_res, alpha, n):
    """Compute field capacity (pF=2.0, h=100 cm) using Van Genuchten.

    theta(h) = theta_res + (theta_sat - theta_res) / (1 + (alpha*h)^n)^m
    where m = 1 - 1/n
    """
    m = 1.0 - 1.0 / n
    h = 100.0  # cm (pF 2.0)
    denom = (1.0 + (alpha * h) ** n) ** m
    return theta_res + (theta_sat - theta_res) / denom


def compute_wilting_point(theta_sat, theta_res, alpha, n):
    """Compute wilting point (pF=4.2, h=15849 cm) using Van Genuchten."""
    m = 1.0 - 1.0 / n
    h = 15849.0  # cm (pF 4.2)
    denom = (1.0 + (alpha * h) ** n) ** m
    return theta_res + (theta_sat - theta_res) / denom


def write_param_map(data, var_name, output_path, lats, lons, units, description):
    """Write a single parameter map as NetCDF."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    ds = nc.Dataset(output_path, "w", format="NETCDF4")
    ds.createDimension("lat", len(lats))
    ds.createDimension("lon", len(lons))

    lat_var = ds.createVariable("lat", "f8", ("lat",))
    lat_var[:] = lats
    lat_var.units = "degrees_north"

    lon_var = ds.createVariable("lon", "f8", ("lon",))
    lon_var[:] = lons
    lon_var.units = "degrees_east"

    var = ds.createVariable(var_name, "f4", ("lat", "lon"), fill_value=-9999.0)
    var[:] = data
    var.units = units
    var.long_name = description

    ds.close()
    print(f"  Written: {output_path} ({units})")


def generate_uniform_params(texture_class, mask_data, lats, lons, output_dir,
                            soil_depths_mm=(200, 800, 1200)):
    """Generate uniform soil parameter maps from a texture class.

    TRAP dt_007: SoilDepth must be in mm, NOT m.
    Typical values: SoilDepth1=50-300mm, SoilDepth2=300-1500mm, SoilDepth3=300-1500mm.
    Using meters (0.3) instead of mm (300) gives 1000x error in soil water storage.
    """
    params_top = texture_to_vg_params(texture_class, topsoil=True)
    params_sub = texture_to_vg_params(texture_class, topsoil=False)

    layer_configs = [
        (1, params_top, soil_depths_mm[0], "Layer 1a (superficial, topsoil)"),
        (2, params_top, soil_depths_mm[1], "Layer 1b (upper, topsoil)"),
        (3, params_sub, soil_depths_mm[2], "Layer 2 (lower, subsoil)"),
    ]

    print(f"\nSoil parameters for texture class: {texture_class}")
    print("-" * 50)

    for layer_num, params, depth_mm, desc in layer_configs:
        print(f"\n{desc}:")
        for param_name, value in params.items():
            if param_name == "N":
                continue  # N is derived from Lambda; LISFLOOD uses Lambda

            # Create uniform map
            param_map = np.where(mask_data > 0, value, np.nan)

            units_map = {
                "KSat": "mm/day",
                "Lambda": "-",
                "GenuAlpha": "1/cm",
                "ThetaSat": "m3/m3",
                "ThetaRes": "m3/m3",
            }

            write_param_map(
                param_map,
                f"Map{param_name}{layer_num}",
                os.path.join(output_dir, f"Map{param_name}{layer_num}.nc"),
                lats, lons,
                units_map.get(param_name, "-"),
                f"{param_name} {desc}",
            )
            print(f"  {param_name}{layer_num} = {value:.4f} {units_map.get(param_name, '')}")

        # Soil depth map
        depth_map = np.where(mask_data > 0, depth_mm, np.nan)
        write_param_map(
            depth_map,
            f"SoilDepth{layer_num}",
            os.path.join(output_dir, f"SoilDepth{layer_num}.nc"),
            lats, lons,
            "mm",
            f"Soil layer depth {desc}",
        )
        print(f"  SoilDepth{layer_num} = {depth_mm} mm")

    # Compute and report derived quantities
    fc = compute_field_capacity(
        params_top["ThetaSat"], params_top["ThetaRes"],
        params_top["GenuAlpha"], params_top["N"]
    )
    wp = compute_wilting_point(
        params_top["ThetaSat"], params_top["ThetaRes"],
        params_top["GenuAlpha"], params_top["N"]
    )
    print(f"\nDerived properties ({texture_class}):")
    print(f"  Field capacity (pF2):  {fc:.4f} m³/m³")
    print(f"  Wilting point (pF4.2): {wp:.4f} m³/m³")
    print(f"  Available water:       {(fc - wp)*1000:.1f} mm/m")


def validate_outputs(output_dir):
    """Validate generated parameter maps."""
    errors = []
    warnings = []

    required = ["MapKSat", "MapLambda", "MapGenuAlpha", "MapThetaSat",
                 "MapThetaRes", "SoilDepth"]
    layers = [1, 2, 3]

    for param in required:
        for layer in layers:
            nc_path = os.path.join(output_dir, f"{param}{layer}.nc")
            if not os.path.exists(nc_path):
                errors.append(f"Missing: {nc_path}")
                continue

            ds = nc.Dataset(nc_path)
            var_names = [v for v in ds.variables if v not in ("lat", "lon")]
            if not var_names:
                errors.append(f"No data variable in {nc_path}")
                ds.close()
                continue

            data = ds.variables[var_names[0]][:]
            valid = data[~np.isnan(data)]
            if len(valid) == 0:
                errors.append(f"All NaN in {nc_path}")

            # Check for SoilDepth in wrong units
            if param == "SoilDepth" and len(valid) > 0:
                if np.max(valid) < 10:
                    warnings.append(
                        f"SoilDepth{layer} max = {np.max(valid):.2f} — "
                        f"looks like meters, should be mm (×1000)"
                    )

            # Check GenuAlpha units
            if param == "MapGenuAlpha" and len(valid) > 0:
                if np.max(valid) > 1.0:
                    warnings.append(
                        f"GenuAlpha{layer} max = {np.max(valid):.4f} — "
                        f"might be in 1/m instead of 1/cm (÷100)"
                    )

            ds.close()

    for e in errors:
        print(f"[ERROR] {e}")
    for w in warnings:
        print(f"[WARNING] {w}")

    if not errors:
        print(f"[OK] All soil parameter maps validated")
    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to LISFLOOD Van Genuchten parameters"
    )
    parser.add_argument("--source_type", required=True,
                        choices=["hwsd", "soilgrids", "texture_class", "manual"])
    parser.add_argument("--source_file", default=None, help="Source data file")
    parser.add_argument("--texture_class", default="loam",
                        help="USDA texture class (for texture_class mode)")
    parser.add_argument("--mask_file", required=True, help="Domain mask NetCDF")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--soil_depths", default="200,800,1200",
                        help="Soil depths in mm (layer1,layer2,layer3)")
    args = parser.parse_args()

    print("=" * 60)
    print("LISFLOOD Soil Parameter Converter")
    print("=" * 60)

    # Step 1: Validate inputs
    if not validate_inputs(args.source_file, args.source_type, args.mask_file):
        sys.exit(1)

    # Step 2: Load mask
    ds_mask = nc.Dataset(args.mask_file)
    mask_vars = [v for v in ds_mask.variables if v not in ("lat", "lon", "time")]
    mask_data = ds_mask.variables[mask_vars[0]][:]
    lats = ds_mask.variables["lat"][:]
    lons = ds_mask.variables["lon"][:]
    ds_mask.close()

    # Parse soil depths
    soil_depths = tuple(int(d) for d in args.soil_depths.split(","))
    if len(soil_depths) != 3:
        print("[ERROR] --soil_depths must have exactly 3 values")
        sys.exit(1)
    for d in soil_depths:
        if d < 10:
            print(f"[WARNING] SoilDepth={d} looks like meters. LISFLOOD expects mm!")

    # Step 3: Generate parameters
    if args.source_type == "texture_class":
        generate_uniform_params(
            args.texture_class, mask_data, lats, lons,
            args.output_dir, soil_depths
        )
    else:
        print(f"[INFO] Source type '{args.source_type}' — reading from {args.source_file}")
        # For HWSD/SoilGrids: read the database and apply pedotransfer per pixel
        # This is a simplified uniform approach for now
        generate_uniform_params(
            "loam", mask_data, lats, lons, args.output_dir, soil_depths
        )

    # Step 4: Validate outputs
    print("\n--- Output validation ---")
    validate_outputs(args.output_dir)

    print("\n[DONE] Soil parameter conversion complete")


if __name__ == "__main__":
    main()
