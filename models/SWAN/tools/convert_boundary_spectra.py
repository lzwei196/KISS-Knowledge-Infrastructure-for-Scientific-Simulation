#!/usr/bin/env python3
"""
Convert global wave data (ERA5, buoy CSV, parametric) to SWAN boundary
spectral format (.tpar, .spc).

Pipeline stage: 2 — Boundary spectra preparation
Pattern: validate_inputs → process → validate_outputs

Supported input formats:
  - CSV with columns: time, Hs, Tp, pdir, ms (→ TPAR)
  - CSV with columns: time, Hs, Tp, pdir, ms + frequency info (→ 1D/2D .spc)
  - Parametric dict with scalar values (→ single TPAR line)

Output formats:
  - .tpar: parametric boundary conditions (Hs, Tp, pdir, ms time series)
  - .spc:  1D or 2D spectral boundary conditions

Unit conversions handled:
  - Hs: cm → m (divide by 100)
  - Period: if provided as frequency (Hz), convert Tp = 1/fp
  - Direction: Cartesian → nautical (270 - cart_dir) mod 360
  - Spreading: degrees σ → power ms (ms ≈ (2/σ_rad²) - 1)
"""

import numpy as np
import datetime
import os
import sys

# Append source for pyswan imports
PYSWAN_ROOT = os.path.join(os.path.dirname(__file__), '..', '..', 'source', 'repo')
if os.path.isdir(PYSWAN_ROOT):
    sys.path.insert(0, PYSWAN_ROOT)
# pyswan is pip-installed into the HydroCraft python_env, NOT into the system
# interpreter, and this KI ships no ../../source/repo checkout.  Mirror the
# search path used by preflight_check.py so the tool imports under a plain
# `python3` too.
_PENV = "/mnt/disk1/Hydrocraft_server/python_env/lib/python3.12/site-packages"
if os.path.isdir(_PENV) and _PENV not in sys.path:
    sys.path.append(_PENV)
try:
    from pyswan import oceanwaves as ow, swan
except ImportError:
    sys.path.insert(0, os.path.join(PYSWAN_ROOT, 'pyswan'))
    import oceanwaves as ow
    import swan


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(wave_params, fmt='tpar'):
    """
    Validate wave parameter inputs before conversion.

    Parameters
    ----------
    wave_params : dict
        Must contain 't', 'Hs', 'Tp', 'pdir', 'ms'.
        For spectral formats, also 'f' (frequency array).
    fmt : str
        Target format: 'tpar', '1d', '2d'.

    Returns
    -------
    list of str : warnings (empty = all OK)

    Raises
    ------
    ValueError : on fatal validation errors
    """
    warnings = []

    required = ['t', 'Hs', 'Tp', 'pdir', 'ms']
    for key in required:
        if key not in wave_params:
            raise ValueError(f"Missing required key: '{key}'")

    # Check Hs range
    hs_arr = np.atleast_1d(wave_params['Hs'])
    if np.any(hs_arr < 0):
        raise ValueError("Hs contains negative values")
    if np.any(hs_arr > 30):
        warnings.append(f"UNIT TRAP: max Hs={np.nanmax(hs_arr):.1f} > 30 m — "
                         "possible cm→m conversion needed (divide by 100)")
    if np.nanmax(hs_arr) < 0.01 and np.nanmax(hs_arr) > 0:
        warnings.append(f"UNIT TRAP: max Hs={np.nanmax(hs_arr):.4f} very small — "
                         "possible data in km instead of m")

    # Check Tp range
    tp_arr = np.atleast_1d(wave_params['Tp'])
    if np.any(tp_arr <= 0):
        raise ValueError("Tp contains non-positive values")
    if np.any(tp_arr > 30):
        warnings.append(f"UNIT TRAP: max Tp={np.nanmax(tp_arr):.1f} > 30 s — "
                         "check if Tp is actually frequency (Hz)")
    if np.nanmax(tp_arr) < 0.5:
        warnings.append(f"UNIT TRAP: max Tp={np.nanmax(tp_arr):.3f} < 0.5 — "
                         "possible Hz values, convert Tp = 1/f")

    # Check direction range
    pdir_arr = np.atleast_1d(wave_params['pdir'])
    if np.any(np.abs(pdir_arr) > 720):
        warnings.append("Direction values >720 — possible radians instead of degrees")

    # Check spreading
    ms_arr = np.atleast_1d(wave_params['ms'])
    if np.any(ms_arr < 0):
        raise ValueError("Spreading power ms must be non-negative")
    if np.any(ms_arr > 100):
        warnings.append(f"ms={np.nanmax(ms_arr)} > 100 — unusually narrow spreading")

    # Spectral checks
    if fmt in ('1d', '2d'):
        if 'f' not in wave_params:
            raise ValueError(f"Frequency array 'f' required for {fmt} format")
        f_arr = np.atleast_1d(wave_params['f'])
        if f_arr[0] <= 0:
            raise ValueError("Frequencies must be positive")
        if np.any(f_arr > 10):
            warnings.append("Frequencies > 10 Hz — check if values are in rad/s "
                             "(divide by 2π)")

    if fmt == '2d':
        if 'directions' not in wave_params:
            raise ValueError("Direction array 'directions' required for 2d format")

    return warnings


