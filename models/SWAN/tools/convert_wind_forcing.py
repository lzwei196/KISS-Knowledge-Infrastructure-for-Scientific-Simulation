#!/usr/bin/env python3
"""
Convert station / gridded wind data to a SWAN wind input field.

Pipeline stage: 3 — Wind forcing preparation
Pattern: validate_inputs -> process -> validate_outputs

SKILL.md's pipeline table lists ``convert_wind_forcing`` as the stage-3 tool
but the file was missing from ``tools/``, so every prior run hand-assembled the
wind file and re-derived the same traps.  This is that tool.

What it writes
--------------
A SWAN non-stationary vector input file to be referenced as::

    INPGRID WIND REGULAR [xpinp] [ypinp] 0. [mxinp] [myinp] [dxinp] [dyinp] &
            NONSTATIONARY [tbeg] [dt] HR [tend]
    READINP WIND 1.0 'wind.wnd' 4 0 FREE

Layout (SWAN user manual, READINP):

* an input grid of ``mxinp x myinp`` MESHES holds ``(mxinp+1) x (myinp+1)``
  VALUES -- the same (+1) rule as the bottom grid;
* for a VECTOR field SWAN reads the whole x-component map first, then the whole
  y-component map, for each time level in turn;
* ``idla=4`` means the map is read left-to-right starting at the LOWER-left
  corner, so row 0 of each written block is the LOWEST y.

Traps handled (docs/03_wind_forcing.md)
---------------------------------------
* knots / km h-1 -> m s-1;
* anemometer height -> U10 (neutral log law) -- NDBC hulls measure at ~4-5 m,
  which is ~9% low, and wave growth scales roughly with U10^2;
* meteorological direction (FROM) -> velocity components (TO);
* NaN in the field -> SWAN crashes or silently stops growing waves, so gaps are
  filled by persistence before writing and the fill count is reported;
* a 2-D input grid (``my > 0``) with a non-positive ``dy`` -> rejected, because
  the weights and the ``dyinp`` written into INPGRID would disagree;
* irregular time levels -> rejected, because NONSTATIONARY carries one ``dt``
  and the maps after the first interval would be read at the wrong times.
"""

import datetime
import os

import numpy as np

KNOTS_TO_MS = 0.514444
KMH_TO_MS = 1.0 / 3.6

#: Largest timing error (seconds) tolerated between the supplied time levels and
#: the regular tbeg/dt/tend triple SWAN actually reads them at.
DT_TOLERANCE_S = 1.0


# ---------------------------------------------------------------------------
# Time levels
# ---------------------------------------------------------------------------

def time_step_hours(times, tol_seconds=DT_TOLERANCE_S):
    """Return the NONSTATIONARY ``[dt]`` in hours for equally spaced ``times``.

    SWAN reads the k-th wind map at ``tbeg + k*dt`` whatever stamps the caller
    had in mind, so an irregular series silently mis-times every field after the
    first interval.  This rejects that instead of quietly adopting ``times[1] -
    times[0]`` as dt.

    Raises
    ------
    ValueError
        if fewer than two levels are given, if the series is not strictly
        increasing, or if any interval departs from the first by more than
        ``tol_seconds``.
    """
    if len(times) < 2:
        raise ValueError("need at least two time levels for a NONSTATIONARY field")
    for i, t in enumerate(times):
        if not isinstance(t, datetime.datetime):
            raise ValueError(
                f"time level {i} is {type(t).__name__}, expected datetime")

    steps = [(times[i + 1] - times[i]).total_seconds()
             for i in range(len(times) - 1)]
    dt_s = steps[0]
    if dt_s <= 0:
        raise ValueError(
            f"wind time levels must be strictly increasing: times[0]={times[0]} "
            f"is not before times[1]={times[1]}")
    bad = [(i, s) for i, s in enumerate(steps) if abs(s - dt_s) > tol_seconds]
    if bad:
        i, s = bad[0]
        raise ValueError(
            f"wind time levels are not equally spaced: interval {i} "
            f"({times[i]} -> {times[i + 1]}) is {s:g} s but interval 0 is "
            f"{dt_s:g} s ({len(bad)} of {len(steps)} intervals differ by more "
            f"than {tol_seconds:g} s); a SWAN NONSTATIONARY input grid takes a "
            "single [dt], so resample the series onto a regular step first")
    return dt_s / 3600.0


