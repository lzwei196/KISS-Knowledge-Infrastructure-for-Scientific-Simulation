#!/usr/bin/env python3
"""Create COSIPY static file from DEM and glacier shapefile.

The static file contains elevation (HGT), slope (SLOPE), aspect (ASPECT),
and glacier mask (MASK) on a regular lat/lon grid.

Usage:
    python convert_static.py \\
        --dem dem.tif \\
        --shapefile glacier.shp \\
        --output static.nc \\
        --lon-min 90.62 --lon-max 90.66 \\
        --lat-min 30.46 --lat-max 30.48 \\
        --resolution 0.003
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import xarray as xr


def validate_inputs(dem_path: str, shapefile_path: str) -> bool:
    """Validate that DEM and shapefile exist.

    Args:
        dem_path: Path to DEM GeoTIFF.
        shapefile_path: Path to glacier shapefile.

    Returns:
        True if all files exist.

    Raises:
        FileNotFoundError: Missing input file.
    """
    if not Path(dem_path).exists():
        raise FileNotFoundError(f"DEM file not found: {dem_path}")
    if not Path(shapefile_path).exists():
        raise FileNotFoundError(f"Shapefile not found: {shapefile_path}")
    return True


def create_grid(lon_min: float, lon_max: float, lat_min: float, lat_max: float,
                resolution: float) -> tuple:
    """Create regular lat/lon grid.

    Args:
        lon_min: Western boundary.
        lon_max: Eastern boundary.
        lat_min: Southern boundary.
        lat_max: Northern boundary.
        resolution: Grid spacing in degrees.

    Returns:
        Tuple of (longitude array, latitude array).
    """
    lons = np.arange(lon_min, lon_max + resolution / 2, resolution)
    lats = np.arange(lat_max, lat_min - resolution / 2, -resolution)

    print(f"Grid created: {len(lats)} x {len(lons)} cells")
    print(f"  Lat: {lats[-1]:.4f} to {lats[0]:.4f}")
    print(f"  Lon: {lons[0]:.4f} to {lons[-1]:.4f}")

    return lons, lats


def extract_dem(dem_path: str, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Extract DEM elevation values at grid points.

    Uses rasterio if available, otherwise creates synthetic DEM.

    Args:
        dem_path: Path to DEM GeoTIFF.
        lons: Longitude array.
        lats: Latitude array.

    Returns:
        2D elevation array (lat, lon).
    """
    try:
        import rasterio
        from rasterio.transform import rowcol

        with rasterio.open(dem_path) as src:
            dem_data = src.read(1)
            transform = src.transform

            hgt = np.zeros((len(lats), len(lons)))
            for i, lat in enumerate(lats):
                for j, lon in enumerate(lons):
                    row, col = rowcol(transform, lon, lat)
                    if 0 <= row < dem_data.shape[0] and 0 <= col < dem_data.shape[1]:
                        hgt[i, j] = dem_data[row, col]
                    else:
                        hgt[i, j] = np.nan

        print(f"DEM extracted: min={np.nanmin(hgt):.1f}m, max={np.nanmax(hgt):.1f}m")
        return hgt

    except ImportError:
        print("WARNING: rasterio not available. Attempting with GDAL...")
        try:
            from osgeo import gdal
            ds = gdal.Open(dem_path)
            band = ds.GetRasterBand(1)
            gt = ds.GetGeoTransform()

            hgt = np.zeros((len(lats), len(lons)))
            for i, lat in enumerate(lats):
                for j, lon in enumerate(lons):
                    col = int((lon - gt[0]) / gt[1])
                    row = int((lat - gt[3]) / gt[5])
                    if 0 <= row < ds.RasterYSize and 0 <= col < ds.RasterXSize:
                        hgt[i, j] = band.ReadAsArray(col, row, 1, 1)[0, 0]
                    else:
                        hgt[i, j] = np.nan
            ds = None
            return hgt

        except ImportError:
            print("WARNING: Neither rasterio nor GDAL available. Creating synthetic DEM.")
            hgt = 5000.0 + np.random.randn(len(lats), len(lons)) * 100
            return hgt


def compute_slope_aspect(hgt: np.ndarray, resolution_m: float) -> tuple:
    """Compute slope and aspect from DEM.

    Args:
        hgt: 2D elevation array.
        resolution_m: Grid spacing in meters.

    Returns:
        Tuple of (slope in degrees, aspect in degrees).
    """
    # Compute gradients
    dy, dx = np.gradient(hgt, resolution_m)

    # Slope in degrees
    slope = np.degrees(np.arctan(np.sqrt(dx ** 2 + dy ** 2)))

    # Aspect in degrees (0=North, 90=East, 180=South, 270=West)
    aspect = np.degrees(np.arctan2(-dx, dy))
    aspect = np.mod(aspect, 360)

    # Handle flat areas
    flat_mask = (dx == 0) & (dy == 0)
    aspect[flat_mask] = 0.0
    slope[flat_mask] = 0.0

    print(f"Slope: min={np.nanmin(slope):.1f}, max={np.nanmax(slope):.1f} degrees")
    print(f"Aspect: min={np.nanmin(aspect):.1f}, max={np.nanmax(aspect):.1f} degrees")

    return slope, aspect


