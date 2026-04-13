#!/usr/bin/env python3
"""
convert_forcing_to_wrf.py - Convert global reanalysis data to WPS intermediate format.

Converts ERA5, GFS, or NCEP-FNL NetCDF/GRIB files into WPS intermediate format
files that can be ingested by metgrid.exe.

Pipeline stage: S2 (Meteorological Forcing)
Pattern: validate -> process -> validate

Usage:
    python convert_forcing_to_wrf.py \
        --input /path/to/era5_files/ \
        --output /path/to/wps_intermediate/ \
        --source ERA5 \
        --start 2020-06-15_00 \
        --end 2020-06-18_00
"""

import argparse
import json
import os
import struct
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------
KELVIN_OFFSET = 273.15
HPA_TO_PA = 100.0
GKG_TO_KGKG = 0.001
KNOTS_TO_MS = 0.514444
KMH_TO_MS = 1.0 / 3.6
MJ_TO_W = 1e6 / 86400.0  # MJ m-2 day-1 -> W m-2

# WPS intermediate format field codes
WPS_FIELD_MAP = {
    # 3D pressure-level fields
    "TT":       {"description": "Temperature",              "units": "K",        "internal": "K"},
    "UU":       {"description": "U-component wind",         "units": "m s-1",    "internal": "m s-1"},
    "VV":       {"description": "V-component wind",         "units": "m s-1",    "internal": "m s-1"},
    "GHT":      {"description": "Geopotential height",      "units": "m",        "internal": "m"},
    "RH":       {"description": "Relative humidity",        "units": "%",        "internal": "%"},
    "SPECHUMD": {"description": "Specific humidity",        "units": "kg kg-1",  "internal": "kg kg-1"},
    # 2D surface fields
    "PMSL":     {"description": "Sea-level pressure",       "units": "Pa",       "internal": "Pa"},
    "PSFC":     {"description": "Surface pressure",         "units": "Pa",       "internal": "Pa"},
    "SKINTEMP": {"description": "Skin temperature",         "units": "K",        "internal": "K"},
    "TT":       {"description": "Temperature",              "units": "K",        "internal": "K"},
    "LANDSEA":  {"description": "Land/sea mask",            "units": "0/1",      "internal": "fraction"},
    "SOILHGT":  {"description": "Soil height (terrain)",    "units": "m",        "internal": "m"},
    "SST":      {"description": "Sea surface temperature",  "units": "K",        "internal": "K"},
    "SM":       {"description": "Soil moisture",            "units": "m3 m-3",   "internal": "m3 m-3"},
    "ST":       {"description": "Soil temperature",         "units": "K",        "internal": "K"},
}

