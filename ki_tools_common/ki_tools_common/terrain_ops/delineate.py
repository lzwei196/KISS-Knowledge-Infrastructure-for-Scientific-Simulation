"""
delineate.py — Watershed/basin delineation from a DEM + pour point.

Wraps the standard whitebox-tools pipeline:
    fill_depressions -> d8_pointer -> d8_flow_accumulation -> extract_streams
    -> snap_pour_points -> watershed

All intermediates are written to ``output_dir`` so they can be inspected /
reused. Returns a dict with paths + basin area (km²).
"""

import math
import os
import tempfile
from typing import Dict, Optional, Tuple

from .registry import geo_tool


@geo_tool(
    name="delineate_basin",
    category="hydrology",
    description="Delineate a watershed boundary from a DEM and pour point using whitebox-tools.",
    requires=["whitebox", "rasterio", "geopandas", "shapely"],
)
def delineate_basin(
    dem_path: str,
    pour_point: Tuple[float, float],
    output_dir: str,
    stream_threshold: int = 100,
    snap_distance_m: float = 1000.0,
    pour_point_crs: str = "EPSG:4326",
    verbose: bool = False,
) -> Dict:
    """Delineate a watershed from a DEM and a single pour point.

    Args:
        dem_path: Absolute path to a DEM raster readable by whitebox (.tif).
        pour_point: (x, y) of the pour point in ``pour_point_crs``. For
            EPSG:4326 this is (lon, lat).
        output_dir: Directory for outputs. Created if absent.
        stream_threshold: Flow-accumulation cells required to qualify as a
            stream. Tune by DEM resolution: 100 cells is reasonable at
            ~30 m; raise it for coarser DEMs.
        snap_distance_m: Max distance (m) to snap the pour point onto the
            nearest stream cell. Snapping is essential — an unsnapped pour
            point usually lands off-channel and delineates an empty basin.
        pour_point_crs: CRS of ``pour_point``. Reprojected to the DEM's CRS
            automatically.
        verbose: If True, whitebox logs to stderr.

    Returns:
        Dict with keys:
            basin_raster:   path to the watershed raster (1 inside basin, 0 else)
            streams_raster: path to the stream-network raster
            d8_pointer:     path to the D8 flow-direction raster
            flow_accum:     path to the flow-accumulation raster
            snapped_pour:   path to the snapped pour-point shapefile
            basin_area_km2: float, area of the basin in km²

    Raises:
        FileNotFoundError: dem_path does not exist
        RuntimeError: whitebox step failed (rc != 0); message names the failed step
    """
    import rasterio
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point
    import whitebox

    if not os.path.isfile(dem_path):
        raise FileNotFoundError(f"DEM not found: {dem_path}")

    os.makedirs(output_dir, exist_ok=True)
    output_dir = os.path.abspath(output_dir)
    dem_path = os.path.abspath(dem_path)

    # Reproject pour point to DEM CRS if needed
    with rasterio.open(dem_path) as src:
        dem_crs = src.crs.to_string() if src.crs else None
        dem_is_geographic = src.crs.is_geographic if src.crs else False
        # Use the pour-point latitude (after reprojection) for the deg->m factor,
        # not the raster centroid — important for tall rasters.
        pour_lat_for_scale = pour_point[1] if pour_point_crs == "EPSG:4326" else None

    pour_geom = Point(pour_point[0], pour_point[1])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[pour_geom], crs=pour_point_crs)
    if dem_crs and pour_point_crs != dem_crs:
        gdf = gdf.to_crs(dem_crs)

    # snap_distance_m is documented in METRES. whitebox interprets the
    # snap_dist arg in the DEM's CRS units. If the DEM is geographic (degrees),
    # convert metres -> degrees at the pour-point latitude. (Otherwise — projected
    # DEM in metres — pass through unchanged.) Without this conversion a
    # snap_dist of 500 m on a 4326 DEM becomes 500 *degrees*, scans the whole
    # world, and hangs for minutes.
    if dem_is_geographic:
        import math
        if pour_lat_for_scale is None:
            # Use the centroid of the (now-DEM-CRS) pour-point as a fallback
            pour_lat_for_scale = gdf.geometry.iloc[0].y
        # 1 deg lat ≈ 111 km; 1 deg lon shrinks with cos(lat).
        # Use the lon-direction scale because snap_dist is isotropic and lon is
        # the tighter constraint at mid/high latitudes.
        m_per_deg = 111_000.0 * max(0.1, math.cos(math.radians(pour_lat_for_scale)))
        snap_dist_crs = snap_distance_m / m_per_deg
    else:
        snap_dist_crs = snap_distance_m

    pour_shp = os.path.join(output_dir, "pour_point.shp")
    gdf.to_file(pour_shp)

    # Output paths
    filled_dem    = os.path.join(output_dir, "dem_filled.tif")
    pointer       = os.path.join(output_dir, "d8_pointer.tif")
    flow_accum    = os.path.join(output_dir, "flow_accum.tif")
    streams_rast  = os.path.join(output_dir, "streams.tif")
    snapped_shp   = os.path.join(output_dir, "pour_point_snapped.shp")
    basin_rast    = os.path.join(output_dir, "basin.tif")

    wbt = whitebox.WhiteboxTools()
    wbt.set_working_dir(output_dir)
    wbt.set_verbose_mode(verbose)

    def _step(name, rc):
        if rc != 0:
            raise RuntimeError(f"whitebox.{name} failed with rc={rc}")

    _step("fill_depressions",     wbt.fill_depressions(dem_path, filled_dem))
    _step("d8_pointer",           wbt.d8_pointer(filled_dem, pointer))
    _step("d8_flow_accumulation", wbt.d8_flow_accumulation(filled_dem, flow_accum, out_type="cells"))
    _step("extract_streams",      wbt.extract_streams(flow_accum, streams_rast, threshold=stream_threshold))
    _step("snap_pour_points",     wbt.snap_pour_points(pour_shp, flow_accum, snapped_shp, snap_dist=snap_dist_crs))
    _step("watershed",            wbt.watershed(pointer, snapped_shp, basin_rast))

    # Compute basin area from the raster
    with rasterio.open(basin_rast) as src:
        basin = src.read(1)
        # whitebox watershed labels basin cells with the pour-point ID (1)
        # and background with the raster's nodata or 0.
        nodata = src.nodata if src.nodata is not None else 0
        n_basin_cells = int(np.sum((basin != nodata) & (basin > 0)))
        # Pixel area: |a * e - b * d| from the affine, in CRS units
        a = src.transform
        pixel_area = abs(a.a * a.e - a.b * a.d)
        # If the DEM is in a geographic CRS (deg), this is deg² — caller is
        # responsible for using a projected DEM for accurate area.
        if src.crs and src.crs.is_geographic:
            # Approximate: 1° ≈ 111 km at mid-latitudes
            mid_lat = (a.f + a.e * src.height / 2)
            km_per_deg_lat = 111.0
            km_per_deg_lon = 111.0 * np.cos(np.radians(mid_lat))
            area_km2 = n_basin_cells * pixel_area * km_per_deg_lat * km_per_deg_lon
        else:
            area_km2 = n_basin_cells * pixel_area / 1e6  # m² -> km²

    # Vector boundary. Downstream consumers (CRHM create_hru_config, any
    # rasterio.mask clip) need a POLYGON, not the raster mask, so polygonize
    # here once instead of every caller re-implementing it.
    basin_vec = os.path.join(output_dir, "basin.geojson")
    try:
        from rasterio import features as _features
        from shapely.geometry import shape as _shape
        with rasterio.open(basin_rast) as src:
            arr = src.read(1)
            nodata = src.nodata if src.nodata is not None else 0
            mask = (arr != nodata) & (arr > 0)
            geoms = [_shape(g) for g, v in _features.shapes(
                mask.astype("uint8"), mask=mask, transform=src.transform) if v == 1]
            crs = src.crs
        if geoms:
            from shapely.ops import unary_union
            gpd.GeoDataFrame({"id": [1]}, geometry=[unary_union(geoms)],
                             crs=crs).to_file(basin_vec, driver="GeoJSON")
        else:
            basin_vec = None
    except Exception:
        basin_vec = None

    return {
        "basin_raster":   basin_rast,
        "basin_vector":   basin_vec,
        "streams_raster": streams_rast,
        "d8_pointer":     pointer,
        "flow_accum":     flow_accum,
        "filled_dem":     filled_dem,
        "snapped_pour":   snapped_shp,
        "basin_area_km2": float(area_km2),
    }