def format_dt_hours(dt_h, n_intervals, tol_seconds=DT_TOLERANCE_S):
    """Format ``dt`` (hours) for INPGRID, checking the triple round-trips.

    The written ``[dt]`` has to carry ``tbeg`` to ``tend`` in ``n_intervals``
    steps; if the decimal text cannot do that within ``tol_seconds`` the caller
    would emit a NONSTATIONARY triple inconsistent with the maps in the file.
    """
    text = f"{dt_h:.10g}"
    drift = abs(float(text) - dt_h) * 3600.0 * n_intervals
    if drift > tol_seconds:
        raise ValueError(
            f"dt={dt_h!r} h cannot be written for INPGRID without drifting "
            f"{drift:.3f} s over {n_intervals} intervals (> {tol_seconds:g} s)")
    return text


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(stations, grid_info, times):
    """Validate station wind series and the target SWAN input grid.

    Parameters
    ----------
    stations : list of dict
        Each: {'id', 'x', 'y', 'u' (ndarray, m/s east), 'v' (ndarray, m/s north)}
        with ``u``/``v`` aligned to ``times``.
    grid_info : dict
        Keys 'xpinp', 'ypinp', 'dx', 'dy', 'mx', 'my'.  'dy' must be positive
        whenever 'my' > 0.
    times : list of datetime
        At least two, strictly increasing and equally spaced.

    Returns
    -------
    list of str : warnings

    Raises
    ------
    ValueError : on fatal problems
    """
    warnings = []
    if not stations:
        raise ValueError("no wind stations supplied")
    # Enforces >= 2 levels, strictly increasing, and a single equal dt -- the
    # NONSTATIONARY [tbeg] [dt] [tend] triple can represent nothing else.
    dt_h = time_step_hours(times)
    format_dt_hours(dt_h, len(times) - 1)

    for st in stations:
        for key in ('id', 'x', 'y', 'u', 'v'):
            if key not in st:
                raise ValueError(f"station missing key '{key}': {st.get('id')}")
        u = np.asarray(st['u'], dtype=float)
        v = np.asarray(st['v'], dtype=float)
        if u.shape != (len(times),) or v.shape != (len(times),):
            raise ValueError(
                f"station {st['id']}: u/v length {u.shape}/{v.shape} != "
                f"{len(times)} time levels")
        spd = np.sqrt(u ** 2 + v ** 2)
        good = spd[~np.isnan(spd)]
        if good.size == 0:
            raise ValueError(f"station {st['id']}: all wind samples missing")
        if good.max() > 60:
            warnings.append(
                f"UNIT TRAP: station {st['id']} max wind {good.max():.1f} m/s "
                "> 60 - knots or km/h rather than m/s?")
        if good.max() < 1.0:
            warnings.append(
                f"station {st['id']} max wind {good.max():.2f} m/s < 1 - "
                "wind essentially zero, GEN3 will not grow waves")
        frac_missing = float(np.isnan(spd).mean())
        if frac_missing > 0.2:
            warnings.append(
                f"station {st['id']}: {100 * frac_missing:.0f}% of wind samples "
                "missing - persistence fill will dominate")

    if grid_info.get('mx', 0) < 1 or grid_info.get('my', 0) < 0:
        raise ValueError(f"invalid wind input grid: {grid_info}")
    if grid_info.get('dx', 0) <= 0:
        raise ValueError(f"invalid wind grid spacing dx={grid_info.get('dx')}")
    # A 2-D input grid (my > 0) MUST carry a positive dy: the weights would
    # otherwise be built on a fallback y spacing while INPGRID still advertises
    # dyinp=0, i.e. a field that does not match the grid SWAN reads it onto.
    # Only the degenerate one-row grid (my == 0) may leave dy at 0/absent,
    # because then there is a single y level and the spacing is never used.
    if grid_info.get('my', 0) > 0 and grid_info.get('dy', 0) <= 0:
        raise ValueError(
            f"invalid wind grid spacing dy={grid_info.get('dy')} for my="
            f"{grid_info['my']}: a 2-D wind input grid needs dy > 0")

    # Stations outside the input grid still work (the field is extrapolated by
    # inverse-distance weighting) but it is worth flagging.
    x0, y0 = grid_info['xpinp'], grid_info['ypinp']
    x1 = x0 + grid_info['mx'] * grid_info['dx']
    y1 = y0 + grid_info['my'] * grid_info.get('dy', 0.0)
    for st in stations:
        if not (x0 <= st['x'] <= x1 and y0 <= st['y'] <= y1):
            warnings.append(
                f"station {st['id']} at ({st['x']:.0f},{st['y']:.0f}) lies "
                f"outside the wind input grid - field is extrapolated there")
    return warnings


