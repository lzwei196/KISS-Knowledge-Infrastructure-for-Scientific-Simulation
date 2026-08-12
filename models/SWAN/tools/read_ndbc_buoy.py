#!/usr/bin/env python3
"""
Read NDBC standard-meteorological (stdmet) buoy files for SWAN forcing and
validation.

Pipeline stage: 2/3/6 support — observation + station-forcing I/O
Pattern: validate_inputs -> process -> validate_outputs

SKILL.md and data_ki/NDBC/SKILL.md both point at
``data_ki/NDBC/tools/read_buoy.py`` for this, but KDT 5.0 removed the
``data_ki/<X>/tools`` trees, so that path does not exist.  Observation I/O
belongs in the model KI's own ``tools/`` directory, which is where this lives.

stdmet file layout (whitespace delimited, TWO '#' header lines)::

    #YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP ...
    #yr  mo dy hr mn degT m/s  m/s     m   sec   sec degT   hPa  degC  degC ...

The column SET is not fixed across NDBC products, so columns are resolved from
each file's OWN header rather than from a hard-coded offset (trap 4 below):

* realtime (last 45 days) stdmet carries PTDY between VIS and TIDE::

      #YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS PTDY TIDE

* the yearly historical archive (what is on disk under ``data/obs/ndbc_buoys``)
  omits PTDY::

      #YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS TIDE

* files older than 2005 also omit the ``mm`` (minute) column.

Missing-value sentinels (data_ki/NDBC/SKILL.md section 7, trap 1) are NOT NaN;
they are per-column magic numbers and MUST be filtered or every statistic is
poisoned:

===========================  ==========  ==================
column                       sentinel    native unit
===========================  ==========  ==================
WDIR, MWD                    999         degrees true (FROM)
WSPD, GST, VIS               99.0        m/s (VIS: nmi)
WVHT, DPD, APD, TIDE         99.00       m / s / s / feet
PRES                         9999.0      hPa
ATMP, WTMP, DEWP             999.0       degC
PTDY                         99.0        hPa (3-h tendency, may be negative)
===========================  ==========  ==================

Three further NDBC traps handled here:
  * records are 10-minute, not hourly (6 per hour) -- use :func:`to_hourly`;
  * WDIR/MWD are directions FROM which wind/waves come, so a plain arithmetic
    mean is wrong near 0/360 -- :func:`to_hourly` averages them circularly;
  * (trap 4) the column set differs between products.  Indexing data columns at
    a fixed ``5 + k`` offset reads TIDE out of the PTDY slot on every realtime
    file -- i.e. a pressure tendency silently becomes a tide height, and
    ``TIDE_m`` a tendency divided by 3.28.  :func:`parse_header` therefore maps
    NAME -> token index from the file's own first header line, and columns the
    file does not carry come back as all-NaN instead of as the neighbouring
    column's values.
"""

import datetime
import os

import numpy as np

# Per-column missing-value sentinels, keyed by stdmet column name.
SENTINELS = {
    'WDIR': 999.0, 'WSPD': 99.0, 'GST': 99.0, 'WVHT': 99.0,
    'DPD': 99.0, 'APD': 99.0, 'MWD': 999.0, 'PRES': 9999.0,
    'ATMP': 999.0, 'WTMP': 999.0, 'DEWP': 999.0, 'VIS': 99.0,
    'PTDY': 99.0, 'TIDE': 99.0,
}

# Full stdmet data-column contract, in NDBC's own order.  PTDY sits between VIS
# and TIDE and is present in realtime files but absent from the yearly archive,
# so this list is the SUPERSET: every parsed record carries all of these keys,
# with the ones the file does not have set to NaN.  Positions come from
# parse_header(), never from this list's own ordering.
COLUMNS = ['WDIR', 'WSPD', 'GST', 'WVHT', 'DPD', 'APD', 'MWD', 'PRES',
           'ATMP', 'WTMP', 'DEWP', 'VIS', 'PTDY', 'TIDE']

# Leading header tokens that carry the timestamp rather than a measurement.
# Case matters: 'MM' is the month, 'mm' the minute.  'mm' is absent before 2005
# and 'YY' held a two-digit year before 1999.
_TIME_TOKENS = ('YY', 'YYYY', '#YY', 'MM', 'DD', 'hh', 'mm')

# Directional columns need circular averaging, not arithmetic.
DIRECTIONAL = {'WDIR', 'MWD'}

# Columns whose values must be strictly positive to be physical.
# PTDY is deliberately absent: a falling barometer gives a legitimately
# negative tendency.
_POSITIVE = {'WVHT', 'DPD', 'APD', 'WSPD', 'GST'}


