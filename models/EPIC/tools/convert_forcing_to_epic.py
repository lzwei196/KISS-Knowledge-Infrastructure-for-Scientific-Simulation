#!/usr/bin/env python3
"""Convert HydroCraft daily forcing (CMFD/NASA POWER/MSWX) to EPIC .DLY/.WP1/.WND.

EPIC .DLY format: (3I4, 6F6.x) YEAR MON DAY  SRAD TMAX TMIN PRCP RH WSPD
    SRAD  MJ m-2 day-1
    TMAX/TMIN  degC
    PRCP  mm
    RH    fraction (0-1)
    WSPD  m/s at 10 m
"""
import argparse
import glob
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import write_text_crlf, add_kdt_common_to_path

# EPIC needs a real diurnal range (TMX and TMN are separate .DLY columns and
# drive both heat-unit accumulation and PET), so the CMFD store MUST be the
# 3-HOURLY one — the daily CMFD product carries only a daily MEAN temperature
# and load_forcing then returns temp_max_c == temp_min_c == temp_mean_c. See
# triplet EPIC_023. The hc_ssd copy is the fast one but that disk auto-mounts
# under /media/server and can be absent after a reboot, so fall back to the
# disk1 original rather than dying (or, worse, silently taking a daily store).
_CMFD_DIR_CANDIDATES = [
    "/media/server/hc_ssd/forcing/Data_forcing_03hr_010deg",
    "/mnt/disk1/Hydrocraft_server/data/forcing/Data_forcing_03hr_010deg",
]
CMFD_DEFAULT_DIR = next((p for p in _CMFD_DIR_CANDIDATES if os.path.isdir(p)),
                        _CMFD_DIR_CANDIDATES[0])


def _load_cmfd_daily_point(forcing_dir, lat, lon, year1, year2):
    """Load CMFD 3-hourly NetCDFs at a single grid point and aggregate to
    daily. Returns canonical ki_tools_common keys so the rest of this tool
    shares one extraction path with NASA POWER / MSWX. Mirrors the contract
    of ki_tools_common.load_forcing._load_cmfd but works directly from the
    per-variable monthly NetCDFs, bypassing the (currently absent)
    load_cmfd_daily_all helper that _load_cmfd tries to import.
    """
    try:
        import numpy as np
        import xarray as xr
    except ImportError as exc:
        raise ImportError("xarray+numpy required for CMFD loading") from exc

    if not os.path.isdir(forcing_dir):
        raise FileNotFoundError(f"CMFD directory not found: {forcing_dir}")

    var_map = {
        "temp": ("Temp", "temp"),
        "prec": ("Prec", "prec"),
        "srad": ("SRad", "srad"),
        "wind": ("Wind", "wind"),
        "shum": ("SHum", "shum"),
        "pres": ("Pres", "pres"),
        "rhum": ("RHum", "rhum"),
    }

    out_dates = []
    out = {k: [] for k in (
        "precip_mm", "temp_mean_c", "temp_max_c", "temp_min_c",
        "srad_wm2", "wind_ms", "shum_kgkg", "pres_pa", "rh_frac",
    )}

    for year in range(year1, year2 + 1):
        for month in range(1, 13):
            month_series = {}
            month_times = None
            for key, (subdir, vname) in var_map.items():
                pattern = os.path.join(
                    forcing_dir, subdir, f"*{year}{month:02d}*.nc"
                )
                files = sorted(glob.glob(pattern))
                if not files:
                    continue
                ds = xr.open_dataset(files[0])
                actual_var = vname
                if actual_var not in ds.data_vars:
                    cand = [v for v in ds.data_vars if vname in v.lower()]
                    if not cand:
                        ds.close()
                        continue
                    actual_var = cand[0]
                lats = (
                    ds["lat"].values if "lat" in ds.coords
                    else ds["latitude"].values
                )
                lons = (
                    ds["lon"].values if "lon" in ds.coords
                    else ds["longitude"].values
                )
                li = int(np.argmin(np.abs(lats - lat)))
                lo = int(np.argmin(np.abs(lons - lon)))
                month_series[key] = ds[actual_var][:, li, lo].values.astype(float)
                if month_times is None and "time" in ds.variables:
                    month_times = ds["time"].values
                ds.close()

            if "temp" not in month_series or "prec" not in month_series:
                continue
            if month_times is None:
                continue

            times = np.asarray(month_times, dtype="datetime64[s]")
            days_np = times.astype("datetime64[D]")
            for day in np.unique(days_np):
                sel = days_np == day
                t = month_series["temp"][sel] - 273.15  # K -> C
                p = month_series["prec"][sel]           # kg m-2 s-1
                out_dates.append(day)
                out["temp_mean_c"].append(float(np.nanmean(t)))
                out["temp_max_c"].append(float(np.nanmax(t)))
                out["temp_min_c"].append(float(np.nanmin(t)))
                # rate kg m-2 s-1 x 86400 s/day = mm/day
                out["precip_mm"].append(
                    max(0.0, float(np.nanmean(p)) * 86400.0)
                )
                for raw_key, out_key in (
                    ("srad", "srad_wm2"),
                    ("wind", "wind_ms"),
                    ("shum", "shum_kgkg"),
                    ("pres", "pres_pa"),
                ):
                    if raw_key in month_series:
                        out[out_key].append(
                            float(np.nanmean(month_series[raw_key][sel]))
                        )
                    else:
                        out[out_key].append(float("nan"))
                if "rhum" in month_series:
                    # CMFD RHum is already in percent (0-100)
                    rh_pct = float(np.nanmean(month_series["rhum"][sel]))
                    out["rh_frac"].append(max(0.0, min(1.0, rh_pct / 100.0)))
                else:
                    out["rh_frac"].append(float("nan"))

    if not out_dates:
        raise FileNotFoundError(
            f"No CMFD data loaded from {forcing_dir} for "
            f"{year1}-{year2} at ({lat}, {lon})."
        )

    dates_py = [
        datetime.utcfromtimestamp(int(d.astype("datetime64[s]").astype("int64")))
        for d in out_dates
    ]
    return {
        "dates": dates_py,
        **{k: list(v) for k, v in out.items()},
    }


