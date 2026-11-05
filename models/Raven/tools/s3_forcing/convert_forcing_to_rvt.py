#!/usr/bin/env python3
"""
convert_forcing_to_rvt.py — Build the Raven .rvt forcing file straight from a
forcing source (CMFD, MSWX or NASA POWER).

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!! CRITICAL WARNING: RAVEN IGNORES UNITS AND WILL NOT DO UNIT CONVERSION.    !!
!! All conversions MUST happen in this tool. If units are wrong, Raven will  !!
!! run without error but produce completely wrong results (SILENT FAILURE).  !!
!!                                                                          !!
!! This is the #1 source of errors in Raven applications.                   !!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

Two halves, kept apart on purpose:

  1. source -> STANDARD DAILY SERIES (shared, ki_tools_common.load_forcing)
     load_daily_forcing (one point) / load_daily_forcing_points (many points in
     one shared pass). The loader does the source's own unit work and returns,
     for every source, the same daily series:
         precip_mm (mm in the day), temp_max_c, temp_min_c (deg C),
         wind_ms (m/s), srad_wm2, lrad_wm2 (W/m2), pres_pa (Pa)

  2. STANDARD DAILY SERIES -> Raven .rvt (this tool)
  | Variable     | loader series | Raven unit | Conversion here               |
  |--------------|---------------|------------|-------------------------------|
  | PRECIP       | precip_mm     | mm/d       | none (already a day total)    |
  | TEMP_MIN     | temp_min_c    | degC       | none                          |
  | TEMP_MAX     | temp_max_c    | degC       | none                          |
  | TEMP_AVE     | (computed)    | degC       | (TEMP_MAX + TEMP_MIN) / 2     |
  | WIND_VEL     | wind_ms       | m/s        | none                          |
  | SW_RADIA     | srad_wm2      | MJ/m2/d    | multiply by 0.0864            |
  | AIR_PRES     | pres_pa       | kPa        | divide by 1000                |

Where the forcing is read (give exactly one):
  --lat --lon     ONE point (the source grid cell nearest to it). Right for a
                  small basin inside one or two cells.
  --points_csv    a CSV with a header and columns lat,lon: the plain mean over
                  those points, day by day.
  --basin_shp     a basin polygon: the mean over EVERY source grid cell whose
                  centre lies inside it, weighted by cos(latitude). Right for a
                  lumped basin run. One cell for a large basin is a sample of
                  one. The tool says how many cells it took and refuses a
                  polygon with no cell centre inside or not fully on the grid.

The basin mean is the mean of the cells' DAILY values (daily Tmax of the basin
= mean of the cells' daily Tmax). No correction for elevation is made inside
the mean: the series stands for --gauge_elev, and Raven lapses from there.

--gauge_elev is the elevation (m) the series stands for (the :Elevation of the
gauge block). With orographic corrections on (select_model_template.py) a wrong
value shifts every HRU's temperature, so it is never guessed: for cmfd it is
read from the store's own elevation field when not given; for mswx and
nasa_power it must be given (the area-weighted mean HRU elevation of the .rvh).

No value is made up. A missing or non-finite value, a value outside its
physical range, an uneven time axis or a period that is not fully covered stops
the tool with a clear error and NOTHING is written.

Observed discharge (--obs_file): the gauge table (text, header with a date
column and a discharge column in m3/s; negative values such as -99 mean
missing) is written as <basin>_obs.rvt (:ObservationData HYDROGRAPH), the file
the main .rvt redirects to. Limit it with --obs_start_date / --obs_end_date.

Outputs (in --output_dir):
  <basin>.rvt                    forcing gauge block
  <basin>_obs.rvt                only with --obs_file
  <basin>_forcing_summary.json   source, number of points, period, mean annual
                                 precipitation, gauge elevation

Usage (basin mean, the normal case for a lumped model):
    python convert_forcing_to_rvt.py \
        --forcing_source cmfd \
        --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg \
        --basin_shp <basin polygon .shp / .geojson> \
        --output_dir <out dir>/ --basin_name <basin> \
        --start_year 2004 --end_year 2015 --include_full_forcing \
        --obs_file <observed discharge text file> \
        --obs_subbasin_id 1 --obs_start_date 2007-01-01 --obs_end_date 2015-12-31

Usage (one point):
    python convert_forcing_to_rvt.py --forcing_source cmfd --lat 35.5 --lon 100.15 \
        --output_dir out/ --basin_name mybasin --start_year 2004 --end_year 2015

Exit codes: 0 success, 1 input validation failed, 2 processing error (nothing
written).
"""

import argparse
import json
import os
import sys
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

try:
    import numpy as np
except ImportError:
    print(json.dumps({"status": "error", "message": "numpy is required"}))
    sys.exit(1)


SOURCES = ("cmfd", "mswx", "nasa_power")   # read by ki_tools_common.load_forcing

# The CMFD store's own surface elevation, on the forcing grid (0.1 deg). It
# gives the cell centres for --basin_shp and the elevation the series stands for.
CMFD_ELEV_NC = "KISSPATH_DATA/elev/elev_CMFD_V0200_B-00_fx_010deg.nc"

# NASA POWER meteorology sits on the MERRA-2 grid: 0.5 deg latitude by 0.625 deg
# longitude, cell centres at -90 + 0.5 i and -180 + 0.625 j.
NASA_POWER_DLAT, NASA_POWER_DLON = 0.5, 0.625

