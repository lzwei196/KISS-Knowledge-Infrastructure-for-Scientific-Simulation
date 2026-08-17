"""
terrain_ops — Shared GIS / terrain operations for HydroCraft model KIs.

Used by HEC-RAS, ANUGA, CRHM, CREST, VIC, and any model needing basin
delineation, river centerline extraction, cross-section cutting, or
DEM profile sampling.

Substrate:
  - whitebox-tools (hydrologic ops: fill, flow, watershed, streams)
  - rasterio       (raster I/O + point/window sampling)
  - geopandas      (vector I/O + reprojection)
  - shapely        (geometry primitives: LineString, Point, perpendicular)
  - pyproj         (CRS transforms)

Discovery: every public function is decorated with @geo_tool — call
``list_tools()`` to enumerate, or import the function directly.
"""

__version__ = "0.1.0"

from .registry import geo_tool, list_tools, get_tool

# Submodule imports register their functions with the global @geo_tool
# registry as a side effect. Import them here so a single
# ``import ki_tools_common.terrain_ops`` populates the registry.
from .delineate import delineate_basin
from .centerline import (
    extract_river_centerline_from_dem,
    extract_river_centerline_from_streams,
)
from .cross_sections import cut_cross_sections
from .profile import sample_dem_profile

__all__ = [
    "geo_tool",
    "list_tools",
    "get_tool",
    "delineate_basin",
    "extract_river_centerline_from_dem",
    "extract_river_centerline_from_streams",
    "cut_cross_sections",
    "sample_dem_profile",
]
