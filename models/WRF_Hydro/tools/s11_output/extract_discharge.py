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
    n_errors = 0
    for i, fpath in enumerate(chrt_files):
        fname = fpath.name
        datestr = fname.split('.')[0]  # e.g., 198007010000
        try:
            dt = datetime.strptime(datestr, '%Y%m%d%H%M')
        except ValueError:
            n_errors += 1
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
        except Exception:
            n_errors += 1

        if (i + 1) % 1000 == 0:
            logger.info(f"  processed {i+1}/{len(chrt_files)} files...")

    if n_errors > 0:
        logger.warning(f"  {n_errors} files skipped due to errors")

    if not records:
        raise ValueError("No valid records extracted")

    df = pd.DataFrame(records).set_index('datetime')
    daily = df.resample('D').mean().dropna()
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
            sys.path.insert(0, '/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent')
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
