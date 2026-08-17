"""
profile.py — Sample DEM elevation along an arbitrary LineString.

Distinct from ``cross_sections.py``: that one cuts perpendicular XS lines
*from* a centerline. This one samples a single LineString the caller
already has (e.g., a thalweg, a road, a survey transect).
"""

import os
from typing import Dict, List, Optional, Tuple

from .registry import geo_tool


@geo_tool(
    name="sample_dem_profile",
    category="raster",
    description="Sample DEM elevation along an arbitrary LineString and return distance-elevation pairs.",
    requires=["rasterio", "shapely", "pyproj"],
)
def sample_dem_profile(
    line,
    dem_path: str,
    step: Optional[float] = None,
    line_crs: Optional[str] = None,
) -> Dict:
    """Walk along ``line`` at ``step`` increments, sample DEM at each point.

    Args:
        line: A shapely LineString (caller-supplied; can be a thalweg, road,
            transect, anything).
        dem_path: Path to DEM raster.
        step: Sampling interval (m if CRS is projected). Defaults to half
            the DEM's pixel size.
        line_crs: CRS of ``line``. Reprojected to DEM CRS if different.

    Returns:
        Dict with keys:
            distance:  list[float] — cumulative distance along ``line`` (m)
            elevation: list[float] — DEM elevation at each sample (m, nan for nodata)
            xy:        list[(float, float)] — sample coordinates in DEM CRS
            length:    float — total LineString length (in DEM CRS units)
            n_samples: int
            crs:       DEM CRS string
    """
    import rasterio
    from shapely.ops import transform as shp_transform
    from pyproj import Transformer

    if not os.path.isfile(dem_path):
        raise FileNotFoundError(f"DEM not found: {dem_path}")

    with rasterio.open(dem_path) as src:
        dem_crs = src.crs.to_string() if src.crs else None
        nodata = src.nodata
        pixel_size = max(abs(src.transform.a), abs(src.transform.e))

    if step is None:
        step = pixel_size / 2.0

    if line_crs and dem_crs and line_crs != dem_crs:
        tx = Transformer.from_crs(line_crs, dem_crs, always_xy=True).transform
        line = shp_transform(tx, line)

    L = line.length
    n = max(2, int(L / step) + 1)
    distances: List[float] = []
    xy: List[Tuple[float, float]] = []
    for i in range(n + 1):
        s = i * L / n
        p = line.interpolate(s)
        distances.append(s)
        xy.append((p.x, p.y))

    with rasterio.open(dem_path) as src:
        samples = list(src.sample(xy))

    elevation: List[float] = []
    for z in samples:
        z = float(z[0])
        if nodata is not None and z == nodata:
            z = float("nan")
        elevation.append(z)

    return {
        "distance":  distances,
        "elevation": elevation,
        "xy":        xy,
        "length":    float(L),
        "n_samples": len(distances),
        "crs":       dem_crs,
    }
