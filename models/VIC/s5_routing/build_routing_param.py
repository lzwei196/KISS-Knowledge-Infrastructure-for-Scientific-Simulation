# -*- coding: utf-8 -*-
"""
build_routing_param.py — VIC → Lohmann (route_1.0) routing-parameter builder.

WHY THIS EXISTS
---------------
VIC has NO internal routing. Its only internal `OUT_DISCHARGE` comes from the
optional lake module (dag.yaml: "for non-lake cells streamflow is not produced
internally"). The KI's validated gauge-discharge path is therefore

    vic_classic.exe  ->  7-column flux  ->  route_1.0/rout  ->  daily m3/s

and `rout` needs five parameter files that, before 2026-07-09, existed only as
pre-baked artefacts for Bengbu. Every new basin was blocked on "no tool for
flow-direction file prep". This module closes that gap.

It is a generalised, environment-configurable port of
`skills/routing-run/s5_routing_param/run_build_routing_new.py`, with three
defects fixed (see FIXES below).

WHAT IT PRODUCES  (in $VIC_OUT_ROOT/$VIC_BASIN_NAME/routing_param/)
------------------------------------------------------------------
    <STA>_direc.txt   D8 flow direction on the VIC 0.25° grid (1=N..8=NW, -88=outlet)
    <STA>_frac.txt    fraction of each cell inside the basin polygon
    <STA>_xmask.txt   flow distance through each cell (m)
    <STA>_staloc.txt  station row/col (1-based, row counted from the BOTTOM)
    UH.all            within-cell unit hydrograph (12 rows)
    rout_global.txt   the `rout` control file
    vic_in/, rout_out/  input/output dirs for `rout`

ALGORITHM
---------
1. Read the VIC grid straight from SOIL_PARAM_COMPLETE.txt (cols 3,4 = lat,lon)
   so the routing grid can never drift from the grid VIC actually ran.
2. Rasterise the basin polygon to per-cell area fractions.
3. Obtain a NATIVE-RESOLUTION flow accumulation + basin raster from
   ki_tools_common.terrain_ops.delineate_basin, and mask accumulation to the
   basin so out-of-basin pixels can never contribute.
4. Aggregate flow accumulation (max) and elevation (min) onto the VIC grid.
5. Two-stage D8: each cell drains to its highest-accumulation neighbour, then
   iteratively repair any cell that cannot trace to the outlet. Lohmann's
   convolution silently drops disconnected cells, so full connectivity is a
   hard correctness requirement, not a nicety.

FIXES vs the skills/routing-run original
----------------------------------------
* THE BIG ONE — the original coarsened the DEM to 0.05° (~5.5 km) with an
  AVERAGE resample and ran fill_depressions + d8_flow_accumulation on that,
  over a bbox-cropped (not basin-masked) DEM. Averaging obliterates incised
  gorges, so fill_depressions floods the plateau and reroutes the network. At
  Tangnaihai the result was physically impossible: the gauge cell drained
  1,122 accumulation units while a cell 300 km UPSTREAM drained 3,891, and
  only 51/251 cells initially connected to the outlet. We now reuse the
  native-resolution flow accumulation produced by
  ki_tools_common.terrain_ops.delineate_basin and mask it to the basin
  polygon; the arg-max cell then lands exactly on the gauge (121,290 km2 of
  18.4M x 90m pixels vs 121,972 km2 published) and connectivity is clean.
* OUTLET_LON/OUTLET_LAT were declared but NEVER USED — the outlet was always
  forced to the minimum-elevation cell. That is right only when the gauge sits
  at the basin's lowest point. The outlet is now the maximum-accumulation cell
  (the hydrological definition); VIC_OUTLET_LON/LAT, when supplied, is used to
  CHECK that cell and warn if it is more than one cell away.
* xmask distances were hard-coded to dx=22849 / dy=27734 m — the values for
  0.25° at ~32°N (Huai). At 35.5°N that over-states dx by ~1%; at 50°N by 20%.
  They are now computed from the grid's own centre latitude.
* Simulation years were hard-coded; now VIC_YEAR_START / VIC_YEAR_END.

USAGE
-----
    export VIC_BASIN_NAME=tangnaihai
    export VIC_BASIN_SHP=/.../tangnaihai_boundary.shp
    export VIC_DEM=/.../china_dem_90m.tif
    export VIC_STATION_NAME=TNH
    export VIC_OUTLET_LON=100.1537 VIC_OUTLET_LAT=35.5162
    export VIC_YEAR_START=1984 VIC_YEAR_END=1994
    python3 s5_routing/build_routing_param.py

Then: ln -s <vic flux 7-col dir> routing_param/vic_in
      cd routing_param && KISSPATH_BINARIES/route_1.0/src/rout rout_global.txt
"""

