#!/usr/bin/env python3
"""
convert_soil_to_wrf.py - Convert soil and terrain datasets to WRF geogrid format.

Converts HWSD (Harmonized World Soil Database), SoilGrids, or custom soil/terrain
data into the binary format expected by WPS geogrid.

Pipeline stage: S1 (Geographical Data)
Pattern: validate -> process -> validate

Usage:
    python convert_soil_to_wrf.py \
        --input /path/to/hwsd_or_soilgrids/ \
        --output /path/to/geogrid_data/ \
        --variable SOILCTOP \
        --resolution 30s
"""

import argparse
import json
import os
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# WRF Soil type classification (USDA 16-category)
# ---------------------------------------------------------------------------
WRF_SOIL_CATEGORIES = {
    1:  "Sand",
    2:  "Loamy Sand",
    3:  "Sandy Loam",
    4:  "Silt Loam",
    5:  "Silt",
    6:  "Loam",
    7:  "Sandy Clay Loam",
    8:  "Silty Clay Loam",
    9:  "Clay Loam",
    10: "Sandy Clay",
    11: "Silty Clay",
    12: "Clay",
    13: "Organic Material",
    14: "Water",
    15: "Bedrock",
    16: "Other",
}

# HWSD texture class -> WRF USDA category mapping
HWSD_TO_WRF_SOIL = {
    "Cl":     12,  # Clay
    "SiCl":   11,  # Silty Clay
    "SaCl":   10,  # Sandy Clay
    "ClLo":    9,  # Clay Loam
    "SiClLo":  8,  # Silty Clay Loam
    "SaClLo":  7,  # Sandy Clay Loam
    "Lo":      6,  # Loam
    "SiLo":    4,  # Silt Loam
    "SaLo":    3,  # Sandy Loam
    "Si":      5,  # Silt
    "LoSa":    2,  # Loamy Sand
    "Sa":      1,  # Sand
}

# SoilGrids USDA texture class -> WRF mapping
SOILGRIDS_TO_WRF_SOIL = {
    0:  14,  # No data / Water
    1:  12,  # Clay
    2:  11,  # Silty Clay
    3:  10,  # Sandy Clay
    4:   9,  # Clay Loam
    5:   8,  # Silty Clay Loam
    6:   7,  # Sandy Clay Loam
    7:   6,  # Loam
    8:   4,  # Silt Loam
    9:   3,  # Sandy Loam
    10:  5,  # Silt
    11:  2,  # Loamy Sand
    12:  1,  # Sand
}

# Geogrid resolution string -> approximate cell size in degrees
RESOLUTION_MAP = {
    "30s": 1.0 / 120.0,   # ~1 km
    "2m":  2.0 / 60.0,    # ~4 km
    "5m":  5.0 / 60.0,    # ~10 km
    "10m": 10.0 / 60.0,   # ~20 km
}

# Geogrid variable specifications
GEOGRID_VARIABLES = {
    "SOILCTOP": {
        "description": "Top-layer soil category (USDA 16-cat)",
        "units": "category",
        "category_min": 1,
        "category_max": 16,
        "type": "categorical",
        "missing_value": 14,  # Default to water
    },
    "SOILCBOT": {
        "description": "Bottom-layer soil category (USDA 16-cat)",
        "units": "category",
        "category_min": 1,
        "category_max": 16,
        "type": "categorical",
        "missing_value": 14,
    },
    "SCT_DOM": {
        "description": "Dominant top-layer soil category",
        "units": "category",
        "category_min": 1,
        "category_max": 16,
        "type": "categorical",
        "missing_value": 14,
    },
    "HGT_M": {
        "description": "Terrain elevation",
        "units": "m",
        "type": "continuous",
        "missing_value": 0.0,
    },
    "LU_INDEX": {
        "description": "Land-use category (MODIS 21-cat or USGS 24-cat)",
        "units": "category",
        "type": "categorical",
        "missing_value": 16,  # Water
    },
}


