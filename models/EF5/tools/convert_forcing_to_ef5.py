#!/usr/bin/env python3
"""
convert_forcing_to_ef5.py — Convert global forcing data to EF5 gridded format.

Converts CMFD, MSWX, GPM, or generic NetCDF/GeoTIFF forcing into EF5-compatible
precipitation and PET grids (ASC or TIF format) with correct unit conversions.

EF5 expects:
  - Precipitation: rate in mm/hr (UNIT=mm/h in config)
  - PET: rate in mm/hr (UNIT=mm/h) or monthly mm (UNIT=mm/m) or temperature in degC (UNIT=C)

Pipeline: validate inputs → extract/resample → convert units → write grids → validate outputs
"""

import argparse
import os
import sys
import struct
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BIF_HEADER_SIZE = 50
BIF_HEADER_FMT = "<iiffff26s"  # ncols, nrows, xll, yll, cellsize, nodata, padding

PRECIP_UNIT_CONVERSIONS = {
    # source_unit -> mm/hr
    "mm/hr": 1.0,
    "mm/h": 1.0,
    "mm/3h": 1.0 / 3.0,
    "mm/3hr": 1.0 / 3.0,
    "mm/day": 1.0 / 24.0,
    "mm/d": 1.0 / 24.0,
    "m/s": 3600.0 * 1000.0,
    "kg/m2/s": 3600.0,  # 1 kg/m2 = 1 mm
    "mm/s": 3600.0,
}

