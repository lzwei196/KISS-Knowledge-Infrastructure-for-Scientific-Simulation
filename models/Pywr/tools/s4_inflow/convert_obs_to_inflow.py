#!/usr/bin/env python3
"""Convert daily observed Q to Pywr inflow, rejecting missing data by default.

Explicit --gap_fill interpolate permits only bracketed gaps of at most 30 days;
--gap_fill zero is an explicit zero-inflow assumption. Every replacement is
recorded in <output>.provenance.json. No fallback method is applied.
"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np
import pandas as pd


def read_obs_discharge(obs_file):
    """Read a single station without dropping malformed or missing observations."""
    raw = Path(obs_file).read_bytes()
    for encoding in ('utf-8-sig', 'gbk', 'gb2312'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f'{obs_file}: unsupported text encoding (expected UTF-8 or GBK)')
    lines = text.splitlines()
    if not lines:
        raise ValueError(f'{obs_file}: empty observation file')
    separator = '\t' if '\t' in lines[0] else ',' if ',' in lines[0] else None
    rows = list(csv.reader(io.StringIO(text), delimiter=separator, strict=True)) if separator else [line.split(maxsplit=4) for line in lines]
    required = ['stcd', 'dates', 'z', 'Q', 'name']
    if [value.strip() for value in rows[0]] != required:
        raise ValueError(f'{obs_file}: expected header {required}')
    for line, row in enumerate(rows[1:], 2):
        if len(row) != 5:
            raise ValueError(f'{obs_file}: line {line} has {len(row)} fields; expected 5')
    df = pd.DataFrame(rows[1:], columns=required)
    if df.empty:
        raise ValueError(f'{obs_file}: no observations')
    stations = df.stcd.str.strip()
    if stations.nunique() != 1 or (stations == '').any():
        raise ValueError(f'{obs_file}: exactly one nonempty station ID is required')
    try:
        dates = pd.to_datetime(df.dates, errors='raise', format='mixed')
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{obs_file}: invalid observation dates: {exc}') from exc
    if dates.isna().any() or dates.dt.tz is not None or not (dates == dates.dt.normalize()).all():
        raise ValueError(f'{obs_file}: dates must be daily calendar dates without a timezone')
    if dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError(f'{obs_file}: observation dates must be unique and increasing')
    values = []
    reasons = []
    originals = df.Q.str.strip()
    for day, original in zip(dates, originals):
        if original.lower() in ('', 'nan', 'na', 'null'):
            values.append(np.nan); reasons.append('missing_value')
            continue
        try:
            value = float(original)
        except ValueError as exc:
            raise ValueError(f'{obs_file}: invalid Q={original!r} on {day.date()}') from exc
        if value in (-99, -9999):
            values.append(np.nan); reasons.append('missing_flag')
        elif not np.isfinite(value) or value < 0:
            raise ValueError(f'{obs_file}: Q must be finite and nonnegative on {day.date()}: {original}')
        else:
            values.append(value); reasons.append(None)
    df['dates'], df['Q'] = dates, values
    df['original_value'], df['reason'] = originals, reasons
    df.attrs.update(encoding=encoding, sha256=hashlib.sha256(raw).hexdigest())
    return df


def _day(value, name):
    try:
        day = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{name}: invalid date {value!r}') from exc
    if pd.isna(day) or day.tz is not None or day != day.normalize():
        raise ValueError(f'{name}: expected a daily calendar date')
    return day


def convert(obs_file, station_area_km2, dam_area_km2, start_date, end_date,
            output_file, gap_fill='error'):
    """Validate the entire requested interval before writing CSV and provenance."""
    if gap_fill not in ('error', 'interpolate', 'zero'):
        raise ValueError(f'Unknown gap_fill method: {gap_fill}')
    start, end = _day(start_date, 'start_date'), _day(end_date, 'end_date')
    if start > end:
        raise ValueError('start_date must not be after end_date')
    if (station_area_km2 is None) != (dam_area_km2 is None):
        raise ValueError('station_area_km2 and dam_area_km2 must be supplied together')
    scale = 1.0
    if station_area_km2 is not None:
        if not all(np.isfinite(v) and v > 0 for v in (station_area_km2, dam_area_km2)):
            raise ValueError('Both drainage areas must be finite and positive')
        scale = dam_area_km2 / station_area_km2
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError('Area ratio must be finite and positive')
    source = read_obs_discharge(obs_file)
    full_index = pd.date_range(start, end, freq='D')
    df = source.set_index('dates').reindex(full_index)
    q = df.Q.to_numpy(dtype=float, copy=True)
    missing = np.flatnonzero(np.isnan(q))
    if len(missing) and gap_fill == 'error':
        days = ', '.join(str(full_index[i].date()) for i in missing[:10])
        raise ValueError(f'{obs_file}: missing observed Q on {len(missing)} requested days: {days}; supply complete observations or explicitly select --gap_fill')
    fills = []
    for group in np.split(missing, np.flatnonzero(np.diff(missing) != 1)+1):
        if not len(group):
            continue
        left, right = int(group[0])-1, int(group[-1])+1
        if gap_fill == 'interpolate' and (left < 0 or right >= len(q) or len(group) > 30):
            raise ValueError(f'{obs_file}: cannot interpolate {len(group)} days starting {full_index[group[0]].date()}; require two observed endpoints and at most 30 missing days')
        for i in group:
            if gap_fill == 'zero':
                value = 0.0
            else:
                weight = (int(i)-left)/(right-left)
                value = (1-weight)*q[left] + weight*q[right]
            q[i] = value
            original = df.original_value.iloc[i]
            absent = pd.isna(original)
            entry = dict(date=str(full_index[i].date()), original_value=None if absent else original,
                         reason='absent_date' if absent else df.reason.iloc[i],
                         method='explicit_zero' if gap_fill == 'zero' else 'linear_interpolation',
                         filled_Q_m3s=float(value), inflow_m3s=float(value*scale))
            if gap_fill == 'interpolate':
                entry.update(left=dict(date=str(full_index[left].date()), Q_m3s=float(q[left])),
                             right=dict(date=str(full_index[right].date()), Q_m3s=float(q[right])))
            fills.append(entry)
    inflow = q*scale
    if not np.isfinite(inflow).all() or (inflow < 0).any():
        raise ValueError('Converted inflow is not finite and nonnegative')
    out = pd.DataFrame({'date':full_index.strftime('%Y-%m-%d'), 'inflow_m3s':inflow})
    csv_text = out.to_csv(index=False, float_format='%.17g')
    provenance = dict(source=str(Path(obs_file).resolve()), source_sha256=source.attrs['sha256'],
                      source_encoding=source.attrs['encoding'], station_id=str(source.stcd.iloc[0]),
                      start_date=str(start.date()), end_date=str(end.date()), days=len(out),
                      units='m3/s', station_area_km2=station_area_km2, dam_area_km2=dam_area_km2,
                      area_scale_factor=scale, gap_fill=gap_fill, fill_count=len(fills), fills=fills,
                      output_sha256=hashlib.sha256(csv_text.encode('utf-8')).hexdigest())
    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Prepare both artifacts first; each replace is atomic. The sidecar hash binds
    # it to the CSV so an interrupted two-file replacement can be detected.
    staged = []
    try:
        for target, content in [(output, csv_text),
                                (Path(str(output)+'.provenance.json'), json.dumps(provenance, indent=2, allow_nan=False)+'\n')]:
            # Write the exact bytes that were hashed (binary mode: no newline translation on Windows).
            with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, delete=False) as stream:
                stream.write(content.encode('utf-8'))
                staged.append((Path(stream.name), target))
        for pending, target in staged:
            os.replace(pending, target)
    finally:
        for pending, _ in staged:
            pending.unlink(missing_ok=True)
    print(f'Output: {output}; {len(out)} days; {len(fills)} filled ({gap_fill}); area ratio={scale:g}')
    print(f'Observed/reconstructed mean Q={q.mean():g} m3/s; mean inflow={inflow.mean():g} m3/s')
    print(f'Provenance: {output}.provenance.json')
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--obs_file', required=True)
    parser.add_argument('--station_area_km2', type=float)
    parser.add_argument('--dam_area_km2', type=float)
    parser.add_argument('--start_date', required=True)
    parser.add_argument('--end_date', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--gap_fill', choices=['error','interpolate','zero'], default='error')
    args = parser.parse_args()
    try:
        convert(args.obs_file, args.station_area_km2, args.dam_area_km2,
                args.start_date, args.end_date, args.output, args.gap_fill)
    except (ValueError, OSError, csv.Error) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
