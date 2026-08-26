#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      landcover_to_mhm_luse
Stage:        s2_morphology
Description:  Convert AVHRR land cover to mHM land use classes.

mHM uses 10 land use classes with monthly LAI lookup:
  1: Coniferous-forest
  2: Deciduous-forest
  3: Mixed-forest
  4: Sparsely-populated-forest
  5: Sealed/Water-bodies
  6: Viniculture (crops)
  7: Intensive-orchards
  8: Pasture
  9: Fields (cropland)
  10: Wetlands

AVHRR Global Land Cover -> mHM mapping:
  1 (Evergreen Needleleaf) -> 1 (Coniferous)
  2 (Evergreen Broadleaf) -> 2 (Deciduous)
  3 (Deciduous Needleleaf) -> 1 (Coniferous)
  4 (Deciduous Broadleaf) -> 2 (Deciduous)
  5 (Mixed Forest) -> 3 (Mixed)
  6 (Closed Shrublands) -> 4 (Sparse forest)
  7 (Open Shrublands) -> 4 (Sparse forest)
  8 (Woody Savannas) -> 4 (Sparse forest)
  9 (Savannas) -> 8 (Pasture)
  10 (Grasslands) -> 8 (Pasture)
  11 (Permanent Wetlands) -> 10 (Wetlands)
  12 (Croplands) -> 9 (Fields)
  13 (Urban) -> 5 (Sealed)
  14 (Crop/Nat Mosaic) -> 9 (Fields)
  15 (Snow/Ice) -> 5 (Sealed)
  16 (Barren) -> 4 (Sparse)
  17 (Water) -> 5 (Sealed/Water)

Inputs:
  - CONFIG_PATH: config.json
  - DOMAIN_INFO_PATH: domain_info.json
  - AVHRR_PATH: path to AVHRR land cover raster

Outputs:
  - lc_YYYY.asc in input/luse/
  - LAI_class.asc in input/morph/
  - LAI_classdefinition.txt in input/morph/

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = ""
DOMAIN_INFO_PATH = ""
AVHRR_PATH = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"),
                          "data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif")
LEGEND = "umd"

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--domain_info", required=True)
    parser.add_argument("--avhrr_path", default=AVHRR_PATH)
    parser.add_argument("--legend", default="umd", choices=["umd", "igbp"],
                        help="Legend of the land-cover raster. The shipped AVHRR "
                             "raster is UMD, not IGBP (dt_s12).")
    args = parser.parse_args()
    CONFIG_PATH = args.config
    DOMAIN_INFO_PATH = args.domain_info
    AVHRR_PATH = args.avhrr_path
    LEGEND = args.legend

# TRAP (dt_s12).  The shipped raster
#   data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif
# uses the UMD 14-class legend, NOT IGBP -- its .vat.dbf global counts confirm it
# (value 11 = 11.8M cells = cropland; value 12 = 87M = bare).  Under IGBP,
# 11 = Permanent Wetlands, so an IGBP lookup relabels all Huai cropland as wetland
# and swaps the seasonal crop LAI curve (0.0-5.2) for a flat 2-5 year-round.
#
# UMD: 0=water 1=evergreen-needleleaf 2=evergreen-broadleaf 3=deciduous-needleleaf
#      4=deciduous-broadleaf 5=mixed-forest 6=woodland 7=wooded-grassland
#      8=closed-shrubland 9=open-shrubland 10=grassland 11=cropland 12=bare 13=urban
UMD_TO_MHM = {
    0: 5,                  # water                 -> Sealed/Water-bodies
    1: 1, 3: 1,            # needleleaf            -> Coniferous
    2: 2, 4: 2,            # broadleaf             -> Deciduous
    5: 3,                  # mixed forest          -> Mixed
    6: 4, 7: 4, 8: 4,      # woodland / closed shrub -> Sparsely-populated-forest
    9: 8, 10: 8,           # open shrub / grassland  -> Pasture
    11: 9, 12: 9, 14: 9,   # cropland / bare         -> Fields
    13: 5,                 # urban                   -> Sealed
}

IGBP_TO_MHM = {
    1: 1, 2: 2, 3: 1, 4: 2, 5: 3, 6: 4, 7: 4, 8: 4,
    9: 8, 10: 8, 11: 10, 12: 9, 13: 5, 14: 9, 15: 5, 16: 4, 17: 5,
    0: 9,  # nodata -> fields (safe default)
}

