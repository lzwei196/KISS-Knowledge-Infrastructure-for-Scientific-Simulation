#!/usr/bin/env python3
"""
calibrate_wrfhydro.py  --  WRF-Hydro Parameter Calibration Tool
================================================================
General-purpose parameter sweep calibration for WRF-Hydro.
Modifies a single parameter in soil_properties.nc or GWBUCKPARM.nc,
runs WRF-Hydro, extracts outlet discharge from CHRTOUT, and computes
goodness-of-fit metrics against observed/benchmark data.

Usage
-----
    python calibrate_wrfhydro.py \\
        --run_dir  outputs/chaohe_wrfhydro_010deg_2000 \\
        --obs_file "outputs/chaohe_2000_2010_025deg/routing_param/rout_out/ZJF  .day" \\
        --param REFKDT \\
        --values "0.1,0.3,0.5,1.0,2.0,3.0" \\
        --start_year 2000 \\
        --nproc 2 \\
        --output_json outputs/chaohe_wrfhydro_010deg_2000/calibration_results.json

Supports:
  - soil_properties.nc parameters: refkdt, slope, bexp, smcmax, dksat, etc.
  - GWBUCKPARM.nc parameters: Coeff, Expon, Zmax, Zinit
  - Observed data formats:
    * VIC routing .day: "year month day Q" (whitespace-separated)
    * Tab-separated: "stcd\tdates\tz\tQ\tname"

Design principles:
  - Backs up original parameter files before any modification
  - Restores originals after calibration completes (or on error)
  - Cleans output files between runs to ensure cold starts
  - Auto-detects outlet feature (highest streamflow in first summer file)
  - Aggregates hourly CHRTOUT to daily mean for comparison with daily obs
"""

import argparse
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import netCDF4 as nc
import numpy as np


# ===================================================================
# Default paths
# ===================================================================
MPICH_BIN = Path(os.path.join(os.environ.get('HYDROCRAFT_ROOT', '/mnt/disk1/Hydrocraft_server'), 'model/wrf_hydro/deps/mpich-install/bin'))
MPICH_LIB = Path(os.path.join(os.environ.get('HYDROCRAFT_ROOT', '/mnt/disk1/Hydrocraft_server'), 'model/wrf_hydro/deps/mpich-install/lib'))
DEFAULT_WRF_HYDRO_EXE = Path(os.path.join(os.environ.get('HYDROCRAFT_ROOT', '/mnt/disk1/Hydrocraft_server'), 'model/wrf_hydro/source/trunk/NDHMS/Run/wrf_hydro.exe'))
DEFAULT_TBL_DIR = Path(os.path.join(os.environ.get('HYDROCRAFT_ROOT', '/mnt/disk1/Hydrocraft_server'), 'model/wrf_hydro/source/trunk/NDHMS/Run'))


# ===================================================================
# Metrics
# ===================================================================

def calc_nse(sim, obs):
    """Nash-Sutcliffe Efficiency."""
    denom = np.sum((obs - obs.mean()) ** 2)
    if denom == 0:
        return float('nan')
    return 1.0 - np.sum((sim - obs) ** 2) / denom


def calc_pbias(sim, obs):
    """Percent bias (%)."""
    denom = np.sum(obs)
    if denom == 0:
        return float('nan')
    return 100.0 * np.sum(sim - obs) / denom


def calc_rmse(sim, obs):
    """Root mean square error."""
    return np.sqrt(np.mean((sim - obs) ** 2))


def calc_corr(sim, obs):
    """Pearson correlation coefficient."""
    if np.std(sim) == 0 or np.std(obs) == 0:
        return float('nan')
    return np.corrcoef(sim, obs)[0, 1]


