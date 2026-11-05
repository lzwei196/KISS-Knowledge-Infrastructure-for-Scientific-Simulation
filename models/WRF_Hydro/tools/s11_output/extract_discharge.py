#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      extract_discharge
Stage:        s11_output
Model:        WRF-Hydro
Description:  Extract daily discharge from CHRTOUT files at the outlet.

Reads hourly CHRTOUT_DOMAIN1 NetCDF files, identifies the outlet feature
(highest streamflow), aggregates to daily mean, and outputs a standard
date,Q_sim CSV for validation.

Usage:
    python extract_discharge.py \
        --run_dir outputs/bengbu_wrfhydro_1980_1990 \
        --output_csv revalidation/WRF_Hydro/bengbu/discharge_sim.csv

    # With explicit outlet feature index:
    python extract_discharge.py \
        --run_dir outputs/wangjiaba_wrfhydro_025deg_1980_1990 \
        --outlet_idx 23 \
        --output_csv discharge_sim.csv

    # With obs comparison and metrics:
    python extract_discharge.py \
        --run_dir outputs/bengbu_wrfhydro_1980_1990 \
        --obs_csv data/obs/BB/51080_bengbu.txt \
        --output_csv discharge_comparison.csv

Exit codes: 0=success, 1=input error, 2=processing error
"""

import argparse
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

try:
    from netCDF4 import Dataset as nc4_Dataset
    USE_NC4 = True
except ImportError:
    import xarray as xr
    USE_NC4 = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def find_outlet_feature(run_dir, pattern="*.CHRTOUT_DOMAIN1"):
    """
    Auto-detect outlet feature index by finding the feature with
    maximum streamflow in a summer CHRTOUT file.
    """
    run_dir = Path(run_dir)
    chrt_files = sorted(run_dir.glob(pattern))
    if not chrt_files:
        # Try CHRTOUT_GRID1
        chrt_files = sorted(run_dir.glob("*.CHRTOUT_GRID1"))
    if not chrt_files:
        raise FileNotFoundError(f"No CHRTOUT files in {run_dir}")

    # Pick a summer file from the SECOND year for robust outlet detection
    # (first year may be spinup with all zeros)
    summer_file = None
    first_year = chrt_files[0].name[:4]
    for f in chrt_files:
        yr = f.name[:4]
        month_str = f.name[4:6]
        if yr != first_year and month_str in ('06', '07', '08'):
            summer_file = f
            break
    # Fallback: any file from second half of the run
    if summer_file is None:
        summer_file = chrt_files[min(len(chrt_files) - 1, len(chrt_files) * 3 // 4)]

    if USE_NC4:
        ds = nc4_Dataset(str(summer_file), 'r')
        Q = ds.variables['streamflow'][:]
        fids = ds.variables['feature_id'][:] if 'feature_id' in ds.variables else np.arange(len(Q))
        ds.close()
    else:
        ds = xr.open_dataset(summer_file)
        Q = ds['streamflow'].values.ravel()
        fids = ds['feature_id'].values if 'feature_id' in ds else np.arange(len(Q))
        ds.close()

    idx = int(np.nanargmax(Q))
    logger.info(f"Outlet detection: feature_id={fids[idx]}, idx={idx}, "
                f"Q={float(Q[idx]):.1f} m3/s (from {summer_file.name})")
    return idx


def find_gauge_feature(run_dir, gauge_lat, gauge_lon, min_order=1,
                       pattern="*.CHRTOUT_DOMAIN1"):
    """
    Select the CHRTOUT feature CLOSEST to the gauge coordinates, restricted to
    Strahler order >= min_order so the search cannot snap onto a headwater
    tributary. This is the correct extraction when a gauge location is known
    (SKILL.md 'How to Correctly Extract Discharge'): with gridded diffusive-wave
    routing every channel cell on the lower main stem carries nearly the same
    discharge and argmax(streamflow) wanders km along the stem, whereas the
    gauge-matched cell is stable and physically at the gauge.
    """
    run_dir = Path(run_dir)
    files = sorted(run_dir.glob(pattern)) or sorted(run_dir.glob("*.CHRTOUT_GRID1"))
    if not files:
        raise FileNotFoundError(f"No CHRTOUT files in {run_dir}")
    f = files[min(len(files) - 1, len(files) // 2)]

    if USE_NC4:
        ds = nc4_Dataset(str(f), 'r')
        lat = np.asarray(ds.variables['latitude'][:]).ravel()
        lon = np.asarray(ds.variables['longitude'][:]).ravel()
        order = (np.asarray(ds.variables['order'][:]).ravel()
                 if 'order' in ds.variables else np.full(lat.shape, min_order))
        ds.close()
    else:
        ds = xr.open_dataset(f)
        lat = ds['latitude'].values.ravel()
        lon = ds['longitude'].values.ravel()
        order = (ds['order'].values.ravel()
                 if 'order' in ds else np.full(lat.shape, min_order))
        ds.close()

    # --- FLOW GUARD (Berounka/Tangnaihai): on a coarse routing grid the channel
    # cell nearest the gauge can be a disconnected order-1/2 stub carrying ZERO
    # discharge; distance-only selection then returns an all-zero series
    # (sim_mean=0, r=NaN, pbias=-100). Require the chosen feature to carry flow.
    # Sample mean streamflow over non-spinup files.
    first_year = files[0].name[:4]
    sample = [g for g in files if g.name[:4] != first_year] or files
    sample = sample[:: max(1, len(sample) // 15)][:15]
    qsum = np.zeros(lat.shape, dtype=float); nq = 0
    for g in sample:
        try:
            if USE_NC4:
                dsg = nc4_Dataset(str(g), 'r')
                qg = np.asarray(dsg.variables['streamflow'][:]).ravel().astype(float)
                dsg.close()
            else:
                dsg = xr.open_dataset(g)
                qg = dsg['streamflow'].values.ravel().astype(float); dsg.close()
            qg = np.where(np.isfinite(qg) & (qg > 0), qg, 0.0)
            qsum = qsum + qg; nq += 1
        except Exception:
            continue
    meanq = qsum / max(nq, 1)
    flow_min = max(1e-3, 1e-3 * float(np.nanmax(meanq)))
    has_flow = meanq > flow_min

    elig = np.where((order >= min_order) & has_flow)[0]
    if elig.size == 0:
        logger.warning(f"No flow-carrying feature with order>={min_order} "
                       f"(max order present={int(np.nanmax(order))}); relaxing order filter")
        elig = np.where(has_flow)[0]
    if elig.size == 0:
        logger.warning("No feature carries flow; falling back to nearest of all features")
        elig = np.arange(lat.size)

    R = 6371.0  # km
    dlat = np.radians(lat[elig] - gauge_lat)
    dlon = np.radians(lon[elig] - gauge_lon)
    a = (np.sin(dlat / 2.0) ** 2 +
         np.cos(np.radians(gauge_lat)) * np.cos(np.radians(lat[elig])) *
         np.sin(dlon / 2.0) ** 2)
    dist = 2.0 * R * np.arcsin(np.sqrt(a))
    k = int(elig[int(np.argmin(dist))])
    logger.info(f"Gauge match: idx={k}, order={int(order[k])} (>= {min_order}), "
                f"dist={float(dist.min()):.2f} km, lat={lat[k]:.4f} lon={lon[k]:.4f}")
    return k


def _run_span(run_dir):
    """(first, last, step, t0_output) of the run's CHRTOUT output times: start
    time and KHOUR (or KDAY) from namelist.hrldas, output interval out_dt
    (minutes) and t0OutputFlag from hydro.namelist. The model writes one CHRTOUT
    every out_dt from the start time to start + KHOUR; the file AT the start time
    is written only when t0OutputFlag = 1 (the model default, module_namelist.F:
    t0OutputFlag = 1; module_HYDRO_drv.F: "if(nlst(did)%t0OutputFlag .eq. 0)
    return" at the initial / restart time)."""
    import re
    from datetime import timedelta
    def read(name):
        f = Path(run_dir) / name
        if not f.is_file():
            raise ValueError(f"{f} not found: cannot tell which CHRTOUT times the run "
                             f"must have, so a missing output step would go unseen")
        return f, re.sub(r"!.*", "", f.read_text(errors="replace"))
    def val(txt, key):
        m = re.search(rf"^\s*{key}\s*=\s*(-?\d+)", txt, re.M | re.I)
        return int(m.group(1)) if m else None
    nl, txt = read("namelist.hrldas")
    y, mo, d, h = (val(txt, k) for k in ("START_YEAR", "START_MONTH", "START_DAY", "START_HOUR"))
    if None in (y, mo, d):
        raise ValueError(f"{nl}: START_YEAR/MONTH/DAY not found")
    t0 = datetime(y, mo, d, h or 0, val(txt, "START_MIN") or 0)
    khour, kday = val(txt, "KHOUR"), val(txt, "KDAY")
    if khour is not None and khour > 0:
        t1 = t0 + timedelta(hours=khour)
    elif kday is not None and kday > 0:
        t1 = t0 + timedelta(days=kday)
    else:
        raise ValueError(f"{nl}: neither KHOUR nor KDAY > 0 found")
    hn, htxt = read("hydro.namelist")
    out_dt = val(htxt, "out_dt")
    if not out_dt or out_dt <= 0:
        raise ValueError(f"{hn}: out_dt (minutes) not found")
    flag = val(htxt, "t0OutputFlag")
    if flag is None:
        flag = 1            # WRF-Hydro default when the key is absent
    if flag not in (0, 1):
        raise ValueError(f"{hn}: t0OutputFlag = {flag}; WRF-Hydro accepts only 0 or 1")
    return t0, t1, timedelta(minutes=out_dt), flag == 1


def extract_daily_discharge(run_dir, feature_idx, pattern="*.CHRTOUT_DOMAIN1",
                            start_year=None, end_year=None):
    """
    Read all CHRTOUT files, extract streamflow at feature_idx,
    aggregate sub-daily to daily mean.

    Uses netCDF4 for speed (avoids xarray overhead per file).
    """
    run_dir = Path(run_dir)
    chrt_files = sorted(run_dir.glob(pattern))
    if not chrt_files:
        chrt_files = sorted(run_dir.glob("*.CHRTOUT_GRID1"))
    if not chrt_files:
        raise FileNotFoundError(f"No CHRTOUT files in {run_dir}")

    logger.info(f"Reading {len(chrt_files)} CHRTOUT files...")

    records = []
    bad = []           # (file, reason): any unreadable output stops the run
    for i, fpath in enumerate(chrt_files):
        fname = fpath.name
        datestr = fname.split('.')[0]  # e.g., 198007010000
        try:
            dt = datetime.strptime(datestr, '%Y%m%d%H%M')
        except ValueError:
            bad.append((fname, "file name is not YYYYMMDDHHMM.*"))
            continue

        if start_year and dt.year < start_year:
            continue
        if end_year and dt.year > end_year:
            continue

        try:
            if USE_NC4:
                ds = nc4_Dataset(str(fpath), 'r')
                q = float(ds.variables['streamflow'][feature_idx])
                ds.close()
            else:
                ds = xr.open_dataset(fpath)
                q = float(ds['streamflow'].values.ravel()[feature_idx])
                ds.close()
            records.append({'datetime': dt, 'Q_sim': q})
        except Exception as exc:
            bad.append((fname, f"{type(exc).__name__}: {exc}"))

        if (i + 1) % 1000 == 0:
            logger.info(f"  processed {i+1}/{len(chrt_files)} files...")

    if bad:
        raise ValueError(
            f"{len(bad)} CHRTOUT file(s) in {run_dir} could not be read; a series "
            f"with those steps left out would be scored as if complete. First: "
            + "; ".join(f"{f} ({why})" for f, why in bad[:5]))

    if not records:
        raise ValueError("No valid records extracted")

    df = pd.DataFrame(records).set_index('datetime')
    # Every output time of the run (inside start_year..end_year) must be there,
    # no more and no fewer: a missing step, also at either end, would otherwise
    # vanish into a daily mean or a shorter series.
    t0, t1, step, t0_output = _run_span(run_dir)
    want = pd.date_range(t0, t1, freq=step)
    if not t0_output:       # t0OutputFlag = 0: no output file at the start time
        want = want[want != pd.Timestamp(t0)]
    if start_year:
        want = want[want.year >= start_year]
    if end_year:
        want = want[want.year <= end_year]
    have = pd.DatetimeIndex(df.index)
    missing, extra = want.difference(have), have.difference(want)
    if len(missing) or len(extra) or have.has_duplicates:
        raise ValueError(
            f"CHRTOUT times in {run_dir} do not match the run (namelist.hrldas + "
            f"hydro.namelist: {t0}..{t1} every {step}): {len(missing)} missing "
            f"{[str(t) for t in missing[:5]]}, {len(extra)} extra {[str(t) for t in extra[:5]]}"
            + (", duplicate times" if have.has_duplicates else ""))
    # A single NaN / masked / inf step would vanish into the daily mean (pandas
    # skips NaN), so every output step must hold a finite value.
    bad_q = df.index[~np.isfinite(df['Q_sim'].to_numpy(dtype=float))]
    if len(bad_q):
        raise ValueError(
            f"{len(bad_q)} CHRTOUT step(s) in {run_dir} have a non-finite streamflow at "
            f"feature {feature_idx}; a daily mean would hide them. First: "
            f"{[str(x) for x in bad_q[:5]]}")
    daily = df.resample('D').mean()
    gaps = daily.index[daily['Q_sim'].isna()]
    if len(gaps):
        raise ValueError(
            f"{len(gaps)} day(s) between {daily.index[0].date()} and "
            f"{daily.index[-1].date()} have no readable CHRTOUT value "
            f"(missing file or NaN streamflow), first: "
            f"{[str(d.date()) for d in gaps[:5]]}")
    daily.index.name = 'date'

    logger.info(f"Extracted {len(daily)} daily values "
                f"({daily.index[0].strftime('%Y-%m-%d')} to {daily.index[-1].strftime('%Y-%m-%d')})")
    return daily


def load_obs(obs_path):
    """Load HydroCraft-format observed discharge (tab-separated, columns: stcd dates z Q name)."""
    df = pd.read_csv(obs_path, sep='\t', encoding='utf-8', encoding_errors='replace')
    df['date'] = pd.to_datetime(df['dates'])
    df = df.set_index('date')[['Q']].astype(float)
    df = df[df['Q'] > 0]
    df = df.rename(columns={'Q': 'Q_obs'})
    return df


def main():
    parser = argparse.ArgumentParser(
        description='Extract daily discharge from WRF-Hydro CHRTOUT files')
    parser.add_argument('--run_dir', required=True, help='Directory with CHRTOUT files')
    parser.add_argument('--output_csv', required=True, help='Output CSV path (date, Q_sim)')
    parser.add_argument('--outlet_idx', type=int, default=None,
                        help='Outlet feature index (auto-detected if omitted)')
    parser.add_argument('--gauge_lat', type=float, default=None,
                        help='Gauge latitude; select nearest feature (with --min_order)')
    parser.add_argument('--gauge_lon', type=float, default=None,
                        help='Gauge longitude; select nearest feature (with --min_order)')
    parser.add_argument('--min_order', type=int, default=1,
                        help='Minimum Strahler order for gauge-matched feature selection')
    parser.add_argument('--obs_csv', default=None,
                        help='Observed discharge file for comparison (HydroCraft format)')
    parser.add_argument('--start_year', type=int, default=None)
    parser.add_argument('--end_year', type=int, default=None)
    parser.add_argument('--metrics_json', default=None,
                        help='Output path for metrics JSON')
    args = parser.parse_args()

    run_dir = Path(args.run_dir)

    # Find outlet
    if args.outlet_idx is not None:
        outlet_idx = args.outlet_idx
    elif args.gauge_lat is not None and args.gauge_lon is not None:
        outlet_idx = find_gauge_feature(run_dir, args.gauge_lat, args.gauge_lon,
                                        min_order=args.min_order)
    else:
        outlet_idx = find_outlet_feature(run_dir)

    # Extract
    daily = extract_daily_discharge(run_dir, outlet_idx,
                                     start_year=args.start_year,
                                     end_year=args.end_year)

    # Save
    out_path = Path(args.output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.obs_csv:
        obs = load_obs(args.obs_csv)
        merged = obs.join(daily, how='inner').dropna()
        merged.to_csv(out_path)
        logger.info(f"Saved comparison CSV ({len(merged)} days): {out_path}")

        # Compute metrics
        if len(merged) >= 30:
            sys.path.insert(0, 'KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent')
            from ki_tools_common.metrics import all_metrics
            m = all_metrics(merged['Q_obs'].values, merged['Q_sim'].values)
            print(f"r={m['r']:.4f}, NSE={m['NSE']:.4f}, KGE={m['KGE']:.4f}, PBIAS={m['PBIAS']:.2f}%")
            if args.metrics_json:
                Path(args.metrics_json).parent.mkdir(parents=True, exist_ok=True)
                with open(args.metrics_json, 'w') as f:
                    json.dump(m, f, indent=2)
    else:
        daily.to_csv(out_path)
        logger.info(f"Saved discharge CSV ({len(daily)} days): {out_path}")


if __name__ == '__main__':
    main()
