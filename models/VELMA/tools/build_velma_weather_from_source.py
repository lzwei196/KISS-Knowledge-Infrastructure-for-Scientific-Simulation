#!/usr/bin/env python3
"""Build the REAL VELMA engine's weather driver files from cmfd / mswx / nasa_power.

Output (the DefaultWeatherModel format of the official BlueRiver_Example):
  <out-dir>/<prefix>_Precip_<Y0>-<Y1>.csv       one value per row, no header, mm/day
  <out-dir>/<prefix>_Temperature_<Y0>-<Y1>.csv  one value per row, no header, mean air T in deg C
  <out-dir>/<prefix>_weather_<Y0>-<Y1>_dated.csv  date,precip_mm_d,tair_c (for checks / plots)
  <out-dir>/<prefix>_weather_<Y0>-<Y1>.provenance.json
Row 1 is <Y0>-01-01 and every day through <Y1>-12-31 is present (leap days
included), so set forcing_start = <Y0> in the configuration
(run_velma_engine.py --forcing-start <Y0>).

Data are read ONLY through ki_tools_common.load_forcing.load_daily_forcing at
--lat/--lon (nearest cell of the product). That loader returns precipitation
already in mm/day (MSWX: sum of the 8 mm/3h steps; CMFD: kg/m2/s x 86400) and
air temperature already in deg C. VELMA weather files are deg C: this tool
NEVER adds 273.15 (the Kelvin JSON of convert_forcing_to_velma.py belongs to
the Python surrogate only).

MSWX sits on an exfat disk that wedges under parallel reads, so this tool makes
the shared reader run one file at a time, and reads only P and Tair. Never run
two mswx builds at once. Each finished cmfd/mswx year is cached in
<out-dir>/_cache/ so a relaunch resumes instead of re-reading. A cached year is
reused only when its source, lat/lon, year, resolved store directory and the
size + mtime of that year's store files all still match; otherwise it is read
again. nasa_power is never cached (always fetched fresh).

Nothing is filled: a missing day or a NaN stops the tool (exit 3).
Exit codes: 0 ok; 2 bad arguments; 3 source data incomplete or implausible
(including a loader error, a loader result without dates/precip_mm/temp_mean_c,
or an unreadable store); 4 the driver files could not be written.
Every exit prints ONE JSON object on the last stdout line: {"status": "success", ...}
or {"status": "error", "exit_code": n, "error": "..."}. An unreadable cache file is
not an error: it is reported and the year is read again from the source.
"""

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import date, datetime, timezone

import numpy as np

for _cand in ["KISSPATH_KI_TOOLS_COMMON"]:
    if os.path.isdir(os.path.join(_cand, "ki_tools_common")) and _cand not in sys.path:
        sys.path.insert(0, _cand)

SOURCES = ("cmfd", "mswx", "nasa_power")
MSWX_VARIABLES = ("P", "Tair")
CMFD_BOX = {"lat": (15.0, 55.0), "lon": (70.0, 140.0)}


