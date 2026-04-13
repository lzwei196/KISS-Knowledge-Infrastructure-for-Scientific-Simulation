#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      create_initial_conditions
Stage:        s5_initial_conditions
Description:  Generate SUMMA cold-start initial conditions NetCDF.

              Sets initial states for snow (SWE=0, no layers), soil
              (temperature from mean annual T, moisture near field capacity),
              canopy (no ice/liquid), and aquifer (near-zero storage).

              CRITICAL: The initial conditions file must have dimensions that
              match the soil layer configuration. The default is 8 soil layers
              with depths [0.025, 0.075, 0.15, 0.25, 0.50, 0.50, 1.0, 1.5] m.

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
ATTRIBUTES_NC = ""
OUTPUT_NC = ""
N_SOIL_LAYERS = 8
SOIL_LAYER_DEPTHS = [0.025, 0.075, 0.15, 0.25, 0.50, 0.50, 1.0, 1.5]  # meters
INIT_SOIL_TEMP = 288.5     # K (15.4 C) — matches Reynolds test case
INIT_SOIL_MOISTURE = 0.29  # volumetric fraction — matches Reynolds
INIT_MATRIC_HEAD = -100.0  # m — matches Reynolds (drier init, avoids saturation instability)
INIT_CANOPY_LIQ = 3.16     # kg/m² — matches Reynolds (some canopy water)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Create SUMMA initial conditions")
    parser.add_argument("--attributes_nc", required=True)
    parser.add_argument("--output_nc", required=True)
    parser.add_argument("--n_soil_layers", type=int, default=8)
    parser.add_argument("--soil_depths", type=str, default="0.025,0.075,0.15,0.25,0.50,0.50,1.0,1.5")
    parser.add_argument("--init_temp", type=float, default=283.16)
    parser.add_argument("--init_moisture", type=float, default=0.30)
    args = parser.parse_args()
    ATTRIBUTES_NC = args.attributes_nc
    OUTPUT_NC = args.output_nc
    N_SOIL_LAYERS = args.n_soil_layers
    SOIL_LAYER_DEPTHS = [float(x) for x in args.soil_depths.split(',')]
    INIT_SOIL_TEMP = args.init_temp
    INIT_SOIL_MOISTURE = args.init_moisture


