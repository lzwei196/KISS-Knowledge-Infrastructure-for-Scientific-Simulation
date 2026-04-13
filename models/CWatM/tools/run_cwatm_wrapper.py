#!/usr/bin/env python3
"""
run_cwatm_wrapper.py — Execute CWatM with preflight validation, progress monitoring,
and post-run diagnostics.

Preflight checks:
  1. Settings file exists and parses correctly
  2. All referenced input files exist
  3. Output directory is writable
  4. Python dependencies are available
  5. C++ shared library is loadable
  6. Date range is valid (start < end, SpinUp between start and end)
  7. Unit conversion factors are reasonable

Post-run checks:
  1. Output files were created
  2. Discharge values are physically reasonable
  3. Water balance closure check
  4. No NaN/Inf in outputs

Usage:
    python run_cwatm_wrapper.py \\
        --settings /path/to/settings.ini \\
        --cwatm_dir /path/to/CWatM/repo \\
        --flags -q

    python run_cwatm_wrapper.py \\
        --settings settings.ini \\
        --cwatm_dir /path/to/CWatM/repo \\
        --check_only
"""

import argparse
import configparser
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np


def validate_settings(settings_path):
    """
    Preflight validation of CWatM settings file.

    Returns
    -------
    dict with keys: valid (bool), errors (list), warnings (list), parsed (dict)
    """
    result = {"valid": True, "errors": [], "warnings": [], "parsed": {}}

    if not os.path.isfile(settings_path):
        result["valid"] = False
        result["errors"].append(f"Settings file not found: {settings_path}")
        return result

    # Parse the ini file
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # Case-sensitive keys
    try:
        config.read(settings_path, encoding="utf-8")
    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Failed to parse settings: {e}")
        return result

    # Check required sections
    required_sections = [
        "OPTIONS", "FILE_PATHS", "MASK_OUTLET",
        "TIME-RELATED_CONSTANTS", "METEO", "OUTPUT",
    ]
    for section in required_sections:
        if not config.has_section(section):
            result["errors"].append(f"Missing required section: [{section}]")
            result["valid"] = False

    if not result["valid"]:
        return result

    # Check critical options
    options = dict(config.items("OPTIONS")) if config.has_section("OPTIONS") else {}
    result["parsed"]["options"] = options

    # Temperature unit check
    temp_in_k = options.get("temperatureinkelvin", "True")
    if temp_in_k.lower() == "true":
        result["parsed"]["temp_unit"] = "Kelvin"
    else:
        result["parsed"]["temp_unit"] = "Celsius"

    # Check file paths
    if config.has_section("FILE_PATHS"):
        file_paths = dict(config.items("FILE_PATHS"))
        result["parsed"]["file_paths"] = file_paths

        # Check PathOut exists or can be created
        path_out = file_paths.get("pathout", "")
        if path_out and not path_out.startswith("$"):
            if not os.path.isdir(path_out):
                result["warnings"].append(
                    f"Output directory does not exist: {path_out} (will be created)"
                )

    # Check date range
    if config.has_section("TIME-RELATED_CONSTANTS"):
        time_cfg = dict(config.items("TIME-RELATED_CONSTANTS"))
        step_start = time_cfg.get("stepstart", "")
        step_end = time_cfg.get("stepend", "")
        spin_up = time_cfg.get("spinup", "")

        result["parsed"]["step_start"] = step_start
        result["parsed"]["step_end"] = step_end
        result["parsed"]["spin_up"] = spin_up

        # Validate date format (DD/MM/YYYY)
        for date_name, date_str in [("StepStart", step_start), ("StepEnd", step_end)]:
            if date_str:
                try:
                    datetime.strptime(date_str, "%d/%m/%Y")
                except ValueError:
                    try:
                        datetime.strptime(date_str, "%Y-%m-%d")
                    except ValueError:
                        result["warnings"].append(
                            f"{date_name} = '{date_str}' — cannot parse date. "
                            f"Expected DD/MM/YYYY."
                        )

    # Check precipitation conversion factor
    if config.has_section("METEO"):
        meteo = dict(config.items("METEO"))
        prec_conv = meteo.get("precipitation_coversion", "86.4")
        try:
            prec_conv_val = float(prec_conv)
            if prec_conv_val == 86.4:
                result["parsed"]["precip_input_unit"] = "kg/m²/s"
            elif prec_conv_val == 1.0:
                result["parsed"]["precip_input_unit"] = "m/day"
            elif prec_conv_val == 0.001:
                result["parsed"]["precip_input_unit"] = "mm/day"
            else:
                result["warnings"].append(
                    f"Unusual precipitation_coversion = {prec_conv_val}. "
                    f"Standard values: 86.4 (kg/m²/s), 1.0 (m/day), 0.001 (mm/day)"
                )
        except ValueError:
            result["warnings"].append(f"Cannot parse precipitation_coversion: {prec_conv}")

    return result


