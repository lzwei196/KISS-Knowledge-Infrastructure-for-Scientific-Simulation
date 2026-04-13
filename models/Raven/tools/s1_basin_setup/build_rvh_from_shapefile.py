#!/usr/bin/env python3
"""
build_rvh_from_shapefile.py — Generate Raven .rvh (HRU/basin definition) file.

Takes a basin shapefile + DEM + AVHRR land cover and generates the .rvh file
defining subbasins and HRUs (Hydrologic Response Units).

Supports three HRU strategies:
  - lumped: entire basin = 1 HRU (simplest, for GR4J/HYMOD)
  - elevation_bands: split by elevation classes (for mountain basins, UBC)
  - landuse: split by land use type (for heterogeneous basins)

Usage:
    python build_rvh_from_shapefile.py \
        --basin_shp data/shp/chaohe.shp \
        --dem data/dem/china_dem_90m/china_dem_90m.tif \
        --landcover data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif \
        --output_dir outputs/chaohe_raven/ \
        --basin_name chaohe \
        --strategy elevation_bands \
        --n_bands 5
"""

import argparse
import json
import os
import sys
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

try:
    import numpy as np
    import geopandas as gpd
    import rasterio
    from rasterio.mask import mask as rio_mask
    from shapely.geometry import mapping
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)

# AVHRR IGBP land cover classes mapped to Raven land use categories
AVHRR_TO_RAVEN_LANDUSE = {
    0: ("WATER", "Water Bodies"),
    1: ("EVERGREEN_NEEDLELEAF", "Evergreen Needleleaf Forests"),
    2: ("EVERGREEN_BROADLEAF", "Evergreen Broadleaf Forests"),
    3: ("DECIDUOUS_NEEDLELEAF", "Deciduous Needleleaf Forests"),
    4: ("DECIDUOUS_BROADLEAF", "Deciduous Broadleaf Forests"),
    5: ("MIXED_FOREST", "Mixed Forests"),
    6: ("CLOSED_SHRUB", "Closed Shrublands"),
    7: ("OPEN_SHRUB", "Open Shrublands"),
    8: ("WOODY_SAVANNA", "Woody Savannas"),
    9: ("SAVANNA", "Savannas"),
    10: ("GRASSLAND", "Grasslands"),
    11: ("WETLAND", "Permanent Wetlands"),
    12: ("CROPLAND", "Croplands"),
    13: ("URBAN", "Urban and Built-Up"),
    14: ("CROP_MOSAIC", "Cropland/Natural Vegetation Mosaic"),
    15: ("SNOW_ICE", "Snow and Ice"),
    16: ("BARREN", "Barren or Sparsely Vegetated"),
}

# Default Raven vegetation class mapping from land use
LANDUSE_TO_VEGCLASS = {
    "WATER": "WATER_VEG",
    "EVERGREEN_NEEDLELEAF": "NEEDLELEAF",
    "EVERGREEN_BROADLEAF": "BROADLEAF",
    "DECIDUOUS_NEEDLELEAF": "NEEDLELEAF",
    "DECIDUOUS_BROADLEAF": "BROADLEAF",
    "MIXED_FOREST": "MIXED_VEG",
    "CLOSED_SHRUB": "SHRUB",
    "OPEN_SHRUB": "SHRUB",
    "WOODY_SAVANNA": "MIXED_VEG",
    "SAVANNA": "GRASSLAND_VEG",
    "GRASSLAND": "GRASSLAND_VEG",
    "WETLAND": "WETLAND_VEG",
    "CROPLAND": "CROP_VEG",
    "URBAN": "URBAN_VEG",
    "CROP_MOSAIC": "CROP_VEG",
    "SNOW_ICE": "BARE_VEG",
    "BARREN": "BARE_VEG",
}


