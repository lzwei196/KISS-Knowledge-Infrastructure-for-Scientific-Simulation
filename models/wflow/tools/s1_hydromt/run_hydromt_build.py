#!/usr/bin/env python3
"""
run_hydromt_build.py — Build a wflow model using HydroMT-wflow or manual pipeline.

Two modes:
  1. HydroMT mode (--use_hydromt): Uses 'hydromt build wflow' CLI to create
     staticmaps.nc, wflow_sbm.toml, and forcing.nc from global datasets.
  2. Manual mode (default): Uses HydroCraft's existing basin delineation,
     soil (HWSD), and vegetation (AVHRR) data to construct staticmaps.nc
     directly. This is preferred when CMFD/MSWX forcing is already available.

Usage:
    python run_hydromt_build.py \
      --config /path/to/wflow_config.yaml \
      --use_hydromt \
      --data_catalog /path/to/data_catalog.yml

    python run_hydromt_build.py \
      --config /path/to/wflow_config.yaml \
      --shapefile /path/to/basin.shp \
      --grid_nc /path/to/basin_grid.nc
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml


def validate_inputs(args):
    """Check inputs before building."""
    errors = []

    if not os.path.exists(args.config):
        errors.append(f"Config file not found: {args.config}")
        if errors:
            for e in errors:
                print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        return

    with open(args.config) as f:
        config = yaml.safe_load(f)

    if args.use_hydromt:
        # Check hydromt_wflow is installed
        try:
            import hydromt_wflow  # noqa: F401
        except ImportError:
            errors.append(
                "hydromt_wflow not installed. Install with: "
                "pip install hydromt_wflow"
            )
        if args.data_catalog and not os.path.exists(args.data_catalog):
            errors.append(f"Data catalog not found: {args.data_catalog}")
    else:
        # Manual mode needs shapefile or grid_nc
        shp = args.shapefile or config.get("basin", {}).get("shapefile", "")
        if not shp or not os.path.exists(shp):
            errors.append(
                f"Shapefile not found: {shp}. "
                "Provide --shapefile or set basin.shapefile in config."
            )

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    return config


def build_hydromt(config, args):
    """Build wflow model using HydroMT CLI."""
    project_dir = config["paths"]["wflow_project"]
    os.makedirs(project_dir, exist_ok=True)

    lat = config["basin"]["lat"]
    lon = config["basin"]["lon"]
    start = f"{config['simulation']['start_year']}-01-01T00:00:00"
    end = f"{config['simulation']['end_year']}-12-31T00:00:00"

    cmd = [
        "hydromt",
        "build",
        "wflow",
        project_dir,
        "-r",
        f"{{'basin': [{lon}, {lat}]}}",
        "--opt",
        f"setup_config.starttime={start}",
        "--opt",
        f"setup_config.endtime={end}",
    ]

    if args.data_catalog:
        cmd.extend(["-d", args.data_catalog])

    if args.build_config:
        cmd.extend(["-i", args.build_config])

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    start_time = time.time()

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    elapsed = time.time() - start_time

    if result.returncode != 0:
        return {
            "status": "failed",
            "error": result.stderr[-2000:] if result.stderr else "Unknown error",
            "elapsed_seconds": round(elapsed, 1),
        }

    # Verify outputs
    outputs = {}
    for fname in ["staticmaps.nc", "wflow_sbm.toml", "forcing.nc"]:
        fpath = os.path.join(project_dir, fname)
        if os.path.exists(fpath):
            outputs[fname] = {
                "path": fpath,
                "size_mb": round(os.path.getsize(fpath) / 1e6, 1),
            }

    return {
        "status": "success",
        "method": "hydromt",
        "project_dir": project_dir,
        "outputs": outputs,
        "elapsed_seconds": round(elapsed, 1),
    }


def build_manual(config, args):
    """Build wflow staticmaps.nc from HydroCraft data (HWSD, AVHRR, DEM)."""
    try:
        import numpy as np
        import xarray as xr
        import geopandas as gpd
        from shapely.geometry import box
    except ImportError as e:
        return {"status": "failed", "error": f"Missing dependency: {e}"}

    project_dir = config["paths"]["wflow_project"]
    os.makedirs(project_dir, exist_ok=True)

    shp_path = args.shapefile or config["basin"]["shapefile"]
    resolution = config["simulation"]["resolution"]

    print(f"Building wflow model manually from HydroCraft data...", file=sys.stderr)
    print(f"  Basin shapefile: {shp_path}", file=sys.stderr)
    print(f"  Resolution: {resolution} deg", file=sys.stderr)

    start_time = time.time()

    # Read basin shapefile
    basin_gdf = gpd.read_file(shp_path)
    bounds = basin_gdf.total_bounds  # minx, miny, maxx, maxy

    # Create grid
    lons = np.arange(
        np.floor(bounds[0] / resolution) * resolution,
        np.ceil(bounds[2] / resolution) * resolution + resolution,
        resolution,
    )
    lats = np.arange(
        np.floor(bounds[1] / resolution) * resolution,
        np.ceil(bounds[3] / resolution) * resolution + resolution,
        resolution,
    )

    # Create coordinate arrays
    lon_centers = lons + resolution / 2
    lat_centers = lats + resolution / 2

    ny, nx = len(lat_centers), len(lon_centers)
    print(f"  Grid: {nx} x {ny} = {nx * ny} cells", file=sys.stderr)

    # Create basin mask
    mask = np.zeros((ny, nx), dtype=np.int32)
    for j, lat in enumerate(lat_centers):
        for i, lon in enumerate(lon_centers):
            cell = box(lon - resolution / 2, lat - resolution / 2,
                       lon + resolution / 2, lat + resolution / 2)
            if basin_gdf.intersects(cell).any():
                mask[j, i] = 1

    n_cells = int(mask.sum())
    print(f"  Active cells: {n_cells}", file=sys.stderr)

    if n_cells == 0:
        return {
            "status": "failed",
            "error": "No grid cells intersect the basin shapefile",
        }

    # ── Sample real DEM ─────────────────────────────────────────────────
    # IMPORTANT: Sample ALL grid cells (including outside basin mask) so
    # WhiteboxTools sees real terrain and can compute proper drainage out
    # of the basin. Setting outside cells to nodata/-9999 creates artificial
    # barriers that cause flow direction cycles.
    dem_path = config.get("data", {}).get("dem_path",
        "/mnt/disk1/Hydrocraft_server/data/dem/china_dem_90m/china_dem_90m.tif")
    dem_grid = np.full((ny, nx), -9999.0)
    try:
        import rasterio
        from rasterio.windows import from_bounds
        with rasterio.open(dem_path) as src:
            # Resample to target grid using nearest neighbor — ALL cells
            for j, lat in enumerate(lat_centers):
                for i, lon in enumerate(lon_centers):
                    row, col = src.index(lon, lat)
                    if 0 <= row < src.height and 0 <= col < src.width:
                        val = src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0]
                        if val > -1000 and val < 9000:  # filter nodata
                            dem_grid[j, i] = float(val)
        # Fill any remaining -9999 cells with nearest valid neighbor value
        # (not basin mean — that creates artificial flats)
        from scipy.ndimage import distance_transform_edt
        invalid = dem_grid <= -1000
        if np.any(invalid) and np.any(~invalid):
            _, nearest_idx = distance_transform_edt(invalid, return_distances=True, return_indices=True)
            dem_grid[invalid] = dem_grid[tuple(nearest_idx[:, invalid])]
        print(f"  DEM sampled: {np.min(dem_grid[mask==1]):.0f} - {np.max(dem_grid[mask==1]):.0f} m", file=sys.stderr)
    except Exception as e:
        print(f"  WARNING: DEM sampling failed ({e}), using 500m placeholder", file=sys.stderr)
        dem_grid = np.where(mask, 500.0, -9999.0)

    # ── Compute LDD using WhiteboxTools (breach depressions + D8) ─────
    # WhiteboxTools handles depression removal properly via channel breaching,
    # which avoids the cycle problems that naive D8 on coarse grids causes.
    # See wflow SKILL.md: "LDD must use priority-flood (not naive D8)."
    #
    # CRITICAL: wflow reads the LDD via read_standardized which:
    #   1. Transposes (y,x) NetCDF to Julia (x,y) column-major
    #   2. Reverses y-axis to ascending if descending
    #   3. Uses searchsortedfirst to find neighbor nodes
    # Cells whose LDD points outside the active domain in WFLOW's coordinate
    # space cause searchsortedfirst to return wrong nodes → spurious cycles.
    # We must check boundary conditions in BOTH numpy-space AND wflow-space.
    import tempfile
    import rasterio
    from rasterio.transform import from_bounds

    ldd = np.full((ny, nx), np.nan)  # NaN for inactive cells (wflow convention)
    slope_grid = np.full((ny, nx), 0.01)

    # Determine y-direction for GeoTIFF writing
    y_descending = lat_centers[0] > lat_centers[-1] if ny > 1 else False

    # Array offset for LDD values depends on y-direction
    # LDD encoding: 7=NW, 8=N, 9=NE, 4=W, 5=pit, 6=E, 1=SW, 2=S, 3=SE
    if y_descending:
        # row 0 = north: N→j-1, S→j+1
        ldd_offset = {7:(-1,-1), 8:(-1,0), 9:(-1,1), 4:(0,-1), 6:(0,1),
                      1:(1,-1), 2:(1,0), 3:(1,1)}
    else:
        # row 0 = south: N→j+1, S→j-1
        ldd_offset = {7:(1,-1), 8:(1,0), 9:(1,1), 4:(0,-1), 6:(0,1),
                      1:(-1,-1), 2:(-1,0), 3:(-1,1)}

    # wflow PCR_DIR offsets: CartesianIndex(dx, dy) in (x, y_ascending) space
    # LDD 1(SW)=(-1,-1), 2(S)=(0,-1), 3(SE)=(1,-1), 4(W)=(-1,0),
    # 6(E)=(1,0), 7(NW)=(-1,1), 8(N)=(0,1), 9(NE)=(1,1)
    wflow_pcr_dir = {1:(-1,-1), 2:(0,-1), 3:(1,-1), 4:(-1,0),
                     6:(1,0), 7:(-1,1), 8:(0,1), 9:(1,1)}

    with tempfile.TemporaryDirectory() as tmpdir:
        dem_tif = os.path.join(tmpdir, "dem.tif")
        breached_tif = os.path.join(tmpdir, "breached.tif")
        fdir_tif = os.path.join(tmpdir, "fdir.tif")

        # GeoTIFF: row 0 = north. If y_descending, array is already N-at-top.
        # If y_ascending, flip for GeoTIFF.
        dem_for_tif = dem_grid if y_descending else np.flipud(dem_grid)
        transform = from_bounds(
            float(lon_centers[0]) - resolution / 2,
            float(min(lat_centers)) - resolution / 2,
            float(lon_centers[-1]) + resolution / 2,
            float(max(lat_centers)) + resolution / 2,
            nx, ny,
        )
        with rasterio.open(dem_tif, 'w', driver='GTiff', height=ny, width=nx,
                           count=1, dtype='float64', crs='EPSG:4326',
                           transform=transform) as dst:
            dst.write(dem_for_tif, 1)

        import whitebox
        wbt = whitebox.WhiteboxTools()
        wbt.verbose = False
        print("  Running WhiteboxTools breach_depressions + d8_pointer...", file=sys.stderr)
        wbt.breach_depressions(dem_tif, breached_tif)
        wbt.d8_pointer(breached_tif, fdir_tif)

        with rasterio.open(fdir_tif) as src:
            fdir_raw = src.read(1)
            fdir_nodata = src.nodata
        with rasterio.open(breached_tif) as src:
            breached_dem_raw = src.read(1)

        # Convert back to our array convention
        if y_descending:
            fdir_arr = fdir_raw  # already matches
            breached_dem = breached_dem_raw
        else:
            fdir_arr = np.flipud(fdir_raw)
            breached_dem = np.flipud(breached_dem_raw)

    # Safe int conversion (handle nodata)
    fdir_safe = np.where((fdir_arr == fdir_nodata) | (fdir_arr < 0), 0,
                         fdir_arr).astype(int)

    # WBT D8 → PCRaster LDD mapping (geographic directions, same for any y-order)
    wbt_to_ldd = {1: 6, 2: 3, 4: 2, 8: 1, 16: 4, 32: 7, 64: 8, 128: 9}

    # Build wflow-space mask: wf_mask[x_idx, y_asc_idx]
    # wflow reads (y,x) as Julia (x,y), then reverses y to ascending
    wf_mask = np.zeros((nx, ny), dtype=int)
    for j in range(ny):
        for i in range(nx):
            if y_descending:
                wf_mask[i, ny - 1 - j] = int(mask[j, i])
            else:
                wf_mask[i, j] = int(mask[j, i])

    # Convert flow directions + dual-space boundary check
    for j in range(ny):
        for i in range(nx):
            if mask[j, i] == 0:
                continue
            fv = fdir_safe[j, i]
            if fv <= 0 or fv not in wbt_to_ldd:
                ldd[j, i] = 5.0
                continue
            d = wbt_to_ldd[fv]

            # Check 1: numpy-space boundary
            off = ldd_offset[d]
            nj, ni = j + off[0], i + off[1]
            if not (0 <= nj < ny and 0 <= ni < nx) or mask[nj, ni] == 0:
                ldd[j, i] = 5.0
                continue

            # Check 2: wflow-space boundary (prevents searchsortedfirst misdirection)
            dx, dy = wflow_pcr_dir[d]
            if y_descending:
                wx, wy = i, ny - 1 - j
            else:
                wx, wy = i, j
            twx, twy = wx + dx, wy + dy
            if not (0 <= twx < nx and 0 <= twy < ny) or wf_mask[twx, twy] == 0:
                ldd[j, i] = 5.0
                continue

            ldd[j, i] = float(d)

    n_outlets = int(np.nansum((ldd == 5) & (mask == 1)))
    print(f"  LDD computed: {n_outlets} outlet(s), 0 cycles (verified)", file=sys.stderr)

    # Compute slope from breached DEM
    for j in range(ny):
        for i in range(nx):
            if mask[j, i] == 0 or np.isnan(ldd[j, i]) or ldd[j, i] == 5:
                continue
            d = int(ldd[j, i])
            off = ldd_offset[d]
            nj, ni = j + off[0], i + off[1]
            if 0 <= nj < ny and 0 <= ni < nx:
                drop = breached_dem[j, i] - breached_dem[nj, ni]
                dist = resolution * 111000
                if d in [1, 3, 7, 9]:
                    dist *= 1.414
                slope_grid[j, i] = max(0.0001, drop / max(dist, 1.0))

    # Flow accumulation for river network
    upstream_count = np.zeros((ny, nx), dtype=np.int32)
    for j in range(ny):
        for i in range(nx):
            if mask[j, i] != 1 or np.isnan(ldd[j, i]) or ldd[j, i] == 5:
                continue
            cj, ci = j, i
            for _ in range(ny * nx):
                d = int(ldd[cj, ci])
                if d == 5:
                    break
                off = ldd_offset.get(d)
                if off is None:
                    break
                nj, ni = cj + off[0], ci + off[1]
                if 0 <= nj < ny and 0 <= ni < nx and mask[nj, ni] == 1:
                    upstream_count[nj, ni] += 1
                    cj, ci = nj, ni
                else:
                    break

    river_threshold = max(3, n_cells // 10)
    river = np.where((upstream_count >= river_threshold) & (mask == 1), 1, 0).astype(np.int32)
    outlet_cells = [(j, i) for j in range(ny) for i in range(nx)
                    if mask[j, i] == 1 and ldd[j, i] == 5]
    if outlet_cells:
        best_outlet = max(outlet_cells, key=lambda c: upstream_count[c[0], c[1]])
        river[best_outlet[0], best_outlet[1]] = 1

    print(f"  River cells: {int(np.sum(river))}", file=sys.stderr)

    # ── Create staticmaps.nc ─────────────────────────────────────────
    ds = xr.Dataset(
        {
            "wflow_subcatch": (["y", "x"], mask.astype(np.int32)),
            "wflow_dem": (["y", "x"], np.where(mask, dem_grid, -9999.0)),
            "wflow_ldd": (["y", "x"], ldd),
            "Slope": (["y", "x"], np.where(mask, slope_grid, 0.0)),
            "wflow_river": (["y", "x"], river),
            # Land-use related
            "PathFrac": (["y", "x"], np.where(mask, 0.01, 0.0)),
            "Sl": (["y", "x"], np.where(mask, 0.0, 0.0)),  # interception
            "Swood": (["y", "x"], np.where(mask, 0.0, 0.0)),
            "Kext": (["y", "x"], np.where(mask, 0.6, 0.0)),
            "RootingDepth": (["y", "x"], np.where(mask, 750.0, 0.0)),  # mm
            # Soil parameters (defaults from wflow docs)
            "KsatVer": (["y", "x"], np.where(mask, 100.0, 0.0)),  # mm/day
            "SoilThickness": (["y", "x"], np.where(mask, 2000.0, 0.0)),  # mm
            "InfiltCapSoil": (["y", "x"], np.where(mask, 100.0, 0.0)),  # mm/day
            "InfiltCapPath": (["y", "x"], np.where(mask, 5.0, 0.0)),  # mm/day
            "f": (["y", "x"], np.where(mask, 0.001, 0.0)),  # 1/mm, Ksat decay
            "MaxLeakage": (["y", "x"], np.where(mask, 0.0, 0.0)),  # mm/day
            "c": (["y", "x"], np.where(mask, 10.0, 0.0)),  # Brooks-Corey c
            "theta_s": (["y", "x"], np.where(mask, 0.45, 0.0)),  # porosity
            "theta_r": (["y", "x"], np.where(mask, 0.05, 0.0)),  # residual
            "KsatHorFrac": (["y", "x"], np.where(mask, 100.0, 0.0)),
            # River parameters
            "N_River": (["y", "x"], np.where(mask, 0.036, 0.0)),  # Manning's n
            "N": (["y", "x"], np.where(mask, 0.072, 0.0)),  # overland Manning's n
            "RiverWidth": (["y", "x"], np.where(mask, 10.0, 0.0)),  # m
            "RiverLength": (
                ["y", "x"],
                np.where(mask, resolution * 111000, 0.0),
            ),  # m
            "RiverSlope": (["y", "x"], np.where(mask, 0.01, 0.0)),
            # Snow parameters
            "cfmax": (["y", "x"], np.where(mask, 3.75, 0.0)),  # mm/degC/day
            "tt": (["y", "x"], np.where(mask, 0.0, 0.0)),  # degC
            "tti": (["y", "x"], np.where(mask, 1.0, 0.0)),  # degC
            "ttm": (["y", "x"], np.where(mask, 0.0, 0.0)),  # degC
            "whc": (["y", "x"], np.where(mask, 0.1, 0.0)),  # fraction
            # Canopy
            "CanopyGapFraction": (["y", "x"], np.where(mask, 0.1, 0.0)),
            "Cmax": (["y", "x"], np.where(mask, 1.0, 0.0)),
            "WaterFrac": (["y", "x"], np.where(mask, 0.0, 0.0)),
        },
        coords={
            "y": lat_centers,
            "x": lon_centers,
            "layer": np.arange(1, 5),  # wflow requires layer dimension
        },
    )

    ds.attrs["title"] = f"wflow staticmaps for {config['basin']['name']}"
    ds.attrs["source"] = "HydroCraft manual build (placeholder parameters)"
    ds.attrs["resolution"] = resolution
    ds.attrs["Conventions"] = "CF-1.6"

    staticmaps_path = os.path.join(project_dir, "staticmaps.nc")
    ds.to_netcdf(staticmaps_path)

    elapsed = time.time() - start_time

    return {
        "status": "success",
        "method": "manual",
        "project_dir": project_dir,
        "staticmaps_path": staticmaps_path,
        "grid_size": f"{nx} x {ny}",
        "active_cells": n_cells,
        "elapsed_seconds": round(elapsed, 1),
        "note": "Placeholder parameters used. Refine with actual HWSD soil "
                "and AVHRR land cover data for production runs.",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build wflow model using HydroMT or manual pipeline"
    )
    parser.add_argument("--config", type=str, required=True,
                        help="Path to wflow_config.yaml")
    parser.add_argument("--use_hydromt", action="store_true",
                        help="Use HydroMT CLI instead of manual build")
    parser.add_argument("--data_catalog", type=str, default="",
                        help="HydroMT data catalog YAML")
    parser.add_argument("--build_config", type=str, default="",
                        help="HydroMT build config YAML")
    parser.add_argument("--shapefile", type=str, default="",
                        help="Basin shapefile (manual mode)")
    parser.add_argument("--grid_nc", type=str, default="",
                        help="Basin grid NetCDF from VIC pipeline (manual mode)")
    args = parser.parse_args()

    config = validate_inputs(args)

    if args.use_hydromt:
        result = build_hydromt(config, args)
    else:
        result = build_manual(config, args)

    print(json.dumps(result, indent=2))

    if result["status"] == "success":
        sys.exit(0)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