import os
import math
import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask
import geopandas as gpd
from shapely.geometry import box, mapping

# ============================================================================
# Configuration (environment-driven; defaults reproduce the Bengbu recipe)
# ============================================================================
ROOT = os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT")
BASIN = os.environ.get("VIC_BASIN_NAME", "bengbu")
OUT_ROOT = os.environ.get("VIC_OUT_ROOT", os.path.join(ROOT, "outputs"))

SOIL_PARAM_PATH = os.environ.get(
    "VIC_SOIL_PARAM",
    os.path.join(OUT_ROOT, BASIN, "vic_temp", "soil", "SOIL_PARAM_COMPLETE.txt"))
DEM_PATH = os.environ.get("VIC_DEM", os.path.join(ROOT, "data/dem/china_dem_90m/china_dem_90m.tif"))
BASIN_SHP = os.environ["VIC_BASIN_SHP"]
OUTPUT_DIR = os.environ.get("VIC_ROUTING_DIR", os.path.join(OUT_ROOT, BASIN, "routing_param"))

CELL_SIZE = float(os.environ.get("VIC_CELL_SIZE", 0.25))
NODATA_VALUE = 0
STATION_NAME = os.environ.get("VIC_STATION_NAME", "BB")

# Optional explicit outlet (gauge location). Unset -> lowest-elevation cell.
_olon = os.environ.get("VIC_OUTLET_LON")
_olat = os.environ.get("VIC_OUTLET_LAT")
OUTLET_LON = float(_olon) if _olon else None
OUTLET_LAT = float(_olat) if _olat else None

# dt_vic_028 — 1.5 m/s and 800 m^2/s are the values that reproduced Bengbu (121,330 km^2).
# They are NOT a universal default. They set the basin travel time, and because `rout`
# renormalises UH_S (unit_hyd_routines.f) a wrong velocity shows up ONLY in r/NSE and
# NEVER in PBIAS — a plausible water balance is no evidence that they are right.
# After building the grid, compare s5_routing/run_routing.basin_mean_uh_lag() against
# run_routing.observed_lag_days(): at 哈尔滨 (398,330 km^2) this default gave a 6.2 d
# travel time vs a 28 d observed lag, holding zero-lag r at 0.589 and capping NSE at 0.347.
VELOCITY = float(os.environ.get("VIC_ROUT_VELOCITY", 1.5))      # m/s
DIFFUSIVITY = float(os.environ.get("VIC_ROUT_DIFF", 800))       # m^2/s
YEAR_START = int(os.environ.get("VIC_YEAR_START", 1980))
YEAR_END = int(os.environ.get("VIC_YEAR_END", 1990))

WBT_DIR = os.environ.get("WBT_DIR", "KISSPATH_HOME/.local/lib/python3.12/site-packages/whitebox/WBT")

# D8 encoding used by Lohmann route_1.0: 1=N, 2=NE, 3=E, 4=SE, 5=S, 6=SW, 7=W, 8=NW
DIR_OFFSETS = {1: (-1, 0), 2: (-1, 1), 3: (0, 1), 4: (1, 1),
               5: (1, 0), 6: (1, -1), 7: (0, -1), 8: (-1, -1)}