# Physical bounds for quality checks (CRITICAL — catches unit errors)
BOUNDS = {
    "PRECIP": (0, 500),        # mm/d — max 500 is extreme but possible
    "TEMP_MIN": (-60, 55),     # degC
    "TEMP_MAX": (-60, 60),     # degC
    "TEMP_AVE": (-60, 55),     # degC
    "WIND_VEL": (0, 50),       # m/s
    "REL_HUMIDITY": (0, 1.1),  # fraction — slightly >1 from rounding is OK
    "SW_RADIA": (0, 50),       # MJ/m2/d (solar constant ~118 MJ/m2/d)
    "AIR_PRES": (30, 110),     # kPa
}

# Raven's blank marker for a missing observation
RAVEN_MISSING = -1.2345

# daily 7-column array used inside this tool
COLS = ["PRECIP", "TEMP_MAX", "TEMP_MIN", "WIND_VEL", "SW_RADIA", "LW_INCOMING", "AIR_PRES"]
# loader series -> (column, multiply by, divide by) to the Raven unit
SERIES = {
    "precip_mm":  (0, 1.0, 1.0),       # mm/d
    "temp_max_c": (1, 1.0, 1.0),       # degC
    "temp_min_c": (2, 1.0, 1.0),       # degC
    "wind_ms":    (3, 1.0, 1.0),       # m/s
    "srad_wm2":   (4, 0.0864, 1.0),    # W/m2 -> MJ/m2/d
    "lrad_wm2":   (5, 0.0864, 1.0),    # W/m2 -> MJ/m2/d
    "pres_pa":    (6, 1.0, 1000.0),    # Pa -> kPa
}
MSWX_KEYS = {"precip_mm": "P", "temp_max_c": "Tair", "temp_min_c": "Tair",
             "wind_ms": "Wind", "srad_wm2": "SWd", "pres_pa": "Pres"}


class ForcingError(Exception):
    """The forcing (or the gauge table) is not usable; nothing is written."""


def written_variables(include_full_forcing):
    """Raven variables that go into the .rvt, in file order."""
    # Minimum: PRECIP + TEMP_MIN + TEMP_MAX (Raven generates the rest)
    if include_full_forcing:
        return ["PRECIP", "TEMP_MIN", "TEMP_MAX", "TEMP_AVE",
                "WIND_VEL", "SW_RADIA", "AIR_PRES"]
    return ["PRECIP", "TEMP_MIN", "TEMP_MAX", "TEMP_AVE"]


def needed_series(include_full_forcing):
    """Loader series the written variables are made from."""
    keys = ["precip_mm", "temp_max_c", "temp_min_c"]
    if include_full_forcing:
        keys += ["wind_ms", "srad_wm2", "pres_pa"]
    return keys


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    point = args.lat is not None or args.lon is not None
    places = int(point) + int(bool(args.points_csv)) + int(bool(args.basin_shp))
    if places != 1:
        errors.append("give where to read the forcing, exactly one of: --lat and --lon "
                      "(one point), --points_csv (lat,lon rows), --basin_shp (basin polygon)")
    if point:
        if args.lat is None or args.lon is None:
            errors.append("--lat and --lon go together")
        else:
            if not (-90.0 <= args.lat <= 90.0):
                errors.append(f"--lat {args.lat} is not a latitude")
            if not (-180.0 <= args.lon <= 360.0):
                errors.append(f"--lon {args.lon} is not a longitude")
    if args.points_csv and not os.path.isfile(args.points_csv):
        errors.append(f"--points_csv not found: {args.points_csv}")
    if args.basin_shp and not os.path.isfile(args.basin_shp):
        errors.append(f"--basin_shp not found: {args.basin_shp}")
    if args.forcing_dir and args.forcing_source in ("cmfd", "mswx") \
            and not os.path.isdir(args.forcing_dir):
        errors.append(f"--forcing_dir not found: {args.forcing_dir}")
    if args.start_year > args.end_year:
        errors.append(f"start_year ({args.start_year}) > end_year ({args.end_year})")
    if args.obs_file and not os.path.isfile(args.obs_file):
        errors.append(f"--obs_file not found: {args.obs_file}")
    if not args.obs_file and (args.obs_start_date or args.obs_end_date):
        errors.append("--obs_start_date / --obs_end_date only apply with --obs_file")
    for name in ("obs_start_date", "obs_end_date"):
        v = getattr(args, name)
        if v:
            try:
                np.datetime64(v, "D")
            except ValueError:
                errors.append(f"--{name} {v} is not a date (YYYY-MM-DD)")
    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Where: points and the source grid
# ---------------------------------------------------------------------------

def _open_nc(path):
    """Open a NetCDF file whichever HDF5 library the process loaded first.

    python_env holds two HDF5 copies (netCDF4 wheel, h5py wheel); the one loaded
    first is the only one that can open a file. A bare xr.open_dataset(path)
    fails with "NetCDF: HDF error" when xarray was loaded first (dt_rav_047).
    """
    import xarray as xr
    errs = []
    for eng in ("h5netcdf", None):
        try:
            return xr.open_dataset(path, engine=eng) if eng else xr.open_dataset(path)
        except Exception as exc:
            errs.append(f"{eng or 'default'} engine: {type(exc).__name__}: {exc}")
    raise ForcingError(f"cannot open {path} ({'; '.join(errs)})")


