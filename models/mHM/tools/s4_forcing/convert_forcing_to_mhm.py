#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      convert_forcing_to_mhm
Stage:        s4_forcing
Description:  Convert CMFD or MSWX forcing data to mHM-compatible NetCDF format.

mHM expects meteorological forcing as NetCDF files with:
  - Dimensions: (time, lat, lon) -- using CF conventions
  - One directory per variable: pre/, tavg/, pet/ (or tmin/, tmax/ for Hargreaves)
  - One file per year per variable (e.g., pre_2005.nc)
  - Daily timestep
  - Time encoding: "days since YYYY-01-01"

UNIT CONVERSIONS (CRITICAL -- silent errors if wrong):
  CMFD:
    - Precipitation: mm/3hr -> mm/day (sum 8 timesteps)
    - Temperature: Kelvin -> degrees Celsius (subtract 273.15)
  MSWX:
    - Precipitation: mm/3hr -> mm/day (sum 8 timesteps)
    - Temperature: already in Celsius
  Both:
    - PET: if pre-computed, must be in mm/day

Inputs:
  - CONFIG_PATH: config.json from s0
  - DOMAIN_INFO_PATH: domain_info.json from s1
  - FORCING_SOURCE_DIR: path to CMFD or MSWX raw data
  - PET_METHOD: 0 (input PET), 1 (Hargreaves needs tmin/tmax)

Outputs:
  - NetCDF files in input/meteo/pre/, input/meteo/tavg/, etc.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius

try:
    import xarray as xr
    import rasterio
    from rasterio.transform import from_bounds