# ============================================================================
# Grid helpers
# ============================================================================
def read_vic_grid_from_soil(soil_path):
    """VIC grid centres from SOIL_PARAM_COMPLETE.txt (col 3 = lat, col 4 = lon)."""
    lats, lons = [], []
    with open(soil_path) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4:
                lats.append(float(parts[2]))
                lons.append(float(parts[3]))
    return np.array(lats), np.array(lons)


def compute_grid_params(lats, lons, cellsize):
    lon_min, lon_max = lons.min(), lons.max()
    lat_min, lat_max = lats.min(), lats.max()
    return {
        'ncols': int(round((lon_max - lon_min) / cellsize)) + 1,
        'nrows': int(round((lat_max - lat_min) / cellsize)) + 1,
        'xllcorner': lon_min - cellsize / 2,
        'yllcorner': lat_min - cellsize / 2,
        'cellsize': cellsize,
        'nodata': NODATA_VALUE,
    }


def rowcol_of(lat, lon, gp):
    """(row, col) of a lat/lon in the ASCII grid (row 0 = north)."""
    col = int(round((lon - gp['xllcorner'] - gp['cellsize'] / 2) / gp['cellsize']))
    row = gp['nrows'] - 1 - int(round((lat - gp['yllcorner'] - gp['cellsize'] / 2) / gp['cellsize']))
    return row, col


def cell_centre(row, col, gp):
    lon = gp['xllcorner'] + (col + 0.5) * gp['cellsize']
    lat = gp['yllcorner'] + (gp['nrows'] - row - 0.5) * gp['cellsize']
    return lat, lon


def create_mask_from_coords(lats, lons, gp):
    m = np.zeros((gp['nrows'], gp['ncols']), dtype=np.int32)
    for lat, lon in zip(lats, lons):
        r, c = rowcol_of(lat, lon, gp)
        if 0 <= r < gp['nrows'] and 0 <= c < gp['ncols']:
            m[r, c] = 1
    return m


def write_ascii_grid(filepath, data, gp, fmt="{:.2f}"):
    with open(filepath, 'w') as f:
        f.write(f"ncols         {gp['ncols']}\n")
        f.write(f"nrows         {gp['nrows']}\n")
        f.write(f"xllcorner     {gp['xllcorner']}\n")
        f.write(f"yllcorner     {gp['yllcorner']}\n")
        f.write(f"cellsize      {gp['cellsize']}\n")
        f.write(f"NODATA_value  {gp['nodata']}\n")
        for row in range(gp['nrows']):
            f.write(" ".join(fmt.format(data[row, col]) for col in range(gp['ncols'])) + "\n")


def build_fraction_grid(shp_path, gp, vic_mask):
    gdf = gpd.read_file(shp_path)
    basin_geom = gdf.union_all() if hasattr(gdf, 'union_all') else gdf.geometry.unary_union
    frac = np.zeros((gp['nrows'], gp['ncols']), dtype=np.float32)
    for row in range(gp['nrows']):
        for col in range(gp['ncols']):
            if vic_mask[row, col] == 0:
                continue
            x_min = gp['xllcorner'] + col * gp['cellsize']
            y_max = gp['yllcorner'] + (gp['nrows'] - row) * gp['cellsize']
            cell = box(x_min, y_max - gp['cellsize'], x_min + gp['cellsize'], y_max)
            inter = basin_geom.intersection(cell)
            if not inter.is_empty:
                frac[row, col] = inter.area / cell.area
    return frac


