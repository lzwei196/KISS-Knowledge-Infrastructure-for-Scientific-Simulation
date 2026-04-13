#!/usr/bin/env python3
"""
build_fulldom_hires.py  --  WRF-Hydro Phase 2, Tool 2
=====================================================
Build Fulldom_hires.nc — the high-resolution routing domain file for
WRF-Hydro's overland/subsurface routing modules.

The script:
  1. Creates the routing grid: sn*AGGFACTRT x we*AGGFACTRT cells at DXRT resolution
  2. Reprojects DEM to routing LCC grid
  3. Runs WhiteboxTools hydrological conditioning (breach -> D8 pointer -> accumulation)
  4. Converts WBT D8 encoding to WRF-Hydro ArcGIS encoding
  5. Thresholds flow accumulation to define channels + Strahler order
  6. Rasterizes basin shapefile for basn_msk
  7. Resamples LU_INDEX to routing grid
  8. Computes lat/lon for each routing cell
  9. Writes CF-compliant NetCDF with CRS and spatial reference attributes

CRITICAL NOTE on flow direction encoding:
  WhiteboxTools d8_pointer uses:   1=E, 2=NE, 4=N, 8=NW, 16=W, 32=SW, 64=S, 128=SE
  WRF-Hydro (ArcGIS convention):   1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
  Conversion is applied automatically.

Usage
-----
    python build_fulldom_hires.py \\
        --geo_em outputs/chaohe_wrf_test/DOMAIN/geo_em.d01.nc \\
        --domain_json outputs/chaohe_wrf_test/domain_def.json \\
        --dem_path data/dem/china_dem_90m/china_dem_90m.tif \\
        --basin_shp data/shp/chaohe_.../chaohe_boundary.shp \\
        --output_path outputs/chaohe_wrf_test/DOMAIN/Fulldom_hires.nc \\
        --aggfactrt 4 --stream_threshold 100
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import netCDF4 as nc
import numpy as np
import rasterio
from rasterio.crs import CRS as RioCRS
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import reproject
from pyproj import Transformer
import whitebox
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import CMFD_PRECIP_KGM2S_TO_MMDAY

# ===================================================================
# WhiteboxTools D8 -> WRF-Hydro D8 conversion table
# ===================================================================
# WBT:      1=E, 2=NE, 4=N, 8=NW, 16=W, 32=SW, 64=S, 128=SE, 0=nodata
# ArcGIS:   1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE, 0=nodata
def smart_stream_threshold(cell_area_m2, basin_cells, precip_mm_yr=800, temp_mean_c=15):
    """Compute stream threshold using USGS flow-based method for fine grids,
    NCAR scale-aware method for coarse grids.

    Fine grid (<500m): USGS 1-cfs threshold using Budyko runoff estimate
    Coarse grid (>=500m): NCAR-style 2% of basin cells, capped at 200

    Returns threshold as integer number of routing cells.
    """
    import math
    cell_size = math.sqrt(cell_area_m2)

    # Budyko runoff ratio estimate
    if temp_mean_c <= 0:
        pet = 50
    else:
        pet = 16 * (10 * temp_mean_c / 30) ** 1.5 * 12  # rough Thornthwaite PET
    aridity = pet / max(precip_mm_yr, 100)
    runoff_ratio = max(0.05, 1 - (1 + aridity - (1 + aridity**2)**0.5))

    if cell_size < 500:
        # USGS flow-based: channel where accumulated runoff >= 1 cfs (0.028 m³/s)
        runoff_m_s = precip_mm_yr * runoff_ratio / 1000 / (365.25 * CMFD_PRECIP_KGM2S_TO_MMDAY)
        cells_for_1cfs = 0.028 / (cell_area_m2 * runoff_m_s) if runoff_m_s > 0 else 200
        threshold = max(5, int(cells_for_1cfs))
    else:
        # Coarse grid: scale-aware (2% of basin, max 200, min 5)
        threshold = max(5, min(200, int(basin_cells * 0.02)))

    return threshold, runoff_ratio


WBT_TO_ARCGIS = {
    # VERIFIED by empirical test (2026-03-20) — WBT docs are WRONG!
    # WBT actual encoding:  1=NE, 2=E, 4=SE, 8=S, 16=SW, 32=W, 64=NW, 128=N
    # ArcGIS/WRF-Hydro:     1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
    0: 0,       # nodata
    1: 128,     # WBT NE -> ArcGIS NE=128
    2: 1,       # WBT E  -> ArcGIS E=1
    4: 2,       # WBT SE -> ArcGIS SE=2
    8: 4,       # WBT S  -> ArcGIS S=4
    16: 8,      # WBT SW -> ArcGIS SW=8
    32: 16,     # WBT W  -> ArcGIS W=16
    64: 32,     # WBT NW -> ArcGIS NW=32
    128: 64,    # WBT N  -> ArcGIS N=64
}


def compute_strahler(fdir, channel_mask):
    """Compute Strahler stream order on channel cells using flow direction.

    Parameters
    ----------
    fdir : ndarray (int)
        Flow direction array in ArcGIS encoding (1=E, 2=SE, 4=S, ...).
    channel_mask : ndarray (bool)
        True where a channel cell exists.

    Returns
    -------
    order : ndarray (int8)
        Strahler order for channel cells, -15 elsewhere.
    """
    ny, nx = fdir.shape
    order = np.full((ny, nx), -15, dtype=np.int8)

    # Direction -> (dy, dx) offsets (row increases downward = S)
    dir_to_offset = {
        1:  (0,  1),   # E
        2:  (1,  1),   # SE
        4:  (1,  0),   # S
        8:  (1, -1),   # SW
        16: (0, -1),   # W
        32: (-1, -1),  # NW
        64: (-1, 0),   # N
        128:(-1, 1),   # NE
    }

    # Build adjacency: for each channel cell, find upstream channel cells
    # A cell (r2,c2) is upstream of (r,c) if fdir[r2,c2] points to (r,c)
    # and both are channels.
    channel_yx = list(zip(*np.where(channel_mask)))
    ch_set = set(channel_yx)
    n_ch = len(channel_yx)
    if n_ch == 0:
        return order

    # Map (y,x) -> list of upstream (y,x)
    upstream = {yx: [] for yx in channel_yx}
    downstream = {}
    for (r, c) in channel_yx:
        d = int(fdir[r, c])
        if d in dir_to_offset:
            dy, dx = dir_to_offset[d]
            nr, nc_ = r + dy, c + dx
            if 0 <= nr < ny and 0 <= nc_ < nx:
                downstream[(r, c)] = (nr, nc_)
                if (nr, nc_) in ch_set:
                    upstream[(nr, nc_)].append((r, c))

    # Topological sort: start from headwaters (no upstream channel cells)
    from collections import deque
    in_degree = {yx: len(upstream[yx]) for yx in channel_yx}
    queue = deque([yx for yx in channel_yx if in_degree[yx] == 0])

    while queue:
        (r, c) = queue.popleft()
        ups = upstream[(r, c)]
        if len(ups) == 0:
            order[r, c] = 1
        else:
            orders = sorted([order[ur, uc] for (ur, uc) in ups], reverse=True)
            if len(orders) == 1:
                order[r, c] = orders[0]
            elif orders[0] > orders[1]:
                order[r, c] = orders[0]
            else:
                order[r, c] = orders[0] + 1

        # Process downstream
        if (r, c) in downstream:
            nr, nc_ = downstream[(r, c)]
            if (nr, nc_) in ch_set:
                in_degree[(nr, nc_)] -= 1
                if in_degree[(nr, nc_)] == 0:
                    queue.append((nr, nc_))

    return order


def build_fulldom(geo_em_path, domain_json_path, dem_path, basin_shp_path,
                  output_path, aggfactrt=4, stream_threshold=100):
    """Build Fulldom_hires.nc."""

    print(f"[build_fulldom] AGGFACTRT={aggfactrt}, stream_threshold={stream_threshold}")

    # --- Load domain definition ---
    with open(domain_json_path) as f:
        dom = json.load(f)

    dx_lsm = dom["dx"]
    dy_lsm = dom["dy"]
    e_we = dom["e_we"]
    e_sn = dom["e_sn"]
    x_sw = dom["x_sw"]
    y_sw = dom["y_sw"]
    proj4 = dom["proj4"]
    cen_lat = dom["cen_lat"]
    cen_lon = dom["cen_lon"]
    truelat1 = dom["truelat1"]
    truelat2 = dom["truelat2"]
    stand_lon = dom["stand_lon"]
    earth_r = dom.get("wrf_earth_radius", 6370000.0)

    dxrt = dx_lsm / aggfactrt
    dyrt = dy_lsm / aggfactrt
    nx_rt = e_we * aggfactrt
    ny_rt = e_sn * aggfactrt

    print(f"  LSM grid: {e_sn}x{e_we} @ {dx_lsm}m")
    print(f"  Routing grid: {ny_rt}x{nx_rt} @ {dxrt}m")

    # Routing domain extent in projected coords (cell-edge)
    x_left   = x_sw
    y_bottom = y_sw
    x_right  = x_sw + e_we * dx_lsm
    y_top    = y_sw + e_sn * dy_lsm

    # Cell centers for routing grid
    x_centers = x_left + (np.arange(nx_rt) + 0.5) * dxrt
    y_centers = y_top  - (np.arange(ny_rt) + 0.5) * dyrt  # top-down

    # --- Step 1: Reproject DEM to routing grid ---
    print("  Step 1: Reprojecting DEM to routing LCC grid...")

    # Build rasterio CRS from proj4 (WRF sphere)
    lcc_crs = RioCRS.from_proj4(proj4)

    # Routing transform: top-left origin, pixel size dxrt
    rt_transform = from_origin(x_left, y_top, dxrt, dyrt)

    with rasterio.open(dem_path) as src:
        dem_rt = np.full((ny_rt, nx_rt), -9999.0, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=dem_rt,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=rt_transform,
            dst_crs=lcc_crs,
            resampling=Resampling.bilinear,
        )
    # Fill nodata cells with nearest valid neighbor
    nodata_mask = dem_rt <= -9990.0
    n_nodata = nodata_mask.sum()
    if n_nodata > 0:
        valid_mask = ~nodata_mask
        if valid_mask.any():
            from scipy.ndimage import distance_transform_edt
            _, nearest_idx = distance_transform_edt(nodata_mask, return_distances=True, return_indices=True)
            dem_rt[nodata_mask] = dem_rt[nearest_idx[0][nodata_mask], nearest_idx[1][nodata_mask]]
            print(f"  [WARN] Routing DEM: {n_nodata} nodata cells filled with nearest neighbor")
        else:
            dem_rt[:] = 500.0  # Fallback: set all to 500m
            print(f"  [WARN] No valid DEM data for routing grid, using default 500m")
    print(f"    DEM range: {dem_rt.min():.1f} - {dem_rt.max():.1f} m")

    # --- Step 2: Hydrological conditioning with WhiteboxTools ---
    print("  Step 2: Hydrological conditioning (WhiteboxTools)...")
    tmpdir = tempfile.mkdtemp(prefix="wrf_fulldom_")

    dem_tif = os.path.join(tmpdir, "dem.tif")
    breach_tif = os.path.join(tmpdir, "breach.tif")
    fdir_tif = os.path.join(tmpdir, "fdir.tif")
    facc_tif = os.path.join(tmpdir, "facc.tif")

    # Write DEM as GeoTIFF
    profile = {
        "driver": "GTiff", "dtype": "float32",
        "width": nx_rt, "height": ny_rt, "count": 1,
        "crs": lcc_crs, "transform": rt_transform,
        "nodata": -9999.0,
    }
    with rasterio.open(dem_tif, "w", **profile) as dst:
        dst.write(dem_rt, 1)

    wbt = whitebox.WhiteboxTools()
    wbt.verbose = False

    # Breach depressions
    print("    Breach depressions...")
    wbt.breach_depressions(dem_tif, breach_tif)

    # D8 flow direction
    print("    D8 flow pointer...")
    wbt.d8_pointer(breach_tif, fdir_tif)

    # D8 flow accumulation
    print("    D8 flow accumulation...")
    wbt.d8_flow_accumulation(breach_tif, facc_tif, out_type="cells")

    # Read results
    with rasterio.open(fdir_tif) as src:
        fdir_wbt = src.read(1).astype(np.int32)
    with rasterio.open(facc_tif) as src:
        facc = src.read(1).astype(np.int32)

    print(f"    Flow accumulation range: {facc.min()} - {facc.max()}")

    # --- Step 3: Convert WBT D8 to ArcGIS D8 ---
    print("  Step 3: Converting WBT D8 encoding to ArcGIS/WRF-Hydro...")
    fdir_arc = np.zeros_like(fdir_wbt, dtype=np.int16)
    for wbt_val, arc_val in WBT_TO_ARCGIS.items():
        fdir_arc[fdir_wbt == wbt_val] = arc_val
    # Also handle nodata / zero
    fdir_arc[fdir_wbt <= 0] = 0

    unique_dirs = np.unique(fdir_arc[fdir_arc > 0])
    print(f"    Flow direction values: {sorted(unique_dirs)}")

    # --- Step 4: Channel grid and stream order ---
    # Auto-compute threshold if set to 0 (USGS/Budyko method)
    if stream_threshold <= 0:
        basin_cells = int(np.sum(basn_msk >= 0)) if 'basn_msk' in dir() else int(np.sum(fdir_arc > 0))
        auto_thresh, runoff_ratio = smart_stream_threshold(
            cell_area_m2=dxrt**2, basin_cells=basin_cells,
            precip_mm_yr=800, temp_mean_c=15  # defaults for Chinese basins
        )
        stream_threshold = auto_thresh
        print(f"  Step 4: Auto threshold={stream_threshold} (USGS/Budyko, runoff_ratio={runoff_ratio:.2f})")
    else:
        print(f"  Step 4: Channel extraction (threshold={stream_threshold})...")
    # WRF-Hydro CHANNELGRID convention: -9999=non-channel, 0=channel
    channel_grid = np.full((ny_rt, nx_rt), -9999, dtype=np.int32)
    channel_mask = facc >= stream_threshold
    channel_grid[channel_mask] = 0
    n_channel = int(channel_mask.sum())
    print(f"    Channel cells: {n_channel}")

    print("  Step 5: Computing Strahler stream order...")
    stream_order = compute_strahler(fdir_arc, channel_mask)
    max_order = int(stream_order[stream_order > 0].max()) if (stream_order > 0).any() else 0
    print(f"    Max Strahler order: {max_order}")

    # --- Step 6: Rasterize basin shapefile ---
    print("  Step 6: Rasterizing basin shapefile...")
    basin_gdf = gpd.read_file(basin_shp_path)
    basin_gdf = basin_gdf.to_crs(lcc_crs)

    # Rasterize: all basin polygons get value 1
    shapes = [(geom, 1) for geom in basin_gdf.geometry if geom is not None]
    basn_msk = np.full((ny_rt, nx_rt), -9999, dtype=np.int32)
    if shapes:
        basin_rast = rasterize(
            shapes, out_shape=(ny_rt, nx_rt),
            transform=rt_transform, fill=0, dtype=np.int32,
        )
        basn_msk[basin_rast == 1] = 1
    n_basin = int((basn_msk == 1).sum())
    print(f"    Basin cells: {n_basin}")

    # frxst_pts: no forecast points for now, all -9999
    frxst_pts = np.full((ny_rt, nx_rt), -9999, dtype=np.int32)

    # LAKEGRID: no lakes, all -9999
    lakegrid = np.full((ny_rt, nx_rt), -9999, dtype=np.int32)

    # --- Step 7: Resample LU_INDEX from geo_em ---
    print("  Step 7: Resampling land use to routing grid...")
    geo = nc.Dataset(geo_em_path, "r")
    lu_index_lsm = geo["LU_INDEX"][0, :, :].astype(np.float32)

    # Create temp raster of LU on LSM grid
    lsm_transform = from_origin(x_left, y_top, dx_lsm, dy_lsm)
    lu_tif = os.path.join(tmpdir, "lu.tif")
    lu_profile = {
        "driver": "GTiff", "dtype": "float32",
        "width": e_we, "height": e_sn, "count": 1,
        "crs": lcc_crs, "transform": lsm_transform,
        "nodata": -9999.0,
    }
    with rasterio.open(lu_tif, "w", **lu_profile) as dst:
        dst.write(lu_index_lsm, 1)

    landuse_rt = np.zeros((ny_rt, nx_rt), dtype=np.float32)
    with rasterio.open(lu_tif) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=landuse_rt,
            src_transform=src.transform,
            src_crs=lcc_crs,
            dst_transform=rt_transform,
            dst_crs=lcc_crs,
            resampling=Resampling.nearest,
        )

    # --- Step 8: Compute lat/lon for each routing cell ---
    print("  Step 8: Computing lat/lon for routing cells...")
    transformer = Transformer.from_proj(
        f"+proj=lcc +R={earth_r} +lat_0={cen_lat} +lon_0={stand_lon} "
        f"+lat_1={truelat1} +lat_2={truelat2} +x_0=0 +y_0=0 +units=m +no_defs",
        "EPSG:4326", always_xy=True
    )
    xx, yy = np.meshgrid(x_centers, y_centers)
    lons, lats = transformer.transform(xx, yy)
    lats = lats.astype(np.float32)
    lons = lons.astype(np.float32)

    # Default factor fields
    retdep = np.ones((ny_rt, nx_rt), dtype=np.float32)
    ovrough = np.ones((ny_rt, nx_rt), dtype=np.float32)
    lksatfac = np.full((ny_rt, nx_rt), 1000.0, dtype=np.float32)

    # --- Step 9a: Fix boundary cells (dt_v007) ---
    # WRF-Hydro requires all edge cells to have fdir=0 (outflow boundary)
    # Also zero flow direction for cells outside the basin
    print("  Step 9a: Fixing boundary flow directions...")
    fdir_arc[0, :] = 0; fdir_arc[-1, :] = 0
    fdir_arc[:, 0] = 0; fdir_arc[:, -1] = 0
    fdir_arc[basn_msk < 0] = 0
    # Cascade: clear channels/accumulation/order where fdir=0
    channel_grid[fdir_arc == 0] = -9999
    facc[fdir_arc == 0] = 0
    stream_order[fdir_arc == 0] = 0
    # Basin-aware fill for remaining negative/zero elevation cells
    basin_cells = basn_msk == 1
    if basin_cells.any():
        basin_mean = dem_rt[basin_cells & (dem_rt > 0)].mean() if (basin_cells & (dem_rt > 0)).any() else 500.0
        # Inside basin: fill zeros/negatives with basin mean
        dem_rt[(dem_rt <= 0) & basin_cells] = basin_mean
        # Outside basin: fill with nearest valid or basin mean
        dem_rt[dem_rt <= 0] = basin_mean
    else:
        dem_rt[dem_rt < 0] = 0  # Fallback to original behavior
    # Coverage validation
    n_zero_inside = ((dem_rt <= 0.1) & basin_cells).sum() if basin_cells.any() else 0
    if n_zero_inside > 0:
        print(f"  [WARN] {n_zero_inside} near-zero elevation cells INSIDE basin")
    print(f"  TOPOGRAPHY range: {dem_rt.min():.1f} - {dem_rt.max():.1f} m")
    n_active = int(np.sum(fdir_arc > 0))
    n_chan = int(np.sum(channel_grid >= 0))
    print(f"    Active flow cells: {n_active:,}, channels: {n_chan:,}")

    # --- Step 9: Write Fulldom_hires.nc ---
    print(f"  Step 9: Writing {output_path} ...")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    out = nc.Dataset(output_path, "w", format="NETCDF4")
    out.createDimension("y", ny_rt)
    out.createDimension("x", nx_rt)

    # y, x coordinate variables
    vy = out.createVariable("y", "f8", ("y",))
    vy.units = "m"
    vy.standard_name = "projection_y_coordinate"
    vy[:] = y_centers

    vx = out.createVariable("x", "f8", ("x",))
    vx.units = "m"
    vx.standard_name = "projection_x_coordinate"
    vx[:] = x_centers

    # CRS variable
    esri_pe = (
        f'PROJCS["unnamed",GEOGCS["GCS_Sphere",'
        f'DATUM["D_Sphere",SPHEROID["unnamed",{earth_r},0.0]],'
        f'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
        f'PROJECTION["Lambert_Conformal_Conic"],'
        f'PARAMETER["False_Easting",0.0],PARAMETER["False_Northing",0.0],'
        f'PARAMETER["Central_Meridian",{stand_lon}],'
        f'PARAMETER["Standard_Parallel_1",{truelat1}],'
        f'PARAMETER["Standard_Parallel_2",{truelat2}],'
        f'PARAMETER["Latitude_Of_Origin",{cen_lat}],'
        f'UNIT["Meter",1.0]]'
    )

    vcrs = out.createVariable("crs", "S1", ())
    vcrs.transform_name = "lambert_conformal_conic"
    vcrs.grid_mapping_name = "lambert_conformal_conic"
    vcrs.esri_pe_string = esri_pe
    vcrs.long_name = "CRS definition"
    vcrs.longitude_of_prime_meridian = 0.0
    # GeoTransform: x_left, dxrt, 0, y_top, 0, -dyrt
    vcrs.GeoTransform = f"{x_left} {dxrt} 0 {y_top} 0 {-dyrt}"
    vcrs._CoordinateAxes = "y x"
    vcrs._CoordinateTransformType = "Projection"
    vcrs.standard_parallel = np.array([truelat1, truelat2], dtype=np.float64)
    vcrs.longitude_of_central_meridian = float(stand_lon)
    vcrs.latitude_of_projection_origin = float(cen_lat)
    vcrs.false_easting = 0.0
    vcrs.false_northing = 0.0
    vcrs.earth_radius = float(earth_r)
    vcrs.semi_major_axis = float(earth_r)
    vcrs.inverse_flattening = 0.0

    # Data variables
    def write_var(name, data, dtype, **attrs):
        v = out.createVariable(name, dtype, ("y", "x"), fill_value=False)
        v.grid_mapping = "crs"
        for k, val in attrs.items():
            v.setncattr(k, val)
        v[:] = data

    write_var("CHANNELGRID", channel_grid, "i4")
    write_var("FLOWDIRECTION", fdir_arc, "i2")
    write_var("FLOWACC", facc, "i4")
    write_var("TOPOGRAPHY", dem_rt, "f4", units="m")
    write_var("RETDEPRTFAC", retdep, "f4")
    write_var("OVROUGHRTFAC", ovrough, "f4")
    write_var("STREAMORDER", stream_order, "i1")
    write_var("frxst_pts", frxst_pts, "i4")
    write_var("basn_msk", basn_msk, "i4")
    write_var("LAKEGRID", lakegrid, "i4")
    write_var("landuse", landuse_rt, "f4")
    write_var("LKSATFAC", lksatfac, "f4")
    write_var("LATITUDE", lats, "f4", units="degrees_north")
    write_var("LONGITUDE", lons, "f4", units="degrees_east")

    # CHAN_DEPTH: estimated channel depth based on stream order
    # WRF-Hydro requires this variable — crashes with MPI_Abort if missing
    chan_depth = np.full_like(dem_rt, -9999.0, dtype="f4")
    channel_mask = channel_grid == 0  # 0 = channel in WRF-Hydro convention
    order_depth_map = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0, 5: 3.0, 6: 4.0, 7: 5.0, 8: 6.0}
    for order_val, depth in order_depth_map.items():
        chan_depth[(stream_order == order_val) & channel_mask] = depth
    # Default depth for any remaining channel cells
    chan_depth[channel_mask & (chan_depth < 0)] = 1.0
    write_var("CHAN_DEPTH", chan_depth, "f4", units="m")

    # Global attributes
    out.Conventions = "CF-1.5"
    out.GDAL_DataType = "Generic"
    out.Source_Software = "HydroCraft WRF-Hydro build_fulldom_hires.py"
    out.proj4 = proj4
    out.history = f"Created by build_fulldom_hires.py"
    out.processing_notes = f"AGGFACTRT={aggfactrt}, stream_threshold={stream_threshold}"
    out.spatial_ref = esri_pe
    out.geogrid_used = str(geo_em_path)
    out.DX = float(dxrt)
    out.DY = float(dxrt)
    out.MAP_PROJ = 1

    # Corner coordinates (from geo_em if available)
    if "corner_lats" in geo.ncattrs():
        out.corner_lats = geo.getncattr("corner_lats")
        out.corner_lons = geo.getncattr("corner_lons")

    out.TRUELAT1 = float(truelat1)
    out.TRUELAT2 = float(truelat2)
    out.STAND_LON = float(stand_lon)
    out.POLE_LAT = 90.0
    out.POLE_LON = 0.0
    out.MOAD_CEN_LAT = float(cen_lat)
    out.CEN_LAT = float(cen_lat)

    out.close()
    geo.close()

    # Cleanup temp files
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"  [OK] Fulldom_hires.nc created: {ny_rt}x{nx_rt} "
          f"({n_channel} channel cells, max order {max_order})")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Build Fulldom_hires.nc routing domain for WRF-Hydro")
    parser.add_argument("--geo_em", required=True, help="Path to geo_em.d01.nc")
    parser.add_argument("--domain_json", required=True, help="Path to domain_def.json")
    parser.add_argument("--dem_path", required=True, help="Path to DEM GeoTIFF")
    parser.add_argument("--basin_shp", required=True, help="Path to basin shapefile")
    parser.add_argument("--output_path", required=True, help="Output Fulldom_hires.nc path")
    parser.add_argument("--aggfactrt", type=int, default=4,
                        help="Aggregation factor for routing grid (default: 4)")
    parser.add_argument("--stream_threshold", type=int, default=100,
                        help="Flow accumulation threshold for channel definition (default: 100)")
    args = parser.parse_args()

    build_fulldom(
        geo_em_path=args.geo_em,
        domain_json_path=args.domain_json,
        dem_path=args.dem_path,
        basin_shp_path=args.basin_shp,
        output_path=args.output_path,
        aggfactrt=args.aggfactrt,
        stream_threshold=args.stream_threshold,
    )


if __name__ == "__main__":
    main()
