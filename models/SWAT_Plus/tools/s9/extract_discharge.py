#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      extract_discharge
Stage:        s9_output_parsing
Model:        SWAT+
Description:  Extract daily discharge from channel_sd_day.txt or channel_day.txt
              at the outlet channel, with proper unit conversion.

SWAT+ channel output stores flo_out in ha-m/day. This tool converts to m³/s:
    Q_m3s = flo_out_ham_day * 10000 / 86400

The outlet is auto-detected as the channel with the highest gis_id
(SWAT+ convention: highest ID = most downstream).

Usage:
    python extract_discharge.py \
        --txtinout_dir outputs/bengbu_swatplus/TxtInOut \
        --output_csv revalidation/SWAT_Plus/bengbu/discharge_sim.csv

    # With explicit outlet channel and obs comparison:
    python extract_discharge.py \
        --txtinout_dir outputs/wangjiaba_swatplus_fixed/TxtInOut \
        --outlet_gis_id 5 \
        --obs_csv data/obs/WJB/HUAIH-51030-wangjiaba.txt \
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# SWAT+ flo_out unit: ha-m/day  →  m³/s
HAM_DAY_TO_M3S = 10000.0 / 86400.0  # 1 ha-m = 10000 m³; 1 day = 86400 s


def parse_channel_day(filepath, outlet_gis_id=None):
    """
    Parse SWAT+ channel_day.txt or channel_sd_day.txt.

    File format:
        Line 0: title (model name + version)
        Line 1: column names (space-separated)
        Line 2: units
        Line 3+: data (space-separated, Fortran scientific notation)

    Returns:
        DataFrame with date index and Q_sim (m³/s) column.
    """
    filepath = Path(filepath)
    lines = filepath.read_text().strip().split('\n')

    if len(lines) < 4:
        raise ValueError(f"File too short ({len(lines)} lines): {filepath}")

    # Line 1 = column names
    col_names = lines[1].split()
    logger.info(f"Columns: {col_names[:8]}... ({len(col_names)} total)")

    # Verify required columns
    required = {'jday', 'mon', 'day', 'yr', 'gis_id', 'flo_out'}
    missing = required - set(col_names)
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Available: {col_names}")

    # Parse data rows
    records = []
    for line in lines[3:]:
        parts = line.split()
        if len(parts) < len(col_names):
            continue
        row = dict(zip(col_names, parts))
        try:
            records.append({
                'yr': int(row['yr']),
                'mon': int(row['mon']),
                'day': int(row['day']),
                'gis_id': int(row['gis_id']),
                'flo_out': float(row['flo_out']),
            })
        except (ValueError, KeyError):
            continue

    df = pd.DataFrame(records)
    logger.info(f"Parsed {len(df)} records, {df['gis_id'].nunique()} channels")

    # Select outlet
    if outlet_gis_id is None:
        outlet_gis_id = df['gis_id'].max()
    logger.info(f"Outlet channel: gis_id={outlet_gis_id}")

    df_out = df[df['gis_id'] == outlet_gis_id].copy()
    if len(df_out) == 0:
        raise ValueError(f"No records for gis_id={outlet_gis_id}")

    # Build date column
    df_out['date'] = pd.to_datetime(df_out[['yr', 'mon', 'day']].rename(
        columns={'yr': 'year', 'mon': 'month', 'day': 'day'}))

    # Convert ha-m/day → m³/s
    df_out['Q_sim'] = df_out['flo_out'] * HAM_DAY_TO_M3S

    result = df_out.set_index('date')[['Q_sim']].sort_index()
    logger.info(f"Discharge: {len(result)} days, mean={result['Q_sim'].mean():.1f} m³/s, "
                f"max={result['Q_sim'].max():.1f} m³/s")
    return result


def find_channel_file(txtinout_dir):
    """Find channel output file in TxtInOut directory."""
    txtinout = Path(txtinout_dir)
    for name in ['channel_sd_day.txt', 'channel_sd_day.csv',
                 'channel_day.txt', 'channel_day.csv']:
        p = txtinout / name
        if p.exists():
            return p
    raise FileNotFoundError(f"No channel output file in {txtinout}")


def load_obs(obs_path):
    """Load HydroCraft-format observed discharge."""
    df = pd.read_csv(obs_path, sep='\t', encoding='utf-8', encoding_errors='replace')
    df['date'] = pd.to_datetime(df['dates'])
    df = df.set_index('date')[['Q']].astype(float)
    df = df[df['Q'] > 0]
    df = df.rename(columns={'Q': 'Q_obs'})
    return df


def main():
    parser = argparse.ArgumentParser(
        description='Extract daily discharge from SWAT+ channel output')
    parser.add_argument('--txtinout_dir', required=True,
                        help='Path to TxtInOut directory (or parent with TxtInOut subdir)')
    parser.add_argument('--output_csv', required=True, help='Output CSV (date, Q_sim)')
    parser.add_argument('--outlet_gis_id', type=int, default=None,
                        help='Outlet channel gis_id (auto-detected if omitted)')
    parser.add_argument('--obs_csv', default=None,
                        help='Observed discharge file for comparison')
    parser.add_argument('--metrics_json', default=None,
                        help='Output path for metrics JSON')
    args = parser.parse_args()

    # Find TxtInOut
    txtinout = Path(args.txtinout_dir)
    if not (txtinout / 'channel_day.txt').exists() and (txtinout / 'TxtInOut').exists():
        txtinout = txtinout / 'TxtInOut'

    chan_file = find_channel_file(txtinout)
    logger.info(f"Reading: {chan_file}")

    # Extract
    daily = parse_channel_day(chan_file, outlet_gis_id=args.outlet_gis_id)

    # Save
    out_path = Path(args.output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.obs_csv:
        obs = load_obs(args.obs_csv)
        merged = obs.join(daily, how='inner').dropna()
        merged.to_csv(out_path)
        logger.info(f"Saved comparison CSV ({len(merged)} days): {out_path}")

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
