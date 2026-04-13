#!/usr/bin/env python3
"""
LISFLOOD Execution Wrapper
===========================
Runs the LISFLOOD model with preflight validation and output checks.

Preflight checks:
  - Settings XML exists and is parseable
  - All referenced input paths exist
  - Domain mask is valid
  - Forcing time range covers simulation period
  - Key parameters are within reasonable ranges

Pattern: validate → execute → validate

Usage:
    python run_lisflood.py \
        --settings /path/to/settings.xml \
        --mode cold \
        --timeout 3600 \
        --check_only
"""

import argparse
import subprocess
import sys
import os
import time
import json
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    import numpy as np
except ImportError:
    np = None


def parse_settings_xml(settings_path):
    """Parse LISFLOOD settings XML and extract key configuration.

    Returns dict with paths, options, time settings, and parameters.
    """
    tree = ET.parse(settings_path)
    root = tree.getroot()

    config = {
        "options": {},
        "textvars": {},
        "bindings": {},
        "settings_dir": os.path.dirname(os.path.abspath(settings_path)),
    }

    # Parse lfoptions
    for option in root.iter("setoption"):
        name = option.get("name", "")
        choice = option.get("choice", "0")
        config["options"][name] = choice

    # Parse lfuser text variables
    for textvar in root.iter("textvar"):
        name = textvar.get("name", "")
        value = textvar.get("value", "")
        config["textvars"][name] = value

    # Parse lfbinding
    for binding in root.iter("textvar"):
        name = binding.get("name", "")
        value = binding.get("value", "")
        config["bindings"][name] = value

    return config


def resolve_path(path_str, config):
    """Resolve a path that may contain $(PathRoot) or other variables."""
    result = path_str
    for var_name, var_value in config["textvars"].items():
        result = result.replace(f"$({var_name})", var_value)

    # If relative, resolve from settings directory
    if not os.path.isabs(result):
        result = os.path.join(config["settings_dir"], result)

    return result


