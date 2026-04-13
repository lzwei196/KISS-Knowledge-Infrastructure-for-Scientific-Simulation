#!/usr/bin/env python3
"""
convert_forcing_to_ef5.py — Convert global forcing datasets to EF5 grid format.

Converts CMFD, MSWX, or generic NetCDF precipitation and PET data into
EF5-compatible grid files (ESRI ASCII .asc or GeoTIFF .tif).

Pipeline stage: s2 (Forcing Conversion)
Pattern: validate → process → validate

Input:
  - NetCDF forcing file(s) with precipitation and/or PET
  - Basin bounding box or clip mask
  - Source metadata (units, variable names, temporal resolution)

Output:
  - Directory of timestamped grid files matching EF5 naming convention
  - Summary log with conversion statistics

Unit conversions handled:
  - CMFD precipitation: mm/hr → mm/hr (no change, but validates)
  - CMFD 3-hourly: mm/3hr → mm/hr (divide by 3)
  - Daily precipitation: mm/day → mm/hr (divide by 24)
  - Monthly PET: mm/month → mm/hr (divide by hours in month)
  - Temperature PET: °C or K → °C (subtract 273.15 if Kelvin)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

try:
    from osgeo import gdal, osr
    HAS_GDAL = True
except ImportError:
    HAS_GDAL = False


# ── Constants ──────────────────────────────────────────────────────────────

UNIT_CONVERSIONS = {
    # (source_unit, target_unit): multiplier
    ("mm/3h", "mm/h"): 1.0 / 3.0,
    ("mm/day", "mm/h"): 1.0 / 24.0,
    ("mm/d", "mm/h"): 1.0 / 24.0,
    ("mm/hr", "mm/h"): 1.0,
    ("mm/h", "mm/h"): 1.0,
    ("mm/month", "mm/h"): 1.0 / 720.0,  # approximate
    ("mm/mon", "mm/h"): 1.0 / 720.0,
    ("K", "C"): -273.15,  # additive, not multiplicative
    ("degC", "C"): 0.0,   # additive, no change
    ("C", "C"): 0.0,
}

EF5_NODATA = -9999.0


# ── Validation ─────────────────────────────────────────────────────────────

def validate_inputs(nc_path, var_name, source_unit, bbox):
    """Validate input NetCDF file and parameters."""
    errors = []

    if not os.path.isfile(nc_path):
        errors.append(f"NetCDF file not found: {nc_path}")
        return errors

    if nc is None:
        errors.append("netCDF4 package not installed. Install with: pip install netCDF4")
        return errors

    ds = nc.Dataset(nc_path, "r")
    if var_name not in ds.variables:
        available = list(ds.variables.keys())
        errors.append(
            f"Variable '{var_name}' not found in {nc_path}. "
            f"Available: {available}"
        )

    # Check for lat/lon dimensions
    has_lat = any(v in ds.variables for v in ["lat", "latitude", "LAT", "y"])
    has_lon = any(v in ds.variables for v in ["lon", "longitude", "LON", "x"])
    if not has_lat or not has_lon:
        errors.append("Cannot find latitude/longitude variables in NetCDF")

    # Check bbox
    if bbox is not None:
        if len(bbox) != 4:
            errors.append(f"Bounding box must have 4 values (lon_min, lat_min, lon_max, lat_max), got {len(bbox)}")
        elif bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            errors.append(f"Invalid bbox: min must be < max. Got {bbox}")

    ds.close()
    return errors


def validate_outputs(output_dir, expected_count):
    """Validate output grid files were created."""
    errors = []
    output_path = Path(output_dir)

    if not output_path.exists():
        errors.append(f"Output directory not found: {output_dir}")
        return errors

    asc_files = list(output_path.glob("*.asc"))
    tif_files = list(output_path.glob("*.tif"))
    total = len(asc_files) + len(tif_files)

    if total == 0:
        errors.append(f"No output files created in {output_dir}")
    elif total < expected_count:
        errors.append(
            f"Expected {expected_count} output files, found {total}. "
            f"Some timesteps may have been skipped."
        )

    return errors


# ── Processing ─────────────────────────────────────────────────────────────

def get_nc_coords(ds):
    """Extract lat/lon arrays from NetCDF dataset."""
    lat_names = ["lat", "latitude", "LAT", "y"]
    lon_names = ["lon", "longitude", "LON", "x"]

    lat = lon = None
    for name in lat_names:
        if name in ds.variables:
            lat = ds.variables[name][:]
            break
    for name in lon_names:
        if name in ds.variables:
            lon = ds.variables[name][:]
            break

    return lat, lon


def get_time_array(ds):
    """Extract time array as datetime objects."""
    time_names = ["time", "Time", "TIME", "t"]
    for name in time_names:
        if name in ds.variables:
            time_var = ds.variables[name]
            times = nc.num2date(time_var[:], units=time_var.units,
                                calendar=getattr(time_var, "calendar", "standard"))
            return times
    return None


def clip_to_bbox(data, lat, lon, bbox):
    """Clip 2D data array to bounding box."""
    lon_min, lat_min, lon_max, lat_max = bbox

    lat_idx = np.where((lat >= lat_min) & (lat <= lat_max))[0]
    lon_idx = np.where((lon >= lon_min) & (lon <= lon_max))[0]

    if len(lat_idx) == 0 or len(lon_idx) == 0:
        return None, None, None

    clipped = data[lat_idx[0]:lat_idx[-1]+1, lon_idx[0]:lon_idx[-1]+1]
    clipped_lat = lat[lat_idx[0]:lat_idx[-1]+1]
    clipped_lon = lon[lon_idx[0]:lon_idx[-1]+1]

    return clipped, clipped_lat, clipped_lon


def apply_unit_conversion(data, source_unit, target_unit):
    """Apply unit conversion to data array."""
    key = (source_unit, target_unit)
    if key in UNIT_CONVERSIONS:
        factor = UNIT_CONVERSIONS[key]
        if source_unit in ("K",):  # Additive conversion
            return data + factor
        elif source_unit in ("degC", "C"):
            return data + factor
        else:  # Multiplicative conversion
            return data * factor
    else:
        print(f"WARNING: No conversion defined for {source_unit} → {target_unit}. Using raw values.")
        return data


def write_esri_ascii(filepath, data, lon, lat, nodata=EF5_NODATA):
    """Write 2D array as ESRI ASCII grid."""
    nrows, ncols = data.shape
    cellsize = abs(lon[1] - lon[0]) if len(lon) > 1 else 0.1
    xllcorner = float(lon[0]) - cellsize / 2.0
    yllcorner = float(lat[-1]) - cellsize / 2.0 if lat[0] > lat[-1] else float(lat[0]) - cellsize / 2.0

    # Ensure data goes from north to south
    if lat[0] < lat[-1]:
        data = np.flipud(data)

    with open(filepath, "w") as f:
        f.write(f"ncols         {ncols}\n")
        f.write(f"nrows         {nrows}\n")
        f.write(f"xllcorner     {xllcorner:.6f}\n")
        f.write(f"yllcorner     {yllcorner:.6f}\n")
        f.write(f"cellsize      {cellsize:.6f}\n")
        f.write(f"NODATA_value  {nodata}\n")
        for row in range(nrows):
            vals = " ".join(f"{v:.6f}" if v != nodata else str(int(nodata))
                           for v in data[row])
            f.write(vals + "\n")


def write_geotiff(filepath, data, lon, lat, nodata=EF5_NODATA):
    """Write 2D array as Float32 GeoTIFF."""
    if not HAS_GDAL:
        # Fallback to ASCII
        write_esri_ascii(filepath.replace(".tif", ".asc"), data, lon, lat, nodata)
        return

    nrows, ncols = data.shape
    cellsize = abs(lon[1] - lon[0]) if len(lon) > 1 else 0.1
    xmin = float(lon[0]) - cellsize / 2.0
    ymax = float(lat[0]) + cellsize / 2.0 if lat[0] > lat[-1] else float(lat[-1]) + cellsize / 2.0

    if lat[0] < lat[-1]:
        data = np.flipud(data)

    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(filepath, ncols, nrows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform([xmin, cellsize, 0, ymax, 0, -cellsize])

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())

    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(data.astype(np.float32))
    ds.FlushCache()
    ds = None


def format_ef5_filename(template, dt):
    """Format EF5 filename template with datetime."""
    result = template
    result = result.replace("YYYY", f"{dt.year:04d}")
    result = result.replace("MM", f"{dt.month:02d}")
    result = result.replace("DD", f"{dt.day:02d}")
    result = result.replace("HH", f"{dt.hour:02d}")
    result = result.replace("UU", f"{dt.minute:02d}")
    result = result.replace("SS", f"{dt.second:02d}")
    return result


def convert_forcing(nc_path, var_name, source_unit, target_unit,
                    output_dir, name_template, output_format="asc",
                    bbox=None):
    """Main conversion function."""
    os.makedirs(output_dir, exist_ok=True)

    ds = nc.Dataset(nc_path, "r")
    lat, lon = get_nc_coords(ds)
    times = get_time_array(ds)
    data_var = ds.variables[var_name]

    count = 0
    for ti, t in enumerate(times):
        dt = t if isinstance(t, datetime) else datetime(t.year, t.month, t.day,
                                                         t.hour, t.minute, t.second)
        # Extract 2D slice
        if data_var.ndim == 3:
            data_2d = data_var[ti, :, :]
        elif data_var.ndim == 4:
            data_2d = data_var[ti, 0, :, :]
        else:
            continue

        data_2d = np.array(data_2d, dtype=np.float64)

        # Handle fill values / missing
        if hasattr(data_var, "_FillValue"):
            fill = data_var._FillValue
            data_2d[data_2d == fill] = EF5_NODATA
        data_2d[np.isnan(data_2d)] = EF5_NODATA

        # Clip to bbox
        if bbox is not None:
            data_2d, clat, clon = clip_to_bbox(data_2d, lat, lon, bbox)
            if data_2d is None:
                continue
        else:
            clat, clon = lat, lon

        # Apply unit conversion (only to valid data)
        valid = data_2d != EF5_NODATA
        converted = data_2d.copy()
        converted[valid] = apply_unit_conversion(data_2d[valid], source_unit, target_unit)

        # Sanity check
        valid_data = converted[valid]
        if len(valid_data) > 0:
            if target_unit == "mm/h" and np.max(valid_data) > 500:
                print(f"WARNING: Timestep {dt}: max precip = {np.max(valid_data):.1f} mm/h "
                      f"(suspiciously high). Check unit conversion.")

        # Write output
        fname = format_ef5_filename(name_template, dt)
        fpath = os.path.join(output_dir, fname)

        if output_format == "tif":
            write_geotiff(fpath, converted, clon, clat)
        else:
            write_esri_ascii(fpath, converted, clon, clat)

        count += 1
        if count % 100 == 0:
            print(f"  Processed {count}/{len(times)} timesteps...")

    ds.close()
    print(f"Converted {count} timesteps to {output_dir}")
    return count


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to EF5 grid format"
    )
    parser.add_argument("nc_path", help="Input NetCDF file path")
    parser.add_argument("var_name", help="Variable name in NetCDF (e.g., 'prec', 'pet')")
    parser.add_argument("--source-unit", required=True,
                        help="Source unit (mm/h, mm/3h, mm/day, K, C)")
    parser.add_argument("--target-unit", default="mm/h",
                        help="Target unit for EF5 (default: mm/h)")
    parser.add_argument("--output-dir", required=True,
                        help="Output directory for grid files")
    parser.add_argument("--name-template", default="forcing_YYYYMMDDHHUU.asc",
                        help="EF5 filename template with date tokens")
    parser.add_argument("--format", choices=["asc", "tif"], default="asc",
                        help="Output grid format")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
                        help="Bounding box for clipping")

    args = parser.parse_args()

    # Step 1: Validate inputs
    print("=== Step 1: Validating inputs ===")
    errors = validate_inputs(args.nc_path, args.var_name, args.source_unit, args.bbox)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        sys.exit(1)
    print("  Input validation passed.")

    # Step 2: Process
    print("=== Step 2: Converting forcing data ===")
    count = convert_forcing(
        nc_path=args.nc_path,
        var_name=args.var_name,
        source_unit=args.source_unit,
        target_unit=args.target_unit,
        output_dir=args.output_dir,
        name_template=args.name_template,
        output_format=args.format,
        bbox=args.bbox,
    )

    # Step 3: Validate outputs
    print("=== Step 3: Validating outputs ===")
    errors = validate_outputs(args.output_dir, expected_count=count)
    if errors:
        for e in errors:
            print(f"WARNING: {e}")
    else:
        print(f"  Output validation passed. {count} files created.")

    print("Done.")


if __name__ == "__main__":
    main()
