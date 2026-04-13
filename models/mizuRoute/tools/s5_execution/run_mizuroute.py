#!/usr/bin/env python3
"""run_mizuroute.py — Execute mizuRoute with preflight validation and output checking.

Runs the mizuRoute Fortran executable with the given control file.
Performs preflight checks (all input files exist, variables match) and
post-run validation (output exists, contains expected variables).

Usage:
    python run_mizuroute.py \\
        --control_file outputs/<run>/mizuroute_input/chaohe.control \\
        --exe model/mizuRoute/mizuRoute-main/route/bin/mizuroute.exe
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time


MIZUROUTE_BIN = os.path.join(os.environ.get('HYDROCRAFT_ROOT', '/mnt/disk1/Hydrocraft_server'), 'model/mizuRoute/mizuRoute-main/route/bin/mizuroute.exe')


def parse_control_file(control_path):
    """Parse mizuRoute control file to extract key-value pairs."""
    config = {}
    with open(control_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('!'):
                continue
            # Format: <variable_name>  value  ! optional comment
            match = re.match(r'<(\w+)>\s+(.+)', line)
            if match:
                key = match.group(1)
                value = match.group(2).strip()
                # Strip inline comment (everything after !)
                if '!' in value:
                    value = value[:value.index('!')].strip()
                config[key] = value
    return config


def preflight_checks(control_path, exe_path):
    """Run preflight validation before executing mizuRoute."""
    errors = []
    warnings = []

    # Check executable
    if not os.path.isfile(exe_path):
        errors.append(f"mizuRoute executable not found: {exe_path}")
    elif not os.access(exe_path, os.X_OK):
        errors.append(f"mizuRoute executable not executable: {exe_path}")

    # Parse control file
    if not os.path.isfile(control_path):
        errors.append(f"Control file not found: {control_path}")
        return errors, warnings

    config = parse_control_file(control_path)

    # Check required paths
    ancil_dir = config.get('ancil_dir', '')
    input_dir = config.get('input_dir', '')
    output_dir = config.get('output_dir', '')

    for name, path in [('ancil_dir', ancil_dir), ('input_dir', input_dir)]:
        if path and not os.path.isdir(path):
            errors.append(f"Directory not found: {name} = {path}")

    # Check input files
    network_file = os.path.join(ancil_dir, config.get('fname_ntopOld', ''))
    if not os.path.isfile(network_file):
        errors.append(f"Network topology file not found: {network_file}")
    else:
        # Verify variable names match
        import netCDF4 as nc
        try:
            with nc.Dataset(network_file, 'r') as ds:
                for cfg_key, var_name in [
                    ('vname_segid', config.get('vname_segid', 'seg_id')),
                    ('vname_tosegment', config.get('vname_tosegment', 'tosegment')),
                    ('vname_length', config.get('vname_length', 'seg_length')),
                    ('vname_slope', config.get('vname_slope', 'seg_slope')),
                ]:
                    if var_name not in ds.variables:
                        errors.append(f"Variable '{var_name}' (from {cfg_key}) not found in {network_file} (dt_m004)")
        except Exception as e:
            errors.append(f"Cannot read network file: {e}")

    runoff_file = os.path.join(input_dir, config.get('fname_qsim', ''))
    if not os.path.isfile(runoff_file):
        errors.append(f"Runoff input file not found: {runoff_file}")
    else:
        import netCDF4 as nc
        try:
            with nc.Dataset(runoff_file, 'r') as ds:
                qsim_var = config.get('vname_qsim', 'RUNOFF')
                if qsim_var not in ds.variables:
                    errors.append(f"Runoff variable '{qsim_var}' not found in {runoff_file} (dt_m004)")
                else:
                    units = ds.variables[qsim_var].units if hasattr(ds.variables[qsim_var], 'units') else 'unknown'
                    if units != 'mm/s':
                        warnings.append(f"Runoff units = '{units}', expected 'mm/s'. Check unit conversion! (dt_m003)")
        except Exception as e:
            errors.append(f"Cannot read runoff file: {e}")

    # Check remap file if remapping is enabled
    is_remap = config.get('is_remap', '.False.')
    if '.True.' in is_remap or 'T' == is_remap:
        remap_file = os.path.join(ancil_dir, config.get('fname_remap', ''))
        if not os.path.isfile(remap_file):
            errors.append(f"Remap file not found: {remap_file}")

    # Check path lengths (Fortran CHARACTER truncation)
    for key in ['ancil_dir', 'input_dir', 'output_dir']:
        path = config.get(key, '')
        if len(path) > 120:
            warnings.append(f"{key} path length = {len(path)} chars (>120, Fortran truncation risk, dt_m017)")

    # Ensure output directory exists
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    return errors, warnings


def run_mizuroute(exe_path, control_path, timeout=3600):
    """Execute mizuRoute and capture output."""

    print(f"Running: {exe_path} {control_path}")
    start_time = time.time()

    try:
        result = subprocess.run(
            [exe_path, control_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(control_path),
        )

        elapsed = time.time() - start_time

        return {
            'returncode': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'elapsed_seconds': elapsed,
        }

    except subprocess.TimeoutExpired:
        return {
            'returncode': -1,
            'stdout': '',
            'stderr': f'Process timed out after {timeout} seconds',
            'elapsed_seconds': timeout,
        }


def postflight_checks(control_path):
    """Validate mizuRoute output after a successful run."""
    config = parse_control_file(control_path)
    output_dir = config.get('output_dir', '')
    basin_name = config.get('fname_output', 'output')

    errors = []

    # Look for output files
    if not os.path.isdir(output_dir):
        errors.append(f"Output directory not found: {output_dir}")
        return errors

    import glob
    output_files = glob.glob(os.path.join(output_dir, f'{basin_name}*.nc'))

    if not output_files:
        errors.append(f"No output NetCDF files found in {output_dir}")
        return errors

    # Check the first output file
    import netCDF4 as nc
    with nc.Dataset(output_files[0], 'r') as ds:
        if 'IRFroutedRunoff' not in ds.variables and 'dlayRunoff' not in ds.variables:
            # Check for other common output variable names
            route_vars = [v for v in ds.variables if 'runoff' in v.lower() or 'flow' in v.lower()]
            if not route_vars:
                errors.append("No routed runoff/flow variable found in output")

    return errors


def process(args):
    # Preflight
    print("=== Preflight Checks ===")
    errors, warnings = preflight_checks(args.control_file, args.exe)

    for w in warnings:
        print(f"WARNING: {w}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        raise RuntimeError(f"Preflight failed with {len(errors)} errors")

    print("  All preflight checks passed")

    # Execute
    print("\n=== Running mizuRoute ===")
    run_result = run_mizuroute(args.exe, args.control_file, args.timeout)

    if run_result['stdout']:
        print(run_result['stdout'][-4000:])
    if run_result['stderr']:
        print(f"STDERR: {run_result['stderr'][-2000:]}", file=sys.stderr)

    if run_result['returncode'] != 0:
        # Check for CFL violation (dt_m009)
        if 'CFL' in run_result['stderr'] or 'CFL' in run_result['stdout']:
            print("HINT: CFL violation detected. Reduce routing timestep (--dt) or use a "
                  "simpler routing method (IRF or KWT instead of DW/KWE). See dt_m009.")
        raise RuntimeError(f"mizuRoute exited with code {run_result['returncode']}")

    print(f"  Completed in {run_result['elapsed_seconds']:.1f} seconds")

    # Postflight
    print("\n=== Postflight Checks ===")
    post_errors = postflight_checks(args.control_file)
    if post_errors:
        for e in post_errors:
            print(f"WARNING: {e}")

    return {
        'status': 'success',
        'returncode': run_result['returncode'],
        'elapsed_seconds': run_result['elapsed_seconds'],
        'control_file': args.control_file,
        'postflight_warnings': len(post_errors),
    }


def main():
    parser = argparse.ArgumentParser(description='Run mizuRoute with validation')
    parser.add_argument('--control_file', required=True, help='mizuRoute control file')
    parser.add_argument('--exe', default=MIZUROUTE_BIN, help='Path to mizuroute.exe')
    parser.add_argument('--timeout', type=int, default=3600, help='Timeout in seconds')

    args = parser.parse_args()

    try:
        result = process(args)
        print(json.dumps(result, indent=2))
        print("\nSUCCESS: mizuRoute completed")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
