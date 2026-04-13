#!/usr/bin/env python3
"""
convert_surface_data.py — Surface Dataset Generator for FATES/CTSM

Generates or modifies CLM surface datasets for single-point FATES runs.
Maps soil properties from HWSD or user-specified values and configures
PFT distributions for the target location.

Follows validate → process → validate pattern.

Usage:
    python convert_surface_data.py --lat 9.15 --lon -79.85 \
        --soil-source hwsd --hwsd-path /path/to/HWSD.nc \
        --output surfdata_bci.nc

    python convert_surface_data.py --lat 45.0 --lon -90.0 \
        --soil-texture "clay_pct=25,sand_pct=40,silt_pct=35" \
        --soil-depth 2.0 --output surfdata_custom.nc

    python convert_surface_data.py --lat 9.15 --lon -79.85 \
        --pft-distribution "1:0.8,5:0.2" --output surfdata_tropical.nc
"""

import argparse
import json
import os
import sys
import numpy as np
from typing import Dict, List, Any, Optional, Tuple

# ─── USDA Soil Texture Classes ──────────────────────────────────────────────
SOIL_TEXTURE_CLASSES = {
    "clay":       {"clay": 60, "sand": 20, "silt": 20},
    "silty_clay": {"clay": 45, "sand": 5,  "silt": 50},
    "sandy_clay": {"clay": 40, "sand": 50, "silt": 10},
    "clay_loam":  {"clay": 33, "sand": 33, "silt": 34},
    "loam":       {"clay": 20, "sand": 40, "silt": 40},
    "sandy_loam": {"clay": 10, "sand": 65, "silt": 25},
    "silt_loam":  {"clay": 15, "sand": 20, "silt": 65},
    "sand":       {"clay": 5,  "sand": 90, "silt": 5},
    "silt":       {"clay": 5,  "sand": 5,  "silt": 90},
}

# ─── CLM Soil Layer Depths (m) ──────────────────────────────────────────────
CLM_SOIL_DEPTHS = [
    0.0175, 0.0451, 0.0906, 0.1655, 0.2891, 0.4929, 0.8289,
    1.3828, 2.2961, 3.8019, 6.3258, 10.5297, 17.5328, 25.0,
    35.0, 45.0  # bedrock layers
]

# ─── Default PFT area fractions (tropical broadleaf evergreen) ──────────────
DEFAULT_PFT_FRACTIONS = {0: 1.0}  # 100% broadleaf evergreen tropical

# ─── HWSD Soil Property Lookup by Texture Class ─────────────────────────────
HWSD_DEFAULTS = {
    "organic_matter": 2.0,        # % organic matter
    "bulk_density":   1.35,       # g/cm³
    "ph":             6.5,        # pH (water)
    "cec":            15.0,       # cmol/kg
    "gravel":         5.0,        # % gravel by volume
}


