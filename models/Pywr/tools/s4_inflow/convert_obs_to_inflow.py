#!/usr/bin/env python3
"""
convert_obs_to_inflow.py — Convert observed discharge data to Pywr reservoir inflow.

Use this when VIC output is not available (e.g., for a new basin) and observed
discharge data exists. Reads HydroCraft-standard obs format (stcd|dates|z|Q|name)
and outputs a Pywr-compatible inflow CSV.

For cases where the observation station drainage area differs from the dam's
upstream area, applies area-scaling:
    Q_dam = Q_obs * (dam_upstream_area / station_drainage_area)

Handles:
  - Tab-separated and comma-separated obs files
  - Missing data flags (-99, -9999, NaN)
  - GBK and UTF-8 file encodings
  - Date gap filling (interpolation or zero-fill)

Usage:
    python convert_obs_to_inflow.py \
        --obs_file data/obs/WJB/HUAIH-51030-wangjiaba.txt \
        --station_area_km2 30630 \
        --dam_area_km2 1094 \
        --start_date 1981-01-01 --end_date 1990-12-31 \
        --output outputs/pywr_run/inflow.csv

Output:
    CSV with columns: date, inflow_m3s
"""

import argparse
import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime


def read_obs_discharge(obs_file):
    """Read HydroCraft-standard observed discharge file.

    Tries multiple encodings and separators to handle Chinese station data.
    Returns DataFrame with 'dates' (datetime) and 'Q' (float) columns.
    """
    for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
        for sep in ['\t', ',', r'\s+']:
            try:
                df = pd.read_csv(obs_file, sep=sep, encoding=encoding,
                                 names=['stcd', 'dates', 'z', 'Q', 'name'],
                                 header=0, on_bad_lines='skip')
                df['dates'] = pd.to_datetime(df['dates'], errors='coerce')
                df['Q'] = pd.to_numeric(df['Q'], errors='coerce')
                df = df.dropna(subset=['dates', 'Q'])

                # Replace missing value flags
                df.loc[df['Q'] < 0, 'Q'] = np.nan

                if len(df) > 100:
                    print(f"  Read {len(df)} records ({encoding}, sep={repr(sep)})")
                    return df
            except Exception:
                continue

    print(f"ERROR: Could not read {obs_file}")
    sys.exit(2)


def convert(obs_file, station_area_km2, dam_area_km2,
            start_date, end_date, output_file, gap_fill='interpolate'):
    """Convert observed discharge to Pywr inflow CSV."""
    os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)

    df = read_obs_discharge(obs_file)

    # Filter to requested period
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    df = df[(df['dates'] >= start) & (df['dates'] <= end)].copy()
    df = df.set_index('dates').sort_index()

    if len(df) == 0:
        print(f"ERROR: No data in period {start_date} to {end_date}")
        sys.exit(2)

    # Reindex to fill date gaps
    full_index = pd.date_range(start, end, freq='D')
    df = df.reindex(full_index)
    n_missing = df['Q'].isna().sum()

    if n_missing > 0:
        if gap_fill == 'interpolate':
            df['Q'] = df['Q'].interpolate(method='linear', limit=30)
        elif gap_fill == 'zero':
            df['Q'] = df['Q'].fillna(0.0)
        remaining_nan = df['Q'].isna().sum()
        if remaining_nan > 0:
            df['Q'] = df['Q'].fillna(df['Q'].median())
        print(f"  Filled {n_missing} missing days ({gap_fill})")

    # Area scaling
    scale_factor = 1.0
    if dam_area_km2 and station_area_km2 and dam_area_km2 != station_area_km2:
        scale_factor = dam_area_km2 / station_area_km2
        print(f"  Area scaling: {station_area_km2} km2 -> {dam_area_km2} km2 (factor={scale_factor:.4f})")

    df['inflow_m3s'] = df['Q'] * scale_factor

    # Write output
    out_df = pd.DataFrame({
        'date': full_index.strftime('%Y-%m-%d'),
        'inflow_m3s': df['inflow_m3s'].values.round(2),
    })
    out_df.to_csv(output_file, index=False)

    mean_q = out_df['inflow_m3s'].mean()
    print(f"\nOutput: {output_file}")
    print(f"  Period: {start_date} to {end_date} ({len(out_df)} days)")
    print(f"  Mean inflow: {mean_q:.1f} m3/s")
    if scale_factor != 1.0:
        print(f"  (scaled from obs mean {df['Q'].mean() / scale_factor:.1f} m3/s)")


def main():
    parser = argparse.ArgumentParser(
        description='Convert observed discharge to Pywr reservoir inflow')
    parser.add_argument('--obs_file', required=True,
                        help='Observed discharge file (tab-sep: stcd|dates|z|Q|name)')
    parser.add_argument('--station_area_km2', type=float, default=None,
                        help='Drainage area of the observation station (km2)')
    parser.add_argument('--dam_area_km2', type=float, default=None,
                        help='Upstream area of the dam (km2). If different from station, applies area scaling.')
    parser.add_argument('--start_date', required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--end_date', required=True, help='End date YYYY-MM-DD')
    parser.add_argument('--output', required=True, help='Output inflow CSV')
    parser.add_argument('--gap_fill', choices=['interpolate', 'zero'], default='interpolate',
                        help='Gap fill method for missing days')
    args = parser.parse_args()

    convert(args.obs_file, args.station_area_km2, args.dam_area_km2,
            args.start_date, args.end_date, args.output, args.gap_fill)


if __name__ == '__main__':
    main()
