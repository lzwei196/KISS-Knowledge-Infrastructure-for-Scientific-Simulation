#!/usr/bin/env python3
"""
convert_forcing_to_noahmp.py — Stage s4: Meteorological Forcing Converter

Converts global reanalysis / gridded forcing data (CMFD, MSWX, ERA5, NASA POWER)
to Noah-MP HRLDAS LDASIN NetCDF format with proper unit conversions.

Pattern: validate_inputs → process → validate_outputs

Noah-MP HRLDAS expected forcing variables and units:
  T2D      — 2-m air temperature [K]
  Q2D      — 2-m specific humidity [kg/kg]
  U2D      — 10-m U-wind component [m/s]
  V2D      — 10-m V-wind component [m/s]
  PSFC     — Surface pressure [Pa]
  SWDOWN   — Downward shortwave radiation [W/m²]
  LWDOWN   — Downward longwave radiation [W/m²]
  RAINRATE — Precipitation rate [mm/s] (= kg/m²/s)

Output file naming: YYYYMMDDHH.LDASIN_DOMAIN1
"""

import os
import sys
import json
import argparse
import numpy as np
from datetime import datetime, timedelta

try:
    import netCDF4 as nc
except ImportError:
    nc = None

# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------
KELVIN_OFFSET = 273.15
PA_PER_HPA = 100.0
MM_PER_S_FROM_MM_PER_HR = 1.0 / 3600.0
MM_PER_S_FROM_MM_PER_DAY = 1.0 / 86400.0
MM_PER_S_FROM_M_PER_HR = 1000.0 / 3600.0

# Physical limits for validation
LIMITS = {
    "T2D":      {"min": 180.0, "max": 340.0, "unit": "K"},
    "Q2D":      {"min": 0.0,   "max": 0.06,  "unit": "kg/kg"},
    "U2D":      {"min": -75.0, "max": 75.0,  "unit": "m/s"},
    "V2D":      {"min": -75.0, "max": 75.0,  "unit": "m/s"},
    "PSFC":     {"min": 40000, "max": 110000, "unit": "Pa"},
    "SWDOWN":   {"min": 0.0,   "max": 1400.0, "unit": "W/m2"},
    "LWDOWN":   {"min": 40.0,  "max": 600.0,  "unit": "W/m2"},
    "RAINRATE": {"min": 0.0,   "max": 0.1,    "unit": "mm/s"},
}