def validate_outputs(output_path, n_times, n_rows, n_cols):
    """Read the written wind file back and check its shape and ranges."""
    results = {'status': 'unknown', 'file': output_path}
    if not os.path.isfile(output_path):
        results['status'] = 'FAIL: file not found'
        return results
    data = np.loadtxt(output_path)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    expect_rows = n_times * 2 * n_rows
    results['shape'] = tuple(int(s) for s in data.shape)
    results['expected_shape'] = (expect_rows, n_cols)
    results['n_nan'] = int(np.isnan(data).sum())
    spd = np.abs(data)
    results['component_range'] = f"{data.min():.2f}..{data.max():.2f} m/s"
    results['max_speed_component'] = float(spd.max())
    if data.shape != (expect_rows, n_cols):
        results['status'] = (f"FAIL: shape {data.shape} != expected "
                             f"({expect_rows}, {n_cols}) = "
                             f"{n_times} times x 2 components x {n_rows} rows")
    elif results['n_nan']:
        results['status'] = f"FAIL: {results['n_nan']} NaN in wind field"
    elif spd.max() > 60:
        results['status'] = f"FAIL: |component| {spd.max():.1f} m/s > 60"
    else:
        results['status'] = 'OK'
    return results


# ---------------------------------------------------------------------------
# Unit / gap helpers
# ---------------------------------------------------------------------------

def speed_to_ms(speed, unit='m/s'):
    """Convert a wind speed array to m/s ('m/s', 'knots', 'km/h', 'mph')."""
    speed = np.asarray(speed, dtype=float)
    factors = {'m/s': 1.0, 'ms': 1.0, 'knots': KNOTS_TO_MS, 'kt': KNOTS_TO_MS,
               'km/h': KMH_TO_MS, 'kmh': KMH_TO_MS, 'mph': 0.44704}
    if unit not in factors:
        raise ValueError(f"unknown wind speed unit '{unit}'")
    return speed * factors[unit]


def fill_gaps(arr):
    """Persistence-fill NaN gaps forward then backward.

    Returns
    -------
    (ndarray, int) : filled array and the number of values filled.
    """
    a = np.array(arr, dtype=float)
    n_missing = int(np.isnan(a).sum())
    last = None
    for i in range(a.size):
        if not np.isnan(a[i]):
            last = a[i]
        elif last is not None:
            a[i] = last
    last = None
    for i in range(a.size - 1, -1, -1):
        if not np.isnan(a[i]):
            last = a[i]
        elif last is not None:
            a[i] = last
    if np.isnan(a).any():
        raise ValueError("cannot fill wind gaps: series is entirely missing")
    return a, n_missing