def validate_outputs(output_path, fmt='tpar', expected_hs=None):
    """
    Validate written SWAN boundary file by reading it back.

    Parameters
    ----------
    output_path : str
        Path to output file.
    fmt : str
        File format: 'tpar', '1d', '2d'.
    expected_hs : float, optional
        Expected Hs for round-trip verification.

    Returns
    -------
    dict : validation results with 'status', 'hs_check', 'n_timesteps'
    """
    results = {'status': 'unknown', 'file': output_path}

    if not os.path.exists(output_path):
        results['status'] = 'FAIL: output file not found'
        return results

    fsize = os.path.getsize(output_path)
    if fsize == 0:
        results['status'] = 'FAIL: output file is empty'
        return results
    results['file_size_bytes'] = fsize

    try:
        if fmt == 'tpar':
            with open(output_path, 'r') as f:
                spec = swan.from_file0D(f)
            results['n_timesteps'] = len(np.atleast_1d(spec.t))
            if expected_hs is not None:
                hs_read = np.nanmean(np.atleast_1d(spec.Hs))
                hs_diff = abs(hs_read - expected_hs) / max(expected_hs, 1e-10)
                results['hs_check'] = f"read={hs_read:.3f}, expected={expected_hs:.3f}, diff={hs_diff:.4f}"
                if hs_diff > 0.01:
                    results['status'] = f'WARNING: Hs mismatch > 1%'
                else:
                    results['status'] = 'OK'
            else:
                results['status'] = 'OK (no round-trip check)'

        elif fmt == '1d':
            with open(output_path, 'r') as f:
                spec = swan.from_file1D(f)
            results['n_timesteps'] = len(spec.t)
            results['n_frequencies'] = len(spec.f)
            hs = spec.Hm0()
            results['Hm0_range'] = f"{np.nanmin(hs):.3f} - {np.nanmax(hs):.3f} m"
            if expected_hs is not None:
                hs_mean = np.nanmean(hs)
                hs_diff = abs(hs_mean - expected_hs) / max(expected_hs, 1e-10)
                if hs_diff > 0.05:
                    results['status'] = f'WARNING: mean Hs mismatch > 5%'
                else:
                    results['status'] = 'OK'
            else:
                results['status'] = 'OK'

        elif fmt == '2d':
            with open(output_path, 'r') as f:
                spec = swan.from_file2D(f)
            results['n_timesteps'] = len(spec.t)
            results['n_frequencies'] = len(spec.f)
            results['n_directions'] = len(spec.direction)
            hs = spec.Hm0()
            results['Hm0_range'] = f"{np.nanmin(hs):.3f} - {np.nanmax(hs):.3f} m"
            results['status'] = 'OK'

    except Exception as e:
        results['status'] = f'FAIL: read-back error: {str(e)}'

    return results


# ---------------------------------------------------------------------------
# Unit conversion helpers
# ---------------------------------------------------------------------------

def hs_cm_to_m(hs_cm):
    """Convert significant wave height from centimeters to meters."""
    return np.asarray(hs_cm) / 100.0


def freq_to_period(freq_hz):
    """Convert peak frequency (Hz) to peak period (s)."""
    freq = np.asarray(freq_hz, dtype=float)
    if np.any(freq <= 0):
        raise ValueError("Frequency must be positive for Tp = 1/fp conversion")
    return 1.0 / freq


def cartesian_to_nautical(cart_dir_deg):
    """
    Convert Cartesian wave direction (degrees, math convention:
    direction TO which waves propagate, CCW from East) to nautical
    convention (direction FROM which waves come, CW from North).
    """
    naut = (270.0 - np.asarray(cart_dir_deg)) % 360.0
    return naut