# ============================================================================
# DEM -> flow accumulation
# ============================================================================
def crop_dem_to_basin(dem_path, shp_path, output_dir):
    out = os.path.join(output_dir, "dem_crop.tif")
    if os.path.exists(out):
        print("  reusing existing dem_crop.tif")
        return out
    gdf = gpd.read_file(shp_path)
    b = gdf.total_bounds
    clip = [mapping(box(b[0] - 0.5, b[1] - 0.5, b[2] + 0.5, b[3] + 0.5))]
    with rasterio.open(dem_path) as src:
        img, tr = rio_mask(src, clip, crop=True)
        meta = src.meta.copy()
        meta.update(driver="GTiff", height=img.shape[1], width=img.shape[2],
                    transform=tr, compress="lzw")
        with rasterio.open(out, "w", **meta) as dst:
            dst.write(img)
    return out


def compute_flow_accum(dem_path, output_dir):
    """Native-resolution flow accumulation + filled DEM, masked to the basin.

    Delegates the hydro-conditioning to the shared KI tool
    ``ki_tools_common.terrain_ops.delineate_basin`` (fill_depressions ->
    d8_pointer -> d8_flow_accumulation -> snap_pour_points -> watershed) rather
    than re-deriving it from a coarsened DEM. Set VIC_FLOW_ACCUM /
    VIC_BASIN_RASTER / VIC_FILLED_DEM to reuse an earlier delineation.

    Returns (elev_basin_tif, accum_basin_tif), both masked to the basin with
    nodata = -9999 outside.
    """
    accum_raw = os.environ.get("VIC_FLOW_ACCUM")
    basin_raw = os.environ.get("VIC_BASIN_RASTER")
    filled_raw = os.environ.get("VIC_FILLED_DEM")

    if not (accum_raw and basin_raw and filled_raw):
        if OUTLET_LON is None or OUTLET_LAT is None:
            raise RuntimeError(
                "No VIC_FLOW_ACCUM/VIC_BASIN_RASTER/VIC_FILLED_DEM supplied and no "
                "VIC_OUTLET_LON/LAT to delineate with. Provide one or the other.")
        from ki_tools_common.terrain_ops import delineate_basin
        print("  running ki_tools_common.terrain_ops.delineate_basin (native resolution)...")
        d = delineate_basin(dem_path=dem_path, pour_point=(OUTLET_LON, OUTLET_LAT),
                            output_dir=output_dir,
                            stream_threshold=int(os.environ.get("VIC_STREAM_THRESHOLD", 20000)),
                            snap_distance_m=float(os.environ.get("VIC_SNAP_DIST_M", 3000)))
        print(f"  delineated basin area = {d['basin_area_km2']:.0f} km2")
        accum_raw, basin_raw, filled_raw = d["flow_accum"], d["basin_raster"], d["filled_dem"]

    accum_basin = os.path.join(output_dir, "flow_accum_basin.tif")
    elev_basin = os.path.join(output_dir, "elev_basin.tif")

    with rasterio.open(basin_raw) as s:
        bas = s.read(1)
        bnod = s.nodata if s.nodata is not None else 0
    inside = (bas > 0) & (bas != bnod)

    for src_path, dst_path in ((accum_raw, accum_basin), (filled_raw, elev_basin)):
        if os.path.exists(dst_path):
            continue
        with rasterio.open(src_path) as s:
            arr = s.read(1).astype("float32")
            prof = s.profile.copy()
        # Out-of-basin pixels MUST be dropped before aggregation: a boundary VIC
        # cell's footprint routinely straddles a much larger neighbouring river
        # (at Tangnaihai, the Yellow River downstream of the gauge), and a max()
        # aggregate would import that river's accumulation into the basin.
        arr = np.where(inside, arr, -9999.0)
        prof.update(dtype="float32", nodata=-9999, compress="lzw")
        with rasterio.open(dst_path, "w", **prof) as d:
            d.write(arr, 1)

    return elev_basin, accum_basin


def PIXEL_KM2(raster_path):
    """Approximate area of one raster pixel in km2 (geographic CRS assumed)."""
    with rasterio.open(raster_path) as src:
        tr = src.transform
        mid_lat = tr.f + tr.e * src.height / 2.0
    dx = abs(tr.a) * 111_320.0 * math.cos(math.radians(mid_lat))
    dy = abs(tr.e) * 110_900.0
    return dx * dy / 1e6