def cmfd_grid_elevation(elev_nc):
    """(lats, lons, elevation[lat, lon]) of the CMFD forcing grid, or raise."""
    if not os.path.isfile(elev_nc):
        raise ForcingError(f"CMFD elevation field not found: {elev_nc} (--cmfd_elev_nc)")
    ds = _open_nc(elev_nc)
    try:
        lats = np.asarray(ds["lat"].values, dtype=float)
        lons = np.asarray(ds["lon"].values, dtype=float)
        elev = np.asarray(ds["elev"].values, dtype=float).squeeze()
    finally:
        ds.close()
    if elev.shape != (lats.size, lons.size):
        raise ForcingError(f"{elev_nc}: elevation shape {elev.shape} is not (lat, lon)")
    return lats, lons, elev


def source_grid(source, forcing_dir, start_year, cmfd_elev_nc):
    """Cell-centre vectors of the source grid: (lats, lons, elevation or None)."""
    if source == "cmfd":
        return cmfd_grid_elevation(cmfd_elev_nc)
    if source == "mswx":
        import h5py
        from ki_tools_common import load_forcing as lf
        fpath = os.path.join(forcing_dir or lf.MSWX_DIR, "P", f"P_{start_year}.nc")
        if not os.path.isfile(fpath):
            raise ForcingError(f"MSWX file not found: {fpath} (grid for --basin_shp)")
        with h5py.File(fpath, "r") as f:
            return (np.asarray(f["lat"][:], dtype=float),
                    np.asarray(f["lon"][:], dtype=float), None)
    lats = np.arange(-90.0, 90.0 + 1e-9, NASA_POWER_DLAT)
    lons = np.arange(-180.0, 180.0 - 1e-9, NASA_POWER_DLON)
    return lats, lons, None


def cells_in_basin(basin_shp, lats, lons, source):
    """Every source cell whose centre is inside the polygon.

    Returns (lat array, lon array, weights summing to 1, index arrays). Weights
    are cos(latitude): a cell of fixed size in degrees is smaller nearer the pole.
    """
    import geopandas as gpd
    import shapely

    gdf = gpd.read_file(basin_shp)
    if gdf.empty or gdf.crs is None:
        raise ForcingError(f"{basin_shp}: no geometry, or no coordinate system stated")
    geom = gdf.to_crs(4326).geometry
    poly = geom.union_all() if hasattr(geom, "union_all") else geom.unary_union
    # The whole basin must lie on the grid. A basin that sticks out of the
    # source area would otherwise be averaged over its inside part only and
    # still give a normal-looking file.
    half_lat = abs(float(lats[1] - lats[0])) / 2.0
    half_lon = abs(float(lons[1] - lons[0])) / 2.0
    g_w, g_e = lons.min() - half_lon, lons.max() + half_lon
    g_s, g_n = lats.min() - half_lat, lats.max() + half_lat
    b_w, b_s, b_e, b_n = poly.bounds
    tol = 1e-6
    if b_w < g_w - tol or b_e > g_e + tol or b_s < g_s - tol or b_n > g_n + tol:
        raise ForcingError(
            f"{basin_shp} is not fully inside the {source} grid: basin lon {b_w:.2f} to "
            f"{b_e:.2f}, lat {b_s:.2f} to {b_n:.2f}; grid lon {g_w:.2f} to {g_e:.2f}, lat "
            f"{g_s:.2f} to {g_n:.2f}. A mean over the inside part only would not be the "
            f"basin. Use a source that covers it.")
    # only the cells of the polygon's bounding box need testing
    i = np.where((lats >= b_s) & (lats <= b_n))[0]
    j = np.where((lons >= b_w) & (lons <= b_e))[0]
    if i.size and j.size:
        lon2, lat2 = np.meshgrid(lons[j], lats[i])
        ii, jj = np.meshgrid(i, j, indexing="ij")
        inside = shapely.contains_xy(poly, lon2, lat2)
    else:
        inside = np.zeros((0, 0), dtype=bool)
    n = int(inside.sum())
    if n == 0:
        raise ForcingError(
            f"no {source} cell centre lies inside {basin_shp} (the basin is smaller than a "
            f"grid cell). Use --lat/--lon for a small basin.")
    la, lo = lat2[inside], lon2[inside]
    w = np.cos(np.deg2rad(la))
    return la, lo, w / w.sum(), (ii[inside], jj[inside])


def read_points_csv(path):
    """lat,lon rows from a CSV with a header naming both columns."""
    import csv
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(f) if r and any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ForcingError(f"{path}: needs a header line and at least one lat,lon row")
    header = [h.strip().lower() for h in rows[0]]
    if "lat" not in header or "lon" not in header:
        raise ForcingError(f"{path}: header must name the columns 'lat' and 'lon', got {rows[0]}")
    a, b = header.index("lat"), header.index("lon")
    pts = []
    for n, r in enumerate(rows[1:], start=2):
        try:
            la, lo = float(r[a]), float(r[b])
        except (ValueError, IndexError):
            raise ForcingError(f"{path}: line {n} is not a lat,lon pair: {r}")
        if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 360.0):
            raise ForcingError(f"{path}: line {n}: ({la}, {lo}) is not a lat,lon pair")
        pts.append((la, lo))
    return pts