PET_UNIT_CONVERSIONS = {
    "mm/hr": 1.0,
    "mm/h": 1.0,
    "mm/day": 1.0 / 24.0,
    "mm/d": 1.0 / 24.0,
    "mm/month": 1.0 / 720.0,  # approximate
    "mm/m": 1.0 / 720.0,
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_inputs(precip_dir, pet_dir, bbox, start_date, end_date):
    """Validate all input arguments before processing."""
    errors = []
    if precip_dir and not os.path.isdir(precip_dir):
        errors.append(f"Precipitation directory not found: {precip_dir}")
    if pet_dir and not os.path.isdir(pet_dir):
        errors.append(f"PET directory not found: {pet_dir}")
    if bbox:
        if len(bbox) != 4:
            errors.append(f"Bounding box must have 4 values [west, south, east, north], got {len(bbox)}")
        else:
            west, south, east, north = bbox
            if west >= east:
                errors.append(f"West ({west}) must be < East ({east})")
            if south >= north:
                errors.append(f"South ({south}) must be < North ({north})")
    if start_date and end_date and start_date >= end_date:
        errors.append(f"Start date ({start_date}) must be before end date ({end_date})")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        return False
    return True


def validate_outputs(output_dir, expected_count, var_type="precip"):
    """Validate output grids exist and have reasonable values."""
    files = sorted(Path(output_dir).glob("*.tif")) + sorted(Path(output_dir).glob("*.asc"))
    if len(files) == 0:
        print(f"[ERROR] No output files found in {output_dir}", file=sys.stderr)
        return False
    if len(files) < expected_count * 0.9:
        print(f"[WARNING] Expected ~{expected_count} files, found {len(files)}", file=sys.stderr)

    # Spot-check first file
    first = files[0]
    if str(first).endswith(".asc"):
        data = read_asc_grid(str(first))
    else:
        data = read_tif_grid(str(first))

    if data is not None:
        valid = data[~np.isnan(data)]
        if len(valid) > 0:
            if var_type == "precip":
                if valid.max() > 500.0:
                    print(f"[WARNING] Max precip = {valid.max():.1f} mm/hr — likely wrong units", file=sys.stderr)
                if valid.min() < 0:
                    print(f"[WARNING] Negative precipitation values found", file=sys.stderr)
            elif var_type == "pet":
                if valid.max() > 50.0:
                    print(f"[WARNING] Max PET = {valid.max():.1f} mm/hr — check units", file=sys.stderr)
    print(f"[OK] {len(files)} {var_type} grids validated in {output_dir}")
    return True


# ---------------------------------------------------------------------------
# Grid I/O
# ---------------------------------------------------------------------------
def read_asc_grid(filepath):
    """Read ESRI ASCII grid, return numpy array."""
    with open(filepath, "r") as f:
        header = {}
        for _ in range(6):
            line = f.readline().strip().split()
            header[line[0].lower()] = float(line[1])
        ncols = int(header["ncols"])
        nrows = int(header["nrows"])
        nodata = header.get("nodata_value", -9999)
        data = np.loadtxt(f, dtype=np.float32)
        data[data == nodata] = np.nan
    return data.reshape(nrows, ncols)


def read_tif_grid(filepath):
    """Read float32 GeoTIFF using GDAL or fallback."""
    try:
        from osgeo import gdal
        ds = gdal.Open(filepath)
        if ds is None:
            return None
        band = ds.GetRasterBand(1)
        data = band.ReadAsArray().astype(np.float32)
        nodata = band.GetNoDataValue()
        if nodata is not None:
            data[data == nodata] = np.nan
        ds = None
        return data
    except ImportError:
        try:
            import rasterio
            with rasterio.open(filepath) as src:
                data = src.read(1).astype(np.float32)
                if src.nodata is not None:
                    data[data == src.nodata] = np.nan
                return data
        except ImportError:
            print("[ERROR] Neither GDAL nor rasterio available", file=sys.stderr)
            return None


def write_asc_grid(filepath, data, xll, yll, cellsize, nodata=-9999.0):
    """Write ESRI ASCII grid."""
    nrows, ncols = data.shape
    out = data.copy()
    out[np.isnan(out)] = nodata
    with open(filepath, "w") as f:
        f.write(f"ncols         {ncols}\n")
        f.write(f"nrows         {nrows}\n")
        f.write(f"xllcorner     {xll}\n")
        f.write(f"yllcorner     {yll}\n")
        f.write(f"cellsize      {cellsize}\n")
        f.write(f"NODATA_value  {nodata}\n")
        for row in range(nrows):
            f.write(" ".join(f"{v:.4f}" for v in out[row]) + "\n")


def write_bif_grid(filepath, data, xll, yll, cellsize, nodata=-9999.0):
    """Write EF5 BIF (binary) grid with 50-byte header."""
    nrows, ncols = data.shape
    out = data.copy()
    out[np.isnan(out)] = nodata
    header = struct.pack(
        BIF_HEADER_FMT,
        ncols, nrows, xll, yll, cellsize, nodata, b"\x00" * 26
    )
    with open(filepath, "wb") as f:
        f.write(header)
        out.astype(np.float32).tofile(f)


def write_tif_grid(filepath, data, xll, yll, cellsize, nodata=-9999.0):
    """Write float32 GeoTIFF."""
    try:
        from osgeo import gdal, osr
        nrows, ncols = data.shape
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(filepath, ncols, nrows, 1, gdal.GDT_Float32)
        ds.SetGeoTransform([xll, cellsize, 0, yll + nrows * cellsize, 0, -cellsize])
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(nodata)
        out = data.copy()
        out[np.isnan(out)] = nodata
        band.WriteArray(out)
        ds.FlushCache()
        ds = None
    except ImportError:
        # Fallback to ASC
        write_asc_grid(filepath.replace(".tif", ".asc"), data, xll, yll, cellsize, nodata)


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
def convert_precip_units(data, source_unit, target_unit="mm/h"):
    """Convert precipitation to EF5 internal rate (mm/hr)."""
    source_unit_lower = source_unit.lower()
    if source_unit_lower not in PRECIP_UNIT_CONVERSIONS:
        raise ValueError(f"Unknown precip unit: {source_unit}. Supported: {list(PRECIP_UNIT_CONVERSIONS.keys())}")
    factor = PRECIP_UNIT_CONVERSIONS[source_unit_lower]
    return data * factor


def convert_pet_units(data, source_unit, target_unit="mm/h"):
    """Convert PET to EF5 internal rate (mm/hr)."""
    source_unit_lower = source_unit.lower()
    if source_unit_lower not in PET_UNIT_CONVERSIONS:
        raise ValueError(f"Unknown PET unit: {source_unit}. Supported: {list(PET_UNIT_CONVERSIONS.keys())}")
    factor = PET_UNIT_CONVERSIONS[source_unit_lower]
    return data * factor


# ---------------------------------------------------------------------------
# NetCDF forcing extraction
# ---------------------------------------------------------------------------
def extract_netcdf_forcing(nc_path, var_name, bbox, time_idx=0):
    """Extract a single timestep from a NetCDF file within bbox."""
    try:
        import netCDF4 as nc
    except ImportError:
        import xarray as xr
        ds = xr.open_dataset(nc_path)
        var = ds[var_name]
        if "time" in var.dims:
            var = var.isel(time=time_idx)
        if bbox:
            west, south, east, north = bbox
            lon_name = "lon" if "lon" in var.dims else "longitude"
            lat_name = "lat" if "lat" in var.dims else "latitude"
            var = var.sel({lon_name: slice(west, east), lat_name: slice(south, north)})
        return var.values.astype(np.float32), ds
    ds = nc.Dataset(nc_path, "r")
    var = ds.variables[var_name]
    if var.ndim == 3:
        data = var[time_idx, :, :].astype(np.float32)
    else:
        data = var[:, :].astype(np.float32)
    ds.close()
    return data, None


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------
def convert_forcing(
    precip_dir,
    pet_dir,
    output_dir,
    bbox,
    start_date,
    end_date,
    precip_unit="mm/h",
    pet_unit="mm/h",
    output_format="tif",
    freq_hours=1,
):
    """
    Convert forcing data directory to EF5-format grids.

    Parameters
    ----------
    precip_dir : str — Directory containing source precipitation files
    pet_dir : str — Directory containing source PET files
    output_dir : str — Output directory for converted grids
    bbox : list — [west, south, east, north] bounding box
    start_date : datetime — Start of period
    end_date : datetime — End of period
    precip_unit : str — Source precipitation unit
    pet_unit : str — Source PET unit
    output_format : str — "tif", "asc", or "bif"
    freq_hours : int — Forcing frequency in hours
    """
    # Validate
    if not validate_inputs(precip_dir, pet_dir, bbox, start_date, end_date):
        return False

    precip_out = os.path.join(output_dir, "precip")
    pet_out = os.path.join(output_dir, "pet")
    os.makedirs(precip_out, exist_ok=True)
    os.makedirs(pet_out, exist_ok=True)

    writer = {"tif": write_tif_grid, "asc": write_asc_grid, "bif": write_bif_grid}
    write_fn = writer.get(output_format, write_tif_grid)
    ext = output_format if output_format != "bif" else "bif"

    # Process precipitation
    n_steps = 0
    current = start_date
    while current < end_date:
        datestr = current.strftime("%Y%m%d%H%M")
        # Try to find matching source file
        for pattern in [f"*{current.strftime('%Y%m%d%H')}*", f"*{current.strftime('%Y%m%d')}*"]:
            matches = sorted(Path(precip_dir).glob(pattern))
            if matches:
                src_file = str(matches[0])
                if src_file.endswith(".nc") or src_file.endswith(".nc4"):
                    data, _ = extract_netcdf_forcing(src_file, "precipitation", bbox)
                elif src_file.endswith(".tif"):
                    data = read_tif_grid(src_file)
                elif src_file.endswith(".asc"):
                    data = read_asc_grid(src_file)
                else:
                    current += timedelta(hours=freq_hours)
                    continue

                if data is not None:
                    data = convert_precip_units(data, precip_unit)
                    out_path = os.path.join(precip_out, f"precip_{datestr}.{ext}")
                    # Use default geo-reference (should be read from source in production)
                    if bbox:
                        write_fn(out_path, data, bbox[0], bbox[1], 0.1)
                    else:
                        write_fn(out_path, data, 0.0, 0.0, 0.1)
                    n_steps += 1
                break
        current += timedelta(hours=freq_hours)

    print(f"[OK] Wrote {n_steps} precipitation grids to {precip_out}")

    # Process PET (typically monthly)
    if pet_dir:
        pet_files = sorted(Path(pet_dir).glob("*"))
        for pf in pet_files:
            pf_str = str(pf)
            if pf_str.endswith(".tif"):
                data = read_tif_grid(pf_str)
            elif pf_str.endswith(".asc"):
                data = read_asc_grid(pf_str)
            else:
                continue
            if data is not None:
                data = convert_pet_units(data, pet_unit)
                out_path = os.path.join(pet_out, f"{pf.stem}.{ext}")
                if bbox:
                    write_fn(out_path, data, bbox[0], bbox[1], 0.1)
                else:
                    write_fn(out_path, data, 0.0, 0.0, 0.1)

    # Validate outputs
    validate_outputs(precip_out, n_steps, "precip")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Convert forcing data to EF5 format")
    parser.add_argument("--precip-dir", required=True, help="Source precipitation directory")
    parser.add_argument("--pet-dir", help="Source PET directory")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"),
                        help="Bounding box [west south east north]")
    parser.add_argument("--start", required=True, help="Start date YYYYMMDD")
    parser.add_argument("--end", required=True, help="End date YYYYMMDD")
    parser.add_argument("--precip-unit", default="mm/h", help="Source precip unit")
    parser.add_argument("--pet-unit", default="mm/h", help="Source PET unit")
    parser.add_argument("--format", default="tif", choices=["tif", "asc", "bif"])
    parser.add_argument("--freq", type=int, default=1, help="Forcing frequency in hours")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y%m%d")
    end = datetime.strptime(args.end, "%Y%m%d")

    success = convert_forcing(
        args.precip_dir, args.pet_dir, args.output_dir,
        args.bbox, start, end,
        args.precip_unit, args.pet_unit, args.format, args.freq,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