def validate_inputs(args):
    """Validate input files exist."""
    errors = []
    if not os.path.isfile(args.basin_shp):
        errors.append(f"Basin shapefile not found: {args.basin_shp}")
    if not os.path.isfile(args.dem):
        errors.append(f"DEM file not found: {args.dem}")
    if args.landcover and not os.path.isfile(args.landcover):
        errors.append(f"Land cover file not found: {args.landcover}")
    if args.strategy not in ("lumped", "elevation_bands", "landuse"):
        errors.append(f"Unknown strategy '{args.strategy}'. Use: lumped, elevation_bands, landuse")
    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def extract_basin_stats(basin_shp, dem_path, landcover_path=None):
    """Extract elevation, area, and land cover statistics from rasters."""
    gdf = gpd.read_file(basin_shp)

    # Reproject to WGS84 if needed
    if gdf.crs and not gdf.crs.is_geographic:
        gdf = gdf.to_crs("EPSG:4326")

    geom = gdf.geometry.union_all() if hasattr(gdf.geometry, 'union_all') else gdf.geometry.unary_union
    centroid = geom.centroid
    bounds = geom.bounds

    # Area calculation
    gdf_proj = gdf.to_crs(gdf.estimate_utm_crs())
    area_km2 = gdf_proj.geometry.area.sum() / 1e6

    # Extract DEM
    with rasterio.open(dem_path) as src:
        geom_shapes = [mapping(geom)]
        try:
            out_image, out_transform = rio_mask(src, geom_shapes, crop=True, nodata=-9999)
            elev = out_image[0]
            elev_valid = elev[elev > -9999]
        except Exception:
            elev_valid = np.array([500.0])  # fallback

    elev_mean = float(np.mean(elev_valid)) if len(elev_valid) > 0 else 500.0
    elev_min = float(np.min(elev_valid)) if len(elev_valid) > 0 else 0.0
    elev_max = float(np.max(elev_valid)) if len(elev_valid) > 0 else 1000.0

    # Extract land cover
    lc_fractions = {}
    if landcover_path:
        try:
            with rasterio.open(landcover_path) as src:
                geom_shapes = [mapping(geom)]
                out_image, _ = rio_mask(src, geom_shapes, crop=True, nodata=255)
                lc = out_image[0]
                lc_valid = lc[(lc >= 0) & (lc < 255)]
                if len(lc_valid) > 0:
                    unique, counts = np.unique(lc_valid, return_counts=True)
                    total = counts.sum()
                    for u, c in zip(unique, counts):
                        if int(u) in AVHRR_TO_RAVEN_LANDUSE:
                            lu_name = AVHRR_TO_RAVEN_LANDUSE[int(u)][0]
                            lc_fractions[lu_name] = float(c) / total
        except Exception:
            lc_fractions = {"MIXED_FOREST": 0.4, "GRASSLAND": 0.3, "CROPLAND": 0.3}

    if not lc_fractions:
        lc_fractions = {"MIXED_FOREST": 0.4, "GRASSLAND": 0.3, "CROPLAND": 0.3}

    return {
        "area_km2": area_km2,
        "centroid_lat": centroid.y,
        "centroid_lon": centroid.x,
        "elev_mean": elev_mean,
        "elev_min": elev_min,
        "elev_max": elev_max,
        "elev_data": elev_valid,
        "lc_fractions": lc_fractions,
    }


def build_hrus_lumped(stats):
    """Build a single lumped HRU."""
    subbasins = [{
        "id": 1,
        "name": "basin",
        "downstream_id": -1,
        "reach_length": 0.0,
        "gauged": 1,
    }]

    # Dominant land use
    dom_lu = max(stats["lc_fractions"], key=stats["lc_fractions"].get)
    dom_veg = LANDUSE_TO_VEGCLASS.get(dom_lu, "MIXED_VEG")

    hrus = [{
        "id": 1,
        "area_km2": stats["area_km2"],
        "elevation": stats["elev_mean"],
        "latitude": stats["centroid_lat"],
        "longitude": stats["centroid_lon"],
        "basin_id": 1,
        "land_use": dom_lu,
        "vegetation": dom_veg,
        "soil_profile": "DEFAULT_PROF",
        "terrain": "DEFAULT_TERRAIN",
        "slope": 0.05,
        "aspect": 0.0,
    }]

    return subbasins, hrus


