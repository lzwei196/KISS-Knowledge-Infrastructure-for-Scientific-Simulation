#!/usr/bin/env python3
"""
load_ntl_lter_obs.py -- Load NTL-LTER in-lake WATER TEMPERATURE depth profiles.

Why this exists: GLM's dag defines `temp` as water temperature per Lagrangian
layer and prescribes comparison against fixed-depth WATER-temperature
observations (dag.yaml comparable_obs_shapes[point_time_series] caveat
"Compare at matched depths ... interpolate to fixed observation depths").
Before this tool the KI's only observation loader was load_ismn_obs.py, which
reads SOIL temperature from KISSPATH_DATA/ismn_clean.db -- a different physical
medium. Scoring GLM against soil temperature yields a high r that is just the
shared annual air-temperature harmonic and never exercises stratification,
thermocline depth, vertical mixing, wind stirring or Kw.

Source: NTL-LTER North Temperate Lakes physical limnology, 13 Wisconsin lakes,
1981-2025, water temperature (and DO) on discrete profile sample dates.

Output is long form `date,depth_m,value,n_obs`, with depth_m in TRUE METRES
below the water surface -- directly feedable to
parse_glm_output.py --depths (see --depths_out).

Example:
    python load_ntl_lter_obs.py --list
    python load_ntl_lter_obs.py --lakeid SP --start 1982-01-01 --end 2015-12-31 \
        --max_depth_m 18.0 --output obs_sp.csv --depths_out depths.txt \
        --meta_out obs_sp_meta.json
    python parse_glm_output.py --output_nc output/output.nc \
        --depths "$(cat depths.txt)" --depth_timeseries sim_depths.csv

Alignment traps on the SIM side (dt_036), handled by the caller, not here:
  * GLM stamps state at the END of each simulated day -> shift sim -1 day.
  * The final timestep is flushed TWICE -> drop duplicate dates.
"""
import argparse
import json
import os
import sys

import pandas as pd

CSV_DEFAULT = "KISSPATH_DATA/obs/ntl-lter-phys-limno/ntl29_physical_limnology.csv"

LAKE_NAMES = {
    'AL': 'Allequash Lake', 'BM': 'Big Muskellunge Lake', 'CB': 'Crystal Bog',
    'CR': 'Crystal Lake', 'FI': 'Fish Lake', 'KE': 'Lake Kegonsa',
    'ME': 'Lake Mendota', 'MO': 'Lake Monona', 'SP': 'Sparkling Lake',
    'TB': 'Trout Bog', 'TR': 'Trout Lake', 'WA': 'Lake Waubesa',
    'WI': 'Lake Wingra',
}


def read_raw(csv_path):
    """Read the NTL CSV.

    dtype=str + low_memory=False is MANDATORY: this file has mixed dtypes
    across read chunks, and a `usecols=[...]` read raises
    `IndexError: list index out of range` inside pandas
    io/parsers/c_parser_wrapper.py `_concatenate_chunks`.
    """
    if not os.path.exists(csv_path):
        raise SystemExit(f"NTL-LTER csv not found: {csv_path}")
    return pd.read_csv(csv_path, dtype=str, low_memory=False)


def list_lakes(df, variable='wtemp'):
    d = df.copy()
    d[variable] = pd.to_numeric(d[variable], errors='coerce')
    d['depth'] = pd.to_numeric(d['depth'], errors='coerce')
    d = d[d[variable].notna() & d['depth'].notna()]
    rows = []
    for lk, g in d.groupby('lakeid'):
        rows.append({
            'lakeid': lk,
            'lake_name': LAKE_NAMES.get(lk, lk),
            'n_obs': int(len(g)),
            'n_dates': int(g['sampledate'].nunique()),
            'n_depths': int(g['depth'].nunique()),
            'depth_min_m': float(g['depth'].min()),
            'depth_max_m': float(g['depth'].max()),
            'start': str(g['sampledate'].min()),
            'end': str(g['sampledate'].max()),
        })
    return sorted(rows, key=lambda r: -r['n_obs'])


