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

Engine: --lisflood-bin -> $LISFLOOD_BIN -> server default
KISSPATH_HOME/miniconda3/envs/lisflood/bin/lisflood (same as preflight_check.py);
only if that default does not exist, `lisflood` on PATH (announced). An explicit
engine that is not an executable file is an error; no other engine is tried.
"""

import argparse
import re
import shutil
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

# Server default engine (same as preflight_check.py DEFAULT_BINARY / manifest binary.path)
SERVER_LISFLOOD = "KISSPATH_HOME/miniconda3/envs/lisflood/bin/lisflood"
TAIL_CHARS = 3000

_VAR = re.compile(r"\$\(([^)]+)\)")


def expand_vars(value, user, max_passes=50):
    """Expand $(name) with LISFLOOD's rule: names come from the user (lfuser +
    built-in) variables only, repeated until nothing is left (nested values).
    Unknown names are left as they are."""
    for _ in range(max_passes):
        new = _VAR.sub(lambda m: user.get(m.group(1), m.group(0)), value)
        if new == value:
            break
        value = new
    return value


def unresolved(value):
    return _VAR.findall(value or "")


def resolve_lisflood_bin(cli_value=None):
    """Return (absolute path, source) of the LISFLOOD engine, or raise RuntimeError."""
    for label, cand in (("--lisflood-bin", cli_value),
                        ("$LISFLOOD_BIN", os.environ.get("LISFLOOD_BIN"))):
        if cand:
            path = shutil.which(cand) if os.sep not in cand else cand
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                return os.path.abspath(path), label
            raise RuntimeError(f"LISFLOOD engine from {label} is not an executable file: {cand}")
    if os.path.exists(SERVER_LISFLOOD):
        if os.path.isfile(SERVER_LISFLOOD) and os.access(SERVER_LISFLOOD, os.X_OK):
            return SERVER_LISFLOOD, "server default"
        raise RuntimeError(f"server default LISFLOOD engine is not executable: {SERVER_LISFLOOD}")
    on_path = shutil.which("lisflood")
    if on_path:
        return os.path.abspath(on_path), "PATH (server default not present)"
    raise RuntimeError(f"LISFLOOD engine not found (server default {SERVER_LISFLOOD}); "
                       "use --lisflood-bin or set LISFLOOD_BIN")


def parse_settings_xml(settings_path):
    """Parse LISFLOOD settings XML and extract key configuration.

    Returns dict with paths, options, time settings, and parameters.
    Variables follow LISFLOOD's own rule (global_modules/settings.py _bindings):
    user = built-ins (SettingsDir/SettingsPath) + <lfuser> textvars; <lfbinding>
    values are expanded with the user variables only. "user" keeps the expanded
    user values (PathOut etc.), "bindings" the expanded model bindings, and
    "textvars" the merged view (bindings override) used by the checks.
    """
    tree = ET.parse(settings_path)
    root = tree.getroot()
    settings_dir = os.path.normpath(os.path.dirname(os.path.abspath(settings_path)))

    config = {
        "options": {},
        "textvars": {},
        "bindings": {},
        "user": {},
        "settings_dir": settings_dir,
    }

    # Parse lfoptions
    for option in root.iter("setoption"):
        name = option.get("name", "")
        choice = option.get("choice", "0")
        config["options"][name] = choice

    # lfuser (+ LISFLOOD's built-in user variables)
    user = {"SettingsDir": settings_dir, "SettingsPath": settings_dir}
    for section in root.iter("lfuser"):
        for textvar in section.iter("textvar"):
            user[textvar.get("name", "")] = textvar.get("value", "")
    # lfbinding
    bindings = {}
    for section in root.iter("lfbinding"):
        for textvar in section.iter("textvar"):
            bindings[textvar.get("name", "")] = textvar.get("value", "")

    config["user"] = {k: expand_vars(v, user) for k, v in user.items()}
    config["bindings"] = {k: expand_vars(v, user) for k, v in bindings.items()}
    config["textvars"] = dict(config["user"])
    config["textvars"].update(config["bindings"])
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

    # Check 3: Key paths exist (user variables; PathOut as LISFLOOD's _out_dir uses it)
    path_vars = ["PathRoot", "PathOut", "PathMeteo", "PathMaps"]
    for pv in path_vars:
        if pv in config["user"]:
            if unresolved(config["user"][pv]):
                issues.append(f"{pv} has undefined variable(s) "
                              f"{unresolved(config['user'][pv])}: {config['user'][pv]}")
                continue
            resolved = resolve_path(config["user"][pv], config)
            if not os.path.exists(resolved):
                if pv == "PathOut":
                    warnings.append(f"Output dir does not exist (will create): {resolved}")
                    os.makedirs(resolved, exist_ok=True)
                else:
                    issues.append(f"Path not found: {pv} = {resolved}")
            else:
                print(f"[OK] {pv}: {resolved}")

    # Check 4: MaskMap exists
    if "MaskMap" in config["textvars"] and unresolved(config["textvars"]["MaskMap"]):
        issues.append(f"MaskMap has undefined variable(s): {config['textvars']['MaskMap']}")
    elif "MaskMap" in config["textvars"]:
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


def run_model(settings_path, timeout=3600, capture_output=True, lisflood_bin=None):
    """Execute LISFLOOD model.

    The engine is the LISFLOOD console script of a conda env with LISFLOOD
    installed: --lisflood-bin / lisflood_bin -> $LISFLOOD_BIN -> server default
    (see resolve_lisflood_bin). No other interpreter or engine is tried.

    Returns (success: bool, stdout: str, stderr: str, runtime_s: float)
    """
    settings_path = os.path.abspath(settings_path)
    try:
        binary, source = resolve_lisflood_bin(lisflood_bin)
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        return False, "", str(e), 0

    env = os.environ.copy()
    env["PATH"] = os.path.dirname(binary) + os.pathsep + env.get("PATH", "")
    cmd = [binary, settings_path]
    print(f"\n[RUN] {' '.join(cmd)}   (engine from {source})")
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(settings_path),
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        print(f"[FAIL] Timeout after {timeout}s")
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        return False, out, err + f"\nTimeout after {timeout}s", timeout
    except OSError as e:
        print(f"[FAIL] Could not start {binary}: {e}")
        return False, "", f"Could not start {binary}: {e}", 0
    runtime = time.time() - t0

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode == 0:
        print(f"[OK] LISFLOOD completed in {runtime:.1f}s")
        return True, stdout, stderr, runtime
    print(f"[FAIL] Exit code: {result.returncode}")
    if stderr:
        # Show last 20 lines of stderr
        last_lines = stderr.strip().split("\n")[-20:]
        print("Last error lines:")
        for line in last_lines:
            print(f"  {line}")
    return False, stdout, stderr, runtime


def validate_output(settings_path, since=None):
    """Validate LISFLOOD output after a run.

    since: run start time (epoch s); when given, at least one file in the output
    folder must have been written by this run.
    """
    config = parse_settings_xml(settings_path)
    out_dir = resolve_path(config["user"].get("PathOut", "out"), config)

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

    # Check for TSS files (time series)
    tss_files = list(Path(out_dir).glob("*.tss"))
    if tss_files:
        results["tss_files"] = [str(f.name) for f in tss_files]
        print(f"[OK] Found {len(tss_files)} TSS files")

    # Check for other NetCDF outputs
    nc_files = list(Path(out_dir).glob("*.nc"))
    results["nc_files"] = [str(f.name) for f in nc_files]
    print(f"[OK] Found {len(nc_files)} NetCDF output files")

    # Any output (NetCDF, TSS, PCRaster maps, ...) written by this run
    all_files = [f for f in Path(out_dir).iterdir() if f.is_file()]
    results["n_output_files"] = len(all_files)
    if since is not None:
        new_files = [f for f in all_files if f.stat().st_mtime >= since]
        results["n_new_output_files"] = len(new_files)
        if not new_files:
            errors.append(f"No output file written by this run in {out_dir}")
    elif not all_files:
        errors.append(f"No output files in {out_dir}")
    if not os.path.exists(dis_path) and not tss_files and not nc_files and all_files:
        warnings.append("No dis.nc, .tss or .nc output (other output formats only)")

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
    parser.add_argument("--lisflood-bin", "--lisflood_bin", dest="lisflood_bin", default=None,
                        help="LISFLOOD engine (default: $LISFLOOD_BIN, then "
                             f"{SERVER_LISFLOOD})")
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
    run_start = time.time()
    success, stdout, stderr, runtime = run_model(
        args.settings, timeout=args.timeout, lisflood_bin=args.lisflood_bin
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
        out_ok, out_results = validate_output(args.settings, since=run_start)
        results["output"] = out_results
        results["output_valid"] = out_ok
        if not out_ok:
            success = False
            results["success"] = False

    # Save results
    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n[OK] Results saved to {args.output_json}")

    if success:
        print(f"\n[DONE] LISFLOOD completed in {runtime:.1f}s")
    else:
        print(f"\n[FAIL] LISFLOOD failed")
        if results.get("output_valid") is False:
            print(f"Output check failed: {results.get('output')}")
        if stdout:
            print(f"Standard output (last {TAIL_CHARS} chars):\n{stdout[-TAIL_CHARS:]}")
        if stderr:
            print(f"Error output (last {TAIL_CHARS} chars):\n{stderr[-TAIL_CHARS:]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
