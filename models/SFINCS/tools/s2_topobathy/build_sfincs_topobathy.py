#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_sfincs_topobathy
Stage:        s2_topobathy
Description:  Build SFINCS topography/bathymetry from DEM. Generates sfincs.dep (bed level)
              and sfincs.msk (active cell mask). Optionally builds subgrid tables.

Inputs:
  --grid_info:    Path to grid_info.json from s1_domain
  --dem_path:     Path to DEM raster (GeoTIFF). Auto-selects China DEM 90m or Copernicus GLO-30.
  --shp_path:     Path to basin shapefile (for masking active cells)
  --output_dir:   Output directory
  --nodata_fill:  Value for cells outside DEM coverage (default: -9999)

Outputs:
  - sfincs.dep:   Bed level / topography file (binary float32, row-major)
  - sfincs.msk:   Active cell mask (binary uint8). SFINCS's OWN convention, read verbatim
                  from the solver binary (`strings sfincs`):
                      inactive=0, active=1, normal_boundary=2, outflow_boundary=3, wavemaker=4
                  2 = water-level ("normal") boundary — needs bnd/bzs, else SFINCS prints
                      "Setting water level at 0.0 m at mask boundary cells" and holds zs=0.
                  3 = OUTFLOW boundary — absorbing/Neumann, needs NO extra file. This is the
                      correct open boundary for an INLAND domain whose bed is far above 0 m.
  - sfincs.ind:   Index file for subgrid (binary int32)
  - topobathy_summary.json: Statistics

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import logging
import argparse
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Default DEM paths ---
CHINA_DEM = "KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif"

# BedMachine is the ONLY source that carries fjord/shelf BATHYMETRY together with
# land topography over the ice sheets. `bed` = bedrock/seafloor altitude in metres
# referenced to the EIGEN-6C4 geoid (~mean sea level) — the same datum SFINCS
# assumes for zsini = 0.0, so it can feed sfincs.dep directly (dt_004 satisfied).
#
# TRAP (found 2026-08-02, Kangerlussuaq run): these NSIDC files CANNOT be opened by
# the HydroCraft venv's netCDF4 1.7.4 / HDF5 1.14.6 stack — every open raises
# "OSError [Errno -101] NetCDF: HDF error". System netCDF (HDF5 1.10) and GDAL read
# them fine. ALWAYS reach BedMachine through the GDAL/rasterio NETCDF subdataset
# connection string, never through xarray/netCDF4 in this venv.
BEDMACHINE_GREENLAND = ("KISSPATH_OBS/ice_sheets/bedmachine/"
                        "BedMachineGreenland-v6.nc")
BEDMACHINE_ANTARCTICA = ("KISSPATH_OBS/ice_sheets/bedmachine/"
                         "NSIDC-0756_BedMachineAntarctica_19700101-20191001_V04.1.nc")


def bedmachine_subdataset(nc_path, variable="bed"):
    """GDAL connection string for a BedMachine variable (readable by rasterio)."""
    return f'NETCDF:"{nc_path}":{variable}'


