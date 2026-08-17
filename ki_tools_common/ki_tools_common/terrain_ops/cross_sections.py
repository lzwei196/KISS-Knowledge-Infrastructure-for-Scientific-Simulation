"""
cross_sections.py — Cut perpendicular cross sections from a river centerline.

This is the missing primitive across the public GIS-agent ecosystem (verified
2026-06-04 across GeoAgent, gdal-mcp, gis-mcp, ras-commander, watershed-workflow:
none ship a cut-XS-from-DEM operation that runs headless). Built in-house on
top of shapely + rasterio.

Algorithm:
  1. Resample the centerline to evenly-spaced points (interval = ``spacing``).
  2. At each point, compute the local tangent (forward-difference of the next
     two centerline vertices, or backward-difference at the last vertex).
  3. The perpendicular is the tangent rotated 90°. Build a LineString of
     length 2 * ``half_width`` centered on the point.
  4. Densify each XS line to ``sample_step`` and sample DEM elevation at
     every densified vertex via ``rasterio.sample``.
  5. Emit station (distance along the XS from the left bank) + elevation
     tables, ready to drop into HEC-RAS .g01 / ANUGA mesh inputs.

Output schema is HEC-RAS-friendly: each XS is a list of (station_m, elev_m)
pairs, ordered left bank to right bank.
"""

import os
from typing import Dict, List, Optional, Sequence, Tuple

from .registry import geo_tool


def _resample_linestring(line, spacing: float):
    """Return a list of shapely Points evenly spaced along ``line``."""
    from shapely.geometry import Point
    n_pts = max(2, int(round(line.length / spacing)) + 1)
    return [line.interpolate(i * line.length / (n_pts - 1)) for i in range(n_pts)]


def _local_tangent(line, distance: float, eps: float = 1.0):
    """Unit tangent (dx, dy) at the given distance along ``line``.

    Uses a centered finite difference of length 2 * eps. Falls back to
    forward/backward difference near the endpoints.
    """
    L = line.length
    d_a = max(0.0, distance - eps)
    d_b = min(L, distance + eps)
    pa = line.interpolate(d_a)
    pb = line.interpolate(d_b)
    dx, dy = pb.x - pa.x, pb.y - pa.y
    norm = (dx ** 2 + dy ** 2) ** 0.5
    if norm == 0:
        return (1.0, 0.0)  # degenerate; shouldn't happen on real streams
    return (dx / norm, dy / norm)


def _perpendicular_xs(center, tangent, half_width: float):
    """Build an XS LineString perpendicular to ``tangent``, centered on ``center``,
    of total length 2 * half_width. Left bank is the first endpoint, right the last
    (left = 90° CCW from tangent direction)."""
    from shapely.geometry import LineString
    tx, ty = tangent
    # Perpendicular: rotate tangent 90° CCW -> (-ty, tx)
    px, py = -ty, tx
    x0 = center.x - px * half_width   # right bank end (CW from tangent)
    y0 = center.y - py * half_width
    x1 = center.x + px * half_width   # left bank end (CCW from tangent)
    y1 = center.y + py * half_width
    # We want left bank first, so emit (x1, y1) -> (x0, y0)? No: convention
    # below treats "station 0" as the START of the LineString. We'll start
    # at the LEFT bank so station increases toward the right.
    return LineString([(x1, y1), (x0, y0)])


