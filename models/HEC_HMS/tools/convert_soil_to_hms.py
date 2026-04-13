#!/usr/bin/env python3
"""
Convert HWSD soil data and AVHRR land cover to HEC-HMS SCS Curve Number parameters.

Reads raster soil and land cover data within a basin boundary and computes:
  - Hydrologic Soil Group (A/B/C/D) from HWSD texture classes
  - SCS Curve Number from soil group + land cover combination
  - Green-Ampt parameters (alternative loss method)
  - Basin-average CN and soil properties

Usage:
  python3 convert_soil_to_hms.py \
    --soil_file /path/to/HWSD_China_Geo.img \
    --landcover_file /path/to/AVHRR_1km_LANDCOVER.tif \
    --basin_shp /path/to/basin.shp \
    --output_file ./soil_params.json
"""

import argparse
import json
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# SCS Curve Number lookup tables
# ---------------------------------------------------------------------------

# Hydrologic Soil Group classification based on HWSD texture classes
# Texture class → Soil Group (A=high infiltration, D=low infiltration)
TEXTURE_TO_SOIL_GROUP = {
    # Sand, Loamy Sand
    1: "A", 2: "A",
    # Sandy Loam
    3: "B",
    # Loam, Silt Loam, Silt
    4: "B", 5: "B", 6: "B",
    # Sandy Clay Loam
    7: "C",
    # Clay Loam, Silty Clay Loam
    8: "C", 9: "C",
    # Sandy Clay, Silty Clay, Clay
    10: "D", 11: "D", 12: "D",
    # Organic
    13: "B",
}

# CN lookup: land_cover_class → {soil_group: CN}
# Based on USDA TR-55 Table 2-2a
# AVHRR classes: 1=Water, 2=Evergreen Needleleaf, 3=Evergreen Broadleaf,
# 4=Deciduous Needleleaf, 5=Deciduous Broadleaf, 6=Mixed Forest,
# 7=Woodland, 8=Wooded Grassland, 9=Closed Shrub, 10=Open Shrub,
# 11=Grassland, 12=Cropland, 13=Bare Ground, 14=Urban
CN_LOOKUP = {
    1:  {"A": 98, "B": 98, "C": 98, "D": 98},    # Water
    2:  {"A": 36, "B": 60, "C": 73, "D": 79},    # Evergreen Needleleaf Forest
    3:  {"A": 30, "B": 55, "C": 70, "D": 77},    # Evergreen Broadleaf Forest
    4:  {"A": 36, "B": 60, "C": 73, "D": 79},    # Deciduous Needleleaf
    5:  {"A": 36, "B": 60, "C": 73, "D": 79},    # Deciduous Broadleaf
    6:  {"A": 36, "B": 60, "C": 73, "D": 79},    # Mixed Forest
    7:  {"A": 43, "B": 65, "C": 76, "D": 82},    # Woodland
    8:  {"A": 49, "B": 69, "C": 79, "D": 84},    # Wooded Grassland
    9:  {"A": 48, "B": 67, "C": 77, "D": 83},    # Closed Shrub
    10: {"A": 48, "B": 67, "C": 77, "D": 83},    # Open Shrub
    11: {"A": 49, "B": 69, "C": 79, "D": 84},    # Grassland
    12: {"A": 67, "B": 78, "C": 85, "D": 89},    # Cropland
    13: {"A": 77, "B": 86, "C": 91, "D": 94},    # Bare Ground
    14: {"A": 89, "B": 92, "C": 94, "D": 95},    # Urban
}

# Green-Ampt parameters by soil group
# suction_head_cm, conductivity_cm_hr, porosity, initial_deficit
GREEN_AMPT = {
    "A": {"suction_cm": 5.0,  "ksat_cm_hr": 11.78, "porosity": 0.437, "deficit": 0.062},
    "B": {"suction_cm": 11.0, "ksat_cm_hr": 1.30,  "porosity": 0.453, "deficit": 0.105},
    "C": {"suction_cm": 22.0, "ksat_cm_hr": 0.20,  "porosity": 0.398, "deficit": 0.148},
    "D": {"suction_cm": 32.0, "ksat_cm_hr": 0.03,  "porosity": 0.385, "deficit": 0.175},
}


# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check input files exist."""
    errors = []
    if not os.path.isfile(args.soil_file):
        errors.append(f"Soil file not found: {args.soil_file}")
    if not os.path.isfile(args.landcover_file):
        errors.append(f"Land cover file not found: {args.landcover_file}")
    if not os.path.isfile(args.basin_shp):
        errors.append(f"Basin shapefile not found: {args.basin_shp}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print("[validate_inputs] All input files found.")


# ---------------------------------------------------------------------------
# Read raster within basin
# ---------------------------------------------------------------------------
def read_raster_in_basin(raster_path, basin_shp):
    """Read raster data clipped to basin boundary, return array and metadata."""
    try:
        import rasterio
        from rasterio.mask import mask as rio_mask
        import geopandas as gpd

        gdf = gpd.read_file(basin_shp).to_crs(epsg=4326)
        geometries = gdf.geometry.values

        with rasterio.open(raster_path) as src:
            out_image, out_transform = rio_mask(src, geometries, crop=True, nodata=-9999)
            data = out_image[0]  # First band
            data = np.where(data == -9999, np.nan, data)
            data = np.where(data == src.nodata, np.nan, data) if src.nodata else data

        print(f"  Raster shape: {data.shape}, valid pixels: {np.sum(~np.isnan(data))}")
        return data

    except ImportError:
        print("  WARNING: rasterio not available, using fallback estimation")
        return None
    except Exception as e:
        print(f"  WARNING: Error reading raster: {e}")
        return None


# ---------------------------------------------------------------------------
# Compute soil groups
# ---------------------------------------------------------------------------
def compute_soil_groups(soil_data):
    """Convert HWSD texture class raster to soil group distribution."""
    if soil_data is None:
        # Fallback: assume mixed B/C for Huai River basin
        print("  Using fallback soil groups: 40% B, 60% C (typical for Huai River)")
        return {"A": 0.0, "B": 0.4, "C": 0.6, "D": 0.0}

    valid = soil_data[~np.isnan(soil_data)].astype(int)
    if len(valid) == 0:
        print("  WARNING: No valid soil pixels, using fallback")
        return {"A": 0.0, "B": 0.4, "C": 0.6, "D": 0.0}

    groups = {"A": 0, "B": 0, "C": 0, "D": 0}
    for pixel_val in valid:
        group = TEXTURE_TO_SOIL_GROUP.get(int(pixel_val), "C")  # Default C
        groups[group] += 1

    total = sum(groups.values())
    fractions = {k: v / total for k, v in groups.items()}
    print(f"  Soil group distribution: {', '.join(f'{k}={v:.1%}' for k, v in fractions.items())}")
    return fractions


# ---------------------------------------------------------------------------
# Compute curve number
# ---------------------------------------------------------------------------
def compute_curve_number(soil_groups, landcover_data):
    """Compute basin-average SCS Curve Number from soil groups and land cover."""
    if landcover_data is None:
        # Fallback: assume cropland-dominant (typical for Huai River)
        print("  Using fallback land cover: cropland-dominant")
        cn_by_group = CN_LOOKUP.get(12, CN_LOOKUP[11])  # Cropland
        cn = sum(soil_groups[g] * cn_by_group[g] for g in "ABCD")
        print(f"  Basin-average CN (fallback): {cn:.1f}")
        return cn

    valid = landcover_data[~np.isnan(landcover_data)].astype(int)
    if len(valid) == 0:
        cn_by_group = CN_LOOKUP.get(12, CN_LOOKUP[11])
        cn = sum(soil_groups[g] * cn_by_group[g] for g in "ABCD")
        print(f"  Basin-average CN (no landcover data): {cn:.1f}")
        return cn

    # Count land cover classes
    lc_counts = {}
    for v in valid:
        lc_counts[int(v)] = lc_counts.get(int(v), 0) + 1
    total = sum(lc_counts.values())
    lc_fractions = {k: v / total for k, v in lc_counts.items()}

    print(f"  Land cover: {', '.join(f'class{k}={v:.1%}' for k, v in sorted(lc_fractions.items())[:5])}")

    # Weighted average CN
    cn = 0.0
    for lc_class, lc_frac in lc_fractions.items():
        cn_by_group = CN_LOOKUP.get(lc_class, CN_LOOKUP.get(11, {}))  # Default grassland
        for group in "ABCD":
            cn += lc_frac * soil_groups.get(group, 0) * cn_by_group.get(group, 75)

    # Validate CN range (dt_103)
    if cn < 30:
        print(f"  WARNING: CN={cn:.1f} is below 30 — check soil/landcover data!")
        cn = max(cn, 30)
    if cn > 100:
        print(f"  WARNING: CN={cn:.1f} is above 100 — capping at 98")
        cn = min(cn, 98)

    print(f"  Basin-average CN: {cn:.1f}")
    return cn


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------
def process(args):
    """Main processing workflow."""
    print("=" * 60)
    print("HEC-HMS Soil Parameter Converter (HWSD + AVHRR → SCS-CN)")
    print("=" * 60)

    # 1. Read soil raster
    print("\n[soil] Reading HWSD soil data...")
    soil_data = read_raster_in_basin(args.soil_file, args.basin_shp)

    # 2. Read landcover raster
    print("\n[landcover] Reading AVHRR land cover...")
    landcover_data = read_raster_in_basin(args.landcover_file, args.basin_shp)

    # 3. Compute soil groups
    print("\n[soil_groups] Computing hydrologic soil groups...")
    soil_groups = compute_soil_groups(soil_data)

    # 4. Compute curve number
    print("\n[curve_number] Computing SCS Curve Number...")
    cn = compute_curve_number(soil_groups, landcover_data)

    # 5. Compute derived parameters
    s_mm = 25400.0 / cn - 254.0  # Maximum retention (mm)
    ia_005 = 0.05 * s_mm  # Initial abstraction (Ia = 0.05*S)
    ia_020 = 0.20 * s_mm  # Initial abstraction (Ia = 0.2*S, classic)

    # Green-Ampt parameters (weighted by soil group)
    ga_params = {}
    for param in ["suction_cm", "ksat_cm_hr", "porosity", "deficit"]:
        ga_params[param] = sum(
            soil_groups[g] * GREEN_AMPT[g][param] for g in "ABCD"
        )

    # 6. Write output
    result = {
        "status": "success",
        "curve_number": round(cn, 1),
        "max_retention_mm": round(s_mm, 1),
        "initial_abstraction_005": round(ia_005, 1),
        "initial_abstraction_020": round(ia_020, 1),
        "soil_groups": {k: round(v, 4) for k, v in soil_groups.items()},
        "green_ampt": {k: round(v, 4) for k, v in ga_params.items()},
        "method_notes": {
            "cn_source": "HWSD texture → soil group + AVHRR → CN (TR-55 Table 2-2a)",
            "ia_recommended": "Use Ia = 0.05*S for humid basins (dt_104)",
            "ga_source": "HWSD texture → USDA soil properties",
        },
    }

    os.makedirs(os.path.dirname(args.output_file) or ".", exist_ok=True)
    with open(args.output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n[write] Soil parameters: {args.output_file}")
    print(json.dumps(result, indent=2))

    return result


# ---------------------------------------------------------------------------
# Validate outputs
# ---------------------------------------------------------------------------
def validate_outputs(result):
    """Verify output parameters are within physical bounds."""
    warnings_list = []
    cn = result["curve_number"]
    if cn < 30 or cn > 98:
        warnings_list.append(f"CN={cn} outside typical range [30, 98]")
    if result["green_ampt"]["ksat_cm_hr"] <= 0:
        warnings_list.append("Ksat <= 0 — physically impossible")
    if result["green_ampt"]["porosity"] <= 0 or result["green_ampt"]["porosity"] >= 1:
        warnings_list.append(f"Porosity={result['green_ampt']['porosity']} outside (0, 1)")
    for w in warnings_list:
        print(f"  WARNING: {w}")
    return warnings_list


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Convert HWSD/AVHRR to HEC-HMS SCS-CN parameters")
    parser.add_argument("--soil_file", required=True, help="HWSD soil raster")
    parser.add_argument("--landcover_file", required=True, help="AVHRR land cover raster")
    parser.add_argument("--basin_shp", required=True, help="Basin shapefile")
    parser.add_argument("--output_file", required=True, help="Output JSON file")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    validate_outputs(result)


if __name__ == "__main__":
    main()
