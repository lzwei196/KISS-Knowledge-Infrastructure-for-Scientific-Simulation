#!/usr/bin/env python3
"""
extract_cmfd_points.py — Batch CMFD 3-hourly NetCDF -> one DSSAT .WTH per point,
in a SINGLE pass over the NetCDF store.

WHY THIS EXISTS
---------------
convert_cmfd_to_wth.py::read_cmfd_point() opens every monthly NetCDF file once
PER POINT. Measured on this platform: 17.5 min for 1 point x 17 years, so a
25-member gridded ensemble run serially costs ~7-9 h — and every one of those
opens re-reads the same files. This tool hoists the point indexing INSIDE the
already-open monthly dataset, so N points cost ONE read of the store
(~25 min for 25 points x 17 years).

The unit conversions are the SAME as read_cmfd_point() and are imported from
convert_cmfd_to_wth wherever possible so the two tools cannot drift:
    precip : kg/m2/s -> mm/day   (x10800 per 3-h step, summed over 8 steps)
    temp   : K -> degC           (-273.15; daily max/min over the 8 steps)
    srad   : W/m2 -> MJ/m2/day   (mean x 0.0864)
    wind   : m/s -> km/day       (mean x 86.4)

The .WTH writer is convert_cmfd_to_wth.write_wth() itself (not a copy), so the
header/TAV/AMP convention is identical to the single-point tool.

Usage:
    python extract_cmfd_points.py \
        --forcing_dir /mnt/disk1/Hydrocraft_server/data/forcing/Data_forcing_03hr_010deg \
        --points_csv members.csv \
        --start_year 2000 --end_year 2016 \
        --out_dir /tmp/grid/weather

points_csv columns (header required): station,lat,lon  [,elev]
  station : 4-char DSSAT station code (WSTA). Must be unique per point; the
            output file is <out_dir>/<STATION>0001.WTH so the FileX WSTA match
            in dssat_workdir_setup._preflight_check succeeds.

Exit codes: 0 = every requested point written; 1 = input error;
            2 = one or more points produced no data (names listed on stderr).
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_cmfd_to_wth import write_wth, _auto_elevation  # noqa: E402

CMFD_VARS = [
    ('Prec', 'prec'),
    ('Temp', 'temp'),
    ('SRad', 'srad'),
    ('Wind', 'wind'),
]


def _open_nc(path):
    """Open a NetCDF with whichever engine this env actually has.

    Mirrors convert_cmfd_to_wth.read_cmfd_point's engine fallback so the two
    tools behave identically across conda envs that ship only one backend.
    """
    import xarray as xr
    last = None
    for eng in ('h5netcdf', 'netcdf4', 'scipy', None):
        try:
            return xr.open_dataset(path, engine=eng) if eng else xr.open_dataset(path)
        except (ValueError, ImportError, OSError) as e:
            last = e
    raise RuntimeError(f"No NetCDF engine could open {path}: {last}")


def read_cmfd_points(forcing_dir, points, start_year, end_year, verbose=True):
    """Read CMFD for MANY points in one pass; aggregate each to daily.

    Parameters
    ----------
    forcing_dir : str
        CMFD root containing Prec/ Temp/ SRad/ Wind/ subdirectories.
    points : list of (name, lat, lon)
    start_year, end_year : int

    Returns
    -------
    dict {name: [ {date, srad, tmax, tmin, rain, wind}, ... ]}
    """
    forcing_dir = Path(forcing_dir)
    daily = {name: [] for name, _, _ in points}

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            # month_data[pattern] -> np.ndarray (n_steps, n_points)
            month_data = {}
            for subdir, pattern in CMFD_VARS:
                sd = forcing_dir / subdir
                nc_files = sorted(sd.glob(f"*{year}{month:02d}*")) if sd.exists() else []
                if not nc_files:
                    nc_files = sorted(forcing_dir.glob(f"*{pattern}*{year}{month:02d}*"))
                if not nc_files:
                    continue

                ds = _open_nc(nc_files[0])
                try:
                    dvar = [v for v in ds.data_vars if pattern in v.lower()] or list(ds.data_vars)
                    glats = ds['lat'].values if 'lat' in ds else ds['latitude'].values
                    glons = ds['lon'].values if 'lon' in ds else ds['longitude'].values
                    # ---- THE POINT OF THIS TOOL --------------------------
                    # Index EVERY member inside the one open dataset instead
                    # of re-opening the file per member.
                    lis = [int(np.argmin(np.abs(glats - lat))) for _, lat, _ in points]
                    los = [int(np.argmin(np.abs(glons - lon))) for _, _, lon in points]
                    arr = ds[dvar[0]].values  # (time, lat, lon)
                    month_data[pattern] = np.stack(
                        [arr[:, li, lo] for li, lo in zip(lis, los)], axis=1)
                finally:
                    ds.close()

            if 'prec' not in month_data:
                continue

            n_steps = month_data['prec'].shape[0]
            n_days = n_steps // 8

            for d in range(n_days):
                s, e = d * 8, (d + 1) * 8
                date = datetime(year, month, 1) + timedelta(days=d)

                rain = np.sum(month_data['prec'][s:e] * 10800, axis=0)

                if 'temp' in month_data:
                    tk = month_data['temp'][s:e]
                    tmax = np.max(tk, axis=0) - 273.15
                    tmin = np.min(tk, axis=0) - 273.15
                else:
                    tmax = np.full(len(points), 25.0)
                    tmin = np.full(len(points), 15.0)

                if 'srad' in month_data:
                    srad = np.mean(month_data['srad'][s:e], axis=0) * 0.0864
                else:
                    srad = np.full(len(points), 15.0)

                if 'wind' in month_data:
                    wind = np.mean(month_data['wind'][s:e], axis=0) * 86.4
                else:
                    wind = np.full(len(points), 150.0)

                for k, (name, _, _) in enumerate(points):
                    daily[name].append({
                        'date': date,
                        'srad': max(0.0, float(srad[k])),
                        'tmax': float(tmax[k]),
                        'tmin': float(tmin[k]),
                        'rain': max(0.0, float(rain[k])),
                        'wind': max(0.0, float(wind[k])),
                    })

        if verbose:
            n = len(daily[points[0][0]]) if points else 0
            print(f"  Year {year}: {n} cumulative days x {len(points)} points", flush=True)

    return daily


def read_points_csv(path):
    """Read station,lat,lon[,elev] rows. Returns [(station, lat, lon, elev)]."""
    pts = []
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            keys = {k.strip().lower(): k for k in row}
            if 'station' not in keys or 'lat' not in keys or 'lon' not in keys:
                raise ValueError(
                    f"{path}: points_csv needs columns station,lat,lon "
                    f"(got {list(row)})")
            station = str(row[keys['station']]).strip().upper()[:4]
            lat = float(row[keys['lat']])
            lon = float(row[keys['lon']])
            elev = float(row[keys['elev']]) if 'elev' in keys and row[keys['elev']] else -99.0
            pts.append((station, lat, lon, elev))
    names = [p[0] for p in pts]
    dups = sorted({n for n in names if names.count(n) > 1})
    if dups:
        raise ValueError(
            f"{path}: station codes must be unique in their first 4 chars "
            f"(DSSAT WSTA); duplicates: {dups}")
    return pts


def main():
    ap = argparse.ArgumentParser(
        description='Batch CMFD -> DSSAT .WTH, one pass over the NetCDF store')
    ap.add_argument('--forcing_dir', required=True,
                    help='CMFD root (with Prec/ Temp/ SRad/ Wind/ subdirs)')
    ap.add_argument('--points_csv', required=True,
                    help='CSV with header station,lat,lon[,elev]')
    ap.add_argument('--start_year', type=int, required=True)
    ap.add_argument('--end_year', type=int, required=True)
    ap.add_argument('--out_dir', required=True,
                    help='Directory to write <STATION>0001.WTH files into')
    ap.add_argument('--elev', type=float, default=-99.0,
                    help='Elevation (m) applied to every point that has no '
                         'per-row elev; -99 = look up from DEM')
    ap.add_argument('--resume', action='store_true',
                    help='Skip points whose .WTH already exists and is non-empty')
    a = ap.parse_args()

    try:
        pts = read_points_csv(a.points_csv)
    except (OSError, ValueError) as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.exit(1)
    if not pts:
        sys.stderr.write(f"ERROR: no points in {a.points_csv}\n")
        sys.exit(1)

    os.makedirs(a.out_dir, exist_ok=True)

    def out_path(station):
        return os.path.join(a.out_dir, f"{station}0001.WTH")

    todo = pts
    if a.resume:
        todo = [p for p in pts
                if not (os.path.isfile(out_path(p[0])) and os.path.getsize(out_path(p[0])) > 0)]
        skipped = len(pts) - len(todo)
        if skipped:
            print(f"--resume: {skipped}/{len(pts)} .WTH already present, skipping")
    if not todo:
        print("Nothing to do — every .WTH already present.")
        sys.exit(0)

    print(f"Extracting CMFD for {len(todo)} point(s), "
          f"{a.start_year}-{a.end_year}, in ONE pass over the store")
    daily = read_cmfd_points(a.forcing_dir, [(n, la, lo) for n, la, lo, _ in todo],
                             a.start_year, a.end_year)

    failed = []
    for station, lat, lon, elev in todo:
        recs = daily.get(station) or []
        if not recs:
            failed.append(station)
            sys.stderr.write(f"ERROR: no CMFD data extracted for {station} "
                             f"({lat}, {lon})\n")
            continue
        e = elev if elev > -99.0 else a.elev
        write_wth(recs, out_path(station), station, lat, lon, e)

    print(f"Wrote {len(todo) - len(failed)}/{len(todo)} .WTH files to {a.out_dir}")
    if failed:
        sys.stderr.write(f"FAILED points (no data): {failed}\n")
        sys.exit(2)


if __name__ == '__main__':
    main()
