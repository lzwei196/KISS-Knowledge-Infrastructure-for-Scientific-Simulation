#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      build_obs
Stage:        s2_observation_data
Description:  Build the CRHM .obs weather file straight from a forcing source.

Two halves, kept apart on purpose:

  1. source -> STANDARD SERIES   (shared, ki_tools_common.load_forcing)
     One dict for every source:
         dates             numpy datetime64, one per step
         timestep_seconds  step length (3600 NASA POWER, 10800 CMFD / MSWX)
         temp_c            air temperature            (deg C)
         precip_mm         precipitation IN THE STEP  (mm, not a rate)
         srad_wm2          incoming short-wave        (W/m^2)
         lrad_wm2          incoming long-wave         (W/m^2)
         wind_ms           wind speed                 (m/s)
         shum_kgkg         specific humidity          (kg/kg)
         pres_pa           air pressure               (Pa)

  2. STANDARD SERIES -> CRHM .obs   (this KI, standard_to_obs() below)
         t (C) | p (mm per step) | rh (%) | u (m/s) | Qsi (W/m^2) | Qli (W/m^2)

What half 2 must get right (each one is a silent error if wrong):
  - humidity: CRHM wants RELATIVE humidity in percent; the sources give
    specific humidity (kg/kg). Passing it through makes the air bone-dry.
  - `p` is INTERVAL precipitation in mm (ClassObs.cpp:85). CRHM has no
    air-pressure observation; a `p (kPa)` column is read as rain.
  - a `####` line must separate the declarations from the data rows (dt_v001).
  - exactly ONE description line before the declarations (dt_020).

No value is made up. A missing or non-finite value in any series stops the
tool with a count per variable; nothing is filled with a constant.

Where the forcing is read (give exactly one):
  --lat --lon     ONE point (the grid cell nearest to it). Right for a plot, a
                  station, a small basin inside one or two cells.
  --basin_shp     a basin polygon: the area-weighted MEAN over every source grid
                  cell whose centre lies inside it. Right for a basin run. One
                  point for a large basin is a sample of one (Nuxia, 205,000
                  km2: centre cell 550 mm in 1970, mean of its 1,944 cells 660 mm).
                  cmfd only, for now.
