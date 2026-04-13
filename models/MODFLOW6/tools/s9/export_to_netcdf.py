#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      export_to_netcdf
Stage:        s9_postprocessing
Description:  Export MODFLOW 6 heads and fluxes to CF-compliant NetCDF
              for coupling with HydroCraft (VIC recharge feedback,
              CaMa-Flood baseflow, routing).

Inputs:
  - HDS_PATH: binary head file
  - CBC_PATH: cell budget file
  - MODEL_PATH: model workspace for grid info
  - OUTPUT_NC: output NetCDF path

Outputs:
  - NetCDF with head, water_table, drain_flux variables

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

HDS_PATH = ""
CBC_PATH = ""
MODEL_PATH = ""
OUTPUT_NC = ""

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not HDS_PATH or not Path(HDS_PATH).exists():
        errors.append(f"Head file not found: {HDS_PATH}")
    if not OUTPUT_NC:
        errors.append("OUTPUT_NC is not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy.utils.binaryfile as bf

    try:
        import netCDF4
        use_netcdf4 = True
    except ImportError:
        try:
            import xarray as xr
            use_netcdf4 = False
        except ImportError:
            raise ImportError("Neither netCDF4 nor xarray is installed. pip install netCDF4")

    # Read heads
    hds = bf.HeadFile(HDS_PATH)
    times = hds.get_times()
    kstpkper_list = hds.get_kstpkper()

    # Get dimensions from first record
    first_heads = hds.get_data(kstpkper=kstpkper_list[0])
    nlay, nrow, ncol = first_heads.shape
    ntime = len(times)

    logger.info(f"Exporting: {ntime} timesteps x {nlay} layers x {nrow} rows x {ncol} cols")

    # Collect all heads
    all_heads = np.zeros((ntime, nlay, nrow, ncol), dtype=np.float32)
    for t_idx, ksp in enumerate(kstpkper_list):
        h = hds.get_data(kstpkper=ksp)
        # Mask HDRY
        h = np.where(h > 0.9e30, np.nan, h)
        all_heads[t_idx] = h.astype(np.float32)

    # Compute water table (head in top active layer)
    water_table = np.full((ntime, nrow, ncol), np.nan, dtype=np.float32)
    for t_idx in range(ntime):
        for i in range(nrow):
            for j in range(ncol):
                for k in range(nlay):
                    if not np.isnan(all_heads[t_idx, k, i, j]):
                        water_table[t_idx, i, j] = all_heads[t_idx, k, i, j]
                        break

    # Read drain budget if available
    drain_flux = None
    if CBC_PATH and Path(CBC_PATH).exists():
        try:
            cbb = bf.CellBudgetFile(CBC_PATH)
            record_names = [r.strip().decode() if isinstance(r, bytes)
                           else r.strip() for r in cbb.get_unique_record_names()]
            if "DRN" in record_names:
                drain_flux = np.zeros((ntime, nrow, ncol), dtype=np.float32)
                for t_idx, ksp in enumerate(kstpkper_list):
                    try:
                        drn_data = cbb.get_data(kstpkper=ksp, text="DRN")
                        for d in drn_data:
                            if isinstance(d, np.recarray):
                                # Distribute to grid
                                for rec in d:
                                    node = int(rec["node"]) - 1
                                    k = node // (nrow * ncol)
                                    ij = node % (nrow * ncol)
                                    i = ij // ncol
                                    j = ij % ncol
                                    drain_flux[t_idx, i, j] += float(rec["q"])
                    except Exception:
                        pass
                logger.info("Drain flux extracted")
        except Exception as e:
            logger.warning(f"Could not read budget file: {e}")

    # Write NetCDF
    output_path = Path(OUTPUT_NC)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if use_netcdf4:
        ds = netCDF4.Dataset(str(output_path), "w", format="NETCDF4")

        # Dimensions
        ds.createDimension("time", ntime)
        ds.createDimension("layer", nlay)
        ds.createDimension("row", nrow)
        ds.createDimension("col", ncol)

        # Time variable
        time_var = ds.createVariable("time", "f8", ("time",))
        time_var.units = "days since simulation start"
        time_var[:] = np.array(times)

        # Head variable
        head_var = ds.createVariable("head", "f4", ("time", "layer", "row", "col"),
                                     fill_value=np.nan)
        head_var.units = "meters"
        head_var.long_name = "groundwater head"
        head_var[:] = all_heads

        # Water table
        wt_var = ds.createVariable("water_table", "f4", ("time", "row", "col"),
                                    fill_value=np.nan)
        wt_var.units = "meters"
        wt_var.long_name = "water table elevation"
        wt_var[:] = water_table

        # Drain flux
        if drain_flux is not None:
            drn_var = ds.createVariable("drain_flux", "f4", ("time", "row", "col"),
                                         fill_value=np.nan)
            drn_var.units = "m3/day"
            drn_var.long_name = "drain discharge (negative = outflow)"
            drn_var[:] = drain_flux

        # Global attributes
        ds.title = "MODFLOW 6 simulation results"
        ds.source = "HydroCraft MODFLOW 6 knowledge infrastructure"
        ds.Conventions = "CF-1.8"

        ds.close()
    else:
        # Use xarray
        import xarray as xr
        data_vars = {
            "head": (["time", "layer", "row", "col"], all_heads,
                     {"units": "meters", "long_name": "groundwater head"}),
            "water_table": (["time", "row", "col"], water_table,
                            {"units": "meters", "long_name": "water table elevation"}),
        }
        if drain_flux is not None:
            data_vars["drain_flux"] = (
                ["time", "row", "col"], drain_flux,
                {"units": "m3/day", "long_name": "drain discharge"}
            )

        ds = xr.Dataset(
            data_vars,
            coords={"time": times},
            attrs={"title": "MODFLOW 6 results", "Conventions": "CF-1.8"},
        )
        ds.to_netcdf(str(output_path))

    logger.info(f"NetCDF exported: {output_path}")
    return str(output_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)
    if Path(output_path).stat().st_size < 1000:
        logger.warning("NetCDF file is very small — may be empty")
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    if len(sys.argv) > 1:
        HDS_PATH = sys.argv[1]
    if len(sys.argv) > 2:
        CBC_PATH = sys.argv[2]
    if len(sys.argv) > 3:
        OUTPUT_NC = sys.argv[3]
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"output": output_path}))
    sys.exit(0)
