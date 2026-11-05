#!/usr/bin/env python3
"""
convert_forcing_to_bgc.py
Build the BIOME-BGC daily meteorological file straight from a data source.

BIOME-BGC met file format (MTCLIM 4.x compatible):
  year  yday  Tmax(C)  Tmin(C)  Tday(C)  prcp(cm)  VPD(Pa)  srad(W/m2)  daylen(s)

CRITICAL UNIT CONVERSIONS:
  - Precipitation: mm -> cm (divide by 10!) [dt_007]
  - VPD: Must be in Pa (not kPa!) [dt_008]
  - Temperature: Must be in Celsius (not Kelvin!) [dt_010]
  - Day length: Must be computed from latitude + DOY [dt_009]
  - Shortwave: BIOME-BGC wants the DAYLIGHT-average flux (metv.swavgfd), not the
    24-h mean that every daily forcing product carries -> x 86400/daylen [dt_027]

Sources (--source is required, there is no default):
  cmfd | mswx | nasa_power   gridded/point product read through the shared loader
                             ki_tools_common.load_forcing.load_daily_forcing at
                             --lat/--lon (cmfd: China only; mswx: global store,
                             read ONE file at a time; nasa_power: network).
                             VPD comes from the source's specific humidity AND the
                             source's own surface pressure. Nothing is filled: a
                             missing or non-finite value, an uneven time axis or a
                             period the source does not fully cover stops the tool
                             and nothing is written [dt_028-dt_033].
  fluxnet                    FLUXNET2015 tower file (FULLSET_DD.csv, with the
                             sibling FULLSET_HH.csv required by default).
                             DD proxies require explicit --fluxnet_daily_only.

Usage:
    python convert_forcing_to_bgc.py --source nasa_power \\
        --lat 55.4859 --lon 11.6446 --start_year 2004 --end_year 2012 \\
        --output metdata/site.mtc43
    python convert_forcing_to_bgc.py --source cmfd --forcing_dir <CMFD dir> \\
        --lat 32.43 --lon 115.60 --start_year 2010 --end_year 2012 \\
        --output metdata/site.mtc43
    python convert_forcing_to_bgc.py --source fluxnet \\
        --forcing_file <site>/FULLSET_DD.csv \\
        --lat 55.4859 --start_year 2004 --end_year 2012 --output metdata/site.mtc43

All sources also write <output>.summary.json with source and conversion provenance.
FLUXNET provider gap-filled fields are used as supplied; no additional filling.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import argparse
import math
from pathlib import Path

LIB_DIR = os.path.join(os.path.dirname(__file__), '..', 'lib')
sys.path.insert(0, LIB_DIR)
from bgc_utils import (compute_daylength, compute_vpd_from_tmin_tmax_q,
                        compute_tday, mm_to_cm, kelvin_to_celsius)


DIRECT_SOURCES = ("cmfd", "mswx", "nasa_power")
# CMFD is a China product; the shared loader takes the nearest cell with no
# domain check, so a point outside the grid would silently get an edge cell.
CMFD_BOX = {"lat": (15.0, 55.0), "lon": (70.0, 140.0)}
# MSWX variables this tool needs (LWd and Wind are not read: one year of one
# variable is a whole-file decompression).
MSWX_VARIABLES = ("P", "Tair", "SWd", "spechum", "Pres")


class _SerialExecutor:
    """Stand-in for ProcessPoolExecutor that runs the tasks one after another.

    The shared MSWX reader fans its per-file reads out over processes. The MSWX
    store sits on an exfat disk that wedges under parallel reads, so this tool
    makes that reader run ONE file at a time (dt_033).
    """

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, *iterables):
        return [fn(*a) for a in zip(*iterables)]


def _load_daily(source, lat, lon, start_year, end_year, forcing_dir):
    """Call the shared loader (the only place weather is read from a product)."""
    from ki_tools_common.load_forcing import load_daily_forcing
    if source != "mswx":
        return load_daily_forcing(source, lat, lon, start_year, end_year,
                                  forcing_dir=forcing_dir)
    import concurrent.futures as cf
    saved = cf.ProcessPoolExecutor
    cf.ProcessPoolExecutor = _SerialExecutor
    try:
        return load_daily_forcing(source, lat, lon, start_year, end_year,
                                  forcing_dir=forcing_dir, variables=MSWX_VARIABLES)
    finally:
        cf.ProcessPoolExecutor = saved


def read_direct_forcing(source: str, lat: float, lon: float, start_year: int,
                        end_year: int, forcing_dir=None):
    """
    Read daily weather for one point from cmfd / mswx / nasa_power through the
    shared loader and return (records, meta) for convert_to_bgc_met.

    Loader fields used: dates, temp_max_c, temp_min_c, temp_mean_c, precip_mm
    (mm in the day), srad_wm2 (24-h mean), shum_kgkg, pres_pa.

    Nothing is filled or clipped. ValueError is raised (and the caller writes
    nothing) when
      - the time axis is not exactly one value per calendar day from 1 Jan
        start_year to 31 Dec end_year (short period, gap, repeat, uneven step);
      - any needed value is missing or not finite;
      - a value is outside the physical range of its unit (wrong unit upstream).
    Feb-29 is dropped afterwards: the model reads exactly 365 lines per year.
    """
    import numpy as np
    import pandas as pd

    if start_year > end_year:
        raise ValueError(f"start_year {start_year} is after end_year {end_year}")
    if source == "cmfd":
        (la0, la1), (lo0, lo1) = CMFD_BOX["lat"], CMFD_BOX["lon"]
        if not (la0 <= lat <= la1 and lo0 <= lon <= lo1):
            raise ValueError(
                f"point ({lat}, {lon}) is outside the CMFD grid "
                f"({la0}-{la1} N, {lo0}-{lo1} E); use mswx or nasa_power")

    d = _load_daily(source, lat, lon, start_year, end_year, forcing_dir)

    need = ["temp_max_c", "temp_min_c", "precip_mm", "srad_wm2", "shum_kgkg", "pres_pa"]
    absent = [k for k in ["dates"] + need if k not in d or d[k] is None]
    if absent:
        raise ValueError(f"{source} loader returned no {absent}")

    dates = pd.DatetimeIndex(pd.to_datetime(list(d["dates"])))
    expected = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")
    if len(dates) == 0:
        raise ValueError(f"{source} returned no days for {start_year}-{end_year}")
    if (dates != dates.normalize()).any():
        raise ValueError(f"{source} time axis is not daily (sub-daily stamps present)")
    if len(dates) != len(expected) or not (dates == expected).all():
        steps = sorted({int(x) for x in np.diff(dates.values).astype("timedelta64[D]").astype(int)}) \
            if len(dates) > 1 else []
        lost = expected.difference(dates)
        raise ValueError(
            f"{source} does not give one value per day for {start_year}-01-01.."
            f"{end_year}-12-31: got {len(dates)} days ({dates[0].date()}..{dates[-1].date()}, "
            f"steps in days {steps}), expected {len(expected)}; "
            f"{len(lost)} day(s) not covered"
            + (f", first {lost[0].date()}" if len(lost) else ""))

    col = {}
    for k in need:
        a = np.asarray(d[k], dtype=float)
        if a.shape != (len(expected),):
            raise ValueError(f"{source} {k}: {a.size} values for {len(expected)} days")
        bad = ~np.isfinite(a)
        if bad.any():
            raise ValueError(
                f"{source} {k}: {int(bad.sum())} missing/non-finite value(s), first on "
                f"{expected[int(np.argmax(bad))].date()}; nothing is filled, pick another "
                f"source or period")
        col[k] = a

    def _range(k, lo, hi, unit):
        a = col[k]
        if a.min() < lo or a.max() > hi:
            i = int(np.argmax((a < lo) | (a > hi)))
            raise ValueError(
                f"{source} {k} = {a[i]:.6g} on {expected[i].date()} is outside "
                f"{lo}..{hi} {unit}: wrong unit or bad value in the source")

    _range("temp_max_c", -90.0, 60.0, "deg C")
    _range("temp_min_c", -90.0, 60.0, "deg C")
    _range("precip_mm", 0.0, 2000.0, "mm/day")
    _range("srad_wm2", 0.0, 500.0, "W/m2 (24-h mean)")
    _range("shum_kgkg", 1e-6, 0.05, "kg/kg")
    _range("pres_pa", 30000.0, 110000.0, "Pa")
    swapped = col["temp_max_c"] < col["temp_min_c"]
    if swapped.any():
        raise ValueError(
            f"{source}: Tmax < Tmin on {int(swapped.sum())} day(s), first "
            f"{expected[int(np.argmax(swapped))].date()}")

    tmean = np.asarray(d.get("temp_mean_c", []), dtype=float)
    if tmean.shape == (len(expected),) and np.isfinite(tmean).all():
        tmean_basis = "loader temp_mean_c"
    else:
        tmean = 0.5 * (col["temp_max_c"] + col["temp_min_c"])
        tmean_basis = "(Tmax+Tmin)/2 (loader gave no finite daily mean)"

    keep = ~((expected.month == 2) & (expected.day == 29))
    leap_prec = float(col["precip_mm"][~keep].sum())
    records = []
    yday = 0
    for i in np.nonzero(keep)[0]:
        day = expected[i]
        yday = 1 if (day.month == 1 and day.day == 1) else yday + 1   # 1..365
        records.append({
            "year": int(day.year), "yday": yday,
            "tmax": float(col["temp_max_c"][i]), "tmin": float(col["temp_min_c"][i]),
            "prec_mm": float(col["precip_mm"][i]), "q": float(col["shum_kgkg"][i]),
            "pres_pa": float(col["pres_pa"][i]), "srad": float(col["srad_wm2"][i]),
        })
    n_years = end_year - start_year + 1
    meta = {
        "source": source, "lat": lat, "lon": lon,
        "forcing_dir": forcing_dir,
        "n_days_from_source": int(len(expected)),
        "n_leap_days_dropped": int((~keep).sum()),
        "leap_day_precip_dropped_mm": round(leap_prec, 3),
        "mean_temperature_c": round(float(tmean[keep].mean()), 3),
        "mean_temperature_basis": tmean_basis,
        "mean_pressure_pa": round(float(col["pres_pa"][keep].mean()), 1),
        "vpd_basis": "es(Tday) - ea(source specific humidity, source surface pressure), Pa",
    }
    return records, meta


def convert_to_bgc_met(daily_records, lat, srad_is_daylight_avg=False):
    """
    Convert daily records to BIOME-BGC met format lines.

    CRITICAL CONVERSIONS:
    - prec: mm -> cm (divide by 10)
    - VPD: computed in Pa from q and T
    - Tday: approximated as Tmin + 0.45*(Tmax-Tmin)
    - daylen: computed from latitude and yday (seconds)
    - srad: BIOME-BGC's met column 8 is metv.swavgfd, the DAYLIGHT-AVERAGE
      shortwave flux density (bgc_struct.h; users guide "met file" item 8;
      MTCLIM output). CMFD/MSWX/NASA POWER/FLUXNET daily radiation is a
      24-h mean, so it is scaled by 86400/daylen here (same daily energy,
      spread over the daylight period). Feeding the 24-h mean under-forces
      photosynthesis by ~1.5x in summer and ~3x in winter at mid-latitudes
      (dt_027). Pass srad_is_daylight_avg=True ONLY for MTCLIM-style input.
    """
    met_lines = []

    for r in daily_records:
        tmax = r["tmax"]
        tmin = r["tmin"]
        tday = compute_tday(tmin, tmax)

        # CRITICAL: precipitation in cm, NOT mm
        prcp_cm = mm_to_cm(r["prec_mm"])

        # CRITICAL: VPD in Pa, NOT kPa
        # For FLUXNET input, vpd_hpa is already available (use directly × 100)
        # For cmfd/mswx/nasa_power, compute it from the day's specific humidity
        # and the SOURCE's surface pressure of that day (no fixed pressure).
        if "vpd_hpa" in r:
            vpd_pa = r["vpd_hpa"] * 100.0
        else:
            vpd_pa = compute_vpd_from_tmin_tmax_q(tmin, tmax, r["q"], r["pres_pa"])

        # CRITICAL: Day length in seconds, computed from latitude
        dayl = compute_daylength(lat, r["yday"])

        # CRITICAL: shortwave must be the DAYLIGHT average, not the 24-h mean.
        # Daily energy is conserved: W/m2 (24 h) * 86400 s / daylen s.
        srad = max(0.0, r["srad"])
        if not srad_is_daylight_avg and dayl > 0:
            srad = srad * 86400.0 / dayl

        met_lines.append(
            f"  {r['year']:4d}  {r['yday']:4d}"
            f"  {tmax:8.2f}  {tmin:8.2f}  {tday:8.2f}"
            f"  {prcp_cm:8.4f}  {vpd_pa:10.2f}"
            f"  {srad:9.2f}  {dayl:8.0f}"
        )

    return met_lines


def validate_output(met_lines, daily_records):
    """Post-generation validation checks."""
    warnings = []
    n = len(daily_records)

    # Check annual precipitation
    years = set(r["year"] for r in daily_records)
    for year in sorted(years):
        annual_prec_mm = sum(r["prec_mm"] for r in daily_records
                             if r["year"] == year)
        annual_prec_cm = annual_prec_mm / 10.0
        if annual_prec_cm > 300:
            warnings.append(
                f"Year {year}: annual precip = {annual_prec_cm:.0f} cm "
                f"({annual_prec_mm:.0f} mm). If > 3000 mm seems too high, "
                "check that input is in mm (not cm already)."
            )
        if annual_prec_cm < 5:
            warnings.append(
                f"Year {year}: annual precip = {annual_prec_cm:.1f} cm "
                f"({annual_prec_mm:.1f} mm). Very dry -- verify input units."
            )

    # Check temperature range
    tmax_all = [r["tmax"] for r in daily_records]
    tmin_all = [r["tmin"] for r in daily_records]
    if max(tmax_all) > 60:
        warnings.append(f"Max Tmax = {max(tmax_all):.1f} C -- may be in Kelvin?")
    if min(tmin_all) < -80:
        warnings.append(f"Min Tmin = {min(tmin_all):.1f} C -- unrealistic")
    if any(r["tmax"] < r["tmin"] for r in daily_records):
        warnings.append("Tmax < Tmin on some days -- columns swapped or proxies used?")

    # Check the written daylight-average shortwave (column 8): a daylight
    # average can never exceed the solar constant; > 1200 W/m2 means the
    # input was ALREADY a daylight average and got scaled twice.
    srad_out = [float(line.split()[7]) for line in met_lines]
    if srad_out and max(srad_out) > 1200:
        warnings.append(
            f"Max daylight-average srad = {max(srad_out):.0f} W/m2 (> 1200). "
            "Input was probably already a daylight average (MTCLIM-style); "
            "re-run with --srad_is_daylight_avg.")

    return warnings


FLUXNET_HH_COLS = ["TIMESTAMP_START", "TA_F", "P_F", "VPD_F", "SW_IN_F", "SW_IN_POT"]


def _fluxnet_hh_path(filepath: str):
    """Sibling FULLSET_HH.csv of a FULLSET_DD.csv (or the file itself if it is HH)."""
    p = Path(filepath)
    if "_HH" in p.name:
        return p
    cand = p.with_name(p.name.replace("_DD", "_HH"))
    return cand if cand.is_file() and cand != p else None


def read_fluxnet_forcing(filepath: str, start_year: int, end_year: int,
                         use_hh: bool = True):
    """
    Read FLUXNET2015 and return daily records for BIOME-BGC.

    BIOME-BGC's met columns are defined (bgc_users_guide, "met file") as the
    DAILY MAXIMUM / MINIMUM temperature, the DAYLIGHT-AVERAGE VPD and the
    DAYLIGHT-AVERAGE shortwave flux -- i.e. MTCLIM output. The half-hourly
    FULLSET_HH.csv shipped next to every FULLSET_DD.csv gives those exactly:
      TA_F      → Tmax = daily max, Tmin = daily min (°C)
      VPD_F     → VPD  = mean over daylight half-hours (SW_IN_POT > 0), hPa
      SW_IN_F   → 24-h mean W/m² (scaled to the daylight average later, dt_027)
      P_F       → mm per half-hour, summed to mm/day
    With explicit use_hh=False the daily file is used with PROXIES and the
    caller is told so in the returned meta. Missing HH does not switch paths:
      TA_F_MDS_DAY / TA_F_MDS_NIGHT → day/night MEANS standing in for Tmax/Tmin
      VPD_F (24-h mean)             → stands in for the daylight average
    Both paths require full calendar coverage and finite required values.
    Residual -9999/NaN gaps stop conversion, including missing HH samples before
    aggregation. Feb-29 is dropped only after validation (365-day model year).

    Returns (records, meta).
    """
    import numpy as np
    import pandas as pd
    if start_year > end_year:
        raise ValueError("start_year must not exceed end_year")
    hh_path = _fluxnet_hh_path(filepath) if use_hh else None
    if use_hh and hh_path is None:
        raise ValueError("FULLSET_HH.csv required for daily extrema/daylight VPD; "
                         "use --fluxnet_daily_only (API use_hh=False) only to explicitly accept DD proxies")
    source = hh_path if use_hh else Path(filepath)
    timestamp = "TIMESTAMP_START" if use_hh else "TIMESTAMP"
    required = (FLUXNET_HH_COLS[1:] if use_hh else
                ["TA_F_MDS_DAY", "TA_F_MDS_NIGHT", "P_F", "VPD_F", "SW_IN_F"])
    frame = pd.read_csv(source, dtype={timestamp: str},
                        usecols=lambda c: c in [timestamp] + required or c.endswith("_QC"))
    missing = [k for k in [timestamp] + required if k not in frame]
    if missing:
        raise ValueError(f"{source}: missing columns {missing}")
    try:
        stamps = pd.to_datetime(frame[timestamp], format="%Y%m%d%H%M" if use_hh else "%Y%m%d", errors="raise")
    except (ValueError, TypeError):
        raise ValueError(f"{source}: invalid {timestamp} timestamps") from None
    if stamps.isna().any():
        raise ValueError(f"{source}: missing {timestamp} timestamps")
    selected = (stamps.dt.year >= start_year) & (stamps.dt.year <= end_year)
    frame = frame.loc[selected].copy()
    stamps = pd.DatetimeIndex(stamps.loc[selected])
    freq = "30min" if use_hh else "D"
    stop = pd.Timestamp(end_year + 1, 1, 1)
    expected = pd.date_range(f"{start_year}-01-01", stop, freq=freq, inclusive="left")
    if not stamps.equals(expected):
        lost = expected.difference(stamps)
        first = str(lost[0]) if len(lost) else "none (duplicate/unordered timestamps)"
        raise ValueError(f"{source}: calendar coverage requires {len(expected)} ordered {freq} records; "
                         f"got {len(stamps)}, missing {len(lost)}, first {first}")
    frame.index = stamps
    for key in required:
        try:
            frame[key] = pd.to_numeric(frame[key], errors="raise").replace(-9999., np.nan)
        except (ValueError, TypeError):
            raise ValueError(f"{source}: {key} must be numeric") from None
        # Night VPD is not used by the daylight-average definition. All other
        # weather samples are required before any skip-NaN group reduction.
        if use_hh and key == "VPD_F":
            continue
        bad = ~np.isfinite(frame[key].to_numpy())
        if bad.any():
            raise ValueError(f"{source}: {key} missing/nonfinite at {stamps[np.flatnonzero(bad)[0]]}; no filling")
    qc = {k: {str(v): int(n) for v, n in frame[k].value_counts(dropna=False).items()}
          for k in frame if k.endswith("_QC")}
    meta = dict(fluxnet_source=str(source), product_variables=required,
                source_product="FLUXNET2015 _F fields as supplied (provider gap filling retained)",
                additional_gap_filling="none", qc_counts=qc,
                n_source_records=len(frame), source_frequency=freq,
                period=f"{start_year}-01-01..{end_year}-12-31")
    if use_hh:
        daylight = frame["SW_IN_POT"] > 0
        vpd = frame.loc[daylight, "VPD_F"]
        if not np.isfinite(vpd.to_numpy()).all():
            bad = vpd.index[~np.isfinite(vpd.to_numpy())][0]
            raise ValueError(f"{source}: VPD_F missing/nonfinite at daylight sample {bad}; no filling")
        for key in ("P_F", "SW_IN_POT"):
            if (frame[key] < 0).any():
                raise ValueError(f"{source}: {key} must be nonnegative")
        if (vpd < 0).any():
            raise ValueError(f"{source}: daylight VPD_F must be nonnegative")
        g = frame.groupby(frame.index.floor("D"))
        df = pd.DataFrame({"tmax": g["TA_F"].max(), "tmin": g["TA_F"].min(),
                           "prec_mm": g["P_F"].sum(), "srad": g["SW_IN_F"].mean(),
                           "vpd_hpa": vpd.groupby(vpd.index.floor("D")).mean()})
        meta.update(tmax_tmin_basis="daily max/min of complete half-hourly TA_F",
                    vpd_basis="mean of half-hourly VPD_F over daylight (SW_IN_POT>0)")
    else:
        df = frame.rename(columns={"TA_F_MDS_DAY": "tmax", "TA_F_MDS_NIGHT": "tmin",
                                   "P_F": "prec_mm", "VPD_F": "vpd_hpa", "SW_IN_F": "srad"})
        meta.update(tmax_tmin_basis="PROXY explicitly selected: TA_F_MDS_DAY/NIGHT day/night MEANS",
                    vpd_basis="PROXY explicitly selected: 24-h mean VPD_F")
    for key in ("tmax", "tmin", "prec_mm", "vpd_hpa", "srad"):
        bad = ~np.isfinite(df[key].to_numpy())
        if bad.any():
            raise ValueError(f"{source}: {key} undefined on {df.index[np.flatnonzero(bad)[0]]}; "
                             "complete required samples/daylight are needed")
    if (df["tmax"] < df["tmin"]).any():
        raise ValueError(f"{source}: Tmax below Tmin; DD proxies may not represent daily extrema")
    for key in ("prec_mm", "vpd_hpa", "srad"):
        if (df[key] < 0).any():
            raise ValueError(f"{source}: {key} must be nonnegative; no clipping")
    leap = (df.index.month == 2) & (df.index.day == 29)
    meta.update(n_leap_days_dropped=int(leap.sum()), leap_day_precip_dropped_mm=float(df.loc[leap,"prec_mm"].sum()))
    df = df.loc[~leap]
    # BIOME-BGC reads exactly 365 entries per year. Use the same contiguous
    # no-leap year-day convention as the direct-source route.
    records = []
    for day, row in df.iterrows():
        yday = 1 if day.month == 1 and day.day == 1 else yday + 1
        records.append({"year": int(day.year), "yday": yday,
                        **{k: float(row[k]) for k in ("tmax", "tmin", "prec_mm", "vpd_hpa", "srad")}})
    return records, meta


def _fail(code, stage, message):
    print(json.dumps({"status": "error", "stage": stage, "message": message}, indent=2))
    sys.exit(code)


def _stage(path: Path, text: str) -> str:
    """Write text to a unique temp file next to path; return the temp path."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp",
                               dir=str(path.parent))
    try:
        umask = os.umask(0); os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)   # same mode a plain open() would give
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return tmp


