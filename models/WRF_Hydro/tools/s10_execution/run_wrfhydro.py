#!/usr/bin/env python3
"""
run_wrfhydro.py  --  WRF-Hydro Phase 3, Tool 3
================================================
Execute WRF-Hydro in a prepared run directory.  Handles:
  1. Pre-flight checks (DOMAIN/, FORCING/, namelists, etc.)
  2. Symlinking TBL files and wrf_hydro.exe
  3. Running mpirun -np N ./wrf_hydro.exe
  4. Post-run checks (exit code, success string, output listing)

Usage
-----
    python run_wrfhydro.py \\
        --run_dir  outputs/chaohe_wrf_test \\
        --nproc 4 \\
        --timeout 3600

The script prints a JSON summary to stdout on completion.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


# ===================================================================
# Default paths (can be overridden via args)
# ===================================================================
DEFAULT_WRF_HYDRO_EXE = Path(os.path.join(os.environ.get('HYDROCRAFT_ROOT', 'KISSPATH_ROOT'), 'model/wrf_hydro/source/trunk/NDHMS/Run/wrf_hydro.exe'))
DEFAULT_TBL_DIR = Path(os.path.join(os.environ.get('HYDROCRAFT_ROOT', 'KISSPATH_ROOT'), 'model/wrf_hydro/source/trunk/NDHMS/Run'))
DEFAULT_MPIRUN = Path(os.path.join(os.environ.get('HYDROCRAFT_ROOT', 'KISSPATH_ROOT'), 'model/wrf_hydro/deps/mpich-install/bin/mpirun'))


def preflight_check(run_dir):
    """
    Verify the run directory has everything needed.
    Returns (ok: bool, messages: list[str])
    """
    run_dir = Path(run_dir)
    ok = True
    msgs = []

    # Check DOMAIN directory and required files
    domain_dir = run_dir / 'DOMAIN'
    if not domain_dir.is_dir():
        msgs.append(f"MISSING: {domain_dir}")
        ok = False
    else:
        required = [
            'wrfinput_d01.nc', 'geo_em.d01.nc', 'Fulldom_hires.nc',
            'hydro2dtbl.nc', 'soil_properties.nc',
            'GEOGRID_LDASOUT_Spatial_Metadata.nc',
            'GWBASINS.nc', 'GWBUCKPARM.nc',
        ]
        for f in required:
            if not (domain_dir / f).exists():
                msgs.append(f"MISSING: DOMAIN/{f}")
                ok = False

    # Check FORCING directory
    forcing_dir = run_dir / 'FORCING'
    if not forcing_dir.is_dir():
        msgs.append(f"MISSING: {forcing_dir}")
        ok = False
    else:
        ldasin = list(forcing_dir.glob('*.LDASIN_DOMAIN1'))
        if not ldasin:
            msgs.append("MISSING: No LDASIN_DOMAIN1 files in FORCING/")
            ok = False
        else:
            msgs.append(f"OK: {len(ldasin)} LDASIN files found")

    # Check namelists
    for nl in ['namelist.hrldas', 'hydro.namelist']:
        if not (run_dir / nl).exists():
            msgs.append(f"MISSING: {nl}")
            ok = False

    return ok, msgs


def setup_symlinks(run_dir, exe_path, tbl_dir):
    """
    Create symlinks for wrf_hydro.exe and *.TBL files in the run directory.
    """
    run_dir = Path(run_dir)
    exe_path = Path(exe_path)
    tbl_dir = Path(tbl_dir)

    # Symlink executable
    exe_link = run_dir / 'wrf_hydro.exe'
    if exe_link.exists() or exe_link.is_symlink():
        exe_link.unlink()
    exe_link.symlink_to(exe_path.resolve())

    # Symlink TBL files
    tbl_files = list(tbl_dir.glob('*.TBL'))
    for tbl in tbl_files:
        link = run_dir / tbl.name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(tbl.resolve())

    return [exe_link.name] + [t.name for t in tbl_files]


SUCCESS_BANNER = 'The model finished successfully'


def scan_diag_for_banner(run_dir):
    """
    Under mpirun, WRF-Hydro writes its completion banner to diag_hydro.0000N
    (one per MPI rank), never to stdout.  Returns (found, last_lines).
    """
    run_dir = Path(run_dir)
    found = False
    last_lines = {}
    for diag in sorted(run_dir.glob('diag_hydro.0*')):
        try:
            text = diag.read_text(errors='replace')
        except OSError:
            continue
        if SUCCESS_BANNER in text:
            found = True
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            last_lines[diag.name] = lines[-1]
    return found, last_lines


def run_model(run_dir, mpirun_path, nproc, timeout):
    """
    Execute WRF-Hydro via mpirun.

    Returns
    -------
    dict with keys: returncode, stdout, stderr, elapsed_s, success
    """
    run_dir = Path(run_dir)
    mpirun_path = Path(mpirun_path)

    cmd = [
        str(mpirun_path),
        '-np', str(nproc),
        './wrf_hydro.exe',
    ]

    # Set environment for MPICH to find libraries
    env = os.environ.copy()
    mpich_dir = mpirun_path.parent.parent
    lib_dir = str(mpich_dir / 'lib')
    env['LD_LIBRARY_PATH'] = lib_dir + ':' + env.get('LD_LIBRARY_PATH', '')

    print(f"\n  Command: {' '.join(cmd)}")
    print(f"  Working dir: {run_dir}")
    print(f"  Timeout: {timeout}s")
    print(f"  LD_LIBRARY_PATH includes: {lib_dir}")
    print()

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(run_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        elapsed = time.time() - t0
        stdout = proc.stdout
        stderr = proc.stderr

        # Check for success banner: stdout first, then diag_hydro.0000N.
        # Under mpirun the banner goes to the per-rank diag files, not stdout,
        # so an stdout-only check is a false negative on every good run.
        success = SUCCESS_BANNER in stdout
        diag_banner, diag_last_lines = scan_diag_for_banner(run_dir)
        if not success:
            success = diag_banner

        return {
            'returncode': proc.returncode,
            'stdout_tail': stdout[-2000:] if len(stdout) > 2000 else stdout,
            'stderr_tail': stderr[-2000:] if len(stderr) > 2000 else stderr,
            'elapsed_s': round(elapsed, 1),
            'success': success,
            'banner_in_stdout': SUCCESS_BANNER in stdout,
            'banner_in_diag': diag_banner,
            'diag_last_lines': diag_last_lines,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        diag_banner, diag_last_lines = scan_diag_for_banner(run_dir)
        return {
            'returncode': -1,
            'stdout_tail': '(timeout)',
            'stderr_tail': '(timeout)',
            'elapsed_s': round(elapsed, 1),
            'success': False,
            'banner_in_stdout': False,
            'banner_in_diag': diag_banner,
            'diag_last_lines': diag_last_lines,
        }


def collect_outputs(run_dir):
    """
    List output files produced by WRF-Hydro.
    """
    run_dir = Path(run_dir)
    # Globs MUST anchor on the '.' timestamp separator: the filename
    # CHRTOUT_DOMAIN1 ends with the literal substring RTOUT_DOMAIN1, so an
    # unanchored '*RTOUT_DOMAIN1' silently matches every channel-output file.
    output_patterns = {
        'LDASOUT':  '*.LDASOUT_DOMAIN1',
        'CHRTOUT':  '*.CHRTOUT_DOMAIN1',
        'RTOUT':    '*.RTOUT_DOMAIN1',
        'GWOUT':    '*.GWOUT_DOMAIN1',
        'CHANOBS':  '*.CHANOBS*',
        'RESTART':  'RESTART*',
        'HYDRO_RST': 'HYDRO_RST*',
    }

    results = {}
    for cat, pattern in output_patterns.items():
        files = sorted(run_dir.glob(pattern))
        if files:
            total_mb = sum(f.stat().st_size for f in files) / 1e6
            results[cat] = {
                'count': len(files),
                'total_MB': round(total_mb, 1),
                'first': files[0].name,
                'last': files[-1].name,
            }

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Run WRF-Hydro in a prepared directory')
    parser.add_argument('--run_dir', required=True,
                        help='Run directory with DOMAIN/, FORCING/, namelists')
    parser.add_argument('--nproc', type=int, default=4,
                        help='Number of MPI processes')
    parser.add_argument('--timeout', type=int, default=3600,
                        help='Timeout in seconds')
    parser.add_argument('--exe', type=str, default=str(DEFAULT_WRF_HYDRO_EXE),
                        help='Path to wrf_hydro.exe')
    parser.add_argument('--tbl_dir', type=str, default=str(DEFAULT_TBL_DIR),
                        help='Directory containing *.TBL files')
    parser.add_argument('--mpirun', type=str, default=str(DEFAULT_MPIRUN),
                        help='Path to mpirun')
    parser.add_argument('--skip_run', action='store_true',
                        help='Only do preflight + symlinks, do not run')
    args = parser.parse_args()

    run_dir = Path(args.run_dir)

    print("=" * 60)
    print("WRF-Hydro Execution Wrapper")
    print("=" * 60)

    # Preflight
    print("\n[1/4] Preflight checks...")
    ok, msgs = preflight_check(run_dir)
    for m in msgs:
        print(f"  {m}")
    if not ok:
        print("\n  FATAL: Preflight checks failed. Aborting.")
        return 1

    # Symlinks
    print("\n[2/4] Setting up symlinks...")
    linked = setup_symlinks(run_dir, args.exe, args.tbl_dir)
    for l in linked:
        print(f"  -> {l}")

    if args.skip_run:
        print("\n  --skip_run set, stopping before execution.")
        return 0

    # Run
    print("\n[3/4] Running WRF-Hydro...")
    result = run_model(run_dir, args.mpirun, args.nproc, args.timeout)

    print(f"\n  Return code: {result['returncode']}")
    print(f"  Elapsed: {result['elapsed_s']}s")
    print(f"  Success: {result['success']}")

    if result['returncode'] != 0 or not result['success']:
        print("\n  --- STDERR (tail) ---")
        print(result['stderr_tail'][:1000])
        print("\n  --- STDOUT (tail) ---")
        print(result['stdout_tail'][:1000])
        print("\n  --- diag_hydro last lines (real abort reason lives here) ---")
        for name, line in (result.get('diag_last_lines') or {}).items():
            print(f"  {name}: {line}")

    # Collect outputs
    print("\n[4/4] Collecting output files...")
    outputs = collect_outputs(run_dir)
    if outputs:
        for cat, info in outputs.items():
            print(f"  {cat}: {info['count']} files, {info['total_MB']} MB "
                  f"({info['first']} ... {info['last']})")
    else:
        print("  No output files found.")

    # JSON summary
    summary = {
        'status': 'success' if result['success'] else 'failure',
        'returncode': result['returncode'],
        'banner_in_stdout': result.get('banner_in_stdout'),
        'banner_in_diag': result.get('banner_in_diag'),
        'diag_last_lines': result.get('diag_last_lines', {}),
        'elapsed_s': result['elapsed_s'],
        'outputs': outputs,
        'run_dir': str(run_dir),
    }

    print("\n" + "=" * 60)
    print("JSON Summary:")
    print(json.dumps(summary, indent=2))
    print("=" * 60)

    return 0 if result['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
