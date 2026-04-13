#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      create_local_attributes
Stage:        s1_domain_setup
Description:  Generate SUMMA local attributes NetCDF file from GRU/HRU mapping
              CSV. This file defines the spatial structure SUMMA uses for all
              subsequent operations.

Required NetCDF variables:
  GRU-dimension: gruId
  HRU-dimension: hruId, gruId (mapping), latitude, longitude, elevation,
                 HRUarea, contourLength, tan_slope, mHeight,
                 vegTypeIndex, soilTypeIndex, slopeTypeIndex, downHRUindex

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GRU_HRU_CSV = ""
OUTPUT_NC = ""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CLI override
# ---------------------------------------------------------------------------
if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Create SUMMA local attributes NetCDF")
    parser.add_argument("--gru_hru_csv", required=True, help="GRU/HRU mapping CSV")
    parser.add_argument("--output_nc", required=True, help="Output NetCDF path")
    args = parser.parse_args()
    GRU_HRU_CSV = args.gru_hru_csv
    OUTPUT_NC = args.output_nc


def validate_inputs():
    errors = []
    if not GRU_HRU_CSV or not Path(GRU_HRU_CSV).exists():
        errors.append(f"GRU/HRU CSV not found: {GRU_HRU_CSV}")
    if not OUTPUT_NC:
        errors.append("OUTPUT_NC is not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_path):
    errors = []
    if not Path(output_path).exists():
        errors.append(f"Output not created: {output_path}")
    else:
        try:
            from netCDF4 import Dataset
            ds = Dataset(output_path, 'r')
            required_vars = ['hruId', 'gruId', 'latitude', 'longitude',
                             'elevation', 'HRUarea', 'tan_slope', 'vegTypeIndex',
                             'soilTypeIndex']
            for var in required_vars:
                if var not in ds.variables:
                    errors.append(f"Missing variable in NetCDF: {var}")
            if 'hru' not in ds.dimensions:
                errors.append("Missing dimension: hru")
            if 'gru' not in ds.dimensions:
                errors.append("Missing dimension: gru")
            ds.close()
        except Exception as e:
            errors.append(f"Cannot read output NetCDF: {e}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def process():
    """Create local attributes NetCDF from CSV."""
    try:
        import csv
        from netCDF4 import Dataset
    except ImportError as e:
        logger.error(f"Missing dependency: {e}. Install: pip install netCDF4")
        sys.exit(2)

    os.makedirs(os.path.dirname(OUTPUT_NC) or '.', exist_ok=True)

    # Read CSV
    logger.info(f"Reading GRU/HRU mapping: {GRU_HRU_CSV}")
    rows = []
    with open(GRU_HRU_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    n_hru = len(rows)
    gru_ids_unique = sorted(set(int(r['gruId']) for r in rows))
    n_gru = len(gru_ids_unique)
    logger.info(f"Found {n_gru} GRUs, {n_hru} HRUs")

    # Create NetCDF
    ds = Dataset(OUTPUT_NC, 'w', format='NETCDF4')

    # Dimensions
    ds.createDimension('hru', n_hru)
    ds.createDimension('gru', n_gru)

    # GRU variables
    gru_id_var = ds.createVariable('gruId', 'i8', ('gru',))
    gru_id_var[:] = np.array(gru_ids_unique, dtype=np.int64)

    # HRU variables
    hru_id_var = ds.createVariable('hruId', 'i8', ('hru',))
    hru2gru_var = ds.createVariable('hru2gruId', 'i8', ('hru',))
    lat_var = ds.createVariable('latitude', 'f8', ('hru',))
    lon_var = ds.createVariable('longitude', 'f8', ('hru',))
    elev_var = ds.createVariable('elevation', 'f8', ('hru',))
    area_var = ds.createVariable('HRUarea', 'f8', ('hru',))
    contour_var = ds.createVariable('contourLength', 'f8', ('hru',))
    slope_var = ds.createVariable('tan_slope', 'f8', ('hru',))
    mheight_var = ds.createVariable('mHeight', 'f8', ('hru',))
    veg_var = ds.createVariable('vegTypeIndex', 'i4', ('hru',))
    soil_var = ds.createVariable('soilTypeIndex', 'i4', ('hru',))
    slopetype_var = ds.createVariable('slopeTypeIndex', 'i4', ('hru',))
    downhru_var = ds.createVariable('downHRUindex', 'i8', ('hru',))

    # Fill arrays
    for i, row in enumerate(rows):
        hru_id_var[i] = int(row['hruId'])
        hru2gru_var[i] = int(row['gruId'])
        lat_var[i] = float(row['lat'])
        lon_var[i] = float(row['lon'])
        elev_var[i] = float(row['elevation'])
        area_var[i] = float(row['area_m2'])
        contour_var[i] = float(row.get('contourLength', np.sqrt(float(row['area_m2']))))
        slope_var[i] = float(row['tan_slope'])
        mheight_var[i] = float(row.get('mHeight', 3.0))
        veg_var[i] = int(row['vegTypeIndex'])
        soil_var[i] = int(row['soilTypeIndex'])
        slopetype_var[i] = 1  # default slope type
        downhru_var[i] = 0    # 0 = basin outlet (no downstream HRU)

    # Add units and descriptions
    lat_var.units = 'degrees_north'
    lon_var.units = 'degrees_east'
    elev_var.units = 'm'
    area_var.units = 'm^2'
    contour_var.units = 'm'
    slope_var.units = '-'
    mheight_var.units = 'm'
    mheight_var.long_name = 'measurement height above bare ground'

    # Global attributes
    ds.history = f"Created by create_local_attributes.py from {GRU_HRU_CSV}"
    ds.Conventions = "CF-1.6"

    ds.close()
    logger.info(f"Local attributes NetCDF created: {OUTPUT_NC}")

    print(json.dumps({
        "status": "success",
        "n_gru": n_gru,
        "n_hru": n_hru,
        "output": OUTPUT_NC
    }))

    return OUTPUT_NC


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