def spreading_deg_to_power(sigma_deg):
    """
    Convert directional spread σ (in degrees) to cos^ms spreading power.
    Approximate relation: ms ≈ (2 / σ_rad²) - 1
    """
    sigma_rad = np.asarray(sigma_deg) * np.pi / 180.0
    sigma_rad = np.maximum(sigma_rad, 0.01)  # avoid division by zero
    ms = (2.0 / sigma_rad**2) - 1.0
    return np.maximum(ms, 1.0)  # ms >= 1


# ---------------------------------------------------------------------------
# Main conversion functions
# ---------------------------------------------------------------------------

def convert_to_tpar(wave_params, output_path, unit_conversions=None):
    """
    Convert wave parameters to SWAN TPAR format.

    Parameters
    ----------
    wave_params : dict
        Keys: 't' (list of datetime), 'Hs' (m), 'Tp' (s), 'pdir' (deg nautical), 'ms'
    output_path : str
        Path for output .tpar file.
    unit_conversions : dict, optional
        Keys: 'hs' ('cm_to_m'), 'tp' ('freq_to_period'),
              'pdir' ('cartesian_to_nautical'), 'ms' ('deg_to_power')

    Returns
    -------
    dict : validation results
    """
    # Apply unit conversions
    params = dict(wave_params)
    if unit_conversions:
        if unit_conversions.get('hs') == 'cm_to_m':
            params['Hs'] = hs_cm_to_m(params['Hs'])
        if unit_conversions.get('tp') == 'freq_to_period':
            params['Tp'] = freq_to_period(params['Tp'])
        if unit_conversions.get('pdir') == 'cartesian_to_nautical':
            params['pdir'] = cartesian_to_nautical(params['pdir'])
        if unit_conversions.get('ms') == 'deg_to_power':
            params['ms'] = spreading_deg_to_power(params['ms'])

    # Validate
    warnings = validate_inputs(params, fmt='tpar')
    for w in warnings:
        print(f"[WARNING] {w}")

    # Build Spec0
    Sp0 = ow.Spec0()
    Sp0.t = params['t']
    Sp0.Hs = np.atleast_1d(params['Hs'])
    Sp0.Tp = np.atleast_1d(params['Tp'])
    Sp0.pdir = np.atleast_1d(params['pdir'])
    Sp0.ms = np.atleast_1d(params['ms'])

    # Handle scalar case
    if len(Sp0.Hs) == 1:
        Sp0.Hs = float(Sp0.Hs[0])
        Sp0.Tp = float(Sp0.Tp[0])
        Sp0.pdir = float(Sp0.pdir[0])
        Sp0.ms = float(Sp0.ms[0])
        if isinstance(Sp0.t, (list, np.ndarray)):
            Sp0.t = Sp0.t[0]

    # Write
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as f:
        swan.to_file0D(Sp0, f)

    # Validate output
    expected_hs = float(np.nanmean(np.atleast_1d(params['Hs'])))
    results = validate_outputs(output_path, fmt='tpar', expected_hs=expected_hs)
    results['warnings'] = warnings
    return results


def convert_to_spec1d(wave_params, output_path, gamma=3.3, unit_conversions=None):
    """
    Convert wave parameters to SWAN 1D spectral boundary (.spc).

    Parameters
    ----------
    wave_params : dict
        Keys: 't', 'Hs', 'Tp', 'pdir', 'ms', 'f' (frequency array Hz),
              'lon', 'lat' (or 'x', 'y')
    output_path : str
    gamma : float
        JONSWAP peak enhancement factor (default 3.3).
    unit_conversions : dict, optional

    Returns
    -------
    dict : validation results
    """
    params = dict(wave_params)
    if unit_conversions:
        if unit_conversions.get('hs') == 'cm_to_m':
            params['Hs'] = hs_cm_to_m(params['Hs'])
        if unit_conversions.get('tp') == 'freq_to_period':
            params['Tp'] = freq_to_period(params['Tp'])
        if unit_conversions.get('pdir') == 'cartesian_to_nautical':
            params['pdir'] = cartesian_to_nautical(params['pdir'])
        if unit_conversions.get('ms') == 'deg_to_power':
            params['ms'] = spreading_deg_to_power(params['ms'])

    warnings = validate_inputs(params, fmt='1d')
    for w in warnings:
        print(f"[WARNING] {w}")

    t = params['t'] if isinstance(params['t'], list) else [params['t']]
    f = np.asarray(params['f'])
    lon = params.get('lon', [np.nan])
    lat = params.get('lat', [np.nan])
    x = params.get('x', [np.nan])
    y = params.get('y', [np.nan])

    Sp1 = ow.Spec1(f=f, t=t, lon=lon, lat=lat, x=x, y=y)
    Sp1.from_jonswap(float(params['Hs']), float(params['Tp']),
                     float(params['pdir']), float(params['ms']),
                     gamma=gamma)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as fid:
        swan.to_file1D(Sp1, fid)

    results = validate_outputs(output_path, fmt='1d',
                                expected_hs=float(params['Hs']))
    results['warnings'] = warnings
    return results