# Source-specific variable mappings
SOURCE_VARIABLE_MAP = {
    "ERA5": {
        "t":    ("TT",       lambda x: x,                 "Temperature already in K"),
        "u":    ("UU",       lambda x: x,                 "Wind already in m/s"),
        "v":    ("VV",       lambda x: x,                 "Wind already in m/s"),
        "z":    ("GHT",      lambda x: x / 9.81,          "CRITICAL: geopotential (m2/s2) -> height (m), divide by g"),
        "q":    ("SPECHUMD", lambda x: x,                 "Specific humidity in kg/kg"),
        "r":    ("RH",       lambda x: x,                 "Relative humidity in %"),
        "sp":   ("PSFC",     lambda x: x,                 "Surface pressure in Pa"),
        "msl":  ("PMSL",     lambda x: x,                 "Mean sea level pressure in Pa"),
        "skt":  ("SKINTEMP", lambda x: x,                 "Skin temperature in K"),
        "sst":  ("SST",      lambda x: x,                 "SST in K"),
        "lsm":  ("LANDSEA",  lambda x: x,                 "Land-sea mask fraction"),
        "swvl1":("SM000010", lambda x: x,                 "Soil moisture 0-10cm, m3/m3"),
        "swvl2":("SM010040", lambda x: x,                 "Soil moisture 10-40cm"),
        "swvl3":("SM040100", lambda x: x,                 "Soil moisture 40-100cm"),
        "swvl4":("SM100200", lambda x: x,                 "Soil moisture 100-200cm"),
        "stl1": ("ST000010", lambda x: x,                 "Soil temp 0-10cm in K"),
        "stl2": ("ST010040", lambda x: x,                 "Soil temp 10-40cm"),
        "stl3": ("ST040100", lambda x: x,                 "Soil temp 40-100cm"),
        "stl4": ("ST100200", lambda x: x,                 "Soil temp 100-200cm"),
    },
    "GFS": {
        "TMP":    ("TT",       lambda x: x,               "Temperature in K"),
        "UGRD":   ("UU",       lambda x: x,               "U-wind in m/s"),
        "VGRD":   ("VV",       lambda x: x,               "V-wind in m/s"),
        "HGT":    ("GHT",      lambda x: x,               "Geopotential height in m"),
        "RH":     ("RH",       lambda x: x,               "Relative humidity in %"),
        "PRMSL":  ("PMSL",     lambda x: x,               "MSL pressure in Pa"),
        "PRES":   ("PSFC",     lambda x: x,               "Surface pressure in Pa"),
        "TMP_SFC":("SKINTEMP", lambda x: x,               "Surface temperature in K"),
        "LAND":   ("LANDSEA",  lambda x: x,               "Land fraction"),
    },
    "FNL": {
        "TMP":    ("TT",       lambda x: x,               "Temperature in K"),
        "UGRD":   ("UU",       lambda x: x,               "U-wind in m/s"),
        "VGRD":   ("VV",       lambda x: x,               "V-wind in m/s"),
        "HGT":    ("GHT",      lambda x: x,               "Geopotential height in m"),
        "RH":     ("RH",       lambda x: x,               "Relative humidity in %"),
        "PRMSL":  ("PMSL",     lambda x: x,               "MSL pressure in Pa"),
        "PRES":   ("PSFC",     lambda x: x,               "Surface pressure in Pa"),
    },
}

# Pressure levels commonly used (hPa)
STANDARD_PRESSURE_LEVELS = [
    1000, 975, 950, 925, 900, 850, 800, 750, 700,
    650, 600, 550, 500, 450, 400, 350, 300, 250,
    200, 150, 100, 70, 50, 30, 20, 10
]


def validate_inputs(input_dir: str, source: str, start: str, end: str) -> dict:
    """Validate all inputs before processing."""
    errors = []
    warnings = []

    # Check input directory exists
    if not os.path.isdir(input_dir):
        errors.append(f"Input directory does not exist: {input_dir}")

    # Check source is supported
    if source not in SOURCE_VARIABLE_MAP:
        errors.append(f"Unsupported source: {source}. Must be one of: {list(SOURCE_VARIABLE_MAP.keys())}")

    # Parse dates
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d_%H")
    except ValueError:
        errors.append(f"Invalid start date format: {start}. Expected YYYY-MM-DD_HH")
        start_dt = None

    try:
        end_dt = datetime.strptime(end, "%Y-%m-%d_%H")
    except ValueError:
        errors.append(f"Invalid end date format: {end}. Expected YYYY-MM-DD_HH")
        end_dt = None

    if start_dt and end_dt and start_dt >= end_dt:
        errors.append(f"Start date ({start}) must be before end date ({end})")

    # Check for netCDF library
    try:
        import netCDF4  # noqa: F401
    except ImportError:
        errors.append("netCDF4 Python package not installed. Run: pip install netCDF4")

    # Check input files exist
    if os.path.isdir(input_dir):
        nc_files = list(Path(input_dir).glob("*.nc")) + list(Path(input_dir).glob("*.grib*"))
        if len(nc_files) == 0:
            errors.append(f"No NetCDF or GRIB files found in {input_dir}")
        else:
            print(f"  Found {len(nc_files)} input files")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def write_wps_intermediate_field(fh, field_name, data, hdate, xfcst, xlvl,
                                  startlat, startlon, deltalat, deltalon,
                                  nx, ny, earth_radius=6371229.0,
                                  iproj=0, truelat1=0.0, truelat2=0.0,
                                  xlonc=0.0, description="", units=""):
    """
    Write a single field in WPS intermediate binary format (version 5).

    WPS intermediate format specification:
      IFV=5, record-based Fortran unformatted binary with big-endian byte order.
    """
    import numpy as np

    ifv = 5
    map_source = "CONVERTED"
    is_wind_grid_rel = False

    # Record 1: version
    record1 = struct.pack(">i", ifv)
    _write_fortran_record(fh, record1)

    # Record 2: header
    hdate_b = hdate.ljust(24).encode("ascii")[:24]
    xfcst_f = float(xfcst)
    map_source_b = field_name.ljust(32).encode("ascii")[:32]
    field_b = field_name.ljust(9).encode("ascii")[:9]
    units_b = units.ljust(25).encode("ascii")[:25]
    desc_b = description.ljust(46).encode("ascii")[:46]

    record2 = struct.pack(">24sf32s9s25s46sfiifffffi?",
                          hdate_b, xfcst_f, map_source_b, field_b,
                          units_b, desc_b, xlvl,
                          nx, ny, iproj,
                          startlat, startlon, deltalat, deltalon,
                          earth_radius, is_wind_grid_rel)
    _write_fortran_record(fh, record2)

    # Record 3: data slab (row-major, big-endian floats)
    slab = np.array(data, dtype=">f4").tobytes()
    _write_fortran_record(fh, slab)