CRHM takes ONE weather series and spreads it over the HRUs by elevation
(obs_elev, lapse_rate). So the elevation the series stands for must go to
derive_parameters.py --forcing_elev_m: the meta file records it as
"forcing_elev_m" (cmfd: from the store's own elevation field).

A NEW DATASET (one the shared loader does not read) -- --source table
  Half 2 does not care where the series came from. To use a dataset that has
  no reader yet, do half 1 for it yourself (its data KI says what the file
  holds and in which units) and hand the result over as a STANDARD TABLE:
  a CSV with exactly these columns, in any order:

      time        UTC, ISO form 2003-01-01T00:00:00, evenly spaced, the first
                  step at Jan 1 00:00 of --start_year, the last one step before
                  Jan 1 of the year after --end_year
      temp_c      air temperature, deg C
      precip_mm   precipitation IN THE STEP, mm (not a rate, not a day total)
      srad_wm2    incoming short-wave, W/m^2
      lrad_wm2    incoming long-wave, W/m^2
      wind_ms     wind speed, m/s
      shum_kgkg   SPECIFIC humidity, kg/kg
      pres_pa     air pressure, Pa

  then:  build_obs.py --source table --table_path my.csv --table_name <dataset>
                      --start_year .. --end_year .. --output_path basin.obs
                      [--forcing_elev_m <elevation the series stands for>]

  The table gets the SAME checks as every other source (no missing value, value
  ranges that catch a wrong unit, even time steps, full period). A dataset that
  has relative humidity or dew point instead of specific humidity is converted
  in half 1, with pressure:
      e  = RH/100 * es(T)          (or e = es(Tdew));   es in the same unit as p
      q  = 0.622 * e / (p - 0.378 * e)
  A variable the dataset does not have at all (often long-wave) is NOT invented
  here: get it from a source that has it, and say so in --table_name.
  What the checks CANNOT see, and the maker of the table must get right: the
  time zone (UTC), precipitation and radiation given per step (not a rate at a
  non-hourly step, not accumulated MJ/m2), and the height the wind was measured
  at (no height adjustment is made here).
  To see a correct table, write one from a known source:
      build_obs.py --source cmfd --lat .. --lon .. ... --save_table example.csv

Inputs:
  --source        nasa_power | cmfd | mswx | table    (required, no default)
  --lat --lon | --basin_shp                           (see above; not for table)
  --forcing_dir   root folder of the cmfd / mswx store (not used by nasa_power)
  --start_year --end_year
  --precip_scale  bias correction (default 1.0); never a unit fix (dt_v013)
  --output_path   the .obs file; a <name>.meta.json is written next to it

Exit codes:
  0 -- success
  1 -- input validation failed
  2 -- processing error
  3 -- output validation failed
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path

# dt_v010: importing netcdf_safe IS the HDF5 load-order guard. It must stay
# above every import that can reach xarray / h5py (ki_tools_common below).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import netcdf_safe                           # noqa: E402  -- import == guard

from ki_tools_common.humidity import saturation_vapor_pressure

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DIRECT_SOURCES = ("nasa_power", "cmfd", "mswx")   # read by the shared loader
TABLE_SOURCE = "table"                             # a standard table made by the caller

# The CMFD store's own surface elevation, on the forcing grid (0.1 deg).
CMFD_ELEV_NC = "KISSPATH_DATA/elev/elev_CMFD_V0200_B-00_fx_010deg.nc"

# The standard series half 2 needs, and the range a real value can lie in.
# Outside the range is a unit error upstream, not weather.
STANDARD_SERIES = {
    "temp_c":    (-90.0, 60.0),
    "precip_mm": (0.0, 500.0),       # per step
    "srad_wm2":  (0.0, 1500.0),
    "lrad_wm2":  (0.0, 700.0),
    "wind_ms":   (0.0, 100.0),
    "shum_kgkg": (0.0, 0.05),
    "pres_pa":   (30000.0, 110000.0),
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a CRHM .obs file straight from a forcing source")
    parser.add_argument("--source", type=str, required=True,
                        choices=list(DIRECT_SOURCES) + [TABLE_SOURCE],
                        help="Forcing source. nasa_power / cmfd / mswx are read through "
                             "ki_tools_common.load_forcing. 'table' takes a STANDARD TABLE you "
                             "made from a dataset that has no reader yet (see the top of this "
                             "file). There is no default: name the source.")
    parser.add_argument("--table_path", type=str, default=None,
                        help="[table] CSV with columns time, temp_c, precip_mm, srad_wm2, "
                             "lrad_wm2, wind_ms, shum_kgkg, pres_pa")
    parser.add_argument("--table_name", type=str, default=None,
                        help="[table] what the table was made from (dataset, place); goes into "
                             "the .obs description line and the meta file. Required.")
    parser.add_argument("--forcing_elev_m", type=float, default=None,
                        help="[table] elevation (m) the series stands for, if known; recorded "
                             "in the meta file for derive_parameters.py")
    parser.add_argument("--save_table", type=str, default=None,
                        help="Also write the standard series as a STANDARD TABLE CSV (an "
                             "example of the form --source table reads)")
    parser.add_argument("--lat", type=float, default=None,
                        help="Latitude of the forcing point (with --lon; or use --basin_shp)")
    parser.add_argument("--lon", type=float, default=None, help="Longitude of the forcing point")
    parser.add_argument("--basin_shp", type=str, default=None,
                        help="Basin polygon file (shapefile / GeoJSON). The forcing is the "
                             "area-weighted mean over every source grid cell whose centre is "
                             "inside it. cmfd only. Use instead of --lat/--lon for a basin run.")
    parser.add_argument("--cmfd_elev_nc", type=str, default=CMFD_ELEV_NC,
                        help="CMFD elevation field on the forcing grid (gives the cells for "
                             "--basin_shp and the forcing elevation for the meta file)")
    parser.add_argument("--forcing_dir", type=str, default=None,
                        help="Root folder of the cmfd / mswx store (not used by nasa_power)")
    parser.add_argument("--precip_scale", type=float, default=1.0,
                        help="Multiplicative precipitation BIAS correction (e.g. 1.7 for NASA "
                             "POWER undercatch in the Rockies). Default 1.0. Not a unit fix: "
                             "the loader already returns mm per step (dt_v013). 10 or more is "
                             "refused.")
    parser.add_argument("--output_path", type=str, required=True, help="Output .obs file path")
    parser.add_argument("--start_year", type=int, required=True, help="Start year")
    parser.add_argument("--end_year", type=int, required=True, help="End year")
    return parser.parse_args()


def specific_to_relative_humidity(q_kgkg, t_celsius, p_kpa):
    """Specific humidity (kg/kg) -> relative humidity (%), clamped to [0, 100].

    e = q * p / (0.622 + 0.378 * q);  RH = e / es(T) * 100, with es from
    ki_tools_common.humidity (Tetens). Skipping this conversion is the #1
    silent CRHM error: 0.001-0.01 read as percent makes the air bone-dry,
    sublimation goes to zero and SWE accumulates for ever.
    """
    es = saturation_vapor_pressure(t_celsius) / 10.0  # hPa -> kPa
    e = q_kgkg * p_kpa / (0.622 + 0.378 * q_kgkg)
    return max(0.0, min(100.0, (e / es) * 100.0))


def check_standard_series(d):
    """Refuse a standard series that is incomplete, gappy or in the wrong unit.

    Returns the list of problems (empty = usable). Nothing is repaired here.
    """
    import numpy as np
    problems = []
    if "dates" not in d or len(d["dates"]) == 0:
        return ["no time steps were returned"]
    n = len(d["dates"])
    for name, (lo, hi) in STANDARD_SERIES.items():
        if name not in d:
            problems.append(f"{name}: series missing")
            continue
        a = np.asarray(d[name], dtype=float)
        if a.shape != (n,):
            problems.append(f"{name}: {a.shape} values for {n} time steps")
            continue
        bad = int((~np.isfinite(a)).sum())
        if bad:
            problems.append(f"{name}: {bad} of {n} values missing or not finite")
            continue
        if a.min() < lo or a.max() > hi:
            problems.append(f"{name}: range {a.min():g} to {a.max():g} is outside "
                            f"{lo:g} to {hi:g} (wrong unit upstream?)")
    dates = np.asarray(d["dates"]).astype("datetime64[s]")
    steps = np.diff(dates).astype("timedelta64[s]").astype(int)
    if len(steps):
        ts = int(d.get("timestep_seconds", 0) or 0)
        if ts <= 0:
            problems.append("timestep_seconds missing")
        elif not (steps == ts).all():
            off = int((steps != ts).sum())
            problems.append(f"time axis: {off} of {len(steps)} steps are not {ts} s apart "
                            f"(first at {dates[int(np.argmax(steps != ts))]})")
    return problems


def standard_to_obs(d, description, output_path, precip_scale=1.0):
    """Half 2: write a STANDARD SERIES dict as a CRHM .obs file.

    `description` becomes the single description line. Returns a summary dict.
    Raises ValueError when the series is not usable (see check_standard_series).
    """
    import numpy as np

    # A scale of ~24 is the hand-made repair for the NASA POWER hourly unit
    # change (dt_v013). The loader reads the unit from the response, so the
    # same 24 would give 24 times too MUCH precipitation.
    if not (0.0 < float(precip_scale) < 10.0):
        raise ValueError(
            f"--precip_scale {precip_scale} is not a bias correction (allowed: >0 and "
            f"<10). If this was meant to undo the NASA POWER hourly /24 problem, drop "
            f"it: the loader handles the unit itself (triplet dt_v013).")
    if "\n" in description or "#" in description:
        raise ValueError("the .obs description must be one line without '#'")

    problems = check_standard_series(d)
    if problems:
        raise ValueError("forcing series not usable, nothing written:\n  - "
                         + "\n  - ".join(problems))

    dates = np.asarray(d["dates"]).astype("datetime64[s]").tolist()
    temp = np.asarray(d["temp_c"], dtype=float)
    precip = np.asarray(d["precip_mm"], dtype=float) * precip_scale  # mm per step
    srad = np.asarray(d["srad_wm2"], dtype=float)
    lrad = np.asarray(d["lrad_wm2"], dtype=float)
    wind = np.asarray(d["wind_ms"], dtype=float)
    shum = np.asarray(d["shum_kgkg"], dtype=float)
    pres_kpa = np.asarray(d["pres_pa"], dtype=float) / 1000.0
    # a store can hold negative zero; "+ 0.0" turns it into 0.0 so the file
    # never carries "-0.00"
    temp, precip, srad, lrad, wind = (x + 0.0 for x in (temp, precip, srad, lrad, wind))

    n = len(dates)
    rh = np.array([specific_to_relative_humidity(shum[i], temp[i], pres_kpa[i])
                   for i in range(n)])

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        f.write(description + "\n")     # exactly ONE description line (dt_020)
        f.write("t 1 (C)\n")
        f.write("p 1 (mm)\n")           # interval precip (ClassObs.cpp:85)
        f.write("rh 1 (%)\n")
        f.write("u 1 (m/s)\n")
        f.write("Qsi 1 (W/m^2)\n")
        f.write("Qli 1 (W/m^2)\n")
        f.write("#" * 44 + "\n")        # MANDATORY delimiter before data (dt_v001)
        for i in range(n):
            dt = dates[i]
            f.write(f"{dt.year} {dt.month} {dt.day} {dt.hour} 0 "
                    f"{temp[i]:.2f} {precip[i]:.3f} {rh[i]:.1f} {wind[i]:.2f} "
                    f"{srad[i]:.2f} {lrad[i]:.2f}\n")

    years = {}
    for i in range(n):
        years[dates[i].year] = years.get(dates[i].year, 0.0) + float(precip[i])
    return {
        "obs_path": str(output_file),
        "n_steps": n,
        "timestep_seconds": int(d["timestep_seconds"]),
        "first_step": str(dates[0]),
        "last_step": str(dates[-1]),
        "precip_total_mm": round(float(precip.sum()), 1),
        "precip_mm_by_year": {str(y): round(v, 1) for y, v in sorted(years.items())},
        "precip_scale": float(precip_scale),
        "temp_c_min_max": [round(float(temp.min()), 2), round(float(temp.max()), 2)],
        "rh_pct_min_max": [round(float(rh.min()), 1), round(float(rh.max()), 1)],
        "wind_ms_mean": round(float(wind.mean()), 2),
        "wind_height_m": d.get("wind_height_m"),
    }


TABLE_COLUMNS = ["time"] + list(STANDARD_SERIES)


def read_standard_table(table_path):
    """A STANDARD TABLE CSV -> the standard series dict. Checks the form only;
    the values are judged by check_standard_series like every other source."""
    import csv
    import numpy as np

    if not Path(table_path).is_file():
        raise FileNotFoundError(f"--table_path not found: {table_path}")
    with open(table_path, newline="") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader, [])]
        rows = [r for r in reader if r and any(c.strip() for c in r)]
    missing = [c for c in TABLE_COLUMNS if c not in header]
    extra = [c for c in header if c not in TABLE_COLUMNS]
    if missing or extra or len(set(header)) != len(header):
        raise ValueError(
            f"{table_path}: columns must be exactly {TABLE_COLUMNS} (any order). "
            f"Missing: {missing or 'none'}; not allowed: {extra or 'none'}. Names carry the "
            f"unit on purpose -- convert, do not rename.")
    if not rows:
        raise ValueError(f"{table_path}: no data rows")
    bad_len = [i + 2 for i, r in enumerate(rows) if len(r) != len(header)]
    if bad_len:
        raise ValueError(f"{table_path}: line {bad_len[0]} has a different number of fields "
                         f"({len(bad_len)} such lines)")
    col = {h: [r[i].strip() for r in rows] for i, h in enumerate(header)}
    try:
        dates = np.array(col["time"], dtype="datetime64[s]")
    except ValueError as exc:
        raise ValueError(f"{table_path}: 'time' must be ISO like 2003-01-01T00:00:00 ({exc})")
    d = {"dates": dates}
    for name in STANDARD_SERIES:
        vals = []
        for i, v in enumerate(col[name]):
            try:
                vals.append(float(v) if v != "" else float("nan"))
            except ValueError:
                raise ValueError(f"{table_path}: line {i + 2}, {name} = {v!r} is not a number")
        d[name] = np.array(vals, dtype=float)
    # the most common step is the timestep; an uneven axis is then reported, with
    # its place, by check_standard_series
    if len(dates) > 1:
        all_steps = np.diff(dates).astype("timedelta64[s]").astype(int)
        vals, counts = np.unique(all_steps, return_counts=True)
        d["timestep_seconds"] = int(vals[np.argmax(counts)])
    else:
        d["timestep_seconds"] = 0
    return d


