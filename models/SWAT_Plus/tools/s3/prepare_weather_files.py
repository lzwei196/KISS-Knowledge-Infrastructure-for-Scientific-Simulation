#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      prepare_weather_files
Stage:        s3_weather_preparation
Description:  Convert meteorological data (CMFD/MSWX/CSV) to SWAT+ weather file format.
              Generates: .pcp, .tmp, .slr, .hmd, .wnd files + .cli index files.

SWAT+ weather file format (3-line header):
  Line 1: Title (free text)
  Line 2: Column headers (nbyr tstep lat lon elev)
  Line 3: Station metadata values
  Line 4+: Data rows (year jday value(s))

Critical unit conversions:
  Temperature: K -> C (subtract 273.15)
  Precipitation: mm/3hr -> mm/day (sum 8 timesteps)
  Solar radiation: W/m2 -> MJ/m2/day (multiply by 0.0864)
  Specific humidity -> relative humidity fraction (0-1)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np

FORCING_SOURCE = "csv"  # cmfd, mswx, csv, nasa_power
FORCING_DIR = ""
STATION_COORDS = []  # [[lat, lon], ...]
START_DATE = ""  # YYYY-MM-DD
END_DATE = ""
OUTPUT_DIR = ""

if len(sys.argv) >= 6:
    FORCING_SOURCE = sys.argv[1]
    FORCING_DIR = sys.argv[2]
    STATION_COORDS = json.loads(sys.argv[3])
    START_DATE = sys.argv[4]
    END_DATE = sys.argv[5]
if len(sys.argv) >= 7:
    OUTPUT_DIR = sys.argv[6]
# SWAT+ binds spatial objects to weather BY NAME: hru.con / rout_unit.con carry a
# `wst` column written by s2/generate_hru_from_global.py (staNN). If S3 invents its
# own p%06d names, weather-sta.cli never matches and the objects get no weather.
# 7th arg lets the caller pass the names S2 already declared (dt_040).
STATION_NAMES = []
if len(sys.argv) >= 8:
    STATION_NAMES = json.loads(sys.argv[7])

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if FORCING_SOURCE not in ["cmfd", "mswx", "csv", "nasa_power"]:
        errors.append(f"Invalid forcing source: {FORCING_SOURCE}")
    if not FORCING_DIR or not Path(FORCING_DIR).exists():
        errors.append(f"Forcing directory not found: {FORCING_DIR}")
    if not STATION_COORDS:
        errors.append("No station coordinates provided")
    if not START_DATE or not END_DATE:
        errors.append("Start and end dates required")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def write_weather_file(filepath, title, var_name, nbyr, lat, lon, elev, data):
    """Write a single SWAT+ weather file with 3-line header."""
    with open(filepath, 'w') as f:
        f.write(f"{title}\n")
        if var_name == "tmp":
            f.write(f"  nbyr       tstep      lat         lon         elev\n")
        else:
            f.write(f"  nbyr       tstep      lat         lon         elev\n")
        f.write(f"  {nbyr:<10d} {0:<10d} {lat:<12.5f} {lon:<12.5f} {elev:<12.1f}\n")
        for row in data:
            if var_name == "tmp":
                f.write(f"  {row['year']:<10d} {row['jday']:<10d} {row['tmax']:<12.3f} {row['tmin']:<12.3f}\n")
            else:
                f.write(f"  {row['year']:<10d} {row['jday']:<10d} {row['value']:<12.5f}\n")


def write_cli_file(filepath, var_name, station_files):
    """Write a .cli index file listing station data files."""
    with open(filepath, 'w') as f:
        f.write(f"{var_name} station files\n")
        f.write("filename\n")
        for sf in station_files:
            f.write(f"{sf}\n")