def _write_fortran_record(fh, data):
    """Write a Fortran unformatted record with 4-byte length markers."""
    length = len(data)
    fh.write(struct.pack(">i", length))
    fh.write(data)
    fh.write(struct.pack(">i", length))


def convert_era5_to_wps(input_dir: str, output_dir: str, start: str, end: str):
    """
    Convert ERA5 NetCDF files to WPS intermediate format.

    UNIT TRAPS:
    - ERA5 geopotential 'z' is in m2/s2, must divide by g=9.81 to get height in m
    - ERA5 pressure levels are in hPa in the file but WPS expects Pa in field metadata
    - ERA5 specific humidity may need conversion to RH for some WPS setups
    - ERA5 soil moisture is volumetric (m3/m3) -- correct for WRF
    - ERA5 accumulated fields (precip, radiation) need de-accumulation
    """
    try:
        import netCDF4 as nc
        import numpy as np
    except ImportError:
        return {"status": "error", "message": "netCDF4 and numpy required"}

    os.makedirs(output_dir, exist_ok=True)
    start_dt = datetime.strptime(start, "%Y-%m-%d_%H")
    end_dt = datetime.strptime(end, "%Y-%m-%d_%H")

    nc_files = sorted(Path(input_dir).glob("*.nc"))
    files_processed = 0
    fields_written = 0

    var_map = SOURCE_VARIABLE_MAP["ERA5"]

    for nc_file in nc_files:
        ds = nc.Dataset(str(nc_file), "r")
        times = nc.num2date(ds.variables["time"][:], ds.variables["time"].units)

        lats = ds.variables["latitude"][:]
        lons = ds.variables["longitude"][:]
        ny, nx = len(lats), len(lons)
        startlat = float(lats[0])
        startlon = float(lons[0])
        deltalat = float(lats[1] - lats[0]) if len(lats) > 1 else 0.25
        deltalon = float(lons[1] - lons[0]) if len(lons) > 1 else 0.25

        for ti, t in enumerate(times):
            t_dt = datetime(t.year, t.month, t.day, t.hour)
            if t_dt < start_dt or t_dt > end_dt:
                continue

            hdate = t_dt.strftime("%Y-%m-%d_%H:%M:%S")
            outfile = os.path.join(output_dir, f"FILE:{hdate}")

            with open(outfile, "wb") as fh:
                for era5_var, (wps_field, converter, note) in var_map.items():
                    if era5_var not in ds.variables:
                        continue

                    var_data = ds.variables[era5_var]
                    ndims = len(var_data.dimensions)

                    if ndims == 4:  # pressure-level (time, level, lat, lon)
                        levels = ds.variables["level"][:]
                        for li, lev in enumerate(levels):
                            slab = converter(np.array(var_data[ti, li, :, :], dtype=np.float32))
                            xlvl = float(lev) * HPA_TO_PA  # hPa -> Pa for WPS
                            write_wps_intermediate_field(
                                fh, wps_field, slab.flatten(), hdate, 0.0, xlvl,
                                startlat, startlon, deltalat, deltalon, nx, ny,
                                description=WPS_FIELD_MAP.get(wps_field, {}).get("description", ""),
                                units=WPS_FIELD_MAP.get(wps_field, {}).get("units", ""),
                            )
                            fields_written += 1
                    elif ndims == 3:  # surface (time, lat, lon)
                        slab = converter(np.array(var_data[ti, :, :], dtype=np.float32))
                        xlvl = 200100.0  # surface code
                        write_wps_intermediate_field(
                            fh, wps_field, slab.flatten(), hdate, 0.0, xlvl,
                            startlat, startlon, deltalat, deltalon, nx, ny,
                            description=WPS_FIELD_MAP.get(wps_field, {}).get("description", ""),
                            units=WPS_FIELD_MAP.get(wps_field, {}).get("units", ""),
                        )
                        fields_written += 1

            files_processed += 1

        ds.close()

    return {
        "status": "success",
        "files_processed": files_processed,
        "fields_written": fields_written,
        "output_dir": output_dir,
    }