def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Stage 1: Validate command-line arguments."""
    errors = []

    # Validate coordinates
    if args.lat < -90 or args.lat > 90:
        errors.append(f"Latitude must be in [-90, 90], got {args.lat}")
    if args.lon < -360 or args.lon > 360:
        errors.append(f"Longitude must be in [-360, 360], got {args.lon}")

    # Validate soil source
    if args.soil_source == "hwsd" and args.hwsd_path:
        if not os.path.exists(args.hwsd_path):
            errors.append(f"HWSD file not found: {args.hwsd_path}")

    # Validate soil texture if provided
    if args.soil_texture:
        try:
            parts = parse_soil_texture(args.soil_texture)
            total = sum(parts.values())
            if abs(total - 100.0) > 1.0:
                errors.append(
                    f"Soil texture fractions must sum to 100%, got {total}%")
        except ValueError as e:
            errors.append(f"Invalid soil texture format: {e}")

    # Validate PFT distribution
    if args.pft_distribution:
        try:
            pft_dist = parse_pft_distribution(args.pft_distribution)
            total = sum(pft_dist.values())
            if abs(total - 1.0) > 0.01:
                errors.append(
                    f"PFT fractions must sum to 1.0, got {total}")
            for idx in pft_dist:
                if idx < 0 or idx >= 14:
                    errors.append(f"PFT index must be 0-13, got {idx}")
        except ValueError as e:
            errors.append(f"Invalid PFT distribution format: {e}")

    if args.soil_depth is not None:
        if args.soil_depth <= 0 or args.soil_depth > 100:
            errors.append(f"Soil depth must be in (0, 100] m, got {args.soil_depth}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2),
              file=sys.stderr)
        sys.exit(1)

    return errors


def parse_soil_texture(texture_str: str) -> Dict[str, float]:
    """Parse soil texture string like 'clay_pct=25,sand_pct=40,silt_pct=35'."""
    parts = {}
    for item in texture_str.split(","):
        key, val = item.strip().split("=")
        key = key.strip().replace("_pct", "")
        parts[key] = float(val.strip())
    return parts


def parse_pft_distribution(dist_str: str) -> Dict[int, float]:
    """Parse PFT distribution string like '1:0.8,5:0.2'."""
    result = {}
    for item in dist_str.split(","):
        idx, frac = item.strip().split(":")
        result[int(idx.strip())] = float(frac.strip())
    return result


def lookup_hwsd(lat: float, lon: float, hwsd_path: str) -> Dict[str, Any]:
    """Look up soil properties from HWSD NetCDF file."""
    try:
        import netCDF4 as nc
        ds = nc.Dataset(hwsd_path, "r")

        # Find nearest grid cell
        lats = ds.variables["lat"][:]
        lons = ds.variables["lon"][:]
        lat_idx = int(np.argmin(np.abs(lats - lat)))
        lon_idx = int(np.argmin(np.abs(lons - lon)))

        soil = {
            "clay_pct": float(ds.variables.get("T_CLAY", [20])[lat_idx, lon_idx]),
            "sand_pct": float(ds.variables.get("T_SAND", [40])[lat_idx, lon_idx]),
            "silt_pct": float(ds.variables.get("T_SILT", [40])[lat_idx, lon_idx]),
            "organic_matter": float(ds.variables.get("T_OC", [2.0])[lat_idx, lon_idx]),
            "bulk_density": float(ds.variables.get("T_BULK_DENSITY", [1.35])[lat_idx, lon_idx]),
            "source": "HWSD",
            "lat_idx": lat_idx,
            "lon_idx": lon_idx,
        }
        ds.close()
        return soil

    except Exception as e:
        print(f"Warning: HWSD lookup failed ({e}), using defaults", file=sys.stderr)
        return {
            "clay_pct": 20.0,
            "sand_pct": 40.0,
            "silt_pct": 40.0,
            "organic_matter": HWSD_DEFAULTS["organic_matter"],
            "bulk_density": HWSD_DEFAULTS["bulk_density"],
            "source": "default",
        }


def compute_hydraulic_properties(clay_pct: float, sand_pct: float,
                                  organic_matter: float) -> Dict[str, float]:
    """Compute soil hydraulic properties from texture (Clapp-Hornberger)."""
    # Clapp-Hornberger parameters from soil texture
    # Based on Cosby et al. (1984)
    b_ch = 2.91 + 0.159 * clay_pct
    psi_sat = -10.0 * (10.0 ** (1.88 - 0.0131 * sand_pct))  # mm
    k_sat = 0.0070556 * (10.0 ** (-0.884 + 0.0153 * sand_pct))  # mm/s

    # Porosity from bulk density (assume particle density 2.65 g/cm³)
    bd = max(0.5, min(2.0, 1.35 + 0.005 * clay_pct - 0.003 * organic_matter))
    porosity = 1.0 - bd / 2.65

    # Field capacity (at -33 kPa) and wilting point (at -1500 kPa)
    fc = porosity * (33.0 / abs(psi_sat)) ** (-1.0 / b_ch)
    wp = porosity * (1500.0 / abs(psi_sat)) ** (-1.0 / b_ch)

    return {
        "b_clapp_hornberger": round(b_ch, 3),
        "psi_sat_mm": round(psi_sat, 3),
        "k_sat_mm_s": round(k_sat, 6),
        "porosity": round(porosity, 4),
        "field_capacity": round(fc, 4),
        "wilting_point": round(wp, 4),
        "bulk_density_g_cm3": round(bd, 3),
    }


def generate_soil_profile(clay_pct: float, sand_pct: float,
                           silt_pct: float, soil_depth: float,
                           n_layers: int = 15) -> Dict[str, List[float]]:
    """Generate a soil property profile for CLM soil layers."""
    depths = CLM_SOIL_DEPTHS[:n_layers]

    # Simple depth-varying texture (clay increases with depth)
    clay_profile = [min(100, clay_pct + 2.0 * (d / soil_depth))
                    for d in depths if d <= soil_depth]
    sand_profile = [max(0, sand_pct - 1.5 * (d / soil_depth))
                    for d in depths if d <= soil_depth]

    # Pad with bedrock for layers below soil depth
    n_soil = len(clay_profile)
    while len(clay_profile) < n_layers:
        clay_profile.append(0.0)
        sand_profile.append(0.0)

    silt_profile = [max(0, 100.0 - c - s) for c, s in
                    zip(clay_profile, sand_profile)]

    # Organic matter decreases exponentially with depth
    om_profile = [max(0.1, 3.0 * np.exp(-d / 0.5)) for d in depths]

    return {
        "layer_depths_m": depths,
        "n_soil_layers": n_soil,
        "clay_pct": [round(v, 2) for v in clay_profile],
        "sand_pct": [round(v, 2) for v in sand_profile],
        "silt_pct": [round(v, 2) for v in silt_profile],
        "organic_matter_pct": [round(v, 3) for v in om_profile],
    }


def generate_surface_dataset(lat: float, lon: float,
                              soil_profile: Dict[str, List[float]],
                              pft_distribution: Dict[int, float],
                              hydraulic_props: Dict[str, float],
                              output_path: str) -> Dict[str, Any]:
    """Generate a surface dataset description (JSON format for documentation)."""
    # In a full implementation, this would write a NetCDF file via the host
    # model's mksurfdata_esmf tool. Here we generate the specification.
    dataset = {
        "metadata": {
            "title": f"FATES surface dataset for ({lat}, {lon})",
            "conventions": "CLM surface data format",
            "source": "convert_surface_data.py",
            "creation_date": "auto-generated",
        },
        "grid": {
            "latitude": lat,
            "longitude": lon if lon >= 0 else lon + 360,  # CLM uses 0-360
            "n_soil_layers": soil_profile["n_soil_layers"],
            "layer_depths_m": soil_profile["layer_depths_m"],
        },
        "soil_properties": {
            "clay_pct_by_layer": soil_profile["clay_pct"],
            "sand_pct_by_layer": soil_profile["sand_pct"],
            "silt_pct_by_layer": soil_profile["silt_pct"],
            "organic_matter_by_layer": soil_profile["organic_matter_pct"],
            "hydraulic": hydraulic_props,
        },
        "vegetation": {
            "pft_distribution": {f"PFT_{k}": v for k, v in pft_distribution.items()},
            "total_pft_fraction": sum(pft_distribution.values()),
            "n_active_pfts": len(pft_distribution),
        },
        "output_file": output_path,
    }

    # Write JSON specification
    with open(output_path, "w") as f:
        json.dump(dataset, f, indent=2)

    return dataset


def validate_outputs(dataset: Dict[str, Any]) -> List[str]:
    """Stage 3: Validate generated surface dataset."""
    warnings = []

    # Check soil texture sums
    soil = dataset.get("soil_properties", {})
    clay = soil.get("clay_pct_by_layer", [])
    sand = soil.get("sand_pct_by_layer", [])
    silt = soil.get("silt_pct_by_layer", [])

    for i, (c, s, si) in enumerate(zip(clay, sand, silt)):
        total = c + s + si
        if abs(total - 100.0) > 2.0 and total > 0:
            warnings.append(
                f"Layer {i}: texture fractions sum to {total:.1f}%, expected 100%")

    # Check PFT distribution
    veg = dataset.get("vegetation", {})
    total_pft = veg.get("total_pft_fraction", 0)
    if abs(total_pft - 1.0) > 0.01:
        warnings.append(
            f"PFT fractions sum to {total_pft}, expected 1.0")

    # Check coordinate conversion
    grid = dataset.get("grid", {})
    lon = grid.get("longitude", 0)
    if lon < 0:
        warnings.append(
            f"Longitude is negative ({lon}°). CLM typically uses 0-360° convention.")

    # Check hydraulic properties
    hydro = soil.get("hydraulic", {})
    porosity = hydro.get("porosity", 0)
    if porosity < 0.2 or porosity > 0.7:
        warnings.append(
            f"Porosity {porosity} outside typical range [0.2, 0.7]")

    fc = hydro.get("field_capacity", 0)
    wp = hydro.get("wilting_point", 0)
    if fc <= wp:
        warnings.append(
            f"Field capacity ({fc}) <= wilting point ({wp}) — physically impossible")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Generate surface dataset for FATES/CTSM single-point runs")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (degrees)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude (degrees)")
    parser.add_argument("--soil-source", choices=["hwsd", "manual", "texture_class"],
                        default="manual", help="Soil data source")
    parser.add_argument("--hwsd-path", help="Path to HWSD NetCDF file")
    parser.add_argument("--soil-texture",
                        help="Manual texture: clay_pct=25,sand_pct=40,silt_pct=35")
    parser.add_argument("--texture-class", choices=list(SOIL_TEXTURE_CLASSES.keys()),
                        help="USDA soil texture class name")
    parser.add_argument("--soil-depth", type=float, default=2.0,
                        help="Soil depth in meters (default: 2.0)")
    parser.add_argument("--pft-distribution",
                        help="PFT fractions: '1:0.8,5:0.2'")
    parser.add_argument("--output", required=True, help="Output file path")
    args = parser.parse_args()

    # Stage 1: Validate inputs
    validate_inputs(args)

    # Stage 2: Process
    # Determine soil texture
    if args.soil_source == "hwsd" and args.hwsd_path:
        soil = lookup_hwsd(args.lat, args.lon, args.hwsd_path)
        clay_pct = soil["clay_pct"]
        sand_pct = soil["sand_pct"]
        silt_pct = soil["silt_pct"]
        om = soil.get("organic_matter", HWSD_DEFAULTS["organic_matter"])
    elif args.texture_class:
        tex = SOIL_TEXTURE_CLASSES[args.texture_class]
        clay_pct = tex["clay"]
        sand_pct = tex["sand"]
        silt_pct = tex["silt"]
        om = HWSD_DEFAULTS["organic_matter"]
    elif args.soil_texture:
        parts = parse_soil_texture(args.soil_texture)
        clay_pct = parts.get("clay", 20.0)
        sand_pct = parts.get("sand", 40.0)
        silt_pct = parts.get("silt", 40.0)
        om = HWSD_DEFAULTS["organic_matter"]
    else:
        # Default loam
        clay_pct, sand_pct, silt_pct = 20.0, 40.0, 40.0
        om = HWSD_DEFAULTS["organic_matter"]

    # Compute hydraulic properties
    hydraulic_props = compute_hydraulic_properties(clay_pct, sand_pct, om)

    # Generate soil profile
    soil_profile = generate_soil_profile(clay_pct, sand_pct, silt_pct,
                                          args.soil_depth)

    # Parse PFT distribution
    if args.pft_distribution:
        pft_dist = parse_pft_distribution(args.pft_distribution)
    else:
        pft_dist = DEFAULT_PFT_FRACTIONS

    # Generate surface dataset
    dataset = generate_surface_dataset(
        args.lat, args.lon, soil_profile, pft_dist,
        hydraulic_props, args.output)

    # Stage 3: Validate outputs
    warnings = validate_outputs(dataset)

    # Print summary
    summary = {
        "status": "success",
        "location": {"lat": args.lat, "lon": args.lon},
        "soil": {
            "clay_pct": clay_pct,
            "sand_pct": sand_pct,
            "silt_pct": silt_pct,
            "depth_m": args.soil_depth,
        },
        "hydraulic": hydraulic_props,
        "n_active_pfts": len(pft_dist),
        "output_file": args.output,
        "warnings": warnings,
    }
    print(json.dumps(summary, indent=2))

    if warnings:
        print("\n--- Output Validation Warnings ---", file=sys.stderr)
        for w in warnings:
            print(f"  WARNING: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
