#!/usr/bin/env python3
"""
Execution wrapper for TOPMODEL BMI.

Handles:
1. Building the binary from source
2. Writing the topmod.run configuration file
3. Writing params.dat from a parameter dictionary
4. Running the model
5. Checking for successful completion

Pipeline: validate → execute → validate
"""

import os
import sys
import subprocess
import argparse
import shutil


def validate_inputs(source_dir, data_dir):
    """Validate that source code and input data exist."""
    errors = []

    src_dir = os.path.join(source_dir, 'src')
    if not os.path.isdir(src_dir):
        errors.append(f"Source directory not found: {src_dir}")

    makefile = os.path.join(src_dir, 'Makefile')
    if not os.path.exists(makefile):
        errors.append(f"Makefile not found: {makefile}")

    for fname in ['inputs.dat', 'subcat.dat', 'params.dat']:
        fpath = os.path.join(data_dir, fname)
        if not os.path.exists(fpath):
            errors.append(f"Input file not found: {fpath}")

    return errors


def build_topmodel(source_dir):
    """
    Build TOPMODEL binary from source.

    Returns path to the binary or None on failure.
    """
    src_dir = os.path.join(source_dir, 'src')

    print("Building TOPMODEL...")

    # Clean
    result = subprocess.run(['make', 'clean'], cwd=src_dir,
                          capture_output=True, text=True)

    # Build
    result = subprocess.run(['make'], cwd=src_dir,
                          capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Build FAILED:\n{result.stderr}")
        return None

    # Binary should be at source_dir/run_bmi (Makefile moves it)
    binary_path = os.path.join(source_dir, 'run_bmi')
    if not os.path.exists(binary_path):
        # Try in src dir
        binary_path = os.path.join(src_dir, 'run_bmi')

    if os.path.exists(binary_path):
        print(f"Build successful: {binary_path}")
        return binary_path
    else:
        print("Build completed but binary not found")
        return None


def write_topmod_run(output_dir, stand_alone=1, title="TOPMODEL Simulation",
                     inputs_path="data/inputs.dat", subcat_path="data/subcat.dat",
                     params_path="data/params.dat", topmod_out="topmod.out",
                     hyd_out="hyd.out"):
    """Write the topmod.run configuration file.

    IMPORTANT — config location is HARDCODED in the binary. main.c opens
    ``./data/topmod.run`` relative to the process CWD (the run dir). So you MUST
    pass ``output_dir=<run_dir>/data`` (NOT the run-dir root) or the binary
    SEGFAULTS before producing any output. The internal file paths
    (inputs_path/subcat_path/params_path) stay relative to the run-dir CWD,
    i.e. "data/inputs.dat" — matching the shipped Taegu demo and the working
    Wangjiaba run. (Confirmed Bengbu 51080, 2026-06-03.)
    """
    config_path = os.path.join(output_dir, 'topmod.run')

    with open(config_path, 'w') as f:
        f.write(f"{stand_alone}\n")
        f.write(f"{title}\n")
        f.write(f"{inputs_path}\n")
        f.write(f"{subcat_path}\n")
        f.write(f"{params_path}\n")
        f.write(f"{topmod_out}\n")
        f.write(f"{hyd_out}\n")

    print(f"Wrote configuration: {config_path}")
    return config_path


def write_params_dat(output_file, params=None, basin_name="Basin"):
    """
    Write TOPMODEL params.dat file.

    Default parameters (from Taegu Pyungkwang demo):
      szm=0.032, t0=5.0, td=50.0, chv=3600.0, rv=3600.0,
      srmax=0.05, Q0=0.0000328, sr0=0.002, infex=0,
      xk0=1.0, hf=0.02, dth=0.1

    ALL units must be in meters and hours.
    """
    if params is None:
        params = {
            'szm': 0.032,
            't0': 5.0,
            'td': 50.0,
            'chv': 3600.0,
            'rv': 3600.0,
            'srmax': 0.05,
            'Q0': 0.0000328,
            'sr0': 0.002,
            'infex': 0,
            'xk0': 1.0,
            'hf': 0.02,
            'dth': 0.1,
        }

    with open(output_file, 'w') as f:
        f.write(f"{basin_name}\n")
        f.write(f"{params['szm']}  {params['t0']}  {params['td']}  ")
        f.write(f"{params['chv']}  {params['rv']}  {params['srmax']}  ")
        f.write(f"{params['Q0']}  {params['sr0']}  {params['infex']}  ")
        f.write(f"{params['xk0']}  {params['hf']}  {params['dth']}\n")

    print(f"Wrote parameters: {output_file}")


def run_topmodel(binary_path, run_dir, config_file="topmod.run"):
    """
    Execute TOPMODEL binary.

    The binary reads config from ./data/topmod.run by default.
    Must be run from the directory containing the config.
    """
    # Copy binary to run directory if needed
    run_binary = os.path.join(run_dir, 'run_bmi')
    if binary_path != run_binary:
        shutil.copy2(binary_path, run_binary)
        os.chmod(run_binary, 0o755)

    print(f"Running TOPMODEL in {run_dir}...")

    # The binary expects config at ./data/topmod.run
    # or a custom path. Check main.c - it uses "./data/topmod.run"
    result = subprocess.run(
        [run_binary],
        cwd=run_dir,
        capture_output=True,
        text=True,
        timeout=300
    )

    if result.returncode != 0:
        print(f"TOPMODEL run FAILED (exit code {result.returncode})")
        if result.stderr:
            print(f"STDERR: {result.stderr[:500]}")
        if result.stdout:
            print(f"STDOUT: {result.stdout[:500]}")
        return False

    print("TOPMODEL run completed successfully")
    if result.stdout:
        print(f"STDOUT: {result.stdout[:300]}")

    return True


def validate_outputs(run_dir):
    """Validate that TOPMODEL produced expected outputs."""
    errors = []

    # Check for output files
    topmod_out = os.path.join(run_dir, 'topmod.out')
    hyd_out = os.path.join(run_dir, 'hyd.out')

    if not os.path.exists(topmod_out):
        errors.append(f"topmod.out not found in {run_dir}")
    else:
        size = os.path.getsize(topmod_out)
        if size == 0:
            errors.append("topmod.out is empty")
        else:
            print(f"topmod.out: {size} bytes")

    if not os.path.exists(hyd_out):
        errors.append(f"hyd.out not found in {run_dir}")
    else:
        size = os.path.getsize(hyd_out)
        if size == 0:
            errors.append("hyd.out is empty")
        else:
            # Check reasonable values
            with open(hyd_out, 'r') as f:
                first_line = f.readline().split()
            if len(first_line) >= 2:
                q_sim = float(first_line[1])
                # Q should be in m/hr, typically 1e-6 to 1e-2
                if q_sim > 1.0:
                    errors.append(f"Q_sim={q_sim} m/hr seems too high (>1 m/hr)")
                print(f"hyd.out: {size} bytes, first Q_sim={q_sim:.6e} m/hr")

    if not errors:
        print("OUTPUT VALIDATION PASSED")
    else:
        for e in errors:
            print(f"OUTPUT WARNING: {e}")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Build and run TOPMODEL")
    parser.add_argument('--source-dir', required=True, help='TOPMODEL source directory')
    parser.add_argument('--run-dir', required=True, help='Run directory')
    parser.add_argument('--data-dir', default=None, help='Data directory with input files')
    parser.add_argument('--title', default='TOPMODEL Simulation', help='Simulation title')
    parser.add_argument('--build-only', action='store_true', help='Only build, do not run')

    args = parser.parse_args()

    if args.data_dir is None:
        args.data_dir = os.path.join(args.run_dir, 'data')

    # Step 1: Validate
    print("=== Step 1: Validating inputs ===")
    errors = validate_inputs(args.source_dir, args.data_dir)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")

    # Step 2: Build
    print("=== Step 2: Building TOPMODEL ===")
    binary_path = build_topmodel(args.source_dir)
    if binary_path is None:
        print("Build failed. Exiting.")
        sys.exit(1)

    if args.build_only:
        print(f"Binary: {binary_path}")
        return

    # Step 3: Run
    print("=== Step 3: Running TOPMODEL ===")
    success = run_topmodel(binary_path, args.run_dir)

    # Step 4: Validate
    print("=== Step 4: Validating outputs ===")
    validate_outputs(args.run_dir)

    if not success:
        sys.exit(1)


if __name__ == '__main__':
    main()
