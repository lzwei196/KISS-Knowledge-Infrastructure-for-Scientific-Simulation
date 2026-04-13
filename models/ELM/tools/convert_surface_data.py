#!/usr/bin/env python3
"""
convert_surface_data.py — Generate ELM surface dataset from soil/vegetation data.

Creates a surface dataset NetCDF file (surfdata_*.nc) containing:
  - Plant functional type (PFT) fractions
  - Soil texture (sand, silt, clay percentages per layer)
  - Soil organic matter content
  - Monthly LAI/SAI climatology
  - Topographic parameters (elevation, slope)
  - Land/water/glacier/urban fractions

Input sources supported:
  - HWSD (Harmonized World Soil Database) for soil texture
  - MODIS land cover for PFT fractions
  - Generic CSV/JSON with soil and vegetation parameters
  - ELM-native surfdata files (for subsetting/modification)

CRITICAL: Soil texture fractions (sand + silt + clay) MUST sum to 100% per layer.
          Violation causes invalid hydraulic parameters (dt_007).
CRITICAL: PFT fractions MUST sum to 100% per grid cell (dt_015).

Usage:
    python convert_surface_data.py --lat 40.0 --lon 117.0 \\
        --sand 45.0 --clay 20.0 --organic 25.0 \\
        --pft_type 1 --pft_frac 100.0 \\
        --output surfdata_point.nc

    python convert_surface_data.py --from_hwsd hwsd.csv \\
        --lat 40.0 --lon 117.0 --output surfdata_point.nc
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

try:
    import netCDF4 as nc4
    HAS_NETCDF = True
except ImportError:
    HAS_NETCDF = False

# ---------------------------------------------------------------------------
# ELM PFT definitions (from elm_varpar.F90)
# ---------------------------------------------------------------------------
PFT_NAMES = {
    0:  "not_vegetated",
    1:  "needleleaf_evergreen_temperate_tree",
    2:  "needleleaf_evergreen_boreal_tree",
    3:  "needleleaf_deciduous_boreal_tree",
    4:  "broadleaf_evergreen_tropical_tree",
    5:  "broadleaf_evergreen_temperate_tree",
    6:  "broadleaf_deciduous_tropical_tree",
    7:  "broadleaf_deciduous_temperate_tree",
    8:  "broadleaf_deciduous_boreal_tree",
    9:  "broadleaf_evergreen_shrub",
    10: "broadleaf_deciduous_temperate_shrub",
    11: "broadleaf_deciduous_boreal_shrub",
    12: "c3_arctic_grass",
    13: "c3_non_arctic_grass",
    14: "c4_grass",
}

# Default soil layer depths (m) — 20 layers
SOIL_LAYER_DEPTHS = np.array([
    0.007, 0.028, 0.062, 0.119, 0.212, 0.366, 0.620, 1.038,
    1.728, 2.865, 4.739, 5.906, 6.927, 7.829, 8.001, 8.001,
    8.001, 8.001, 8.001, 8.001
])
NLEVSOI = 20

# USDA texture triangle classes → sand/clay percentages
USDA_TEXTURE_CLASSES = {
    "sand":       (92, 5),
    "loamy_sand": (82, 8),
    "sandy_loam": (65, 10),
    "loam":       (40, 20),
    "silt_loam":  (20, 15),
    "silt":       (8,  5),
    "sandy_clay_loam": (58, 28),
    "clay_loam":  (32, 35),
    "silty_clay_loam": (10, 35),
    "sandy_clay": (52, 42),
    "silty_clay": (8,  48),
    "clay":       (20, 60),
}

# Typical LAI values by PFT (12 monthly values)
DEFAULT_LAI = {
    0:  [0.0]*12,
    1:  [4.5, 4.5, 4.5, 5.0, 5.5, 6.0, 6.0, 5.5, 5.0, 4.5, 4.5, 4.5],
    2:  [2.0, 2.0, 2.0, 2.5, 3.0, 3.5, 3.5, 3.0, 2.5, 2.0, 2.0, 2.0],
    3:  [0.0, 0.0, 0.0, 1.0, 2.0, 3.0, 3.0, 2.0, 1.0, 0.0, 0.0, 0.0],
    4:  [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
    5:  [3.0, 3.0, 3.5, 4.0, 4.5, 5.0, 5.0, 4.5, 4.0, 3.5, 3.0, 3.0],
    6:  [1.0, 1.0, 2.0, 3.5, 5.0, 5.5, 5.5, 5.0, 3.5, 2.0, 1.0, 1.0],
    7:  [0.0, 0.0, 0.5, 2.0, 4.0, 5.0, 5.0, 4.0, 2.0, 0.5, 0.0, 0.0],
    8:  [0.0, 0.0, 0.0, 1.0, 2.5, 3.5, 3.5, 2.5, 1.0, 0.0, 0.0, 0.0],
    9:  [1.5, 1.5, 1.5, 2.0, 2.5, 3.0, 3.0, 2.5, 2.0, 1.5, 1.5, 1.5],
    10: [0.0, 0.0, 0.5, 1.5, 2.0, 2.5, 2.5, 2.0, 1.5, 0.5, 0.0, 0.0],
    11: [0.0, 0.0, 0.0, 0.5, 1.5, 2.0, 2.0, 1.5, 0.5, 0.0, 0.0, 0.0],
    12: [0.0, 0.0, 0.0, 0.5, 1.0, 1.5, 1.5, 1.0, 0.5, 0.0, 0.0, 0.0],
    13: [0.5, 0.5, 1.0, 1.5, 2.0, 2.5, 2.5, 2.0, 1.5, 1.0, 0.5, 0.5],
    14: [0.5, 0.5, 1.0, 2.0, 3.0, 3.5, 3.5, 3.0, 2.0, 1.0, 0.5, 0.5],
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []

    if args.lat is None or not (-90 <= args.lat <= 90):
        errors.append(f"Latitude required and must be in [-90, 90]: {args.lat}")
    if args.lon is None or not (-360 <= args.lon <= 360):
        errors.append(f"Longitude required and must be in [-360, 360]: {args.lon}")

    if args.from_hwsd is None:
        # Manual soil specification
        if args.sand is not None and args.clay is not None:
            silt = 100.0 - args.sand - args.clay
            if silt < 0:
                errors.append(
                    f"sand ({args.sand}%) + clay ({args.clay}%) = "
                    f"{args.sand + args.clay}% > 100%. "
                    f"Soil texture fractions must sum to 100% (dt_007)"
                )
        if args.pft_type is not None and not (0 <= args.pft_type <= 14):
            errors.append(f"PFT type must be 0-14, got {args.pft_type}")
    else:
        if not os.path.exists(args.from_hwsd):
            errors.append(f"HWSD file not found: {args.from_hwsd}")

    if errors:
        result = {"status": "error", "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)


def validate_outputs(surfdata, warnings):
    """Validate generated surface dataset."""
    # Check soil texture sums
    sand = surfdata["PCT_SAND"]
    clay = surfdata["PCT_CLAY"]
    total = sand + clay
    if np.any(total > 100.01):
        warnings.append(
            f"FATAL: Sand + clay > 100% in some layers (max={np.max(total):.1f}%). "
            f"This will crash ELM with invalid hydraulic parameters (dt_007)"
        )

    # Check PFT fraction sum
    pft_sum = np.sum(surfdata["PCT_PFT"])
    if abs(pft_sum - 100.0) > 0.1:
        warnings.append(
            f"PFT fractions sum to {pft_sum:.1f}%, expected 100%. "
            f"This causes missing or double-counted area (dt_015)"
        )

    # Check LAI range
    lai_max = np.max(surfdata["MONTHLY_LAI"])
    if lai_max > 12.0:
        warnings.append(
            f"Maximum LAI = {lai_max:.1f} m²/m², which is unrealistically high (dt_006)"
        )

    # Check organic matter
    org_max = np.max(surfdata["ORGANIC"])
    if org_max > 200.0:
        warnings.append(
            f"Organic matter = {org_max:.1f} kg/m³, might be in wrong units (dt_011). "
            f"Expected range: 0-130 kg/m³"
        )

    return warnings


# ---------------------------------------------------------------------------
# HWSD parsing
# ---------------------------------------------------------------------------
def parse_hwsd_csv(filepath, lat, lon):
    """Parse HWSD CSV data to extract soil properties for a point.

    Returns dict with sand, clay, organic percentages.
    """
    import pandas as pd
    df = pd.read_csv(filepath)

    # Find nearest point
    if "lat" in df.columns and "lon" in df.columns:
        dist = np.sqrt((df["lat"] - lat)**2 + (df["lon"] - lon)**2)
        idx = dist.idxmin()
        row = df.iloc[idx]

        sand = row.get("T_SAND", row.get("sand", 50.0))
        clay = row.get("T_CLAY", row.get("clay", 20.0))
        organic = row.get("T_OC", row.get("organic", 1.0))

        return {
            "sand": float(sand),
            "clay": float(clay),
            "organic": float(organic),
            "distance_km": float(dist.iloc[idx]) * 111.0,  # Rough degree-to-km
        }
    else:
        # Single record
        row = df.iloc[0]
        return {
            "sand": float(row.get("sand", 50.0)),
            "clay": float(row.get("clay", 20.0)),
            "organic": float(row.get("organic", 1.0)),
            "distance_km": 0.0,
        }


def texture_class_to_fractions(texture_class):
    """Convert USDA texture class name to sand/clay percentages."""
    key = texture_class.lower().replace(" ", "_")
    if key in USDA_TEXTURE_CLASSES:
        sand, clay = USDA_TEXTURE_CLASSES[key]
        return sand, clay
    else:
        raise ValueError(f"Unknown texture class: {texture_class}. "
                         f"Valid: {list(USDA_TEXTURE_CLASSES.keys())}")


# ---------------------------------------------------------------------------
# Surface dataset creation
# ---------------------------------------------------------------------------
def build_surfdata(sand, clay, organic, pft_type, pft_frac, lat, lon):
    """Build surface data dictionary for a single point.

    Args:
        sand: Sand fraction (%)
        clay: Clay fraction (%)
        organic: Organic matter (kg/m³)
        pft_type: PFT index (0-14)
        pft_frac: PFT fraction (%, should be 100 for single-PFT)
        lat: Latitude
        lon: Longitude

    Returns:
        dict with all surface dataset arrays
    """
    silt = 100.0 - sand - clay

    surfdata = {}

    # Soil texture (uniform with depth by default)
    surfdata["PCT_SAND"] = np.full(NLEVSOI, sand, dtype=np.float64)
    surfdata["PCT_CLAY"] = np.full(NLEVSOI, clay, dtype=np.float64)

    # Organic matter decreases exponentially with depth
    org_profile = organic * np.exp(-SOIL_LAYER_DEPTHS / 0.5)
    surfdata["ORGANIC"] = org_profile

    # PFT fractions
    pft_fracs = np.zeros(15, dtype=np.float64)
    if pft_type is not None:
        bare_frac = max(0.0, 100.0 - pft_frac)
        pft_fracs[0] = bare_frac
        pft_fracs[pft_type] = pft_frac
    else:
        pft_fracs[0] = 100.0  # All bare ground
    surfdata["PCT_PFT"] = pft_fracs

    # Monthly LAI
    lai_monthly = np.zeros((12, 15), dtype=np.float64)
    for pft_id, lai_vals in DEFAULT_LAI.items():
        lai_monthly[:, pft_id] = lai_vals
    surfdata["MONTHLY_LAI"] = lai_monthly

    # Monthly SAI (stem area index, ~10% of LAI)
    surfdata["MONTHLY_SAI"] = lai_monthly * 0.1

    # Land fraction
    surfdata["LANDFRAC_PFT"] = 1.0

    # Topography
    surfdata["TOPO"] = 0.0  # Will be overridden if DEM provided
    surfdata["SLOPE"] = 0.0
    surfdata["STD_ELEV"] = 0.0

    # Other fractions
    surfdata["PCT_LAKE"] = 0.0
    surfdata["PCT_WETLAND"] = 0.0
    surfdata["PCT_URBAN"] = 0.0
    surfdata["PCT_GLACIER"] = 0.0

    # Coordinates
    surfdata["lat"] = lat
    surfdata["lon"] = lon if lon >= 0 else lon + 360.0

    return surfdata


def write_surfdata_netcdf(output_path, surfdata):
    """Write surface dataset in ELM-compatible NetCDF format."""
    if not HAS_NETCDF:
        raise ImportError("netCDF4 required for NetCDF output. pip install netCDF4")

    ds = nc4.Dataset(output_path, "w", format="NETCDF4")

    # Dimensions
    ds.createDimension("lsmlat", 1)
    ds.createDimension("lsmlon", 1)
    ds.createDimension("nlevsoi", NLEVSOI)
    ds.createDimension("natpft", 15)
    ds.createDimension("time", 12)

    # Coordinates
    lat_var = ds.createVariable("LATIXY", "f8", ("lsmlat", "lsmlon"))
    lat_var.units = "degrees_north"
    lat_var[:] = surfdata["lat"]

    lon_var = ds.createVariable("LONGXY", "f8", ("lsmlat", "lsmlon"))
    lon_var.units = "degrees_east"
    lon_var[:] = surfdata["lon"]

    # Soil texture
    sand_var = ds.createVariable("PCT_SAND", "f8",
                                 ("nlevsoi", "lsmlat", "lsmlon"))
    sand_var.units = "percent"
    sand_var.long_name = "percent sand"
    sand_var[:, 0, 0] = surfdata["PCT_SAND"]

    clay_var = ds.createVariable("PCT_CLAY", "f8",
                                 ("nlevsoi", "lsmlat", "lsmlon"))
    clay_var.units = "percent"
    clay_var.long_name = "percent clay"
    clay_var[:, 0, 0] = surfdata["PCT_CLAY"]

    org_var = ds.createVariable("ORGANIC", "f8",
                                ("nlevsoi", "lsmlat", "lsmlon"))
    org_var.units = "kg/m3"
    org_var.long_name = "organic matter density"
    org_var[:, 0, 0] = surfdata["ORGANIC"]

    # PFT fractions
    pft_var = ds.createVariable("PCT_NAT_PFT", "f8",
                                ("natpft", "lsmlat", "lsmlon"))
    pft_var.units = "percent"
    pft_var.long_name = "percent plant functional type"
    pft_var[:, 0, 0] = surfdata["PCT_PFT"]

    # Monthly LAI
    lai_var = ds.createVariable("MONTHLY_LAI", "f8",
                                ("time", "natpft", "lsmlat", "lsmlon"))
    lai_var.units = "m2/m2"
    lai_var.long_name = "monthly leaf area index"
    lai_var[:, :, 0, 0] = surfdata["MONTHLY_LAI"]

    sai_var = ds.createVariable("MONTHLY_SAI", "f8",
                                ("time", "natpft", "lsmlat", "lsmlon"))
    sai_var.units = "m2/m2"
    sai_var.long_name = "monthly stem area index"
    sai_var[:, :, 0, 0] = surfdata["MONTHLY_SAI"]

    # Land use fractions
    for fname in ["LANDFRAC_PFT", "PCT_LAKE", "PCT_WETLAND",
                  "PCT_URBAN", "PCT_GLACIER"]:
        v = ds.createVariable(fname, "f8", ("lsmlat", "lsmlon"))
        v[:] = surfdata[fname]

    # Topography
    for fname in ["TOPO", "SLOPE", "STD_ELEV"]:
        v = ds.createVariable(fname, "f8", ("lsmlat", "lsmlon"))
        v[:] = surfdata[fname]

    # Global attributes
    ds.title = "ELM surface dataset (single point)"
    ds.conventions = "CF-1.6"
    ds.history = f"Created {datetime.now().isoformat()} by convert_surface_data.py"

    ds.close()


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process(args):
    """Main processing: read inputs → build surfdata → validate → write."""
    warnings = []

    # Get soil properties
    if args.from_hwsd:
        hwsd = parse_hwsd_csv(args.from_hwsd, args.lat, args.lon)
        sand = hwsd["sand"]
        clay = hwsd["clay"]
        organic = hwsd["organic"] * 10.0  # Convert from % to approximate kg/m³
        if hwsd["distance_km"] > 50:
            warnings.append(
                f"Nearest HWSD point is {hwsd['distance_km']:.0f} km away. "
                f"Soil properties may not be representative."
            )
    elif args.texture_class:
        sand, clay = texture_class_to_fractions(args.texture_class)
        organic = args.organic if args.organic is not None else 25.0
    else:
        sand = args.sand if args.sand is not None else 50.0
        clay = args.clay if args.clay is not None else 20.0
        organic = args.organic if args.organic is not None else 25.0

    pft_type = args.pft_type if args.pft_type is not None else 13  # C3 grass default
    pft_frac = args.pft_frac if args.pft_frac is not None else 100.0

    # Build surface data
    surfdata = build_surfdata(sand, clay, organic, pft_type, pft_frac,
                              args.lat, args.lon)

    # Validate
    warnings = validate_outputs(surfdata, warnings)

    # Write
    if args.output.endswith(".nc"):
        write_surfdata_netcdf(args.output, surfdata)
    else:
        # JSON fallback for inspection
        json_data = {}
        for k, v in surfdata.items():
            if isinstance(v, np.ndarray):
                json_data[k] = v.tolist()
            else:
                json_data[k] = v
        with open(args.output, "w") as f:
            json.dump(json_data, f, indent=2)

    result = {
        "status": "success",
        "output_file": args.output,
        "soil": {
            "sand_pct": float(sand),
            "clay_pct": float(clay),
            "silt_pct": float(100.0 - sand - clay),
            "organic_kg_m3": float(organic),
        },
        "vegetation": {
            "pft_type": pft_type,
            "pft_name": PFT_NAMES.get(pft_type, "unknown"),
            "pft_fraction_pct": float(pft_frac),
        },
        "location": {
            "lat": args.lat,
            "lon": args.lon,
        },
        "warnings": warnings,
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Generate ELM surface dataset from soil/vegetation data"
    )
    parser.add_argument("--lat", type=float, required=True,
                        help="Latitude (degrees)")
    parser.add_argument("--lon", type=float, required=True,
                        help="Longitude (degrees)")
    parser.add_argument("--output", required=True,
                        help="Output file path (.nc or .json)")

    # Soil options
    soil_group = parser.add_argument_group("Soil properties")
    soil_group.add_argument("--sand", type=float,
                            help="Sand fraction (%%)")
    soil_group.add_argument("--clay", type=float,
                            help="Clay fraction (%%)")
    soil_group.add_argument("--organic", type=float,
                            help="Organic matter density (kg/m³)")
    soil_group.add_argument("--texture_class",
                            help="USDA texture class (e.g., 'loam', 'sandy_clay')")
    soil_group.add_argument("--from_hwsd",
                            help="Path to HWSD CSV file")

    # Vegetation options
    veg_group = parser.add_argument_group("Vegetation properties")
    veg_group.add_argument("--pft_type", type=int,
                           help="PFT index (0-14)")
    veg_group.add_argument("--pft_frac", type=float, default=100.0,
                           help="PFT fraction (%%, default 100)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    print(json.dumps(result, indent=2))

    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