def load(df, lakeid, variable='wtemp', start=None, end=None,
         allow_flags=None, vmin=-2.0, vmax=40.0, max_depth_m=None):
    """Return (long-form DataFrame date,depth_m,value,n_obs ; provenance dict)."""
    flagcol = 'flag' + variable
    allow = set(f.strip().upper() for f in (allow_flags or '').split(',') if f.strip())

    d = df[df['lakeid'] == lakeid].copy()
    n_raw = len(d)
    if n_raw == 0:
        raise SystemExit(
            f"lakeid {lakeid!r} not in file; available: {sorted(df['lakeid'].unique())}")

    d[variable] = pd.to_numeric(d[variable], errors='coerce')
    d['depth_m'] = pd.to_numeric(d['depth'], errors='coerce')
    d['date'] = pd.to_datetime(d['sampledate'], errors='coerce')
    d = d[d[variable].notna() & d['depth_m'].notna() & d['date'].notna()]
    n_parsed = len(d)

    # QC. flagwtemp is null for clean rows; 'J' (estimated) / 'K' (below
    # detection) are real NTL codes; the ~30 NUMERIC values in this column
    # ('5.6', '0.3', '999', ...) are column-shift contamination and are
    # ALWAYS dropped -- they can never be opted back in via --allow_flags.
    if flagcol in d.columns:
        flag = d[flagcol].fillna('').str.strip().str.upper()
        keep = (flag == '') | (flag.isin(allow) & flag.str.isalpha())
        d = d[keep]
    n_qc = len(d)

    # Physical range gate (catches sentinel values that escaped the flag column)
    d = d[(d[variable] >= vmin) & (d[variable] <= vmax)]
    n_range = len(d)

    if start:
        d = d[d['date'] >= pd.to_datetime(start)]
    if end:
        d = d[d['date'] <= pd.to_datetime(end)]
    if max_depth_m is not None:
        d = d[d['depth_m'] <= float(max_depth_m)]
    n_window = len(d)
    if n_window == 0:
        raise SystemExit(
            f"no {variable} rows left for {lakeid} after QC/window filters "
            f"(raw={n_raw}, parsed={n_parsed}, qc={n_qc}, range={n_range})")

    # Average replicate samples: NTL carries rep/sta columns, so a
    # (sampledate, depth) pair can hold several measurements.
    g = (d.groupby(['date', 'depth_m'])[variable]
           .agg(['mean', 'size']).reset_index()
           .rename(columns={'mean': 'value', 'size': 'n_obs'}))
    g = g.sort_values(['date', 'depth_m']).reset_index(drop=True)
    g['date'] = g['date'].dt.strftime('%Y-%m-%d')

    depths = sorted(g['depth_m'].unique().tolist())
    meta = {
        'source': 'NTL-LTER north temperate lakes physical limnology',
        'lakeid': lakeid,
        'lake_name': LAKE_NAMES.get(lakeid, lakeid),
        'variable': variable,
        'medium': 'in-lake water column',
        'unit': 'degC' if variable == 'wtemp' else 'unknown',
        'depth_reference': 'metres below water surface',
        'n_rows_raw': n_raw, 'n_rows_parsed': n_parsed,
        'n_rows_after_qc': n_qc, 'n_rows_after_range': n_range,
        'n_rows_in_window': n_window, 'n_paired_rows_out': int(len(g)),
        'n_dates': int(g['date'].nunique()), 'n_depths': len(depths),
        'depths_m': depths,
        'depth_min_m': float(min(depths)), 'depth_max_m': float(max(depths)),
        'start': g['date'].min(), 'end': g['date'].max(),
        'value_min': float(g['value'].min()), 'value_max': float(g['value'].max()),
        'allow_flags': sorted(allow), 'max_depth_m': max_depth_m,
    }
    return g, meta


def main():
    p = argparse.ArgumentParser(
        description="Load NTL-LTER in-lake water temperature depth profiles")
    p.add_argument("--csv", default=CSV_DEFAULT)
    p.add_argument("--lakeid", help="NTL lake code, e.g. SP (Sparkling), TR (Trout), ME (Mendota)")
    p.add_argument("--variable", default="wtemp", help="wtemp (default) or o2")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--allow_flags", default="",
                   help="comma-separated NTL letter flags to KEEP, e.g. 'J'. "
                        "Numeric (corrupt) flags are never kept.")
    p.add_argument("--min_temp", type=float, default=-2.0)
    p.add_argument("--max_temp", type=float, default=40.0)
    p.add_argument("--max_depth_m", type=float,
                   help="drop obs deeper than this (e.g. the model lake bottom)")
    p.add_argument("--list", action="store_true",
                   help="list per-lake coverage and exit")
    p.add_argument("--output", help="long-form CSV: date,depth_m,value,n_obs")
    p.add_argument("--depths_out",
                   help="write comma-joined unique depths for parse_glm_output --depths")
    p.add_argument("--meta_out", help="JSON provenance/QC accounting")
    a = p.parse_args()

    df = read_raw(a.csv)

    if a.list:
        print(json.dumps(list_lakes(df, a.variable), indent=2))
        return

    if not a.lakeid:
        p.error("--lakeid is required (or use --list)")

    g, meta = load(df, a.lakeid, a.variable, a.start, a.end,
                   a.allow_flags, a.min_temp, a.max_temp, a.max_depth_m)

    if a.output:
        os.makedirs(os.path.dirname(a.output) or '.', exist_ok=True)
        g.to_csv(a.output, index=False)
        meta['output'] = a.output
        print(f"wrote {len(g)} rows -> {a.output}", file=sys.stderr)
    if a.depths_out:
        os.makedirs(os.path.dirname(a.depths_out) or '.', exist_ok=True)
        with open(a.depths_out, 'w') as f:
            f.write(",".join(f"{d:g}" for d in meta['depths_m']))
        meta['depths_out'] = a.depths_out
    if a.meta_out:
        os.makedirs(os.path.dirname(a.meta_out) or '.', exist_ok=True)
        with open(a.meta_out, 'w') as f:
            json.dump(meta, f, indent=2)

    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
