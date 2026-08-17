"""
netcdf_utils.py — NetCDF helpers for coordinate discovery, subsetting, and forcing loaders.

Consolidates patterns duplicated across 50+ ki/tools/ scripts.

Works with both **xarray** (``xr.Dataset``) and **netCDF4** (``netCDF4.Dataset``)
objects where feasible. Functions that require dimension-aware operations are
xarray-primary with netCDF4 fall-backs noted in docstrings.

Examples::

    >>> import xarray as xr
    >>> from ki_tools_common.netcdf_utils import find_coords, bbox_subset
    >>> ds = xr.open_dataset("forcing.nc")
    >>> coords = find_coords(ds)
    >>> sub = bbox_subset(ds, 30.0, 35.0, 115.0, 120.0)
"""

from __future__ import annotations

import os
import glob
import warnings
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

# Optional heavy imports — fail gracefully if not installed.
try:
    import xarray as xr

    _HAS_XARRAY = True
except ImportError:
    _HAS_XARRAY = False

try:
    import netCDF4

    _HAS_NETCDF4 = True
except ImportError:
    _HAS_NETCDF4 = False

try:
    import geopandas as gpd
    from shapely.geometry import Point

    _HAS_GEO = True
except ImportError:
    _HAS_GEO = False


# Common aliases that appear across the 97 models
_LAT_NAMES = {"lat", "latitude", "Latitude", "LAT", "XLAT", "nav_lat", "y"}
_LON_NAMES = {"lon", "longitude", "Longitude", "LON", "XLONG", "nav_lon", "x"}
_TIME_NAMES = {"time", "Time", "TIME", "t", "date", "datetime"}


def find_coords(dataset: Any) -> Dict[str, Optional[str]]:
    """Detect coordinate variable names for latitude, longitude, and time.

    Inspects dimension / coordinate names against common aliases observed in
    CMFD, MSWX, ERA5, and model-output files.

    Args:
        dataset: An ``xr.Dataset``, ``xr.DataArray``, or ``netCDF4.Dataset``.

    Returns:
        Dict with keys ``'lat'``, ``'lon'``, ``'time'``, each mapping to the
        detected name (str) or ``None`` if not found.

    Example::

        >>> find_coords(xr.open_dataset("cmfd.nc"))
        {'lat': 'lat', 'lon': 'lon', 'time': 'time'}
    """
    if _HAS_XARRAY and isinstance(dataset, (xr.Dataset, xr.DataArray)):
        names = set(dataset.dims) | set(dataset.coords)
    elif _HAS_NETCDF4 and isinstance(dataset, netCDF4.Dataset):
        names = set(dataset.dimensions.keys()) | set(dataset.variables.keys())
    else:
        names = set(getattr(dataset, "dims", [])) | set(
            getattr(dataset, "variables", {}).keys()
        )

    def _match(candidates: set) -> Optional[str]:
        for c in candidates:
            if c in names:
                return c
        return None

    return {
        "lat": _match(_LAT_NAMES),
        "lon": _match(_LON_NAMES),
        "time": _match(_TIME_NAMES),
    }


def read_variable_with_units(
    dataset: Any,
    var_name: str,
) -> Tuple[np.ndarray, Optional[str]]:
    """Read a variable's data and its ``units`` attribute.

    Args:
        dataset: An ``xr.Dataset`` or ``netCDF4.Dataset``.
        var_name: Name of the variable to read.

    Returns:
        Tuple of (data as numpy array, units string or None).

    Example::

        >>> data, units = read_variable_with_units(ds, 'prec')
    """
    if _HAS_XARRAY and isinstance(dataset, xr.Dataset):
        da = dataset[var_name]
        units = da.attrs.get("units", da.attrs.get("unit", None))
        return da.values, units
    elif _HAS_NETCDF4 and isinstance(dataset, netCDF4.Dataset):
        var = dataset.variables[var_name]
        units = getattr(var, "units", None)
        return var[:], units
    else:
        raise TypeError(
            f"Unsupported dataset type: {type(dataset)}. "
            "Expected xr.Dataset or netCDF4.Dataset."
        )