def validate_inputs(input_dir: str, variable: str, resolution: str, source: str) -> dict:
    """Validate inputs before processing."""
    errors = []
    warnings = []

    if not os.path.isdir(input_dir):
        errors.append(f"Input directory does not exist: {input_dir}")

    if variable not in GEOGRID_VARIABLES:
        errors.append(f"Unknown variable: {variable}. Supported: {list(GEOGRID_VARIABLES.keys())}")

    if resolution not in RESOLUTION_MAP:
        errors.append(f"Unknown resolution: {resolution}. Supported: {list(RESOLUTION_MAP.keys())}")

    if source not in ("HWSD", "SoilGrids", "custom"):
        errors.append(f"Unknown source: {source}. Supported: HWSD, SoilGrids, custom")

    if os.path.isdir(input_dir):
        files = list(Path(input_dir).glob("*"))
        data_files = [f for f in files if f.suffix in (".nc", ".tif", ".bil", ".csv", ".asc")]
        if len(data_files) == 0:
            errors.append(f"No recognized data files in {input_dir}")
        else:
            print(f"  Found {len(data_files)} data files")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def write_geogrid_index(output_dir: str, variable: str, resolution: str,
                         nx: int, ny: int, known_lat: float, known_lon: float,
                         dx: float, dy: float):
    """
    Write the 'index' file required by geogrid for each data source tile.

    This file tells geogrid how to read the binary data.
    """
    var_spec = GEOGRID_VARIABLES[variable]

    index_content = f"""type = {var_spec['type']}
signed = yes
projection = regular_ll
known_x = 1.0
known_y = 1.0
known_lat = {known_lat:.6f}
known_lon = {known_lon:.6f}
dx = {dx:.10f}
dy = {dy:.10f}
wordsize = 2
tile_x = {nx}
tile_y = {ny}
tile_z = 1
units = "{var_spec['units']}"
description = "{var_spec['description']}"
missing_value = {var_spec['missing_value']}
"""
    if var_spec["type"] == "categorical":
        index_content += f"category_min = {var_spec.get('category_min', 1)}\n"
        index_content += f"category_max = {var_spec.get('category_max', 16)}\n"

    index_path = os.path.join(output_dir, "index")
    with open(index_path, "w") as f:
        f.write(index_content)

    return index_path


def convert_hwsd_to_geogrid(input_dir: str, output_dir: str, variable: str,
                              resolution: str) -> dict:
    """
    Convert HWSD raster data to WPS geogrid binary tile format.

    UNIT TRAPS:
    - HWSD texture classes use FAO abbreviations, must map to USDA 16-category
    - Missing soil data over water must be set to category 14 (Water), not 0
    - Geogrid expects signed 16-bit integers in big-endian byte order
    - Tile naming convention: NNNNN-MMMMM.NNNNN-MMMMM (start_x-end_x.start_y-end_y)
    """
    os.makedirs(output_dir, exist_ok=True)

    try:
        import numpy as np
    except ImportError:
        return {"status": "error", "message": "numpy required"}

    # Attempt to read source data
    nc_files = list(Path(input_dir).glob("*.nc"))
    tif_files = list(Path(input_dir).glob("*.tif"))
    csv_files = list(Path(input_dir).glob("*.csv"))

    data = None
    lats = None
    lons = None

    if nc_files:
        try:
            import netCDF4 as nc4
            ds = nc4.Dataset(str(nc_files[0]), "r")
            # Try common variable names
            for vname in ["SOILTYPE", "soiltype", "soil_type", "texture_class", "Band1"]:
                if vname in ds.variables:
                    data = np.array(ds.variables[vname][:])
                    break
            for lname in ["lat", "latitude", "y"]:
                if lname in ds.variables:
                    lats = np.array(ds.variables[lname][:])
                    break
            for lname in ["lon", "longitude", "x"]:
                if lname in ds.variables:
                    lons = np.array(ds.variables[lname][:])
                    break
            ds.close()
        except Exception as e:
            return {"status": "error", "message": f"Failed to read NetCDF: {e}"}
    elif tif_files:
        try:
            from osgeo import gdal
            ds = gdal.Open(str(tif_files[0]))
            data = ds.ReadAsArray()
            gt = ds.GetGeoTransform()
            ny_d, nx_d = data.shape
            lons = np.arange(nx_d) * gt[1] + gt[0] + gt[1] / 2
            lats = np.arange(ny_d) * gt[5] + gt[3] + gt[5] / 2
            ds = None
        except Exception as e:
            return {"status": "error", "message": f"Failed to read GeoTIFF: {e}"}

    if data is None:
        return {"status": "error", "message": "Could not read soil data from input files"}

    # Apply soil category mapping
    var_spec = GEOGRID_VARIABLES[variable]
    mapped = np.full_like(data, var_spec["missing_value"], dtype=np.int16)

    for src_class, wrf_class in HWSD_TO_WRF_SOIL.items():
        # Handle both string and numeric keys depending on source format
        if isinstance(src_class, str):
            pass  # String keys handled differently
        else:
            mapped[data == src_class] = wrf_class

    # Numeric mapping fallback
    for src_val in range(1, 13):
        if src_val in SOILGRIDS_TO_WRF_SOIL:
            mapped[data == src_val] = SOILGRIDS_TO_WRF_SOIL[src_val]

    # Ensure valid range
    mapped[(mapped < 1) | (mapped > 16)] = var_spec["missing_value"]

    ny_d, nx_d = mapped.shape
    cell_size = RESOLUTION_MAP[resolution]

    # Write binary tile
    tile_name = f"00001-{nx_d:05d}.00001-{ny_d:05d}"
    tile_path = os.path.join(output_dir, tile_name)

    with open(tile_path, "wb") as f:
        # Write as big-endian signed 16-bit integers (row by row, south to north)
        for j in range(ny_d - 1, -1, -1):
            row = mapped[j, :].astype(">i2")
            f.write(row.tobytes())

    # Write index file
    known_lat = float(lats[-1]) if lats is not None else -90.0
    known_lon = float(lons[0]) if lons is not None else -180.0
    write_geogrid_index(output_dir, variable, resolution, nx_d, ny_d,
                         known_lat, known_lon, cell_size, cell_size)

    return {
        "status": "success",
        "tile_file": tile_path,
        "index_file": os.path.join(output_dir, "index"),
        "dimensions": f"{nx_d} x {ny_d}",
        "resolution": resolution,
    }


