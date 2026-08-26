"""
centerline.py — Extract a river centerline (LineString) from a DEM.

Two routes:
  - ``extract_river_centerline_from_dem``: whitebox pipeline
    (fill_depressions -> d8_pointer -> d8_flow_accumulation ->
    extract_streams -> raster_streams_to_vector). Returns the largest
    contiguous stream LineString or a list per the ``select`` mode.
  - ``extract_river_centerline_from_streams``: bypass the whitebox steps
    and use a pre-computed streams raster (e.g., the one ``delineate_basin``
    already produced).
"""

import os
from typing import Dict, List, Optional, Tuple

from .registry import geo_tool


def _vectorize_streams(streams_raster: str, output_dir: str, d8_pointer: str) -> str:
    """Convert a streams raster to a vector shapefile via whitebox."""
    import whitebox

    out_shp = os.path.join(output_dir, "streams.shp")
    wbt = whitebox.WhiteboxTools()
    wbt.set_working_dir(output_dir)
    rc = wbt.raster_streams_to_vector(streams_raster, d8_pointer, out_shp)
    if rc != 0:
        raise RuntimeError(f"raster_streams_to_vector failed with rc={rc}")
    return out_shp


def _pick_main_stem(streams_shp: str, select: str = "longest") -> "shapely.geometry.LineString":
    """Pick a single LineString from the streams shapefile.

    select:
        'longest' — the single longest LineString (suitable for a single-reach
            routing test).
        'merged'  — linemerge all features into one MultiLineString, return the
            largest contiguous component as a LineString.
    """
    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge

    gdf = gpd.read_file(streams_shp)
    if gdf.empty:
        raise RuntimeError(f"streams shapefile {streams_shp} is empty")

    lines = []
    for geom in gdf.geometry:
        if geom is None:
            continue
        if geom.geom_type == "LineString":
            lines.append(geom)
        elif geom.geom_type == "MultiLineString":
            lines.extend(list(geom.geoms))

    if not lines:
        raise RuntimeError("no LineString geometries found in streams shapefile")

    if select == "longest":
        return max(lines, key=lambda g: g.length)
    elif select == "merged":
        merged = linemerge(MultiLineString(lines))
        if isinstance(merged, LineString):
            return merged
        # MultiLineString -> pick longest component
        return max(merged.geoms, key=lambda g: g.length)
    else:
        raise ValueError(f"unknown select mode: {select!r}")


@geo_tool(
    name="extract_river_centerline_from_dem",
    category="hydrology",
    description="Extract a river centerline (LineString) from a DEM using whitebox.",
    requires=["whitebox", "rasterio", "geopandas", "shapely"],
)
def extract_river_centerline_from_dem(
    dem_path: str,
    output_dir: str,
    stream_threshold: int = 100,
    select: str = "longest",
    verbose: bool = False,
) -> Dict:
    """Run the whitebox stream-extraction pipeline and return a single LineString.

    Args:
        dem_path: Path to DEM (.tif).
        output_dir: Where to write whitebox intermediates + the streams shapefile.
        stream_threshold: Flow-accumulation threshold (cells). See
            ``delineate_basin`` for tuning.
        select: 'longest' picks the single longest stream LineString; 'merged'
            linemerges before picking.
        verbose: whitebox verbosity.

    Returns:
        Dict with keys:
            centerline:        shapely.geometry.LineString (in DEM CRS)
            centerline_length: float (in DEM CRS units)
            streams_shp:       path to the full streams shapefile (all features)
            crs:               CRS string of the centerline
    """
    import rasterio
    import whitebox

    if not os.path.isfile(dem_path):
        raise FileNotFoundError(f"DEM not found: {dem_path}")
    os.makedirs(output_dir, exist_ok=True)
    output_dir = os.path.abspath(output_dir)
    dem_path = os.path.abspath(dem_path)

    filled_dem   = os.path.join(output_dir, "dem_filled.tif")
    pointer      = os.path.join(output_dir, "d8_pointer.tif")
    flow_accum   = os.path.join(output_dir, "flow_accum.tif")
    streams_rast = os.path.join(output_dir, "streams.tif")

    wbt = whitebox.WhiteboxTools()
    wbt.set_working_dir(output_dir)
    wbt.set_verbose_mode(verbose)

    def _step(name, rc):
        if rc != 0:
            raise RuntimeError(f"whitebox.{name} failed with rc={rc}")

    # Skip steps that already produced output (cheap re-run)
    if not os.path.isfile(filled_dem):
        _step("fill_depressions", wbt.fill_depressions(dem_path, filled_dem))
    if not os.path.isfile(pointer):
        _step("d8_pointer",       wbt.d8_pointer(filled_dem, pointer))
    if not os.path.isfile(flow_accum):
        _step("d8_flow_accumulation", wbt.d8_flow_accumulation(filled_dem, flow_accum, out_type="cells"))
    if not os.path.isfile(streams_rast):
        _step("extract_streams",  wbt.extract_streams(flow_accum, streams_rast, threshold=stream_threshold))

    streams_shp = _vectorize_streams(streams_rast, output_dir, pointer)
    centerline  = _pick_main_stem(streams_shp, select=select)

    with rasterio.open(dem_path) as src:
        crs = src.crs.to_string() if src.crs else None

    return {
        "centerline":        centerline,
        "centerline_length": float(centerline.length),
        "streams_shp":       streams_shp,
        "crs":               crs,
    }


@geo_tool(
    name="extract_river_centerline_from_streams",
    category="hydrology",
    description="Pick a single river centerline from an existing streams raster + d8 pointer.",
    requires=["whitebox", "rasterio", "geopandas", "shapely"],
)
def extract_river_centerline_from_streams(
    streams_raster: str,
    d8_pointer: str,
    output_dir: str,
    select: str = "longest",
) -> Dict:
    """Reuse the streams raster produced by ``delineate_basin`` rather than
    re-running the whole whitebox pipeline. Same return contract as
    ``extract_river_centerline_from_dem``.
    """
    import rasterio

    if not os.path.isfile(streams_raster):
        raise FileNotFoundError(f"streams raster not found: {streams_raster}")
    if not os.path.isfile(d8_pointer):
        raise FileNotFoundError(f"d8 pointer not found: {d8_pointer}")
    os.makedirs(output_dir, exist_ok=True)
    output_dir = os.path.abspath(output_dir)

    streams_shp = _vectorize_streams(
        os.path.abspath(streams_raster), output_dir, os.path.abspath(d8_pointer)
    )
    centerline  = _pick_main_stem(streams_shp, select=select)

    with rasterio.open(streams_raster) as src:
        crs = src.crs.to_string() if src.crs else None

    return {
        "centerline":        centerline,
        "centerline_length": float(centerline.length),
        "streams_shp":       streams_shp,
        "crs":               crs,
    }