def parse_header(header_line):
    """Resolve stdmet column positions from the first '#' header line.

    Parameters
    ----------
    header_line : str
        The first header line, e.g.
        ``#YY MM DD hh mm WDIR WSPD GST ... VIS PTDY TIDE``.

    Returns
    -------
    dict
        ``{'time': [tok, ...], 'columns': {NAME: token_index},
        'unknown': [tok, ...]}``.  Indices are into ``line.split()`` of a data
        row, so they already account for a missing ``mm`` column or a present
        ``PTDY`` column.

    Raises
    ------
    ValueError
        if the header declares no recognised stdmet data column -- guessing a
        layout there would fabricate values rather than read them.
    """
    tokens = header_line.lstrip('#').split()
    time_tokens = []
    for tok in tokens:
        if tok in _TIME_TOKENS:
            time_tokens.append(tok)
        else:
            break
    columns, unknown = {}, []
    for i, tok in enumerate(tokens[len(time_tokens):], start=len(time_tokens)):
        name = tok.upper()
        if name in SENTINELS:
            columns[name] = i
        else:
            unknown.append(tok)
    if len(time_tokens) < 4:
        raise ValueError(
            f"NDBC stdmet header must start with at least YY MM DD hh; got "
            f"{time_tokens} from {header_line[:80]!r}")
    if not columns:
        raise ValueError(
            f"no recognised NDBC stdmet data columns in header {header_line[:80]!r}; "
            f"expected one or more of {sorted(SENTINELS)}")
    return {'time': time_tokens, 'columns': columns, 'unknown': unknown}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(path):
    """Check an stdmet file exists and has the expected two-line header.

    Returns
    -------
    list of str : warnings

    Raises
    ------
    FileNotFoundError, ValueError
    """
    warnings = []
    if not os.path.isfile(path):
        raise FileNotFoundError(f"NDBC stdmet file not found: {path}")
    with open(path) as f:
        h1 = f.readline()
        h2 = f.readline()
    if not h1.startswith('#') or not h2.startswith('#'):
        raise ValueError(
            f"{path}: expected two '#' header lines (stdmet format); "
            f"got {h1[:40]!r} / {h2[:40]!r}")
    if 'WVHT' not in h1:
        warnings.append(f"{path}: header has no WVHT column - not a stdmet file?")
    hdr = parse_header(h1)
    # Report the layout rather than assume one: TIDE's position moves with PTDY,
    # and a file that declares neither is not silently given the other's values.
    for name in ('PTDY', 'TIDE'):
        if name not in hdr['columns']:
            warnings.append(
                f"{path}: header declares no {name} column - {name} will be NaN")
    if 'mm' not in hdr['time']:
        warnings.append(
            f"{path}: header has no 'mm' column (pre-2005 stdmet) - "
            "minute set to 0")
    if hdr['unknown']:
        warnings.append(
            f"{path}: ignoring unrecognised header column(s) "
            f"{', '.join(hdr['unknown'])}")
    return warnings