def _load_daily_window(source, lat, lon, year1, year2):
    """Single-shot extraction for [year1, year2] (no caching)."""
    add_kdt_common_to_path()
    forcing_dir = os.environ.get("CMFD_PATH", CMFD_DEFAULT_DIR) if source == "cmfd" else None
    try:
        from ki_tools_common.load_forcing import load_daily_forcing
        return load_daily_forcing(source, lat, lon, year1, year2, forcing_dir=forcing_dir)
    except (ImportError, FileNotFoundError):
        # Fall back to local CMFD loader if ki_tools_common path is broken
        if source == "cmfd":
            return _load_cmfd_daily_point(forcing_dir or CMFD_DEFAULT_DIR, lat, lon, year1, year2)
        raise


def _cache_path(cache_dir, source, lat, lon, year):
    return os.path.join(
        cache_dir, f"{source}_{lat:.4f}_{lon:.4f}_{year}.json")


def _load_year_cached(source, lat, lon, year, cache_dir):
    """Extract ONE year, memoised to a JSON file under `cache_dir`.

    Point extraction from the CMFD 3-hourly store costs ~2 min/year (7 vars x
    12 monthly NetCDFs), so a 20-year setup is ~40 min. Without a cache any
    interruption (or a relaunch of a detached run) redoes the whole fetch.
    Caching per YEAR makes the forcing stage resumable at year granularity.
    """
    import json
    path = _cache_path(cache_dir, source, lat, lon, year)
    if os.path.isfile(path):
        try:
            with open(path) as fh:
                raw = json.load(fh)
            dates = [datetime.strptime(d, "%Y-%m-%d") for d in raw.pop("dates")]
            if dates:
                print(f"  forcing cache hit: {year} ({len(dates)} days)")
                return {"dates": dates, **raw}
        except Exception:
            os.remove(path)  # corrupt/partial cache -> re-extract

    data = _load_daily_window(source, lat, lon, year, year)
    dates = []
    for d in data["dates"]:
        if hasattr(d, "year"):
            dates.append(d if isinstance(d, datetime)
                         else datetime(d.year, d.month, d.day))
        else:
            import numpy as np
            ts = (d - np.datetime64('1970-01-01T00:00:00')) / np.timedelta64(1, 's')
            dates.append(datetime.utcfromtimestamp(int(ts)))
    payload = {"dates": [d.strftime("%Y-%m-%d") for d in dates]}
    for k, v in data.items():
        if k == "dates" or not isinstance(v, (list, tuple)):
            continue
        if len(v) != len(dates):
            continue
        payload[k] = [None if (isinstance(x, float) and x != x) else float(x)
                      for x in v]
    os.makedirs(cache_dir, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)  # atomic: a killed run never leaves a half file
    return {"dates": dates,
            **{k: v for k, v in payload.items() if k != "dates"}}