def _aggregate(raster_path, frac, gp, agg='max'):
    with rasterio.open(raster_path) as src:
        data = src.read(1)
        tr = src.transform
    out = np.full((gp['nrows'], gp['ncols']), np.nan)
    for row in range(gp['nrows']):
        for col in range(gp['ncols']):
            if frac[row, col] <= 0:
                continue
            x_min = gp['xllcorner'] + col * gp['cellsize']
            x_max = x_min + gp['cellsize']
            y_max = gp['yllcorner'] + (gp['nrows'] - row) * gp['cellsize']
            y_min = y_max - gp['cellsize']
            c0 = max(0, int((x_min - tr.c) / tr.a));  c1 = min(data.shape[1], int((x_max - tr.c) / tr.a))
            r0 = max(0, int((tr.f - y_max) / (-tr.e))); r1 = min(data.shape[0], int((tr.f - y_min) / (-tr.e)))
            if r0 < r1 and c0 < c1:
                sub = data[r0:r1, c0:c1]
                v = sub[np.isfinite(sub) & (sub > -9999)]
                if agg == 'max':
                    v = v[v > 0]
                if len(v):
                    out[row, col] = np.max(v) if agg == 'max' else np.min(v)
    return out


# ============================================================================
# D8 on the VIC grid
# ============================================================================
def _pick_outlet(vic_accum, vic_elev, frac, gp):
    """The outlet is the maximum-accumulation cell of the basin-masked accum.

    With accumulation correctly restricted to the basin this is exact and needs
    no heuristic. VIC_OUTLET_LON/LAT, when given, is used as an assertion: the
    arg-max cell must be the gauge's own cell (or an immediate neighbour), else
    something upstream is wrong and we say so loudly instead of routing to the
    wrong place.
    """
    masked = np.where(frac > 0, vic_accum, -1.0)
    idx = tuple(int(v) for v in np.unravel_index(np.argmax(masked), masked.shape))
    lat, lon = cell_centre(*idx, gp)
    print(f"  outlet = max-accumulation cell {idx} @ {lon:.4f}E {lat:.4f}N "
          f"(accum={vic_accum[idx]:.0f})")

    if OUTLET_LON is not None and OUTLET_LAT is not None:
        gr, gc = rowcol_of(OUTLET_LAT, OUTLET_LON, gp)
        d = max(abs(gr - idx[0]), abs(gc - idx[1]))
        if d == 0:
            print(f"  gauge check OK: gauge cell ({gr},{gc}) IS the max-accumulation cell")
        elif d == 1:
            print(f"  gauge check: gauge cell ({gr},{gc}) is 1 cell from the outlet {idx} "
                  f"(acceptable at 0.25 deg)")
        else:
            raise RuntimeError(
                f"outlet {idx} is {d} cells from the gauge cell ({gr},{gc}). The flow "
                f"accumulation does not drain through the gauge -- check the DEM, the basin "
                f"mask, or VIC_OUTLET_LON/LAT before routing.")
    else:
        elev = np.where((frac > 0) & np.isfinite(vic_elev), vic_elev, np.inf)
        print(f"  (no gauge coords given; lowest cell elevation = {np.min(elev):.1f} m)")
    return idx