def validate_outputs(rec):
    """Range-check a parsed record dict; returns a diagnostics dict."""
    out = {'status': 'OK', 'n_records': len(rec['t']), 'ranges': {}, 'errors': []}
    if out['n_records'] == 0:
        out['status'] = 'FAIL: no records parsed'
        return out
    for name in COLUMNS:
        v = rec.get(name)
        if v is None:
            continue
        good = v[~np.isnan(v)]
        if good.size == 0:
            out['ranges'][name] = 'all-missing'
            continue
        out['ranges'][name] = f"{good.min():.2f}..{good.max():.2f} (n={good.size})"
        # UNIT TRAP guards from data_ki/NDBC/SKILL.md section 9
        if name == 'WSPD' and good.max() > 60:
            out['errors'].append(
                f"UNIT TRAP: max WSPD={good.max():.1f} > 60 - knots, not m/s? "
                "(1 kt = 0.5144 m/s)")
        if name == 'WVHT' and good.max() > 30:
            out['errors'].append(
                f"UNIT TRAP: max WVHT={good.max():.1f} m > 30 - cm, not m? "
                "(divide by 100)")
        if name == 'PRES' and good.max() > 2000:
            out['errors'].append(
                f"UNIT TRAP: max PRES={good.max():.0f} - Pa, not hPa?")
        if name in _POSITIVE and good.min() < 0:
            out['errors'].append(f"{name} has negative values (sentinel leak?)")
    if out['errors']:
        out['status'] = f"FAIL: {len(out['errors'])} range errors"
    return out


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def read_stdmet(path, year=None):
    """Parse an NDBC stdmet .txt file with sentinels replaced by NaN.

    Parameters
    ----------
    path : str
    year : int, optional
        Keep only records in this calendar year (stdmet year files carry a few
        records from the neighbouring year).

    Returns
    -------
    dict : {'t': list[datetime], 'WDIR': ndarray, 'WSPD': ndarray, ...}
        Every value array is float with NaN for missing.  All of
        :data:`COLUMNS` is always present; columns the file does not declare
        (typically PTDY in archive files) are all-NaN.  ``'columns'`` lists the
        names actually read from the file.
    """
    validate_inputs(path)

    with open(path) as f:
        header = f.readline()
    hdr = parse_header(header)
    index = hdr['columns']
    n_time = len(hdr['time'])
    # Minute is optional (pre-2005 files stop at 'hh'); everything else in the
    # timestamp is mandatory.
    minute_pos = hdr['time'].index('mm') if 'mm' in hdr['time'] else None

    times = []
    cols = {name: [] for name in COLUMNS}
    with open(path) as f:
        for line in f:
            if line.startswith('#'):
                continue
            p = line.split()
            if len(p) < n_time + 1:
                continue
            try:
                yy, mo, dd, hh = (int(p[i]) for i in range(4))
                mi = int(p[minute_pos]) if minute_pos is not None else 0
                t = datetime.datetime(yy, mo, dd, hh, mi)
            except ValueError:
                continue
            if year is not None and t.year != year:
                continue
            times.append(t)
            for name in COLUMNS:
                idx = index.get(name)
                if idx is None or idx >= len(p):
                    cols[name].append(np.nan)
                    continue
                try:
                    v = float(p[idx])
                except ValueError:
                    cols[name].append(np.nan)
                    continue
                # Sentinel filtering. NDBC pads short values (99 vs 99.0 vs
                # 99.00), so compare with a tolerance rather than for equality.
                sent = SENTINELS[name]
                cols[name].append(np.nan if abs(v - sent) < 1e-6 or v >= sent
                                  else v)

    rec = {'t': times, 'source': path, 'columns': sorted(index)}
    for name in COLUMNS:
        rec[name] = np.asarray(cols[name], dtype=float)
    # TIDE is the only length reported in FEET (data_ki/NDBC/SKILL.md trap 2).
    # This is now the real TIDE column: reading it at a fixed offset 17 picked up
    # PTDY (hPa) on any file carrying the realtime column set.
    rec['TIDE_m'] = rec['TIDE'] / 3.28084
    return rec


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _circular_mean_deg(vals):
    """Mean of directions in degrees, correct across the 0/360 wrap."""
    good = vals[~np.isnan(vals)]
    if good.size == 0:
        return np.nan
    a = np.deg2rad(good)
    return float(np.rad2deg(np.arctan2(np.sin(a).mean(), np.cos(a).mean())) % 360.0)


def to_hourly(rec, names=None):
    """Aggregate 10-minute stdmet records to hourly means.

    Directional columns (WDIR, MWD) are averaged CIRCULARLY; all others
    arithmetically.  Hours with no valid sample are simply absent.

    Returns
    -------
    dict : {name: {datetime -> float}}
    """
    if names is None:
        names = COLUMNS
    bins = {name: {} for name in names}
    for i, t in enumerate(rec['t']):
        hr = t.replace(minute=0, second=0, microsecond=0)
        for name in names:
            v = rec[name][i]
            if not np.isnan(v):
                bins[name].setdefault(hr, []).append(v)
    out = {}
    for name in names:
        if name in DIRECTIONAL:
            out[name] = {h: _circular_mean_deg(np.asarray(v))
                         for h, v in bins[name].items()}
        else:
            out[name] = {h: float(np.mean(v)) for h, v in bins[name].items()}
    return out


# ---------------------------------------------------------------------------
# Wind helpers
# ---------------------------------------------------------------------------

def u10_factor(anemometer_height_m, z0=0.0002):
    """Neutral log-law factor converting anemometer wind to U10.

    SWAN expects the 10-m wind (docs/03_wind_forcing.md trap "Wind at wrong
    height").  NDBC 3-m discus/foam hulls carry the anemometer at ~4.1 m, so
    the raw WSPD is ~9% low.

    U10 = U(z) * ln(10/z0) / ln(z/z0)
    """
    if anemometer_height_m <= 0:
        raise ValueError("anemometer height must be > 0")
    return float(np.log(10.0 / z0) / np.log(anemometer_height_m / z0))


def wind_to_components(wspd, wdir_from_deg):
    """Meteorological speed/direction -> (u_east, v_north) velocity components.

    NDBC WDIR is the direction the wind blows FROM (data_ki/NDBC/SKILL.md trap
    3), so the velocity vector points the OPPOSITE way::

        u = -WSPD * sin(WDIR)      v = -WSPD * cos(WDIR)

    SWAN's ``READINP WIND`` always consumes x- and y-VELOCITY components,
    independently of SET NAUTICAL / SET CARTESIAN.
    """
    wspd = np.asarray(wspd, dtype=float)
    th = np.deg2rad(np.asarray(wdir_from_deg, dtype=float))
    return -wspd * np.sin(th), -wspd * np.cos(th)


if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        r = read_stdmet(p)
        print(p)
        print(' ', validate_outputs(r))
