#!/usr/bin/env python3
"""
convert_landscape_to_nc.py — Convert DEM + fuel map to ForeFire landscape NetCDF.

ForeFire expects a NetCDF file (data.nc) containing gridded layers:
  - altitude (t, z, y, x): elevation in meters
  - fuel (t, z, y, x): integer fuel type index (references fuels.csv rows)
  - windU (t, z, y, x): eastward wind component in m/s
  - windV (t, z, y, x): northward wind component in m/s

Coordinate system: UTM meters. The domain SW/NE must match the FireDomain command.

CRITICAL UNIT CONVERSIONS:
  - Elevation: must be in meters (not feet). DEM sources like SRTM are already in meters.
  - Wind: must be in m/s. Convert from km/h (÷3.6), mph (×0.44704), or knots (×0.5144).
  - Fuel index: integer >= 0, matching row indices in fuels.csv.
  - Coordinates: must be in UTM meters, NOT lon/lat degrees.

Usage:
    python convert_landscape_to_nc.py \\
        --dem_tif /path/to/elevation.tif \\
        --fuel_tif /path/to/fuel_index.tif \\
        --wind_u 5.0 --wind_v 0.0 \\
        --timestamp 2025-02-10T17:35:54Z \\
        --output data.nc

    python convert_landscape_to_nc.py \\
        --dem_tif /path/to/elevation.tif \\
        --fuel_tif /path/to/fuel_index.tif \\
        --wind_nc /path/to/era5_wind.nc \\
        --timestamp 2025-02-10T17:35:54Z \\
        --output data.nc
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

try:
    import netCDF4
except ImportError:
    print("ERROR: netCDF4 required. Install with: pip install netCDF4", file=sys.stderr)
    sys.exit(1)


def validate_inputs(args):
    """Validate input arguments before processing."""
    errors = []

    if not os.path.isfile(args.dem_tif):
        errors.append(f"DEM file not found: {args.dem_tif}")

    if not os.path.isfile(args.fuel_tif):
        errors.append(f"Fuel map file not found: {args.fuel_tif}")

    if args.wind_nc and not os.path.isfile(args.wind_nc):
        errors.append(f"Wind NetCDF file not found: {args.wind_nc}")

    if args.wind_u is not None and (args.wind_u < -100 or args.wind_u > 100):
        errors.append(f"Wind U component unrealistic: {args.wind_u} m/s (expect -100 to 100)")

    if args.wind_v is not None and (args.wind_v < -100 or args.wind_v > 100):
        errors.append(f"Wind V component unrealistic: {args.wind_v} m/s (expect -100 to 100)")

    if errors:
        for e in errors:
            print(f"VALIDATION ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print("Input validation passed.")


def load_raster(filepath):
    """Load a GeoTIFF raster using rasterio or GDAL."""
    try:
        import rasterio
        with rasterio.open(filepath) as src:
            data = src.read(1).astype(np.float64)
            transform = src.transform
            crs = src.crs
            bounds = src.bounds
            return {
                "data": data,
                "transform": transform,
                "crs": str(crs),
                "bounds": bounds,
                "shape": data.shape,
            }
    except ImportError:
        try:
            from osgeo import gdal
            ds = gdal.Open(filepath)
            band = ds.GetRasterBand(1)
            data = band.ReadAsArray().astype(np.float64)
            gt = ds.GetGeoTransform()
            ny, nx = data.shape
            bounds_obj = type('Bounds', (), {
                'left': gt[0],
                'bottom': gt[3] + ny * gt[5],
                'right': gt[0] + nx * gt[1],
                'top': gt[3],
            })()
            return {
                "data": data,
                "transform": gt,
                "crs": ds.GetProjection(),
                "bounds": bounds_obj,
                "shape": data.shape,
            }
        except ImportError:
            print("ERROR: rasterio or GDAL required for GeoTIFF reading.", file=sys.stderr)
            sys.exit(1)


def convert_wind_units(speed, direction, source_unit="m/s"):
    """Convert wind speed and direction to U/V components in m/s."""
    conversion = {
        "m/s": 1.0,
        "km/h": 1.0 / 3.6,
        "mph": 0.44704,
        "knots": 0.5144,
        "ft/min": 0.00508,
    }
    if source_unit not in conversion:
        raise ValueError(f"Unknown wind unit: {source_unit}. Supported: {list(conversion.keys())}")

    speed_ms = speed * conversion[source_unit]
    # Meteorological convention: direction is where wind comes FROM
    dir_rad = np.radians(direction)
    u = -speed_ms * np.sin(dir_rad)
    v = -speed_ms * np.cos(dir_rad)
    return u, v


def process(args):
    """Main processing: load inputs and create ForeFire NetCDF."""
    print(f"Loading DEM: {args.dem_tif}")
    dem_info = load_raster(args.dem_tif)
    dem = dem_info["data"]
    ny, nx = dem.shape

    print(f"Loading fuel map: {args.fuel_tif}")
    fuel_info = load_raster(args.fuel_tif)
    fuel = fuel_info["data"].astype(np.int32)

    if fuel.shape != dem.shape:
        print(f"WARNING: Fuel shape {fuel.shape} != DEM shape {dem.shape}. Resampling.", file=sys.stderr)
        from scipy.ndimage import zoom
        zy = dem.shape[0] / fuel.shape[0]
        zx = dem.shape[1] / fuel.shape[1]
        fuel = zoom(fuel, (zy, zx), order=0).astype(np.int32)

    # Create wind arrays
    nt = 2  # Two time steps for interpolation
    nz = 1

    if args.wind_nc:
        print(f"Loading wind from: {args.wind_nc}")
        wds = netCDF4.Dataset(args.wind_nc, 'r')
        # Attempt to read standard ERA5 variable names
        wind_u_data = np.zeros((nt, nz, ny, nx))
        wind_v_data = np.zeros((nt, nz, ny, nx))
        for vname in ['u10', 'U10M', 'windU', 'ugrd']:
            if vname in wds.variables:
                raw = wds[vname][:]
                wind_u_data[0, 0, :, :] = raw[0] if raw.ndim > 2 else raw
                wind_u_data[1, 0, :, :] = raw[-1] if raw.ndim > 2 else raw
                break
        for vname in ['v10', 'V10M', 'windV', 'vgrd']:
            if vname in wds.variables:
                raw = wds[vname][:]
                wind_v_data[0, 0, :, :] = raw[0] if raw.ndim > 2 else raw
                wind_v_data[1, 0, :, :] = raw[-1] if raw.ndim > 2 else raw
                break
        wds.close()
    else:
        u_val = args.wind_u if args.wind_u is not None else 0.0
        v_val = args.wind_v if args.wind_v is not None else 0.0
        wind_u_data = np.full((nt, nz, ny, nx), u_val, dtype=np.float64)
        wind_v_data = np.full((nt, nz, ny, nx), v_val, dtype=np.float64)

    # Create output NetCDF in ForeFire's REQUIRED domain format.
    # The binary's DataBroker::loadFromNCFile has a hard contract that the
    # XHAT/YHAT layout does NOT satisfy ("Domain variable not found"): it needs
    #   - a scalar NC_STRING `domain` variable carrying float32 SWx/SWy/Lx/Ly +
    #     BBoxWSEN (lon/lat) so startFire[lonlat] maps to local meters,
    #   - per-layer `type` attributes ('data'/'fuel'),
    #   - nt=1 (nt=2 with no time coord underflows the time index),
    #   - south-up rows (domain origin = SW corner, y increasing north).
    print(f"Writing: {args.output}")
    bounds = dem_info["bounds"]
    crs = dem_info["crs"]
    Lx = float(bounds.right - bounds.left)
    Ly = float(bounds.top - bounds.bottom)

    # lon/lat bounding box of the (projected) corners for the lonlat->meter map
    try:
        from pyproj import Transformer
        tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        los, las = [], []
        for X in (bounds.left, bounds.right):
            for Y in (bounds.bottom, bounds.top):
                lo, la = tr.transform(X, Y)
                los.append(lo); las.append(la)
        W, E = min(los), max(los); S, N = min(las), max(las)
    except Exception as _e:
        print(f"WARNING: corner reprojection failed ({_e}); using meter bbox", file=sys.stderr)
        W, S, E, N = 0.0, 0.0, Lx, Ly

    # rasterio/GDAL give north-up rows (row 0 = north); flip to south-up.
    alt2 = np.flipud(dem.astype(np.float64))
    fuel2 = np.flipud(fuel.astype(np.int16))
    wu2 = np.flipud(np.asarray(wind_u_data[0, 0], dtype=np.float64))
    wv2 = np.flipud(np.asarray(wind_v_data[0, 0], dtype=np.float64))

    ds = netCDF4.Dataset(args.output, 'w', format='NETCDF4')
    for dname, dsize in [('nt', 1), ('nz', 1), ('ny', ny), ('nx', nx),
                         ('ft', 1), ('fz', 1), ('fy', ny), ('fx', nx)]:
        ds.createDimension(dname, dsize)

    dom = ds.createVariable('domain', str)          # NC_STRING scalar
    dom[...] = ""
    dom.type = "domain"
    dom.SWx = np.float32(0.0); dom.SWy = np.float32(0.0); dom.SWz = np.float32(0.0)
    dom.Lx = np.float32(Lx); dom.Ly = np.float32(Ly); dom.Lz = np.float32(0.0)
    dom.t0 = np.float32(0.0); dom.Lt = np.float32(np.inf)
    dom.BBoxWSEN = f"{W},{S},{E},{N}"
    dom.WSENLBRT = f"{W},{S},{E},{N},0.0,0.0,{Lx},{Ly}"
    # PROVENANCE ONLY -- these are NOT read by the engine. SWx/SWy above MUST stay
    # at 0: the engine maps its LOCAL metric frame (0..Lx, 0..Ly) onto BBoxWSEN,
    # and putting the projected easting/northing in SWx/SWy corrupts that mapping
    # (perimeters then dump at nonsense lon/lat). The consequence for callers is
    # the trap in triplet dt_022: `startFire[loc=(x,y,0)]` expects LOCAL metres,
    # so passing absolute UTM puts the ignition outside the domain and ForeFire
    # silently creates NO fire -- every isochrone is an empty FeatureCollection
    # and the exit code is 0. Subtract these origins, or use startFire[lonlat=].
    dom.originX = float(bounds.left)
    dom.originY = float(bounds.bottom)
    dom.projCRS = str(crs)
    print(f"  Domain frame: LOCAL metres 0..{Lx:.0f} x 0..{Ly:.0f}; "
          f"projected origin (SW) = ({bounds.left}, {bounds.bottom}) in {crs}.")
    print( "  -> startFire[loc=] takes LOCAL metres (subtract the origin); "
           "startFire[lonlat=] takes degrees. Absolute CRS coords ignite nothing "
           "and raise no error (triplet dt_022).")

    alt_var = ds.createVariable('altitude', 'f8', ('nt', 'nz', 'ny', 'nx'))
    alt_var.type = "data"; alt_var.units = "m"
    alt_var[0, 0, :, :] = alt2

    fuel_var = ds.createVariable('fuel', 'i2', ('ft', 'fz', 'fy', 'fx'))
    fuel_var.type = "fuel"
    fuel_var[0, 0, :, :] = fuel2

    wu_var = ds.createVariable('windU', 'f8', ('nt', 'nz', 'ny', 'nx'))
    wu_var.type = "data"; wu_var.units = "m/s"
    wu_var[0, 0, :, :] = wu2

    wv_var = ds.createVariable('windV', 'f8', ('nt', 'nz', 'ny', 'nx'))
    wv_var.type = "data"; wv_var.units = "m/s"
    wv_var[0, 0, :, :] = wv2

    ds.description = "ForeFire landscape data"
    ds.timestamp = args.timestamp
    ds.close()

    print(f"Output written: {args.output}")
    print(f"  Grid: {nx} x {ny}")
    print(f"  Bounds: ({bounds.left}, {bounds.bottom}) to ({bounds.right}, {bounds.top})")
    print(f"  Fuel range: {fuel.min()} to {fuel.max()}")
    print(f"  Elevation range: {dem.min():.1f} to {dem.max():.1f} m")


def validate_outputs(output_path):
    """Post-processing validation of the created NetCDF."""
    errors = []
    ds = netCDF4.Dataset(output_path, 'r')

    # Check required variables
    required = ['altitude', 'fuel', 'windU', 'windV']
    for var in required:
        if var not in ds.variables:
            errors.append(f"Missing required variable: {var}")

    if 'altitude' in ds.variables:
        alt = ds['altitude'][:]
        if np.any(np.isnan(alt)):
            errors.append("Altitude contains NaN values")
        if alt.max() > 9000:
            errors.append(f"Altitude max={alt.max():.0f}m — exceeds Everest, likely wrong units")
        if alt.min() < -500:
            errors.append(f"Altitude min={alt.min():.0f}m — below Dead Sea, check data")

    if 'fuel' in ds.variables:
        fuel = ds['fuel'][:]
        if np.any(fuel < 0):
            errors.append("Fuel index contains negative values")
        if fuel.max() > 300:
            errors.append(f"Fuel index max={fuel.max()} — unusually high, check fuel table")

    if 'windU' in ds.variables:
        wu = ds['windU'][:]
        if np.any(np.abs(wu) > 80):
            errors.append(f"Wind U max={np.abs(wu).max():.1f} m/s — exceeds hurricane force")

    ds.close()

    if errors:
        for e in errors:
            print(f"OUTPUT VALIDATION WARNING: {e}", file=sys.stderr)
        return False

    print("Output validation passed.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Convert landscape data to ForeFire NetCDF")
    parser.add_argument("--dem_tif", required=True, help="Path to elevation GeoTIFF (meters)")
    parser.add_argument("--fuel_tif", required=True, help="Path to fuel index GeoTIFF")
    parser.add_argument("--wind_nc", default=None, help="Path to wind NetCDF (ERA5 or similar)")
    parser.add_argument("--wind_u", type=float, default=None, help="Constant U wind (m/s)")
    parser.add_argument("--wind_v", type=float, default=None, help="Constant V wind (m/s)")
    parser.add_argument("--timestamp", default="2025-01-01T00:00:00Z", help="ISO 8601 timestamp")
    parser.add_argument("--output", default="data.nc", help="Output NetCDF path")
    args = parser.parse_args()

    validate_inputs(args)
    process(args)
    validate_outputs(args.output)


if __name__ == "__main__":
    main()