def load_daily(source, lat, lon, year1, year2, cache_dir=None):
    """Load daily forcing for [year1, year2].

    With `cache_dir` set (the default when called from build()), the
    extraction runs YEAR BY YEAR and each year is memoised, so a re-run
    resumes instead of restarting. Without it, behaviour is the previous
    single-shot call.
    """
    if not cache_dir:
        return _load_daily_window(source, lat, lon, year1, year2)

    years = []
    for y in range(year1, year2 + 1):
        years.append(_load_year_cached(source, lat, lon, y, cache_dir))

    # Keep only variables present in EVERY year, so merged lists stay aligned
    # with `dates` and a variable missing from one year cannot shift the rest.
    keys = None
    for yd in years:
        ks = {k for k in yd if k != "dates"}
        keys = ks if keys is None else (keys & ks)
    merged = {"dates": []}
    for k in sorted(keys or []):
        merged[k] = []
    for yd in years:
        merged["dates"].extend(yd["dates"])
        for k in merged:
            if k != "dates":
                merged[k].extend(
                    [float("nan") if v is None else v for v in yd[k]])
    return merged


def _validate_ranges(tmax, tmin, prcp, srad):
    def mean(a):
        return sum(a) / len(a) if a else 0.0
    m_tmax, m_tmin, m_prcp, m_srad = mean(tmax), mean(tmin), mean(prcp), mean(srad)
    print(f"  forcing sanity: Tmax={m_tmax:.1f}C Tmin={m_tmin:.1f}C "
          f"prcp={m_prcp:.2f}mm/day srad={m_srad:.1f}MJ/m2/d")
    bad = []
    if not (-30 < m_tmax < 50):
        bad.append(f"Tmax mean {m_tmax:.1f}C out of range")
    if not (-40 < m_tmin < 40):
        bad.append(f"Tmin mean {m_tmin:.1f}C out of range")
    if not (0 <= m_prcp < 30):
        bad.append(f"Precip mean {m_prcp:.2f}mm/day out of range")
    if not (0 <= m_srad < 45):
        bad.append(f"SRAD mean {m_srad:.1f} MJ/m2/d out of range")
    if bad:
        raise ValueError("Forcing validation FAILED: " + "; ".join(bad))


def write_dly(path, dates, srad, tmax, tmin, prcp, rh, wspd):
    lines = []
    for i, d in enumerate(dates):
        y, m, dy = d.year, d.month, d.day
        lines.append(
            f"{y:>6d}{m:>4d}{dy:>4d}"
            f"{srad[i]:>6.1f}{tmax[i]:>6.2f}{tmin[i]:>6.2f}"
            f"{prcp[i]:>6.2f}{rh[i]:>6.2f}{wspd[i]:>6.2f}"
        )
    write_text_crlf(path, "\r\n".join(lines))


def monthly_mean(values, months, m):
    vs = [v for v, mm in zip(values, months) if mm == m]
    return sum(vs) / len(vs) if vs else 0.0


def monthly_std(values, months, m):
    vs = [v for v, mm in zip(values, months) if mm == m]
    if len(vs) < 2:
        return 0.0
    mu = sum(vs) / len(vs)
    return (sum((v - mu) ** 2 for v in vs) / (len(vs) - 1)) ** 0.5


