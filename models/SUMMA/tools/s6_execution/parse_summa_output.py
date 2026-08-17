#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      parse_summa_output
Stage:        s6_execution
Description:  Parse SUMMA output NetCDF files into analysis-ready DataFrames.
              Extracts key hydrologic variables (runoff, ET, SWE, soil moisture,
              energy fluxes) and handles multi-layer outputs.

CRITICAL: SUMMA output variables use MIXED UNITS (dt_025):
  Variables in m/s:       scalarTotalRunoff, scalarRainPlusMelt, scalarInfiltration,
                          scalarSoilDrainage, scalarSurfaceRunoff, averageRoutedRunoff
  Variables in kg/m2/s:   scalarThroughfallRain, scalarTotalET, pptrate,
                          scalarCanopyEvaporation, scalarGroundEvaporation

  To compute discharge: Q(m³/s) = scalarTotalRunoff(m/s) × HRUarea(m²)
  Do NOT divide by 1000. The /iden_water conversion is already done in computFlux.f90.

  To convert to mm/yr:
    m/s variables:       × 86400 × 365 × 1000 (m→mm)
    kg/m2/s variables:   × 86400 × 365         (kg/m2 = mm)

Key SUMMA output variables:
  scalarTotalRunoff    (m/s)     - total runoff — Q = value × area(m²)
  scalarTotalET        (kg/m2/s) - total ET (NEGATIVE = evaporation in SUMMA convention)
  scalarSWE            (kg/m2)   - snow water equivalent
  scalarSnowDepth      (m)       - total snow depth
  scalarRainPlusMelt   (m/s)     - rain plus snowmelt entering soil
  scalarSurfaceRunoff  (m/s)     - surface runoff
  scalarSoilDrainage   (m/s)     - soil bottom drainage
  pptrate              (kg/m2/s) - precipitation rate
  mLayerVolFracLiq     (-)       - volumetric liquid water (per layer)
  mLayerTemp           (K)       - layer temperature (per layer)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
from ki_tools_common.units import CMFD_PRECIP_KGM2S_TO_MMDAY

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OUTPUT_NC = ""
VARIABLES = ['scalarTotalRunoff', 'scalarTotalET', 'scalarSWE',
             'scalarSnowDepth', 'scalarRainPlusMelt']
HRU_INDEX = 0  # which HRU to extract (0-based), or -1 for all
OUTPUT_CSV = ""

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Parse SUMMA output NetCDF")
    parser.add_argument("--output_nc", required=True, help="SUMMA output NetCDF")
    parser.add_argument("--variables", nargs='+',
                        default=['scalarTotalRunoff', 'scalarTotalET', 'scalarSWE'])
    parser.add_argument("--hru_index", type=int, default=0)
    parser.add_argument("--output_csv", default="")
    args = parser.parse_args()
    OUTPUT_NC = args.output_nc
    VARIABLES = args.variables
    HRU_INDEX = args.hru_index
    OUTPUT_CSV = args.output_csv


def validate_inputs():
    errors = []
    if not OUTPUT_NC or not Path(OUTPUT_NC).exists():
        errors.append(f"SUMMA output not found: {OUTPUT_NC}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_path):
    if output_path and not Path(output_path).exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)
    logger.info("Output validation passed.")


def process():
    """Parse SUMMA output NetCDF."""
    from netCDF4 import Dataset, num2date
    import csv

    ds = Dataset(OUTPUT_NC, 'r')

    # Get time
    time_var = ds.variables['time']
    times = num2date(time_var[:], time_var.units, time_var.calendar
                     if hasattr(time_var, 'calendar') else 'standard')

    n_time = len(times)
    logger.info(f"Output has {n_time} time steps from {times[0]} to {times[-1]}")

    # List available variables
    available = list(ds.variables.keys())
    logger.info(f"Available variables: {available}")

    # Extract requested variables
    data = {'time': [str(t) for t in times]}
    stats = {}

    for var_name in VARIABLES:
        if var_name not in ds.variables:
            logger.warning(f"Variable '{var_name}' not in output. Skipping.")
            continue

        var = ds.variables[var_name]
        dims = var.dimensions
        logger.info(f"  {var_name}: dims={dims}, units={getattr(var, 'units', 'unknown')}")

        if 'hru' in dims:
            if HRU_INDEX >= 0:
                values = var[:, HRU_INDEX] if len(dims) == 2 else var[:]
            else:
                values = np.mean(var[:], axis=-1)  # average across HRUs
        else:
            values = var[:]

        values = np.array(values, dtype=np.float64)

        # Handle NaN/fill values
        if hasattr(var, '_FillValue'):
            values[values == var._FillValue] = np.nan

        data[var_name] = values.tolist()

        # Compute statistics
        valid = values[~np.isnan(values)]
        stats[var_name] = {
            'mean': float(np.mean(valid)) if len(valid) > 0 else None,
            'std': float(np.std(valid)) if len(valid) > 0 else None,
            'min': float(np.min(valid)) if len(valid) > 0 else None,
            'max': float(np.max(valid)) if len(valid) > 0 else None,
            'units': getattr(var, 'units', 'unknown'),
            'n_nan': int(np.sum(np.isnan(values)))
        }

    ds.close()

    # Convert runoff units for summary
    if 'scalarTotalRunoff' in stats and stats['scalarTotalRunoff']['mean'] is not None:
        # m/s -> mm/day
        runoff_mm_day = stats['scalarTotalRunoff']['mean'] * CMFD_PRECIP_KGM2S_TO_MMDAY * 1000
        logger.info(f"  Mean runoff: {runoff_mm_day:.4f} mm/day "
                    f"({stats['scalarTotalRunoff']['mean']:.2e} m/s)")

    # Write CSV if requested
    output_path = OUTPUT_CSV or (OUTPUT_NC + '.parsed.csv')
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        headers = list(data.keys())
        writer.writerow(headers)
        for i in range(n_time):
            row = [data[h][i] if isinstance(data[h], list) else data[h]
                   for h in headers]
            writer.writerow(row)

    logger.info(f"Parsed data written to: {output_path}")

    result = {
        "status": "success",
        "n_timesteps": n_time,
        "variables_extracted": list(stats.keys()),
        "statistics": stats,
        "output_csv": output_path,
        "time_range": f"{times[0]} to {times[-1]}"
    }
    print(json.dumps(result, indent=2))

    return output_path


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