# --------------------------------------------------------------------------- #
# MERIT-Hydro delineation (flow-direction tracing, no DEM conditioning).
# --------------------------------------------------------------------------- #
MERIT_D8_OFFSETS = {
    1: (0, 1),     # east
    2: (1, 1),     # southeast
    4: (1, 0),     # south
    8: (1, -1),    # southwest
    16: (0, -1),   # west
    32: (-1, -1),  # northwest
    64: (-1, 0),   # north
    128: (-1, 1),  # northeast
}


def _merit_tiles_for_bbox(merit_dir, bbox, kind):
    """MERIT-Hydro 5x5-degree tile paths covering bbox=(minlon,minlat,maxlon,maxlat).

    Accepts either a flat directory of ``<tile>_<kind>.tif`` or the tar-extracted
    ``<kind>_nXXeYYY/`` subdirectory layout.
    """
    import glob
    minlon, minlat, maxlon, maxlat = bbox
    want = []
    lat0 = int(math.floor(minlat / 5.0) * 5)
    lon0 = int(math.floor(minlon / 5.0) * 5)
    lat1 = int(math.floor(maxlat / 5.0) * 5)
    lon1 = int(math.floor(maxlon / 5.0) * 5)
    for la in range(lat0, lat1 + 1, 5):
        for lo in range(lon0, lon1 + 1, 5):
            ns = "n" if la >= 0 else "s"
            ew = "e" if lo >= 0 else "w"
            tile = f"{ns}{abs(la):02d}{ew}{abs(lo):03d}"
            hits = glob.glob(os.path.join(merit_dir, f"{tile}_{kind}.tif")) or \
                glob.glob(os.path.join(merit_dir, "**", f"{tile}_{kind}.tif"),
                          recursive=True)
            if hits:
                want.append(hits[0])
    if not want:
        raise FileNotFoundError(
            f"no MERIT-Hydro '{kind}' tiles found under {merit_dir} for bbox {bbox}")
    return sorted(set(want))