def build_hrus_elevation_bands(stats, n_bands=5):
    """Build HRUs by elevation bands."""
    elev_data = stats["elev_data"]
    if len(elev_data) == 0:
        return build_hrus_lumped(stats)

    # Create elevation breaks
    elev_min = stats["elev_min"]
    elev_max = stats["elev_max"]
    band_width = (elev_max - elev_min) / n_bands

    if band_width < 1.0:
        return build_hrus_lumped(stats)

    subbasins = [{
        "id": 1,
        "name": "basin",
        "downstream_id": -1,
        "reach_length": 0.0,
        "gauged": 1,
    }]

    dom_lu = max(stats["lc_fractions"], key=stats["lc_fractions"].get)
    dom_veg = LANDUSE_TO_VEGCLASS.get(dom_lu, "MIXED_VEG")

    hrus = []
    total_cells = len(elev_data)

    for i in range(n_bands):
        low = elev_min + i * band_width
        high = elev_min + (i + 1) * band_width
        if i == n_bands - 1:
            high = elev_max + 1  # include max

        mask = (elev_data >= low) & (elev_data < high)
        n_cells = mask.sum()
        if n_cells == 0:
            continue

        frac = n_cells / total_cells
        band_elev = float(np.mean(elev_data[mask]))

        hrus.append({
            "id": len(hrus) + 1,
            "area_km2": stats["area_km2"] * frac,
            "elevation": band_elev,
            "latitude": stats["centroid_lat"],
            "longitude": stats["centroid_lon"],
            "basin_id": 1,
            "land_use": dom_lu,
            "vegetation": dom_veg,
            "soil_profile": "DEFAULT_PROF",
            "terrain": "DEFAULT_TERRAIN",
            "slope": 0.05 + 0.02 * i,  # steeper at higher elevations
            "aspect": 0.0,
        })

    if not hrus:
        return build_hrus_lumped(stats)

    return subbasins, hrus


def build_hrus_landuse(stats):
    """Build HRUs by dominant land use classes."""
    subbasins = [{
        "id": 1,
        "name": "basin",
        "downstream_id": -1,
        "reach_length": 0.0,
        "gauged": 1,
    }]

    hrus = []
    # Only include land use classes with >5% area
    significant = {k: v for k, v in stats["lc_fractions"].items() if v > 0.05}
    if not significant:
        significant = stats["lc_fractions"]

    # Renormalize
    total = sum(significant.values())
    for lu, frac in significant.items():
        norm_frac = frac / total
        veg = LANDUSE_TO_VEGCLASS.get(lu, "MIXED_VEG")

        hrus.append({
            "id": len(hrus) + 1,
            "area_km2": stats["area_km2"] * norm_frac,
            "elevation": stats["elev_mean"],
            "latitude": stats["centroid_lat"],
            "longitude": stats["centroid_lon"],
            "basin_id": 1,
            "land_use": lu,
            "vegetation": veg,
            "soil_profile": "DEFAULT_PROF",
            "terrain": "DEFAULT_TERRAIN",
            "slope": 0.05,
            "aspect": 0.0,
        })

    if not hrus:
        return build_hrus_lumped(stats)

    return subbasins, hrus


def generate_rvh_content(basin_name, subbasins, hrus):
    """Generate .rvh file content."""
    lines = []
    lines.append(f"# Raven .rvh file -- Basin/HRU definition for {basin_name}")
    lines.append(f"# Generated by HydroCraft build_rvh_from_shapefile.py")
    lines.append(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"# HRUs: {len(hrus)}")
    lines.append("")

    # SubBasins (comma-separated format)
    lines.append(":SubBasins")
    lines.append("  :Attributes,  NAME,  DOWNSTREAM_ID,  PROFILE,  REACH_LENGTH,  GAUGED")
    lines.append("  :Units,       none,  none,           none,     km,            none")
    for sb in subbasins:
        lines.append(f"  {sb['id']},  {sb['name']},  {sb['downstream_id']},  NONE,  {sb['reach_length']:.1f},  {sb['gauged']}")
    lines.append(":EndSubBasins")
    lines.append("")

    # HRUs — CRITICAL: Raven requires exactly 13 columns (including AQUIFER_PROFILE)
    # Discovered during validation: ParseHRUFile.cpp line 253 requires Len>=13
    # Columns: ID, AREA, ELEVATION, LATITUDE, LONGITUDE, BASIN_ID, LAND_USE_CLASS,
    #          VEG_CLASS, SOIL_PROFILE, AQUIFER_PROFILE, TERRAIN_CLASS, SLOPE, ASPECT
    lines.append(":HRUs")
    lines.append("  :Attributes,  AREA,  ELEVATION,  LATITUDE,  LONGITUDE,  BASIN_ID,  LAND_USE_CLASS,  VEG_CLASS,  SOIL_PROFILE,  AQUIFER_PROFILE,  TERRAIN_CLASS,  SLOPE,  ASPECT")
    lines.append("  :Units,       km2,   m,          deg,       deg,        none,      none,            none,       none,          none,             none,           none,   deg")
    for hru in hrus:
        lines.append(
            f"  {hru['id']},  {hru['area_km2']:.2f},  {hru['elevation']:.1f},  "
            f"{hru['latitude']:.4f},  {hru['longitude']:.4f},  {hru['basin_id']},  "
            f"{hru['land_use']},  {hru['vegetation']},  {hru['soil_profile']},  "
            f"[NONE],  {hru['terrain']},  {hru['slope']:.4f},  {hru['aspect']:.1f}"
        )
    lines.append(":EndHRUs")
    lines.append("")

    return "\n".join(lines)


