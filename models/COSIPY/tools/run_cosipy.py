#!/usr/bin/env python3
"""Execute COSIPY model with preflight validation and monitoring.

Performs comprehensive preflight checks on configuration and input data,
runs the model, and validates output completeness.

Usage:
    python run_cosipy.py \\
        --config config.toml \\
        --constants constants.toml \\
        --source-dir /path/to/cosipy/source

    python run_cosipy.py --preflight-only  # just validate, don't run
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


def load_toml(path: str) -> dict:
    """Load a TOML configuration file.

    Args:
        path: Path to .toml file.

    Returns:
        Parsed TOML data.
    """
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib
    except ImportError:
        import toml
        with open(path) as f:
            return toml.load(f)

    with open(path, "rb") as f:
        return tomllib.load(f)


def validate_config(config_path: str) -> list:
    """Validate config.toml parameters.

    Args:
        config_path: Path to config.toml.

    Returns:
        List of error/warning messages.
    """
    issues = []

    try:
        cfg = load_toml(config_path)
    except Exception as e:
        return [f"ERROR: Cannot parse config.toml: {e}"]

    # Check required sections
    required_sections = ["SIMULATION_PERIOD", "FILENAMES", "DIMENSIONS"]
    for sec in required_sections:
        if sec not in cfg:
            issues.append(f"ERROR: Missing section [{sec}] in config.toml")

    if "SIMULATION_PERIOD" in cfg:
        ts = cfg["SIMULATION_PERIOD"].get("time_start", "")
        te = cfg["SIMULATION_PERIOD"].get("time_end", "")
        if not ts or not te:
            issues.append("ERROR: time_start or time_end not set")
        elif ts >= te:
            issues.append(f"ERROR: time_start ({ts}) >= time_end ({te})")

    if "FILENAMES" in cfg:
        data_path = cfg["FILENAMES"].get("data_path", "./data/")
        input_nc = cfg["FILENAMES"].get("input_netcdf", "")
        full_input = os.path.join(data_path, "input", input_nc)
        if not os.path.exists(full_input):
            issues.append(f"ERROR: Input file not found: {full_input}")

    return issues


def validate_constants(constants_path: str) -> list:
    """Validate constants.toml parameters.

    Args:
        constants_path: Path to constants.toml.

    Returns:
        List of error/warning messages.
    """
    issues = []

    try:
        cst = load_toml(constants_path)
    except Exception as e:
        return [f"ERROR: Cannot parse constants.toml: {e}"]

    if "GENERAL" in cst:
        dt = cst["GENERAL"].get("dt", 3600)
        if dt <= 0:
            issues.append(f"ERROR: dt must be positive, got {dt}")
        if dt > 86400:
            issues.append(f"WARNING: dt={dt}s (>{dt/3600:.0f}h) is unusually large")

        max_layers = cst["GENERAL"].get("max_layers", 200)
        if max_layers < 50:
            issues.append(f"WARNING: max_layers={max_layers} is very low, may crash")

    if "INITIAL_CONDITIONS" in cst:
        ic = cst["INITIAL_CONDITIONS"]
        t_bottom = ic.get("temperature_bottom", 270.16)
        if t_bottom > 273.16:
            issues.append(f"WARNING: temperature_bottom={t_bottom}K > melting point")
        if t_bottom < 200:
            issues.append(f"WARNING: temperature_bottom={t_bottom}K is unrealistically cold")

    if "CONSTANTS" in cst:
        con = cst["CONSTANTS"]
        a_snow = con.get("albedo_fresh_snow", 0.85)
        a_ice = con.get("albedo_ice", 0.3)
        if a_snow < a_ice:
            issues.append(f"ERROR: albedo_fresh_snow ({a_snow}) < albedo_ice ({a_ice})")

    return issues


def validate_input_data(config_path: str, constants_path: str) -> list:
    """Validate input netCDF data ranges and consistency.

    Args:
        config_path: Path to config.toml.
        constants_path: Path to constants.toml.

    Returns:
        List of error/warning messages.
    """
    issues = []

    try:
        import xarray as xr
        cfg = load_toml(config_path)
        cst = load_toml(constants_path)
    except ImportError:
        return ["WARNING: xarray not available, skipping input data validation"]
    except Exception as e:
        return [f"WARNING: Cannot load config for data validation: {e}"]

    data_path = cfg.get("FILENAMES", {}).get("data_path", "./data/")
    input_nc = cfg.get("FILENAMES", {}).get("input_netcdf", "")
    full_input = os.path.join(data_path, "input", input_nc)

    if not os.path.exists(full_input):
        return [f"ERROR: Input file not found: {full_input}"]

    try:
        ds = xr.open_dataset(full_input)
    except Exception as e:
        return [f"ERROR: Cannot open input file: {e}"]

    # Check required variables
    required_vars = ["T2", "RH2", "U2", "G", "PRES", "MASK"]
    for var in required_vars:
        if var not in ds.data_vars and var not in ds.coords:
            issues.append(f"ERROR: Missing required variable: {var}")

    # Precipitation check
    has_rrr = "RRR" in ds.data_vars
    has_sf = "SNOWFALL" in ds.data_vars
    if not has_rrr and not has_sf:
        issues.append("ERROR: Need at least one of RRR or SNOWFALL")

    # Longwave check
    has_lw = "LWin" in ds.data_vars
    has_n = "N" in ds.data_vars
    if not has_lw and not has_n:
        issues.append("ERROR: Need at least one of LWin or N")

    # Bounds checks
    bounds = {
        "T2": (223.16, 316.16),
        "RH2": (0.0, 100.0),
        "U2": (0.0, 50.0),
        "G": (0.0, 1600.0),
        "PRES": (200.0, 1080.0),
        "RRR": (0.0, 20.0),
    }

    for var, (lo, hi) in bounds.items():
        if var in ds.data_vars:
            vmin = float(ds[var].min())
            vmax = float(ds[var].max())
            if vmin < lo:
                issues.append(f"WARNING: {var} min={vmin:.2f} below expected {lo}")
            if vmax > hi:
                issues.append(f"WARNING: {var} max={vmax:.2f} above expected {hi}")

    # dt consistency check
    dt_config = cst.get("GENERAL", {}).get("dt", 3600)
    time_vals = ds.time.values
    if len(time_vals) > 1:
        time_diff = (time_vals[1] - time_vals[0]) / np.timedelta64(1, "s")
        if abs(time_diff - dt_config) > 1:
            issues.append(
                f"WARNING: dt={dt_config}s in constants.toml but input time step is {time_diff}s"
            )

    # Time range check
    ts = cfg.get("SIMULATION_PERIOD", {}).get("time_start", "")
    te = cfg.get("SIMULATION_PERIOD", {}).get("time_end", "")
    if ts and te:
        data_start = str(time_vals[0])[:16]
        data_end = str(time_vals[-1])[:16]
        if ts < data_start:
            issues.append(f"WARNING: time_start ({ts}) before data start ({data_start})")
        if te > data_end:
            issues.append(f"WARNING: time_end ({te}) after data end ({data_end})")

    # NaN check in masked cells
    if "MASK" in ds:
        mask = ds["MASK"].values
        for var in ["T2", "RH2", "U2", "G", "PRES"]:
            if var in ds.data_vars:
                data = ds[var].values
                # Check if any masked cell has NaN at any time
                for t in range(min(data.shape[0], 10)):  # check first 10 timesteps
                    masked_vals = data[t][mask == 1]
                    if np.isnan(masked_vals).any():
                        issues.append(f"ERROR: {var} has NaN in glacier cells at timestep {t}")
                        break

    ds.close()
    return issues


def run_model(source_dir: str, config_path: str, constants_path: str,
              timeout: int = 3600) -> dict:
    """Execute the COSIPY model.

    Args:
        source_dir: Path to COSIPY source directory.
        config_path: Path to config.toml.
        constants_path: Path to constants.toml.
        timeout: Max runtime in seconds.

    Returns:
        Dictionary with status, runtime, and output info.
    """
    cmd = [
        sys.executable, os.path.join(source_dir, "COSIPY.py"),
        "-c", config_path,
        "-x", constants_path,
    ]

    print(f"Running: {' '.join(cmd)}")
    print(f"Working directory: {source_dir}")

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=source_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time

        return {
            "status": "success" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "runtime_seconds": round(elapsed, 2),
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "returncode": -1,
            "runtime_seconds": timeout,
            "stdout": "",
            "stderr": f"Process timed out after {timeout}s",
        }
    except Exception as e:
        return {
            "status": "error",
            "returncode": -1,
            "runtime_seconds": time.time() - start_time,
            "stdout": "",
            "stderr": str(e),
        }


def validate_output(config_path: str) -> list:
    """Validate model output after execution.

    Args:
        config_path: Path to config.toml.

    Returns:
        List of validation messages.
    """
    issues = []

    try:
        import xarray as xr
        cfg = load_toml(config_path)
    except Exception:
        return ["WARNING: Cannot validate output"]

    data_path = cfg.get("FILENAMES", {}).get("data_path", "./data/")
    output_dir = os.path.join(data_path, "output")

    if not os.path.exists(output_dir):
        return ["ERROR: Output directory does not exist"]

    # Find output files
    nc_files = list(Path(output_dir).glob("*.nc"))
    if not nc_files:
        return ["ERROR: No output netCDF files found"]

    for nc_file in nc_files:
        ds = xr.open_dataset(str(nc_file))

        expected_vars = ["MB", "SNOWHEIGHT", "TS", "ALBEDO"]
        for var in expected_vars:
            if var in ds.data_vars:
                if np.isnan(ds[var].values).all():
                    issues.append(f"WARNING: {var} is all NaN in {nc_file.name}")
            else:
                issues.append(f"INFO: {var} not in output (may be disabled in config)")

        ds.close()

    if not issues:
        issues.append("Output validation: PASSED")

    return issues


def main():
    parser = argparse.ArgumentParser(description="Run COSIPY with preflight checks")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml")
    parser.add_argument("--constants", default="constants.toml", help="Path to constants.toml")
    parser.add_argument("--source-dir", default=".", help="COSIPY source directory")
    parser.add_argument("--preflight-only", action="store_true", help="Only validate, don't run")
    parser.add_argument("--timeout", type=int, default=3600, help="Max runtime in seconds")
    args = parser.parse_args()

    print("=" * 60)
    print("COSIPY Execution Wrapper")
    print("=" * 60)

    # Preflight checks
    print("\n--- Preflight Checks ---")

    config_issues = validate_config(args.config)
    constants_issues = validate_constants(args.constants)
    data_issues = validate_input_data(args.config, args.constants)

    all_issues = config_issues + constants_issues + data_issues
    errors = [i for i in all_issues if i.startswith("ERROR")]
    warnings = [i for i in all_issues if i.startswith("WARNING")]

    for issue in all_issues:
        print(f"  {issue}")

    if errors:
        print(f"\n*** {len(errors)} ERRORS found — fix before running ***")
        if not args.preflight_only:
            print("Aborting execution.")
            sys.exit(1)
    elif warnings:
        print(f"\n{len(warnings)} warnings (non-blocking)")

    if args.preflight_only:
        print("\nPreflight complete (--preflight-only).")
        return

    # Run model
    print("\n--- Running COSIPY ---")
    result = run_model(args.source_dir, args.config, args.constants, args.timeout)

    print(f"\nStatus: {result['status']}")
    print(f"Runtime: {result['runtime_seconds']:.1f}s")

    if result["status"] != "success":
        print(f"Error output:\n{result['stderr'][:1000]}")
        sys.exit(1)

    # Validate output
    print("\n--- Output Validation ---")
    output_issues = validate_output(args.config)
    for issue in output_issues:
        print(f"  {issue}")

    print("\n" + "=" * 60)
    print("COSIPY execution complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
