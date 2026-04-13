#!/usr/bin/env python3
"""
Parse SWAN output files to CSV and pandas DataFrames.

Pipeline stage: 6 — Output parsing and analysis
Pattern: validate_inputs → process → validate_outputs

Supported SWAN output formats:
  - TABLE (.crv): tabulated output along curves (XP, YP, Hsig, Tp, etc.)
  - SPEC1D (.s1d): 1D spectral output at specified points
  - SPEC2D (.s2d, .spc): 2D spectral output at specified points
  - TPAR (.tpar): parametric time series

Output:
  - CSV files with labeled columns and units
  - pandas DataFrames (if pandas available)
  - Spectral objects (Spec0, Spec1, Spec2) for analysis

Key variables extracted:
  - Hsig (Hs): significant wave height [m]
  - RTpeak (Tp): relative peak period [s]
  - Tm01, Tm02: mean wave periods [s]
  - PkDir: peak wave direction [deg]
  - Depth: water depth [m]
  - XP, YP: coordinates [m or deg]
"""

import os
import sys
import re
import numpy as np

PYSWAN_ROOT = os.path.join(os.path.dirname(__file__), '..', '..', 'source', 'repo')
if os.path.isdir(PYSWAN_ROOT):
    sys.path.insert(0, PYSWAN_ROOT)
try:
    from pyswan import oceanwaves as ow, swan
except ImportError:
    sys.path.insert(0, os.path.join(PYSWAN_ROOT, 'pyswan'))
    import oceanwaves as ow
    import swan


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(file_path, fmt=None):
    """
    Validate SWAN output file before parsing.

    Parameters
    ----------
    file_path : str
    fmt : str, optional
        Format hint: 'table', 'spec1d', 'spec2d', 'tpar'. Auto-detected if None.

    Returns
    -------
    dict : {'status', 'format', 'file_size'}
    """
    results = {'status': 'unknown', 'file': file_path}

    if not os.path.exists(file_path):
        results['status'] = f'FAIL: file not found: {file_path}'
        return results

    fsize = os.path.getsize(file_path)
    if fsize == 0:
        results['status'] = 'FAIL: file is empty'
        return results
    results['file_size_bytes'] = fsize

    # Auto-detect format
    if fmt is None:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ('.crv', '.tab'):
            fmt = 'table'
        elif ext in ('.s1d',):
            fmt = 'spec1d'
        elif ext in ('.s2d', '.spc'):
            # Need to check header for 1D vs 2D
            with open(file_path, 'r') as f:
                content = f.read(2000)
            if 'CDIR' in content or 'NDIR' in content:
                # Check if direction block exists after frequency block
                lines = content.split('\n')
                after_freq = False
                for line in lines:
                    stripped = line.strip().upper()
                    if stripped in ('AFREQ', 'RFREQ'):
                        after_freq = True
                    elif after_freq and stripped in ('CDIR', 'NDIR'):
                        fmt = 'spec2d'
                        break
                    elif after_freq and stripped == 'QUANT':
                        fmt = 'spec1d'
                        break
                if fmt is None:
                    fmt = 'spec2d'
            else:
                fmt = 'spec1d'
        elif ext == '.tpar':
            fmt = 'tpar'
        else:
            fmt = 'table'  # default guess

    results['format'] = fmt
    results['status'] = 'OK'
    return results


def validate_parsed_data(data, fmt):
    """
    Validate parsed data for physical reasonableness.

    Parameters
    ----------
    data : dict or object
        Parsed data.
    fmt : str
        Format that was parsed.

    Returns
    -------
    list of str : warnings
    """
    warnings = []

    if fmt == 'table' and isinstance(data, dict):
        if 'Hsig' in data or 'HSIG' in data:
            hs_key = 'Hsig' if 'Hsig' in data else 'HSIG'
            hs = np.asarray(data[hs_key])
            if np.any(hs < 0):
                warnings.append("Negative Hs values found — check for exception values")
            if np.nanmax(hs) > 25:
                warnings.append(f"Max Hs={np.nanmax(hs):.1f} m — extreme value")
            if np.all(hs == 0):
                warnings.append("All Hs = 0 — SWAN may not have run correctly")

    elif fmt in ('spec1d', 'spec2d'):
        if hasattr(data, 'energy'):
            if np.all(np.isnan(data.energy)):
                warnings.append("All spectral energy is NaN — check SWAN run")
            if hasattr(data, 'Hm0'):
                try:
                    hm0 = data.Hm0()
                    if np.nanmax(hm0) > 25:
                        warnings.append(f"Max Hm0={np.nanmax(hm0):.1f} m — extreme")
                except Exception:
                    pass

    return warnings