class PairWriteError(OSError):
    """The met/summary pair could not be written; message says what is on disk."""


def _write_pair(met_path: Path, met_text: str, summary_path: Path, summary_text: str):
    """Write the met file and its summary as one pair.

    Both are fully written to temp files first. Then the met file is put in
    place and the summary after it; if the summary step fails, the previous
    met file (if any) is put back, so an old summary never sits beside new
    data and a failed run never leaves a new met file without its summary.
    """
    import shutil
    import tempfile
    staged = []
    keep = None
    try:
        met_tmp = _stage(met_path, met_text); staged.append(met_tmp)
        sum_tmp = _stage(summary_path, summary_text); staged.append(sum_tmp)
        if met_path.exists():
            fd, keep = tempfile.mkstemp(
                prefix="." + met_path.name + ".", suffix=".prev", dir=str(met_path.parent))
            os.close(fd)
            shutil.copy2(met_path, keep)
        had_met = met_path.exists()
        os.replace(met_tmp, met_path); staged.remove(met_tmp)
        try:
            os.replace(sum_tmp, summary_path); staged.remove(sum_tmp)
        except BaseException as e:
            try:
                if had_met:
                    os.replace(keep, met_path); keep = None
                else:
                    os.unlink(met_path)
            except BaseException as e2:
                # Rollback failed: keep the copy of the old met file and say so.
                left, keep = keep, None
                raise PairWriteError(
                    f"summary not written ({e}) AND the met file could not be put back "
                    f"({e2}): {met_path} now holds NEW data and {summary_path} (if present) "
                    "is the OLD summary, so they do NOT match; "
                    + (f"the previous met file is saved at {left}"
                       if left else "there was no previous met file")) from e
            raise PairWriteError(
                f"summary not written ({e}); previous met file and summary kept"
                if had_met else f"summary not written ({e}); no files written") from e
    finally:
        for t in staged + ([keep] if keep else []):
            try:
                os.unlink(t)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="Build the BIOME-BGC met file from cmfd / mswx / nasa_power "
                    "(shared loader) or from a FLUXNET2015 tower file")
    parser.add_argument("--source", required=True,
                        choices=list(DIRECT_SOURCES) + ["fluxnet"],
                        help="Where the weather comes from (required, no default): "
                             "cmfd | mswx | nasa_power read at --lat/--lon through "
                             "ki_tools_common.load_forcing, or fluxnet (tower file)")
    parser.add_argument("--forcing_file", default=None,
                        help="fluxnet only: FLUXNET FULLSET_DD.csv")
    parser.add_argument("--forcing_dir", default=None,
                        help="cmfd / mswx only: root directory of the store "
                             "(default: the shared loader's own default)")
    parser.add_argument("--lat", type=float, required=True,
                        help="Site latitude (degrees)")
    parser.add_argument("--lon", type=float, default=None,
                        help="Site longitude (degrees east); required for cmfd/mswx/nasa_power")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--fluxnet_daily_only", action="store_true",
                        help="FLUXNET only: ignore the sibling FULLSET_HH.csv and use the "
                             "daily file's day/night-mean temperature and 24-h VPD PROXIES "
                             "(legacy behaviour; Tmax/Tmin/VPD no longer match the model's "
                             "definitions).")
    parser.add_argument("--srad_is_daylight_avg", action="store_true",
                        help="Set ONLY when the input shortwave is already a daylight "
                             "average (MTCLIM-style). By default the 24-h mean that "
                             "CMFD/MSWX/NASA POWER/FLUXNET daily data carry is "
                             "converted to BIOME-BGC's daylight average (x 86400/daylen).")
    parser.add_argument("--summary_json", default=None,
                        help="Where to write the source/conversion summary "
                             "(default: <output>.summary.json)")
    parser.add_argument("--output", required=True,
                        help="Output met file path")

    args = parser.parse_args()
    direct = args.source in DIRECT_SOURCES

    # Validate the point (NaN/inf pass argparse's float())
    if not (math.isfinite(args.lat) and -90.0 <= args.lat <= 90.0):
        _fail(1, "input_validation", f"--lat must be a finite number in [-90, 90], got {args.lat}")
    if args.lon is not None and not (math.isfinite(args.lon) and -180.0 <= args.lon <= 360.0):
        _fail(1, "input_validation", f"--lon must be a finite number in [-180, 360], got {args.lon}")

    # The met file and its summary must be two different files
    _out = Path(args.output)
    _sum = Path(args.summary_json or (str(_out) + ".summary.json"))
    if _out.resolve() == _sum.resolve() or (
            _out.exists() and _sum.exists() and os.path.samefile(_out, _sum)):
        _fail(1, "input_validation",
              f"--summary_json and --output name the same file ({_out}); nothing written")
    for _p in (_out, _sum):
        if _p.exists() and not _p.is_file():
            _fail(1, "input_validation", f"output path is not a regular file: {_p}")

    # Validate the inputs of the chosen source
    if direct:
        if args.lon is None:
            _fail(1, "input_validation", f"--lon is required for --source {args.source}")
        if args.forcing_file:
            _fail(1, "input_validation",
                  f"--forcing_file is not used by --source {args.source} "
                  "(the source is read at --lat/--lon; --forcing_dir names a cmfd/mswx store)")
        if args.srad_is_daylight_avg:
            _fail(1, "input_validation",
                  f"--srad_is_daylight_avg does not apply to --source {args.source}: "
                  "its shortwave is a 24-h mean")
        if args.forcing_dir and not os.path.isdir(args.forcing_dir):
            _fail(1, "input_validation", f"--forcing_dir not found: {args.forcing_dir}")
    else:
        if not args.forcing_file:
            _fail(1, "input_validation", "--forcing_file is required for --source fluxnet")
        if not os.path.isfile(args.forcing_file):
            _fail(1, "input_validation", f"Forcing file not found: {args.forcing_file}")

    # Never write over (or into) the weather we read. For FLUXNET this covers the
    # DD file and its sibling HH name (even if that file does not exist yet: a
    # summary written there would later be read as half-hourly data).
    def _same(a: Path, b: Path) -> bool:
        if a.resolve() == b.resolve():
            return True
        try:
            return a.exists() and b.exists() and os.path.samefile(a, b)
        except OSError:
            return False
    if direct:
        if args.forcing_dir:
            store = Path(args.forcing_dir).resolve()
            for _p in (_out, _sum):
                if _p.resolve() == store or store in _p.resolve().parents:
                    _fail(1, "input_validation",
                          f"output {_p} is inside the --forcing_dir store {store}; nothing written")
    else:
        dd = Path(args.forcing_file)
        inputs = [dd]
        if "_HH" in dd.name:
            inputs.append(dd)
        elif "_DD" in dd.name:
            inputs.append(dd.with_name(dd.name.replace("_DD", "_HH")))
        for _p in (_out, _sum):
            for _i in inputs:
                if _same(_p, _i):
                    _fail(1, "input_validation",
                          f"output {_p} is the FLUXNET input {_i}; nothing written")

    # Read
    source_meta = {}
    try:
        if direct:
            daily_records, source_meta = read_direct_forcing(
                args.source, args.lat, args.lon, args.start_year, args.end_year,
                forcing_dir=args.forcing_dir)
        else:
            daily_records, source_meta = read_fluxnet_forcing(
                args.forcing_file, args.start_year, args.end_year,
                use_hh=not args.fluxnet_daily_only)
    except Exception as e:
        _fail(2, "processing", f"Failed to read forcing ({args.source}): {e}; nothing written")

    if not daily_records:
        _fail(2, "processing", "No daily records after filtering by year range")

    # Convert
    try:
        met_lines = convert_to_bgc_met(daily_records, args.lat,
                                       srad_is_daylight_avg=args.srad_is_daylight_avg)
    except Exception as e:
        _fail(2, "processing", f"Conversion failed: {e}")

    # Validate output
    warnings = validate_output(met_lines, daily_records)

    years = sorted(set(r["year"] for r in daily_records))
    mean_annual_prec_mm = sum(r["prec_mm"] for r in daily_records) / len(years)

    # Write with MTCLIM-compatible header (4 lines; the model skips them)
    out_path = Path(args.output)
    if direct:
        origin = (f"Generated from {args.source} via ki_tools_common.load_forcing: "
                  f"lat={args.lat} lon={args.lon} {args.start_year}-{args.end_year}")
    else:
        # Until 2026-10-03 this line read "Generated from VIC forcing: ..." although the
        # file is a FLUXNET tower file (dt_030); corrected on the owner's decision.
        origin = f"Generated from FLUXNET tower file: {Path(args.forcing_file).name}"
    header_lines = [
        f"HydroCraft BIOME-BGC met file, lat={args.lat:.2f}",
        origin,
        f"  year  yday    Tmax    Tmin    Tday    prcp      VPD     srad  daylen",
        f"             (deg C) (deg C) (deg C)    (cm)     (Pa)  (W m-2)     (s)",
    ]
    summary_path = Path(args.summary_json or (str(out_path) + ".summary.json"))
    if direct:
        summary = {
            "source": args.source,
            "point": {"lat": args.lat, "lon": args.lon},
            "period": f"{args.start_year}-01-01..{args.end_year}-12-31",
            "n_years": len(years),
            "n_days_in_met_file": len(daily_records),
            "mean_annual_precip_mm": round(mean_annual_prec_mm, 2),
            "mean_temperature_c": source_meta["mean_temperature_c"],
            "mean_temperature_basis": source_meta["mean_temperature_basis"],
            "mean_pressure_pa": source_meta["mean_pressure_pa"],
            "n_leap_days_dropped": source_meta["n_leap_days_dropped"],
            "leap_day_precip_dropped_mm": source_meta["leap_day_precip_dropped_mm"],
            "note": "means are over the 365-day years written to the met file",
            "met_file": str(out_path),
        }
    else:
        summary = {"source": "fluxnet", **source_meta, "met_file": str(out_path),
                   "n_days_in_met_file": len(daily_records),
                   "mean_annual_precip_mm": round(mean_annual_prec_mm, 2)}
    try:
        _write_pair(out_path, "".join(l + "\n" for l in header_lines + met_lines),
                    summary_path, json.dumps(summary, indent=2) + "\n")
    except Exception as e:
        if isinstance(e, PairWriteError):
            _fail(3, "output", f"Failed to write: {e}")
        _fail(3, "output", f"Failed to write: {e}; nothing replaced, previous files (if any) kept")

    result = {
        "status": "success",
        "output_file": str(out_path),
        "n_days": len(daily_records),
        "n_years": len(years),
        "year_range": f"{years[0]}-{years[-1]}",
        "header_lines": len(header_lines),
        "latitude": args.lat,
        "mean_annual_precip_mm": round(mean_annual_prec_mm, 1),
        "mean_annual_precip_cm": round(mean_annual_prec_mm / 10.0, 1),
        "tmax_range": [round(min(r["tmax"] for r in daily_records), 1),
                       round(max(r["tmax"] for r in daily_records), 1)],
        "srad_basis": ("daylight average, input used as given"
                       if args.srad_is_daylight_avg else
                       "daylight average, converted from 24-h mean (x 86400/daylen)"),
        **source_meta,
        "srad_daylight_avg_range_Wm2": [
            round(min(float(l.split()[7]) for l in met_lines), 1),
            round(max(float(l.split()[7]) for l in met_lines), 1)],
        "warnings": warnings,
    }
    result["summary_json"] = str(summary_path)
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
