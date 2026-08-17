#!/usr/bin/env python3
"""
run_hydromt_build.py — Build a wflow model using HydroMT-wflow or manual pipeline.

Two modes:
  1. HydroMT mode (--use_hydromt): Uses 'hydromt build wflow' CLI to create
     staticmaps.nc, wflow_sbm.toml, and forcing.nc from global datasets.
  2. Manual mode (default): Uses HydroCraft's existing basin delineation plus
     MERIT-Hydro (flow network, sub-grid channel profile), HWSD (soil texture
     and REF_DEPTH), GLC_FCS30 30 m land cover and GLASS LAI to construct
     staticmaps.nc directly. This is preferred when CMFD/MSWX forcing is
     already available.

     NOTE: hydromt_wflow is NOT installed on this server, so --use_hydromt is
     dead and manual mode is the only live path. The land-surface fields it
     writes therefore have to be real per-cell lookups, not constants — see
     derive_landsurface_params.py and dt_w042.

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
import math
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


def _merit_tiles_for_bbox_local(merit_dir, bbox, kind):
    """MERIT-Hydro 5x5-degree tile paths covering bbox=(minlon,minlat,maxlon,maxlat)."""
    import glob as _glob
    import math as _math
    want = []
    lon0 = int(_math.floor(bbox[0] / 5.0) * 5)
    lon1 = int(_math.floor(bbox[2] / 5.0) * 5)
    lat0 = int(_math.floor(bbox[1] / 5.0) * 5)
    lat1 = int(_math.floor(bbox[3] / 5.0) * 5)
    for la in range(lat0, lat1 + 1, 5):
        for lo in range(lon0, lon1 + 1, 5):
            ns = "n" if la >= 0 else "s"
            ew = "e" if lo >= 0 else "w"
            tile = f"{ns}{abs(la):02d}{ew}{abs(lo):03d}"
            hits = _glob.glob(os.path.join(merit_dir, f"{tile}_{kind}.tif")) or \
                _glob.glob(os.path.join(merit_dir, "**", f"{tile}_{kind}.tif"),
                           recursive=True)
            if hits:
                want.append(hits[0])
    if not want:
        raise FileNotFoundError(
            f"no MERIT-Hydro '{kind}' tiles under {merit_dir} for bbox {bbox}")
    return sorted(set(want))


CHINA_DEM = "KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif"
MERIT_DEM_DIR = "KISSPATH_DATA/MERIT_DEM"
# Generous land bbox of the China 90 m DEM (minlon, minlat, maxlon, maxlat).
CHINA_BBOX = (73.0, 17.0, 136.0, 54.0)


def _resolve_dem_path(config, bbox):
    """Pick the elevation source for THIS window (dt_w040).

    Precedence: config `data.dem_path` > auto. Auto is the China 90 m DEM only
    when the WHOLE window lies inside China, otherwise the global MERIT DEM
    tile directory.

    This used to be a hard default to `china_dem_90m.tif`. Outside China every
    sample is nodata, the nearest-neighbour gap fill has no donor at all, and
    the build carried on with a uniform -9999 (or, via the except branch, a
    flat 500 m placeholder) surface: `Slope` / `RiverSlope` then collapse to
    the floor and kinematic-wave celerity is set by the floor instead of the
    terrain. wflow runs; the hydrograph is simply wrong. Observed again at the
    Saar (2026-08-08): `DEM sampled: -9999 - -9999 m`, RiverSlope median
    1.67e-04.
    """
    p = (config.get("data") or {}).get("dem_path", "")
    if p:
        return p, "config data.dem_path"
    inside_china = (CHINA_BBOX[0] <= bbox[0] and bbox[2] <= CHINA_BBOX[2] and
                    CHINA_BBOX[1] <= bbox[1] and bbox[3] <= CHINA_BBOX[3])
    if inside_china and os.path.exists(CHINA_DEM):
        return CHINA_DEM, "auto (window inside China)"
    return MERIT_DEM_DIR, "auto (global MERIT DEM tiles)"


def _sample_dem(dem_path, lat_centers, lon_centers):
    """Nearest-neighbour sample of `dem_path` onto the model grid.

    `dem_path` is either a single GeoTIFF or a DIRECTORY of MERIT 5x5-degree
    `<tile>_dem.tif` tiles, which are merged over the window first. Returns
    (dem_grid, n_valid, source_description). NEVER substitutes a placeholder:
    the caller raises when n_valid == 0 (dt_w040).
    """
    import numpy as np
    import rasterio

    ny, nx = len(lat_centers), len(lon_centers)
    dem_grid = np.full((ny, nx), -9999.0)

    if os.path.isdir(dem_path):
        from rasterio.merge import merge as rio_merge
        pad = 0.05
        bbox = (float(min(lon_centers)) - pad, float(min(lat_centers)) - pad,
                float(max(lon_centers)) + pad, float(max(lat_centers)) + pad)
        tiles = _merit_tiles_for_bbox_local(dem_path, bbox, "dem")
        srcs = [rasterio.open(t) for t in tiles]
        try:
            arr, transform = rio_merge(srcs, bounds=bbox)
        finally:
            for s in srcs:
                s.close()
        band = arr[0].astype(float)
        inv = ~transform
        nr, nc = band.shape
        for j, lat in enumerate(lat_centers):
            for i, lon in enumerate(lon_centers):
                col, row = inv * (float(lon), float(lat))
                r, c = int(row), int(col)
                if 0 <= r < nr and 0 <= c < nc:
                    v = band[r, c]
                    if -1000.0 < v < 9000.0:
                        dem_grid[j, i] = float(v)
        src_desc = f"{dem_path} ({len(tiles)} MERIT tile(s))"
    else:
        with rasterio.open(dem_path) as src:
            for j, lat in enumerate(lat_centers):
                for i, lon in enumerate(lon_centers):
                    row, col = src.index(float(lon), float(lat))
                    if 0 <= row < src.height and 0 <= col < src.width:
                        val = src.read(1, window=rasterio.windows.Window(
                            col, row, 1, 1))[0, 0]
                        if -1000.0 < val < 9000.0:
                            dem_grid[j, i] = float(val)
        src_desc = dem_path

    n_valid = int((dem_grid > -1000.0).sum())
    return dem_grid, n_valid, src_desc


def _slope_floor(acc_area_km2, k=2.0e-3, exponent=0.4, floor_min=1.0e-5):
    """Upstream-area-consistent minimum slope.

    A blanket `max(slope, 1e-4)` floors headwater and mainstem cells at the same
    value; at Rio Pelotas it pinned 20 of 53 river cells (38 % of the channel
    network) at exactly 1e-4, 40x below the network median of 4.1e-3, so the
    kinematic-wave celerity of those reaches was set by the floor rather than by
    the terrain (dt_w040). Channel slope decays with contributing area
    (Flint's law, S ~ A^-theta with theta ~ 0.4), so the floor must decay too.
    """
    a = max(float(acc_area_km2), 1.0e-3)
    return max(floor_min, k * a ** (-exponent))


def _subgrid_river_slope(mask, acc_area, slope_grid, lat_centers, lon_centers,
                         resolution, merit_fine, merit_hydro_dir, report):
    """RiverSlope from the MERIT-Hydro sub-grid channel profile.

    For every active coarse cell, walk the FINE (3-arcsec) D8 main stem upstream
    from the cell's outlet pixel while it stays inside the cell. The slope is
    (elevation at the fine entry pixel - elevation at the fine exit pixel)
    divided by the fine flow-path length, i.e. a real channel gradient instead
    of a copy of the coarse land D8 drop.

    Returns (river_slope, n_subgrid, n_fallback) or None when the MERIT `elv`
    tiles are not staged (stage them with
    `fetch_merit_hydro_tiles.py --kinds dir,upa,elv`).
    """
    import numpy as np
    import rasterio
    from rasterio.merge import merge as rio_merge
    from ki_tools_common.terrain_ops.delineate import MERIT_D8_OFFSETS

    try:
        tiles = _merit_tiles_for_bbox_local(
            merit_hydro_dir, tuple(merit_fine["bounds"]), "elv")
    except FileNotFoundError as e:
        report["river_slope_note"] = (
            f"{e}; falling back to the coarse D8 drop. Stage the elevation "
            f"tiles with fetch_merit_hydro_tiles.py --kinds dir,upa,elv to get "
            f"the sub-grid channel profile.")
        return None

    srcs = [rasterio.open(t) for t in tiles]
    try:
        arr, _ = rio_merge(srcs, bounds=tuple(merit_fine["bounds"]))
    finally:
        for s in srcs:
            s.close()
    elv = arr[0].astype(float)
    elv[elv < -9000] = np.nan

    fdir = merit_fine["fdir"]
    fupa = merit_fine["fupa"]
    fine_mask = merit_fine["fine_mask"]
    cj, ci = merit_fine["cj"], merit_fine["ci"]
    ftrans = merit_fine["transform"]
    fnr, fnc = fine_mask.shape
    if elv.shape != fine_mask.shape:
        report["river_slope_note"] = (
            f"MERIT elv mosaic {elv.shape} != flow-direction grid "
            f"{fine_mask.shape}; falling back to the coarse D8 drop")
        return None

    pix_deg = abs(float(ftrans.a))
    ny, nx = mask.shape
    out = np.zeros((ny, nx))
    n_sub = n_fb = 0

    # neighbour (r-dr, c-dc) flows INTO (r, c) when its D8 code is `code`
    nbrs = [(dr, dc, code) for code, (dr, dc) in MERIT_D8_OFFSETS.items()]

    for (j, i), (pr, pc) in merit_fine["outlet_px"].items():
        if not (0 <= j < ny and 0 <= i < nx) or mask[j, i] == 0:
            continue
        r, c = pr, pc
        length_m = 0.0
        for _ in range(20000):
            best, best_upa = None, -np.inf
            for dr, dc, code in nbrs:
                nr, nc = r - dr, c - dc
                if not (0 <= nr < fnr and 0 <= nc < fnc):
                    continue
                if not fine_mask[nr, nc]:
                    continue
                if cj[nr, nc] != j or ci[nr, nc] != i:
                    continue          # left the coarse cell
                if int(fdir[nr, nc]) != code:
                    continue          # does not drain into (r, c)
                if float(fupa[nr, nc]) > best_upa:
                    best, best_upa = (nr, nc, dr, dc), float(fupa[nr, nc])
            if best is None:
                break
            nr, nc, dr, dc = best
            lat = ftrans.f + (r + 0.5) * ftrans.e
            dy = abs(dr) * pix_deg * 111320.0
            dx = abs(dc) * pix_deg * 111320.0 * math.cos(math.radians(lat))
            length_m += math.hypot(dx, dy)
            r, c = nr, nc

        z_in, z_out = elv[r, c], elv[pr, pc]
        if length_m <= 0.0 or not np.isfinite(z_in) or not np.isfinite(z_out):
            out[j, i] = slope_grid[j, i]
            n_fb += 1
            continue
        out[j, i] = (z_in - z_out) / length_m
        n_sub += 1

    # cells the fine trace never reached (e.g. the outlet cell after pruning)
    todo = (mask == 1) & (out == 0.0)
    n_fb += int(todo.sum())
    out = np.where(todo, slope_grid, out)

    report["river_slope_elv_tiles"] = [os.path.basename(t) for t in tiles]
    return out, n_sub, n_fb


def build_manual(config, args):
    """Build wflow staticmaps.nc from HydroCraft data.

    Sources actually read: MERIT-Hydro (D8 flow network, upstream area and — when
    the `elv` tiles are staged — the sub-grid channel profile), a real DEM
    (MERIT DEM globally, the China 90 m DEM inside China), HWSD (texture ->
    KsatVer/theta_s/theta_r/c, REF_DEPTH -> SoilThickness), GLC_FCS30 30 m land
    cover (sub-grid class fractions -> RootingDepth/Kext/Sl/Swood/N/PathFrac/
    WaterFrac) and GLASS LAI (-> Cmax/CanopyGapFraction).
    """
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

    # Read basin shapefile — used ONLY to bound the working window and to supply
    # a reference area. The ROUTING DOMAIN is delineated from the coarse-grid
    # flow network further down (see "domain delineation" below), never from a
    # rasterised shapefile: a shapefile derived from a different (finer) DEM does
    # not align cell-for-cell with the coarse D8 network, and forcing every
    # misaligned edge cell to a pit shatters the basin into many sub-basins.
    basin_gdf = gpd.read_file(shp_path)
    bounds = basin_gdf.total_bounds  # minx, miny, maxx, maxy

    try:
        shp_area_km2 = float(basin_gdf.to_crs(6933).union_all().area) / 1e6
    except Exception:
        shp_area_km2 = None

    # Working window: pad the shapefile bounds so upstream tracing is never
    # clipped by the window edge.
    pad = 3 * resolution
    lons = np.arange(
        np.floor((bounds[0] - pad) / resolution) * resolution,
        np.ceil((bounds[2] + pad) / resolution) * resolution + resolution,
        resolution,
    )
    lats = np.arange(
        np.floor((bounds[1] - pad) / resolution) * resolution,
        np.ceil((bounds[3] + pad) / resolution) * resolution + resolution,
        resolution,
    )

    # Create coordinate arrays.
    # y MUST be DESCENDING (north first) — see SKILL.md critical fact #10
    # (dt_w034): an ascending y axis inverts the LDD directions wflow derives
    # after its read_standardized transform.
    lon_centers = lons + resolution / 2
    lat_centers = (lats + resolution / 2)[::-1]

    ny, nx = len(lat_centers), len(lon_centers)
    print(f"  Grid: {nx} x {ny} = {nx * ny} cells (window incl. {pad:.2f} deg pad)",
          file=sys.stderr)

    # Provisional mask = whole window. The DEM is sampled everywhere (SKILL.md
    # LDD problem 2), and the true domain is traced from the flow network below.
    mask = np.ones((ny, nx), dtype=np.int32)
    n_cells = int(mask.sum())

    # ── Sample real DEM ─────────────────────────────────────────────────
    # IMPORTANT: Sample ALL grid cells (including outside basin mask) so
    # WhiteboxTools sees real terrain and can compute proper drainage out
    # of the basin. Setting outside cells to nodata/-9999 creates artificial
    # barriers that cause flow direction cycles.
    win_bbox = (float(min(lon_centers)), float(min(lat_centers)),
                float(max(lon_centers)), float(max(lat_centers)))
    dem_path, dem_why = _resolve_dem_path(config, win_bbox)
    dem_grid, n_dem_valid, dem_src = _sample_dem(dem_path, lat_centers,
                                                 lon_centers)
    if n_dem_valid == 0:
        # NO placeholder (dt_w040). A flat surface silently pins Slope and
        # RiverSlope at the floor and produces a plausible-looking but wrong
        # hydrograph, so an unusable elevation source must FAIL the build.
        return {"status": "failed",
                "error": f"DEM {dem_src} ({dem_why}) covers none of the model "
                         f"window {win_bbox}: 0/{n_cells} cells valid. Point "
                         f"config data.dem_path at an elevation source that "
                         f"covers the basin (the global MERIT DEM tile "
                         f"directory {MERIT_DEM_DIR} works worldwide). "
                         f"Refusing to build on a placeholder surface."}
    # Fill any remaining -9999 cells with the nearest valid neighbour value
    # (not the basin mean — that creates artificial flats).
    from scipy.ndimage import distance_transform_edt
    invalid = dem_grid <= -1000
    if np.any(invalid):
        _, nearest_idx = distance_transform_edt(
            invalid, return_distances=True, return_indices=True)
        dem_grid[invalid] = dem_grid[tuple(nearest_idx[:, invalid])]
    print(f"  DEM sampled from {dem_src} [{dem_why}]: {n_dem_valid}/{n_cells} "
          f"cells valid, {np.min(dem_grid[mask==1]):.0f} - "
          f"{np.max(dem_grid[mask==1]):.0f} m", file=sys.stderr)

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

    # ── MERIT-Hydro mode: upscale a CORRECTED flow network ──────────────
    # On low-relief basins (the Huai plain, and any floodplain) a D8 network
    # derived from a nearest-neighbour-resampled DEM is noise: neighbouring
    # 0.1 deg cells differ by a few metres, so the drainage pattern is
    # essentially arbitrary and the delineated area misses whole tributaries.
    # MERIT-Hydro ships a hydrologically corrected 3-arcsec D8 grid; upscaling
    # it to the model grid keeps the real river network.
    merit_meta = None
    merit_fine = None
    if args.merit_hydro_dir:
        import rasterio
        from rasterio.merge import merge as rio_merge
        from ki_tools_common.terrain_ops.delineate import (
            delineate_basin_merit_hydro, MERIT_D8_OFFSETS)

        bbox = (float(lon_centers[0] - resolution / 2),
                float(lat_centers[-1] - resolution / 2),
                float(lon_centers[-1] + resolution / 2),
                float(lat_centers[0] + resolution / 2))
        mr = delineate_basin_merit_hydro(
            merit_hydro_dir=args.merit_hydro_dir,
            pour_point=(float(config["basin"]["lon"]), float(config["basin"]["lat"])),
            bbox=bbox,
            output_dir=os.path.join(project_dir, "merit_basin"),
            snap_radius_deg=args.merit_snap_radius_deg,
            expected_area_km2=(args.expected_area_km2 or None),
            area_tolerance_pct=args.merit_area_tolerance_pct,
        )
        merit_meta = mr

        with rasterio.open(mr["basin_raster"]) as src:
            fine_mask = src.read(1).astype(bool)
            ftrans = src.transform
            fbounds = src.bounds

        def _fine(kind):
            tiles = _merit_tiles_for_bbox_local(args.merit_hydro_dir, tuple(fbounds), kind)
            srcs = [rasterio.open(t) for t in tiles]
            arr, _ = rio_merge(srcs, bounds=tuple(fbounds))
            for s in srcs:
                s.close()
            return arr[0]

        fdir_fine = _fine("dir")
        fupa_fine = _fine("upa")
        fnr, fnc = fine_mask.shape

        # Map every fine pixel to its coarse cell
        rr, cc = np.indices((fnr, fnc))
        plon = ftrans.c + (cc + 0.5) * ftrans.a
        plat = ftrans.f + (rr + 0.5) * ftrans.e
        cj = np.rint((lat_centers[0] - plat) / resolution).astype(int)
        ci = np.rint((plon - lon_centers[0]) / resolution).astype(int)
        inside = (cj >= 0) & (cj < ny) & (ci >= 0) & (ci < nx)

        # Coarse cell is active when at least half of it lies in the basin
        n_tot = np.zeros((ny, nx))
        n_bas = np.zeros((ny, nx))
        np.add.at(n_tot, (cj[inside], ci[inside]), 1)
        sel = inside & fine_mask
        np.add.at(n_bas, (cj[sel], ci[sel]), 1)
        frac = np.divide(n_bas, np.maximum(n_tot, 1))
        mask = (frac >= args.merit_cell_fraction).astype(np.int32)

        # Accumulated area per coarse cell = MERIT upa at the cell's outlet
        # pixel (the basin pixel of largest upstream area inside the cell).
        acc_area = np.zeros((ny, nx))
        outlet_px = {}
        upa_masked = np.where(fine_mask, fupa_fine, -np.inf)
        for j in range(ny):
            for i in range(nx):
                if mask[j, i] == 0:
                    continue
                box_sel = (cj == j) & (ci == i) & fine_mask
                if not box_sel.any():
                    mask[j, i] = 0
                    continue
                idx = np.argmax(np.where(box_sel, upa_masked, -np.inf))
                pr, pc = np.unravel_index(idx, (fnr, fnc))
                outlet_px[(j, i)] = (int(pr), int(pc))
                acc_area[j, i] = float(fupa_fine[pr, pc])

        # Keep the fine network around: RiverSlope is derived from the sub-grid
        # channel profile further down instead of copying the coarse D8 drop.
        merit_fine = {
            "fdir": fdir_fine,
            "fupa": fupa_fine,
            "fine_mask": fine_mask,
            "cj": cj,
            "ci": ci,
            "transform": ftrans,
            "bounds": tuple(fbounds),
            "outlet_px": outlet_px,
        }

        # Coarse LDD: walk downstream on the fine network from each cell's
        # outlet pixel until reaching a DIFFERENT active coarse cell.
        ldd_full = np.full((ny, nx), 5, dtype=int)
        dir_to_ldd = {(-1, -1): 7, (-1, 0): 8, (-1, 1): 9,
                      (0, -1): 4, (0, 1): 6,
                      (1, -1): 1, (1, 0): 2, (1, 1): 3}
        for (j, i), (pr, pc) in outlet_px.items():
            r, c = pr, pc
            for _ in range(20000):
                d = int(fdir_fine[r, c])
                if d not in MERIT_D8_OFFSETS:
                    break  # river mouth / pit / nodata
                dr_, dc_ = MERIT_D8_OFFSETS[d]
                r, c = r + dr_, c + dc_
                if not (0 <= r < fnr and 0 <= c < fnc):
                    break
                nj, ni = cj[r, c], ci[r, c]
                if (nj, ni) == (j, i):
                    continue
                if not (0 <= nj < ny and 0 <= ni < nx):
                    break
                if mask[nj, ni] == 0:
                    continue  # skip cells the 50% rule dropped
                dj, di = int(np.sign(nj - j)), int(np.sign(ni - i))
                if abs(nj - j) <= 1 and abs(ni - i) <= 1:
                    ldd_full[j, i] = dir_to_ldd[(dj, di)]
                elif mask[j + dj, i + di] == 1:
                    ldd_full[j, i] = dir_to_ldd[(dj, di)]
                break

        # Outlet = the coarse cell holding the traced basin outlet
        oj = int(np.rint((lat_centers[0] - mr["outlet_lat"]) / resolution))
        oi = int(np.rint((mr["outlet_lon"] - lon_centers[0]) / resolution))
        oj = int(np.clip(oj, 0, ny - 1)); oi = int(np.clip(oi, 0, nx - 1))
        mask[oj, oi] = 1
        ldd_full[oj, oi] = 5

        # Cell areas + reporting
        cell_area = np.zeros((ny, nx))
        for j in range(ny):
            cell_area[j, :] = (resolution * 111320.0) * (
                resolution * 111320.0 * np.cos(np.radians(lat_centers[j]))) / 1e6
        n_cells = int(mask.sum())
        basin_area_km2 = float(cell_area[mask == 1].sum())
        expected_km2 = args.expected_area_km2 or shp_area_km2
        area_err = ((basin_area_km2 - expected_km2) / expected_km2 * 100
                    if expected_km2 else float("nan"))
        print(f"  MERIT-Hydro upscaled: outlet {mr['outlet_lat']:.4f},"
              f"{mr['outlet_lon']:.4f} (MERIT upa {mr['merit_upa_km2']:,.0f} km2) "
              f"-> cell ({oj},{oi})", file=sys.stderr)
        print(f"  Domain: {n_cells} cells, {basin_area_km2:,.0f} km2 "
              f"({area_err:+.1f}% vs reference {expected_km2:,.0f} km2)", file=sys.stderr)

        # Every active cell must reach the outlet; prune any that do not.
        reach = np.zeros((ny, nx), dtype=bool)
        for j in range(ny):
            for i in range(nx):
                if mask[j, i] == 0:
                    continue
                cjj, cii, ok = j, i, False
                for _ in range(ny * nx):
                    if (cjj, cii) == (oj, oi):
                        ok = True
                        break
                    d = ldd_full[cjj, cii]
                    if d == 5:
                        break
                    off = ldd_offset[d]
                    cjj, cii = cjj + off[0], cii + off[1]
                    if not (0 <= cjj < ny and 0 <= cii < nx) or mask[cjj, cii] == 0:
                        break
                reach[j, i] = ok
        n_pruned = int((mask == 1).sum() - reach.sum())
        if n_pruned:
            print(f"  Pruned {n_pruned} cell(s) that do not drain to the outlet",
                  file=sys.stderr)
            mask = np.where(reach, 1, 0).astype(np.int32)
            n_cells = int(mask.sum())
            basin_area_km2 = float(cell_area[mask == 1].sum())
            area_err = ((basin_area_km2 - expected_km2) / expected_km2 * 100
                        if expected_km2 else float("nan"))
            print(f"  Domain after prune: {n_cells} cells, {basin_area_km2:,.0f} km2 "
                  f"({area_err:+.1f}%)", file=sys.stderr)

    # ── Step 1: LDD over the FULL window (no basin mask applied yet) ────
    if merit_meta is None:
        ldd_full = np.full((ny, nx), 5, dtype=int)
        for j in range(ny):
            for i in range(nx):
                fv = fdir_safe[j, i]
                if fv <= 0 or fv not in wbt_to_ldd:
                    continue
                d = wbt_to_ldd[fv]
                off = ldd_offset[d]
                nj, ni = j + off[0], i + off[1]
                if not (0 <= nj < ny and 0 <= ni < nx):
                    continue  # drains out of the window -> window-edge pit
                ldd_full[j, i] = d

        # ── Step 2: area-weighted flow accumulation (topological, cycle-free) ──
        # Cell area varies with latitude; accumulate km2 so the result can be
        # checked directly against the gauge's published catchment area.
        cell_area = np.zeros((ny, nx))
        for j in range(ny):
            cell_area[j, :] = (resolution * 111320.0) * \
                              (resolution * 111320.0 * np.cos(np.radians(lat_centers[j]))) / 1e6

        down = {}
        indeg = np.zeros((ny, nx), dtype=int)
        for j in range(ny):
            for i in range(nx):
                d = ldd_full[j, i]
                if d == 5:
                    continue
                off = ldd_offset[d]
                nj, ni = j + off[0], i + off[1]
                down[(j, i)] = (nj, ni)
                indeg[nj, ni] += 1

        acc_area = cell_area.copy()
        from collections import deque
        queue = deque([(j, i) for j in range(ny) for i in range(nx) if indeg[j, i] == 0])
        processed = 0
        while queue:
            j, i = queue.popleft()
            processed += 1
            tgt = down.get((j, i))
            if tgt is None:
                continue
            nj, ni = tgt
            acc_area[nj, ni] += acc_area[j, i]
            indeg[nj, ni] -= 1
            if indeg[nj, ni] == 0:
                queue.append((nj, ni))
        if processed != ny * nx:
            return {"status": "failed",
                    "error": f"flow network has cycles: {ny*nx - processed} cells unprocessed"}

        # ── Step 3: snap the gauge and delineate the DOMAIN from this network ──
        # Snap-radius ladder: evaluate every cell within 5 cells of the gauge and
        # keep the one whose accumulated area best matches the reference area. A
        # single fixed radius is the repeat silent failure (snapping onto a creek).
        g_lat = float(config["basin"]["lat"])
        g_lon = float(config["basin"]["lon"])
        expected_km2 = args.expected_area_km2 or shp_area_km2
        gj = int(np.argmin(np.abs(lat_centers - g_lat)))
        gi = int(np.argmin(np.abs(lon_centers - g_lon)))

        best = None
        for j in range(max(0, gj - 5), min(ny, gj + 6)):
            for i in range(max(0, gi - 5), min(nx, gi + 6)):
                a = acc_area[j, i]
                score = abs(a - expected_km2) / expected_km2 if expected_km2 else -a
                if best is None or score < best[0]:
                    best = (score, j, i, a)
        _, oj, oi, outlet_area = best
        print(f"  Gauge ({g_lat}, {g_lon}) snapped to cell ({oj},{oi}) = "
              f"{lat_centers[oj]:.3f},{lon_centers[oi]:.3f}; accumulated area "
              f"{outlet_area:,.0f} km2 (reference {expected_km2:,.0f} km2)",
              file=sys.stderr)

        # Trace upstream from the outlet: the domain is exactly the set of cells
        # that drain to it, so by construction it has ONE outlet and no cell needs
        # a fabricated pit at the boundary.
        upstream = {}
        for src, tgt in down.items():
            upstream.setdefault(tgt, []).append(src)
        mask = np.zeros((ny, nx), dtype=np.int32)
        stack = [(oj, oi)]
        mask[oj, oi] = 1
        while stack:
            cur = stack.pop()
            for src in upstream.get(cur, []):
                if mask[src[0], src[1]] == 0:
                    mask[src[0], src[1]] = 1
                    stack.append(src)

        n_cells = int(mask.sum())
        basin_area_km2 = float(cell_area[mask == 1].sum())
        area_err = (basin_area_km2 - expected_km2) / expected_km2 * 100 if expected_km2 else float("nan")
        print(f"  Domain delineated: {n_cells} cells, {basin_area_km2:,.0f} km2 "
              f"({area_err:+.1f}% vs reference)", file=sys.stderr)
        if n_cells < 2:
            return {"status": "failed",
                    "error": f"delineated domain has only {n_cells} cell(s) — gauge snap failed"}

    # ── Step 4: write the LDD for the delineated domain ────────────────
    # Rebuild wflow-space mask for the FINAL domain, then apply the dual-space
    # boundary check (dt_w014). On a traced domain it can only fire at the
    # outlet, which is the one legitimate pit.
    wf_mask = np.zeros((nx, ny), dtype=int)
    for j in range(ny):
        for i in range(nx):
            if y_descending:
                wf_mask[i, ny - 1 - j] = int(mask[j, i])
            else:
                wf_mask[i, j] = int(mask[j, i])

    for j in range(ny):
        for i in range(nx):
            if mask[j, i] == 0:
                continue
            if (j, i) == (oj, oi):
                ldd[j, i] = 5.0
                continue
            d = ldd_full[j, i]
            off = ldd_offset[d]
            nj, ni = j + off[0], i + off[1]
            if d == 5 or not (0 <= nj < ny and 0 <= ni < nx) or mask[nj, ni] == 0:
                ldd[j, i] = 5.0
                continue
            dx, dy = wflow_pcr_dir[d]
            wx, wy = (i, ny - 1 - j) if y_descending else (i, j)
            twx, twy = wx + dx, wy + dy
            if not (0 <= twx < nx and 0 <= twy < ny) or wf_mask[twx, twy] == 0:
                ldd[j, i] = 5.0
                continue
            ldd[j, i] = float(d)

    n_outlets = int(np.nansum((ldd == 5) & (mask == 1)))
    print(f"  LDD computed: {n_outlets} outlet(s), 0 cycles (verified)", file=sys.stderr)
    if n_outlets != 1:
        return {"status": "failed",
                "error": f"{n_outlets} outlets in the delineated domain (expected exactly 1) — "
                         "the domain and the flow network disagree; discharge at the gauge "
                         "would integrate only part of the basin"}

    # Compute slope from breached DEM.
    # The floor is upstream-area-consistent (see _slope_floor): a single blanket
    # max(...,1e-4) collapses whole reaches onto the same value and the
    # kinematic wave then runs on the floor instead of on the terrain (dt_w040).
    n_land_slope_floored = 0
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
                raw = drop / max(dist, 1.0)
                floor = _slope_floor(acc_area[j, i])
                if raw < floor:
                    n_land_slope_floored += 1
                slope_grid[j, i] = max(floor, raw)

    # ── River network from the accumulated DRAINAGE AREA ────────────────
    # A fixed cell-count threshold scales with the grid, not with hydrology.
    # Use a physical contributing-area threshold instead so the channel head
    # sits where a channel actually forms.
    river_area_threshold_km2 = args.river_threshold_km2
    river = np.where((acc_area >= river_area_threshold_km2) & (mask == 1), 1, 0).astype(np.int32)
    river[oj, oi] = 1  # the outlet is always a river cell
    n_river = int(river.sum())
    print(f"  River cells: {n_river} / {n_cells} "
          f"({100.0*n_river/n_cells:.0f}%, threshold {river_area_threshold_km2} km2)",
          file=sys.stderr)
    if n_river < 2:
        return {"status": "failed",
                "error": f"only {n_river} river cell(s) — lower --river_threshold_km2 "
                         "(dt_w013: a degenerate river network routes no flow)"}

    # ── River geometry from drainage area (dt_w015) ─────────────────────
    # Uniform placeholder width/slope is the documented cause of a 2-3x
    # discharge magnitude error. Downstream hydraulic geometry W = a * A^b
    # gives a width that grows from headwater to outlet.
    river_width = np.where(
        river == 1, np.maximum(5.0, 2.5 * np.power(np.maximum(acc_area, 1.0), 0.45)), 0.0)
    river_length = np.zeros((ny, nx))
    for j in range(ny):
        for i in range(nx):
            if mask[j, i] == 0:
                continue
            cell_m = resolution * 111320.0 * np.cos(np.radians(lat_centers[j]))
            d = ldd[j, i]
            river_length[j, i] = cell_m * (1.414 if d in (1, 3, 7, 9) else 1.0)
    # ── RiverSlope from the MERIT sub-grid channel profile (dt_w040) ────
    # It used to be a verbatim copy of the coarse land D8 slope under a blanket
    # 1e-4 floor. Two separate defects: a hillslope gradient is not a channel
    # gradient, and one constant floor pins unrelated reaches to the same value
    # (20 of 53 river cells at Rio Pelotas). Derive the real channel gradient
    # from the fine flow path where MERIT elevation is available, and floor with
    # an area-consistent minimum everywhere.
    slope_report = {}
    n_slope_subgrid = n_slope_fallback = 0
    river_slope_method = "coarse_d8_fallback"
    river_slope_raw = np.where(mask == 1, slope_grid, 0.0)
    if merit_fine is not None:
        sub = _subgrid_river_slope(mask, acc_area, slope_grid, lat_centers,
                                   lon_centers, resolution, merit_fine,
                                   args.merit_hydro_dir, slope_report)
        if sub is not None:
            river_slope_raw, n_slope_subgrid, n_slope_fallback = sub
            river_slope_method = "merit_subgrid_channel_profile"

    river_slope = np.zeros((ny, nx))
    n_river_slope_floored = 0
    for j in range(ny):
        for i in range(nx):
            if mask[j, i] == 0:
                continue
            floor = _slope_floor(acc_area[j, i])
            raw = float(river_slope_raw[j, i])
            if raw < floor:
                n_river_slope_floored += 1
            river_slope[j, i] = max(floor, raw)

    _rs = river_slope[river == 1]
    slope_report.update({
        "river_slope_method": river_slope_method,
        "river_slope_subgrid_cells": int(n_slope_subgrid),
        "river_slope_coarse_fallback_cells": int(n_slope_fallback),
        "river_slope_floored_cells": int(np.sum(
            (river == 1) & (river_slope_raw < np.vectorize(_slope_floor)(acc_area)))),
        "river_slope_floored_cells_domain": int(n_river_slope_floored),
        "land_slope_floored_cells": int(n_land_slope_floored),
        "river_slope_min": float(_rs.min()) if _rs.size else None,
        "river_slope_median": float(np.median(_rs)) if _rs.size else None,
        "river_slope_max": float(_rs.max()) if _rs.size else None,
    })
    print(f"  RiverSlope ({river_slope_method}): {n_slope_subgrid} sub-grid / "
          f"{n_slope_fallback} coarse-fallback cells; "
          f"{slope_report['river_slope_floored_cells']}/{n_river} river cells "
          f"at the area-consistent floor; median "
          f"{slope_report['river_slope_median']:.2e}", file=sys.stderr)

    # ── Soil parameters from HWSD (SKILL.md "Data Sources": lookup_hwsd) ──
    # The previous build wrote one constant per parameter, which makes every
    # soil-physics lever inert.
    from ki_tools_common.soil_utils import lookup_hwsd
    ksat = np.zeros((ny, nx))
    th_s = np.zeros((ny, nx))
    th_r = np.zeros((ny, nx))
    bc_c = np.zeros((ny, nx))
    n_soil_ok = 0
    for j in range(ny):
        for i in range(nx):
            if mask[j, i] == 0:
                continue
            try:
                s = lookup_hwsd(float(lat_centers[j]), float(lon_centers[i]))
                h = s["hydraulics"]
                # ksat_cm_hr -> mm/day (wflow unit, dt_w026)
                ksat[j, i] = max(1.0, float(h["ksat_cm_hr"]) * 10.0 * 24.0)
                th_s[j, i] = float(h["saturation"])
                th_r[j, i] = max(0.01, float(h["wilting_point"]) * 0.5)
                # Brooks-Corey exponent from clay content (finer -> larger c)
                bc_c[j, i] = float(np.clip(6.0 + 0.18 * float(s["clay"]), 6.0, 20.0))
                n_soil_ok += 1
            except Exception:
                ksat[j, i], th_s[j, i], th_r[j, i], bc_c[j, i] = 100.0, 0.45, 0.05, 10.0
    print(f"  HWSD soil sampled for {n_soil_ok}/{n_cells} cells: "
          f"KsatVer {ksat[mask==1].min():.0f}-{ksat[mask==1].max():.0f} mm/day, "
          f"theta_s {th_s[mask==1].min():.2f}-{th_s[mask==1].max():.2f}", file=sys.stderr)

    # ── Land-surface parameters (dt_w042) ───────────────────────────────
    # These used to be single hard-coded constants over the whole domain, which
    # makes RootingDepth / SoilThickness / the canopy block — the calibration-
    # free controls Imhoff et al. 2020 flags as the most sensitive for discharge
    # — inert, and lets AET pin to PET. Derive them per cell instead.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from derive_landsurface_params import (derive_landsurface_params,
                                           DeriveError)
    # There is deliberately NO uniform-constant mode. A constant land-surface map
    # over a multi-cell mask IS the dt_w015 / dt_w042 defect this build replaces,
    # so shipping it as a supported switch would let the defect be reproduced on
    # request and silently scored. Derivation is the only path; if it cannot
    # resolve its sources the build FAILS.
    try:
        ls, ls_prov = derive_landsurface_params(
            lat_centers, lon_centers, mask,
            config["simulation"]["start_year"],
            config["simulation"]["end_year"],
            resolution=resolution,
            ksat_mm_day=ksat,
            lc_source=args.lc_source,
            lc_dir=args.lc_dir,
            lai_dir=args.lai_dir,
            hwsd_csv=args.hwsd_csv,
        )
    except DeriveError as e:
        # NO fallback to constants: silently substituting a placeholder when
        # the source does not resolve is the dt_w040 failure pattern, and
        # writing uniform maps is the dt_w042 defect this replaces.
        return {"status": "failed",
                "error": f"land-surface derivation failed: {e}"}
    ls_prov["mode"] = "derive"

    # ── Create staticmaps.nc ─────────────────────────────────────────
    ds = xr.Dataset(
        {
            # Mask variables: float64 + NaN for inactive cells, NEVER int 0
            # (SKILL.md critical fact #11 / dt_w035 — 0 is a valid subcatchment
            # id, so int masks make wflow treat every cell as active).
            "wflow_subcatch": (["y", "x"], np.where(mask == 1, 1.0, np.nan)),
            "wflow_dem": (["y", "x"], np.where(mask, dem_grid, -9999.0)),
            "wflow_ldd": (["y", "x"], ldd),
            "Slope": (["y", "x"], np.where(mask, slope_grid, 0.0)),
            "wflow_river": (["y", "x"], np.where(mask == 1, river.astype(float), np.nan)),
            # Land-use related — per-cell GLC_FCS30 sub-grid class fractions
            # (derive_landsurface_params.py). PathFrac/WaterFrac are the
            # impervious/water AREA FRACTIONS, not a dominant-class 0/1.
            "PathFrac": (["y", "x"], ls["PathFrac"]),
            "Sl": (["y", "x"], ls["Sl"]),  # interception, mm/LAI
            "Swood": (["y", "x"], ls["Swood"]),
            "Kext": (["y", "x"], ls["Kext"]),
            "RootingDepth": (["y", "x"], ls["RootingDepth"]),  # mm
            # Soil parameters — KsatVer/theta from HWSD (lookup_hwsd)
            "KsatVer": (["y", "x"], ksat),  # mm/day (dt_w026)
            # SoilThickness = HWSD REF_DEPTH (SHARE-weighted, cm -> mm), NOT a
            # flat 2000 mm; InfiltCapSoil follows the per-cell HWSD KsatVer.
            "SoilThickness": (["y", "x"], ls["SoilThickness"]),  # mm
            "InfiltCapSoil": (["y", "x"], ls["InfiltCapSoil"]),  # mm/day
            "InfiltCapPath": (["y", "x"], np.where(mask, 5.0, 0.0)),  # mm/day
            "f": (["y", "x"], np.where(mask, 0.001, 0.0)),  # 1/mm, Ksat decay
            "MaxLeakage": (["y", "x"], np.where(mask, 0.0, 0.0)),  # mm/day
            "theta_s": (["y", "x"], th_s),  # porosity (HWSD)
            "theta_r": (["y", "x"], th_r),  # residual (HWSD)
            "KsatHorFrac": (["y", "x"], np.where(mask, 100.0, 0.0)),
            # Brooks-Corey exponent — MUST carry a layer dimension (dt_w031)
            "c": (["layer", "y", "x"], np.repeat(bc_c[None, :, :], 4, axis=0)),
            # River parameters
            "N_River": (["y", "x"], np.where(mask, 0.036, 0.0)),  # Manning's n
            "N": (["y", "x"], ls["N"]),  # overland Manning's n, GLC_FCS30-weighted
            "RiverWidth": (["y", "x"], river_width),  # m, W = 2.5*A^0.45
            "RiverLength": (["y", "x"], river_length),  # m, diagonal-aware
            "RiverSlope": (["y", "x"], river_slope),  # from breached DEM
            # Snow parameters
            "cfmax": (["y", "x"], np.where(mask, 3.75, 0.0)),  # mm/degC/day
            "tt": (["y", "x"], np.where(mask, 0.0, 0.0)),  # degC
            "tti": (["y", "x"], np.where(mask, 1.0, 0.0)),  # degC
            "ttm": (["y", "x"], np.where(mask, 0.0, 0.0)),  # degC
            "whc": (["y", "x"], np.where(mask, 0.1, 0.0)),  # fraction
            # Canopy — from the per-cell growing-season mean GLASS LAI:
            # Cmax = 0.935 + 0.498*LAI - 0.00575*LAI^2 and
            # CanopyGapFraction = exp(-Kext*LAI) (van Verseveld et al. 2024)
            "CanopyGapFraction": (["y", "x"], ls["CanopyGapFraction"]),
            "Cmax": (["y", "x"], ls["Cmax"]),
            "WaterFrac": (["y", "x"], ls["WaterFrac"]),
        },
        coords={
            "y": lat_centers,
            "x": lon_centers,
            "layer": np.arange(1, 5),  # wflow requires layer dimension
        },
    )

    ds.attrs["title"] = f"wflow staticmaps for {config['basin']['name']}"
    ds.attrs["source"] = ("HydroCraft manual build: domain and routing network "
                          "from MERIT-Hydro, soil texture + REF_DEPTH from HWSD, "
                          "land surface from GLC_FCS30 30 m sub-grid class "
                          "fractions, canopy from GLASS LAI, river geometry from "
                          "drainage area")
    ds.attrs["landsurface_mode"] = ls_prov.get("mode", "derive")
    ds.attrs["landsurface_provenance"] = json.dumps(ls_prov, default=float)
    ds.attrs["resolution"] = resolution
    ds.attrs["Conventions"] = "CF-1.6"
    # Publish the snapped outlet so downstream tools sample the gauge cell
    # explicitly. Without this s3 has no way to know which cell the gauge is in
    # and can only fall back to a domain-wide reducer, which is not the gauge.
    ds.attrs["outlet_lat"] = float(lat_centers[oj])
    ds.attrs["outlet_lon"] = float(lon_centers[oi])
    ds.attrs["outlet_index_yx"] = [int(oj), int(oi)]

    staticmaps_path = os.path.join(project_dir, "staticmaps.nc")
    ds.to_netcdf(staticmaps_path)

    # Sidecar copy, so the outlet survives even if the NetCDF is regenerated by
    # a tool that does not preserve global attributes.
    with open(os.path.join(project_dir, "outlet.json"), "w") as f:
        json.dump({
            "outlet_lat": float(lat_centers[oj]),
            "outlet_lon": float(lon_centers[oi]),
            "outlet_index_yx": [int(oj), int(oi)],
            "gauge_lat": float(config["basin"]["lat"]),
            "gauge_lon": float(config["basin"]["lon"]),
        }, f, indent=2)

    elapsed = time.time() - start_time

    return {
        "status": "success",
        "method": "manual",
        "project_dir": project_dir,
        "staticmaps_path": staticmaps_path,
        "grid_size": f"{nx} x {ny}",
        "active_cells": n_cells,
        "basin_area_km2": round(basin_area_km2, 1),
        "reference_area_km2": round(expected_km2, 1) if expected_km2 else None,
        "area_error_pct": round(area_err, 1),
        "outlet_lat": float(lat_centers[oj]),
        "outlet_lon": float(lon_centers[oi]),
        "outlet_index_yx": [int(oj), int(oi)],
        "n_outlets": n_outlets,
        "river_cells": n_river,
        # Slope diagnostics — the 1e-4 floor artefact must never be silent again
        # (dt_w040): read river_slope_floored_cells against river_cells.
        **slope_report,
        "landsurface": ls_prov,
        "elapsed_seconds": round(elapsed, 1),
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
    parser.add_argument("--expected_area_km2", type=float, default=0.0,
                        help="Published catchment area of the gauge. Used to pick "
                             "the outlet cell from the snap ladder; falls back to "
                             "the shapefile area when omitted.")
    parser.add_argument("--river_threshold_km2", type=float, default=200.0,
                        help="Contributing area above which a cell is a river cell")
    parser.add_argument("--merit_hydro_dir", type=str, default="",
                        help="Directory of MERIT-Hydro *_dir.tif / *_upa.tif tiles. "
                             "When given, the domain and the routing network are "
                             "upscaled from MERIT's corrected 3-arcsec D8 grid "
                             "instead of being derived from the resampled DEM. "
                             "REQUIRED for low-relief basins (floodplains), where "
                             "coarse-DEM D8 is noise.")
    parser.add_argument("--merit_snap_radius_deg", type=float, default=0.05,
                        help="Pour-point snap radius for MERIT delineation")
    parser.add_argument("--merit_area_tolerance_pct", type=float, default=15.0,
                        help="Allowed deviation of the traced area from --expected_area_km2")
    parser.add_argument("--merit_cell_fraction", type=float, default=0.5,
                        help="Basin fraction a coarse cell needs to be active")
    # NOTE: --landsurface is intentionally single-valued. The removed "constant"
    # choice restored the uniform placeholder maps, i.e. it reproduced the
    # dt_w015 / dt_w042 defect on request; it is not a supported build mode.
    parser.add_argument("--landsurface", choices=["derive"], default="derive",
                        help="Per-cell RootingDepth / SoilThickness / canopy / "
                             "PathFrac / WaterFrac from GLC_FCS30 + GLASS LAI + "
                             "HWSD REF_DEPTH. This is the only supported mode: "
                             "uniform placeholder maps are the dt_w015 / dt_w042 "
                             "defect, not a fallback.")
    parser.add_argument("--lc_source", type=str, default="glcfcs30",
                        choices=["glcfcs30"],
                        help="Land-cover source for the sub-grid class fractions")
    parser.add_argument("--lc_dir", type=str,
                        default="KISSPATH_DATA/vegetation/GLCFCS30",
                        help="GLC_FCS30 30 m tile directory")
    parser.add_argument("--lai_dir", type=str,
                        default="KISSPATH_DATA/vegetation/GLASS_LAI_global",
                        help="GLASS LAI seasonal-composite directory")
    parser.add_argument("--hwsd_csv", type=str,
                        default="KISSPATH_STATIC/HWSD_DATA.csv",
                        help="HWSD attribute table (REF_DEPTH -> SoilThickness)")
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
