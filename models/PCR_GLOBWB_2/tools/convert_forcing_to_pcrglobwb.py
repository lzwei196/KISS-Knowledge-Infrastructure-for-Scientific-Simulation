#!/usr/bin/env python3
"""
PCR-GLOBWB 2 Forcing Converter
===============================
Converts global meteorological forcing data (ERA5, CMFD, CRU, W5E5) to
PCR-GLOBWB 2 NetCDF format with correct units and variable naming.

Pipeline stage: s2 (Forcing Preparation)
Pattern: validate_inputs → process → validate_outputs

PCR-GLOBWB expects:
  - precipitation:  m/day  (NOT mm/day)
  - temperature:    degrees Celsius (NOT Kelvin)
  - referencePotET: m/day  (NOT mm/day)
  - NetCDF variable names: 'precipitation', 'temperature', 'referencePotET'

Unit conversion traps:
  dt_001: Precipitation must be m/day, not mm/day (divide by 1000)
  dt_002: Temperature must be Celsius, not Kelvin (subtract 273.15)
  dt_003: Reference ET must be m/day, not mm/day (divide by 1000)

Two entry points
----------------
1. ``process()`` / CLI -- rewrite EXISTING gridded NetCDFs into PCR-GLOBWB
   units and variable names.
2. ``build_from_ki_forcing()`` -- build forcing DIRECTLY on a clone grid from
   the shared ``ki_tools_common.load_forcing`` point loader. This is what a
   regional run uses: it needs no pre-existing gridded file, and it derives a
   physically-based reference ET (see below).

Reference ET (dt_028)
---------------------
PCR-GLOBWB's ``referenceETPotMethod = Hamon`` derives refET from temperature
alone. Hamon systematically UNDER-estimates PET in cold continental basins: at
Songhua/Harbin it yields ~665 mm/yr against ~907 mm/yr for FAO-56
Penman-Monteith computed from the same CMFD record. The missing evaporation
leaves the basin as runoff, so discharge is biased high by a nearly constant
fraction in every month (PBIAS +76%, r 0.86 -- a volume offset, not a timing
error).

CMFD ships downward shortwave radiation, wind speed, specific humidity and
surface pressure alongside precipitation and temperature. When those fields are
present, derive refET with FAO-56 Penman-Monteith and run the model with
``referenceETPotMethod = Input`` + ``refETPotFileNC``. Reserve Hamon for
forcings that genuinely lack radiation/wind/humidity.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(precip_nc, temp_nc, refet_nc, source_format):
    """Validate that input files exist and source format is recognized."""
    errors = []

    for label, path in [("Precipitation", precip_nc), ("Temperature", temp_nc)]:
        if path and not os.path.exists(path):
            errors.append(f"{label} file not found: {path}")

    if refet_nc and not os.path.exists(refet_nc):
        errors.append(f"Reference ET file not found: {refet_nc}")

    valid_sources = ["era5", "cmfd", "cru_era_interim", "w5e5", "custom"]
    if source_format not in valid_sources:
        errors.append(f"Unknown source format '{source_format}'. Valid: {valid_sources}")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"Input validation failed: {len(errors)} error(s)")

    logger.info("Input validation passed.")
    return True


def validate_outputs(output_dir, start_date, end_date):
    """Validate output NetCDF files have correct units and ranges."""
    warnings = []
    errors = []

    precip_file = os.path.join(output_dir, "precipitation.nc")
    temp_file = os.path.join(output_dir, "temperature.nc")
    refet_file = os.path.join(output_dir, "referencePotET.nc")

    if nc is None:
        logger.warning("netCDF4 not available; skipping output validation.")
        return True

    # Check precipitation (m/day)
    if os.path.exists(precip_file):
        with nc.Dataset(precip_file, "r") as ds:
            if "precipitation" not in ds.variables:
                errors.append("dt_009: Variable 'precipitation' not found in output")
            else:
                data = ds.variables["precipitation"][:]
                max_val = float(np.nanmax(data))
                if max_val > 1.0:
                    warnings.append(
                        f"dt_001: Max precipitation = {max_val:.4f} m/day — "
                        f"suspiciously high. Likely still in mm/day?"
                    )
                if max_val < 1e-6:
                    warnings.append("Precipitation all zeros — check input file")
                logger.info(f"Precipitation range: {float(np.nanmin(data)):.6f} to {max_val:.6f} m/day")

    # Check temperature (Celsius)
    if os.path.exists(temp_file):
        with nc.Dataset(temp_file, "r") as ds:
            if "temperature" not in ds.variables:
                errors.append("dt_009: Variable 'temperature' not found in output")
            else:
                data = ds.variables["temperature"][:]
                min_val = float(np.nanmin(data))
                max_val = float(np.nanmax(data))
                if max_val > 100:
                    errors.append(
                        f"dt_002: Max temperature = {max_val:.1f} — "
                        f"likely still in Kelvin. Subtract 273.15"
                    )
                logger.info(f"Temperature range: {min_val:.1f} to {max_val:.1f} deg C")

    # Check reference ET (m/day)
    if os.path.exists(refet_file):
        with nc.Dataset(refet_file, "r") as ds:
            varname = None
            for vn in ["referencePotET", "evapotranspiration"]:
                if vn in ds.variables:
                    varname = vn
                    break
            if varname is None:
                errors.append("dt_009: Neither 'referencePotET' nor 'evapotranspiration' found in output")
            else:
                data = ds.variables[varname][:]
                max_val = float(np.nanmax(data))
                if max_val > 0.1:
                    warnings.append(
                        f"dt_003: Max refET = {max_val:.4f} m/day — "
                        f"suspiciously high. Likely still in mm/day?"
                    )
                logger.info(f"Reference ET range: {float(np.nanmin(data)):.6f} to {max_val:.6f} m/day")

    for w in warnings:
        logger.warning(w)
    for e in errors:
        logger.error(e)

    if errors:
        raise ValueError(f"Output validation failed: {len(errors)} error(s)")

    logger.info("Output validation passed.")
    return True


# ---------------------------------------------------------------------------
# Conversion functions per source
# ---------------------------------------------------------------------------

def _get_unit_conversions(source_format):
    """Return conversion factors for each source format.

    Returns dict with keys: precip_factor, precip_offset,
    temp_factor, temp_offset, et_factor, et_offset.
    """
    conversions = {
        "era5": {
            "precip_factor": 1.0 / 1000.0,   # mm/day -> m/day
            "precip_offset": 0.0,
            "temp_factor": 1.0,
            "temp_offset": -273.15,           # K -> C
            "et_factor": 1.0 / 1000.0,       # mm/day -> m/day
            "et_offset": 0.0,
            "precip_varname": "tp",
            "temp_varname": "t2m",
            "et_varname": "pev",
        },
        "cmfd": {
            "precip_factor": 1.0 / 1000.0,   # mm/day -> m/day
            "precip_offset": 0.0,
            "temp_factor": 1.0,
            "temp_offset": -273.15,           # K -> C
            "et_factor": 1.0 / 1000.0,
            "et_offset": 0.0,
            "precip_varname": "prcp",
            "temp_varname": "temp",
            "et_varname": "pet",
        },
        "cru_era_interim": {
            "precip_factor": 1.0,             # already m/day in CRU-ERA
            "precip_offset": 0.0,
            "temp_factor": 1.0,               # already Celsius
            "temp_offset": 0.0,
            "et_factor": 1.0,                 # already m/day
            "et_offset": 0.0,
            "precip_varname": "precipitation",
            "temp_varname": "temperature",
            "et_varname": "referencePotET",
        },
        "w5e5": {
            "precip_factor": 86400.0 / 1000.0,  # kg/m2/s -> m/day
            "precip_offset": 0.0,
            "temp_factor": 1.0,
            "temp_offset": -273.15,              # K -> C
            "et_factor": 1.0 / 1000.0,          # mm/day -> m/day
            "et_offset": 0.0,
            "precip_varname": "pr",
            "temp_varname": "tas",
            "et_varname": "evspsblpot",
        },
        "custom": {
            "precip_factor": 1.0 / 1000.0,
            "precip_offset": 0.0,
            "temp_factor": 1.0,
            "temp_offset": 0.0,
            "et_factor": 1.0 / 1000.0,
            "et_offset": 0.0,
            "precip_varname": "precipitation",
            "temp_varname": "temperature",
            "et_varname": "referencePotET",
        },
    }
    return conversions[source_format]


def convert_variable(input_nc, output_nc, src_varname, dst_varname,
                     factor, offset, units, long_name):
    """Read a variable from input NetCDF, apply factor+offset, write to output.

    output = input * factor + offset
    """
    if nc is None:
        raise ImportError("netCDF4 is required for conversion")

    with nc.Dataset(input_nc, "r") as src:
        if src_varname not in src.variables:
            available = list(src.variables.keys())
            raise KeyError(
                f"Variable '{src_varname}' not found in {input_nc}. "
                f"Available: {available}"
            )

        src_var = src.variables[src_varname]
        data = src_var[:]

        # Apply conversion
        data = data * factor + offset

        # Ensure precipitation and ET are non-negative
        if "precip" in dst_varname.lower() or "et" in dst_varname.lower() or "evap" in dst_varname.lower():
            data = np.maximum(data, 0.0)

        # Get dimensions
        time_var = src.variables.get("time")
        lat_var = src.variables.get("lat", src.variables.get("latitude"))
        lon_var = src.variables.get("lon", src.variables.get("longitude"))

        # Create output
        with nc.Dataset(output_nc, "w", format="NETCDF4") as dst:
            # Copy dimensions
            for dim_name, dim in src.dimensions.items():
                dst.createDimension(dim_name, len(dim) if not dim.isunlimited() else None)

            # Copy coordinate variables
            if time_var is not None:
                t = dst.createVariable("time", time_var.dtype, time_var.dimensions)
                t[:] = time_var[:]
                for attr in time_var.ncattrs():
                    t.setncattr(attr, time_var.getncattr(attr))

            if lat_var is not None:
                lat_name = "lat" if "lat" in src.variables else "latitude"
                la = dst.createVariable(lat_name, lat_var.dtype, lat_var.dimensions)
                la[:] = lat_var[:]
                for attr in lat_var.ncattrs():
                    la.setncattr(attr, lat_var.getncattr(attr))

            if lon_var is not None:
                lon_name = "lon" if "lon" in src.variables else "longitude"
                lo = dst.createVariable(lon_name, lon_var.dtype, lon_var.dimensions)
                lo[:] = lon_var[:]
                for attr in lon_var.ncattrs():
                    lo.setncattr(attr, lon_var.getncattr(attr))

            # Write converted data
            out_var = dst.createVariable(
                dst_varname, "f4", src_var.dimensions,
                fill_value=1e20, zlib=True
            )
            out_var[:] = data
            out_var.units = units
            out_var.long_name = long_name

            # Global attributes
            dst.description = f"PCR-GLOBWB 2 forcing: {dst_varname}"
            dst.history = f"Converted on {datetime.now().isoformat()}"
            dst.source = f"Original: {input_nc}"

    logger.info(f"Converted {src_varname} -> {dst_varname} in {output_nc}")
    logger.info(f"  Factor={factor}, Offset={offset}, Units={units}")


# ---------------------------------------------------------------------------
# Main process
# ---------------------------------------------------------------------------

def process(precip_nc, temp_nc, refet_nc, output_dir, source_format,
            start_date=None, end_date=None):
    """Convert forcing data from source format to PCR-GLOBWB format.

    Args:
        precip_nc: Path to precipitation NetCDF
        temp_nc: Path to temperature NetCDF
        refet_nc: Path to reference ET NetCDF (optional)
        output_dir: Output directory for converted files
        source_format: One of 'era5', 'cmfd', 'cru_era_interim', 'w5e5', 'custom'
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
    """
    os.makedirs(output_dir, exist_ok=True)

    conv = _get_unit_conversions(source_format)

    # Precipitation
    if precip_nc:
        logger.info(f"Converting precipitation from {source_format} format...")
        convert_variable(
            precip_nc,
            os.path.join(output_dir, "precipitation.nc"),
            conv["precip_varname"], "precipitation",
            conv["precip_factor"], conv["precip_offset"],
            "m.day-1", "daily precipitation"
        )

    # Temperature
    if temp_nc:
        logger.info(f"Converting temperature from {source_format} format...")
        convert_variable(
            temp_nc,
            os.path.join(output_dir, "temperature.nc"),
            conv["temp_varname"], "temperature",
            conv["temp_factor"], conv["temp_offset"],
            "degrees Celsius", "mean daily air temperature"
        )

    # Reference ET
    if refet_nc:
        logger.info(f"Converting reference ET from {source_format} format...")
        convert_variable(
            refet_nc,
            os.path.join(output_dir, "referencePotET.nc"),
            conv["et_varname"], "referencePotET",
            conv["et_factor"], conv["et_offset"],
            "m.day-1", "daily reference potential evapotranspiration"
        )

    logger.info(f"All conversions complete. Output in: {output_dir}")


# ---------------------------------------------------------------------------
# Reference ET: FAO-56 Penman-Monteith (dt_028)
# ---------------------------------------------------------------------------

def fao56_penman_monteith(doy, t_mean_c, srad_wm2, wind_ms, shum_kgkg, pres_pa,
                          lat_deg, wind_height_m=10.0, albedo=0.23):
    """Daily FAO-56 reference evapotranspiration ET0, in mm/day.

    Allen et al. (1998), FAO Irrigation & Drainage Paper 56, eq. 6, with the
    net-radiation parameterisation of eq. 37-40 and the psychrometric constant
    computed from the ACTUAL surface pressure rather than from elevation.

    Tmax/Tmin: the CMFD *daily* product carries a single temperature per day,
    so Tmax == Tmin == Tmean. FAO-56 Annex 4 sanctions using Tmean for the
    saturation vapour pressure and for the long-wave term in that case; es is
    then slightly under-estimated, making this a mildly CONSERVATIVE ET0.

    All inputs are 1-D arrays over time except lat_deg (scalar, degrees).
    Returns ET0 clamped at >= 0 (Penman-Monteith can go slightly negative on
    cold, humid, low-radiation winter days).
    """
    t = np.asarray(t_mean_c, dtype=float)
    rs = np.asarray(srad_wm2, dtype=float) * 0.0864          # W/m2 -> MJ/m2/day
    q = np.asarray(shum_kgkg, dtype=float)
    p_kpa = np.asarray(pres_pa, dtype=float) / 1000.0        # Pa -> kPa
    doy = np.asarray(doy, dtype=float)

    # wind at 2 m (FAO-56 eq. 47)
    u2 = np.asarray(wind_ms, dtype=float) * 4.87 / np.log(67.8 * wind_height_m - 5.42)

    es = 0.6108 * np.exp(17.27 * t / (t + 237.3))            # eq. 11, kPa
    ea = q * p_kpa / (0.622 + 0.378 * q)                     # specific humidity -> kPa
    ea = np.clip(ea, 0.0, es)                                # no supersaturation
    delta = 4098.0 * es / (t + 237.3) ** 2                   # eq. 13, kPa/degC
    gamma = 0.665e-3 * p_kpa                                 # eq. 8, kPa/degC

    # extraterrestrial radiation Ra (eq. 21-25)
    phi = np.radians(lat_deg)
    dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * doy / 365.0)
    dec = 0.409 * np.sin(2.0 * np.pi * doy / 365.0 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1.0, 1.0))
    ra = (24.0 * 60.0 / np.pi) * 0.0820 * dr * (
        ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws)
    )
    rso = 0.75 * ra                                          # eq. 37 with z ~ 0

    # cloudiness factor; undefined where Rso == 0 (polar night) -> assume clear
    ratio = np.where(rso > 0.0, rs / np.maximum(rso, 1e-6), 0.5)
    ratio = np.clip(ratio, 0.25, 1.0)

    rns = (1.0 - albedo) * rs                                # eq. 38
    tk4 = (t + 273.16) ** 4
    rnl = (4.903e-9 * tk4 * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0.0)))
           * (1.35 * ratio - 0.35))                          # eq. 39
    rn = rns - rnl

    et0 = ((0.408 * delta * rn + gamma * 900.0 / (t + 273.0) * u2 * (es - ea))
           / (delta + gamma * (1.0 + 0.34 * u2)))            # eq. 6, G = 0
    return np.maximum(et0, 0.0)


# ---------------------------------------------------------------------------
# Clone-grid forcing built straight from ki_tools_common.load_forcing
# ---------------------------------------------------------------------------

def _clone_cell_centres(clone_meta):
    """(lat, lon) centre arrays of the clone, lat DESCENDING like every PCR map."""
    cs = float(clone_meta["cellsize"])
    rows, cols = int(clone_meta["rows"]), int(clone_meta["cols"])
    lats = clone_meta["yUL"] - cs / 2.0 - cs * np.arange(rows)
    lons = clone_meta["xUL"] + cs / 2.0 + cs * np.arange(cols)
    return lats, lons


def _sample_offsets(cellsize, native_res, subsample):
    """Offsets of the native forcing cells sampled inside one clone cell."""
    n = max(int(round(cellsize / native_res)), 1)
    idx = np.arange(0, n, max(int(subsample), 1))
    return (idx - (n - 1) / 2.0) * native_res


def _write_grid_nc(path, varname, data, lats, lons, dates, units, long_name):
    """Write a (time, lat, lon) forcing field in PCR-GLOBWB's expected layout."""
    if nc is None:
        raise ImportError("netCDF4 is required")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    epoch = datetime(1901, 1, 1)
    with nc.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("lat", len(lats))
        ds.createDimension("lon", len(lons))

        t = ds.createVariable("time", "f8", ("time",))
        t.units = "days since 1901-01-01"
        t.calendar = "standard"
        t[:] = [(d - epoch).days for d in dates]

        la = ds.createVariable("lat", "f8", ("lat",))
        la.units = "degrees_north"
        la.standard_name = "latitude"
        la[:] = lats

        lo = ds.createVariable("lon", "f8", ("lon",))
        lo.units = "degrees_east"
        lo.standard_name = "longitude"
        lo[:] = lons

        v = ds.createVariable(varname, "f4", ("time", "lat", "lon"),
                              fill_value=1e20, zlib=True, complevel=4)
        v[:] = data
        v.units = units
        v.long_name = long_name

        ds.description = f"PCR-GLOBWB 2 forcing: {varname}"
        ds.history = f"Built by convert_forcing_to_pcrglobwb on {datetime.now().isoformat()}"
    logger.info(f"Wrote {path}: {data.shape} {varname} [{units}]")