def process():
    """Extract and convert weather data to SWAT+ format."""
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    start = datetime.strptime(START_DATE, "%Y-%m-%d")
    end = datetime.strptime(END_DATE, "%Y-%m-%d")
    nbyr = end.year - start.year + 1

    pcp_files = []
    tmp_files = []
    slr_files = []
    hmd_files = []
    wnd_files = []

    # ROOT-CAUSE FIX (2026-06-05, Xixian run): the previous CMFD/MSWX path was a
    # non-functional stub — it opened NetCDFs but then appended HARDCODED constants
    # (precip=0.0, tmax=25, tmin=15, slr=15, hmd=0.65, wnd=2.5) for every day, so
    # every produced .pcp/.tmp was physically meaningless (Xixian came out at
    # ~130 mm/yr). The KI's own canonical loader, ki_tools_common.load_forcing,
    # already reads CMFD/MSWX/NASA-POWER correctly (3-hourly -> daily aggregation,
    # K->C, kg/m2/s->mm/day). Delegate to it instead of re-implementing badly.
    from ki_tools_common.load_forcing import load_daily_forcing_points
    # ki_tools_common.terrain exports get_terrain(), NOT point_elevation. The old
    # `from ... import point_elevation` raised ImportError, the bare except swallowed
    # it, and EVERY station in EVERY basin was written with elev=0.0 — 1000 m
    # mountain stations placed at sea level, which biases PET and snowmelt.
    from ki_tools_common.terrain import get_terrain

    def _es_pa(tc):
        # Saturation vapour pressure (Pa), Alduchov-Eskridge over water
        return 610.94 * np.exp(17.625 * tc / (tc + 243.04))

    # One pass over the CMFD monthly NetCDFs for ALL stations (see
    # load_daily_forcing_points docstring): a per-station loop re-inflates the
    # whole lat/lon slab and costs ~214 s per station-year.
    fdir_arg = FORCING_DIR if (FORCING_DIR and Path(FORCING_DIR).exists()) else None
    forcings = load_daily_forcing_points(FORCING_SOURCE,
                                         [(lat, lon) for lat, lon in STATION_COORDS],
                                         start.year, end.year, forcing_dir=fdir_arg)

    for idx, (lat, lon) in enumerate(STATION_COORDS):
        station_name = (STATION_NAMES[idx] if idx < len(STATION_NAMES)
                        else f"p{idx+1:06d}")
        try:
            elev = float(get_terrain(lat, lon)["elevation"])
        except Exception as e:
            logger.warning(f"get_terrain failed at ({lat},{lon}): {e}")
            elev = 0.0
        if elev == 0.0:
            logger.warning(f"station {station_name} ({lat:.3f},{lon:.3f}) has elev=0.0 m "
                           f"— check the terrain lookup before trusting PET/snowmelt")

        fc = forcings[idx]
        fdates = fc["dates"]
        precip = np.asarray(fc["precip_mm"], dtype=float)
        tmax = np.asarray(fc["temp_max_c"], dtype=float)
        tmin = np.asarray(fc["temp_min_c"], dtype=float)
        srad = np.asarray(fc.get("srad_wm2", [np.nan] * len(fdates)), dtype=float)
        wind = np.asarray(fc.get("wind_ms", [np.nan] * len(fdates)), dtype=float)
        shum = np.asarray(fc.get("shum_kgkg", [np.nan] * len(fdates)), dtype=float)
        pres = np.asarray(fc.get("pres_pa", [np.nan] * len(fdates)), dtype=float)

        # Derived: solar W/m2 -> MJ/m2/day; specific humidity -> RH fraction
        slr_mj = srad * 0.0864
        tmean = (tmax + tmin) / 2.0
        with np.errstate(invalid="ignore", divide="ignore"):
            e_act = shum * pres / (0.622 + 0.378 * shum)
            rh = np.clip(e_act / _es_pa(tmean), 0.05, 1.0)

        def _clean(v, fill):
            return fill if (v is None or not np.isfinite(v)) else float(v)

        pcp_data, tmp_data, slr_data, hmd_data, wnd_data = [], [], [], [], []
        for i, d in enumerate(fdates):
            yr = d.year
            jday = d.timetuple().tm_yday
            pcp_data.append({"year": yr, "jday": jday, "value": max(0.0, _clean(precip[i], 0.0))})
            tmp_data.append({"year": yr, "jday": jday,
                             "tmax": _clean(tmax[i], 25.0), "tmin": _clean(tmin[i], 15.0)})
            slr_data.append({"year": yr, "jday": jday, "value": _clean(slr_mj[i], 15.0)})
            hmd_data.append({"year": yr, "jday": jday, "value": _clean(rh[i], 0.65)})
            wnd_data.append({"year": yr, "jday": jday, "value": _clean(wind[i], 2.5)})

        logger.info(f"Loaded {len(pcp_data)} days for station {station_name} "
                    f"({lat:.3f},{lon:.3f}) from {FORCING_SOURCE}: "
                    f"mean precip {np.nanmean(precip)*365:.0f} mm/yr, "
                    f"Tmax {np.nanmean(tmax):.1f} Tmin {np.nanmean(tmin):.1f} C")

        # Write individual station files
        pcp_name = f"{station_name}.pcp"
        write_weather_file(output_dir / pcp_name, f"Precipitation data for station {station_name}",
                          "pcp", nbyr, lat, lon, elev, pcp_data)
        pcp_files.append(pcp_name)

        tmp_name = f"{station_name}.tmp"
        write_weather_file(output_dir / tmp_name, f"Temperature data for station {station_name}",
                          "tmp", nbyr, lat, lon, elev, tmp_data)
        tmp_files.append(tmp_name)

        slr_name = f"{station_name}.slr"
        write_weather_file(output_dir / slr_name, f"Solar radiation data for station {station_name}",
                          "slr", nbyr, lat, lon, elev, slr_data)
        slr_files.append(slr_name)

        hmd_name = f"{station_name}.hmd"
        write_weather_file(output_dir / hmd_name, f"Relative humidity data for station {station_name}",
                          "hmd", nbyr, lat, lon, elev, hmd_data)
        hmd_files.append(hmd_name)

        wnd_name = f"{station_name}.wnd"
        write_weather_file(output_dir / wnd_name, f"Wind speed data for station {station_name}",
                          "wnd", nbyr, lat, lon, elev, wnd_data)
        wnd_files.append(wnd_name)

        logger.info(f"Created weather files for station {station_name} ({lat:.3f}, {lon:.3f})")

    # Write .cli index files
    write_cli_file(output_dir / "pcp.cli", "Precipitation", pcp_files)
    write_cli_file(output_dir / "tmp.cli", "Temperature", tmp_files)
    write_cli_file(output_dir / "slr.cli", "Solar radiation", slr_files)
    write_cli_file(output_dir / "hmd.cli", "Relative humidity", hmd_files)
    write_cli_file(output_dir / "wnd.cli", "Wind speed", wnd_files)

    return {
        "status": "success",
        "n_stations": len(STATION_COORDS),
        "n_days": (end - start).days + 1,
        "period": f"{START_DATE} to {END_DATE}",
        "files_created": {
            "pcp": pcp_files,
            "tmp": tmp_files,
            "slr": slr_files,
            "hmd": hmd_files,
            "wnd": wnd_files,
            "cli": ["pcp.cli", "tmp.cli", "slr.cli", "hmd.cli", "wnd.cli"]
        }
    }


def validate_outputs(result):
    errors = []
    output_dir = Path(OUTPUT_DIR)
    for cli in ["pcp.cli", "tmp.cli", "slr.cli", "hmd.cli", "wnd.cli"]:
        if not (output_dir / cli).exists():
            errors.append(f"CLI file not created: {cli}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