def save_standard_table(d, table_path):
    """Write a standard series dict as a STANDARD TABLE (full precision)."""
    import numpy as np
    dates = np.asarray(d["dates"]).astype("datetime64[s]")
    Path(table_path).parent.mkdir(parents=True, exist_ok=True)
    with open(table_path, "w") as f:
        f.write(",".join(TABLE_COLUMNS) + "\n")
        cols = [np.asarray(d[k], dtype=float) for k in STANDARD_SERIES]
        for i in range(len(dates)):
            f.write(str(dates[i]) + "," + ",".join(repr(float(c[i])) for c in cols) + "\n")


def check_period_covered(d, start_year, end_year):
    """The series must hold every step of start_year..end_year, no more, no less."""
    import numpy as np
    ts = int(d.get("timestep_seconds", 0) or 0)
    if ts <= 0 or 86400 % ts:
        raise ValueError(f"timestep_seconds {ts} does not divide a day")
    days = int((np.datetime64(f"{end_year + 1:04d}-01-01") - np.datetime64(f"{start_year:04d}-01-01"))
               / np.timedelta64(1, "D"))
    want = days * (86400 // ts)
    dates = np.asarray(d["dates"]).astype("datetime64[s]")
    first = np.datetime64(f"{start_year:04d}-01-01T00:00:00")
    if len(dates) != want or dates[0] != first:
        raise ValueError(
            f"forcing does not cover {start_year}-{end_year}: {len(dates)} steps from "
            f"{dates[0] if len(dates) else 'nothing'}, expected {want} steps from {first}. "
            f"Nothing written.")


def cmfd_grid_elevation(elev_nc):
    """(lats, lons, elevation[lat, lon]) of the CMFD forcing grid, or raise."""
    import numpy as np
    if not Path(elev_nc).is_file():
        raise FileNotFoundError(f"CMFD elevation field not found: {elev_nc}")
    # netcdf_safe.open_dataset is the KI's ONE load-order-safe reader (dt_v010):
    # a plain netCDF4.Dataset here fails with "NetCDF: HDF error" whenever h5py
    # was imported first.
    ds = netcdf_safe.open_dataset(elev_nc)
    try:
        lats = np.asarray(ds["lat"].values, dtype=float)
        lons = np.asarray(ds["lon"].values, dtype=float)
        elev = np.asarray(ds["elev"].values, dtype=float).squeeze()
    finally:
        ds.close()
    if elev.shape != (lats.size, lons.size):
        raise ValueError(f"{elev_nc}: elevation shape {elev.shape} is not (lat, lon)")
    return lats, lons, elev


def cmfd_cells_in_basin(basin_shp, elev_nc):
    """Every CMFD cell whose centre is inside the polygon.

    Returns (points [(lat, lon)], weights summing to 1, elevations). Weights
    are cos(latitude): a 0.1 deg cell is smaller nearer the pole.
    """
    import numpy as np
    import geopandas as gpd
    import shapely

    if not Path(basin_shp).is_file():
        raise FileNotFoundError(f"--basin_shp not found: {basin_shp}")
    gdf = gpd.read_file(basin_shp)
    if gdf.empty or gdf.crs is None:
        raise ValueError(f"{basin_shp}: no geometry, or no coordinate system stated")
    poly = gdf.to_crs(4326).geometry.union_all()
    lats, lons, elev = cmfd_grid_elevation(elev_nc)
    # The whole basin must lie on the grid. A basin that sticks out of the CMFD
    # domain would otherwise be averaged over its inside part only and still
    # give a normal-looking file.
    half_lat = abs(float(lats[1] - lats[0])) / 2.0
    half_lon = abs(float(lons[1] - lons[0])) / 2.0
    g_w, g_e = lons.min() - half_lon, lons.max() + half_lon
    g_s, g_n = lats.min() - half_lat, lats.max() + half_lat
    b_w, b_s, b_e, b_n = poly.bounds
    tol = 1e-6   # a polygon drawn exactly on the outer cell edge is on the grid
    if b_w < g_w - tol or b_e > g_e + tol or b_s < g_s - tol or b_n > g_n + tol:
        footprint = shapely.box(g_w, g_s, g_e, g_n)
        outside = 100.0 * (1.0 - poly.intersection(footprint).area / poly.area)
        raise ValueError(
            f"{basin_shp} is not fully inside the CMFD grid: basin lon {b_w:.2f} to "
            f"{b_e:.2f}, lat {b_s:.2f} to {b_n:.2f}; grid lon {g_w:.2f} to {g_e:.2f}, lat "
            f"{g_s:.2f} to {g_n:.2f}; about {outside:.1f}% of the basin (in degrees) is "
            f"outside. A mean over the inside part only would not be the basin. Use a "
            f"source that covers it.")
    lon2, lat2 = np.meshgrid(lons, lats)
    inside = shapely.contains_xy(poly, lon2, lat2)
    n = int(inside.sum())
    if n == 0:
        raise ValueError(
            f"no CMFD cell centre lies inside {basin_shp} (the basin is smaller than a "
            f"0.1 deg cell, or outside the CMFD domain {lats.min():.1f}-{lats.max():.1f} N, "
            f"{lons.min():.1f}-{lons.max():.1f} E). Use --lat/--lon for a small basin.")
    el = elev[inside]
    if not np.isfinite(el).all():
        raise ValueError(f"{int((~np.isfinite(el)).sum())} of {n} basin cells have no CMFD "
                         f"elevation (sea or outside the land mask)")
    w = np.cos(np.deg2rad(lat2[inside]))
    return (list(zip(lat2[inside].tolist(), lon2[inside].tolist())), w / w.sum(), el)


def basin_mean_cmfd(points, weights, start_year, end_year, forcing_dir):
    """Area-weighted mean of the CMFD cells -> ONE standard series.

    Read one year at a time (all cells of all years at once does not fit in
    memory for a large basin). Every variable is averaged over the cells step by
    step; precipitation is turned from the store's rate (kg m-2 s-1) into mm in
    the step first. A cell with a missing value makes the mean NaN, and the
    series is then refused by check_standard_series -- nothing is filled.
    """
    import numpy as np
    from ki_tools_common.load_forcing import load_subdaily_forcing_points

    w = np.asarray(weights, dtype=float)[:, None]
    names = {"temp_c": "temp_c", "srad_wm2": "srad_wm2", "lrad_wm2": "lrad_wm2",
             "wind_ms": "wind_ms", "shum_kgkg": "shum_kgkg", "pres_pa": "pres_pa"}
    out = {k: [] for k in list(names) + ["precip_mm"]}
    dates, ts = [], None
    for year in range(start_year, end_year + 1):
        logger.info(f"  basin mean {year}: reading {len(points)} CMFD cells")
        per_point = load_subdaily_forcing_points("cmfd", points, year, year,
                                                 forcing_dir=forcing_dir)
        if len(per_point) != len(points):
            raise ValueError(f"{year}: loader returned {len(per_point)} cells, "
                             f"asked for {len(points)}")
        ts_y = int(per_point[0]["timestep_seconds"])
        if ts is None:
            ts = ts_y
        elif ts_y != ts:
            raise ValueError(f"{year}: timestep {ts_y} s differs from {ts} s")
        dates.append(np.asarray(per_point[0]["dates"], dtype="datetime64[s]"))
        for key, src_key in names.items():
            a = np.array([np.asarray(p[src_key], dtype=float) for p in per_point])
            out[key].append((a * w).sum(axis=0))
        rate = np.array([np.asarray(p["prec_kgm2s"], dtype=float) for p in per_point])
        out["precip_mm"].append((rate * ts_y * w).sum(axis=0))   # kg m-2 s-1 * s = mm
        del per_point
    d = {k: np.concatenate(v) for k, v in out.items()}
    d["dates"] = np.concatenate(dates)
    d["timestep_seconds"] = ts
    return d


def build_from_source(source, lat, lon, output_path, start_year, end_year,
                      forcing_dir=None, precip_scale=1.0, basin_shp=None,
                      cmfd_elev_nc=CMFD_ELEV_NC, table_path=None, table_name=None,
                      forcing_elev_m=None, save_table=None):
    """Half 1 + half 2. One point (lat, lon) or a basin mean (basin_shp).

    Returns the summary dict (also saved next to the .obs as .meta.json).
    """
    import numpy as np
    from ki_tools_common.load_forcing import load_hourly_forcing

    where = {}
    if source == TABLE_SOURCE:
        if not table_path or not table_name or not str(table_name).strip():
            raise ValueError("--source table needs --table_path and --table_name")
        logger.info(f"Reading standard table {table_path} ({table_name})")
        d = read_standard_table(table_path)
        description = f"CRHM forcing from table {table_name} {start_year}-{end_year}"
        where = {"mode": "table", "table_path": str(table_path), "table_name": table_name,
                 "forcing_elev_m": forcing_elev_m,
                 "forcing_elev_source": ("given with --forcing_elev_m"
                                         if forcing_elev_m is not None else None),
                 "via": "a standard table made by the caller (half 1 done outside this "
                        "tool)"}
    elif basin_shp:
        if source != "cmfd":
            raise ValueError(f"--basin_shp is available for --source cmfd only, not {source}; "
                             f"use --lat/--lon")
        points, weights, elevs = cmfd_cells_in_basin(basin_shp, cmfd_elev_nc)
        logger.info(f"Basin mean over {len(points)} CMFD cells inside {basin_shp} "
                    f"{start_year}-{end_year}")
        d = basin_mean_cmfd(points, weights, start_year, end_year, forcing_dir)
        lats = np.array([p[0] for p in points]); lons = np.array([p[1] for p in points])
        description = (f"CRHM forcing from cmfd basin mean of {len(points)} cells "
                       f"({Path(basin_shp).name}) {start_year}-{end_year}")
        where = {"mode": "basin_mean", "basin_shp": str(basin_shp), "n_cells": len(points),
                 "cell_weighting": "cos(latitude)",
                 "averaging": "each variable is the plain area mean of the cell values, step "
                              "by step. Relative humidity is worked out AFTER averaging, from "
                              "mean specific humidity, mean pressure and mean temperature; it "
                              "is not the mean of the cells' relative humidity. No correction "
                              "for elevation is made inside the mean: the series stands for "
                              "forcing_elev_m, and CRHM lapses temperature from there per HRU.",
                 "cells_lat_min_max": [float(lats.min()), float(lats.max())],
                 "cells_lon_min_max": [float(lons.min()), float(lons.max())],
                 "forcing_elev_m": round(float((elevs * weights).sum()), 1),
                 "cell_elev_m_min_max": [float(elevs.min()), float(elevs.max())],
                 "forcing_elev_source": str(cmfd_elev_nc),
                 "via": "ki_tools_common.load_forcing.load_subdaily_forcing_points"}
    else:
        logger.info(f"Loading hourly {source} forcing at ({lat}, {lon}) {start_year}-{end_year}")
        d = load_hourly_forcing(source, lat, lon, start_year, end_year, forcing_dir=forcing_dir)
        description = f"CRHM forcing from {source} at ({lat}, {lon}) {start_year}-{end_year}"
        where = {"mode": "point", "lat": lat, "lon": lon, "forcing_elev_m": None,
                 "via": "ki_tools_common.load_forcing.load_hourly_forcing"}
        if source == "cmfd":
            # the elevation the cell's temperature stands for; never guessed
            try:
                glats, glons, gelev = cmfd_grid_elevation(cmfd_elev_nc)
                i = int(np.abs(glats - lat).argmin()); j = int(np.abs(glons - lon).argmin())
                if np.isfinite(gelev[i, j]):
                    where.update({"forcing_elev_m": round(float(gelev[i, j]), 1),
                                  "forcing_elev_source": str(cmfd_elev_nc),
                                  "cell_centre": [float(glats[i]), float(glons[j])]})
            except Exception as exc:
                logger.warning("CMFD cell elevation not read (%s); forcing_elev_m left empty.",
                               exc)

    # values and time axis first (a gap is named with its place), then the period
    problems = check_standard_series(d)
    if problems:
        raise ValueError("forcing series not usable, nothing written:\n  - "
                         + "\n  - ".join(problems))
    check_period_covered(d, start_year, end_year)
    summary = standard_to_obs(d, description, output_path, precip_scale=precip_scale)
    if save_table:
        save_standard_table(d, save_table)       # the series as read, before --precip_scale
        summary["standard_table"] = str(save_table)
    summary.update({"source": source, "start_year": start_year, "end_year": end_year,
                    "forcing_dir": forcing_dir, "clock_utc_offset_hours": 0.0})
    summary.update(where)
    meta_path = str(output_path) + ".meta.json"
    with open(meta_path, "w") as f:
        json.dump(summary, f, indent=2)
    if summary.get("forcing_elev_m") is not None:
        logger.info(f"Forcing elevation {summary['forcing_elev_m']} m -> pass it to "
                    f"derive_parameters.py --forcing_elev_m")
    logger.info(f"Wrote {summary['n_steps']} timesteps of {summary['timestep_seconds']} s "
                f"to {summary['obs_path']} "
                f"(P_total={summary['precip_total_mm']:.0f} mm, "
                f"max RH={summary['rh_pct_min_max'][1]:.1f}%)")
    return summary


def validate_inputs(args):
    errors = []
    point = args.lat is not None or args.lon is not None
    table_only = [n for n, v in (("--table_path", args.table_path), ("--table_name", args.table_name),
                                 ("--forcing_elev_m", args.forcing_elev_m)) if v is not None]
    if args.source == TABLE_SOURCE:
        if not args.table_path or not args.table_name or not args.table_name.strip():
            errors.append("--source table needs --table_path and --table_name")
        elif not Path(args.table_path).is_file():
            errors.append(f"--table_path not found: {args.table_path}")
        if point or args.basin_shp or args.forcing_dir:
            errors.append("--lat/--lon, --basin_shp and --forcing_dir do not apply to "
                          "--source table (the table already is the series)")
    elif table_only:
        errors.append(f"{', '.join(table_only)} only apply to --source table")
    elif args.basin_shp and point:
        errors.append("give --lat/--lon OR --basin_shp, not both")
    elif args.basin_shp:
        if not Path(args.basin_shp).is_file():
            errors.append(f"--basin_shp not found: {args.basin_shp}")
        if args.source != "cmfd":
            errors.append(f"--basin_shp is available for --source cmfd only, not {args.source}")
    elif args.lat is None or args.lon is None:
        errors.append("give where to read the forcing: --lat and --lon, or --basin_shp")
    else:
        if not (-90.0 <= args.lat <= 90.0):
            errors.append(f"--lat {args.lat} is not a latitude")
        if not (-180.0 <= args.lon <= 360.0):
            errors.append(f"--lon {args.lon} is not a longitude")
    if args.start_year > args.end_year:
        errors.append(f"Start year ({args.start_year}) > end year ({args.end_year})")
    if args.source in ("cmfd", "mswx") and args.forcing_dir and not Path(args.forcing_dir).is_dir():
        errors.append(f"--forcing_dir not found: {args.forcing_dir}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_path):
    """Re-read the file as CRHM will: one description line, declarations, ####, rows."""
    errors = []
    p = Path(output_path)
    if not p.exists() or p.stat().st_size == 0:
        errors.append(f"Output file missing or empty: {output_path}")
    else:
        with open(p) as f:
            head = [next(f, "") for _ in range(9)]
        want = ["t 1 (C)", "p 1 (mm)", "rh 1 (%)", "u 1 (m/s)", "Qsi 1 (W/m^2)", "Qli 1 (W/m^2)"]
        got = [h.strip() for h in head[1:7]]
        if got != want:
            errors.append(f"variable declarations are {got}, expected {want}")
        if not head[7].startswith("####"):
            errors.append("no #### line between the declarations and the data (dt_v001)")
        if len(head[8].split()) != 11:
            errors.append(f"first data row has {len(head[8].split())} fields, expected 11")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def main(argv=None):
    if argv is not None:
        sys.argv = [sys.argv[0]] + list(argv)
    args = parse_args()
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs(args)
    try:
        summary = build_from_source(
            args.source, args.lat, args.lon, args.output_path,
            args.start_year, args.end_year,
            forcing_dir=args.forcing_dir, precip_scale=args.precip_scale,
            basin_shp=args.basin_shp, cmfd_elev_nc=args.cmfd_elev_nc,
            table_path=args.table_path, table_name=args.table_name,
            forcing_elev_m=args.forcing_elev_m, save_table=args.save_table)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    validate_outputs(summary["obs_path"])
    print(json.dumps({"status": "success", "output": summary["obs_path"],
                      "meta": summary["obs_path"] + ".meta.json"}))
    sys.exit(0)


if __name__ == "__main__":
    main()