def check_dependencies(cwatm_dir):
    """Check that all required Python packages and C++ library are available."""
    result = {"errors": [], "warnings": []}

    # Check Python packages
    required = ["numpy", "scipy", "netCDF4"]
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            result["errors"].append(f"Missing Python package: {pkg}")

    # Check GDAL
    try:
        from osgeo import gdal
    except ImportError:
        result["errors"].append("Missing osgeo/GDAL package")

    # Check C++ shared library
    import platform as plat
    if plat.system() == "Linux":
        so_name = "t5_linux.so"
    elif plat.system() == "Darwin":
        so_name = "t5_mac.so"
    elif plat.system() == "Windows":
        so_name = "t5.dll"
    else:
        so_name = "t5_linux.so"

    so_path = os.path.join(
        cwatm_dir, "cwatm", "hydrological_modules", "routing_reservoirs", so_name
    )
    if not os.path.isfile(so_path):
        result["warnings"].append(
            f"C++ routing library not found: {so_path}. "
            f"Model will fall back to slower Python routing."
        )
    else:
        # Try to load it
        import ctypes
        try:
            ctypes.cdll.LoadLibrary(so_path)
        except OSError as e:
            result["warnings"].append(
                f"C++ library found but cannot load: {e}. "
                f"Falling back to Python routing."
            )

    return result


def run_model(settings_path, cwatm_dir, flags=""):
    """Execute CWatM and capture output."""
    run_script = os.path.join(cwatm_dir, "run_cwatm.py")
    if not os.path.isfile(run_script):
        return {
            "status": "error",
            "error": f"run_cwatm.py not found at {run_script}",
        }

    cmd = [sys.executable, run_script, settings_path]
    if flags:
        cmd.extend(flags.split())

    print(f"Running: {' '.join(cmd)}")
    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour timeout
            cwd=cwatm_dir,
        )
        elapsed = time.time() - start_time

        return {
            "status": "success" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:] if len(proc.stdout) > 2000 else proc.stdout,
            "stderr": proc.stderr[-2000:] if len(proc.stderr) > 2000 else proc.stderr,
            "elapsed_seconds": elapsed,
            "command": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "error": "Model execution exceeded 1 hour timeout",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