@geo_tool(
    name="delineate_basin_merit_hydro",
    category="hydrology",
    description=("Delineate a watershed by tracing MERIT-Hydro D8 flow directions "
                 "upstream from a pour point. Correct in flat/plain basins where "
                 "DEM-conditioning delineation fails."),
    requires=["rasterio", "numpy"],
)
def delineate_basin_merit_hydro(
    merit_hydro_dir: str,
    pour_point: Tuple[float, float],
    bbox: Tuple[float, float, float, float],
    output_dir: str,
    snap_radius_deg: float = 0.05,
    expected_area_km2: Optional[float] = None,
    area_tolerance_pct: float = 10.0,
    verbose: bool = True,
) -> Dict:
    """Trace a basin upstream from a pour point on MERIT-Hydro flow directions.

    ``delineate_basin`` conditions a raw DEM (fill -> D8 -> accumulation). In
    low-relief basins that conditioning invents drainage divides: on the Huai
    plain it returned 18,110 km² for a gauge whose true catchment is 30,845 km²,
    silently dropping every northern tributary. MERIT-Hydro instead ships a
    hydrologically CORRECTED D8 flow-direction grid (``dir``) plus its own
    upstream-area grid (``upa``), so the basin is obtained exactly by walking
    the flow network upstream — no conditioning, no invented divides.

    The pour point is snapped within ``snap_radius_deg`` to the cell of maximum
    ``upa`` (the channel), which is also read back as an INDEPENDENT check on
    the traced area: MERIT's own upstream area at the outlet must agree with the
    number of traced cells. When ``expected_area_km2`` is given, a deviation
    beyond ``area_tolerance_pct`` raises rather than returning a wrong basin.

    Args:
        merit_hydro_dir: Directory holding MERIT-Hydro ``*_dir.tif`` and
            ``*_upa.tif`` tiles (flat or tar-extracted subdirs).
        pour_point: (lon, lat) of the gauge, EPSG:4326.
        bbox: (minlon, minlat, maxlon, maxlat) search extent. Must comfortably
            contain the basin — the trace stops at the window edge.
        output_dir: Directory for the basin mask GeoTIFF.
        snap_radius_deg: Radius to snap the pour point onto the channel.
        expected_area_km2: Known catchment area for validation (optional).
        area_tolerance_pct: Allowed deviation from ``expected_area_km2``.

    Returns:
        dict with ``basin_raster`` (uint8 mask GeoTIFF), ``basin_area_km2``
        (traced), ``merit_upa_km2`` (independent MERIT value at the snapped
        outlet), ``n_cells``, ``outlet_lon``/``outlet_lat`` (snapped) and
        ``area_check_pct``.
    """
    import numpy as np
    import rasterio
    from rasterio.merge import merge as rio_merge

    os.makedirs(output_dir, exist_ok=True)
    lon, lat = pour_point

    dir_tiles = _merit_tiles_for_bbox(merit_hydro_dir, bbox, "dir")
    upa_tiles = _merit_tiles_for_bbox(merit_hydro_dir, bbox, "upa")
    if verbose:
        print(f"[merit-delineate] dir tiles: {[os.path.basename(t) for t in dir_tiles]}")

    def _window_mosaic(tiles):
        srcs = [rasterio.open(t) for t in tiles]
        arr, transform = rio_merge(srcs, bounds=bbox)
        for s in srcs:
            s.close()
        return arr[0], transform

    d8, transform = _window_mosaic(dir_tiles)
    upa, _ = _window_mosaic(upa_tiles)
    nrow, ncol = d8.shape
    inv = ~transform

    def rc_of(x, y):
        c, r = inv * (x, y)
        return int(math.floor(r)), int(math.floor(c))

    # ---- snap the pour point to the channel (max upstream area) ------------ #
    r0, c0 = rc_of(lon, lat)
    px = abs(transform.a)
    rad = max(1, int(round(snap_radius_deg / px)))
    r_lo, r_hi = max(0, r0 - rad), min(nrow, r0 + rad + 1)
    c_lo, c_hi = max(0, c0 - rad), min(ncol, c0 + rad + 1)
    sub = upa[r_lo:r_hi, c_lo:c_hi]
    if sub.size == 0:
        raise ValueError(f"pour point {pour_point} outside bbox {bbox}")
    k = int(np.nanargmax(np.where(np.isfinite(sub), sub, -np.inf)))
    dr, dc = np.unravel_index(k, sub.shape)
    r_out, c_out = r_lo + int(dr), c_lo + int(dc)
    merit_upa = float(upa[r_out, c_out])
    out_x, out_y = transform * (c_out + 0.5, r_out + 0.5)
    if verbose:
        print(f"[merit-delineate] outlet snapped to {out_y:.5f},{out_x:.5f} "
              f"(MERIT upa {merit_upa:,.0f} km2)")

    # ---- trace upstream ---------------------------------------------------- #
    # A neighbour p belongs to the basin iff its D8 direction points AT the cell
    # already in the basin. Iterative stack (no recursion: basins reach millions
    # of cells and CPython's frame limit is ~1000).
    mask = np.zeros((nrow, ncol), dtype=np.uint8)
    mask[r_out, c_out] = 1
    stack = [(r_out, c_out)]
    nbrs = [(dr_, dc_, code) for code, (dr_, dc_) in MERIT_D8_OFFSETS.items()]
    while stack:
        r, c = stack.pop()
        for dr_, dc_, code in nbrs:
            # neighbour at (r-dr_, c-dc_) flows INTO (r, c) when its direction
            # code is the offset pointing back to (r, c).
            nr, nc = r - dr_, c - dc_
            if 0 <= nr < nrow and 0 <= nc < ncol and not mask[nr, nc]:
                if int(d8[nr, nc]) == code:
                    mask[nr, nc] = 1
                    stack.append((nr, nc))

    n_cells = int(mask.sum())
    # Per-row cos(lat) cell area — 3 arcsec cells are not equal-area.
    rows = np.arange(nrow)
    _, ys = transform * (np.zeros(nrow), rows + 0.5)
    ys = np.asarray(ys, dtype=float)
    cell_km2 = (px * 111.32) * (px * 111.32 * np.cos(np.radians(ys)))
    area_km2 = float((mask.sum(axis=1) * cell_km2).sum())

    check = 100.0 * (area_km2 - merit_upa) / merit_upa if merit_upa > 0 else float("nan")
    if verbose:
        print(f"[merit-delineate] traced {n_cells:,} cells = {area_km2:,.0f} km2 "
              f"(vs MERIT upa {merit_upa:,.0f} km2, {check:+.1f}%)")
    if abs(check) > 5.0:
        raise RuntimeError(
            f"traced area {area_km2:,.0f} km2 disagrees with MERIT's own upstream "
            f"area {merit_upa:,.0f} km2 by {check:+.1f}% — the trace likely hit the "
            f"bbox edge. Widen `bbox`.")
    if expected_area_km2 and expected_area_km2 > 0:
        dev = 100.0 * (area_km2 - expected_area_km2) / expected_area_km2
        if abs(dev) > area_tolerance_pct:
            raise RuntimeError(
                f"delineated area {area_km2:,.0f} km2 deviates {dev:+.1f}% from the "
                f"expected {expected_area_km2:,.0f} km2 (tolerance "
                f"+-{area_tolerance_pct}%). Check the pour point / snap radius.")
        if verbose:
            print(f"[merit-delineate] area check vs expected "
                  f"{expected_area_km2:,.0f} km2: {dev:+.1f}% OK")

    out_tif = os.path.join(output_dir, "basin_merit.tif")
    profile = {
        "driver": "GTiff", "height": nrow, "width": ncol, "count": 1,
        "dtype": "uint8", "crs": "EPSG:4326", "transform": transform,
        "nodata": 0, "compress": "deflate",
    }
    with rasterio.open(out_tif, "w", **profile) as dst:
        dst.write(mask, 1)

    return {
        "basin_raster": out_tif,
        "basin_area_km2": area_km2,
        "merit_upa_km2": merit_upa,
        "n_cells": n_cells,
        "outlet_lon": float(out_x),
        "outlet_lat": float(out_y),
        "area_check_pct": check,
    }
