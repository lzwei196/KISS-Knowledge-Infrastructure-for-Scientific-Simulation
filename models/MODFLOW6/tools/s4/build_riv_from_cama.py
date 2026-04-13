"""
Build MODFLOW RIV package from CaMa-Flood river network.

Identifies river cells in the MODFLOW grid by intersecting with the
CaMa-Flood river network, and extracts river stage from CaMa output.

Usage:
    python build_riv_from_cama.py \
        --grid_nc outputs/<basin>/vic_temp/grid/basin_grid.nc \
        --cama_map model/cmf_v420_pkg/map/<basin>_15min \
        --cama_out model/cmf_v420_pkg/out/<run_name> \
        --layers_dir outputs/<basin>/modflow/layers \
        --output_dir outputs/<basin>/modflow/riv \
        --year 2005
"""

import argparse
import json
import logging
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_riv")


def main():
    parser = argparse.ArgumentParser(description="Build MODFLOW RIV from CaMa-Flood")
    parser.add_argument("--grid_nc", type=Path, required=True)
    parser.add_argument("--cama_out", type=str, default=None,
                        help="CaMa output directory with o_sfcelv*.nc files")
    parser.add_argument("--layers_dir", type=Path, required=True,
                        help="Directory with top.npy, botm.npy from build_layers")
    parser.add_argument("--output_dir", type=Path, required=True)
    parser.add_argument("--year", type=int, default=2005)
    parser.add_argument("--riv_conductance", type=float, default=100.0,
                        help="River bed conductance (m²/day per m of river)")
    parser.add_argument("--riv_depth", type=float, default=2.0,
                        help="Assumed river bed depth below stage (m)")
    parser.add_argument("--threshold_area_km2", type=float, default=500.0,
                        help="Minimum upstream area to identify river cells")
    args = parser.parse_args()

    import xarray as xr

    # Read MODFLOW grid
    ds = xr.open_dataset(args.grid_nc)
    lat_key = 'y' if 'y' in ds else 'lat'
    lon_key = 'x' if 'x' in ds else 'lon'
    lats = ds[lat_key].values
    lons = ds[lon_key].values
    ds.close()
    nrow, ncol = len(lats), len(lons)

    # Read layer geometry
    top = np.load(args.layers_dir / "top.npy")
    botm = np.load(args.layers_dir / "botm.npy")
    idomain = np.load(args.layers_dir / "idomain.npy")

    # ── Identify river cells ──
    # Strategy: cells where DEM is in the lower 20th percentile of the basin
    # (rivers flow through low-elevation areas)
    # More sophisticated: use CaMa-Flood outflw to find cells with significant discharge
    riv_cells = []

    if args.cama_out and Path(args.cama_out).exists():
        # Use CaMa-Flood output to identify river cells
        logger.info("Reading CaMa-Flood output to identify river cells...")
        sfcelv_file = Path(args.cama_out) / f"o_sfcelv{args.year}.nc"
        outflw_file = Path(args.cama_out) / f"o_outflw{args.year}.nc"

        if outflw_file.exists():
            ds_cama = xr.open_dataset(outflw_file)
            mean_Q = ds_cama['outflw'].mean(dim='time').values
            cama_lats = ds_cama['lat'].values
            cama_lons = ds_cama['lon'].values
            ds_cama.close()

            # Get river stage if available
            stage_data = None
            if sfcelv_file.exists():
                ds_stage = xr.open_dataset(sfcelv_file)
                stage_data = ds_stage['sfcelv'].mean(dim='time').values
                ds_stage.close()

            # Map CaMa river cells to MODFLOW grid
            for i, lat in enumerate(lats):
                for j, lon in enumerate(lons):
                    # Find nearest CaMa cell
                    ci = np.argmin(np.abs(cama_lats - lat))
                    cj = np.argmin(np.abs(cama_lons - lon))

                    # Skip inactive cells
                    if idomain[0, i, j] <= 0:
                        continue
                    q = mean_Q[ci, cj]
                    if q > 1.0:  # cells with > 1 m³/s mean discharge = river
                        stage = float(stage_data[ci, cj]) if stage_data is not None else top[i, j] - 1.0
                        if stage < -9000 or np.isnan(stage):
                            stage = top[i, j] - 1.0  # fallback
                        # Ensure stage is below ground surface
                        stage = min(stage, top[i, j] - 0.5)
                        rbot = stage - args.riv_depth
                        # CRITICAL: rbot must be above layer bottom (MODFLOW constraint)
                        cell_bot = float(botm[0, i, j])
                        rbot = max(rbot, cell_bot + 0.5)
                        # Ensure stage > rbot
                        if stage <= rbot:
                            stage = rbot + 0.5
                        cond = args.riv_conductance
                        riv_cells.append({
                            "layer": 0, "row": i, "col": j,
                            "stage": float(stage),
                            "conductance": float(cond),
                            "rbot": float(rbot),
                            "mean_Q_m3s": float(q),
                        })

            logger.info("  Found %d river cells from CaMa-Flood (Q > 1 m³/s)", len(riv_cells))
        else:
            logger.warning("  CaMa outflw file not found: %s", outflw_file)

    if not riv_cells:
        # Fallback: use DEM low points as river proxy
        logger.info("No CaMa data — using DEM low-point heuristic for river cells")
        threshold = np.nanpercentile(top, 15)  # lowest 15% = potential river cells
        for i in range(nrow):
            for j in range(ncol):
                if idomain[0, i, j] <= 0:
                    continue
                if top[i, j] <= threshold:
                    stage = top[i, j] - 0.5
                    rbot = stage - args.riv_depth
                    riv_cells.append({
                        "layer": 0, "row": i, "col": j,
                        "stage": float(stage),
                        "conductance": float(args.riv_conductance),
                        "rbot": float(rbot),
                        "mean_Q_m3s": 0.0,
                    })
        logger.info("  Assigned %d river cells from DEM (lowest 15%%)", len(riv_cells))

    # Save RIV stress period data
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # FloPy-compatible list format
    riv_spd = []
    for rc in riv_cells:
        riv_spd.append([
            (rc["layer"], rc["row"], rc["col"]),
            rc["stage"], rc["conductance"], rc["rbot"]
        ])

    np.save(args.output_dir / "riv_spd.npy", np.array(riv_spd, dtype=object), allow_pickle=True)

    # Also save as JSON for inspection
    summary = {
        "n_riv_cells": len(riv_cells),
        "source": "CaMa-Flood" if args.cama_out else "DEM_heuristic",
        "conductance_m2day": args.riv_conductance,
        "riv_depth_m": args.riv_depth,
        "cells": riv_cells[:10],  # first 10 for inspection
    }
    with open(args.output_dir / "riv_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    logger.info("RIV data saved to %s (%d cells)", args.output_dir, len(riv_cells))
    print(json.dumps({"n_riv_cells": len(riv_cells), "source": summary["source"]}, indent=2))


if __name__ == "__main__":
    main()
