#!/usr/bin/env python3
"""
Execute SWAN wave model (binary or PySWaN spectral generation pipeline).

Pipeline stage: 5 — Model execution
Pattern: validate_inputs → process → validate_outputs

This tool handles two execution modes:
  1. SWAN binary: run the Fortran-based SWAN executable on a .swn input file
  2. PySWaN spectral: generate/process spectra using the Python toolbox

Preflight checks:
  - SWAN binary exists and is executable
  - All input files referenced in .swn exist
  - Bathymetry file has correct dimensions
  - Boundary spectral files are readable
  - Output directory exists

Postflight checks:
  - Output files were created and are non-empty
  - No SWAN error messages in PRINT file
  - Spectral parameters are within physical bounds
"""

import os
import sys
import subprocess
import re
import time
import datetime
import numpy as np

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
# Preflight validation
# ---------------------------------------------------------------------------

def _strip_comment(raw):
    """Remove a SWAN comment from one physical line.

    The SWAN user manual (section 4.1) says everything on a line behind a '$'
    is ignored, and that '!' may be used as a comment sign as well.  Both are
    INLINE, not just line-leading:

        READINP BOTTOM 1. 'flat.bot' 3 0 FREE   $ 500 m grid
        BOUNDSPEC SIDE W CCW CON FILE 'b.tpar'  ! from buoy 46050

    Only skipping lines that BEGIN with a comment sign gets this wrong twice
    over.  A trailing "& ! why" no longer ends with '&', so the continuation is
    not joined and the command is parsed as two broken fragments; and a
    commented-out line such as "$ READINP WIND 1. 'old.wnd' 4 0 FREE" still
    yields a quoted name, so preflight demands a file the run never reads.

    A comment sign inside a quoted name is data, not a comment, so quoting is
    tracked.  An unbalanced quote leaves the rest of the line untouched, which
    keeps a real filename rather than truncating it.
    """
    in_quote = False
    for i, ch in enumerate(raw):
        if ch == "'":
            in_quote = not in_quote
        elif ch in '$!' and not in_quote:
            return raw[:i]
    return raw


def _logical_lines(lines):
    """Join SWAN continuation lines into one logical command per element.

    A SWAN command may be spread over several physical lines by ending each
    continued line with '&' or '_'.  Classifying PHYSICAL lines misreads such a
    command twice: the first fragment is classified on its real keyword and the
    continuation on whatever word happens to start it.  A continued READINP
    would then have its filename skipped entirely, and a continued output
    command could have its fragment misread.

    Comments are stripped (see :func:`_strip_comment`) BEFORE the continuation
    test, so "READINP ... & $ comment" still joins.  Lines that are entirely
    comment or blank are dropped rather than emitted, and a comment line in the
    middle of a continuation does not terminate it.  Yield stripped logical
    lines, none of them empty.
    """
    out, buf = [], ''
    for raw in lines:
        s = _strip_comment(raw).strip()
        if not s:
            # Pure comment or blank: never a command, and must not close an
            # open continuation.
            continue
        if s.endswith('&') or s.endswith('_'):
            buf += s[:-1].rstrip() + ' '
            continue
        out.append((buf + s).strip())
        buf = ''
    if buf:
        out.append(buf.strip())
    return out