def compute_direction_with_fix(vic_accum, frac, gp, vic_elev=None):
    nrows, ncols = gp['nrows'], gp['ncols']
    direction = np.zeros((nrows, ncols), dtype=np.int32)

    for row in range(nrows):
        for col in range(ncols):
            if frac[row, col] <= 0:
                continue
            best_dir, max_acc = 0, vic_accum[row, col]
            for d, (dr, dc) in DIR_OFFSETS.items():
                r, c = row + dr, col + dc
                if 0 <= r < nrows and 0 <= c < ncols and frac[r, c] > 0 and vic_accum[r, c] > max_acc:
                    max_acc, best_dir = vic_accum[r, c], d
            direction[row, col] = best_dir

    outlet_row, outlet_col = _pick_outlet(vic_accum, vic_elev, frac, gp)
    direction[outlet_row, outlet_col] = -88

    def traces(r, c):
        seen = set()
        for _ in range(500):
            if (r, c) in seen:
                return False
            seen.add((r, c))
            if (r, c) == (outlet_row, outlet_col) or direction[r, c] == -88:
                return True
            d = direction[r, c]
            if d not in DIR_OFFSETS:
                return False
            dr, dc = DIR_OFFSETS[d]
            r, c = r + dr, c + dc
            if not (0 <= r < nrows and 0 <= c < ncols):
                return False
        return False

    cells = [(r, c) for r in range(nrows) for c in range(ncols) if frac[r, c] > 0]
    total = len(cells)
    reaching = sum(traces(r, c) for r, c in cells)
    print(f"  initial connectivity: {reaching}/{total}")

    if reaching < total:
        for it in range(50):
            fixed = 0
            for row, col in cells:
                if traces(row, col):
                    continue
                best_dir, max_acc = 0, -1
                for d, (dr, dc) in DIR_OFFSETS.items():
                    r, c = row + dr, col + dc
                    if 0 <= r < nrows and 0 <= c < ncols and frac[r, c] > 0 and traces(r, c):
                        if vic_accum[r, c] > max_acc:
                            max_acc, best_dir = vic_accum[r, c], d
                if best_dir:
                    direction[row, col] = best_dir
                    fixed += 1
            if fixed == 0:
                break
            print(f"    repair iteration {it+1}: fixed {fixed} cells")
        reaching = sum(traces(r, c) for r, c in cells)
        print(f"  final connectivity: {reaching}/{total}")

    return direction, outlet_row, outlet_col, reaching, total


def compute_xmask(direction, frac, gp):
    """Flow distance per cell (m), from the grid's own centre latitude."""
    mid_lat = gp['yllcorner'] + gp['nrows'] * gp['cellsize'] / 2.0
    dy = gp['cellsize'] * 110_900.0
    dx = gp['cellsize'] * 111_320.0 * math.cos(math.radians(mid_lat))
    diag = math.hypot(dx, dy)
    print(f"  xmask: dx={dx:.0f} dy={dy:.0f} diag={diag:.0f} m (mid_lat={mid_lat:.2f})")
    dist = {1: dy, 2: diag, 3: dx, 4: diag, 5: dy, 6: diag, 7: dx, 8: diag}
    xmask = np.zeros(direction.shape, dtype=np.float32)
    for row in range(gp['nrows']):
        for col in range(gp['ncols']):
            if frac[row, col] > 0:
                xmask[row, col] = dist.get(abs(int(direction[row, col])), dx)
    return xmask


def write_staloc(filepath, station, outlet_row, outlet_col, nrows):
    with open(filepath, 'w') as f:
        f.write(f"1 {station} {outlet_col + 1} {nrows - outlet_row} -9999\n")
        f.write("NONE\n")   # mandatory: tells rout to recompute UH_S


def write_uh_file(filepath):
    for i, v in enumerate([0.15, 0.40, 0.25, 0.10, 0.06, 0.03, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0]):
        mode = 'w' if i == 0 else 'a'
        with open(filepath, mode) as f:
            f.write(f"   {i}   {v:.2f}\n")