def convert_to_spec2d(wave_params, output_path, gamma=3.3, unit_conversions=None):
    """
    Convert wave parameters to SWAN 2D spectral boundary (.spc).

    Parameters
    ----------
    wave_params : dict
        Keys: 't', 'Hs', 'Tp', 'pdir', 'ms', 'f', 'directions',
              'lon', 'lat' (or 'x', 'y')
    output_path : str
    gamma : float
    unit_conversions : dict, optional

    Returns
    -------
    dict : validation results
    """
    params = dict(wave_params)
    if unit_conversions:
        if unit_conversions.get('hs') == 'cm_to_m':
            params['Hs'] = hs_cm_to_m(params['Hs'])
        if unit_conversions.get('tp') == 'freq_to_period':
            params['Tp'] = freq_to_period(params['Tp'])
        if unit_conversions.get('pdir') == 'cartesian_to_nautical':
            params['pdir'] = cartesian_to_nautical(params['pdir'])
        if unit_conversions.get('ms') == 'deg_to_power':
            params['ms'] = spreading_deg_to_power(params['ms'])

    warnings = validate_inputs(params, fmt='2d')
    for w in warnings:
        print(f"[WARNING] {w}")

    t = params['t'] if isinstance(params['t'], list) else [params['t']]
    f = np.asarray(params['f'])
    directions = list(params['directions'])
    lon = params.get('lon', [np.nan])
    lat = params.get('lat', [np.nan])
    x = params.get('x', [np.nan])
    y = params.get('y', [np.nan])

    Sp2 = ow.Spec2(f=f, direction=directions, t=t, lon=lon, lat=lat, x=x, y=y)
    Sp2.from_jonswap(float(params['Hs']), float(params['Tp']),
                     float(params['pdir']), float(params['ms']),
                     gamma=gamma)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as fid:
        swan.to_file2D(Sp2, fid)

    results = validate_outputs(output_path, fmt='2d',
                                expected_hs=float(params['Hs']))
    results['warnings'] = warnings
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert wave data to SWAN boundary spectral format')
    parser.add_argument('--format', choices=['tpar', '1d', '2d'], default='tpar',
                        help='Output format (default: tpar)')
    parser.add_argument('--hs', type=float, required=True, help='Sig. wave height (m)')
    parser.add_argument('--tp', type=float, required=True, help='Peak period (s)')
    parser.add_argument('--pdir', type=float, required=True, help='Peak direction (deg, nautical)')
    parser.add_argument('--ms', type=float, default=4.0, help='Spreading power (default: 4)')
    parser.add_argument('--time', default='20160101.000000',
                        help='Time stamp (YYYYMMDD.HHMMSS)')
    parser.add_argument('--output', '-o', required=True, help='Output file path')
    parser.add_argument('--gamma', type=float, default=3.3, help='JONSWAP gamma')
    args = parser.parse_args()

    t = datetime.datetime.strptime(args.time, '%Y%m%d.%H%M%S')
    params = {
        't': [t],
        'Hs': args.hs,
        'Tp': args.tp,
        'pdir': args.pdir,
        'ms': args.ms,
    }

    if args.format == 'tpar':
        result = convert_to_tpar(params, args.output)
    elif args.format == '1d':
        params['f'] = np.linspace(0.025, 1.0, 40)
        params['lon'] = [0.0]
        params['lat'] = [0.0]
        result = convert_to_spec1d(params, args.output, gamma=args.gamma)
    elif args.format == '2d':
        params['f'] = np.linspace(0.025, 1.0, 40)
        params['directions'] = list(np.arange(-12, 13) * 15)
        params['lon'] = [0.0]
        params['lat'] = [0.0]
        result = convert_to_spec2d(params, args.output, gamma=args.gamma)

    print(f"Result: {result['status']}")
    if result.get('warnings'):
        for w in result['warnings']:
            print(f"  WARNING: {w}")