def idw_weights(stations, grid_info, power=2.0, min_dist=1.0):
    """Inverse-distance weights of each station at every input-grid point.

    Returns
    -------
    ndarray, shape (n_stations, my+1, mx+1), summing to 1 along axis 0.
    """
    mx, my = grid_info['mx'], grid_info.get('my', 0)
    dy = grid_info.get('dy', 0.0)
    # No silent fallback spacing: with my > 0 a non-positive dy would place every
    # row at the same y and disagree with the dyinp written into INPGRID.
    if my > 0 and dy <= 0:
        raise ValueError(
            f"idw_weights: dy={dy} is not positive for my={my}; the wind input "
            "grid spacing must match the INPGRID dyinp")
    x = grid_info['xpinp'] + np.arange(mx + 1) * grid_info['dx']
    y = grid_info['ypinp'] + np.arange(my + 1) * dy
    xx, yy = np.meshgrid(x, y)          # row 0 == lowest y  (idla=4 order)

    d = np.stack([np.hypot(xx - st['x'], yy - st['y']) for st in stations])
    d = np.maximum(d, min_dist)
    w = 1.0 / d ** power
    return w / w.sum(axis=0, keepdims=True)


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert_wind_forcing(stations, grid_info, times, output_path,
                         speed_unit='m/s', idw_power=2.0,
                         validation_station_id=None):
    """Write a SWAN non-stationary wind field from one or more station series.

    A single station gives a spatially UNIFORM (but time-varying) field; two or
    more give an inverse-distance-weighted field, which is the honest way to
    represent the large-scale wind gradient across a multi-hundred-km domain
    when no gridded reanalysis is on disk.

    INDEPENDENCE: pass ``validation_station_id`` whenever the run is scored at
    a station.  Wind is the HIGHEST-sensitivity driver of HSIGN in deep/open
    water, so forcing the domain with the scored buoy's OWN anemometer makes
    the hindcast circular; this refuses that instead of accepting it silently.
    Use ``fetch_gridded_wind`` + :func:`convert_gridded_wind_forcing` for an
    independent gridded analysis.

    Parameters
    ----------
    stations : list of dict
        {'id', 'x', 'y', 'u', 'v'} -- u east / v north VELOCITY components
        (use ``read_ndbc_buoy.wind_to_components``), already at 10 m.
    grid_info : dict
        {'xpinp','ypinp','dx','dy','mx','my'} of the WIND input grid; 'dy' must
        be positive unless 'my' == 0.
    times : list of datetime
        Time levels, equally spaced -- enforced, not assumed, so the emitted
        INPGRID NONSTATIONARY [tbeg] [dt] [tend] triple always matches the maps
        written to ``output_path``.
    output_path : str
    speed_unit : str
        Unit of the supplied components, converted to m/s.
    idw_power : float

    Returns
    -------
    dict : validation results, plus 'inpgrid'/'readinp' command strings and
           'n_filled' (persistence-filled samples per station).
    """
    stations = [dict(st) for st in stations]
    if validation_station_id is not None:
        ids = [str(st.get('id')) for st in stations]
        if str(validation_station_id) in ids:
            raise ValueError(
                f"wind station list {ids} contains the VALIDATION station "
                f"'{validation_station_id}': the scored buoy's own anemometer "
                "cannot force the domain whose HSIGN is scored at that buoy "
                "(wind->HSIGN is a HIGH-sensitivity edge, so this is a "
                "circular hindcast, not an independent one). Use "
                "fetch_gridded_wind.fetch_gridded_wind() + "
                "convert_gridded_wind_forcing(), or drop that station.")
    for st in stations:
        st['u'] = speed_to_ms(st['u'], speed_unit)
        st['v'] = speed_to_ms(st['v'], speed_unit)

    warnings = validate_inputs(stations, grid_info, times)
    for w in warnings:
        print(f"[WARNING] {w}")

    n_filled = {}
    for st in stations:
        st['u'], nu = fill_gaps(st['u'])
        st['v'], nv = fill_gaps(st['v'])
        n_filled[st['id']] = {'u': nu, 'v': nv}

    w = idw_weights(stations, grid_info, power=idw_power)
    n_rows, n_cols = w.shape[1], w.shape[2]

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as f:
        for k in range(len(times)):
            u_k = np.tensordot(np.array([st['u'][k] for st in stations]), w,
                               axes=(0, 0))
            v_k = np.tensordot(np.array([st['v'][k] for st in stations]), w,
                               axes=(0, 0))
            # x-component map first, then y-component map (SWAN vector input),
            # each written lowest-y row first to match idla=4.
            for field in (u_k, v_k):
                for row in field:
                    f.write(' '.join(f'{val:.3f}' for val in row) + '\n')

    results = validate_outputs(output_path, len(times), n_rows, n_cols)
    results['warnings'] = warnings
    results['n_filled'] = n_filled
    results['n_stations'] = len(stations)
    results['n_times'] = len(times)

    # Equal spacing was proved in validate_inputs, so this dt describes every
    # interval and not just the first one.
    dt_h = time_step_hours(times)
    results['dt_hours'] = dt_h
    results['inpgrid'] = (
        f"INPGRID WIND REGULAR {grid_info['xpinp']:.1f} {grid_info['ypinp']:.1f} "
        f"0. {grid_info['mx']} {grid_info.get('my', 0)} "
        f"{grid_info['dx']:.4f} {grid_info.get('dy', 0.0):.4f} NONSTATIONARY "
        f"{times[0].strftime('%Y%m%d.%H%M%S')} "
        f"{format_dt_hours(dt_h, len(times) - 1)} HR "
        f"{times[-1].strftime('%Y%m%d.%H%M%S')}")
    results['readinp'] = (
        f"READINP WIND 1.0 '{os.path.basename(output_path)}' 4 0 FREE")
    return results