def validate_inputs(args):
    """Validate all input arguments and data availability."""
    errors = []

    if not os.path.isdir(args.input_dir):
        errors.append(f"Input directory does not exist: {args.input_dir}")

    if args.lat < -90 or args.lat > 90:
        errors.append(f"Latitude out of range: {args.lat}")
    if args.lon < -180 or args.lon > 360:
        errors.append(f"Longitude out of range: {args.lon}")

    try:
        start = datetime.strptime(args.start_date, "%Y-%m-%d")
        end = datetime.strptime(args.end_date, "%Y-%m-%d")
        if end <= start:
            errors.append("end_date must be after start_date")
    except ValueError as e:
        errors.append(f"Date parsing error: {e}")

    if args.timestep not in [3600, 10800, 21600, 86400]:
        errors.append(f"Unusual timestep {args.timestep}s; expected 3600/10800/21600/86400")

    if nc is None:
        errors.append("netCDF4 package not installed. Install with: pip install netCDF4")

    if errors:
        print("INPUT VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    return {"start": start, "end": end}


def detect_source_format(input_dir):
    """Detect forcing data source format from file patterns."""
    files = os.listdir(input_dir)

    # CMFD: temp_YYYY.nc, prec_YYYY.nc, etc.
    if any("temp_" in f and f.endswith(".nc") for f in files):
        return "cmfd"
    # ERA5: era5_YYYY_MM.nc or single file
    if any("era5" in f.lower() for f in files):
        return "era5"
    # MSWX: mswx_Temp_YYYY.nc etc.
    if any("mswx" in f.lower() for f in files):
        return "mswx"
    # Generic NetCDF with standard names
    if any(f.endswith(".nc") for f in files):
        return "generic_nc"
    # CSV fallback
    if any(f.endswith(".csv") for f in files):
        return "csv"

    return "unknown"


def convert_temperature(temp_raw, source):
    """Convert temperature to Kelvin."""
    if source in ("cmfd", "mswx"):
        # CMFD/MSWX: Celsius -> Kelvin
        if np.nanmax(temp_raw) < 100:  # likely Celsius
            return temp_raw + KELVIN_OFFSET
    if np.nanmin(temp_raw) > 150:  # already Kelvin
        return temp_raw
    return temp_raw + KELVIN_OFFSET


def convert_humidity(q_raw, temp_k, psfc_pa, source):
    """Convert humidity to specific humidity [kg/kg]."""
    if np.nanmax(q_raw) > 1.0:
        # Likely relative humidity (0-100%)
        rh = q_raw
        # Compute saturation vapor pressure (Tetens formula)
        temp_c = temp_k - KELVIN_OFFSET
        es = 611.2 * np.exp(17.67 * temp_c / (temp_c + 243.5))  # Pa
        e = rh / 100.0 * es
        q = 0.622 * e / (psfc_pa - 0.378 * e)
        return np.clip(q, 0.0, 0.06)
    elif np.nanmax(q_raw) > 0.06:
        # Likely g/kg -> kg/kg
        return q_raw / 1000.0
    return q_raw  # Already kg/kg


def convert_pressure(p_raw, source):
    """Convert pressure to Pa."""
    if np.nanmax(p_raw) < 2000:
        # Likely hPa/mbar
        return p_raw * PA_PER_HPA
    if np.nanmax(p_raw) < 200:
        # Likely kPa
        return p_raw * 1000.0
    return p_raw  # Already Pa


def convert_precipitation(precip_raw, source, timestep_s):
    """Convert precipitation to mm/s."""
    if source == "cmfd":
        # CMFD: mm/hr -> mm/s
        return precip_raw * MM_PER_S_FROM_MM_PER_HR
    elif source == "era5":
        # ERA5: m accumulated per hour -> mm/s
        return precip_raw * MM_PER_S_FROM_M_PER_HR
    elif np.nanmax(precip_raw) > 0.5 and timestep_s >= 86400:
        # Likely mm/day
        return precip_raw * MM_PER_S_FROM_MM_PER_DAY
    elif np.nanmax(precip_raw) > 0.5:
        # Likely mm/hr
        return precip_raw * MM_PER_S_FROM_MM_PER_HR
    return precip_raw  # Already mm/s


def read_cmfd_at_point(input_dir, lat, lon, start, end):
    """Read CMFD forcing data at a single lat/lon point."""
    import glob

    variables = {
        "temp": "T2D", "shum": "Q2D", "wind": "WIND",
        "pres": "PSFC", "srad": "SWDOWN", "lrad": "LWDOWN", "prec": "RAINRATE"
    }
    data = {}
    times = None

    for cmfd_var, noahmp_var in variables.items():
        pattern = os.path.join(input_dir, f"{cmfd_var}_*.nc")
        files = sorted(glob.glob(pattern))
        if not files:
            raise FileNotFoundError(f"No CMFD files found for {cmfd_var}: {pattern}")

        all_vals = []
        all_times = []
        for fpath in files:
            with nc.Dataset(fpath, 'r') as ds:
                lats = ds.variables['lat'][:]
                lons = ds.variables['lon'][:]
                ilat = int(np.argmin(np.abs(lats - lat)))
                ilon = int(np.argmin(np.abs(lons - lon)))
                var_name = [v for v in ds.variables if v not in ('lat', 'lon', 'time')][0]
                vals = ds.variables[var_name][:, ilat, ilon]
                t = nc.num2date(ds.variables['time'][:],
                                ds.variables['time'].units,
                                only_use_cftime_datetimes=False)
                all_vals.append(vals)
                all_times.append(t)

        data[noahmp_var] = np.concatenate(all_vals)
        if times is None:
            times = np.concatenate(all_times)

    # CMFD wind is scalar speed; split equally into U and V
    if "WIND" in data:
        wind = data.pop("WIND")
        data["U2D"] = wind / np.sqrt(2.0)
        data["V2D"] = wind / np.sqrt(2.0)

    return times, data


def read_generic_nc_at_point(input_dir, lat, lon, start, end):
    """Read generic NetCDF forcing data."""
    import glob
    files = sorted(glob.glob(os.path.join(input_dir, "*.nc")))
    if not files:
        raise FileNotFoundError(f"No NetCDF files in {input_dir}")

    # Try reading the first file to detect variable names
    with nc.Dataset(files[0], 'r') as ds:
        var_names = list(ds.variables.keys())

    # Map common variable names to Noah-MP names
    name_map = {
        "t2m": "T2D", "T2M": "T2D", "tmp": "T2D", "TMP": "T2D", "T2D": "T2D",
        "q2m": "Q2D", "Q2M": "Q2D", "SPFH": "Q2D", "Q2D": "Q2D",
        "u10": "U2D", "U10M": "U2D", "UGRD": "U2D", "U2D": "U2D",
        "v10": "V2D", "V10M": "V2D", "VGRD": "V2D", "V2D": "V2D",
        "sp": "PSFC", "PS": "PSFC", "PRES": "PSFC", "PSFC": "PSFC",
        "ssrd": "SWDOWN", "DSWRF": "SWDOWN", "SWDOWN": "SWDOWN",
        "strd": "LWDOWN", "DLWRF": "LWDOWN", "LWDOWN": "LWDOWN",
        "tp": "RAINRATE", "APCP": "RAINRATE", "RAINRATE": "RAINRATE",
    }

    data = {}
    times = None

    for fpath in files:
        with nc.Dataset(fpath, 'r') as ds:
            lats = ds.variables.get('lat', ds.variables.get('latitude', None))
            lons = ds.variables.get('lon', ds.variables.get('longitude', None))
            if lats is None or lons is None:
                continue
            lats = lats[:]
            lons = lons[:]
            ilat = int(np.argmin(np.abs(lats - lat)))
            ilon = int(np.argmin(np.abs(lons - lon)))

            for vn in ds.variables:
                if vn in name_map:
                    target = name_map[vn]
                    vals = ds.variables[vn][:, ilat, ilon] if ds.variables[vn].ndim >= 3 \
                        else ds.variables[vn][:]
                    if target not in data:
                        data[target] = []
                    data[target].append(vals)

            if times is None and 'time' in ds.variables:
                times = nc.num2date(ds.variables['time'][:],
                                    ds.variables['time'].units,
                                    only_use_cftime_datetimes=False)

    for k in data:
        data[k] = np.concatenate(data[k]) if isinstance(data[k], list) else data[k]

    return times, data


def write_ldasin(output_dir, timestamp, data_dict, lat, lon):
    """Write a single LDASIN NetCDF file for one timestep."""
    fname = timestamp.strftime("%Y%m%d%H") + ".LDASIN_DOMAIN1"
    fpath = os.path.join(output_dir, fname)

    with nc.Dataset(fpath, 'w', format='NETCDF4') as ds:
        ds.createDimension('Time', 1)
        ds.createDimension('south_north', 1)
        ds.createDimension('west_east', 1)

        for varname, value in data_dict.items():
            var = ds.createVariable(varname, 'f4', ('Time', 'south_north', 'west_east'))
            var[0, 0, 0] = float(value)
            if varname in LIMITS:
                var.units = LIMITS[varname]["unit"]

    return fpath


def process(args, context):
    """Main processing: read, convert, write LDASIN files."""
    start = context["start"]
    end = context["end"]
    os.makedirs(args.output_dir, exist_ok=True)

    source = detect_source_format(args.input_dir)
    print(f"Detected source format: {source}")

    # Read raw data
    if source == "cmfd":
        times, raw = read_cmfd_at_point(args.input_dir, args.lat, args.lon, start, end)
    else:
        times, raw = read_generic_nc_at_point(args.input_dir, args.lat, args.lon, start, end)

    if times is None or len(times) == 0:
        print("ERROR: No forcing data found in specified period", file=sys.stderr)
        sys.exit(1)

    # Apply unit conversions
    converted = {}
    converted["T2D"] = convert_temperature(raw.get("T2D", np.full(len(times), 280.0)), source)
    converted["PSFC"] = convert_pressure(raw.get("PSFC", np.full(len(times), 101325.0)), source)
    converted["Q2D"] = convert_humidity(
        raw.get("Q2D", np.full(len(times), 0.005)),
        converted["T2D"], converted["PSFC"], source
    )
    converted["U2D"] = raw.get("U2D", np.full(len(times), 0.0))
    converted["V2D"] = raw.get("V2D", np.full(len(times), 0.0))
    converted["SWDOWN"] = np.clip(raw.get("SWDOWN", np.full(len(times), 0.0)), 0.0, None)
    converted["LWDOWN"] = raw.get("LWDOWN", np.full(len(times), 300.0))
    converted["RAINRATE"] = np.clip(
        convert_precipitation(raw.get("RAINRATE", np.full(len(times), 0.0)), source, args.timestep),
        0.0, None
    )

    # Write LDASIN files
    n_written = 0
    n_warnings = 0
    for i, t in enumerate(times):
        ts = t if isinstance(t, datetime) else datetime(t.year, t.month, t.day, t.hour)
        if ts < start or ts > end:
            continue

        step_data = {}
        for varname in LIMITS:
            val = float(converted[varname][i])
            lim = LIMITS[varname]
            if val < lim["min"] or val > lim["max"]:
                n_warnings += 1
                if n_warnings <= 10:
                    print(f"  WARNING: {varname}={val:.4f} outside [{lim['min']}, {lim['max']}] "
                          f"at {ts}")
            step_data[varname] = val

        write_ldasin(args.output_dir, ts, step_data, args.lat, args.lon)
        n_written += 1

    return n_written, n_warnings


def validate_outputs(output_dir, n_written):
    """Validate output LDASIN files were created correctly."""
    errors = []

    files = [f for f in os.listdir(output_dir) if f.endswith(".LDASIN_DOMAIN1")]
    if len(files) == 0:
        errors.append("No LDASIN files were written")
    elif len(files) != n_written:
        errors.append(f"Expected {n_written} files, found {len(files)}")

    # Spot-check first file
    if files:
        fpath = os.path.join(output_dir, sorted(files)[0])
        with nc.Dataset(fpath, 'r') as ds:
            for varname in ["T2D", "Q2D", "U2D", "V2D", "PSFC", "SWDOWN", "LWDOWN", "RAINRATE"]:
                if varname not in ds.variables:
                    errors.append(f"Missing variable {varname} in {fpath}")

    if errors:
        print("OUTPUT VALIDATION WARNINGS:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Convert global forcing data to Noah-MP HRLDAS LDASIN format"
    )
    parser.add_argument("--input_dir", required=True, help="Input forcing data directory")
    parser.add_argument("--output_dir", required=True, help="Output LDASIN directory")
    parser.add_argument("--lat", type=float, required=True, help="Latitude of point")
    parser.add_argument("--lon", type=float, required=True, help="Longitude of point")
    parser.add_argument("--start_date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--timestep", type=int, default=3600,
                        help="Output timestep in seconds (default: 3600)")
    parser.add_argument("--source", default="auto",
                        help="Source format: cmfd/era5/mswx/auto (default: auto)")

    args = parser.parse_args()

    print("=" * 60)
    print("Noah-MP Forcing Converter")
    print("=" * 60)

    context = validate_inputs(args)
    print(f"  Input:  {args.input_dir}")
    print(f"  Output: {args.output_dir}")
    print(f"  Point:  ({args.lat}, {args.lon})")
    print(f"  Period: {args.start_date} to {args.end_date}")
    print(f"  Timestep: {args.timestep}s")

    n_written, n_warnings = process(args, context)
    print(f"\nWrote {n_written} LDASIN files ({n_warnings} warnings)")

    ok = validate_outputs(args.output_dir, n_written)
    if ok:
        print("OUTPUT VALIDATION: PASSED")
    else:
        print("OUTPUT VALIDATION: WARNINGS (check messages above)")

    # Write summary JSON
    summary = {
        "tool": "convert_forcing_to_noahmp",
        "n_files": n_written,
        "n_warnings": n_warnings,
        "output_dir": args.output_dir,
        "source_format": detect_source_format(args.input_dir),
        "validation": "passed" if ok else "warnings",
    }
    summary_path = os.path.join(args.output_dir, "forcing_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"Summary written to {summary_path}")


if __name__ == "__main__":
    main()
