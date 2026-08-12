#!/usr/bin/env python3
"""
convert_forcing_to_cwatm.py — Convert global forcing data (CMFD/ERA5/MSWX/ISIMIP)
to CWatM-compatible NetCDF meteorological inputs.

CRITICAL UNIT CONVERSIONS:
  - Precipitation: kg m⁻² s⁻¹ is CWatM's expected input. CWatM multiplies by
    precipitation_coversion (default 86.4) to get m/day.
    If input is mm/day: write as-is and set precipitation_coversion = 0.001
    If input is m/day: write as-is and set precipitation_coversion = 1.0
    If input is kg/m²/s: write as-is and set precipitation_coversion = 86.4 (default)
  - Temperature: Must match TemperatureInKelvin flag. K or °C.
  - Radiation: W/m² (CWatM converts internally: W → MJ via ×86400×1e-6)
  - Pressure: Pa
  - Wind: m/s (10m height)
  - Humidity: specific humidity (kg/kg) or relative humidity (%)

CWatM NetCDF format:
  Dimensions: lat, lon, time
  Variables: standard CF names with calendar='standard'
  Coordinate reference: WGS84 (EPSG:4326)

Usage:
    python convert_forcing_to_cwatm.py \\
        --forcing_dir /path/to/cmfd/ \\
        --forcing_type cmfd \\
        --bbox 45.0 50.0 5.0 15.0 \\
        --start_date 2000-01-01 --end_date 2010-12-31 \\
        --output_dir /path/to/cwatm_meteo/

    python convert_forcing_to_cwatm.py \\
        --forcing_dir /path/to/era5/ \\
        --forcing_type era5 \\
        --bbox -35.0 -25.0 20.0 35.0 \\
        --start_date 1990-01-01 --end_date 2020-12-31 \\
        --output_dir /path/to/cwatm_meteo/
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

try:
    from osgeo import gdal
except ImportError:
    gdal = None


# ---------------------------------------------------------------------------
# CWatM expected variable mapping
# ---------------------------------------------------------------------------
CWATM_VARIABLES = {
    "precipitation": {
        "long_name": "Precipitation",
        "units": "kg m-2 s-1",
        "standard_name": "precipitation_flux",
    },
    "tavg": {
        "long_name": "Average air temperature",
        "units": "K",
        "standard_name": "air_temperature",
    },
    "tmin": {
        "long_name": "Minimum air temperature",
        "units": "K",
        "standard_name": "air_temperature",
    },
    "tmax": {
        "long_name": "Maximum air temperature",
        "units": "K",
        "standard_name": "air_temperature",
    },
    "psurf": {
        "long_name": "Surface air pressure",
        "units": "Pa",
        "standard_name": "surface_air_pressure",
    },
    "wind": {
        "long_name": "Wind speed at 10m",
        "units": "m s-1",
        "standard_name": "wind_speed",
    },
    "rsds": {
        "long_name": "Surface downwelling shortwave radiation",
        "units": "W m-2",
        "standard_name": "surface_downwelling_shortwave_flux_in_air",
    },
    "rsdl": {
        "long_name": "Surface downwelling longwave radiation",
        "units": "W m-2",
        "standard_name": "surface_downwelling_longwave_flux_in_air",
    },
    "qair": {
        "long_name": "Specific humidity",
        "units": "kg kg-1",
        "standard_name": "specific_humidity",
    },
    "rhs": {
        "long_name": "Relative humidity",
        "units": "%",
        "standard_name": "relative_humidity",
    },
}

# Forcing type-specific variable name mappings
FORCING_VAR_MAPS = {
    "cmfd": {
        "prec": "precipitation",
        "temp": "tavg",
        "shum": "qair",
        "pres": "psurf",
        "wind": "wind",
        "srad": "rsds",
        "lrad": "rsdl",
    },
    "era5": {
        "tp": "precipitation",
        "t2m": "tavg",
        "d2m": "tmin",  # dew point → used for humidity
        "sp": "psurf",
        "u10": "wind",
        "ssrd": "rsds",
        "strd": "rsdl",
    },
    "isimip": {
        "pr": "precipitation",
        "tas": "tavg",
        "tasmin": "tmin",
        "tasmax": "tmax",
        "ps": "psurf",
        "sfcWind": "wind",
        "rsds": "rsds",
        "rlds": "rsdl",
        "huss": "qair",
    },
}

# Unit conversion functions per forcing type
UNIT_CONVERSIONS = {
    "cmfd": {
        "precipitation": lambda x: x,  # Already kg/m²/s
        "tavg": lambda x: x,  # Already K
        "qair": lambda x: x,  # Already kg/kg
        "psurf": lambda x: x,  # Already Pa
        "wind": lambda x: x,  # Already m/s
        "rsds": lambda x: np.maximum(x, 0.0),  # Clip negative
        "rsdl": lambda x: x,
    },
    "era5": {
        "precipitation": lambda x: x / 86400.0,  # m/day → kg/m²/s (≈mm/s)
        "tavg": lambda x: x,  # Already K
        "psurf": lambda x: x,  # Already Pa
        "wind": lambda x: np.abs(x),  # Ensure positive
        "rsds": lambda x: np.maximum(x / 86400.0, 0.0),  # J/m²/day → W/m²
        "rsdl": lambda x: x / 86400.0,  # J/m²/day → W/m²
    },
    "isimip": {
        "precipitation": lambda x: x,  # Already kg/m²/s
        "tavg": lambda x: x,  # Already K
        "tmin": lambda x: x,
        "tmax": lambda x: x,
        "psurf": lambda x: x,  # Already Pa
        "wind": lambda x: x,
        "rsds": lambda x: np.maximum(x, 0.0),
        "rsdl": lambda x: x,
        "qair": lambda x: x,
    },
}


def validate_inputs(args):
    """Validate all input arguments before processing."""
    errors = []

    if not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory not found: {args.forcing_dir}")

    if args.forcing_type not in FORCING_VAR_MAPS:
        errors.append(
            f"Unknown forcing type: {args.forcing_type}. "
            f"Supported: {list(FORCING_VAR_MAPS.keys())}"
        )

    if len(args.bbox) != 4:
        errors.append("--bbox requires exactly 4 values: lat_min lat_max lon_min lon_max")
    else:
        lat_min, lat_max, lon_min, lon_max = args.bbox
        if lat_min >= lat_max:
            errors.append(f"lat_min ({lat_min}) must be < lat_max ({lat_max})")
        if lon_min >= lon_max:
            errors.append(f"lon_min ({lon_min}) must be < lon_max ({lon_max})")

    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        errors.append(f"Invalid date format: {e}")

    if nc is None:
        errors.append("netCDF4 package not installed. Install with: pip install netCDF4")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def read_forcing_variable(forcing_dir, forcing_type, var_name, bbox, start_date, end_date):
    """
    Read a single forcing variable from NetCDF files.

    Returns
    -------
    data : np.ndarray
        3D array (time, lat, lon) with the variable data
    times : np.ndarray
        1D array of datetime objects
    lats : np.ndarray
        1D array of latitudes
    lons : np.ndarray
        1D array of longitudes
    """
    import glob

    lat_min, lat_max, lon_min, lon_max = bbox

    # Find NetCDF files matching the variable (case-insensitive subdir names)
    # CMFD uses mixed-case dirs: Prec/, Temp/, SHum/, Pres/, Wind/, SRad/, LRad/, RHum/
    cap = var_name.capitalize()
    patterns = [
        os.path.join(forcing_dir, f"*{var_name}*.nc"),
        os.path.join(forcing_dir, f"*{var_name}*.nc4"),
        os.path.join(forcing_dir, var_name, "*.nc"),
        os.path.join(forcing_dir, cap, "*.nc"),
        os.path.join(forcing_dir, var_name.upper(), "*.nc"),
    ]
    # Add case-insensitive subdir match (handles SHum, SRad, LRad, RHum, etc.)
    try:
        for entry in os.listdir(forcing_dir):
            if entry.lower() == var_name.lower():
                patterns.append(os.path.join(forcing_dir, entry, "*.nc"))
    except OSError:
        pass

    files = []
    for pattern in patterns:
        files.extend(sorted(glob.glob(pattern)))
    # Deduplicate while preserving sort order
    seen = set()
    files = [f for f in files if not (f in seen or seen.add(f))]

    if not files:
        return None, None, None, None

    import cftime as _cftime

    # Parse target period using cftime to avoid cftime-vs-datetime comparison issues
    _start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    _end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # Read grid coords from the first file (same for all CMFD files)
    _ds0 = nc.Dataset(files[0])
    lat_var = next((v for v in _ds0.variables if v.lower() in ("lat", "latitude", "y")), None)
    lon_var = next((v for v in _ds0.variables if v.lower() in ("lon", "longitude", "x")), None)
    time_var = next((v for v in _ds0.variables if v.lower() in ("time", "t")), None)
    if lat_var is None or lon_var is None or time_var is None:
        _ds0.close()
        return None, None, None, None
    lats = _ds0.variables[lat_var][:].copy()
    lons = _ds0.variables[lon_var][:].copy()

    # Find the data variable name from the first file
    data_var = None
    for vname in _ds0.variables:
        if vname.lower() == var_name.lower() or var_name in vname:
            if len(_ds0.variables[vname].dimensions) >= 2:
                data_var = vname
                break
    _ds0.close()

    if data_var is None:
        return None, None, None, None

    # Subset spatially
    lat_mask = (lats >= lat_min) & (lats <= lat_max)
    lon_mask = (lons >= lon_min) & (lons <= lon_max)
    out_lats = lats[lat_mask]
    out_lons = lons[lon_mask]

    # Loop through each file (nc.MFDataset doesn't support NETCDF4 format)
    all_data = []
    all_times = []
    for fpath in files:
        ds = nc.Dataset(fpath)
        times = nc.num2date(
            ds.variables[time_var][:],
            ds.variables[time_var].units,
            ds.variables[time_var].calendar if hasattr(ds.variables[time_var], "calendar") else "standard",
        )
        # Convert cftime objects to Python datetimes for robust comparison
        py_times = []
        for t in times:
            try:
                py_times.append(datetime(t.year, t.month, t.day, t.hour, t.minute, t.second))
            except Exception:
                py_times.append(None)
        # Compare on the calendar DATE, not the timestamp: CMFD daily files are
        # stamped at 10:30, so `t <= end_date 00:00` silently drops the last day.
        time_mask = np.array([
            (t is not None and _start_dt.date() <= t.date() <= _end_dt.date())
            for t in py_times
        ])
        if time_mask.sum() == 0:
            ds.close()
            continue
        # Read only selected time steps to save memory, then subset spatially
        tidx = np.where(time_mask)[0]
        chunk = ds.variables[data_var][tidx, :, :]
        chunk = np.asarray(chunk)  # convert MaskedArray to ndarray
        chunk = chunk[:, lat_mask, :][:, :, lon_mask]
        all_data.append(chunk)
        all_times.extend([py_times[i] for i in tidx])
        ds.close()

    if not all_data:
        return None, None, None, None

    data = np.concatenate(all_data, axis=0)
    out_times = np.array(all_times)
    return data, out_times, out_lats, out_lons


def write_cwatm_netcdf(output_path, var_name, data, times, lats, lons, metadata):
    """Write a single variable to CWatM-compatible NetCDF."""
    ds = nc.Dataset(output_path, "w", format="NETCDF4")

    # Dimensions
    ds.createDimension("time", None)  # unlimited
    ds.createDimension("lat", len(lats))
    ds.createDimension("lon", len(lons))

    # Coordinate variables
    time_var = ds.createVariable("time", "f8", ("time",))
    time_var.units = f"days since {times[0].strftime('%Y-%m-%d')}"
    time_var.calendar = "standard"
    time_var.standard_name = "time"

    lat_var = ds.createVariable("lat", "f8", ("lat",))
    lat_var.units = "degrees_north"
    lat_var.standard_name = "latitude"
    lat_var[:] = lats

    lon_var = ds.createVariable("lon", "f8", ("lon",))
    lon_var.units = "degrees_east"
    lon_var.standard_name = "longitude"
    lon_var[:] = lons

    # Time values
    ref_date = times[0]
    time_values = np.array([(t - ref_date).total_seconds() / 86400.0 for t in times])
    time_var[:] = time_values

    # Data variable
    data_var = ds.createVariable(
        var_name, "f4", ("time", "lat", "lon"),
        fill_value=-9999.0, zlib=True, complevel=4,
    )
    for key, val in metadata.items():
        setattr(data_var, key, val)
    data_var[:] = data

    # Global attributes
    ds.Conventions = "CF-1.6"
    ds.title = f"CWatM forcing: {var_name}"
    ds.institution = "Converted for CWatM"
    ds.history = f"Created {datetime.now().isoformat()}"

    ds.close()


def _edges(centres):
    """Cell edges of a regular 1-D coordinate axis given its centres."""
    c = np.asarray(centres, dtype=float)
    step = c[1] - c[0]
    return np.concatenate([c - step / 2.0, [c[-1] + step / 2.0]])


def _overlap_weights(src_centres, dst_centres, cosine_lat=False):
    """Area-weighted 1-D regrid matrix, shape (len(dst), len(src)).

    Each destination cell is the source-cell average weighted by the length of
    the overlap (times cos(lat) on a latitude axis, so a coarse lat/lon cell
    receives the true area-weighted mean).
    """
    se, de = _edges(src_centres), _edges(dst_centres)
    slo, shi = np.minimum(se[:-1], se[1:]), np.maximum(se[:-1], se[1:])
    dlo, dhi = np.minimum(de[:-1], de[1:]), np.maximum(de[:-1], de[1:])
    ov = np.maximum(0.0, np.minimum(dhi[:, None], shi[None, :]) -
                         np.maximum(dlo[:, None], slo[None, :]))
    if cosine_lat:
        ov = ov * np.cos(np.radians(np.asarray(src_centres, dtype=float)))[None, :]
    tot = ov.sum(axis=1, keepdims=True)
    if np.any(tot <= 0):
        bad = np.flatnonzero(tot.ravel() <= 0)
        raise SystemExit(
            f"--target_res regrid: destination cells {bad.tolist()} have no source "
            f"overlap — the source window does not cover the target grid")
    return ov / tot


def regrid_to_target(data, lats, lons, bbox, target_res):
    """Area-weighted regrid of (time, lat, lon) onto the CWatM target grid.

    The target grid is exactly the one build_cwatm_static.py produces for the
    same --bbox / --res, including the CWatM-mandatory N→S latitude order.
    """
    lat_min, lat_max, lon_min, lon_max = bbox
    dst_lat = np.arange(lat_max - target_res / 2, lat_min, -target_res)
    dst_lon = np.arange(lon_min + target_res / 2, lon_max, target_res)
    wlat = _overlap_weights(lats, dst_lat, cosine_lat=True)
    wlon = _overlap_weights(lons, dst_lon)
    out = np.einsum("ij,tjk,lk->til", wlat, np.asarray(data, dtype=np.float64), wlon)
    return out.astype(np.float32), dst_lat, dst_lon


def read_daily_minmax_from_3hr(three_hr_dir, bbox, start_date, end_date):
    """Daily tmin/tmax from the CMFD 3-hourly temperature archive.

    CMFD daily files carry only the daily mean.  A constant ±4 K placeholder
    diurnal range biases Penman-Monteith, so take the min/max over the eight
    3-hourly steps of each day instead.
    """
    import glob
    from datetime import datetime as _dt

    lat_min, lat_max, lon_min, lon_max = bbox
    files = sorted(glob.glob(os.path.join(three_hr_dir, "*.nc")))
    if not files:
        raise SystemExit(f"no 3-hourly NetCDF files in {three_hr_dir}")
    s, e = _dt.strptime(start_date, "%Y-%m-%d"), _dt.strptime(end_date, "%Y-%m-%d")

    tmins, tmaxs, days = [], [], []
    lats = lons = None
    ilat = ilon = None
    for f in files:
        ym = os.path.basename(f).rsplit("_", 1)[-1][:6]
        if not ym.isdigit():
            continue
        y, m = int(ym[:4]), int(ym[4:])
        if (y, m) < (s.year, s.month) or (y, m) > (e.year, e.month):
            continue
        ds = nc.Dataset(f)
        if lats is None:
            la, lo = np.array(ds.variables["lat"][:]), np.array(ds.variables["lon"][:])
            ilat = np.flatnonzero((la >= lat_min) & (la <= lat_max))
            ilon = np.flatnonzero((lo >= lon_min) & (lo <= lon_max))
            lats, lons = la[ilat], lo[ilon]
        t = ds.variables["time"]
        tt = nc.num2date(t[:], t.units, only_use_cftime_datetimes=False)
        a = np.asarray(ds.variables["temp"][:, ilat[0]:ilat[-1] + 1, ilon[0]:ilon[-1] + 1])
        ds.close()
        nd = a.shape[0] // 8
        if nd * 8 != a.shape[0]:
            raise SystemExit(f"{f}: {a.shape[0]} steps is not a whole number of 3-hourly days")
        a = a.reshape(nd, 8, a.shape[1], a.shape[2])
        tmins.append(a.min(axis=1))
        tmaxs.append(a.max(axis=1))
        days.extend([datetime(tt[i * 8].year, tt[i * 8].month, tt[i * 8].day) for i in range(nd)])

    if not tmins:
        raise SystemExit(f"no 3-hourly files covering {start_date}..{end_date}")
    tmin = np.concatenate(tmins, axis=0)
    tmax = np.concatenate(tmaxs, axis=0)
    days = np.array(days)
    keep = np.array([s <= d <= e for d in days])
    return tmin[keep], tmax[keep], days[keep], lats, lons


def convert_forcing(args):
    """Main conversion pipeline: validate → process → validate."""
    forcing_type = args.forcing_type
    var_map = FORCING_VAR_MAPS[forcing_type]
    conversions = UNIT_CONVERSIONS.get(forcing_type, {})

    os.makedirs(args.output_dir, exist_ok=True)

    results = {"status": "success", "variables_converted": [], "warnings": []}

    target_res = getattr(args, "target_res", None)
    # When regridding, read one destination cell of padding so that every target
    # cell is fully covered by source cells.
    read_bbox = list(args.bbox)
    if target_res:
        read_bbox = [args.bbox[0] - target_res, args.bbox[1] + target_res,
                     args.bbox[2] - target_res, args.bbox[3] + target_res]

    def _emit(cwatm_var, data, times, lats, lons):
        if target_res:
            data, lats, lons = regrid_to_target(data, lats, lons, args.bbox, target_res)
        elif lats[0] < lats[-1]:
            data, lats = data[:, ::-1, :], lats[::-1]   # CWatM needs N→S latitude
        meta = CWATM_VARIABLES.get(cwatm_var, {})
        results["warnings"].extend(validate_converted_data(cwatm_var, data, meta))
        output_path = os.path.join(args.output_dir, f"{cwatm_var}.nc")
        write_cwatm_netcdf(output_path, cwatm_var, data, times, lats, lons, meta)
        results["variables_converted"].append({
            "variable": cwatm_var, "output_file": output_path,
            "shape": list(data.shape), "min": float(np.nanmin(data)),
            "max": float(np.nanmax(data)), "mean": float(np.nanmean(data)),
        })

    for src_var, cwatm_var in var_map.items():
        output_path = os.path.join(args.output_dir, f"{cwatm_var}.nc")
        if getattr(args, "resume", False) and os.path.exists(output_path):
            print(f"  {cwatm_var}: exists, skipping (--resume)")
            continue
        print(f"  Processing {src_var} → {cwatm_var}...")

        data, times, lats, lons = read_forcing_variable(
            args.forcing_dir, forcing_type, src_var,
            read_bbox, args.start_date, args.end_date,
        )

        if data is None:
            results["warnings"].append(f"Variable {src_var} not found, skipping")
            continue

        # Apply unit conversion
        if cwatm_var in conversions:
            data = conversions[cwatm_var](data)
        _emit(cwatm_var, data, times, lats, lons)

    three_hr = getattr(args, "tminmax_3hr_dir", None)
    if three_hr:
        need = [v for v in ("tmin", "tmax")
                if not (getattr(args, "resume", False) and
                        os.path.exists(os.path.join(args.output_dir, f"{v}.nc")))]
        if need:
            print(f"  Deriving {need} from 3-hourly temperature in {three_hr}...")
            tmin, tmax, days, la, lo = read_daily_minmax_from_3hr(
                three_hr, read_bbox, args.start_date, args.end_date)
            for v, arr in (("tmin", tmin), ("tmax", tmax)):
                if v in need:
                    _emit(v, arr, days, la, lo)
        else:
            print("  tmin/tmax: exist, skipping (--resume)")

    print(json.dumps(results, indent=2))
    return results


def validate_converted_data(var_name, data, meta):
    """Post-conversion validation to catch unit errors."""
    warnings = []

    if var_name == "precipitation":
        # kg/m²/s: typical range 0 to ~0.01 (≈ 864 mm/day max extreme)
        max_val = float(np.nanmax(data))
        if max_val > 0.1:
            warnings.append(
                f"UNIT TRAP: Precipitation max={max_val:.4f} kg/m²/s "
                f"(={max_val * 86400:.1f} mm/day). If > 1000 mm/day, units are likely wrong."
            )
        if max_val < 1e-8 and max_val >= 0:
            warnings.append(
                f"WARNING: Precipitation max={max_val:.2e}. All near-zero — check input."
            )

    elif var_name == "tavg":
        mean_val = float(np.nanmean(data))
        if mean_val < 100:
            warnings.append(
                f"UNIT TRAP: Temperature mean={mean_val:.1f}. "
                f"Likely in Celsius — set TemperatureInKelvin = False in settings, "
                f"or convert to Kelvin (+273.15)."
            )
        elif mean_val > 350:
            warnings.append(
                f"WARNING: Temperature mean={mean_val:.1f} K — unrealistically high."
            )

    elif var_name == "psurf":
        mean_val = float(np.nanmean(data))
        if mean_val < 2000:
            warnings.append(
                f"UNIT TRAP: Pressure mean={mean_val:.1f}. "
                f"Likely in hPa — multiply by 100 to get Pa."
            )

    elif var_name == "rsds":
        min_val = float(np.nanmin(data))
        if min_val < 0:
            warnings.append(
                f"WARNING: Shortwave radiation has negative values (min={min_val:.2f}). "
                f"Clipping to 0."
            )

    elif var_name == "rhs":
        max_val = float(np.nanmax(data))
        if max_val <= 1.0:
            warnings.append(
                f"UNIT TRAP: Relative humidity max={max_val:.3f}. "
                f"Likely fraction (0-1) — multiply by 100 for percentage."
            )

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert global forcing data to CWatM NetCDF format"
    )
    parser.add_argument("--forcing_dir", required=True, help="Input forcing directory")
    parser.add_argument(
        "--forcing_type", required=True,
        choices=["cmfd", "era5", "isimip", "mswx"],
        help="Type of forcing dataset",
    )
    parser.add_argument(
        "--bbox", type=float, nargs=4, required=True,
        metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"),
        help="Bounding box: lat_min lat_max lon_min lon_max",
    )
    parser.add_argument("--start_date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output_dir", required=True, help="Output directory for CWatM NetCDFs")
    parser.add_argument(
        "--target_res", type=float, default=None,
        help="Area-weighted regrid onto the static grid of this resolution (deg). "
             "Must equal build_cwatm_static.py --res.",
    )
    parser.add_argument(
        "--tminmax_3hr_dir", default=None,
        help="Directory of 3-hourly temperature NetCDFs; derives real daily tmin/tmax.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip variables whose output NetCDF already exists.",
    )

    args = parser.parse_args()

    print("=== CWatM Forcing Converter ===")
    print(f"Source: {args.forcing_type} from {args.forcing_dir}")
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"BBox: {args.bbox}")

    validate_inputs(args)
    convert_forcing(args)


if __name__ == "__main__":
    main()