# ---------------------------------------------------------------------------
# Gridded conversion (independent reanalysis / analysis source)
# ---------------------------------------------------------------------------

def swan_node_lonlat(grid_info, lon0, lat0, m_per_deg_lon, m_per_deg_lat):
    """Longitude/latitude of every node of a SWAN input grid.

    The SWAN grid is defined in LOCAL metres measured from the domain origin
    ``(lon0, lat0)`` on the equirectangular scaling the caller used to build
    it, so the inverse mapping has to use the SAME two metres-per-degree
    constants.  Returns two ``(my+1, mx+1)`` arrays with row 0 at the LOWEST y,
    i.e. the ``idla=4`` order the wind file is written in.
    """
    mx, my = grid_info['mx'], grid_info.get('my', 0)
    dy = grid_info.get('dy', 0.0)
    if my > 0 and dy <= 0:
        raise ValueError(
            f"swan_node_lonlat: dy={dy} is not positive for my={my}")
    if m_per_deg_lon <= 0 or m_per_deg_lat <= 0:
        raise ValueError("metres-per-degree constants must be positive")
    x = grid_info['xpinp'] + np.arange(mx + 1) * grid_info['dx']
    y = grid_info['ypinp'] + np.arange(my + 1) * dy
    xx, yy = np.meshgrid(x, y)
    return (lon0 + xx / m_per_deg_lon), (lat0 + yy / m_per_deg_lat)