def build_from_ki_forcing(source, clone_meta, output_dir, start_year, end_year,
                          forcing_dir=None, subsample=2, cache_dir=None,
                          native_res=0.1, refet_method="penman"):
    """Build clone-grid precipitation / temperature / reference ET.

    Every clone cell is filled with the unweighted mean of the native forcing
    cells inside it (strided by `subsample`). Reference ET is then computed per
    clone cell from those cell-mean drivers.

    Args:
        source: forcing key understood by ki_tools_common (e.g. 'cmfd')
        clone_meta: dict loaded from {prefix}.clone.json
        output_dir: where precipitation.nc / temperature.nc / referencePotET.nc go
        start_year, end_year: inclusive
        forcing_dir: root of the native forcing archive
        subsample: stride over native cells inside each clone cell (2 -> every
            other cell in each direction)
        cache_dir: per-year .npy cache so an interrupted build resumes cheaply
        native_res: native forcing grid spacing in degrees
        refet_method: 'penman' (FAO-56 PM, requires radiation/wind/humidity/
            pressure) or 'none' (skip refET; the model must then use Hamon)

    Returns the dict of written paths.
    """
    from ki_tools_common.load_forcing import load_daily_forcing_points

    if refet_method not in ("penman", "none"):
        raise ValueError(f"refet_method must be 'penman' or 'none', got {refet_method}")

    lats, lons = _clone_cell_centres(clone_meta)
    rows, cols = len(lats), len(lons)
    offs = _sample_offsets(float(clone_meta["cellsize"]), native_res, subsample)
    nsub = len(offs) ** 2
    logger.info(f"Clone {rows}x{cols}; sampling {nsub} native cells per clone cell "
                f"({len(offs)} offsets/axis at {native_res} deg, subsample={subsample})")

    latlons = []
    for la in lats:
        for lo in lons:
            for dla in offs:
                for dlo in offs:
                    latlons.append((float(la + dla), float(lo + dlo)))
    logger.info(f"{len(latlons)} native sample points")

    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)

    def _cache(tag, year):
        return os.path.join(cache_dir, f"{tag}_{year}.npy") if cache_dir else None

    all_dates, P, T, E = [], [], [], []

    for year in range(start_year, end_year + 1):
        tags = ["d", "p", "t"] + (["e"] if refet_method != "none" else [])
        paths = {tag: _cache(tag, year) for tag in tags}
        if cache_dir and all(p and os.path.exists(p) for p in paths.values()):
            logger.info(f"{year}: cached")
            d = np.load(paths["d"], allow_pickle=True)
            all_dates.extend([datetime.strptime(str(x), "%Y-%m-%d") for x in d])
            P.append(np.load(paths["p"]))
            T.append(np.load(paths["t"]))
            if refet_method != "none":
                E.append(np.load(paths["e"]))
            continue

        logger.info(f"{year}: reading {source} at {len(latlons)} points")
        series = load_daily_forcing_points(source, latlons, year, year,
                                           forcing_dir=forcing_dir)
        dates = [d if isinstance(d, datetime) else datetime.strptime(str(d)[:10], "%Y-%m-%d")
                 for d in series[0]["dates"]]
        nday = len(dates)

        def _stack(key):
            # (npoints, nday) -> (rows, cols, nsub, nday) -> mean over nsub
            arr = np.array([s[key] for s in series], dtype=float)
            return np.nanmean(arr.reshape(rows, cols, nsub, nday), axis=2)

        p_mm = _stack("precip_mm")                     # mm/day
        t_c = _stack("temp_mean_c")                    # degC
        p_year = p_mm / 1000.0                         # dt_001: mm/day -> m/day
        t_year = t_c

        if refet_method == "none":
            e_year = None
        else:
            srad = _stack("srad_wm2")
            wind = _stack("wind_ms")
            shum = _stack("shum_kgkg")
            pres = _stack("pres_pa")
            doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
            e_mm = np.empty((rows, cols, nday), dtype=float)
            for i in range(rows):
                for j in range(cols):
                    e_mm[i, j] = fao56_penman_monteith(
                        doy, t_c[i, j], srad[i, j], wind[i, j],
                        shum[i, j], pres[i, j], float(lats[i]))
            e_year = e_mm / 1000.0                     # dt_003: mm/day -> m/day
            logger.info(f"{year}: ET0 basin mean {e_mm.mean(axis=(0, 1)).sum():.0f} mm/yr")

        if cache_dir:
            np.save(paths["d"], np.array([d.strftime("%Y-%m-%d") for d in dates]))
            np.save(paths["p"], p_year)
            np.save(paths["t"], t_year)
            if e_year is not None:
                np.save(paths["e"], e_year)

        all_dates.extend(dates)
        P.append(p_year)
        T.append(t_year)
        if e_year is not None:
            E.append(e_year)

    # (rows, cols, time) -> (time, rows, cols)
    precip = np.concatenate(P, axis=2).transpose(2, 0, 1)
    temp = np.concatenate(T, axis=2).transpose(2, 0, 1)

    os.makedirs(output_dir, exist_ok=True)
    written = {}
    written["precipitation"] = os.path.join(output_dir, "precipitation.nc")
    _write_grid_nc(written["precipitation"], "precipitation", precip, lats, lons,
                   all_dates, "m.day-1", "daily precipitation")

    written["temperature"] = os.path.join(output_dir, "temperature.nc")
    _write_grid_nc(written["temperature"], "temperature", temp, lats, lons,
                   all_dates, "degrees Celsius", "mean daily air temperature")

    if E:
        refet = np.concatenate(E, axis=2).transpose(2, 0, 1)
        written["referencePotET"] = os.path.join(output_dir, "referencePotET.nc")
        # PCR-GLOBWB's default refETPotVarName is 'evapotranspiration'
        _write_grid_nc(written["referencePotET"], "evapotranspiration", refet,
                       lats, lons, all_dates, "m.day-1",
                       "FAO-56 Penman-Monteith reference potential evapotranspiration")

    return written


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Convert meteorological forcing to PCR-GLOBWB 2 format"
    )
    parser.add_argument("--precip", required=True, help="Precipitation NetCDF file")
    parser.add_argument("--temp", required=True, help="Temperature NetCDF file")
    parser.add_argument("--refet", default=None, help="Reference ET NetCDF file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument(
        "--source", required=True,
        choices=["era5", "cmfd", "cru_era_interim", "w5e5", "custom"],
        help="Source data format"
    )
    parser.add_argument("--start-date", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="End date (YYYY-MM-DD)")

    args = parser.parse_args()

    # Validate → Process → Validate
    validate_inputs(args.precip, args.temp, args.refet, args.source)
    process(args.precip, args.temp, args.refet, args.output_dir,
            args.source, args.start_date, args.end_date)
    validate_outputs(args.output_dir, args.start_date, args.end_date)


if __name__ == "__main__":
    main()
