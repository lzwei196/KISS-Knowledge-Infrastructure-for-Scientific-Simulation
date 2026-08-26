"""
terrain.py — Point elevation and slope lookup from DEM.

Provides data-driven terrain properties at any location, replacing
hardcoded defaults. Used by EPIC, DSSAT, AquaCrop, SWAT+, and any
model needing elevation or slope at a point.

Data sources:
  - China DEM 90m GeoTIFF (primary, 90m resolution)
  - CMFD elevation grid (fallback, 0.1° resolution, China only)

Usage::

    from ki_tools_common.terrain import get_terrain

    t = get_terrain(32.9, 117.4)
    # Returns: {'elevation': 16.0, 'slope': 0.001, 'slope_degrees': 0.06,
    #           'source': 'china_dem_90m'}
"""

import os
from typing import Dict

import numpy as np

CHINA_DEM_PATH = "KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif"
CMFD_ELEV_PATH = "KISSPATH_DATA/elev/elev_CMFD_V0200_B-00_fx_010deg.nc"

# Minimum slope for models that need nonzero (e.g., EPIC erosion)
MIN_SLOPE = 0.001


def _from_china_dem(lat, lon):
    """Extract elevation and slope from China DEM 90m GeoTIFF."""
    try:
        import rasterio
    except ImportError:
        return None

    if not os.path.isfile(CHINA_DEM_PATH):
        return None

    try:
        with rasterio.open(CHINA_DEM_PATH) as src:
            row, col = src.index(lon, lat)
            if not (2 <= row < src.height - 2 and 2 <= col < src.width - 2):
                return None

            win = rasterio.windows.Window(col - 2, row - 2, 5, 5)
            data = src.read(1, window=win).astype(float)
            if src.nodata is not None:
                data[data == src.nodata] = np.nan

            center = float(data[2, 2])
            if np.isnan(center) or center < -500 or center > 9000:
                return None

            # Central difference slope (m/m)
            cellx = abs(src.res[0]) * 111320 * np.cos(np.radians(lat))
            celly = abs(src.res[1]) * 111320
            dzdx = (data[2, 3] - data[2, 1]) / (2 * cellx)
            dzdy = (data[1, 2] - data[3, 2]) / (2 * celly)
            slope = float(np.sqrt(dzdx**2 + dzdy**2))

            return {
                'elevation': round(center, 1),
                'slope': max(MIN_SLOPE, round(slope, 6)),
                'slope_degrees': round(float(np.degrees(np.arctan(slope))), 3),
                'source': 'china_dem_90m',
            }
    except Exception:
        return None


def _from_cmfd_elev(lat, lon):
    """Extract elevation from CMFD grid (0.1° resolution, China only)."""
    if not (15 < lat < 55 and 70 < lon < 140):
        return None
    if not os.path.isfile(CMFD_ELEV_PATH):
        return None

    try:
        import xarray as xr
        ds = xr.open_dataset(CMFD_ELEV_PATH)
        data = ds['elev'].sel(lat=lat, lon=lon, method='nearest')
        if 'time' in data.dims:
            data = data.isel(time=0)
        val = float(data.values)
        ds.close()
        if 0 < val < 9000:
            return {
                'elevation': round(val, 1),
                'slope': MIN_SLOPE,  # no slope info at 0.1° resolution
                'slope_degrees': round(float(np.degrees(np.arctan(MIN_SLOPE))), 3),
                'source': 'cmfd_elev',
            }
    except Exception:
        pass
    return None


def get_terrain(lat: float, lon: float) -> Dict:
    """Look up elevation and slope at a point.

    Tries China DEM 90m first (provides both elevation and slope),
    then CMFD elevation grid (elevation only), then defaults.

    Args:
        lat: Latitude (degrees, positive N)
        lon: Longitude (degrees, positive E)

    Returns:
        dict with: elevation (m), slope (m/m), slope_degrees, source
    """
    # Try high-res DEM first
    result = _from_china_dem(lat, lon)
    if result:
        return result

    # Try CMFD elevation
    result = _from_cmfd_elev(lat, lon)
    if result:
        return result

    # Default
    return {
        'elevation': 100.0,
        'slope': MIN_SLOPE,
        'slope_degrees': round(float(np.degrees(np.arctan(MIN_SLOPE))), 3),
        'source': 'default',
    }