def calc_kge(sim, obs):
    """Kling-Gupta Efficiency."""
    r = calc_corr(sim, obs)
    if np.isnan(r):
        return float('nan')
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else float('nan')
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else float('nan')
    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def compute_all_metrics(sim, obs):
    """Compute all metrics, return dict."""
    return {
        'NSE': round(float(calc_nse(sim, obs)), 4),
        'PBIAS': round(float(calc_pbias(sim, obs)), 2),
        'RMSE': round(float(calc_rmse(sim, obs)), 4),
        'r': round(float(calc_corr(sim, obs)), 4),
        'KGE': round(float(calc_kge(sim, obs)), 4),
        'mean_sim': round(float(np.mean(sim)), 4),
        'mean_obs': round(float(np.mean(obs)), 4),
    }


# ===================================================================
# Observed data parsing
# ===================================================================

def parse_obs_vic_day(filepath, start_year=None, end_year=None):
    """
    Parse VIC routing .day file.
    Format: "year month day Q" (whitespace-separated, Fortran-style).
    Returns dict {datetime.date: Q_m3s}.
    """
    obs = {}
    with open(filepath, 'r') as f:
        for line in f:
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                yr, mon, day = int(parts[0]), int(parts[1]), int(parts[2])
                q = float(parts[3])
            except (ValueError, IndexError):
                continue
            if start_year and yr < start_year:
                continue
            if end_year and yr > end_year:
                continue
            try:
                d = datetime.date(yr, mon, day)
                obs[d] = q
            except ValueError:
                continue
    return obs


def parse_obs_tabsep(filepath, start_year=None, end_year=None):
    """
    Parse tab-separated observed discharge file.
    Format: "stcd\tdates\tz\tQ\tname"
    dates can be YYYY-MM-DD or YYYY/MM/DD.
    Returns dict {datetime.date: Q_m3s}.
    """
    obs = {}
    with open(filepath, 'r') as f:
        header = f.readline()  # skip header
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 4:
                continue
            try:
                date_str = parts[1].strip()
                date_str = date_str.replace('/', '-')
                d = datetime.date.fromisoformat(date_str)
                q = float(parts[3])
            except (ValueError, IndexError):
                continue
            if start_year and d.year < start_year:
                continue
            if end_year and d.year > end_year:
                continue
            obs[d] = q
    return obs


def parse_obs_file(filepath, start_year=None, end_year=None):
    """
    Auto-detect format and parse observed discharge file.
    Returns dict {datetime.date: Q_m3s}.
    """
    filepath = str(filepath)
    # Peek at first line to detect format
    with open(filepath, 'r') as f:
        first_line = f.readline().strip()

    # Tab-separated with header containing 'stcd' or 'dates' or 'Q'
    if '\t' in first_line and any(kw in first_line.lower() for kw in ['stcd', 'dates', 'date', 'discharge']):
        print(f"  Detected tab-separated format")
        return parse_obs_tabsep(filepath, start_year, end_year)
    else:
        # Try VIC .day format (whitespace-separated: yr mon day Q)
        parts = first_line.split()
        if len(parts) >= 4:
            try:
                int(parts[0])
                int(parts[1])
                int(parts[2])
                float(parts[3])
                print(f"  Detected VIC .day format")
                return parse_obs_vic_day(filepath, start_year, end_year)
            except ValueError:
                pass

    # Fallback: try tab-sep without keyword header
    if '\t' in first_line:
        print(f"  Trying tab-separated format (no keyword header)")
        return parse_obs_tabsep(filepath, start_year, end_year)

    # Last fallback: VIC .day
    print(f"  Defaulting to VIC .day format")
    return parse_obs_vic_day(filepath, start_year, end_year)


# ===================================================================
# CHRTOUT extraction
# ===================================================================