def validate_outputs(output_dir: str, start: str, end: str) -> dict:
    """Validate that WPS intermediate files were created correctly."""
    errors = []
    warnings = []

    files = sorted(Path(output_dir).glob("FILE:*"))
    if len(files) == 0:
        errors.append("No WPS intermediate files produced")
        return {"valid": False, "errors": errors, "warnings": warnings}

    print(f"  Produced {len(files)} WPS intermediate files")

    # Check file sizes (should be > 0)
    for f in files:
        size = f.stat().st_size
        if size == 0:
            errors.append(f"Empty output file: {f.name}")
        elif size < 1000:
            warnings.append(f"Suspiciously small output file: {f.name} ({size} bytes)")

    # Check temporal coverage
    start_dt = datetime.strptime(start, "%Y-%m-%d_%H")
    end_dt = datetime.strptime(end, "%Y-%m-%d_%H")
    first_file = files[0].name.replace("FILE:", "")
    last_file = files[-1].name.replace("FILE:", "")
    print(f"  Time range: {first_file} to {last_file}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "n_files": len(files),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert global reanalysis data to WPS intermediate format for WRF"
    )
    parser.add_argument("--input", required=True, help="Input directory with NetCDF/GRIB files")
    parser.add_argument("--output", required=True, help="Output directory for WPS intermediate files")
    parser.add_argument("--source", required=True, choices=["ERA5", "GFS", "FNL"],
                        help="Data source type")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD_HH)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD_HH)")
    args = parser.parse_args()

    print("=" * 60)
    print("WRF Forcing Converter: Reanalysis -> WPS Intermediate")
    print("=" * 60)
    print(f"  Source:  {args.source}")
    print(f"  Input:   {args.input}")
    print(f"  Output:  {args.output}")
    print(f"  Period:  {args.start} to {args.end}")

    # Step 1: Validate inputs
    print("\n[1/3] Validating inputs...")
    v = validate_inputs(args.input, args.source, args.start, args.end)
    if not v["valid"]:
        print("VALIDATION FAILED:")
        for e in v["errors"]:
            print(f"  ERROR: {e}")
        sys.exit(1)
    for w in v["warnings"]:
        print(f"  WARNING: {w}")

    # Step 2: Convert
    print("\n[2/3] Converting forcing data...")
    if args.source == "ERA5":
        result = convert_era5_to_wps(args.input, args.output, args.start, args.end)
    else:
        result = {"status": "error", "message": f"Source {args.source} conversion not yet implemented"}

    if result["status"] != "success":
        print(f"CONVERSION FAILED: {result.get('message', 'Unknown error')}")
        sys.exit(1)

    # Step 3: Validate outputs
    print("\n[3/3] Validating outputs...")
    vo = validate_outputs(args.output, args.start, args.end)
    if not vo["valid"]:
        print("OUTPUT VALIDATION FAILED:")
        for e in vo["errors"]:
            print(f"  ERROR: {e}")
        sys.exit(1)
    for w in vo["warnings"]:
        print(f"  WARNING: {w}")

    print("\nDONE - Conversion successful")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