def _densify_line(line, step: float) -> List[Tuple[float, float, float]]:
    """Return (x, y, station) at every step along ``line`` (station 0 at start)."""
    n = max(2, int(line.length // step) + 1)
    out = []
    for i in range(n + 1):
        s = i * line.length / n
        p = line.interpolate(s)
        out.append((p.x, p.y, s))
    return out


@geo_tool(
    name="cut_cross_sections",
    category="hydrology",
    description="Cut perpendicular cross sections along a river centerline and sample a DEM at each. Returns HEC-RAS-style station-elevation tables.",
    requires=["rasterio", "shapely", "numpy"],
)
def cut_cross_sections(
    centerline,
    dem_path: str,
    spacing: float,
    half_width: float,
    sample_step: Optional[float] = None,
    centerline_crs: Optional[str] = None,
    tangent_eps: float = 1.0,
    skip_first: float = 0.0,
    skip_last: float = 0.0,
) -> Dict:
    """Cut evenly-spaced perpendicular XS lines along ``centerline`` and sample
    elevations from ``dem_path``.

    Args:
        centerline: A shapely LineString (centerline geometry, expected to be
            in the same CRS as the DEM unless ``centerline_crs`` is given and
            differs — in which case the centerline is reprojected).
        dem_path: Path to the DEM raster.
        spacing: Distance between consecutive XS lines along the centerline
            (m if the CRS is projected). For routing applications, 200–500 m
            is typical on a 30 m DEM.
        half_width: XS extent on each side of the centerline (m). The total
            XS length is ``2 * half_width``. Pick large enough to cover the
            full floodplain at the design discharge.
        sample_step: Distance between DEM samples along each XS (m). Defaults
            to half of the DEM's pixel size.
        centerline_crs: CRS of ``centerline`` (e.g., "EPSG:4326"). If absent,
            assumed to match the DEM.
        tangent_eps: Half-length (m) of the finite-difference window used to
            estimate the centerline tangent. Larger smooths over centerline
            wiggle; smaller follows curvature more tightly.
        skip_first: Distance from the centerline start to skip before the
            first XS (m). Useful when the upstream end is a noisy DEM artefact.
        skip_last: Distance from the centerline end to skip after the last XS.

    Returns:
        Dict with keys:
            cross_sections:     list of dicts, each:
                {
                    "id": int,                      # 0-indexed along centerline
                    "station_along_river": float,   # m, from centerline start
                    "center_xy": (float, float),    # XS midpoint in DEM CRS
                    "xs_line_wkt": str,             # LineString WKT in DEM CRS
                    "station_elevation": [(s, z), ...],  # left -> right bank
                }
            n_cross_sections:   int
            crs:                CRS string (DEM CRS, all geometries in this CRS)

    Raises:
        FileNotFoundError: DEM missing
        ValueError: half_width <= 0 or spacing <= 0
    """
    import numpy as np
    import rasterio
    from shapely.geometry import LineString
    from shapely.ops import transform as shp_transform
    from pyproj import Transformer

    if half_width <= 0:
        raise ValueError(f"half_width must be > 0, got {half_width}")
    if spacing <= 0:
        raise ValueError(f"spacing must be > 0, got {spacing}")
    if not os.path.isfile(dem_path):
        raise FileNotFoundError(f"DEM not found: {dem_path}")

    with rasterio.open(dem_path) as src:
        dem_crs = src.crs.to_string() if src.crs else None
        pixel_size = max(abs(src.transform.a), abs(src.transform.e))

    if sample_step is None:
        sample_step = pixel_size / 2.0

    # Reproject centerline into DEM CRS if needed
    if centerline_crs and dem_crs and centerline_crs != dem_crs:
        tx = Transformer.from_crs(centerline_crs, dem_crs, always_xy=True).transform
        centerline = shp_transform(tx, centerline)

    # Trim
    if skip_first > 0 or skip_last > 0:
        L = centerline.length
        if skip_first + skip_last >= L:
            raise ValueError("skip_first + skip_last exceeds centerline length")
        # Re-sample to trimmed start/end
        n_dense = max(2, int(L / (sample_step or 1)) + 1)
        coords = [centerline.interpolate(s).coords[0]
                  for s in np.linspace(skip_first, L - skip_last, n_dense)]
        centerline = LineString(coords)

    # Distances along centerline at which to place XS midpoints
    L = centerline.length
    n_xs = max(2, int(L / spacing) + 1)
    distances = [i * L / (n_xs - 1) for i in range(n_xs)]

    sections = []
    with rasterio.open(dem_path) as src:
        for idx, d in enumerate(distances):
            center = centerline.interpolate(d)
            tang = _local_tangent(centerline, d, eps=tangent_eps)
            xs_line = _perpendicular_xs(center, tang, half_width)
            samples = _densify_line(xs_line, sample_step)

            xy = [(x, y) for (x, y, _s) in samples]
            elevs = list(src.sample(xy))  # list of np.ndarray, single-band
            # Handle nodata: rasterio.sample returns nodata as np.float; keep np.nan
            nodata = src.nodata
            station_elev = []
            for (x, y, s), z in zip(samples, elevs):
                z = float(z[0])
                if nodata is not None and z == nodata:
                    z = float("nan")
                station_elev.append((float(s), z))

            sections.append({
                "id": idx,
                "station_along_river": float(d),
                "center_xy": (center.x, center.y),
                "xs_line_wkt": xs_line.wkt,
                "station_elevation": station_elev,
            })

    return {
        "cross_sections": sections,
        "n_cross_sections": len(sections),
        "crs": dem_crs,
    }