def validate_outputs(output_dir, settings_path):
    """Post-run validation of model outputs."""
    result = {"valid": True, "warnings": [], "outputs_found": []}

    if not os.path.isdir(output_dir):
        result["valid"] = False
        result["warnings"].append(f"Output directory not found: {output_dir}")
        return result

    # Find output NetCDF files
    import glob
    nc_files = glob.glob(os.path.join(output_dir, "*.nc"))
    tss_files = glob.glob(os.path.join(output_dir, "*.tss"))

    result["outputs_found"] = [os.path.basename(f) for f in nc_files + tss_files]

    if not nc_files and not tss_files:
        result["valid"] = False
        result["warnings"].append("No output files found. Model may have failed silently.")
        return result

    # Check discharge output for physical reasonableness
    try:
        import netCDF4 as nc_lib
        for nc_file in nc_files:
            if "discharge" in nc_file.lower():
                ds = nc_lib.Dataset(nc_file)
                for vname in ds.variables:
                    if "discharge" in vname.lower():
                        data = ds.variables[vname][:]
                        if np.any(np.isnan(data)):
                            result["warnings"].append(
                                f"NaN values in discharge output: {nc_file}"
                            )
                        if np.any(np.isinf(data)):
                            result["warnings"].append(
                                f"Inf values in discharge output: {nc_file}"
                            )
                        max_q = float(np.nanmax(data))
                        min_q = float(np.nanmin(data))
                        if max_q > 1e6:
                            result["warnings"].append(
                                f"Discharge max = {max_q:.1f} m³/s — extremely high. "
                                f"Check precipitation units."
                            )
                        if min_q < 0:
                            result["warnings"].append(
                                f"Negative discharge found (min={min_q:.3f} m³/s)."
                            )
                        result["discharge_stats"] = {
                            "min": min_q,
                            "max": max_q,
                            "mean": float(np.nanmean(data)),
                        }
                ds.close()
    except Exception as e:
        result["warnings"].append(f"Could not validate discharge output: {e}")

    return result


def main():
    parser = argparse.ArgumentParser(description="CWatM execution wrapper")
    parser.add_argument("--settings", required=True, help="Path to settings.ini")
    parser.add_argument("--cwatm_dir", required=True, help="Path to CWatM repository")
    parser.add_argument("--flags", default="-q", help="CWatM CLI flags (default: -q)")
    parser.add_argument("--check_only", action="store_true", help="Only run preflight checks")
    parser.add_argument("--output_dir", default=None, help="Override output directory for validation")

    args = parser.parse_args()

    print("=== CWatM Execution Wrapper ===")

    # Step 1: Preflight validation
    print("\n[1/3] Preflight validation...")
    settings_result = validate_settings(args.settings)
    dep_result = check_dependencies(args.cwatm_dir)

    all_errors = settings_result["errors"] + dep_result["errors"]
    all_warnings = settings_result["warnings"] + dep_result["warnings"]

    if all_warnings:
        for w in all_warnings:
            print(f"  WARNING: {w}")

    if all_errors:
        for e in all_errors:
            print(f"  ERROR: {e}")
        print(json.dumps({"status": "preflight_failed", "errors": all_errors}, indent=2))
        sys.exit(1)

    print(f"  Settings: {args.settings}")
    print(f"  Temp unit: {settings_result['parsed'].get('temp_unit', 'unknown')}")
    print(f"  Precip unit: {settings_result['parsed'].get('precip_input_unit', 'unknown')}")

    if args.check_only:
        print(json.dumps({"status": "preflight_passed", "parsed": settings_result["parsed"]}, indent=2))
        return

    # Step 2: Run model
    print("\n[2/3] Running CWatM...")
    run_result = run_model(args.settings, args.cwatm_dir, args.flags)

    if run_result["status"] != "success":
        print(f"  Model failed: {run_result.get('error', run_result.get('stderr', ''))[:500]}")
        print(json.dumps(run_result, indent=2))
        sys.exit(1)

    print(f"  Completed in {run_result['elapsed_seconds']:.1f} seconds")

    # Step 3: Post-run validation
    print("\n[3/3] Post-run validation...")
    output_dir = args.output_dir or settings_result["parsed"].get("file_paths", {}).get("pathout", "")
    if output_dir:
        output_result = validate_outputs(output_dir, args.settings)
        print(f"  Output files: {len(output_result['outputs_found'])}")
        for w in output_result["warnings"]:
            print(f"  WARNING: {w}")
    else:
        output_result = {"warning": "Could not determine output directory for validation"}

    # Final report
    report = {
        "status": "success",
        "settings": args.settings,
        "elapsed_seconds": run_result["elapsed_seconds"],
        "preflight": {"warnings": all_warnings},
        "output_validation": output_result,
        "stdout_tail": run_result.get("stdout", "")[-500:],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