def write_wp1(path, title, lat, lon, elev, dates, tmax, tmin, prcp, srad, rh, wspd):
    months = [d.month for d in dates]
    n_years = max(1, len(set(d.year for d in dates)))
    days_per_mo = {m: sum(1 for mm in months if mm == m) / n_years for m in range(1, 13)}

    def row12(fn, fmt="{:>10.2f}"):
        return "".join(fmt.format(fn(m)) for m in range(1, 13))

    rows = []
    rows.append(f"{title[:72]:<72}")
    rows.append(f"  LATT = {lat:6.2f} LONG = {abs(lon):6.2f} ELEV = {elev:6.1f}"
                f" TP5 .5H =   50.0 TP6 6.H =  100.0")
    rows.append(row12(lambda m: monthly_mean(tmax, months, m)))
    rows.append(row12(lambda m: monthly_mean(tmin, months, m)))
    rows.append(row12(lambda m: monthly_std(tmax, months, m)))
    rows.append(row12(lambda m: monthly_std(tmin, months, m)))
    rows.append(row12(lambda m: monthly_mean(prcp, months, m) * days_per_mo.get(m, 30)))
    rows.append(row12(lambda m: monthly_std(prcp, months, m)))
    rows.append(row12(lambda m: 0.0))
    rows.append(row12(lambda m: 0.3))
    rows.append(row12(lambda m: 0.5))
    rows.append(row12(lambda m: days_per_mo.get(m, 30) * 0.3))
    rows.append(row12(lambda m: 20.0))
    rows.append(row12(lambda m: monthly_mean(srad, months, m)))
    rows.append(row12(lambda m: monthly_mean(rh, months, m)))
    rows.append(row12(lambda m: monthly_mean(wspd, months, m)))

    write_text_crlf(path, "\r\n".join(rows))


def write_wnd(path, title, dates, wspd):
    months = [d.month for d in dates]

    def row12(fn):
        return "".join(f"{fn(m):>10.2f}" for m in range(1, 13))

    rows = [f"{title[:40]:<40}", "     .00     .00"]
    rows.append(row12(lambda m: monthly_mean(wspd, months, m)))
    for _ in range(16):
        rows.append(row12(lambda m: 8.0))
    write_text_crlf(path, "\r\n".join(rows))


def _pick(data, *keys, default=None):
    """Return the first key present in `data`, else `default`."""
    for k in keys:
        if k in data and data[k] is not None:
            return data[k]
    return default


def _rh_from_shum(shum, tmean_c, pres_pa):
    """Approximate RH (0-1) from specific humidity using Magnus for es."""
    import math
    out = []
    for q, t, p in zip(shum, tmean_c, pres_pa):
        if any(v is None or (isinstance(v, float) and v != v) for v in (q, t, p)):
            out.append(0.7)
            continue
        es = 611.2 * math.exp(17.67 * t / (t + 243.5))  # Pa
        e = q * p / (0.622 + 0.378 * q)                  # Pa
        out.append(max(0.01, min(0.99, e / es)))
    return out