def bbox_subset(
    dataset: Any,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
) -> Any:
    """Subset an xarray Dataset/DataArray to a bounding box.

    Args:
        dataset: An ``xr.Dataset`` or ``xr.DataArray``.
        lat_min: Southern boundary in degrees.
        lat_max: Northern boundary in degrees.
        lon_min: Western boundary in degrees.
        lon_max: Eastern boundary in degrees.

    Returns:
        Subsetted dataset of the same type.

    Raises:
        RuntimeError: If xarray is not available.

    Example::

        >>> sub = bbox_subset(ds, 30.0, 35.0, 115.0, 120.0)
    """
    if not _HAS_XARRAY:
        raise RuntimeError("xarray is required for bbox_subset.")

    coords = find_coords(dataset)
    lat_name = coords["lat"]
    lon_name = coords["lon"]

    if lat_name is None or lon_name is None:
        raise ValueError(
            f"Could not detect lat/lon coordinate names in dataset. "
            f"Detected: {coords}"
        )

    lat_vals = dataset[lat_name].values
    lon_vals = dataset[lon_name].values

    # Handle decreasing-latitude grids
    if lat_vals[0] > lat_vals[-1]:
        lat_slice = slice(lat_max, lat_min)
    else:
        lat_slice = slice(lat_min, lat_max)

    lon_slice = slice(lon_min, lon_max)

    return dataset.sel({lat_name: lat_slice, lon_name: lon_slice})


def basin_mask_from_shapefile(
    dataset: Any,
    shapefile_path: str,
) -> np.ndarray:
    """Create a boolean mask for grid cells inside a basin polygon.

    Args:
        dataset: An ``xr.Dataset`` with lat/lon coordinates.
        shapefile_path: Path to a shapefile (.shp) defining the basin boundary.

    Returns:
        2-D boolean numpy array (lat x lon) where True indicates the cell
        centre falls inside the basin polygon.

    Raises:
        RuntimeError: If geopandas or shapely are not available.
        FileNotFoundError: If *shapefile_path* does not exist.

    Example::

        >>> mask = basin_mask_from_shapefile(ds, "huaihe_basin.shp")
        >>> masked_precip = ds['prec'].values[:, mask]
    """
    if not _HAS_GEO:
        raise RuntimeError(
            "geopandas and shapely are required for basin_mask_from_shapefile."
        )
    if not _HAS_XARRAY:
        raise RuntimeError("xarray is required for basin_mask_from_shapefile.")

    if not os.path.exists(shapefile_path):
        raise FileNotFoundError(f"Shapefile not found: {shapefile_path}")

    gdf = gpd.read_file(shapefile_path)
    basin_geom = gdf.geometry.unary_union

    coords = find_coords(dataset)
    lat_vals = dataset[coords["lat"]].values
    lon_vals = dataset[coords["lon"]].values

    lon2d, lat2d = np.meshgrid(lon_vals, lat_vals)
    mask = np.zeros(lon2d.shape, dtype=bool)

    for i in range(lat2d.shape[0]):
        for j in range(lat2d.shape[1]):
            pt = Point(lon2d[i, j], lat2d[i, j])
            mask[i, j] = basin_geom.contains(pt)

    return mask