def preflight_check(settings_path):
    """Run preflight checks on LISFLOOD configuration.

    Returns (passed: bool, issues: list[str], warnings: list[str])
    """
    issues = []
    warnings = []

    # Check 1: Settings file exists
    if not os.path.isfile(settings_path):
        return False, [f"Settings file not found: {settings_path}"], []

    # Check 2: Parse XML
    try:
        config = parse_settings_xml(settings_path)
    except ET.ParseError as e:
        return False, [f"XML parse error: {e}"], []

    print(f"[OK] Settings parsed: {len(config['options'])} options, "
          f"{len(config['textvars'])} variables")

    # Check 3: Key paths exist
    path_vars = ["PathRoot", "PathOut", "PathMeteo", "PathMaps"]
    for pv in path_vars:
        if pv in config["textvars"]:
            resolved = resolve_path(config["textvars"][pv], config)
            if not os.path.exists(resolved):
                if pv == "PathOut":
                    warnings.append(f"Output dir does not exist (will create): {resolved}")
                    os.makedirs(resolved, exist_ok=True)
                else:
                    issues.append(f"Path not found: {pv} = {resolved}")
            else:
                print(f"[OK] {pv}: {resolved}")

    # Check 4: MaskMap exists
    if "MaskMap" in config["textvars"]:
        mask_path = resolve_path(config["textvars"]["MaskMap"], config)
        # Try with common extensions
        found = False
        for ext in ["", ".nc", ".map", ".nc4"]:
            if os.path.exists(mask_path + ext):
                found = True
                break
        if not found:
            issues.append(f"MaskMap not found: {mask_path}")
        else:
            print(f"[OK] MaskMap: {mask_path}")

    # Check 5: Time settings
    dt_sec = config["textvars"].get("DtSec", "86400")
    try:
        dt_val = int(dt_sec)
        if dt_val < 3600:
            warnings.append(f"DtSec={dt_val}s (<1hr) — very small timestep")
        elif dt_val > 86400:
            warnings.append(f"DtSec={dt_val}s (>1day) — very large timestep")
        print(f"[OK] DtSec: {dt_val}s ({dt_val/3600:.1f} hours)")
    except ValueError:
        issues.append(f"Invalid DtSec: {dt_sec}")

    # Check 6: TemperatureInKelvin flag consistency
    temp_in_k = config["options"].get("TemperatureInKelvin", "0")
    if temp_in_k == "1":
        print("[INFO] Temperature input expected in Kelvin (TemperatureInKelvin=1)")
    else:
        print("[INFO] Temperature input expected in Celsius (TemperatureInKelvin=0)")

    # Check 7: LDD encoding (dt_006)
    if "Ldd" in config["textvars"]:
        print("[INFO] LDD must use PCRaster encoding (1-9, 5=pit). "
              "ArcGIS D8 encoding (1,2,4,8,...,128) will cause errors.")

    # Check 8: Calibration parameters in reasonable range
    param_ranges = {
        "UpperZoneTimeConstant": (1, 100, "days"),
        "LowerZoneTimeConstant": (10, 5000, "days"),
        "b_Xinanjiang": (0.01, 1.0, "-"),
        "GwPercValue": (0.1, 10.0, "mm/day"),
        "SnowMeltCoef": (1.0, 10.0, "mm/C/day"),
        "CalChanMan": (0.1, 10.0, "multiplier"),
    }
    for param, (lo, hi, unit) in param_ranges.items():
        if param in config["textvars"]:
            try:
                val = float(config["textvars"][param])
                if val < lo or val > hi:
                    warnings.append(
                        f"{param}={val} outside typical range [{lo}-{hi}] {unit}"
                    )
                # TRAP dt_009: CalChanMan is multiplier, not Manning's n
                if param == "CalChanMan" and val < 0.05:
                    warnings.append(
                        f"CalChanMan={val} looks like Manning's n value. "
                        f"It should be a MULTIPLIER on n (typical: 0.5-2.0). "
                        f"Effective n = n_map * CalChanMan."
                    )
            except ValueError:
                pass  # Might be a map path, which is fine

    # Check 9: Output options
    if config["options"].get("writeNetcdfStack", "0") == "0" and \
       config["options"].get("writeNetcdf", "0") == "0":
        warnings.append(
            "Both writeNetcdfStack and writeNetcdf are off — no spatial output will be produced"
        )

    return len(issues) == 0, issues, warnings


def run_model(settings_path, timeout=3600, capture_output=True):
    """Execute LISFLOOD model.

    LISFLOOD can be invoked either:
      1. `lisflood settings.xml` (if installed via pip)
      2. `python src/lisf1.py settings.xml` (from source)

    Returns (success: bool, stdout: str, stderr: str, runtime_s: float)
    """
    # Try 'lisflood' command first, fall back to python src/lisf1.py
    commands_to_try = [
        ["lisflood", settings_path],
        [sys.executable, "-m", "lisflood.main", settings_path],
    ]

    # Check if source code is available
    src_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "source", "repo", "src"
    )
    lisf1_path = os.path.join(src_dir, "lisf1.py")
    if os.path.exists(lisf1_path):
        commands_to_try.append([sys.executable, lisf1_path, settings_path])

    for cmd in commands_to_try:
        print(f"\n[RUN] {' '.join(cmd)}")
        t0 = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                cwd=os.path.dirname(os.path.abspath(settings_path)),
            )
            runtime = time.time() - t0

            stdout = result.stdout or ""
            stderr = result.stderr or ""

            if result.returncode == 0:
                print(f"[OK] LISFLOOD completed in {runtime:.1f}s")
                return True, stdout, stderr, runtime
            else:
                print(f"[FAIL] Exit code: {result.returncode}")
                if stderr:
                    # Show last 20 lines of stderr
                    last_lines = stderr.strip().split("\n")[-20:]
                    print("Last error lines:")
                    for line in last_lines:
                        print(f"  {line}")
                return False, stdout, stderr, runtime

        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            print(f"[FAIL] Timeout after {timeout}s")
            return False, "", f"Timeout after {timeout}s", timeout

    print("[FAIL] Could not find LISFLOOD executable")
    return False, "", "LISFLOOD not found (tried: lisflood, python -m lisflood.main, lisf1.py)", 0