# ---------------------------------------------------------------------------
# TABLE (.crv) parser
# ---------------------------------------------------------------------------

def parse_table(file_path):
    """
    Parse SWAN TABLE output (.crv file).

    The TABLE format has a header with % comment lines containing:
      - Run ID and SWAN version
      - Column names
      - Column units

    Parameters
    ----------
    file_path : str
        Path to .crv file.

    Returns
    -------
    dict : {column_name: np.array, 'columns': [...], 'units': [...],
            'run_info': str}
    """
    val = validate_inputs(file_path, 'table')
    if 'FAIL' in val['status']:
        raise FileNotFoundError(val['status'])

    with open(file_path, 'r') as f:
        lines = f.readlines()

    # Parse header
    header_lines = []
    data_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith('%'):
            header_lines.append(line.strip().lstrip('%').strip())
            data_start = i + 1
        else:
            break

    # Extract column names and units from header
    run_info = ''
    column_names = []
    column_units = []

    for hl in header_lines:
        if 'Run:' in hl:
            run_info = hl
        elif hl and not hl.startswith('['):
            # Could be column names
            parts = hl.split()
            if len(parts) > 2 and all(p.replace('.', '').isalpha() or
                                       p.isalnum() for p in parts):
                column_names = parts
        elif hl.startswith('[') or (hl and '[' in hl):
            # Units line
            units = re.findall(r'\[([^\]]+)\]', hl)
            if units:
                column_units = units

    # Parse data
    data_lines = []
    for line in lines[data_start:]:
        stripped = line.strip()
        if stripped and not stripped.startswith('%'):
            try:
                values = [float(v) for v in stripped.split()]
                data_lines.append(values)
            except ValueError:
                continue

    if not data_lines:
        return {'columns': column_names, 'units': column_units,
                'run_info': run_info, 'n_rows': 0}

    data_array = np.array(data_lines)

    # Build result dict
    result = {
        'columns': column_names,
        'units': column_units,
        'run_info': run_info,
        'n_rows': len(data_lines),
        'n_cols': data_array.shape[1],
        'data': data_array
    }

    # Map columns to named arrays
    for j, name in enumerate(column_names):
        if j < data_array.shape[1]:
            result[name] = data_array[:, j]

    # Validate
    warnings = validate_parsed_data(result, 'table')
    result['warnings'] = warnings

    return result


def table_to_csv(file_path, output_csv):
    """
    Convert SWAN TABLE output to CSV.

    Parameters
    ----------
    file_path : str
        Input .crv path.
    output_csv : str
        Output .csv path.
    """
    data = parse_table(file_path)

    os.makedirs(os.path.dirname(output_csv) or '.', exist_ok=True)
    with open(output_csv, 'w') as f:
        # Header
        if data['columns']:
            f.write(','.join(data['columns']) + '\n')
        if data['units']:
            f.write(','.join(f'[{u}]' for u in data['units']) + '\n')

        # Data
        if 'data' in data:
            for row in data['data']:
                f.write(','.join(f'{v:.6f}' for v in row) + '\n')

    return {'status': 'OK', 'output': output_csv, 'n_rows': data['n_rows']}


# ---------------------------------------------------------------------------
# Spectral parsers (wrapping PySWaN)
# ---------------------------------------------------------------------------

def parse_spec1d(file_path):
    """
    Parse SWAN 1D spectral output.

    Parameters
    ----------
    file_path : str

    Returns
    -------
    Spec1 object with computed Hm0, Tp, Tm01, Tm02
    """
    val = validate_inputs(file_path, 'spec1d')
    if 'FAIL' in val['status']:
        raise FileNotFoundError(val['status'])

    with open(file_path, 'r') as f:
        spec = swan.from_file1D(f, source=file_path)

    return spec


def parse_spec2d(file_path):
    """
    Parse SWAN 2D spectral output.

    Parameters
    ----------
    file_path : str

    Returns
    -------
    Spec2 object with computed Hm0, Tp, Tm01, Tm02, pdir
    """
    val = validate_inputs(file_path, 'spec2d')
    if 'FAIL' in val['status']:
        raise FileNotFoundError(val['status'])

    with open(file_path, 'r') as f:
        spec = swan.from_file2D(f, source=file_path)

    return spec