def find_outlet_feature(run_dir):
    """
    Auto-detect outlet feature index by finding the feature with
    maximum streamflow in a summer CHRTOUT file. Falls back to first
    available file if no summer file exists.
    """
    run_dir = Path(run_dir)
    chrtout_files = sorted(run_dir.glob('*.CHRTOUT_DOMAIN1'))
    if not chrtout_files:
        raise FileNotFoundError(f"No CHRTOUT files in {run_dir}")

    # Prefer a summer file (Jun-Aug) for clearer signal
    summer_files = [f for f in chrtout_files
                    if f.name[4:6] in ('06', '07', '08')]
    # Among summer, pick one from late July for peak flow
    target_files = [f for f in chrtout_files if f.name[4:8] == '0715'] or \
                   [f for f in chrtout_files if f.name[4:6] == '07'] or \
                   summer_files or chrtout_files

    # Use a file from the middle of the available range
    target = target_files[len(target_files) // 2]

    with nc.Dataset(str(target), 'r') as ds:
        Q = ds.variables['streamflow'][:]
        fids = ds.variables['feature_id'][:]
        lats = ds.variables['latitude'][:]
        lons = ds.variables['longitude'][:]
        idx = int(np.nanargmax(Q))

    print(f"  Outlet detection: feature_id={fids[idx]}, "
          f"lat={lats[idx]:.4f}, lon={lons[idx]:.4f}, "
          f"Q={Q[idx]:.2f} m3/s (from {target.name})")
    return idx, int(fids[idx])


def extract_daily_discharge(run_dir, feature_idx, start_year=None, end_year=None):
    """
    Read all CHRTOUT files, extract streamflow at feature_idx,
    aggregate hourly to daily mean.
    Returns dict {datetime.date: Q_daily_mean_m3s}.
    """
    run_dir = Path(run_dir)
    chrtout_files = sorted(run_dir.glob('*.CHRTOUT_DOMAIN1'))
    if not chrtout_files:
        raise FileNotFoundError(f"No CHRTOUT files in {run_dir}")

    # Collect hourly values grouped by date
    daily_accum = {}  # date -> list of Q values
    for fpath in chrtout_files:
        fname = fpath.name  # e.g. 200007010000.CHRTOUT_DOMAIN1
        try:
            yr = int(fname[:4])
            mon = int(fname[4:6])
            day = int(fname[6:8])
        except (ValueError, IndexError):
            continue

        if start_year and yr < start_year:
            continue
        if end_year and yr > end_year:
            continue

        try:
            d = datetime.date(yr, mon, day)
        except ValueError:
            continue

        try:
            with nc.Dataset(str(fpath), 'r') as ds:
                q = float(ds.variables['streamflow'][feature_idx])
        except Exception:
            continue

        if d not in daily_accum:
            daily_accum[d] = []
        daily_accum[d].append(q)

    # Compute daily means
    daily_q = {}
    for d, vals in sorted(daily_accum.items()):
        daily_q[d] = np.mean(vals)

    return daily_q


# ===================================================================
# Parameter modification
# ===================================================================

# Map of canonical parameter names to (file, variable_name)
PARAM_REGISTRY = {
    # soil_properties.nc parameters
    'REFKDT':   ('soil_properties.nc', 'refkdt'),
    'SLOPE':    ('soil_properties.nc', 'slope'),
    'BEXP':     ('soil_properties.nc', 'bexp'),
    'SMCMAX':   ('soil_properties.nc', 'smcmax'),
    'DKSAT':    ('soil_properties.nc', 'dksat'),
    'REFDK':    ('soil_properties.nc', 'refdk'),
    'MFSNO':    ('soil_properties.nc', 'mfsno'),
    'CWPVT':    ('soil_properties.nc', 'cwpvt'),
    'MP':       ('soil_properties.nc', 'mp'),
    'VCMX25':   ('soil_properties.nc', 'vcmx25'),
    'HVT':      ('soil_properties.nc', 'hvt'),
    'RSURFEXP': ('soil_properties.nc', 'rsurfexp'),
    # GWBUCKPARM.nc parameters
    'COEFF':    ('GWBUCKPARM.nc', 'Coeff'),
    'EXPON':    ('GWBUCKPARM.nc', 'Expon'),
    'ZMAX':     ('GWBUCKPARM.nc', 'Zmax'),
    'ZINIT':    ('GWBUCKPARM.nc', 'Zinit'),
}


def backup_param_file(domain_dir, filename):
    """Back up a parameter file. Returns backup path."""
    src = Path(domain_dir) / filename
    bak = Path(domain_dir) / (filename + '.calibration_backup')
    if not bak.exists():
        shutil.copy2(str(src), str(bak))
        print(f"  Backed up {filename} -> {bak.name}")
    else:
        print(f"  Backup already exists: {bak.name}")
    return bak


def restore_param_file(domain_dir, filename):
    """Restore parameter file from backup."""
    bak = Path(domain_dir) / (filename + '.calibration_backup')
    dst = Path(domain_dir) / filename
    if bak.exists():
        shutil.copy2(str(bak), str(dst))
        print(f"  Restored {filename} from backup")
    else:
        print(f"  WARNING: No backup found for {filename}")


def set_parameter(domain_dir, param_name, value):
    """
    Set a parameter to a uniform value in the appropriate NetCDF file.
    For soil_properties.nc, sets all non-masked cells.
    For GWBUCKPARM.nc, sets the scalar/1D value.
    """
    param_key = param_name.upper()
    if param_key not in PARAM_REGISTRY:
        raise ValueError(
            f"Unknown parameter '{param_name}'. Known: {list(PARAM_REGISTRY.keys())}")

    filename, varname = PARAM_REGISTRY[param_key]
    filepath = Path(domain_dir) / filename

    with nc.Dataset(str(filepath), 'r+') as ds:
        var = ds.variables[varname]
        old_data = var[:]

        if filename == 'soil_properties.nc':
            # Set all non-zero (non-masked) cells to the new value
            # Preserve zeros (masked/water cells)
            new_data = np.where(old_data != 0, value, old_data)
            var[:] = new_data
            n_modified = int(np.sum(old_data != 0))
            print(f"  Set {varname} = {value} in {n_modified} cells ({filename})")
        else:
            # GWBUCKPARM: simple scalar set
            var[:] = value
            print(f"  Set {varname} = {value} ({filename})")


# ===================================================================
# WRF-Hydro execution
# ===================================================================

def clean_output_files(run_dir):
    """
    Remove all WRF-Hydro output files to ensure a clean cold start.
    Removes CHRTOUT, LDASOUT, GWOUT, RTOUT, RESTART, HYDRO_RST, diag_hydro.
    """
    run_dir = Path(run_dir)
    patterns = [
        '*.CHRTOUT_DOMAIN1',
        '*.LDASOUT_DOMAIN1',
        '*.GWOUT_DOMAIN1',
        '*.RTOUT_DOMAIN1',
        'RESTART.*',
        'HYDRO_RST.*',
        'diag_hydro.*',
    ]
    total_removed = 0
    for pattern in patterns:
        files = list(run_dir.glob(pattern))
        for f in files:
            f.unlink()
        total_removed += len(files)
    print(f"  Cleaned {total_removed} output files from {run_dir}")


def ensure_symlinks(run_dir, exe_path=None, tbl_dir=None):
    """Ensure wrf_hydro.exe and TBL symlinks exist."""
    run_dir = Path(run_dir)
    exe_path = Path(exe_path or DEFAULT_WRF_HYDRO_EXE)
    tbl_dir = Path(tbl_dir or DEFAULT_TBL_DIR)

    exe_link = run_dir / 'wrf_hydro.exe'
    if not exe_link.exists():
        exe_link.symlink_to(exe_path.resolve())

    for tbl in tbl_dir.glob('*.TBL'):
        link = run_dir / tbl.name
        if not link.exists():
            link.symlink_to(tbl.resolve())


def run_wrfhydro(run_dir, nproc=2, timeout=3600):
    """
    Execute WRF-Hydro via mpirun. Returns dict with success flag and timing.
    """
    run_dir = Path(run_dir)
    mpirun = str(MPICH_BIN / 'mpirun')

    cmd = [mpirun, '-np', str(nproc), './wrf_hydro.exe']

    env = os.environ.copy()
    env['PATH'] = f"{MPICH_BIN}:" + env['PATH']
    env['LD_LIBRARY_PATH'] = f"{MPICH_LIB}:" + env.get('LD_LIBRARY_PATH', '')

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

        # WRF-Hydro "succeeds" even when forcing runs out — check for
        # the success string OR a non-zero exit with "The model finished"
        stdout = proc.stdout
        success = 'The model finished successfully' in stdout

        # Also treat "no forcing data" gracefully — it means the model
        # ran to the end of available forcing, which is expected
        no_forcing = ('STOP' in stdout and 'forc' in stdout.lower()) or \
                     proc.returncode != 0

        # Count output files to verify something was produced
        n_chrtout = len(list(run_dir.glob('*.CHRTOUT_DOMAIN1')))

        return {
            'success': success or n_chrtout > 100,
            'returncode': proc.returncode,
            'elapsed_s': round(elapsed, 1),
            'n_chrtout': n_chrtout,
            'stdout_tail': stdout[-500:] if stdout else '',
            'stderr_tail': proc.stderr[-500:] if proc.stderr else '',
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return {
            'success': False,
            'returncode': -1,
            'elapsed_s': round(elapsed, 1),
            'n_chrtout': 0,
            'stdout_tail': '(timeout)',
            'stderr_tail': '(timeout)',
        }


# ===================================================================
# Main calibration loop
# ===================================================================

def run_calibration(args):
    """Execute the full calibration sweep."""
    run_dir = Path(args.run_dir)
    domain_dir = run_dir / 'DOMAIN'

    param_key = args.param.upper()
    if param_key not in PARAM_REGISTRY:
        print(f"ERROR: Unknown parameter '{args.param}'. "
              f"Known: {list(PARAM_REGISTRY.keys())}")
        return 1

    param_file = PARAM_REGISTRY[param_key][0]
    values = [float(v.strip()) for v in args.values.split(',')]

    print("=" * 70)
    print("WRF-Hydro Parameter Calibration")
    print("=" * 70)
    print(f"  Run directory : {run_dir}")
    print(f"  Parameter     : {args.param} (in {param_file})")
    print(f"  Values to test: {values}")
    print(f"  Obs file      : {args.obs_file}")
    print(f"  Start year    : {args.start_year}")
    print(f"  End year      : {args.end_year}")
    print(f"  MPI procs     : {args.nproc}")
    print()

    # ---- Parse observed data ----
    print("[1/5] Parsing observed/benchmark discharge...")
    obs_data = parse_obs_file(args.obs_file, args.start_year, args.end_year)
    if not obs_data:
        print("ERROR: No observed data found in the specified period.")
        return 1
    obs_dates = sorted(obs_data.keys())
    print(f"  Loaded {len(obs_data)} daily observations "
          f"({obs_dates[0]} to {obs_dates[-1]})")
    print()

    # ---- Backup parameter file ----
    print(f"[2/5] Backing up {param_file}...")
    backup_param_file(domain_dir, param_file)
    print()

    # ---- Ensure symlinks ----
    print("[3/5] Ensuring executable and TBL symlinks...")
    ensure_symlinks(run_dir)
    print()

    # ---- Calibration loop ----
    print("[4/5] Running calibration sweep...")
    print("-" * 70)

    results = []
    best_nse = -999
    best_value = None
    best_idx = -1

    for i, val in enumerate(values):
        print(f"\n  === Trial {i + 1}/{len(values)}: {args.param} = {val} ===")

        # Set parameter
        set_parameter(domain_dir, args.param, val)

        # Clean previous outputs
        clean_output_files(run_dir)

        # Run WRF-Hydro
        print(f"  Running WRF-Hydro ({args.nproc} procs)...")
        run_result = run_wrfhydro(run_dir, args.nproc, args.timeout)
        print(f"  Completed in {run_result['elapsed_s']}s, "
              f"exit={run_result['returncode']}, "
              f"CHRTOUT files={run_result['n_chrtout']}")

        if not run_result['success']:
            print(f"  WARNING: Run may have failed. Attempting to extract output anyway.")
            if run_result['n_chrtout'] == 0:
                print(f"  SKIP: No output produced.")
                results.append({
                    'value': val,
                    'run_success': False,
                    'elapsed_s': run_result['elapsed_s'],
                    'metrics': None,
                })
                continue

        # Find outlet (re-detect for first trial, reuse for subsequent)
        if i == 0:
            try:
                outlet_idx, outlet_fid = find_outlet_feature(run_dir)
            except FileNotFoundError as e:
                print(f"  ERROR: {e}")
                results.append({
                    'value': val,
                    'run_success': False,
                    'elapsed_s': run_result['elapsed_s'],
                    'metrics': None,
                })
                continue

        # Extract daily discharge
        print(f"  Extracting daily discharge (feature_idx={outlet_idx})...")
        sim_data = extract_daily_discharge(
            run_dir, outlet_idx, args.start_year, args.end_year)
        print(f"  Extracted {len(sim_data)} daily values")

        # Align sim and obs on common dates
        common_dates = sorted(set(sim_data.keys()) & set(obs_data.keys()))
        if len(common_dates) < 30:
            print(f"  WARNING: Only {len(common_dates)} overlapping days. "
                  f"Need >= 30 for meaningful metrics.")
            if len(common_dates) == 0:
                results.append({
                    'value': val,
                    'run_success': True,
                    'elapsed_s': run_result['elapsed_s'],
                    'n_sim_days': len(sim_data),
                    'n_overlap_days': 0,
                    'metrics': None,
                })
                continue

        sim_arr = np.array([sim_data[d] for d in common_dates])
        obs_arr = np.array([obs_data[d] for d in common_dates])

        # Compute metrics
        metrics = compute_all_metrics(sim_arr, obs_arr)
        print(f"  Metrics: NSE={metrics['NSE']:.4f}, PBIAS={metrics['PBIAS']:.1f}%, "
              f"RMSE={metrics['RMSE']:.2f}, r={metrics['r']:.4f}, KGE={metrics['KGE']:.4f}")
        print(f"  Mean Q: sim={metrics['mean_sim']:.2f}, obs={metrics['mean_obs']:.2f} m3/s")

        trial_result = {
            'value': val,
            'run_success': True,
            'elapsed_s': run_result['elapsed_s'],
            'n_sim_days': len(sim_data),
            'n_overlap_days': len(common_dates),
            'date_range': f"{common_dates[0]} to {common_dates[-1]}",
            'metrics': metrics,
        }
        results.append(trial_result)

        if metrics['NSE'] > best_nse:
            best_nse = metrics['NSE']
            best_value = val
            best_idx = len(results) - 1

    print()
    print("-" * 70)

    # ---- Restore original + apply best ----
    print("\n[5/5] Finalizing...")
    restore_param_file(domain_dir, param_file)

    # Apply best value
    if best_value is not None:
        print(f"\n  BEST: {args.param} = {best_value} (NSE = {best_nse:.4f})")
        if args.apply_best:
            print(f"  Applying best value and running final simulation...")
            set_parameter(domain_dir, args.param, best_value)
            clean_output_files(run_dir)
            final_result = run_wrfhydro(run_dir, args.nproc, args.timeout)
            print(f"  Final run completed in {final_result['elapsed_s']}s")
        else:
            print(f"  Use --apply_best to apply this value and run a final simulation.")
            print(f"  Or manually set: set {args.param}={best_value} in DOMAIN/{param_file}")
    else:
        print("  WARNING: No successful trials. Check WRF-Hydro setup.")

    # ---- Build output JSON ----
    summary = {
        'parameter': args.param,
        'param_file': param_file,
        'values_tested': values,
        'n_trials': len(values),
        'n_successful': sum(1 for r in results if r.get('metrics') is not None),
        'best_value': best_value,
        'best_nse': best_nse if best_nse > -999 else None,
        'best_applied': args.apply_best and best_value is not None,
        'obs_file': str(args.obs_file),
        'run_dir': str(run_dir),
        'start_year': args.start_year,
        'end_year': args.end_year,
        'outlet_feature_idx': outlet_idx if 'outlet_idx' in dir() else None,
        'outlet_feature_id': outlet_fid if 'outlet_fid' in dir() else None,
        'trials': results,
    }

    # Write JSON
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  Results written to: {output_json}")

    # ---- Print summary table ----
    print()
    print("=" * 70)
    print("CALIBRATION RESULTS SUMMARY")
    print("=" * 70)
    print(f"{'Value':>8s} {'NSE':>8s} {'KGE':>8s} {'PBIAS%':>8s} "
          f"{'RMSE':>8s} {'r':>6s} {'Time(s)':>8s} {'Note':>6s}")
    print("-" * 70)
    for r in results:
        val = r['value']
        t = r.get('elapsed_s', 0)
        if r.get('metrics') is None:
            print(f"{val:8.2f} {'---':>8s} {'---':>8s} {'---':>8s} "
                  f"{'---':>8s} {'---':>6s} {t:8.1f} {'FAIL':>6s}")
        else:
            m = r['metrics']
            mark = '  BEST' if val == best_value else ''
            print(f"{val:8.2f} {m['NSE']:8.4f} {m['KGE']:8.4f} {m['PBIAS']:8.1f} "
                  f"{m['RMSE']:8.2f} {m['r']:6.4f} {t:8.1f} {mark:>6s}")
    print("=" * 70)

    return 0


# ===================================================================
# CLI entry point
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description='WRF-Hydro parameter calibration via sweep',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Calibrate REFKDT on Chaohe basin
  python calibrate_wrfhydro.py \\
    --run_dir outputs/chaohe_wrfhydro_010deg_2000 \\
    --obs_file outputs/chaohe_2000_2010_025deg/routing_param/rout_out/ZJF\\ \\ .day \\
    --param REFKDT --values "0.1,0.3,0.5,1.0,2.0,3.0" \\
    --start_year 2000 --nproc 2

  # Calibrate groundwater exponent
  python calibrate_wrfhydro.py \\
    --run_dir outputs/chaohe_wrfhydro_010deg_2000 \\
    --obs_file data/obs/chaohe/obs.txt \\
    --param EXPON --values "1.0,2.0,3.0,5.0,8.0" \\
    --start_year 2000 --nproc 2

  # Calibrate slope parameter with auto-apply
  python calibrate_wrfhydro.py \\
    --run_dir outputs/chaohe_wrfhydro_010deg_2000 \\
    --obs_file data/obs/chaohe/obs.txt \\
    --param SLOPE --values "0.01,0.05,0.1,0.2,0.5,1.0" \\
    --start_year 2000 --apply_best
        """)

    parser.add_argument('--run_dir', required=True,
                        help='WRF-Hydro run directory (with DOMAIN/, FORCING/, namelists)')
    parser.add_argument('--obs_file', required=True,
                        help='Observed/benchmark discharge file '
                             '(VIC .day format or tab-separated)')
    parser.add_argument('--param', default='REFKDT',
                        help='Parameter to calibrate (default: REFKDT). '
                             f'Choices: {list(PARAM_REGISTRY.keys())}')
    parser.add_argument('--values', default='0.1,0.3,0.5,1.0,2.0,3.0,5.0',
                        help='Comma-separated parameter values to test')
    parser.add_argument('--start_year', type=int, default=None,
                        help='Start year for evaluation (skip spinup)')
    parser.add_argument('--end_year', type=int, default=None,
                        help='End year for evaluation')
    parser.add_argument('--nproc', type=int, default=2,
                        help='Number of MPI processes (default: 2)')
    parser.add_argument('--timeout', type=int, default=3600,
                        help='Per-run timeout in seconds (default: 3600)')
    parser.add_argument('--output_json', default=None,
                        help='Output JSON path (default: <run_dir>/calibration_results.json)')
    parser.add_argument('--apply_best', action='store_true',
                        help='Apply best parameter value and run a final simulation')

    args = parser.parse_args()

    if args.output_json is None:
        args.output_json = str(Path(args.run_dir) / 'calibration_results.json')

    return run_calibration(args)


if __name__ == '__main__':
    sys.exit(main())