def write_rout_global(filepath, station):
    with open(filepath, 'w') as f:
        f.write(f"""# Routing Information File for {station}
# NAME OF FLOW DIRECTION FILE
./{station}_direc.txt
# NAME OF VELOCITY FILE
.false.
{VELOCITY}
# NAME OF DIFF FILE
.false.
{DIFFUSIVITY}
# NAME OF XMASK FILE
.true.
./{station}_xmask.txt
# NAME OF FRACTION FILE
.true.
./{station}_frac.txt
# NAME OF STATION FILE
./{station}_staloc.txt
# PATH OF INPUT FILES AND PRECISION
./vic_in/fluxes_
4
# PATH OF OUTPUT FILES
./rout_out/
# YEAR AND MONTH OF VIC OUTPUT TO ROUTE & ROUTED OUTPUT TO WRITE
{YEAR_START} 01 {YEAR_END} 12
{YEAR_START} 01 {YEAR_END} 12
# NAME OF UNIT HYDROGRAPH FILE
./UH.all
""")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    temp = os.path.join(OUTPUT_DIR, "temp")
    os.makedirs(temp, exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "rout_out"), exist_ok=True)

    print(f"[1] VIC grid from {SOIL_PARAM_PATH}")
    lats, lons = read_vic_grid_from_soil(SOIL_PARAM_PATH)
    print(f"    {len(lats)} cells, lon {lons.min():.3f}..{lons.max():.3f}, lat {lats.min():.3f}..{lats.max():.3f}")

    gp = compute_grid_params(lats, lons, CELL_SIZE)
    print(f"[2] grid {gp['nrows']} x {gp['ncols']}, ll=({gp['xllcorner']}, {gp['yllcorner']})")

    vic_mask = create_mask_from_coords(lats, lons, gp)
    print(f"[3] mask cells: {vic_mask.sum()}")

    frac = build_fraction_grid(BASIN_SHP, gp, vic_mask)
    print(f"[4] frac>0 cells: {(frac > 0).sum()}")

    dem_crop = crop_dem_to_basin(DEM_PATH, BASIN_SHP, temp)
    print("[5] DEM cropped")

    elev_basin, accum_basin = compute_flow_accum(dem_crop, temp)
    print("[6] basin-masked flow accumulation ready")

    vic_accum = _aggregate(accum_basin, frac, gp, 'max')
    vic_accum[np.isnan(vic_accum)] = 0
    vic_elev = _aggregate(elev_basin, frac, gp, 'min')
    print(f"[7] max accum {vic_accum.max():.0f} px "
          f"(~{vic_accum.max() * PIXEL_KM2(accum_basin):.0f} km2); "
          f"elev {np.nanmin(vic_elev):.0f}..{np.nanmax(vic_elev):.0f} m")

    print("[8] D8 directions")
    direction, orow, ocol, reaching, total = compute_direction_with_fix(vic_accum, frac, gp, vic_elev)
    if reaching < total:
        raise RuntimeError(
            f"routing network not fully connected ({reaching}/{total}); "
            "rout would silently drop the unconnected cells")

    xmask = compute_xmask(direction, frac, gp)

    print("[9] writing parameter files")
    write_ascii_grid(os.path.join(OUTPUT_DIR, f"{STATION_NAME}_direc.txt"), direction, gp, "{:.0f}")
    write_ascii_grid(os.path.join(OUTPUT_DIR, f"{STATION_NAME}_frac.txt"), frac, gp, "{:.2f}")
    write_ascii_grid(os.path.join(OUTPUT_DIR, f"{STATION_NAME}_xmask.txt"), xmask, gp, "{:.0f}")
    write_staloc(os.path.join(OUTPUT_DIR, f"{STATION_NAME}_staloc.txt"), STATION_NAME, orow, ocol, gp['nrows'])
    write_uh_file(os.path.join(OUTPUT_DIR, "UH.all"))
    write_rout_global(os.path.join(OUTPUT_DIR, "rout_global.txt"), STATION_NAME)

    lat, lon = cell_centre(orow, ocol, gp)
    print(f"\nDONE -> {OUTPUT_DIR}")
    print(f"  station {STATION_NAME} at staloc col={ocol+1} row={gp['nrows']-orow} "
          f"({lon:.4f}E, {lat:.4f}N); connectivity {reaching}/{total}")


if __name__ == "__main__":
    main()