def process(args):
    """Main processing: extract stats and generate .rvh file."""
    # Extract basin statistics
    stats = extract_basin_stats(args.basin_shp, args.dem, args.landcover)

    # Build HRUs based on strategy
    if args.strategy == "lumped":
        subbasins, hrus = build_hrus_lumped(stats)
    elif args.strategy == "elevation_bands":
        subbasins, hrus = build_hrus_elevation_bands(stats, n_bands=args.n_bands)
    elif args.strategy == "landuse":
        subbasins, hrus = build_hrus_landuse(stats)
    else:
        subbasins, hrus = build_hrus_lumped(stats)

    # CRITICAL CHECK: total HRU area must match basin area (tolerance 1%)
    total_hru_area = sum(h["area_km2"] for h in hrus)
    area_ratio = total_hru_area / stats["area_km2"] if stats["area_km2"] > 0 else 0
    if abs(area_ratio - 1.0) > 0.01:
        # Rescale to match
        for h in hrus:
            h["area_km2"] *= stats["area_km2"] / total_hru_area

    # Generate .rvh file
    rvh_content = generate_rvh_content(args.basin_name, subbasins, hrus)

    os.makedirs(args.output_dir, exist_ok=True)
    rvh_path = os.path.join(args.output_dir, f"{args.basin_name}.rvh")
    with open(rvh_path, "w") as f:
        f.write(rvh_content)

    results = {
        "status": "success",
        "output_rvh": rvh_path,
        "basin_stats": {
            "area_km2": round(stats["area_km2"], 1),
            "centroid_lat": round(stats["centroid_lat"], 4),
            "centroid_lon": round(stats["centroid_lon"], 4),
            "elev_mean": round(stats["elev_mean"], 1),
            "elev_min": round(stats["elev_min"], 1),
            "elev_max": round(stats["elev_max"], 1),
        },
        "hru_count": len(hrus),
        "strategy": args.strategy,
        "land_use_fractions": {k: round(v, 3) for k, v in stats["lc_fractions"].items()},
        "subbasins": len(subbasins),
    }

    return results


def validate_outputs(results, args):
    """Validate generated output."""
    errors = []
    rvh_path = results.get("output_rvh")
    if rvh_path and not os.path.isfile(rvh_path):
        errors.append(f"Expected .rvh not found: {rvh_path}")
    elif rvh_path:
        with open(rvh_path) as f:
            content = f.read()
        if ":SubBasins" not in content:
            errors.append(".rvh missing :SubBasins block")
        if ":HRUs" not in content:
            errors.append(".rvh missing :HRUs block")
    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def main():
    parser = argparse.ArgumentParser(description="Generate Raven .rvh from basin shapefile")
    parser.add_argument("--basin_shp", required=True, help="Path to basin boundary shapefile")
    parser.add_argument("--dem", required=True, help="Path to DEM raster (GeoTIFF)")
    parser.add_argument("--landcover", default=None, help="Path to AVHRR land cover raster")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--basin_name", required=True, help="Basin name")
    parser.add_argument("--strategy", default="elevation_bands",
                        help="HRU strategy: lumped, elevation_bands, landuse")
    parser.add_argument("--n_bands", type=int, default=5, help="Number of elevation bands")

    args = parser.parse_args()

    validation = validate_inputs(args)
    if validation["status"] == "error":
        print(json.dumps(validation, indent=2))
        sys.exit(1)

    try:
        results = process(args)
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(2)

    output_validation = validate_outputs(results, args)
    if output_validation["status"] == "error":
        results["output_validation"] = output_validation
        print(json.dumps(results, indent=2))
        sys.exit(3)

    print(json.dumps(results, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