except ImportError as e:
    print(f"ERROR: Required: xarray, rasterio. {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CONFIG_PATH = ""
DOMAIN_INFO_PATH = ""
FORCING_SOURCE_DIR = ""
PET_METHOD = 0  # 0=input PET, 1=Hargreaves

# CMFD variable mapping
CMFD_VAR_MAP = {
    "pre": {"file_pattern": "prec_CMFD_V0106_B-01_01hr_010deg_{year}{month:02d}.nc",
            "var_name": "prec", "unit_conv": "sum_3hr_to_daily", "temp_offset": 0},
    "tavg": {"file_pattern": "temp_CMFD_V0106_B-01_01hr_010deg_{year}{month:02d}.nc",
             "var_name": "temp", "unit_conv": "K_to_C_daily_mean", "temp_offset": -273.15},
}

# MSWX variable mapping
MSWX_VAR_MAP = {
    "pre": {"file_pattern": "P3h_MSWX_{year}.nc",
            "var_name": "precipitation", "unit_conv": "sum_3hr_to_daily"},
    "tavg": {"file_pattern": "Temp_MSWX_{year}.nc",
             "var_name": "air_temperature", "unit_conv": "mean_3hr_to_daily"},
}

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Convert forcing to mHM format")
    parser.add_argument("--config", required=True)
    parser.add_argument("--domain_info", required=True)
    parser.add_argument("--forcing_dir", required=True)
    parser.add_argument("--pet_method", type=int, default=0)
    args = parser.parse_args()
    CONFIG_PATH = args.config
    DOMAIN_INFO_PATH = args.domain_info
    FORCING_SOURCE_DIR = args.forcing_dir
    PET_METHOD = args.pet_method

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def l1_grid(domain_info):
    """Cell-centre lat/lon of the L1 grid.

    Write the L2 (forcing) grid IDENTICAL to the L1 grid -- same xllcorner,
    yllcorner, cellsize and shape. This is what mHM's test_domain_2 does and it
    removes all L0->L2 cellFactor ambiguity.
    """
    h = domain_info["header_L1"]
    cs = h["cellsize"]
    lons = h["xllcorner"] + (np.arange(h["ncols"]) + 0.5) * cs
    lats = h["yllcorner"] + (np.arange(h["nrows"]) + 0.5) * cs
    return lats[::-1], lons, h          # lat DESCENDING (N->S), as mHM expects


def _open_cmfd(source_dir, prefix, years):
    """Open the CMFD files for one variable across `years` as a single DataArray."""
    files = []
    for y in years:
        hits = sorted(Path(source_dir).glob(f"**/{prefix}_*{y}*.nc"))
        files.extend(h for h in hits if h not in files)
    if not files:
        raise FileNotFoundError(f"No CMFD '{prefix}' files under {source_dir} for {years}")
    ds = xr.open_mfdataset(sorted(files), combine="by_coords", engine="netcdf4")
    name = [v for v in ds.data_vars][0]
    da = ds[name]
    # CMFD grids name their axes x/y (not lon/lat)
    ren = {}
    for d in da.dims:
        if d in ("y", "latitude"):
            ren[d] = "lat"
        elif d in ("x", "longitude"):
            ren[d] = "lon"
    return da.rename(ren) if ren else da


def sample_to_grid(da, lats, lons, cellsize=None):
    """Resample a (time, lat, lon) DataArray onto the L1 cell centres.

    When the source is FINER than L1 (e.g. the 0.1 deg national CMFD onto a 0.25 deg
    L1) take the area-mean of the source cells falling inside each L1 cell -- that is
    what a coarse-resolution product IS, and nearest-neighbour would instead pick one
    arbitrary sub-cell. When the source is at (or coarser than) the L1 resolution,
    fall back to nearest neighbour.
    """
    # crop first: the national grid is (nt, 400, 700) and does not fit in memory
    if cellsize:
        buf = 2 * cellsize
        lo_lat, hi_lat = float(np.min(lats)) - buf, float(np.max(lats)) + buf
        lo_lon, hi_lon = float(np.min(lons)) - buf, float(np.max(lons)) + buf
        lat_v = da.lat.values
        sl = slice(hi_lat, lo_lat) if lat_v[0] > lat_v[-1] else slice(lo_lat, hi_lat)
        da = da.sel(lat=sl, lon=slice(lo_lon, hi_lon))

    src_res = abs(float(da.lon.values[1] - da.lon.values[0]))
    if cellsize is None or src_res > 0.75 * cellsize:
        out = da.sel(lat=xr.DataArray(lats, dims="yc"),
                     lon=xr.DataArray(lons, dims="xc"), method="nearest")
        return out.transpose("time", "yc", "xc").values.astype(np.float32)

    vals = da.transpose("time", "lat", "lon").values.astype(np.float32)
    nt = vals.shape[0]
    ny, nx = len(lats), len(lons)
    # lats descend, so bin on -lat to keep indices increasing
    yi = np.floor((-da.lat.values - (-lats[0] - cellsize / 2)) / cellsize).astype(int)
    xi = np.floor((da.lon.values - (lons[0] - cellsize / 2)) / cellsize).astype(int)
    ok_y, ok_x = (yi >= 0) & (yi < ny), (xi >= 0) & (xi < nx)
    vals = vals[:, ok_y][:, :, ok_x]
    yi, xi = yi[ok_y], xi[ok_x]

    finite = np.isfinite(vals)
    v0 = np.where(finite, vals, 0.0)
    flat = yi[:, None] * nx + xi[None, :]
    flat = np.broadcast_to(flat, v0.shape[1:]).ravel()

    sums = np.zeros((nt, ny * nx), dtype=np.float64)
    cnts = np.zeros((nt, ny * nx), dtype=np.float64)
    np.add.at(sums.T, flat, v0.reshape(nt, -1).T)
    np.add.at(cnts.T, flat, finite.reshape(nt, -1).T.astype(np.float64))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(cnts > 0, sums / cnts, np.nan)
    logger.info(f"Area-averaged source {src_res:.3f} deg -> L1 {cellsize} deg")
    return out.reshape(nt, ny, nx).astype(np.float32)


def oudin_pet(tavg_c, lats, dates):
    """Oudin (2005) temperature-based PET (mm/day).

        PET = Re / (lambda * rho_w) * (T + 5) / 100     for T + 5 > 0, else 0

    Re = extraterrestrial radiation (MJ m-2 d-1); lambda*rho_w = 2.45 MJ mm-1 m-2,
    so Re/2.45 converts Re to its mm/day water-equivalent.

    TRAP (dt_s11). CMFD *daily* carries a single temperature field, so
    temp_max_c == temp_min_c == temp_mean_c and Hargreaves -- which scales with
    sqrt(Tmax - Tmin) -- is IDENTICALLY ZERO. Synthesising a fake diurnal range
    (tavg +/- 5 K) does not recover the missing information: it fabricates the very
    quantity the method integrates, and produced a basin-mean PET of 98 mm/day
    (~20x physical) that evaporated the whole water balance. For temperature-only
    daily forcing use Oudin and feed mHM the result with processCase(5) = 0.
    """
    doy = np.array([pd.Timestamp(d).dayofyear for d in dates], dtype=float)
    phi = np.radians(np.asarray(lats, dtype=float))              # (nlat,)
    dr = 1.0 + 0.033 * np.cos(2 * np.pi * doy / 365.0)           # (nt,)
    dec = 0.409 * np.sin(2 * np.pi * doy / 365.0 - 1.39)         # (nt,)

    x = -np.tan(phi)[None, :] * np.tan(dec)[:, None]
    ws = np.arccos(np.clip(x, -1.0, 1.0))                        # (nt, nlat)
    Gsc = 0.0820                                                 # MJ m-2 min-1
    Re = (24 * 60 / np.pi) * Gsc * dr[:, None] * (
        ws * np.sin(phi)[None, :] * np.sin(dec)[:, None]
        + np.cos(phi)[None, :] * np.cos(dec)[:, None] * np.sin(ws)
    )                                                            # (nt, nlat)

    pet = (Re[:, :, None] / 2.45) * (tavg_c + 5.0) / 100.0
    return np.where((tavg_c + 5.0) > 0, pet, 0.0).astype(np.float32)


def basin_mask_L1(shp_path, hL1):
    """Rasterise the basin polygon onto the L1 grid (row 0 = north, as lats descend)."""
    import geopandas as gpd
    from rasterio.features import geometry_mask
    cs = hL1["cellsize"]
    xll, yll = hL1["xllcorner"], hL1["yllcorner"]
    nc, nr = hL1["ncols"], hL1["nrows"]
    tr = from_bounds(xll, yll, xll + nc * cs, yll + nr * cs, nc, nr)
    gdf = gpd.read_file(shp_path)
    return geometry_mask(gdf.geometry, out_shape=(nr, nc), transform=tr,
                         invert=True, all_touched=True)


def clip_and_aggregate(ds, var_name, bounds, cellsize, agg_method="sum"):
    """Clip a dataset to domain bounds and aggregate sub-daily to daily."""
    minx, miny, maxx, maxy = bounds

    # Find lat/lon dimension names
    lat_name = None
    lon_name = None
    for dim in ds.dims:
        if dim.lower() in ('lat', 'latitude', 'y'):
            lat_name = dim
        elif dim.lower() in ('lon', 'longitude', 'x'):
            lon_name = dim

    if lat_name is None or lon_name is None:
        # Try coordinate names
        for coord in ds.coords:
            if coord.lower() in ('lat', 'latitude'):
                lat_name = coord
            elif coord.lower() in ('lon', 'longitude'):
                lon_name = coord

    if lat_name is None or lon_name is None:
        raise ValueError(f"Cannot find lat/lon dimensions. Dims: {list(ds.dims)}, Coords: {list(ds.coords)}")

    # Clip spatially with buffer
    buf = cellsize * 2
    lat_sel = (ds[lat_name] >= miny - buf) & (ds[lat_name] <= maxy + buf)
    lon_sel = (ds[lon_name] >= minx - buf) & (ds[lon_name] <= maxx + buf)
    ds_clip = ds.where(lat_sel & lon_sel, drop=True)

    if var_name in ds_clip:
        var = ds_clip[var_name]
    else:
        # Try first data variable
        var = ds_clip[list(ds_clip.data_vars)[0]]

    # Aggregate to daily
    if 'time' in var.dims and len(var.time) > 366:
        if agg_method == "sum":
            var_daily = var.resample(time="1D").sum(dim="time")
        elif agg_method == "mean":
            var_daily = var.resample(time="1D").mean(dim="time")
        else:
            var_daily = var
    else:
        var_daily = var

    return var_daily


def write_mhm_nc(data, lats, lons, times, var_name, output_path, units):
    """One concatenated file per variable, named <varname>.nc, dims (time, yc, xc).

    mHM opens <dir>/<varname>.nc -- ONE file spanning the whole period, not one file
    per year -- and the NetCDF variable name equals the directory name.
    _FillValue = -9999.0 (never NaN: NaN raises Fortran IEEE_INVALID_FLAG when mHM
    compares against nodata); time is int32 (int64 overruns mHM's 4-byte slots).
    """
    ds = xr.Dataset(
        {var_name: (["time", "yc", "xc"], data.astype(np.float32))},
        coords={"time": times,
                "lat": ("yc", np.asarray(lats, dtype=np.float64)),
                "lon": ("xc", np.asarray(lons, dtype=np.float64))},
    )
    ds[var_name].attrs["units"] = units
    ds[var_name].attrs["long_name"] = var_name
    ds[var_name].attrs["coordinates"] = "lat lon"
    encoding = {
        var_name: {"_FillValue": -9999.0, "dtype": "float32"},
        "time": {"units": f"days since {pd.Timestamp(times[0]).year}-01-01",
                 "calendar": "standard", "dtype": "int32"},
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(output_path, encoding=encoding)
    logger.info(f"Written: {output_path} ({len(times)} timesteps)")


def write_header_txt(path, header_L1):
    with open(path, "w") as f:
        f.write(f"ncols\t{header_L1['ncols']}\n")
        f.write(f"nrows\t{header_L1['nrows']}\n")
        f.write(f"xllcorner\t{header_L1['xllcorner']}\n")
        f.write(f"yllcorner\t{header_L1['yllcorner']}\n")
        f.write(f"cellsize\t{header_L1['cellsize']}\n")
        f.write("NODATA_value\t-9999\n")


def write_mhm_forcing_nc(data, lats, lons, times, var_name, output_path, units="mm/day"):
    """Write mHM-compatible forcing NetCDF file.

    CRITICAL FORMAT REQUIREMENTS (from mHM Fortran source analysis):
      - lat must be DESCENDING (North → South) — mHM assumes this order
      - _FillValue must be -9999.0, NOT NaN — NaN causes Fortran IEEE_INVALID_FLAG
        when mHM compares data to nodata_value, leading to false "nodata in domain"
      - time must be int32 — mHM reads time as 32-bit integer; int64 causes heap
        corruption and SIGSEGV when get_time_vector_and_select reads 8-byte values
        into 4-byte slots
      - mHM reads combined file as {varname}.nc (e.g., pre.nc, tavg.nc)
    """
    # Sort lats descending (north to south) as mHM expects
    if len(lats) > 1 and lats[0] < lats[-1]:
        lats = lats[::-1]
        data = data[:, ::-1, :]

    ds = xr.Dataset(
        {var_name: (["time", "lat", "lon"], data.astype(np.float32))},
        coords={
            "time": times,
            "lat": lats.astype(np.float64),
            "lon": lons.astype(np.float64),
        },
    )
    ds[var_name].attrs["units"] = units
    ds[var_name].attrs["long_name"] = var_name

    # Encoding: _FillValue=-9999 (not NaN), time as int32 (not int64)
    encoding = {
        var_name: {"_FillValue": -9999.0, "dtype": "float32"},
        "time": {
            "units": f"days since {pd.Timestamp(times[0]).year}-01-01",
            "calendar": "standard",
            "dtype": "int32",
        },
    }

    ds.to_netcdf(output_path, encoding=encoding)
    logger.info(f"Written: {output_path} ({len(times)} timesteps, _FillValue=-9999, time=int32)")


def validate_inputs():
    errors = []
    if not CONFIG_PATH or not Path(CONFIG_PATH).exists():
        errors.append(f"Config not found: {CONFIG_PATH}")
    if not DOMAIN_INFO_PATH or not Path(DOMAIN_INFO_PATH).exists():
        errors.append(f"Domain info not found: {DOMAIN_INFO_PATH}")
    if not FORCING_SOURCE_DIR or not Path(FORCING_SOURCE_DIR).exists():
        errors.append(f"Forcing source dir not found: {FORCING_SOURCE_DIR}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    config = json.load(open(CONFIG_PATH))
    domain_info = json.load(open(DOMAIN_INFO_PATH))

    start_year = config["start_year"]
    end_year = config["end_year"]
    forcing_dataset = config["forcing_dataset"].upper()
    output_base = Path(config["output_dir"]) / "input" / "meteo"
    years = list(range(start_year, end_year + 1))

    lats, lons, hL1 = l1_grid(domain_info)
    logger.info(f"L2 forcing grid == L1 grid: {hL1['ncols']}x{hL1['nrows']} @ {hL1['cellsize']} deg")

    if forcing_dataset != "CMFD":
        logger.error(f"This tool currently converts CMFD only (got {forcing_dataset}).")
        sys.exit(1)

    src = Path(FORCING_SOURCE_DIR)
    daily_product = "01dy" in src.name or "01dy" in str(src)

    # ---- precipitation ------------------------------------------------------
    pre_da = _open_cmfd(src, "prec", years)
    pre = sample_to_grid(pre_da, lats, lons, hL1["cellsize"])
    times = pd.to_datetime(pre_da.time.values).normalize()

    # TRAP (dt_s10). CMFD stores precipitation as kg m-2 s-1 (= mm/s). The
    # Data_forcing_01dy_* (DAILY) product is a daily MEAN RATE, not a 3-hourly
    # accumulation: it must be multiplied by 86400 s/day. Applying the 3-hourly
    # factor 10800 delivers exactly 1/8 of the true rainfall -- a silent dry bias
    # that drives PBIAS to about -95% and that no calibration can undo.
    factor = 86400.0 if daily_product else 10800.0
    pre = pre * factor
    logger.info(f"Precip: kg m-2 s-1 -> mm/day (x{factor:.0f}, "
                f"{'daily-mean-rate' if daily_product else '3-hourly'} product)")

    # ---- temperature --------------------------------------------------------
    tavg_da = _open_cmfd(src, "temp", years)
    tavg = sample_to_grid(tavg_da, lats, lons, hL1["cellsize"]) - 273.15
    logger.info("Temperature: K -> degC")

    # ---- gates (a structural unit error looks exactly like a calibration problem)
    #
    # The regional CMFD cut-outs are masked to their own basin polygon, so L1 cells in
    # the padded corners can be all-NaN. That is harmless (they are outside the
    # catchment and mHM never activates them), but a basin cell with no forcing is a
    # silent hole in the water balance. Gate on the basin cells only.
    basin = basin_mask_L1(config["shp_path"], hL1)
    have = np.isfinite(pre).any(axis=0)
    missing = basin & ~have
    if missing.any():
        rc = np.argwhere(missing)[:10].tolist()
        logger.error(f"{int(missing.sum())} L1 cells inside the basin have NO forcing "
                     f"(the source cut-out does not cover them). First cells: {rc}")
        sys.exit(2)
    logger.info(f"Basin covers {int(basin.sum())} of {basin.size} L1 cells; "
                f"all have forcing")

    p_annual = float(np.nanmean(pre[:, basin])) * 365.25
    logger.info(f"Basin-mean precipitation: {p_annual:.0f} mm/yr")
    if not (200.0 <= p_annual <= 4000.0):
        logger.error(f"Basin-mean precipitation {p_annual:.0f} mm/yr is outside "
                     f"[200, 4000] -- check the CMFD unit factor (dt_s10).")
        sys.exit(2)

    variables = ["pre", "tavg"]
    write_mhm_nc(pre, lats, lons, times, "pre", output_base / "pre" / "pre.nc", "mm d-1")
    write_mhm_nc(tavg, lats, lons, times, "tavg", output_base / "tavg" / "tavg.nc", "degC")

    # ---- PET ----------------------------------------------------------------
    if PET_METHOD == 0:
        pet = oudin_pet(tavg, lats, times)
        pet_annual = float(np.nanmean(pet[:, basin])) * 365.25
        pet_max = float(np.nanmax(pet[:, basin]))
        logger.info(f"Oudin PET: {pet_annual:.0f} mm/yr, max {pet_max:.1f} mm/day")
        if pet_max > 8.0:
            logger.error(f"PET max {pet_max:.1f} mm/day exceeds the physical "
                         f"~8 mm/day ceiling (dt_s11).")
            sys.exit(2)
        write_mhm_nc(pet, lats, lons, times, "pet", output_base / "pet" / "pet.nc", "mm d-1")
        variables.append("pet")

    elif PET_METHOD == 1:
        # Hargreaves-Samani needs a REAL diurnal range.
        tmin = sample_to_grid(_open_cmfd(src, "temp", years), lats, lons, hL1["cellsize"]) - 273.15
        drange = float(np.nanmean(np.abs(tavg - tmin)))
        if drange < 0.1:
            logger.error(
                f"Mean diurnal range {drange:.4f} K < 0.1 K: this forcing carries a "
                f"single temperature field, so Hargreaves (which scales with "
                f"sqrt(Tmax-Tmin)) is IDENTICALLY ZERO. Do not synthesise a fake "
                f"range. Use --pet_method 0 (Oudin, processCase(5)=0). See dt_s11.")
            sys.exit(2)
        logger.error("Hargreaves path requires genuine tmin/tmax inputs.")
        sys.exit(2)
    else:
        logger.error(f"Unsupported --pet_method {PET_METHOD}")
        sys.exit(2)

    for var in variables:
        write_header_txt(output_base / var / "header.txt", hL1)

    result = {
        "status": "success",
        "forcing_dir": str(output_base),
        "variables": variables,
        "period": f"{start_year}-{end_year}",
        "n_timesteps": int(len(times)),
        "precip_mm_per_year": round(p_annual, 1),
        "pet_mm_per_year": round(pet_annual, 1) if PET_METHOD == 0 else None,
        "precip_factor": factor,
        "L2_grid": {"ncols": hL1["ncols"], "nrows": hL1["nrows"],
                    "xll": hL1["xllcorner"], "yll": hL1["yllcorner"],
                    "cs": hL1["cellsize"]},
    }
    print(json.dumps(result, indent=2))
    return str(output_base)


def validate_outputs(output_path):
    meteo_dir = Path(output_path)
    # Check at least pre directory exists with files
    pre_dir = meteo_dir / "pre"
    if not pre_dir.exists() or not list(pre_dir.glob("*.nc")):
        logger.error(f"No precipitation files in {pre_dir}")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