def convert_gridded_wind_forcing(u_nodes, v_nodes, grid_info, times,
                                 output_path, speed_unit='m/s'):
    """Write a SWAN non-stationary wind field from an already-regridded field.

    This is the GRIDDED counterpart of :func:`convert_wind_forcing`: the caller
    supplies U/V already interpolated onto the wind input grid's nodes (see
    ``fetch_gridded_wind.regrid_to_swan_grid``), so no station geometry or IDW
    is involved.

    Parameters
    ----------
    u_nodes, v_nodes : ndarray, shape (n_times, my+1, mx+1)
        Eastward / northward VELOCITY components, row 0 at the LOWEST y to
        match ``idla=4``.
    grid_info : dict
        {'xpinp','ypinp','dx','dy','mx','my'} of the WIND input grid.
    times : list of datetime
        Equally spaced -- enforced, so the emitted NONSTATIONARY triple always
        matches the maps in the file.

    Returns
    -------
    dict : validation results plus 'inpgrid'/'readinp' command strings and
           'mean_spatial_range_ms' (the domain-wide speed spread averaged over
           time; ~0 means the "gridded" field collapsed to a constant).
    """
    u_nodes = speed_to_ms(np.asarray(u_nodes, dtype=float), speed_unit)
    v_nodes = speed_to_ms(np.asarray(v_nodes, dtype=float), speed_unit)

    n_rows = grid_info.get('my', 0) + 1
    n_cols = grid_info['mx'] + 1
    expect = (len(times), n_rows, n_cols)
    if u_nodes.shape != expect or v_nodes.shape != expect:
        raise ValueError(
            f"gridded wind shape {u_nodes.shape}/{v_nodes.shape} != {expect} "
            f"= (n_times, my+1, mx+1); a SWAN INPGRID of {grid_info['mx']}x"
            f"{grid_info.get('my', 0)} MESHES carries (mx+1) x (my+1) VALUES")
    if not np.isfinite(u_nodes).all() or not np.isfinite(v_nodes).all():
        raise ValueError(
            "gridded wind contains non-finite values; fill land/masked cells "
            "before writing (fetch_gridded_wind.fill_masked_cells) -- SWAN "
            "stops growing waves silently on a NaN wind field")
    # Equal spacing / a representable dt are proved here, not assumed.
    dt_h = time_step_hours(times)
    format_dt_hours(dt_h, len(times) - 1)
    if grid_info.get('mx', 0) < 1 or grid_info.get('my', 0) < 0:
        raise ValueError(f"invalid wind input grid: {grid_info}")
    if grid_info.get('dx', 0) <= 0:
        raise ValueError(f"invalid wind grid spacing dx={grid_info.get('dx')}")
    if grid_info.get('my', 0) > 0 and grid_info.get('dy', 0) <= 0:
        raise ValueError(
            f"invalid wind grid spacing dy={grid_info.get('dy')} for my="
            f"{grid_info['my']}: a 2-D wind input grid needs dy > 0")

    spd = np.hypot(u_nodes, v_nodes)
    flat = spd.reshape(spd.shape[0], -1)
    mean_range = float(np.mean(flat.max(axis=1) - flat.min(axis=1)))

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as f:
        for k in range(len(times)):
            # x-component map first, then y-component map (SWAN vector input),
            # each written lowest-y row first to match idla=4.
            for field in (u_nodes[k], v_nodes[k]):
                for row in field:
                    f.write(' '.join(f'{val:.3f}' for val in row) + '\n')

    results = validate_outputs(output_path, len(times), n_rows, n_cols)
    results['n_times'] = len(times)
    results['dt_hours'] = dt_h
    results['source'] = 'gridded'
    results['mean_spatial_range_ms'] = mean_range
    results['max_speed_ms'] = float(spd.max())
    if results['status'] == 'OK' and mean_range < 1e-6 and n_rows * n_cols > 1:
        results['status'] = (
            'FAIL: gridded wind field is spatially uniform at every time level '
            '- the regrid collapsed to a domain constant')
    results['inpgrid'] = (
        f"INPGRID WIND REGULAR {grid_info['xpinp']:.1f} {grid_info['ypinp']:.1f} "
        f"0. {grid_info['mx']} {grid_info.get('my', 0)} "
        f"{grid_info['dx']:.4f} {grid_info.get('dy', 0.0):.4f} NONSTATIONARY "
        f"{times[0].strftime('%Y%m%d.%H%M%S')} "
        f"{format_dt_hours(dt_h, len(times) - 1)} HR "
        f"{times[-1].strftime('%Y%m%d.%H%M%S')}")
    results['readinp'] = (
        f"READINP WIND 1.0 '{os.path.basename(output_path)}' 4 0 FREE")
    return results

if __name__ == '__main__':
    # Smoke test: two stations, 3 h, 2x1 mesh input grid -> 3*2*2 = 12 rows x 3.
    times = [datetime.datetime(2020, 1, 1) + datetime.timedelta(hours=i)
             for i in range(3)]
    sts = [
        {'id': 'A', 'x': 0.0, 'y': 0.0, 'u': [10., 11., 12.], 'v': [0., 0., 0.]},
        {'id': 'B', 'x': 2000.0, 'y': 1000.0, 'u': [-5., -5., -5.],
         'v': [3., 3., np.nan]},
    ]
    grid = {'xpinp': 0.0, 'ypinp': 0.0, 'dx': 1000.0, 'dy': 1000.0,
            'mx': 2, 'my': 1}
    print(convert_wind_forcing(sts, grid, times, './_wind_smoke.wnd'))