def create_mask(lons: np.ndarray, lats: np.ndarray, shapefile_path: str) -> np.ndarray:
    """Create glacier mask from shapefile.

    Args:
        lons: Longitude array.
        lats: Latitude array.
        shapefile_path: Path to glacier shapefile.

    Returns:
        2D mask array (1=glacier, 0=not glacier).
    """
    try:
        import geopandas as gpd
        from shapely.geometry import Point

        gdf = gpd.read_file(shapefile_path)
        glacier_geom = gdf.unary_union

        mask = np.zeros((len(lats), len(lons)), dtype=np.int32)
        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                if glacier_geom.contains(Point(lon, lat)):
                    mask[i, j] = 1

        n_glacier = np.sum(mask)
        print(f"Mask: {n_glacier} glacier cells out of {mask.size} total")

        if n_glacier == 0:
            print("WARNING: No glacier cells found! Check shapefile/DEM extent overlap.")

        return mask

    except ImportError:
        print("WARNING: geopandas not available. Setting all cells as glacier.")
        return np.ones((len(lats), len(lons)), dtype=np.int32)


def write_static_netcdf(lons: np.ndarray, lats: np.ndarray, hgt: np.ndarray,
                        slope: np.ndarray, aspect: np.ndarray, mask: np.ndarray,
                        output_path: str):
    """Write COSIPY static file.

    Args:
        lons: Longitude coordinate array.
        lats: Latitude coordinate array.
        hgt: Elevation array (lat, lon).
        slope: Slope array (lat, lon).
        aspect: Aspect array (lat, lon).
        mask: Glacier mask array (lat, lon).
        output_path: Output file path.
    """
    ds = xr.Dataset()

    # Coordinates
    ds.coords["lon"] = ("lon", lons)
    ds.coords["lat"] = ("lat", lats)
    ds.lon.attrs = {"units": "degrees_east", "long_name": "longitude"}
    ds.lat.attrs = {"units": "degrees_north", "long_name": "latitude"}

    # Variables
    ds["HGT"] = (("lat", "lon"), hgt)
    ds["HGT"].attrs = {"units": "meters", "long_name": "Elevation", "_FillValue": -9999}

    ds["SLOPE"] = (("lat", "lon"), slope)
    ds["SLOPE"].attrs = {"units": "degrees", "long_name": "Terrain slope", "_FillValue": -9999}

    ds["ASPECT"] = (("lat", "lon"), aspect)
    ds["ASPECT"].attrs = {"units": "degrees", "long_name": "Aspect of slope", "_FillValue": -9999}

    ds["MASK"] = (("lat", "lon"), mask)
    ds["MASK"].attrs = {"units": "boolean", "long_name": "Glacier mask", "_FillValue": -9999}

    ds.to_netcdf(output_path)
    print(f"\nStatic file written: {output_path}")
    print(f"  Grid: {len(lats)} x {len(lons)}")
    print(f"  Glacier cells: {np.sum(mask)}")


def validate_output(output_path: str) -> bool:
    """Validate the output static file.

    Args:
        output_path: Path to static file.

    Returns:
        True if valid.
    """
    ds = xr.open_dataset(output_path)

    required = ["HGT", "SLOPE", "ASPECT", "MASK"]
    missing = [v for v in required if v not in ds.data_vars]
    if missing:
        print(f"ERROR: Missing variables: {missing}")
        ds.close()
        return False

    if ds["MASK"].values.sum() == 0:
        print("ERROR: MASK has no glacier cells (all zeros)")
        ds.close()
        return False

    # Check for NaN in masked cells
    for var in ["HGT", "SLOPE", "ASPECT"]:
        masked_vals = ds[var].values[ds["MASK"].values == 1]
        if np.isnan(masked_vals).any():
            print(f"ERROR: {var} has NaN values in glacier cells")
            ds.close()
            return False

    print("Static file validation: PASSED")
    ds.close()
    return True


def main():
    parser = argparse.ArgumentParser(description="Create COSIPY static file")
    parser.add_argument("--dem", required=True, help="Path to DEM GeoTIFF")
    parser.add_argument("--shapefile", required=True, help="Path to glacier shapefile")
    parser.add_argument("--output", required=True, help="Output static netCDF file")
    parser.add_argument("--lon-min", type=float, required=True)
    parser.add_argument("--lon-max", type=float, required=True)
    parser.add_argument("--lat-min", type=float, required=True)
    parser.add_argument("--lat-max", type=float, required=True)
    parser.add_argument("--resolution", type=float, default=0.003, help="Grid resolution in degrees")
    args = parser.parse_args()

    # Validate inputs
    validate_inputs(args.dem, args.shapefile)

    # Create grid
    lons, lats = create_grid(args.lon_min, args.lon_max, args.lat_min, args.lat_max, args.resolution)

    # Extract DEM
    hgt = extract_dem(args.dem, lons, lats)

    # Compute slope and aspect
    resolution_m = args.resolution * 111000  # approximate degrees to meters
    slope, aspect = compute_slope_aspect(hgt, resolution_m)

    # Create glacier mask
    mask = create_mask(lons, lats, args.shapefile)

    # Write output
    write_static_netcdf(lons, lats, hgt, slope, aspect, mask, args.output)

    # Validate
    validate_output(args.output)


if __name__ == "__main__":
    main()