AVHRR_TO_MHM = UMD_TO_MHM if LEGEND == "umd" else IGBP_TO_MHM

# Monthly LAI values for each mHM class (from test_domain LAI_classdefinition.txt)
LAI_TABLE = {
    1:  [11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11],      # Coniferous
    2:  [0.5, 0.5, 1.5, 4.0, 7.0, 11, 12, 12, 11, 8.0, 1.5, 0.5],  # Deciduous
    3:  [3.0, 3.0, 4.0, 6.0, 8.0, 11, 11.5, 11.5, 11, 9.0, 4.0, 3.0],  # Mixed
    4:  [2.0, 2.0, 3.0, 5.5, 6.5, 7.5, 7.5, 7.5, 6.5, 4.0, 2.5, 2.0],  # Sparse
    5:  [0.01, 0.01, 0.02, 0.04, 0.06, 0.09, 0.09, 0.07, 0.06, 0.04, 0.02, 0.02],  # Sealed
    6:  [1.0, 1.0, 1.0, 1.5, 2.0, 3.5, 4.0, 4.0, 4.0, 1.5, 1.0, 1.0],  # Viniculture
    7:  [2.0, 2.0, 2.0, 2.0, 3.0, 3.5, 4.0, 4.0, 4.0, 2.5, 2.0, 2.0],  # Orchards
    8:  [2.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0, 5.0, 5.0, 3.0, 2.5, 2.0],  # Pasture
    9:  [0.4, 0.4, 0.3, 0.7, 3.0, 5.2, 4.6, 3.1, 1.3, 0.2, 0.0, 0.0],  # Fields
    10: [2.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0, 5.0, 5.0, 3.0, 2.5, 2.0],  # Wetlands
}

LAI_NAMES = {
    1: "Coniferous-forest", 2: "Deciduous-forest", 3: "Mixed-forest",
    4: "Sparsely-populated-forest", 5: "Sealed-Water-bodies", 6: "Viniculture",
    7: "Intensive-orchards", 8: "Pasture", 9: "Fields", 10: "Wetlands",
}


def write_ascii_grid(filepath, data, header):
    with open(filepath, 'w') as f:
        f.write(f"ncols         {header['ncols']}\n")
        f.write(f"nrows         {header['nrows']}\n")
        f.write(f"xllcorner     {header['xllcorner']}\n")
        f.write(f"yllcorner     {header['yllcorner']}\n")
        f.write(f"cellsize      {header['cellsize']}\n")
        f.write(f"NODATA_value  {header['NODATA_value']}\n")
        nodata = header['NODATA_value']
        for row in data:
            vals = [str(int(nodata)) if np.isnan(v) or v == nodata else str(int(v)) for v in row]
            f.write(" ".join(vals) + "\n")