class ToolError(Exception):
    """An expected failure: printed as {"status": "error", ...} with this exit code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fail(code, message):
    raise ToolError(code, message)


class _SerialExecutor:
    """Stand-in for ProcessPoolExecutor that runs the tasks one after another.

    The shared MSWX reader fans its per-file reads out over processes; the MSWX
    store is on an exfat disk that wedges under parallel reads.
    """

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, *iterables):
        return [fn(*a) for a in zip(*iterables)]


def load_year(source, lat, lon, year, forcing_dir):
    from ki_tools_common.load_forcing import load_daily_forcing
    if source != "mswx":
        # variables= also limits the loader's completeness check to P and Tair
        return load_daily_forcing(source, lat, lon, year, year, forcing_dir=forcing_dir,
                                  variables=MSWX_VARIABLES)
    import concurrent.futures as cf
    saved = cf.ProcessPoolExecutor
    cf.ProcessPoolExecutor = _SerialExecutor
    try:
        return load_daily_forcing(source, lat, lon, year, year, forcing_dir=forcing_dir,
                                  variables=MSWX_VARIABLES)
    finally:
        cf.ProcessPoolExecutor = saved


def resolve_forcing_dir(source, forcing_dir):
    """The store directory the loader will really read (None for nasa_power)."""
    if source == "nasa_power":
        return None
    if not forcing_dir:
        from ki_tools_common.load_forcing import CMFD_DIR, MSWX_DIR
        forcing_dir = CMFD_DIR if source == "cmfd" else MSWX_DIR
    return os.path.realpath(forcing_dir)


def store_files_by_year(source, fdir, years):
    """{year: [(relpath, size, mtime_ns), ...]} for the .nc store files naming that year."""
    roots = [os.path.join(fdir, v) for v in MSWX_VARIABLES] if source == "mswx" else [fdir]
    found = {y: [] for y in years}
    for root in roots:
        for dirpath, _, names in os.walk(root):
            for name in names:
                if not name.endswith(".nc"):
                    continue
                for y in years:
                    if str(y) in name:
                        path = os.path.join(dirpath, name)
                        st = os.stat(path)
                        found[y].append((os.path.relpath(path, fdir), st.st_size, st.st_mtime_ns))
    return {y: sorted(v) for y, v in found.items()}


def year_identity(source, lat, lon, year, fdir, files):
    """What a cached year must match to be reused."""
    digest = hashlib.sha256(json.dumps(files).encode()).hexdigest()
    return {"source": source, "lat": lat, "lon": lon, "year": year, "forcing_dir": fdir,
            "n_store_files": len(files), "store_files_sha256": digest}


def _main():
    ap = argparse.ArgumentParser(
        description="Build VELMA engine weather drivers (P mm/day, T deg C) from cmfd/mswx/nasa_power.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--source", required=True, choices=SOURCES)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True, help="degrees east (west is negative)")
    ap.add_argument("--start-year", type=int, required=True)
    ap.add_argument("--end-year", type=int, required=True)
    ap.add_argument("--out-dir", required=True, help="Usually the VELMA input folder of the run")
    ap.add_argument("--prefix", required=True, help="File name prefix, e.g. WS10_MSWX")
    ap.add_argument("--forcing-dir", help="cmfd / mswx store root (loader default if omitted)")
    args = ap.parse_args()

    if args.end_year < args.start_year:
        fail(2, "end-year < start-year")
    if args.source == "cmfd" and not (CMFD_BOX["lat"][0] <= args.lat <= CMFD_BOX["lat"][1]
                                      and CMFD_BOX["lon"][0] <= args.lon <= CMFD_BOX["lon"][1]):
        fail(2, "cmfd covers China only; use mswx or nasa_power")

    fdir = resolve_forcing_dir(args.source, args.forcing_dir)
    if fdir is not None and not os.path.isdir(fdir):
        fail(2, f"forcing dir {fdir} does not exist")
    years_wanted = list(range(args.start_year, args.end_year + 1))
    try:
        store_files = store_files_by_year(args.source, fdir, years_wanted) if fdir else {}
    except OSError as exc:
        fail(3, f"cannot list the {args.source} store {fdir}: {exc}")
    cache = os.path.join(args.out_dir, "_cache")
    try:
        os.makedirs(cache, exist_ok=True)
    except OSError as exc:
        fail(2, f"cannot create --out-dir {args.out_dir}: {exc}")
    dates, prec, tair = [], [], []
    year_ids = {}
    for year in years_wanted:
        cpath = os.path.join(cache, f"{args.prefix}_{args.source}_{args.lat}_{args.lon}_{year}.npz")
        ident = None
        if fdir is not None:
            ident = year_identity(args.source, args.lat, args.lon, year, fdir, store_files[year])
        cached = False
        if ident is not None and os.path.isfile(cpath):
            try:
                with np.load(cpath) as z:
                    if "identity" in z.files and json.loads(str(z["identity"])) == ident:
                        d = np.asarray(z["dates"]).astype("datetime64[D]")
                        p = np.asarray(z["precip_mm"], dtype=float)
                        t = np.asarray(z["temp_mean_c"], dtype=float)
                        cached = True
                        print(f"{year}: cached", flush=True)
                    else:
                        print(f"{year}: cache does not match this source/store, reading again", flush=True)
            except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile) as exc:
                print(f"{year}: cache file unreadable ({exc}), reading again", flush=True)
        if not cached:
            try:
                out = load_year(args.source, args.lat, args.lon, year, fdir)
            except Exception as exc:  # loader / store / network failure -> documented exit 3
                fail(3, f"{year}: loading {args.source} failed: {type(exc).__name__}: {exc}")
            missing = [k for k in ("dates", "precip_mm", "temp_mean_c")
                       if not isinstance(out, dict) or k not in out]
            if missing:
                fail(3, f"{year}: loader result lacks {missing}")
            try:
                d = np.asarray(out["dates"]).astype("datetime64[D]")
                p = np.asarray(out["precip_mm"], dtype=float)
                t = np.asarray(out["temp_mean_c"], dtype=float)
            except (TypeError, ValueError) as exc:
                fail(3, f"{year}: loader result is not a dated numeric series: {exc}")
            if ident is not None:
                try:
                    np.savez(cpath + ".tmp.npz", dates=d, precip_mm=p, temp_mean_c=t,
                             identity=np.array(json.dumps(ident)))
                    os.replace(cpath + ".tmp.npz", cpath)
                except OSError as exc:  # cache is only a speed-up; never fatal
                    print(f"{year}: could not write cache ({exc})", flush=True)
            print(f"{year}: read P {np.nansum(p):.0f} mm, T mean {np.nanmean(t):.2f} C", flush=True)
        year_ids[year] = dict(ident or {"source": args.source, "year": year,
                                        "fetched_utc": datetime.now(timezone.utc).isoformat()},
                              from_cache=cached)
        if not (len(p) == len(t) == len(d)):
            fail(3, f"{year}: {len(d)} dates but {len(p)} precip and {len(t)} tair values")
        ndays = (date(year + 1, 1, 1) - date(year, 1, 1)).days
        expect = np.arange(np.datetime64(f"{year}-01-01"), np.datetime64(f"{year + 1}-01-01"))
        if len(d) != ndays or not np.array_equal(d.astype("datetime64[D]"), expect):
            fail(3, f"{year}: {len(d)} days, expected {ndays}")
        bad = ~np.isfinite(p) | ~np.isfinite(t)
        if bad.any():
            fail(3, f"{year}: {int(bad.sum())} missing days, first {d[bad][:3]}")
        dates.append(d)
        prec.append(p)
        tair.append(t)
    d = np.concatenate(dates)
    p = np.concatenate(prec)
    t = np.concatenate(tair)
    if p.min() < 0 or p.max() > 1000:
        fail(3, f"precip {p.min():.2f}..{p.max():.2f} is not mm/day")
    if t.min() < -60 or t.max() > 50:
        fail(3, f"tair {t.min():.2f}..{t.max():.2f} is not deg C")

    tag = f"{args.start_year}-{args.end_year}"
    p_file = os.path.join(args.out_dir, f"{args.prefix}_Precip_{tag}.csv")
    t_file = os.path.join(args.out_dir, f"{args.prefix}_Temperature_{tag}.csv")
    dated = os.path.join(args.out_dir, f"{args.prefix}_weather_{tag}_dated.csv")
    try:
        write_outputs(args, d, p, t, fdir, year_ids, p_file, t_file, dated)
    except OSError as exc:
        fail(4, f"cannot write the driver files in {args.out_dir}: {exc}")
    return 0


def _write_atomic(path, lines):
    """Write to <path>.tmp, then rename: a failed write never leaves a short driver file."""
    with open(path + ".tmp", "w") as f:
        f.writelines(lines)
    os.replace(path + ".tmp", path)


def write_outputs(args, d, p, t, fdir, year_ids, p_file, t_file, dated):
    tag = f"{args.start_year}-{args.end_year}"
    _write_atomic(p_file, (f"{v:.4f}\n" for v in p))
    _write_atomic(t_file, (f"{v:.4f}\n" for v in t))
    _write_atomic(dated, ["date,precip_mm_d,tair_c\n"]
                  + [f"{dd},{pp:.4f},{tt:.4f}\n" for dd, pp, tt in zip(d.astype(str), p, t)])
    years = d.astype("datetime64[Y]").astype(int) + 1970
    annual_p = {int(y): round(float(p[years == y].sum()), 1) for y in np.unique(years)}
    prov = {
        "status": "success", "source": args.source, "lat": args.lat, "lon": args.lon,
        "reader": "ki_tools_common.load_forcing.load_daily_forcing (nearest cell)"
                  + ("; serial, P+Tair only" if args.source == "mswx" else ""),
        "forcing_dir": fdir if fdir is not None else "NASA POWER API (no local store, not cached)",
        "years": {str(y): v for y, v in year_ids.items()},
        "forcing_start": args.start_year, "forcing_end": args.end_year, "n_days": int(len(p)),
        "units": {"precip": "mm/day", "tair": "deg C (daily mean)"},
        "rain_file": p_file, "temp_file": t_file, "dated_csv": dated,
        "mean_annual_precip_mm": round(float(p.sum() / (len(p) / 365.25)), 1),
        "mean_tair_c": round(float(t.mean()), 2), "annual_precip_mm": annual_p,
    }
    _write_atomic(os.path.join(args.out_dir, f"{args.prefix}_weather_{tag}.provenance.json"),
                  [json.dumps(prov, indent=2)])
    print(json.dumps(prov))


def main():
    try:
        return _main()
    except ToolError as exc:
        print(json.dumps({"status": "error", "exit_code": exc.code, "error": str(exc)}))
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
