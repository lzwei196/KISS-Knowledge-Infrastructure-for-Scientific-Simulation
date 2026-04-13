#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      glim_to_mhm_geology
Stage:        s2_morphology
Description:  Convert GLiM (Global Lithological Map) to mHM geology classification.

mHM uses geology to parameterize baseflow recession (GeoParam array in mhm_parameter.nml).
Each geology class has a recession constant. Karstic formations are flagged separately.

GLiM -> mHM mapping (10 classes):
  1: Unconsolidated sediments (su,sm,sc,ev) -> high permeability, high baseflow
  2: Siliciclastic sedimentary (ss) -> medium permeability
  3: Carbonate sedimentary (sc) -> karstic, very high baseflow
  4: Mixed sedimentary (sm) -> medium permeability
  5: Volcanic basic (vb) -> low-medium permeability
  6: Volcanic acid (va) -> low permeability
  7: Plutonic (pa,pb,pi) -> very low permeability
  8: Metamorphic (mt) -> low permeability
  9: Water bodies (wb) -> no baseflow
  10: Ice/glacier (ig) -> no baseflow

Inputs:
  - DOMAIN_INFO_PATH: domain_info.json
  - CONFIG_PATH: config.json
  - GLIM_SHP: path to GLiM shapefile (optional; if not available, use default class)

Outputs:
  - geology_class.asc
  - geology_classdefinition.txt

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
GLIM_SHP = ""
DEFAULT_GEOLOGY_CLASS = 2  # Siliciclastic sedimentary (safe default for most regions)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="GLiM to mHM geology classes")
    parser.add_argument("--config", required=True)
    parser.add_argument("--domain_info", required=True)
    parser.add_argument("--glim_shp", default="")
    parser.add_argument("--default_class", type=int, default=2)
    args = parser.parse_args()
    CONFIG_PATH = args.config
    DOMAIN_INFO_PATH = args.domain_info
    GLIM_SHP = args.glim_shp
    DEFAULT_GEOLOGY_CLASS = args.default_class

# GLiM lithology code to mHM class mapping
GLIM_TO_MHM = {
    "su": 1, "sm": 1, "sc": 3, "ss": 2, "ev": 1,  # Sedimentary
    "vb": 5, "va": 6, "vi": 5,                       # Volcanic
    "pa": 7, "pb": 7, "pi": 7,                        # Plutonic
    "mt": 8,                                           # Metamorphic
    "wb": 9,                                           # Water body
    "ig": 10, "nd": DEFAULT_GEOLOGY_CLASS,             # Ice, No data
}

MHM_GEO_CLASSES = {
    1: {"name": "Unconsolidated-sediments", "karstic": 0},
    2: {"name": "Siliciclastic-sedimentary", "karstic": 0},
    3: {"name": "Carbonate-sedimentary", "karstic": 1},
    4: {"name": "Mixed-sedimentary", "karstic": 0},
    5: {"name": "Volcanic-basic", "karstic": 0},
    6: {"name": "Volcanic-acid", "karstic": 0},
    7: {"name": "Plutonic", "karstic": 0},
    8: {"name": "Metamorphic", "karstic": 0},
    9: {"name": "Water-body", "karstic": 0},
    10: {"name": "Ice-glacier", "karstic": 0},
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
    logger.info(f"Written: {filepath}")


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
    morph_dir.mkdir(parents=True, exist_ok=True)

    nrows = header["nrows"]
    ncols = header["ncols"]

    if GLIM_SHP and Path(GLIM_SHP).exists():
        # Rasterize GLiM shapefile to grid
        import geopandas as gpd
        from rasterio.features import rasterize
        from rasterio.transform import from_bounds

        logger.info(f"Reading GLiM shapefile: {GLIM_SHP}")
        glim = gpd.read_file(GLIM_SHP)

        xll = header['xllcorner']
        yll = header['yllcorner']
        cs = header['cellsize']
        xur = xll + ncols * cs
        yur = yll + nrows * cs

        # Clip to domain
        from shapely.geometry import box
        domain_box = box(xll, yll, xur, yur)
        glim_clip = glim[glim.intersects(domain_box)]

        if len(glim_clip) > 0:
            transform = from_bounds(xll, yll, xur, yur, ncols, nrows)

            # Map GLiM xx field to mHM class
            shapes = []
            for _, row in glim_clip.iterrows():
                lith_code = str(row.get("xx", "nd")).lower()[:2]
                mhm_class = GLIM_TO_MHM.get(lith_code, DEFAULT_GEOLOGY_CLASS)
                shapes.append((row.geometry, mhm_class))

            geo_grid = rasterize(
                shapes, out_shape=(nrows, ncols),
                transform=transform, fill=DEFAULT_GEOLOGY_CLASS,
                dtype=np.int32
            )
        else:
            logger.warning("No GLiM features in domain, using default class")
            geo_grid = np.full((nrows, ncols), DEFAULT_GEOLOGY_CLASS, dtype=np.int32)
    else:
        # No GLiM data available: use default geology class
        logger.warning(f"No GLiM shapefile provided. Using default class {DEFAULT_GEOLOGY_CLASS}")
        geo_grid = np.full((nrows, ncols), DEFAULT_GEOLOGY_CLASS, dtype=np.int32)

    # Read DEM to mask nodata areas
    dem_path = morph_dir / "dem.asc"
    if dem_path.exists():
        with open(dem_path) as f:
            for _ in range(6):
                f.readline()  # skip header
            dem_data = []
            for line in f:
                dem_data.append([float(x) for x in line.split()])
            dem_arr = np.array(dem_data)
            geo_grid[dem_arr == -9999] = -9999

    write_ascii_grid(morph_dir / "geology_class.asc", geo_grid.astype(float), header)

    # Write geology_classdefinition.txt
    classdef_path = morph_dir / "geology_classdefinition.txt"
    with open(classdef_path, 'w') as f:
        f.write("nGeo_Formations  10\n")
        f.write("GeoParam(i)   ClassUnit     Karstic      Description\n")
        for i in range(1, 11):
            info = MHM_GEO_CLASSES[i]
            f.write(f"         {i}\t          {i}           {info['karstic']}      {info['name']}\n")
        f.write("!<-END\n")
    logger.info(f"Written: {classdef_path}")

    # Count classes
    unique, counts = np.unique(geo_grid[geo_grid > 0], return_counts=True)
    class_dist = {int(u): int(c) for u, c in zip(unique, counts)}

    result = {
        "status": "success",
        "files": ["geology_class.asc", "geology_classdefinition.txt"],
        "n_classes_used": len(class_dist),
        "class_distribution": class_dist,
        "glim_used": bool(GLIM_SHP and Path(GLIM_SHP).exists()),
    }
    print(json.dumps(result, indent=2))
    return str(morph_dir)


def validate_outputs(output_path):
    morph_dir = Path(output_path)
    for f in ["geology_class.asc", "geology_classdefinition.txt"]:
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