def build(source, lat, lon, year1, year2, workspace, stn, cache_dir=None):
    os.makedirs(workspace, exist_ok=True)
    # Per-year memoisation lives beside the workspace by default so re-running
    # a workspace (or resuming a killed detached run) skips already-extracted
    # years. Override with $EPIC_FORCING_CACHE or cache_dir=False to disable.
    if cache_dir is None:
        cache_dir = os.environ.get(
            "EPIC_FORCING_CACHE", os.path.join(workspace, ".forcing_cache"))
    print(f"  loading {source} daily forcing {year1}..{year2} at ({lat:.3f},{lon:.3f})")
    data = load_daily(source, lat, lon, year1, year2,
                      cache_dir=cache_dir or None)

    raw_dates = list(data["dates"])
    dates = []
    for d in raw_dates:
        if hasattr(d, 'year'):
            dates.append(d)
        else:
            import numpy as np
            ts = (d - np.datetime64('1970-01-01T00:00:00')) / np.timedelta64(1, 's')
            dates.append(datetime.utcfromtimestamp(int(ts)))
    n = len(dates)

    # ki_tools_common canonical keys (matching NASA POWER / MSWX / CMFD):
    #   precip_mm, temp_max_c, temp_min_c, temp_mean_c, srad_wm2,
    #   wind_ms, shum_kgkg, pres_pa, (optional) rh_frac
    tmax = list(_pick(data, "temp_max_c", "tmax", default=[0.0] * n))
    tmin = list(_pick(data, "temp_min_c", "tmin", default=[0.0] * n))
    tmean = list(_pick(
        data, "temp_mean_c",
        default=[(a + b) * 0.5 for a, b in zip(tmax, tmin)]
    ))
    prcp = list(_pick(data, "precip_mm", "prcp", default=[0.0] * n))

    # GUARD (triplet EPIC_023): a forcing store that carries only a daily MEAN
    # temperature returns temp_max_c == temp_min_c, which reaches EPIC as a
    # zero diurnal range. That is not a crash — EPIC runs happily and silently
    # produces wrong heat-unit accumulation (hence wrong PHU/HUSC/maturity) and
    # wrong PET. The CMFD *daily* store (Data_forcing_01dy_010deg) does exactly
    # this; the 3-hourly store is the one that yields a real TMX/TMN. Fail loud
    # rather than write a physically impossible .DLY.
    if n:
        n_flat = sum(1 for a, b in zip(tmax, tmin) if abs(a - b) < 0.01)
        if n_flat > 0.9 * n:
            raise ValueError(
                f"{source} forcing has a ZERO diurnal temperature range on "
                f"{n_flat}/{n} days (temp_max_c == temp_min_c). EPIC needs a "
                f"real TMX/TMN. This is the signature of a DAILY-MEAN store: "
                f"for CMFD point $CMFD_PATH / CMFD_DEFAULT_DIR at the 3-HOURLY "
                f"archive (Data_forcing_03hr_010deg), not Data_forcing_01dy_"
                f"010deg. See diagnostics/triplets.yaml EPIC_023.")

    # Radiation: canonical is srad_wm2 (W/m2) -> convert to MJ/m2/day via
    # *0.0864. Legacy "srad" / "rad" keys may already be MJ/m2/day; detect
    # by magnitude (>60 means it's W/m2).
    srad_raw = list(_pick(data, "srad_wm2", "srad", "rad", default=[18.0] * n))
    m_rad = sum(srad_raw) / max(1, len(srad_raw))
    srad = [v * 0.0864 for v in srad_raw] if m_rad > 60 else srad_raw

    wspd = list(_pick(data, "wind_ms", "wind", default=[3.0] * n))

    rh_raw = _pick(data, "rh_frac", "rh", default=None)
    if rh_raw is not None:
        rh = [max(0.01, min(0.99, v if v <= 1.0 else v / 100.0)) for v in rh_raw]
    else:
        shum = _pick(data, "shum_kgkg", default=None)
        pres = _pick(data, "pres_pa", default=None)
        if shum is not None and pres is not None:
            rh = _rh_from_shum(list(shum), tmean, list(pres))
        else:
            rh = [0.7] * n

    for i in range(n):
        if tmin[i] > tmax[i]:
            tmin[i], tmax[i] = tmax[i], tmin[i]

    _validate_ranges(tmax, tmin, prcp, srad)

    dly = os.path.join(workspace, f"{stn}.DLY")
    wp1 = os.path.join(workspace, f"{stn}.WP1")
    wnd = os.path.join(workspace, f"{stn}.WND")
    write_dly(dly, dates, srad, tmax, tmin, prcp, rh, wspd)
    write_wp1(wp1, f"{source.upper()} at {lat:.2f},{lon:.2f}", lat, lon, 100.0,
              dates, tmax, tmin, prcp, srad, rh, wspd)
    write_wnd(wnd, f"{source.upper()} wind at {lat:.2f},{lon:.2f}", dates, wspd)
    print(f"  wrote {dly}, {wp1}, {wnd}  ({len(dates)} days)")
    return dly, wp1, wnd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["cmfd", "nasa_power", "mswx"], required=True)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--stn", default="EPICSTN")
    args = ap.parse_args()

    try:
        build(args.source, args.lat, args.lon, args.start, args.end,
              args.workspace, args.stn)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