def parse_tpar(file_path):
    """
    Parse SWAN TPAR parametric file.

    Parameters
    ----------
    file_path : str

    Returns
    -------
    Spec0 object with Hs, Tp, pdir, ms arrays
    """
    val = validate_inputs(file_path, 'tpar')
    if 'FAIL' in val['status']:
        raise FileNotFoundError(val['status'])

    with open(file_path, 'r') as f:
        spec = swan.from_file0D(f, source=file_path)

    return spec


# ---------------------------------------------------------------------------
# Spectral analysis helpers
# ---------------------------------------------------------------------------

def extract_spectral_params(spec, output_csv=None):
    """
    Extract bulk spectral parameters from Spec1 or Spec2 object to dict/CSV.

    Parameters
    ----------
    spec : Spec1 or Spec2
        Spectral object.
    output_csv : str, optional
        If provided, write results to CSV.

    Returns
    -------
    dict : {
        'Hm0': array, 'Tp': float, 'Tm01': array, 'Tm02': array,
        't': array, 'lon': list, 'lat': list
    }
    """
    result = {
        't': spec.t,
        'lon': spec.lon,
        'lat': spec.lat,
        'x': spec.x,
        'y': spec.y,
    }

    try:
        result['Hm0'] = spec.Hm0()
    except Exception:
        result['Hm0'] = None

    try:
        result['Tm01'] = spec.Tm01()
    except Exception:
        result['Tm01'] = None

    try:
        result['Tm02'] = spec.Tm02()
    except Exception:
        result['Tm02'] = None

    try:
        result['Tp'] = spec.Tp()
    except Exception:
        result['Tp'] = None

    if hasattr(spec, 'pdir') and callable(spec.pdir):
        try:
            result['pdir'] = spec.pdir()
        except Exception:
            result['pdir'] = None

    if output_csv:
        os.makedirs(os.path.dirname(output_csv) or '.', exist_ok=True)
        with open(output_csv, 'w') as f:
            f.write('time,Hm0_m,Tm01_s,Tm02_s\n')
            hm0 = result['Hm0']
            tm01 = result['Tm01']
            tm02 = result['Tm02']
            if hm0 is not None:
                for it in range(hm0.shape[0]):
                    for ix in range(hm0.shape[1]):
                        t_str = str(spec.t[it]) if it < len(spec.t) else ''
                        h = hm0[it, ix]
                        m01 = tm01[it, ix] if tm01 is not None else ''
                        m02 = tm02[it, ix] if tm02 is not None else ''
                        f.write(f'{t_str},{h:.4f},{m01},{m02}\n')

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Parse SWAN output files')
    parser.add_argument('input', help='Input file (.crv, .spc, .s1d, .tpar)')
    parser.add_argument('--format', choices=['table', 'spec1d', 'spec2d', 'tpar'],
                        help='Force format (auto-detected if omitted)')
    parser.add_argument('--csv', help='Output CSV path')
    parser.add_argument('--summary', action='store_true',
                        help='Print summary statistics')
    args = parser.parse_args()

    # Auto-detect or use specified format
    val = validate_inputs(args.input, args.format)
    fmt = val.get('format', args.format or 'table')
    print(f"Format: {fmt}")

    if fmt == 'table':
        data = parse_table(args.input)
        print(f"Rows: {data['n_rows']}, Columns: {data.get('columns', [])}")
        if args.csv:
            table_to_csv(args.input, args.csv)
            print(f"CSV written: {args.csv}")
        if args.summary and 'Hsig' in data:
            hs = data['Hsig']
            print(f"Hsig: min={np.min(hs):.3f}, max={np.max(hs):.3f}, "
                  f"mean={np.mean(hs):.3f} m")
        if data.get('warnings'):
            for w in data['warnings']:
                print(f"  WARNING: {w}")

    elif fmt == 'spec1d':
        spec = parse_spec1d(args.input)
        params = extract_spectral_params(spec, args.csv)
        if params['Hm0'] is not None:
            print(f"Hm0: {np.nanmean(params['Hm0']):.3f} m")
        if params['Tm01'] is not None:
            print(f"Tm01: {np.nanmean(params['Tm01']):.3f} s")

    elif fmt == 'spec2d':
        spec = parse_spec2d(args.input)
        params = extract_spectral_params(spec, args.csv)
        if params['Hm0'] is not None:
            print(f"Hm0: {np.nanmean(params['Hm0']):.3f} m")

    elif fmt == 'tpar':
        spec = parse_tpar(args.input)
        print(f"Time steps: {len(np.atleast_1d(spec.t))}")
        print(f"Hs range: {np.nanmin(spec.Hs):.3f} - {np.nanmax(spec.Hs):.3f} m")