def read_binary_map(topobathy_dir, nmax, mmax):
    """Re-expand the compressed SFINCS binary maps into full NORTH-UP (nmax, mmax) grids.

    Inverse of the writer below (dt_v023). Returns (dep, msk) with NaN / 0 outside the
    active domain. Downstream KI tools (source snapping, gauge placement, plotting) should
    call this rather than np.fromfile(...).reshape(...), which silently mis-shapes the
    compressed files.

    The .npy aux files are only a cache: a stale pair left behind by a PREVIOUS domain in
    the same directory would hand the caller a wrong-shaped grid — exactly the silent
    mis-shaping this function exists to prevent — so their shape is checked against the
    requested (nmax, mmax) and a mismatch falls through to the compressed files."""
    d = Path(topobathy_dir)
    aux_dep, aux_msk = d / "grid_dep_northup.npy", d / "grid_msk_northup.npy"
    if aux_dep.exists() and aux_msk.exists():
        dep_a, msk_a = np.load(aux_dep), np.load(aux_msk)
        if dep_a.shape == (nmax, mmax) and msk_a.shape == (nmax, mmax):
            return dep_a, msk_a
        logger.warning(
            "Ignoring STALE north-up cache in %s: grid_dep_northup.npy is %s and "
            "grid_msk_northup.npy is %s, but (nmax, mmax) = (%d, %d) was requested. "
            "Re-expanding from sfincs.ind/.dep/.msk instead.",
            d, dep_a.shape, msk_a.shape, nmax, mmax)
    ind = np.fromfile(d / "sfincs.ind", dtype=np.int32)
    if ind.size < 1:
        raise ValueError(f"{d / 'sfincs.ind'} is empty — cannot re-expand the binary maps")
    n_active, idx = int(ind[0]), ind[1:]
    if len(idx) != n_active:
        raise ValueError(f"{d / 'sfincs.ind'} header says {n_active} active cells but "
                         f"carries {len(idx)} indices")
    if idx.size and (int(idx.min()) < 1 or int(idx.max()) > nmax * mmax):
        raise ValueError(
            f"{d / 'sfincs.ind'} indexes cell {int(idx.max())} of a grid with only "
            f"{nmax * mmax} cells (nmax={nmax}, mmax={mmax}) — these binary maps were "
            "built for a DIFFERENT domain than the grid_info.json being used")
    dep_c = np.fromfile(d / "sfincs.dep", dtype=np.float32)[:n_active]
    msk_c = np.fromfile(d / "sfincs.msk", dtype=np.uint8)[:n_active]
    dep = np.full(nmax * mmax, np.nan, dtype=np.float32)
    msk = np.zeros(nmax * mmax, dtype=np.uint8)
    dep[idx - 1] = dep_c
    msk[idx - 1] = msk_c
    return (dep.reshape((nmax, mmax), order="F")[::-1, :],
            msk.reshape((nmax, mmax), order="F")[::-1, :])


def _is_gdal_connection(p):
    """True for GDAL connection strings such as NETCDF:"file.nc":bed."""
    return isinstance(p, str) and (":" in p) and p.split(":", 1)[0].upper() in (
        "NETCDF", "HDF5", "HDF4_EOS", "VRT", "GTIFF"
    )


def validate_inputs(args):
    errors = []
    if not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if args.dem_path and not _is_gdal_connection(args.dem_path) \
            and not Path(args.dem_path).exists():
        errors.append(f"DEM not found: {args.dem_path}")
    if args.shp_path and not Path(args.shp_path).exists():
        errors.append(f"Shapefile not found: {args.shp_path}")
    if not args.output_dir:
        errors.append("--output_dir is required")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def auto_select_dem(center_lon, center_lat):
    """Auto-select DEM based on location."""
    # China bounding box (rough)
    if 73 <= center_lon <= 135 and 18 <= center_lat <= 54:
        if Path(CHINA_DEM).exists():
            logger.info("Auto-selected China DEM 90m")
            return CHINA_DEM
    # Greenland — BedMachine v6 (150 m) is the only source with fjord bathymetry
    if -75 <= center_lon <= -10 and 58 <= center_lat <= 84:
        if Path(BEDMACHINE_GREENLAND).exists():
            logger.info("Auto-selected BedMachine Greenland v6 'bed' (150m, EPSG:3413, geoid datum)")
            return bedmachine_subdataset(BEDMACHINE_GREENLAND, "bed")
    # Antarctica — BedMachine v4.1 (500 m)
    if center_lat <= -60:
        if Path(BEDMACHINE_ANTARCTICA).exists():
            logger.info("Auto-selected BedMachine Antarctica v4.1 'bed' (500m, EPSG:3031, geoid datum)")
            return bedmachine_subdataset(BEDMACHINE_ANTARCTICA, "bed")
    logger.info("Location outside China or China DEM unavailable — need Copernicus GLO-30 or user DEM")
    return None