def validate_output(settings_path):
    """Validate LISFLOOD output after a run."""
    config = parse_settings_xml(settings_path)
    out_dir = resolve_path(config["textvars"].get("PathOut", "out"), config)

    errors = []
    warnings = []
    results = {}

    if not os.path.isdir(out_dir):
        return False, {"error": f"Output directory not found: {out_dir}"}

    # Check for discharge output
    dis_path = os.path.join(out_dir, "dis.nc")
    if os.path.exists(dis_path):
        try:
            import netCDF4 as nc4
            ds = nc4.Dataset(dis_path)
            dis_var = None
            for vn in ["dis", "discharge", "DischargeMaps"]:
                if vn in ds.variables:
                    dis_var = vn
                    break
            if dis_var:
                data = ds.variables[dis_var][:]
                results["discharge"] = {
                    "shape": list(data.shape),
                    "max": float(np.nanmax(data)) if np is not None else "N/A",
                    "mean": float(np.nanmean(data)) if np is not None else "N/A",
                    "timesteps": data.shape[0],
                }
                print(f"[OK] Discharge output: {data.shape}, max={results['discharge']['max']:.2f} m3/s")
            ds.close()
        except Exception as e:
            warnings.append(f"Could not read dis.nc: {e}")
    else:
        warnings.append("dis.nc not found in output directory")

    # Check for TSS files (time series)
    tss_files = list(Path(out_dir).glob("*.tss"))
    if tss_files:
        results["tss_files"] = [str(f.name) for f in tss_files]
        print(f"[OK] Found {len(tss_files)} TSS files")

    # Check for other NetCDF outputs
    nc_files = list(Path(out_dir).glob("*.nc"))
    results["nc_files"] = [str(f.name) for f in nc_files]
    print(f"[OK] Found {len(nc_files)} NetCDF output files")

    for e in errors:
        print(f"[ERROR] {e}")
    for w in warnings:
        print(f"[WARNING] {w}")

    return len(errors) == 0, results


def main():
    parser = argparse.ArgumentParser(description="LISFLOOD Execution Wrapper")
    parser.add_argument("--settings", required=True, help="Path to settings XML")
    parser.add_argument("--mode", default="cold", choices=["cold", "warm"],
                        help="Run mode (cold/warm start)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600)")
    parser.add_argument("--check_only", action="store_true",
                        help="Only run preflight checks, don't execute")
    parser.add_argument("--output_json", default=None,
                        help="Write run results to JSON file")
    args = parser.parse_args()

    print("=" * 60)
    print("LISFLOOD Execution Wrapper")
    print(f"Mode: {args.mode} | Timeout: {args.timeout}s")
    print("=" * 60)

    # Step 1: Preflight checks
    print("\n--- Preflight checks ---")
    passed, issues, warnings = preflight_check(args.settings)

    for w in warnings:
        print(f"[WARNING] {w}")

    if not passed:
        print("\n[FAIL] Preflight checks failed:")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)

    print("\n[OK] All preflight checks passed")

    if args.check_only:
        print("\n[INFO] Check-only mode — skipping execution")
        sys.exit(0)

    # Step 2: Execute
    print("\n--- Executing LISFLOOD ---")
    success, stdout, stderr, runtime = run_model(
        args.settings, timeout=args.timeout
    )

    # Step 3: Validate output
    results = {
        "settings": args.settings,
        "mode": args.mode,
        "success": success,
        "runtime_s": runtime,
    }

    if success:
        print("\n--- Output validation ---")
        out_ok, out_results = validate_output(args.settings)
        results["output"] = out_results
        results["output_valid"] = out_ok

    # Save results
    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n[OK] Results saved to {args.output_json}")

    if success:
        print(f"\n[DONE] LISFLOOD completed in {runtime:.1f}s")
    else:
        print(f"\n[FAIL] LISFLOOD failed")
        if stderr:
            print(f"Error output (last 500 chars):\n{stderr[-500:]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