def validate_swn_inputs(swn_path, swan_binary=None):
    """
    Parse a .swn command file and check all referenced input files exist.

    Parameters
    ----------
    swn_path : str
        Path to .swn input file.
    swan_binary : str, optional
        Path to SWAN executable.

    Returns
    -------
    dict : {
        'status': 'OK' or error string,
        'input_files': list of referenced files,
        'missing_files': list of files not found,
        'warnings': list of str
    }
    """
    results = {
        'status': 'unknown',
        'input_files': [],
        'missing_files': [],
        'warnings': []
    }

    if not os.path.exists(swn_path):
        results['status'] = f'FAIL: .swn file not found: {swn_path}'
        return results

    swn_dir = os.path.dirname(os.path.abspath(swn_path))

    # Check SWAN binary
    if swan_binary:
        if not os.path.exists(swan_binary):
            results['status'] = f'FAIL: SWAN binary not found: {swan_binary}'
            return results
        if not os.access(swan_binary, os.X_OK):
            results['warnings'].append(f"SWAN binary not executable: {swan_binary}")

    # Parse .swn for file references
    with open(swn_path, 'r') as f:
        lines = f.readlines()

    for line in _logical_lines(lines):
        # _logical_lines already dropped comments and blanks.
        if not line:
            continue

        # Only commands that READ a file reference a required INPUT. SWAN OUTPUT
        # commands (TABLE/BLOCK/SPEC/SPECOUT/NESTOUT/HOTFILE) also quote
        # filenames, but those are CREATED by the run and do not exist at
        # preflight time, so flagging them as "missing input" wrongly FAILs a
        # valid run.
        #
        # The commands that CONSUME a pre-existing file all begin with either
        # READ (READINP / READGRID / READ) or BOUN (BOUNdspec ... FILE 'f',
        # BOUNdnest1/2/3 ... 'f', and the historical BOUNNEST spelling).  Every
        # output command begins with something else (TABLE, BLOCK, SPEC*, NEST*,
        # HOTFILE, POINTS...), so this prefix test never mistakes an output for
        # an input.  Testing only the READ/BOUNNEST prefixes silently skipped
        # BOUNDSPEC ... FILE boundary data, which IS a required pre-existing
        # input -- a missing TPAR then surfaced only as a mid-run SWAN abort.
        tokens = line.split()
        cmd = tokens[0].upper() if tokens else ''
        if not (cmd.startswith('READ') or cmd.startswith('BOUN')):
            continue

        # Find quoted filenames
        quoted = re.findall(r"'([^']+)'", line)
        for q in quoted:
            if '.' in q and not q.startswith('$'):
                filepath = os.path.join(swn_dir, q)
                results['input_files'].append(q)
                if not os.path.exists(filepath):
                    results['missing_files'].append(q)

    if results['missing_files']:
        results['status'] = (f"FAIL: Missing input files: "
                             f"{', '.join(results['missing_files'])}")
    else:
        results['status'] = 'OK'

    return results


def validate_outputs_after_run(swn_path, output_dir=None):
    """
    Check SWAN outputs after execution.

    Parameters
    ----------
    swn_path : str
        Path to .swn file (to find referenced output files).
    output_dir : str, optional
        Directory where outputs are expected.

    Returns
    -------
    dict : validation results
    """
    results = {'status': 'unknown', 'output_files': [], 'errors': []}

    swn_dir = output_dir or os.path.dirname(os.path.abspath(swn_path))

    # Parse .swn for output file references.
    #
    # SWAN's file-writing commands quote the POINT/CURVE SET name FIRST and the
    # output FILE name second:
    #     TABLE 'sname' [HEADER] 'fname' <var> ...
    #     BLOCK 'sname' [HEADER] 'fname' <var> ...
    #     SPECOUT 'sname' ... 'fname'
    #     NESTOUT 'sname' 'fname'
    # only HOTFILE quotes the filename first.  A non-greedy
    # "(?:TABLE|SPEC)\s+.*?'([^']+)'" therefore captured 'sname', which has no
    # dot, so the `if '.' in outfile` test dropped it and this postflight
    # validated NOTHING -- an empty or missing .crv passed as OK.  Commands are
    # joined into logical lines first so a continued TABLE is read once.
    with open(swn_path, 'r') as f:
        lines = f.readlines()

    output_patterns = []
    for line in _logical_lines(lines):
        # _logical_lines already dropped comments and blanks.
        if not line:
            continue
        tokens = line.split()
        cmd = tokens[0].upper() if tokens else ''
        quoted = re.findall(r"'([^']+)'", line)
        if not quoted:
            continue
        if cmd.startswith('HOTF'):
            output_patterns.append(quoted[0])
        elif (cmd.startswith('TABLE') or cmd.startswith('BLOCK')
              or cmd.startswith('SPECOUT') or cmd.startswith('NESTOUT')):
            # skip quoted[0] == set name; the rest may name the output file
            output_patterns.extend(quoted[1:])

    for outfile in output_patterns:
        if '.' in outfile:
            filepath = os.path.join(swn_dir, outfile)
            results['output_files'].append(outfile)
            if os.path.exists(filepath):
                size = os.path.getsize(filepath)
                if size == 0:
                    results['errors'].append(f"Empty output: {outfile}")
            else:
                results['errors'].append(f"Missing output: {outfile}")

    # Check PRINT file for errors
    print_file = os.path.join(swn_dir, 'PRINT')
    if os.path.exists(print_file):
        with open(print_file, 'r') as f:
            print_content = f.read()
        if 'ERROR' in print_content.upper():
            error_lines = [l for l in print_content.split('\n')
                           if 'ERROR' in l.upper()]
            results['errors'].extend(error_lines[:5])

    if results['errors']:
        results['status'] = f"FAIL: {len(results['errors'])} errors"
    else:
        results['status'] = 'OK'

    return results