def validate_inputs():
    errors = []
    if not ATTRIBUTES_NC or not Path(ATTRIBUTES_NC).exists():
        errors.append(f"Attributes NC not found: {ATTRIBUTES_NC}")
    if not OUTPUT_NC:
        errors.append("OUTPUT_NC is not set")
    if len(SOIL_LAYER_DEPTHS) != N_SOIL_LAYERS:
        errors.append(f"SOIL_LAYER_DEPTHS has {len(SOIL_LAYER_DEPTHS)} entries "
                      f"but N_SOIL_LAYERS={N_SOIL_LAYERS}")
    if INIT_SOIL_TEMP < 200 or INIT_SOIL_TEMP > 320:
        errors.append(f"INIT_SOIL_TEMP={INIT_SOIL_TEMP} K is unrealistic")
    if INIT_SOIL_MOISTURE < 0 or INIT_SOIL_MOISTURE > 0.6:
        errors.append(f"INIT_SOIL_MOISTURE={INIT_SOIL_MOISTURE} is out of range [0, 0.6]")
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
            required = ['nSoil', 'nSnow', 'mLayerTemp', 'mLayerVolFracLiq',
                         'mLayerVolFracIce', 'mLayerMatricHead', 'dt_init']
            for var in required:
                if var not in ds.variables:
                    errors.append(f"Missing variable: {var}")
            ds.close()
        except Exception as e:
            errors.append(f"Cannot read output: {e}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def process():
    """Create cold-start initial conditions."""
    from netCDF4 import Dataset

    os.makedirs(os.path.dirname(OUTPUT_NC) or '.', exist_ok=True)

    # Read attributes
    attr_ds = Dataset(ATTRIBUTES_NC, 'r')
    hru_ids = attr_ds.variables['hruId'][:]
    n_hru = len(hru_ids)
    attr_ds.close()

    n_snow = 0  # cold start: no snow layers
    n_soil = N_SOIL_LAYERS
    n_toto = n_snow + n_soil  # total layers (snow + soil)

    # Create NetCDF
    ds = Dataset(OUTPUT_NC, 'w', format='NETCDF4')

    # Dimensions
    ds.createDimension('hru', n_hru)
    ds.createDimension('scalarv', 1)
    ds.createDimension('midSoil', n_soil)
    ds.createDimension('midToto', n_toto)
    ds.createDimension('ifcSoil', n_soil + 1)
    ds.createDimension('ifcToto', n_toto + 1)
    ds.createDimension('spectral', 2)

    # Scalar state variables (scalarv, hru)
    def scalar_var(name, value, units='', long_name=''):
        v = ds.createVariable(name, 'f8', ('scalarv', 'hru'))
        v[:] = np.full((1, n_hru), value)
        if units:
            v.units = units
        if long_name:
            v.long_name = long_name
        return v

    scalar_var('dt_init', 360.0, 's', 'Length of initial time step')  # Reynolds uses 360s
    scalar_var('scalarCanopyIce', 0.0, 'kg m-2', 'Mass of ice on vegetation canopy')
    scalar_var('scalarCanopyLiq', INIT_CANOPY_LIQ, 'kg m-2', 'Mass of liquid water on vegetation canopy')
    scalar_var('scalarCanairTemp', INIT_SOIL_TEMP - 2.5, 'K', 'Temperature of canopy air space')  # slightly cooler than soil
    scalar_var('scalarCanopyTemp', INIT_SOIL_TEMP + 1.5, 'K', 'Temperature of vegetation canopy')  # slightly warmer
    scalar_var('scalarSnowAlbedo', 0.82, '-', 'Snow albedo for the entire spectral band')
    scalar_var('scalarSnowDepth', 0.0, 'm', 'Total snow depth')
    scalar_var('scalarSWE', 0.0, 'kg m-2', 'Snow water equivalent')
    scalar_var('scalarSfcMeltPond', 0.0, 'kg m-2', 'Ponded water caused by melt')
    scalar_var('scalarAquiferStorage', 0.0, 'm', 'Relative aquifer storage')

    # Integer scalars
    nsoil_var = ds.createVariable('nSoil', 'i4', ('scalarv', 'hru'))
    nsoil_var[:] = np.full((1, n_hru), n_soil, dtype=np.int32)

    nsnow_var = ds.createVariable('nSnow', 'i4', ('scalarv', 'hru'))
    nsnow_var[:] = np.full((1, n_hru), 0, dtype=np.int32)

    # Layer variables -- midToto dimension (soil only for cold start)
    # Layer depth
    depth_var = ds.createVariable('mLayerDepth', 'f8', ('midToto', 'hru'))
    depth_var.units = 'm'
    for i in range(n_soil):
        depth_var[i, :] = SOIL_LAYER_DEPTHS[i]

    # Layer temperature
    temp_var = ds.createVariable('mLayerTemp', 'f8', ('midToto', 'hru'))
    temp_var.units = 'K'
    for i in range(n_soil):
        # Slight gradient: surface warmer, deep cooler (or constant)
        temp_var[i, :] = INIT_SOIL_TEMP

    # Volumetric liquid fraction
    liq_var = ds.createVariable('mLayerVolFracLiq', 'f8', ('midToto', 'hru'))
    liq_var.units = '-'
    for i in range(n_soil):
        liq_var[i, :] = INIT_SOIL_MOISTURE

    # Volumetric ice fraction
    ice_var = ds.createVariable('mLayerVolFracIce', 'f8', ('midToto', 'hru'))
    ice_var.units = '-'
    for i in range(n_soil):
        ice_var[i, :] = 0.0

    # Matric head (midSoil dimension)
    head_var = ds.createVariable('mLayerMatricHead', 'f8', ('midSoil', 'hru'))
    head_var.units = 'm'
    for i in range(n_soil):
        head_var[i, :] = INIT_MATRIC_HEAD

    # Interface heights (ifcToto)
    ifch_var = ds.createVariable('iLayerHeight', 'f8', ('ifcToto', 'hru'))
    ifch_var.units = 'm'
    cumulative = 0.0
    for i in range(n_toto + 1):
        if i == 0:
            ifch_var[i, :] = 0.0
        else:
            cumulative += SOIL_LAYER_DEPTHS[i - 1]
            ifch_var[i, :] = cumulative

    # Spectral band albedo
    spec_var = ds.createVariable('spectralSnowAlbedoDiffuse', 'f8', ('spectral', 'hru'))
    spec_var[:] = np.array([[0.95], [0.65]]) * np.ones((1, n_hru))

    ds.history = "Cold start initial conditions created by create_initial_conditions.py"
    ds.close()

    logger.info(f"Initial conditions written: {OUTPUT_NC}")
    logger.info(f"  {n_hru} HRUs, {n_soil} soil layers, 0 snow layers (cold start)")
    logger.info(f"  Init temp: {INIT_SOIL_TEMP} K, Init moisture: {INIT_SOIL_MOISTURE}")

    print(json.dumps({
        "status": "success",
        "n_hru": n_hru,
        "n_soil_layers": n_soil,
        "init_temp_K": INIT_SOIL_TEMP,
        "init_moisture": INIT_SOIL_MOISTURE,
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