def load_cmfd_forcing(
    forcing_dir: str,
    variable: str,
    years: List[int],
    shapefile: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Load CMFD forcing data as basin-averaged daily time series.

    Handles the CMFD file naming convention and applies unit conversions:
      - prec: kg/m2/s -> mm/day
      - temp: K -> degC
      - All others returned as-is with a warning.

    Args:
        forcing_dir: Root directory containing CMFD NetCDF files.
        variable: CMFD variable name (e.g. ``'prec'``, ``'temp'``, ``'shum'``).
        years: List of years to load.
        shapefile: Optional path to basin shapefile for spatial masking.

    Returns:
        Tuple of (dates as numpy datetime64 array, values as 1-D float array).

    Raises:
        RuntimeError: If xarray is not available.
        FileNotFoundError: If no matching files are found.

    Example::

        >>> dates, precip = load_cmfd_forcing(
        ...     "/data/cmfd", "prec", [2000, 2001], "basin.shp")
    """
    if not _HAS_XARRAY:
        raise RuntimeError("xarray is required for load_cmfd_forcing.")

    from ki_tools_common.units import kgm2s_to_mmday, kelvin_to_celsius

    all_dates: list = []
    all_values: list = []
    mask = None

    for year in sorted(years):
        pattern = os.path.join(forcing_dir, f"*{variable}*{year}*.nc")
        files = sorted(glob.glob(pattern))
        if not files:
            warnings.warn(f"No CMFD files found for {variable}/{year}: {pattern}")
            continue

        for fpath in files:
            ds = xr.open_dataset(fpath)
            coords = find_coords(ds)

            if mask is None and shapefile is not None:
                mask = basin_mask_from_shapefile(ds, shapefile)

            var_name = variable
            if variable not in ds.data_vars:
                # Try to find the variable by partial match
                candidates = [v for v in ds.data_vars if variable.lower() in v.lower()]
                if candidates:
                    var_name = candidates[0]
                else:
                    ds.close()
                    continue

            data = ds[var_name].values  # (time, lat, lon) typically
            time_vals = ds[coords["time"]].values if coords["time"] else None

            if mask is not None and data.ndim == 3:
                # Basin average: mean over masked spatial cells
                spatial = data[:, mask]
                daily_vals = np.nanmean(spatial, axis=1)
            elif data.ndim == 3:
                daily_vals = np.nanmean(data, axis=(1, 2))
            else:
                daily_vals = data.flatten()

            # Unit conversion
            if variable in ("prec", "pre", "precipitation"):
                daily_vals = kgm2s_to_mmday(daily_vals)
            elif variable in ("temp", "tmp", "temperature", "tair"):
                daily_vals = kelvin_to_celsius(daily_vals)

            if time_vals is not None:
                all_dates.extend(time_vals)
            all_values.extend(daily_vals)
            ds.close()

    if not all_values:
        raise FileNotFoundError(
            f"No data found for variable '{variable}' in {forcing_dir} "
            f"for years {years}."
        )

    return np.array(all_dates), np.array(all_values, dtype=float)


def load_mswx_forcing(
    mswx_dir: str,
    variable: str,
    years: List[int],
    shapefile: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Load MSWX forcing data as basin-averaged daily time series.

    Same interface as :func:`load_cmfd_forcing` but adapted for the MSWX
    file naming convention and variable units (e.g., Tair in K, P in mm/3hr).

    Args:
        mswx_dir: Root directory containing MSWX NetCDF files.
        variable: MSWX variable name (e.g. ``'P'``, ``'Tair'``, ``'Wind'``).
        years: List of years to load.
        shapefile: Optional path to basin shapefile for spatial masking.

    Returns:
        Tuple of (dates as numpy datetime64 array, values as 1-D float array).

    Raises:
        RuntimeError: If xarray is not available.
        FileNotFoundError: If no matching files are found.

    Example::

        >>> dates, precip = load_mswx_forcing(
        ...     "/data/mswx", "P", [2000, 2001], "basin.shp")
    """
    if not _HAS_XARRAY:
        raise RuntimeError("xarray is required for load_mswx_forcing.")

    from ki_tools_common.units import kelvin_to_celsius

    all_dates: list = []
    all_values: list = []
    mask = None

    for year in sorted(years):
        pattern = os.path.join(mswx_dir, f"*{variable}*{year}*.nc")
        files = sorted(glob.glob(pattern))
        if not files:
            warnings.warn(f"No MSWX files found for {variable}/{year}: {pattern}")
            continue

        for fpath in files:
            ds = xr.open_dataset(fpath)
            coords = find_coords(ds)

            if mask is None and shapefile is not None:
                mask = basin_mask_from_shapefile(ds, shapefile)

            var_name = variable
            if variable not in ds.data_vars:
                candidates = [v for v in ds.data_vars if variable.lower() in v.lower()]
                if candidates:
                    var_name = candidates[0]
                else:
                    ds.close()
                    continue

            data = ds[var_name].values
            time_vals = ds[coords["time"]].values if coords["time"] else None

            if mask is not None and data.ndim == 3:
                spatial = data[:, mask]
                daily_vals = np.nanmean(spatial, axis=1)
            elif data.ndim == 3:
                daily_vals = np.nanmean(data, axis=(1, 2))
            else:
                daily_vals = data.flatten()

            # MSWX-specific: precipitation P is in mm/3hr, need to aggregate
            # sub-daily to daily externally if needed; Tair is in K
            if variable in ("Tair", "tair"):
                daily_vals = kelvin_to_celsius(daily_vals)

            if time_vals is not None:
                all_dates.extend(time_vals)
            all_values.extend(daily_vals)
            ds.close()

    if not all_values:
        raise FileNotFoundError(
            f"No data found for variable '{variable}' in {mswx_dir} "
            f"for years {years}."
        )

    return np.array(all_dates), np.array(all_values, dtype=float)