def resolve_place(args):
    """Points, weights and the elevation the series stands for.

    Returns dict: mode, points [(lat, lon)], weights (sum 1), gauge_elev,
    gauge_elev_source, plus what the summary reports.
    """
    src = args.forcing_source
    place = {}
    grid = None
    if args.basin_shp:
        lats, lons, elev = source_grid(src, args.forcing_dir, args.start_year, args.cmfd_elev_nc)
        la, lo, w, idx = cells_in_basin(args.basin_shp, lats, lons, src)
        grid = (lats, lons, elev)
        cell_elev = elev[idx] if elev is not None else None
        place.update({"mode": "basin_mean", "basin_shp": os.path.abspath(args.basin_shp),
                      "weighting": "cos(latitude)"})
    elif args.points_csv:
        pts = read_points_csv(args.points_csv)
        la = np.array([p[0] for p in pts]); lo = np.array([p[1] for p in pts])
        w = np.full(len(pts), 1.0 / len(pts))
        cell_elev = None
        place.update({"mode": "points_mean", "points_csv": os.path.abspath(args.points_csv),
                      "weighting": "equal"})
    else:
        la = np.array([float(args.lat)]); lo = np.array([float(args.lon)])
        w = np.array([1.0])
        cell_elev = None
        place.update({"mode": "point", "weighting": "none"})

    if src == "cmfd":
        # The loader takes the NEAREST cell and never says a point is off the
        # grid: a point outside China would silently get an edge cell.
        if grid is None:
            grid = cmfd_grid_elevation(args.cmfd_elev_nc)
        lats, lons, elev = grid
        h = abs(float(lats[1] - lats[0])) / 2.0
        off = (la < lats.min() - h) | (la > lats.max() + h) | \
              (lo < lons.min() - h) | (lo > lons.max() + h)
        if off.any():
            k = int(np.argmax(off))
            raise ForcingError(
                f"{int(off.sum())} of {la.size} points are outside the CMFD grid "
                f"({lats.min() - h:.1f}-{lats.max() + h:.1f} N, {lons.min() - h:.1f}-"
                f"{lons.max() + h:.1f} E), first ({la[k]:.3f}, {lo[k]:.3f}). Use mswx or "
                f"nasa_power.")
        if cell_elev is None:
            ci = np.abs(lats[None, :] - la[:, None]).argmin(axis=1)
            cj = np.abs(lons[None, :] - lo[:, None]).argmin(axis=1)
            cell_elev = elev[ci, cj]

    if args.gauge_elev is not None:
        gauge_elev, elev_src = float(args.gauge_elev), "given with --gauge_elev"
    elif src == "cmfd":
        if not np.isfinite(cell_elev).all():
            raise ForcingError(
                f"{int((~np.isfinite(cell_elev)).sum())} of {la.size} points have no CMFD "
                f"elevation (sea or outside the land mask); give --gauge_elev")
        gauge_elev = float((cell_elev * w).sum())
        elev_src = f"mean of the CMFD cell elevations ({args.cmfd_elev_nc})"
    else:
        raise ForcingError(
            f"--gauge_elev is required with --forcing_source {src}: the elevation (m) the "
            f"series stands for (area-weighted mean HRU elevation of the .rvh). It is not "
            f"guessed; a wrong value shifts every HRU's temperature when orographic "
            f"corrections are on.")
    place.update({"points": list(zip(la.tolist(), lo.tolist())), "weights": w,
                  "gauge_elev": gauge_elev, "gauge_elev_source": elev_src,
                  "points_lat_min_max": [float(la.min()), float(la.max())],
                  "points_lon_min_max": [float(lo.min()), float(lo.max())]})
    return place


# ---------------------------------------------------------------------------
# Half 1: source -> standard daily series (shared loader)
# ---------------------------------------------------------------------------

def _load_points(source, points, start_year, end_year, forcing_dir, variables):
    """One dict per point from ki_tools_common.load_forcing (the ONLY reader)."""
    from ki_tools_common.load_forcing import load_daily_forcing, load_daily_forcing_points
    kw = {"forcing_dir": forcing_dir}
    if variables:
        kw["variables"] = variables
    if len(points) == 1:
        la, lo = points[0]
        return [load_daily_forcing(source, la, lo, start_year, end_year, **kw)]
    return load_daily_forcing_points(source, points, start_year, end_year, **kw)


def expected_days(start_year, end_year):
    return np.arange(np.datetime64(f"{start_year:04d}-01-01"),
                     np.datetime64(f"{end_year + 1:04d}-01-01"), np.timedelta64(1, "D"))


def check_time_axis(dates, start_year, end_year, what):
    """Every day of start_year..end_year, once, in order — or raise."""
    want = expected_days(start_year, end_year)
    try:
        got = np.asarray(dates, dtype="datetime64[s]").astype("datetime64[D]")
    except (ValueError, TypeError) as exc:
        raise ForcingError(f"{what}: time axis not readable ({exc})")
    if got.size == 0:
        raise ForcingError(f"{what}: no days returned for {start_year}-{end_year}")
    steps = np.diff(got).astype(int)
    if steps.size and not (steps == 1).all():
        k = int(np.argmax(steps != 1))
        raise ForcingError(
            f"{what}: uneven time axis, {int((steps != 1).sum())} steps are not one day "
            f"(first after {got[k]}: next is {got[k + 1]}). Nothing written.")
    if got.size != want.size or got[0] != want[0] or got[-1] != want[-1]:
        raise ForcingError(
            f"{what}: period {start_year}-{end_year} is not fully covered: {got.size} days "
            f"from {got[0]} to {got[-1]}, expected {want.size} days from {want[0]} to "
            f"{want[-1]}. Nothing written.")
    return want


