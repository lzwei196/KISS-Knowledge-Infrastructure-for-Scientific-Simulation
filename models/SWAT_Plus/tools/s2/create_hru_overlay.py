#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      create_hru_overlay
Stage:        s2_hru_definition
Description:  Overlay land use, soil, and slope rasters onto subbasins to create HRUs.
              Writes hru-data.hru and hru.con for SWAT+.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import logging
import json
from pathlib import Path

SUBBASIN_SHP = ""
LANDUSE_RASTER = ""
SOIL_RASTER = ""
DEM_PATH = ""
SLOPE_CLASSES = [0, 3, 8, 15, 9999]  # percent
OUTPUT_DIR = ""

if len(sys.argv) >= 6:
    SUBBASIN_SHP = sys.argv[1]
    LANDUSE_RASTER = sys.argv[2]
    SOIL_RASTER = sys.argv[3]
    DEM_PATH = sys.argv[4]
    OUTPUT_DIR = sys.argv[5]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    for path, name in [
        (SUBBASIN_SHP, "Subbasin shapefile"),
        (LANDUSE_RASTER, "Land use raster"),
        (SOIL_RASTER, "Soil raster"),
        (DEM_PATH, "DEM"),
    ]:
        if not path or not Path(path).exists():
            errors.append(f"{name} not found: {path}")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if len(SLOPE_CLASSES) < 2:
        errors.append("SLOPE_CLASSES must have at least 2 break points")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    """Overlay landuse/soil/slope onto subbasins to create HRUs."""
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    import numpy as np
    import rasterio
    from rasterio.mask import mask as rio_mask
    import geopandas as gpd

    subbasins = gpd.read_file(SUBBASIN_SHP)
    hru_records = []
    hru_id = 0

    for sub_idx, sub_row in subbasins.iterrows():
        sub_id = sub_idx + 1
        sub_geom = [sub_row.geometry]

        # Extract raster values within this subbasin — all resampled to DEM grid
        from rasterio.warp import reproject, Resampling as WarpResampling
        with rasterio.open(DEM_PATH) as dem_src:
            dem_data, dem_transform = rio_mask(dem_src, sub_geom, crop=True, nodata=-9999)
            dem_profile = dem_src.profile.copy()
            dem_profile.update(transform=dem_transform, height=dem_data.shape[1], width=dem_data.shape[2])
            dy, dx = np.gradient(dem_data[0].astype(float),
                                 abs(dem_src.transform[4]), abs(dem_src.transform[0]))
            slope_flat = (np.sqrt(dx**2 + dy**2) * 100).flatten()

        ref_h, ref_w = dem_data.shape[1], dem_data.shape[2]

        def resample_to_dem(raster_path, nodata_val):
            with rasterio.open(raster_path) as src:
                dst_arr = np.full((ref_h, ref_w), nodata_val, dtype=np.float32)
                reproject(
                    source=rasterio.band(src, 1),
                    destination=dst_arr,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=dem_transform,
                    dst_crs=dem_profile['crs'],
                    resampling=WarpResampling.nearest,
                    src_nodata=nodata_val if src.nodata is None else src.nodata,
                    dst_nodata=nodata_val,
                )
            return dst_arr.flatten()

        lu_flat = resample_to_dem(LANDUSE_RASTER, 0)
        soil_flat = resample_to_dem(SOIL_RASTER, 0)

        # Classify slopes
        slope_class = np.digitize(slope_flat, SLOPE_CLASSES[1:])

        # Find unique combinations
        valid = (lu_flat > 0) & (soil_flat > 0)
        for lu_val in np.unique(lu_flat[valid]):
            for soil_val in np.unique(soil_flat[valid]):
                for sc in range(len(SLOPE_CLASSES) - 1):
                    combo_mask = valid & (lu_flat == lu_val) & (soil_flat == soil_val) & (slope_class == sc)
                    area_frac = combo_mask.sum() / valid.sum() if valid.sum() > 0 else 0
                    if area_frac > 0:
                        hru_id += 1
                        hru_records.append({
                            "id": hru_id,
                            "subbasin": sub_id,
                            "landuse": int(lu_val),
                            "soil": int(soil_val),
                            "slope_class": sc,
                            "area_frac": float(area_frac),
                            "mean_slope": float(np.mean(slope_flat[combo_mask])) if combo_mask.any() else 0.0
                        })

    # Write hru-data.hru
    hru_data_path = output_dir / "hru-data.hru"
    with open(hru_data_path, 'w') as f:
        f.write("hru-data.hru: written by SWAT+ knowledge infrastructure\n")
        f.write("  id         name           topo       hyd        lu_mgt     soil       soil_plant fld        surf_stor  snow_init\n")
        for rec in hru_records:
            name = f"hru{rec['id']:05d}"
            f.write(f"  {rec['id']:<10d} {name:<14s} "
                    f"{'topo1':>10s} {'hyd1':>10s} "
                    f"{'lu{}'.format(rec['landuse']):>10s} "
                    f"{'soil{}'.format(rec['soil']):>10s} "
                    f"{'null':>10s} {'null':>10s} {'null':>10s} {'null':>10s}\n")

    # Write hru.con
    hru_con_path = output_dir / "hru.con"
    with open(hru_con_path, 'w') as f:
        f.write("hru.con: written by SWAT+ knowledge infrastructure\n")
        f.write("  id         name           gis_id     area       lat        lon        elev       wst\n")
        for rec in hru_records:
            name = f"hru{rec['id']:05d}"
            f.write(f"  {rec['id']:<10d} {name:<14s} {rec['id']:>10d} "
                    f"{rec['area_frac']:>10.4f} {'0.0':>10s} {'0.0':>10s} "
                    f"{'0.0':>10s} {'wst001':>10s}\n")

    logger.info(f"Created {len(hru_records)} HRUs across {len(subbasins)} subbasins")

    return {
        "status": "success",
        "hru_data": str(hru_data_path),
        "hru_con": str(hru_con_path),
        "n_hrus": len(hru_records),
        "n_subbasins": len(subbasins)
    }


def validate_outputs(result):
    errors = []
    for key in ["hru_data", "hru_con"]:
        if not Path(result[key]).exists():
            errors.append(f"Expected output not created: {result[key]}")
    if result["n_hrus"] == 0:
        errors.append("No HRUs created — check overlay inputs")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info(f"Output validation passed. {result['n_hrus']} HRUs created.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