def validate_inputs():
    errors = []
    if not CONFIG_PATH or not Path(CONFIG_PATH).exists():
        errors.append(f"Config not found: {CONFIG_PATH}")
    if not DOMAIN_INFO_PATH or not Path(DOMAIN_INFO_PATH).exists():
        errors.append(f"Domain info not found: {DOMAIN_INFO_PATH}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    config = json.load(open(CONFIG_PATH))
    domain_info = json.load(open(DOMAIN_INFO_PATH))
    header = domain_info["header_L0"]
    morph_dir = Path(config["output_dir"]) / "input" / "morph"
    luse_dir = Path(config["output_dir"]) / "input" / "luse"
    morph_dir.mkdir(parents=True, exist_ok=True)
    luse_dir.mkdir(parents=True, exist_ok=True)

    nrows = header["nrows"]
    ncols = header["ncols"]

    if Path(AVHRR_PATH).exists():
        import rasterio
        from rasterio.warp import reproject, Resampling
        from rasterio.transform import from_bounds

        xll = header['xllcorner']
        yll = header['yllcorner']
        cs = header['cellsize']
        xur = xll + ncols * cs
        yur = yll + nrows * cs

        with rasterio.open(AVHRR_PATH) as src:
            dst_transform = from_bounds(xll, yll, xur, yur, ncols, nrows)
            lc_grid = np.full((nrows, ncols), 0, dtype=np.int32)
            reproject(
                source=rasterio.band(src, 1),
                destination=lc_grid,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs="EPSG:4326",
                resampling=Resampling.nearest,
                dst_nodata=0,
            )
        logger.info(f"Read AVHRR land cover: {AVHRR_PATH}")
    else:
        # dt_s12: a UNIFORM land-cover grid is never a valid result -- it silently
        # disables every land-cover-dependent MPR transfer function. Fail, don't fake.
        logger.error(f"Land-cover raster not found: {AVHRR_PATH}. Refusing to fall "
                     f"back to a uniform grid.")
        sys.exit(1)

    # Reclassify AVHRR -> mHM
    mhm_lc = np.full((nrows, ncols), -9999, dtype=np.int32)
    for avhrr_class, mhm_class in AVHRR_TO_MHM.items():
        mhm_lc[lc_grid == avhrr_class] = mhm_class

    # Set remaining 0/unclassified to default
    mhm_lc[(mhm_lc <= 0) & (mhm_lc != -9999)] = 9

    # Apply nodata mask from DEM
    dem_path = morph_dir / "dem.asc"
    if dem_path.exists():
        with open(dem_path) as f:
            for _ in range(6):
                f.readline()
            dem_data = [[float(x) for x in line.split()] for line in f]
            dem_arr = np.array(dem_data)
            mhm_lc[dem_arr == -9999] = -9999

    # Write land cover scene for MPR (lc_YYYY.asc) — MUST use 3-class system
    # mHM's MPR (mo_mpr_soilmoist.f90) only handles 3 organic matter classes:
    #   1 = forest, 2 = impervious/sealed, 3 = pervious
    # If max landcover ID > 3, MPR crashes with "pOM used uninitialized".
    # Remap: forest classes (1-4) → 1, sealed (5) → 2, pervious (6-10) → 3
    MHM_10_TO_3 = {
        1: 1, 2: 1, 3: 1, 4: 1,    # all forest types → forest
        5: 2,                        # sealed/impervious → impervious
        6: 3, 7: 3, 8: 3, 9: 3, 10: 3,  # crops/pasture/wetlands → pervious
    }
    mhm_lc_3class = np.where(
        mhm_lc > 0,
        np.vectorize(lambda x: MHM_10_TO_3.get(int(x), 3))(mhm_lc),
        -9999
    ).astype(float)

    start_year = config["start_year"]
    lc_filename = f"lc_{start_year}.asc"
    write_ascii_grid(luse_dir / lc_filename, mhm_lc_3class, header)
    logger.info(f"Written: {luse_dir / lc_filename} (3-class for MPR)")

    # Write LAI_class.asc (10-class for LAI lookup — NOT the same as lc_*.asc)
    write_ascii_grid(morph_dir / "LAI_class.asc", mhm_lc.astype(float), header)

    # Write LAI_classdefinition.txt
    classdef_path = morph_dir / "LAI_classdefinition.txt"
    with open(classdef_path, 'w') as f:
        f.write("NoLAIclasses           10\n")
        f.write("ID   LAND-USE                  Jan.   Feb.    Mar.    Apr.    May    Jun.    Jul.    Aug.    Sep.    Oct.    Nov.    Dec.\n")
        for i in range(1, 11):
            lai = LAI_TABLE[i]
            name = LAI_NAMES[i]
            lai_str = "".join(f"{v:8}" for v in lai)
            f.write(f"{i:2d}    {name:26s}{lai_str}\n")
    logger.info(f"Written: {classdef_path}")

    unique, counts = np.unique(mhm_lc[mhm_lc > 0], return_counts=True)
    class_dist = {int(u): int(c) for u, c in zip(unique, counts)}

    result = {
        "status": "success",
        "files": [lc_filename, "LAI_class.asc", "LAI_classdefinition.txt"],
        "n_classes_used": len(class_dist),
        "class_distribution": class_dist,
    }
    print(json.dumps(result, indent=2))
    return str(morph_dir)


def validate_outputs(output_path):
    morph_dir = Path(output_path)
    for f in ["LAI_class.asc", "LAI_classdefinition.txt"]:
        if not (morph_dir / f).exists():
            logger.error(f"Missing: {morph_dir / f}")
            sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