def build_daily(args, place):
    """Loader series at every point -> ONE daily array in Raven units.

    Columns: 0 PRECIP (mm/d), 1 TEMP_MAX (C), 2 TEMP_MIN (C), 3 WIND (m/s),
    4 SHORTWAVE (MJ/m2/d), 5 LONGWAVE (MJ/m2/d), 6 PRESSURE (kPa).
    A column that is not written stays as the loader gave it (may be NaN).
    Read one year at a time: all cells of all years at once does not fit in
    memory for a large basin.
    """
    src = args.forcing_source
    points, w = place["points"], np.asarray(place["weights"], dtype=float)
    need = needed_series(args.include_full_forcing)
    variables = None
    if src == "mswx":
        # each MSWX variable skipped saves a whole-year decompression
        variables = tuple(dict.fromkeys(MSWX_KEYS[k] for k in need))
    forcing_dir = args.forcing_dir if args.forcing_dir else None
    blocks, dates = [], []
    single = len(points) == 1
    years = [(args.start_year, args.end_year)] if single else \
        [(y, y) for y in range(args.start_year, args.end_year + 1)]
    for y0, y1 in years:
        label = f"{src} {y0}" if y0 == y1 else f"{src} {y0}-{y1}"
        try:
            per_point = _load_points(src, points, y0, y1, forcing_dir, variables)
        except ForcingError:
            raise
        except Exception as exc:
            raise ForcingError(f"{label}: the loader could not read the forcing "
                               f"({type(exc).__name__}: {exc}). Nothing written.")
        if len(per_point) != len(points):
            raise ForcingError(f"{label}: loader returned {len(per_point)} points, "
                               f"asked for {len(points)}")
        days = check_time_axis(per_point[0]["dates"], y0, y1, label)
        block = np.full((days.size, 7), np.nan)
        for key, (col, mult, div) in SERIES.items():
            missing_key = [n for n, p in enumerate(per_point) if key not in p or p[key] is None]
            if missing_key:
                if key in need:
                    raise ForcingError(f"{label}: series {key} missing at "
                                       f"{len(missing_key)} of {len(points)} points")
                continue
            a = np.array([np.asarray(p[key], dtype=float) for p in per_point])  # (npts, ndays)
            if a.shape != (len(points), days.size):
                raise ForcingError(f"{label}: {key} has shape {a.shape}, expected "
                                   f"({len(points)}, {days.size})")
            if key in need:
                bad = ~np.isfinite(a)
                if bad.any():
                    pi, di = np.argwhere(bad)[0]
                    raise ForcingError(
                        f"{label}: {key} has {int(bad.sum())} missing or non-finite values "
                        f"(first on {days[di]} at point ({points[pi][0]:.3f}, "
                        f"{points[pi][1]:.3f})). No value is filled in. Nothing written.")
            series = a[0] if single else (a * w[:, None]).sum(axis=0)
            block[:, col] = series * mult / div
        blocks.append(block)
        dates.append(days)
        del per_point
    return np.concatenate(blocks), np.concatenate(dates)


def bounds_check(daily, variables):
    """Values outside the physical range of a written variable = a unit error."""
    problems = []
    cols = {v: COLS.index(v) for v in COLS}
    for var in variables:
        if var == "TEMP_AVE":
            col = (daily[:, 1] + daily[:, 2]) / 2.0
        else:
            col = daily[:, cols[var]]
        lo, hi = BOUNDS[var]
        if col.min() < lo or col.max() > hi:
            problems.append(f"{var}: range [{col.min():.2f}, {col.max():.2f}] outside "
                            f"expected [{lo}, {hi}] — likely unit error upstream")
    return problems


# ---------------------------------------------------------------------------
# Half 2: standard daily series -> .rvt text
# ---------------------------------------------------------------------------