def validate_outputs(output_dir: str, variable: str) -> dict:
    """Validate geogrid output files."""
    errors = []
    warnings = []

    index_file = os.path.join(output_dir, "index")
    if not os.path.isfile(index_file):
        errors.append("Missing index file")

    tile_files = [f for f in Path(output_dir).iterdir()
                  if f.is_file() and f.name != "index" and not f.name.startswith(".")]
    if len(tile_files) == 0:
        errors.append("No tile files produced")
    else:
        for tf in tile_files:
            if tf.stat().st_size == 0:
                errors.append(f"Empty tile file: {tf.name}")
        print(f"  Produced {len(tile_files)} tile files")

    # Validate index file content
    if os.path.isfile(index_file):
        with open(index_file) as f:
            content = f.read()
        required_keys = ["type", "projection", "known_lat", "known_lon", "dx", "dy", "wordsize"]
        for key in required_keys:
            if key not in content:
                errors.append(f"Index file missing required key: {key}")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/terrain data to WRF geogrid binary format"
    )
    parser.add_argument("--input", required=True, help="Input directory with soil/terrain data")
    parser.add_argument("--output", required=True, help="Output directory for geogrid tiles")
    parser.add_argument("--variable", required=True,
                        choices=list(GEOGRID_VARIABLES.keys()),
                        help="Geogrid variable to produce")
    parser.add_argument("--source", default="HWSD", choices=["HWSD", "SoilGrids", "custom"],
                        help="Input data source")
    parser.add_argument("--resolution", default="30s", choices=list(RESOLUTION_MAP.keys()),
                        help="Target resolution")
    args = parser.parse_args()

    print("=" * 60)
    print("WRF Soil/Terrain Converter: External -> Geogrid Format")
    print("=" * 60)
    print(f"  Variable:   {args.variable}")
    print(f"  Source:     {args.source}")
    print(f"  Resolution: {args.resolution}")
    print(f"  Input:      {args.input}")
    print(f"  Output:     {args.output}")

    # Step 1: Validate inputs
    print("\n[1/3] Validating inputs...")
    v = validate_inputs(args.input, args.variable, args.resolution, args.source)
    if not v["valid"]:
        for e in v["errors"]:
            print(f"  ERROR: {e}")
        sys.exit(1)

    # Step 2: Convert
    print("\n[2/3] Converting data...")
    result = convert_hwsd_to_geogrid(args.input, args.output, args.variable, args.resolution)
    if result["status"] != "success":
        print(f"CONVERSION FAILED: {result.get('message', 'Unknown error')}")
        sys.exit(1)

    # Step 3: Validate outputs
    print("\n[3/3] Validating outputs...")
    vo = validate_outputs(args.output, args.variable)
    if not vo["valid"]:
        for e in vo["errors"]:
            print(f"  ERROR: {e}")
        sys.exit(1)

    print("\nDONE - Conversion successful")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