def process(args):
    import rasterio
    from rasterio.warp import reproject, Resampling, calculate_default_transform
    from rasterio.mask import mask as rio_mask
    from pyproj import CRS
    import geopandas as gpd

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Load grid info ---
    with open(args.grid_info) as f:
        grid = json.load(f)

    x0 = grid["x0"]
    y0 = grid["y0"]
    dx = grid["dx"]
    dy = grid["dy"]
    mmax = grid["mmax"]
    nmax = grid["nmax"]
    epsg = grid["epsg"]
    target_crs = CRS.from_epsg(epsg)

    logger.info(f"Grid: {mmax}x{nmax}, dx={dx}m, origin=({x0},{y0}), EPSG:{epsg}")

    # --- Select DEM ---
    dem_path = args.dem_path
    if not dem_path:
        dem_path = auto_select_dem(grid.get("center_lon", 0), grid.get("center_lat", 0))
    if not dem_path or (not _is_gdal_connection(dem_path) and not Path(dem_path).exists()):
        logger.error("No DEM available. Provide --dem_path or ensure China DEM exists.")
        sys.exit(2)

    # --- Resample DEM to SFINCS grid ---
    logger.info(f"Reading DEM: {dem_path}")
    with rasterio.open(dem_path) as src:
        # Define target transform
        from rasterio.transform import from_origin
        # SFINCS uses top-left origin convention for raster output
        # But grid y0 is bottom-left. Need y0 + nmax*dy for top
        y_top = y0 + nmax * dy
        target_transform = from_origin(x0, y_top, dx, dy)

        # Reproject DEM to target grid
        dem_data = np.zeros((nmax, mmax), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=dem_data,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=target_transform,
            dst_crs=target_crs,
            resampling=Resampling.bilinear,
            dst_nodata=args.nodata_fill,
        )

    logger.info(f"DEM resampled to grid. Shape: {dem_data.shape}")
    logger.info(f"Elevation range: {np.nanmin(dem_data[dem_data > -9000]):.1f} to "
                f"{np.nanmax(dem_data[dem_data > -9000]):.1f} m")

    # --- Build mask ---
    # SFINCS mask convention (verbatim from the solver binary, dt_v021):
    #   inactive=0, active=1, normal_boundary=2, outflow_boundary=3, wavemaker=4
    # Interior cells MUST be 1. 2 is a WATER-LEVEL boundary (held at zs=0 m unless a
    # bnd/bzs pair is supplied); 3 is the ABSORBING OUTFLOW boundary.
    msk = np.zeros((nmax, mmax), dtype=np.uint8)

    if args.shp_path:
        gdf = gpd.read_file(args.shp_path).to_crs(f"EPSG:{epsg}")
        # Rasterize shapefile to grid
        from rasterio.features import rasterize
        shapes = [(geom, 1) for geom in gdf.geometry]
        basin_mask = rasterize(
            shapes,
            out_shape=(nmax, mmax),
            transform=target_transform,
            fill=0,
            dtype=np.uint8,
        )
        # Active cells inside basin = 1 (NOT 3)
        msk[basin_mask == 1] = 1
    else:
        # All cells with valid DEM data are active
        msk[dem_data > -9000] = 1

    # --- Optional: deactivate deep open water (ocean / fjord interior) ---
    # SFINCS is a flood model, not an ocean model. Carrying 100-600 m of standing
    # water inside the active domain (a) forces a tiny internal CFL timestep and
    # (b) contributes nothing to the land inundation being simulated. Cutting the
    # deep water out moves the mask=2 outflow ring onto the SHORELINE, which is
    # exactly where a coastal domain wants its open boundary.
    if args.min_elev is not None:
        deep = (msk > 0) & (dem_data < args.min_elev)
        n_deep = int(np.sum(deep))
        msk[deep] = 0
        logger.info(f"min_elev={args.min_elev} m: deactivated {n_deep} deep-water cells")

    # --- Optional: deactivate high ground (valley-floor domain) ---
    # A river-reach domain drawn as a lat/lon box in mountainous terrain is mostly
    # hillside that can never flood, so cutting it out can reduce the active-cell count —
    # and therefore the runtime — by 3-4x.
    #
    # WHEN THIS IS PHYSICALLY FREE: only under RIVER-ONLY forcing (src/dis and/or
    # bnd/bzs) with no precipitation. SFINCS integrates only the cells listed in
    # sfincs.ind, so under rainfall/pluvial forcing (precipfile / netamprfile) the rain
    # falling on every deactivated cell is DISCARDED and the hillslope runoff it would
    # have delivered to the valley floor never arrives — the water balance changes and
    # the flood volume is biased low. Do NOT combine --max_elev with precipitation
    # forcing unless the hillslope contribution enters the domain some other way (e.g.
    # as a discharge source derived from an offline rainfall-runoff model).
    if args.max_elev is not None:
        high = (msk > 0) & (dem_data > args.max_elev)
        msk[high] = 0
        logger.info(f"max_elev={args.max_elev} m: deactivated {int(np.sum(high))} upland cells")

    # Set boundary cells (edges of active domain) to the open-boundary value
    active = (msk == 1)
    # Find edge cells using convolution
    from scipy.ndimage import binary_erosion
    interior = binary_erosion(active, structure=np.ones((3, 3)))
    edge = active & ~interior

    # dt_v021: msk=2 is SFINCS's WATER-LEVEL boundary, not its outflow boundary. With no
    # bnd/bzs pair it is held at zs = 0.0 m (the solver even says so: "Setting water level
    # at 0.0 m at mask boundary cells"), so on an edge cell whose bed sits at 300 m it
    # creates a 300 m head gradient and silently drains the whole domain to hmax=0 — the
    # symptom recorded as dt_v005/dt_v019. The open boundary that does NOT impose a datum
    # is msk=3 (outflow / absorbing), which is now the default here.
    #   --outflow_value 3 : absorbing outflow, correct for INLAND river reaches (default)
    #   --outflow_value 2 : water-level boundary, only with a bnd/bzs pair, or coastal zs=0
    #
    # WHERE the open boundary is allowed to sit. `edge` is the perimeter of the ACTIVE
    # mask, which is NOT the same thing as the border of the domain rectangle: as soon as
    # cells are deactivated inside the rectangle (--max_elev), the active area grows an
    # INTERIOR perimeter that runs along the valley walls. Opening that contour would let
    # flood water drain sideways into the hillside and vanish, so:
    #   * --outflow_edges n/s/e/w restricts the open boundary to the named sides of the
    #     DOMAIN rectangle — an interior mask edge against a hillside is never an outlet;
    #   * --outflow_edges all (the default) opens the whole mask perimeter, which is only
    #     meaningful when that perimeter IS the domain border or a real shoreline. When
    #     --max_elev has carved uplands out of the domain, 'all' is therefore intersected
    #     with the domain rectangle border below.
    ov = int(args.outflow_value)
    on_domain_border = np.zeros_like(edge)
    # row 0 of the raster is the NORTH edge (target_transform uses a top-left origin)
    on_domain_border[0, :] = True
    on_domain_border[-1, :] = True
    on_domain_border[:, 0] = True
    on_domain_border[:, -1] = True

    edge_ok = edge
    if args.outflow_edges and args.outflow_edges.lower() != "all":
        sides = set(s.strip().lower() for s in args.outflow_edges.split(",") if s.strip())
        on_domain_edge = np.zeros_like(edge)
        if "n" in sides:
            on_domain_edge[0, :] = True
        if "s" in sides:
            on_domain_edge[-1, :] = True
        if "w" in sides:
            on_domain_edge[:, 0] = True
        if "e" in sides:
            on_domain_edge[:, -1] = True
        edge_ok = edge & on_domain_edge
        logger.info(f"outflow_edges={sides}: {int(np.sum(edge_ok))} of {int(np.sum(edge))} "
                    "mask-edge cells are on an eligible domain side")
    elif args.max_elev is not None:
        edge_ok = edge & on_domain_border
        logger.info(
            "--max_elev is set with --outflow_edges=all: the open boundary is restricted "
            "to the %d of %d mask-edge cells that lie on the DOMAIN rectangle border. The "
            "remaining perimeter is the interior contour against the deactivated uplands; "
            "opening it would drain the valley sideways into the hillside. Pass explicit "
            "--outflow_edges n/s/e/w to open only the downstream end.",
            int(np.sum(edge_ok)), int(np.sum(edge)))

    if args.outflow_max_elev is not None:
        outflow = edge_ok & (dem_data <= args.outflow_max_elev)
        closed_edge = edge & ~outflow
        msk[outflow] = ov
        logger.info(
            f"outflow_max_elev={args.outflow_max_elev} m: {int(np.sum(outflow))} edge cells "
            f"set to open boundary ({ov}); {int(np.sum(closed_edge))} edge cells kept closed (1)"
        )
    else:
        msk[edge_ok] = ov
        edge_elev = dem_data[edge_ok]
        if ov == 2 and edge_elev.size and float(np.min(edge_elev)) > 10.0:
            logger.warning(
                "dt_v021: ALL edge cells set to mask=2 but the lowest edge cell is at "
                f"{float(np.min(edge_elev)):.1f} m. mask=2 is a WATER-LEVEL boundary held at "
                "zs=0.0 m, so this domain will drain instantly and report hmax=0. Use "
                "--outflow_value 3 (absorbing outflow) for an inland domain."
            )

    if int(np.sum(msk == ov)) == 0 and ov in (2, 3):
        logger.warning("No open-boundary cells were created — water can only leave this "
                       "domain by infiltration. Check --outflow_edges/--outflow_max_elev.")

    active_count = int(np.sum(msk > 0))
    outflow_count = int(np.sum(msk == ov))
    logger.info(f"Active cells: {active_count}, Outflow boundary: {outflow_count}")

    if active_count == 0:
        logger.error("No active cells! Check shapefile alignment with DEM and CRS.")
        sys.exit(2)

    # --- Replace nodata with reasonable value in inactive cells ---
    dem_data[msk == 0] = args.nodata_fill

    # --- Write the SFINCS v2 binary maps (dt_v023 — THE format bug) ---
    # Proven against the solver on 2026-08-05 by reading sfincs_map.nc `zb` back and
    # matching it byte-for-byte to the file that produced it:
    #   * sfincs.ind : int32 n_active, then n_active 1-based flat indices in FORTRAN
    #                  order (n fastest) over an (nmax, mmax) grid whose row 0 is the
    #                  SOUTH edge (y0 is the LOWER-left origin).
    #   * sfincs.dep : n_active float32 — ONLY the active cells, in index order.
    #   * sfincs.msk : n_active uint8   — ONLY the active cells, in index order.
    # The old code wrote FULL nmax*mmax grids in C order with row 0 = NORTH. SFINCS then
    # read the first n_active values of each file as if they were the compressed arrays,
    # so the domain it simulated was a scrambled, upside-down fragment of the intended one
    # (measured: 5,406 of 25,067 active cells survived and every mask=3 cell was lost).
    # It never errors — the run "succeeds" and every statistic downstream is meaningless.
    dep_south = dem_data[::-1, :]        # flip N-up raster -> S-up SFINCS grid
    msk_south = msk[::-1, :]
    flat_msk = msk_south.flatten(order="F")
    active_flat = np.where(flat_msk > 0)[0]
    n_active = len(active_flat)
    active_1based = (active_flat + 1).astype(np.int32)

    dep_path = output_dir / "sfincs.dep"
    msk_path = output_dir / "sfincs.msk"
    ind_path = output_dir / "sfincs.ind"

    dep_south.flatten(order="F")[active_flat].astype(np.float32).tofile(str(dep_path))
    flat_msk[active_flat].astype(np.uint8).tofile(str(msk_path))
    with open(str(ind_path), 'wb') as f_ind:
        np.array([n_active], dtype=np.int32).tofile(f_ind)
        active_1based.tofile(f_ind)

    # Auxiliary (NOT read by SFINCS): the full north-up grids, so downstream KI tools
    # can place gauges/sources without re-deriving the compression.
    np.save(output_dir / "grid_dep_northup.npy", dem_data.astype(np.float32))
    np.save(output_dir / "grid_msk_northup.npy", msk.astype(np.uint8))

    logger.info(f"Wrote: {dep_path} ({dep_path.stat().st_size} bytes = {n_active} x 4)")
    logger.info(f"Wrote: {msk_path} ({msk_path.stat().st_size} bytes = {n_active} x 1)")
    logger.info(f"Wrote: {ind_path} ({ind_path.stat().st_size} bytes)")

    # Enforce the dt_v023 format invariant. This must NOT be an `assert`: asserts are
    # stripped under `python -O`, and the failure they guard against is precisely the one
    # that "never errors" — SFINCS would read the first n_active values of a wrong-sized
    # file and simulate a scrambled domain while reporting success.
    dep_size, msk_size, ind_size = (dep_path.stat().st_size, msk_path.stat().st_size,
                                    ind_path.stat().st_size)
    fmt_errors = []
    if dep_size != n_active * 4:
        fmt_errors.append(f"sfincs.dep is {dep_size} bytes, must be {n_active} float32 "
                          f"= {n_active * 4}")
    if msk_size != n_active:
        fmt_errors.append(f"sfincs.msk is {msk_size} bytes, must be {n_active} uint8")
    if ind_size != (n_active + 1) * 4:
        fmt_errors.append(f"sfincs.ind is {ind_size} bytes, must be 1 + {n_active} int32 "
                          f"= {(n_active + 1) * 4}")
    if fmt_errors:
        for e in fmt_errors:
            logger.error(f"dt_v023 format invariant violated: {e}")
        logger.error("Refusing to leave a malformed binary map on disk — SFINCS would read "
                     "it without error and simulate a scrambled domain.")
        sys.exit(3)

    # --- Summary ---
    valid_dem = dem_data[msk > 0]
    summary = {
        "status": "success",
        "dep_file": str(dep_path),
        "msk_file": str(msk_path),
        "ind_file": str(ind_path),
        "grid_shape": [nmax, mmax],
        "total_cells": mmax * nmax,
        "active_cells": active_count,
        "outflow_cells": outflow_count,
        "elevation_min": float(np.nanmin(valid_dem)) if len(valid_dem) > 0 else None,
        "elevation_max": float(np.nanmax(valid_dem)) if len(valid_dem) > 0 else None,
        "elevation_mean": float(np.nanmean(valid_dem)) if len(valid_dem) > 0 else None,
        "dem_source": str(dem_path),
    }

    summary_path = output_dir / "topobathy_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    return str(summary_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Summary not created: {output_path}")
        sys.exit(3)

    parent = Path(output_path).parent
    for fname in ["sfincs.dep", "sfincs.msk", "sfincs.ind"]:
        fpath = parent / fname
        if not fpath.exists() or fpath.stat().st_size == 0:
            logger.error(f"Output file missing or empty: {fpath}")
            sys.exit(3)

    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build SFINCS topography/bathymetry")
    parser.add_argument("--grid_info", required=True, help="Path to grid_info.json")
    parser.add_argument("--dem_path", default=None, help="Path to DEM raster (auto-selects if omitted)")
    parser.add_argument("--shp_path", default=None, help="Basin shapefile for masking")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--nodata_fill", type=float, default=-9999, help="Fill value for nodata")
    parser.add_argument("--min_elev", type=float, default=None,
                        help="Deactivate (mask=0) cells whose bed level is below this "
                             "elevation, e.g. -20 to cut deep ocean/fjord out of a coastal "
                             "domain. Default: keep everything.")
    parser.add_argument("--max_elev", type=float, default=None,
                        help="Deactivate (mask=0) cells whose bed level is ABOVE this "
                             "elevation, e.g. 40 to keep only the valley floor of a "
                             "mountain river reach. RIVER-ONLY forcing: rain falling on "
                             "deactivated cells is discarded, so this biases the water "
                             "balance under precipitation forcing. Also forces the open "
                             "boundary onto the domain rectangle border when "
                             "--outflow_edges=all. Default: keep everything.")
    parser.add_argument("--outflow_max_elev", type=float, default=None,
                        help="Only edge cells with bed level <= this value become an open "
                             "boundary; higher edge cells stay closed (mask=1). Default: "
                             "every mask-edge cell on an eligible side is opened.")
    parser.add_argument("--outflow_value", type=int, default=3, choices=[2, 3],
                        help="Mask value for the open boundary. 3 = outflow/absorbing "
                             "(no datum imposed — correct inland, DEFAULT). 2 = water-level "
                             "boundary, held at zs=0 m unless you supply bnd+bzs (dt_v021).")
    parser.add_argument("--outflow_edges", default="all",
                        help="Comma list of DOMAIN sides allowed to carry the open boundary: "
                             "n,s,e,w or 'all' (default). Use this to open only the "
                             "downstream end of a river-reach domain. 'all' opens the whole "
                             "ACTIVE-mask perimeter, except that with --max_elev it is "
                             "intersected with the domain rectangle border so the interior "
                             "perimeter along the valley walls never becomes an outlet.")
    args = parser.parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs(args)

    try:
        output_path = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)
    sys.exit(0)