def generate_rvt_gauge_block(station_name, lat, lon, elev, daily_data,
                              start_date, variables):
    """
    Generate a Raven gauge block for .rvt file.

    Format:
      :Gauge StationName
        :Latitude 40.5
        :Longitude 116.8
        :Elevation 500.0
        :Data PRECIP mm/d
          2000-01-01 00:00:00.0 1.0 365
          value1
          value2
          ...
        :EndData
      :EndGauge
    """
    lines = []
    lines.append(f":Gauge {station_name}")
    lines.append(f"  :Latitude  {lat:.4f}")
    lines.append(f"  :Longitude {lon:.4f}")
    lines.append(f"  :Elevation {elev:.1f}")
    lines.append("")

    n_days = len(daily_data)

    # Variable-to-column mapping and units
    var_info = {
        "PRECIP":       {"col": 0, "unit": "mm/d"},
        "TEMP_MAX":     {"col": 1, "unit": "degC"},
        "TEMP_MIN":     {"col": 2, "unit": "degC"},
        "TEMP_AVE":     {"col": None, "unit": "degC"},  # computed
        "WIND_VEL":     {"col": 3, "unit": "m/s"},
        "SW_RADIA":     {"col": 4, "unit": "MJ/m2/d"},
        "LW_INCOMING":  {"col": 5, "unit": "MJ/m2/d"},
        "AIR_PRES":     {"col": 6, "unit": "kPa"},
    }

    for var in variables:
        if var not in var_info:
            continue

        info = var_info[var]
        unit = info["unit"]

        lines.append(f"  :Data {var} {unit}")
        lines.append(f"    {start_date} 00:00:00.0 1.0 {n_days}")

        if var == "TEMP_AVE":
            # Compute average from min and max
            values = (daily_data[:, 1] + daily_data[:, 2]) / 2.0
        else:
            col = info["col"]
            values = daily_data[:, col]

        for v in values:
            # Raven's time-series parser rejects the token "-0.0000" (negative
            # zero) as non-numeric. Tiny negative values (e.g. -1e-5) round to
            # "-0.0000" under %.4f, so normalise the sign before writing.
            s = f"{v:.4f}"
            if s.startswith("-") and float(s) == 0.0:
                s = s[1:]
            lines.append(f"    {s}")

        lines.append(f"  :EndData")
        lines.append("")

    lines.append(":EndGauge")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Observed discharge -> <basin>_obs.rvt
# ---------------------------------------------------------------------------

DATE_NAMES = ("dates", "date", "time", "datetime")
Q_NAMES = ("q", "discharge", "flow", "streamflow", "discharge_m3s", "q_m3s", "qobs")