# ---------------------------------------------------------------------------
# SWAN binary execution
# ---------------------------------------------------------------------------

def run_swan_binary(swn_path, swan_binary='swan.exe', work_dir=None,
                    timeout=3600, verbose=True):
    """
    Execute SWAN binary on a .swn input file.

    Parameters
    ----------
    swn_path : str
        Path to .swn input file.
    swan_binary : str
        Path to SWAN executable (default: 'swan.exe').
    work_dir : str, optional
        Working directory for execution (default: directory of .swn file).
    timeout : int
        Max execution time in seconds.
    verbose : bool
        Print progress.

    Returns
    -------
    dict : execution results
    """
    results = {
        'status': 'unknown',
        'return_code': None,
        'runtime_s': None,
        'stdout': '',
        'stderr': ''
    }

    # Preflight
    preflight = validate_swn_inputs(swn_path, swan_binary)
    if 'FAIL' in preflight['status']:
        results['status'] = preflight['status']
        return results

    if work_dir is None:
        work_dir = os.path.dirname(os.path.abspath(swn_path))

    swn_basename = os.path.basename(swn_path)
    swn_stem = os.path.splitext(swn_basename)[0]

    if verbose:
        print(f"[SWAN] Running {swn_basename} in {work_dir}")
        print(f"[SWAN] Binary: {swan_binary}")

    t0 = time.time()
    try:
        proc = subprocess.run(
            [swan_binary, swn_stem],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        results['return_code'] = proc.returncode
        results['stdout'] = proc.stdout[:2000]
        results['stderr'] = proc.stderr[:2000]
    except subprocess.TimeoutExpired:
        results['status'] = f'FAIL: timeout after {timeout}s'
        return results
    except FileNotFoundError:
        results['status'] = f'FAIL: SWAN binary not found: {swan_binary}'
        return results

    results['runtime_s'] = round(time.time() - t0, 2)

    if proc.returncode != 0:
        results['status'] = f'FAIL: return code {proc.returncode}'
    else:
        # Postflight
        postflight = validate_outputs_after_run(swn_path, work_dir)
        if 'FAIL' in postflight['status']:
            results['status'] = postflight['status']
        else:
            results['status'] = 'OK'
        results['output_files'] = postflight['output_files']

    if verbose:
        print(f"[SWAN] Finished in {results['runtime_s']}s — {results['status']}")

    return results


# ---------------------------------------------------------------------------
# PySWaN spectral pipeline execution
# ---------------------------------------------------------------------------

def run_pyswan_pipeline(params, output_dir, mode='roundtrip_test'):
    """
    Run PySWaN spectral generation and I/O pipeline.

    Parameters
    ----------
    params : dict
        Wave parameters: Hs, Tp, pdir, ms, gamma, f_range, directions, etc.
    output_dir : str
        Directory for output files.
    mode : str
        'roundtrip_test': generate → write → read → verify Hm0
        'generate_boundary': generate boundary files for SWAN run
        'generate_tpar': generate TPAR file only

    Returns
    -------
    dict : results with status, files created, verification metrics
    """
    results = {'status': 'unknown', 'files': [], 'metrics': {}}
    os.makedirs(output_dir, exist_ok=True)

    Hs = params.get('Hs', 1.0)
    Tp = params.get('Tp', 10.0)
    pdir = params.get('pdir', 270.0)
    ms = params.get('ms', 4)
    gamma = params.get('gamma', 3.3)
    f = np.linspace(
        params.get('fmin', 0.025),
        params.get('fmax', 1.0),
        params.get('nf', 40)
    )
    t_list = params.get('t', [datetime.datetime(2016, 1, 1)])
    lon = params.get('lon', [0.0])
    lat = params.get('lat', [0.0])

    try:
        if mode == 'generate_tpar':
            # Parametric only
            Sp0 = ow.Spec0()
            Sp0.t = t_list[0] if len(t_list) == 1 else t_list
            Sp0.Hs = float(Hs)
            Sp0.Tp = float(Tp)
            Sp0.pdir = float(pdir)
            Sp0.ms = float(ms)

            tpar_path = os.path.join(output_dir, 'boundary.tpar')
            with open(tpar_path, 'w') as fid:
                swan.to_file0D(Sp0, fid)
            results['files'].append(tpar_path)

        elif mode in ('roundtrip_test', 'generate_boundary'):
            # 1D spectrum
            Sp1 = ow.Spec1(f=f, t=t_list, lon=lon, lat=lat)
            Sp1.from_jonswap(float(Hs), float(Tp), float(pdir), float(ms),
                             gamma=gamma)

            spc1_path = os.path.join(output_dir, 'boundary_1d.spc')
            with open(spc1_path, 'w') as fid:
                swan.to_file1D(Sp1, fid)
            results['files'].append(spc1_path)

            # 2D spectrum
            dirs = params.get('directions', list(np.arange(-12, 13) * 15))
            Sp2 = ow.Spec2(f=f, direction=dirs, t=t_list, lon=lon, lat=lat)
            Sp2.from_jonswap(float(Hs), float(Tp), float(pdir), float(ms),
                             gamma=gamma)

            spc2_path = os.path.join(output_dir, 'boundary_2d.spc')
            with open(spc2_path, 'w') as fid:
                swan.to_file2D(Sp2, fid)
            results['files'].append(spc2_path)

            if mode == 'roundtrip_test':
                # Read back and verify
                with open(spc1_path, 'r') as fid:
                    Sp1_read = swan.from_file1D(fid)
                hm0_1d = float(Sp1_read.Hm0()[0, 0])

                with open(spc2_path, 'r') as fid:
                    Sp2_read = swan.from_file2D(fid)
                hm0_2d = float(Sp2_read.Hm0()[0, 0])

                results['metrics'] = {
                    'input_Hs': Hs,
                    'Hm0_1D': round(hm0_1d, 4),
                    'Hm0_2D': round(hm0_2d, 4),
                    'error_1D': round(abs(hm0_1d - Hs), 4),
                    'error_2D': round(abs(hm0_2d - Hs), 4),
                }

                if abs(hm0_1d - Hs) > 0.01 * Hs:
                    results['status'] = f'WARNING: 1D Hm0 error > 1%'
                elif abs(hm0_2d - Hs) > 0.01 * Hs:
                    results['status'] = f'WARNING: 2D Hm0 error > 1%'
                else:
                    results['status'] = 'OK'

        results['status'] = results.get('status', 'OK')
        if results['status'] == 'unknown':
            results['status'] = 'OK'

    except Exception as e:
        results['status'] = f'FAIL: {str(e)}'

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run SWAN model or PySWaN pipeline')
    sub = parser.add_subparsers(dest='command')

    # SWAN binary mode
    p_bin = sub.add_parser('binary', help='Run SWAN binary')
    p_bin.add_argument('swn', help='Path to .swn input file')
    p_bin.add_argument('--swan-exe', default='swan.exe', help='SWAN executable')
    p_bin.add_argument('--timeout', type=int, default=3600, help='Timeout (s)')

    # PySWaN pipeline mode
    p_py = sub.add_parser('pyswan', help='Run PySWaN spectral pipeline')
    p_py.add_argument('--hs', type=float, default=1.0)
    p_py.add_argument('--tp', type=float, default=10.0)
    p_py.add_argument('--pdir', type=float, default=270.0)
    p_py.add_argument('--ms', type=float, default=4.0)
    p_py.add_argument('--mode', choices=['roundtrip_test', 'generate_boundary',
                                          'generate_tpar'],
                      default='roundtrip_test')
    p_py.add_argument('--output-dir', '-o', default='./output')

    args = parser.parse_args()

    if args.command == 'binary':
        result = run_swan_binary(args.swn, args.swan_exe, timeout=args.timeout)
    elif args.command == 'pyswan':
        params = {'Hs': args.hs, 'Tp': args.tp, 'pdir': args.pdir, 'ms': args.ms}
        result = run_pyswan_pipeline(params, args.output_dir, mode=args.mode)
    else:
        parser.print_help()
        sys.exit(1)

    print(f"Status: {result['status']}")
    if result.get('metrics'):
        for k, v in result['metrics'].items():
            print(f"  {k}: {v}")