def read_gauge_table(obs_file):
    """Daily discharge (m3/s) from a text table -> (days, values).

    Header line with a date column and a discharge column; fields split on
    tab, comma or blanks. A negative value (-99, -9999) or an empty/unreadable
    field is a missing day. Duplicate days keep the first value.
    """
    import re
    with open(obs_file, encoding="utf-8-sig", errors="replace") as f:
        lines = [ln.rstrip("\n\r") for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if len(lines) < 2:
        raise ForcingError(f"{obs_file}: no data rows")

    def split(ln):
        if "\t" in ln:
            return [c.strip() for c in ln.split("\t")]
        if "," in ln:
            return [c.strip() for c in ln.split(",")]
        return ln.split()

    header = [h.lower() for h in split(lines[0])]
    di = next((header.index(n) for n in DATE_NAMES if n in header), None)
    qi = next((header.index(n) for n in Q_NAMES if n in header), None)
    if di is None or qi is None:
        raise ForcingError(
            f"{obs_file}: header {split(lines[0])} must have a date column (one of "
            f"{DATE_NAMES}) and a discharge column in m3/s (one of {Q_NAMES})")
    seen = {}
    for ln in lines[1:]:
        parts = split(ln)
        if len(parts) <= max(di, qi):
            continue
        m = re.match(r"^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", parts[di])
        if not m:
            continue
        try:
            day = np.datetime64(f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-"
                                f"{int(m.group(3)):02d}")
        except ValueError:
            continue
        try:
            q = float(parts[qi])
        except ValueError:
            q = float("nan")
        if not np.isfinite(q) or q < 0:
            q = float("nan")
        seen.setdefault(day, q)
    if not seen:
        raise ForcingError(f"{obs_file}: no row with a readable date (YYYY-M-D)")
    days = np.array(sorted(seen))
    return days, np.array([seen[d] for d in days], dtype=float)


def build_obs_rvt(obs_file, subbasin_id=1, obs_start=None, obs_end=None):
    """Text of the :ObservationData file plus its facts. Raises ForcingError."""
    days, vals = read_gauge_table(obs_file)
    valid_days = days[np.isfinite(vals)]
    if valid_days.size == 0:
        raise ForcingError(f"{obs_file}: no valid discharge value at all")
    d0 = np.datetime64(obs_start, "D") if obs_start else valid_days[0]
    d1 = np.datetime64(obs_end, "D") if obs_end else valid_days[-1]
    if d1 < d0:
        raise ForcingError(f"observation window ends ({d1}) before it starts ({d0})")
    window = np.arange(d0, d1 + np.timedelta64(1, "D"), np.timedelta64(1, "D"))
    series = np.full(window.size, np.nan)
    sel = (days >= d0) & (days <= d1)
    series[(days[sel] - d0).astype(int)] = vals[sel]
    n_valid = int(np.isfinite(series).sum())
    if n_valid == 0:
        # an all-missing record makes Raven report -9999 diagnostics (dt_011)
        raise ForcingError(
            f"{obs_file}: no valid discharge between {d0} and {d1} (the record has valid "
            f"values from {valid_days[0]} to {valid_days[-1]}). Nothing written.")
    lines = [f"# Observed discharge from {os.path.basename(obs_file)} -- m3/s, daily",
             f"# Missing values written as {RAVEN_MISSING} (Raven blank marker)",
             f":ObservationData HYDROGRAPH {int(subbasin_id)} m3/s",
             f"  {d0} 00:00:00 1.0 {window.size}"]
    lines += [f"  {v:.3f}" if np.isfinite(v) else f"  {RAVEN_MISSING}" for v in series]
    lines += [":EndObservationData", ""]
    info = {"n_days": int(window.size), "n_valid": n_valid,
            "n_missing": int(window.size - n_valid), "period": [str(d0), str(d1)],
            "subbasin_id": int(subbasin_id), "unit": "m3/s",
            "mean_m3s": round(float(np.nanmean(series)), 3),
            "source_file": os.path.abspath(obs_file)}
    return "\n".join(lines), info


def write_obs_rvt(obs_file, out_path, subbasin_id=1, obs_start=None, obs_end=None):
    """Write the gauge table as a Raven :ObservationData file (for callers that
    need a second window, e.g. a calibration-only copy). Returns a status dict."""
    try:
        text, info = build_obs_rvt(obs_file, subbasin_id, obs_start, obs_end)
    except (ForcingError, OSError) as exc:
        return {"status": "error", "message": str(exc)}
    _write_all({out_path: text})
    return dict(info, status="success", output=out_path)


def _write_all(files):
    """Write every file or none: all go to temporary names first, then are
    renamed into place."""
    tmp = []
    try:
        for path, text in files.items():
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            t = f"{path}.tmp_{os.getpid()}"
            with open(t, "w") as f:
                f.write(text)
            tmp.append((t, path))
        for t, path in tmp:
            os.replace(t, path)
    finally:
        for t, _ in tmp:
            if os.path.exists(t):
                os.remove(t)


# ---------------------------------------------------------------------------

def process(args):
    """Read the forcing, check it, and only then write the files."""
    place = resolve_place(args)
    n_points = len(place["points"])
    if n_points > 1:
        print(f"[s3] {place['mode']}: {n_points} {args.forcing_source} points, "
              f"{args.start_year}-{args.end_year} (one shared pass per year)",
              file=sys.stderr, flush=True)

    daily, days = build_daily(args, place)
    check_time_axis(days, args.start_year, args.end_year, args.forcing_source)

    variables = written_variables(args.include_full_forcing)
    problems = bounds_check(daily, variables)
    precip_annual = daily[:, 0].sum() / max(1, len(daily) / 365.25)
    temp_mean = (daily[:, 1] + daily[:, 2]).mean() / 2.0
    if precip_annual > 5000:
        problems.append(f"annual precip = {precip_annual:.1f} mm — likely unit error "
                        f"(expected 200-3000 mm/yr)")
    if precip_annual < 10:
        problems.append(f"annual precip = {precip_annual:.1f} mm — likely unit error or "
                        f"missing data")
    if problems:
        raise ForcingError("forcing series not usable, nothing written:\n  - "
                           + "\n  - ".join(problems))

    w = np.asarray(place["weights"], dtype=float)
    mean_lat = float((np.array([p[0] for p in place["points"]]) * w).sum()) if n_points > 1 \
        else place["points"][0][0]
    mean_lon = float((np.array([p[1] for p in place["points"]]) * w).sum()) if n_points > 1 \
        else place["points"][0][1]
    start_date = f"{args.start_year}-01-01"

    # Generate .rvt content
    rvt_content = []
    rvt_content.append(f"# Raven .rvt file -- Forcing data for {args.basin_name}")
    rvt_content.append(f"# Generated by HydroCraft convert_forcing_to_rvt.py")
    rvt_content.append(f"# Source: {args.forcing_source} forcing, aggregated from {n_points} grid cells to basin mean")
    rvt_content.append(f"# Period: {args.start_year}-01-01 to {args.end_year}-12-31")
    rvt_content.append(f"# CRITICAL: Raven ignores units. All conversions done in this tool.")
    rvt_content.append(f"# Unit conversions applied:")
    rvt_content.append(f"#   PRECIP: -> mm/d")
    rvt_content.append(f"#   TEMP: degC")
    rvt_content.append(f"#   SHORTWAVE: W/m2 -> MJ/m2/d (x 0.0864)")
    rvt_content.append(f"#   PRESSURE: -> kPa")
    rvt_content.append(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    rvt_content.append("")

    gauge_block = generate_rvt_gauge_block(
        station_name=f"{args.basin_name}_mean",
        lat=mean_lat, lon=mean_lon, elev=place["gauge_elev"],
        daily_data=daily, start_date=start_date,
        variables=variables,
    )
    rvt_content.append(gauge_block)

    rvt_path = os.path.join(args.output_dir, f"{args.basin_name}.rvt")
    obs_path = os.path.join(args.output_dir, f"{args.basin_name}_obs.rvt")
    summary_path = os.path.join(args.output_dir, f"{args.basin_name}_forcing_summary.json")
    files = {}

    # Observed discharge: the file the main .rvt redirects to
    obs_info = None
    if args.obs_file:
        obs_text, obs_info = build_obs_rvt(
            args.obs_file, args.obs_subbasin_id,
            args.obs_start_date or start_date,
            args.obs_end_date or f"{args.end_year}-12-31")
        obs_info["output"] = obs_path
        rvt_content.append(f"# Observed discharge for calibration/validation")
        rvt_content.append(f":RedirectToFile {args.basin_name}_obs.rvt")
        rvt_content.append("")
        files[obs_path] = obs_text
    files[rvt_path] = "\n".join(rvt_content)

    by_year = {}
    yrs = days.astype("datetime64[Y]").astype(int) + 1970
    for y in range(args.start_year, args.end_year + 1):
        by_year[str(y)] = round(float(daily[yrs == y, 0].sum()), 1)

    results = {
        "status": "success",
        "output_rvt": rvt_path,
        "summary_json": summary_path,
        "source": args.forcing_source,
        "forcing_dir": args.forcing_dir,
        "via": "ki_tools_common.load_forcing." + (
            "load_daily_forcing" if n_points == 1 else "load_daily_forcing_points"),
        "mode": place["mode"],
        "n_points": n_points,
        "weighting": place["weighting"],
        "points_lat_min_max": place["points_lat_min_max"],
        "points_lon_min_max": place["points_lon_min_max"],
        "gauge_lat_lon": [round(mean_lat, 4), round(mean_lon, 4)],
        "gauge_elev_m": round(place["gauge_elev"], 1),
        "gauge_elev_source": place["gauge_elev_source"],
        "period": [start_date, f"{args.end_year}-12-31"],
        "forcing_stats": {
            "grid_cells_used": n_points,
            "total_cells_found": n_points,
            "daily_records": len(daily),
            "start_date": start_date,
            "end_date": f"{args.end_year}-12-31",
            "variables_included": variables,
            "mean_annual_precip_mm": round(float(precip_annual), 1),
            "precip_mm_by_year": by_year,
            "mean_temp_C": round(float(temp_mean), 1),
            "precip_range_mm_d": [round(float(daily[:, 0].min()), 2),
                                  round(float(daily[:, 0].max()), 2)],
            "temp_range_C": [round(float(daily[:, 2].min()), 1),
                             round(float(daily[:, 1].max()), 1)],
        },
        "unit_conversions_applied": [
            "PRECIP: loader precip_mm is already mm in the day (no conversion here)",
            "TEMP: loader gives deg C (no conversion here)",
            "SW_RADIA: W/m2 -> MJ/m2/d (factor 0.0864)",
            "AIR_PRES: Pa -> kPa (divide by 1000)",
        ],
        "warnings": [],
    }
    if place.get("basin_shp"):
        results["basin_shp"] = place["basin_shp"]
    if place.get("points_csv"):
        results["points_csv"] = place["points_csv"]
    if obs_info:
        results["obs_rvt"] = dict(obs_info, status="success")
    files[summary_path] = json.dumps(results, indent=2, ensure_ascii=False)

    _write_all(files)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Build the Raven .rvt forcing file straight from a forcing source")
    parser.add_argument("--forcing_source", required=True, choices=SOURCES,
                        help="Forcing source, read through ki_tools_common.load_forcing. "
                             "There is no default: name the source.")
    parser.add_argument("--forcing_dir", default=None,
                        help="Root folder of the cmfd / mswx store (not used by nasa_power). "
                             "Without it the loader's own default store is used.")
    parser.add_argument("--lat", type=float, default=None,
                        help="Latitude of ONE forcing point (with --lon)")
    parser.add_argument("--lon", type=float, default=None, help="Longitude of ONE forcing point")
    parser.add_argument("--points_csv", default=None,
                        help="CSV with header and columns lat,lon: plain mean over these points")
    parser.add_argument("--basin_shp", default=None,
                        help="Basin polygon (shapefile / GeoJSON): cos(latitude)-weighted mean "
                             "over every source grid cell whose centre is inside it")
    parser.add_argument("--cmfd_elev_nc", default=CMFD_ELEV_NC,
                        help="CMFD elevation field on the forcing grid (cells for --basin_shp "
                             "and the gauge elevation when --gauge_elev is not given)")
    parser.add_argument("--gauge_elev", type=float, default=None,
                        help="Elevation (m) the series stands for, written as the gauge "
                             ":Elevation. cmfd: read from the store's elevation field when not "
                             "given. mswx / nasa_power: required.")
    parser.add_argument("--output_dir", required=True, help="Output directory for .rvt file")
    parser.add_argument("--basin_name", required=True, help="Basin name")
    parser.add_argument("--start_year", type=int, required=True, help="Start year")
    parser.add_argument("--end_year", type=int, required=True, help="End year")
    parser.add_argument("--include_full_forcing", action="store_true",
                        help="Include wind, radiation, pressure (not just P/T)")
    parser.add_argument("--obs_file", default=None,
                        help="Observed discharge table (header with a date column and a "
                             "discharge column in m3/s; negative = missing). Written as "
                             "<basin>_obs.rvt, which the main .rvt redirects to.")
    parser.add_argument("--obs_subbasin_id", type=int, default=1,
                        help="SubBasin ID of the gauge in the .rvh (default 1)")
    parser.add_argument("--obs_start_date", default=None,
                        help="First day of the observation file (YYYY-MM-DD; default: first "
                             "day of --start_year)")
    parser.add_argument("--obs_end_date", default=None,
                        help="Last day of the observation file (YYYY-MM-DD; default: last "
                             "day of --end_year)")

    args = parser.parse_args()

    validation = validate_inputs(args)
    if validation["status"] == "error":
        print(json.dumps(validation, indent=2))
        sys.exit(1)

    try:
        results = process(args)
    except ForcingError as e:
        print(json.dumps({"status": "error", "message": str(e), "files_written": []},
                         indent=2, ensure_ascii=False))
        sys.exit(2)
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "message": str(e), "files_written": [],
                          "traceback": traceback.format_exc()}))
        sys.exit(2)

    print(json.dumps(results, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
