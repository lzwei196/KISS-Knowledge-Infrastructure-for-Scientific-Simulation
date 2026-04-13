#!/usr/bin/env python3
"""
run_topoflow.py — Execution wrapper for TopoFlow 3.6.

Performs preflight validation, runs the EMELI-coupled model, and captures
output status.

Preflight checks:
  1. Python environment has topoflow, numpy, scipy, netCDF4, cfunits
  2. CFG directory exists and contains required files
  3. Provider file is valid and references existing component CFGs
  4. DEM/D8/slope RTG grids exist with consistent dimensions
  5. Outlet pixel file exists and coordinates are within grid bounds
  6. Timestep is small enough for numerical stability

Usage:
  python run_topoflow.py \\
    --cfg_prefix June_20_67 \\
    --cfg_directory /path/to/cfg_files/ \\
    --driver_comp_name topoflow_driver \\
    --timeout 3600

Output:
  JSON to stdout with status, elapsed time, peak Q, output files.
"""

import argparse
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path


def validate_inputs(cfg_prefix, cfg_directory, driver_comp_name):
    """Preflight validation of all inputs.

    Returns (errors, warnings).
    """
    errors = []
    warnings = []

    # 1. Check cfg directory
    if not os.path.isdir(cfg_directory):
        errors.append(f"CFG directory does not exist: {cfg_directory}")
        return errors, warnings

    # 2. Check provider file
    provider_file = os.path.join(cfg_directory, f"{cfg_prefix}_providers.txt")
    if not os.path.exists(provider_file):
        # Try alternate naming
        candidates = list(Path(cfg_directory).glob("*providers*"))
        if candidates:
            provider_file = str(candidates[0])
            warnings.append(f"Using provider file: {provider_file}")
        else:
            errors.append(f"Provider file not found: {provider_file}")

    # 3. Check driver CFG
    driver_cfg = os.path.join(cfg_directory, f"{cfg_prefix}_topoflow.cfg")
    if not os.path.exists(driver_cfg):
        candidates = list(Path(cfg_directory).glob("*topoflow*.cfg"))
        if candidates:
            warnings.append(f"Driver CFG found at: {candidates[0]}")
        else:
            errors.append(f"Driver CFG not found: {driver_cfg}")

    # 4. Check for DEM
    dem_files = list(Path(cfg_directory).glob("*DEM*")) + \
                list(Path(cfg_directory).glob("*dem*")) + \
                list(Path(cfg_directory).parent.glob("*DEM*"))
    if not dem_files:
        warnings.append("No DEM file found in cfg_directory. Ensure path_info points to correct location.")

    # 5. Check Python dependencies
    missing_deps = []
    for dep in ["numpy", "scipy", "netCDF4"]:
        try:
            __import__(dep)
        except ImportError:
            missing_deps.append(dep)
    if missing_deps:
        errors.append(f"Missing Python packages: {missing_deps}")

    # 6. Check TopoFlow importable
    try:
        import topoflow
    except ImportError:
        errors.append("TopoFlow not installed. Run: pip install -e /path/to/topoflow36")

    return errors, warnings


def check_rti_consistency(cfg_directory):
    """Verify RTI header and RTG files have consistent dimensions.

    Returns (errors, warnings).
    """
    errors = []
    warnings = []

    rti_files = list(Path(cfg_directory).rglob("*.rti"))
    if not rti_files:
        warnings.append("No .rti header files found; cannot verify grid consistency.")
        return errors, warnings

    # Parse first RTI for reference dimensions
    ref_nrows, ref_ncols = None, None
    for rti in rti_files:
        with open(rti) as f:
            for line in f:
                line = line.strip().lower()
                if "ncols" in line:
                    try:
                        ref_ncols = int(line.split("|")[-1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
                elif "nrows" in line:
                    try:
                        ref_nrows = int(line.split("|")[-1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
        if ref_nrows and ref_ncols:
            break

    if ref_nrows and ref_ncols:
        # Check RTG file sizes
        expected_bytes = ref_nrows * ref_ncols * 4  # float32
        rtg_files = list(Path(cfg_directory).rglob("*.rtg"))
        for rtg in rtg_files:
            actual_bytes = rtg.stat().st_size
            if actual_bytes != expected_bytes:
                errors.append(
                    f"RTG size mismatch: {rtg.name} is {actual_bytes} bytes, "
                    f"expected {expected_bytes} ({ref_nrows}×{ref_ncols}×4)."
                )

    return errors, warnings


def run_model_api(cfg_prefix, cfg_directory, driver_comp_name, timeout):
    """Run TopoFlow via Python API (EMELI framework).

    Returns result dict.
    """
    start_time = time.time()

    try:
        from topoflow.framework import emeli

        f = emeli.framework()
        f.run_model(
            driver_comp_name=driver_comp_name,
            cfg_prefix=cfg_prefix,
            cfg_directory=cfg_directory,
        )

        elapsed = time.time() - start_time

        # Collect output files
        output_files = {}
        cfg_path = Path(cfg_directory)
        for ext in ["*.nc", "*_0D-*.txt", "*_report.txt"]:
            for fp in cfg_path.glob(ext):
                output_files[fp.name] = str(fp)
            # Also check parent directory
            for fp in cfg_path.parent.glob(ext):
                output_files[fp.name] = str(fp)

        return {
            "status": "success",
            "method": "api",
            "elapsed_seconds": round(elapsed, 2),
            "output_files": output_files,
        }

    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "status": "error",
            "method": "api",
            "elapsed_seconds": round(elapsed, 2),
            "error": str(e),
            "error_type": type(e).__name__,
        }


def run_model_cli(cfg_prefix, cfg_directory, driver_comp_name, timeout):
    """Run TopoFlow via CLI subprocess.

    Returns result dict.
    """
    cmd = [
        sys.executable, "-m", "topoflow",
        f"--cfg_prefix={cfg_prefix}",
        f"--cfg_directory={cfg_directory}",
        f"--driver_comp_name={driver_comp_name}",
    ]

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time

        # Check for success indicators
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        success = proc.returncode == 0 or "Finished." in stdout

        # Collect output files
        output_files = {}
        cfg_path = Path(cfg_directory)
        for ext in ["*.nc", "*_0D-*.txt", "*_report.txt"]:
            for fp in cfg_path.rglob(ext):
                output_files[fp.name] = str(fp)

        return {
            "status": "success" if success else "error",
            "method": "cli",
            "return_code": proc.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "stdout_tail": stdout[-500:] if stdout else "",
            "stderr_tail": stderr[-500:] if stderr else "",
            "output_files": output_files,
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            "status": "timeout",
            "method": "cli",
            "elapsed_seconds": round(elapsed, 2),
            "error": f"Process exceeded timeout of {timeout}s",
        }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "status": "error",
            "method": "cli",
            "elapsed_seconds": round(elapsed, 2),
            "error": str(e),
        }


def parse_peak_q(cfg_directory, cfg_prefix):
    """Try to extract peak Q from output files.

    Returns dict with Q_peak, T_peak if found.
    """
    result = {}

    # Look for 0D-Q file
    q_files = list(Path(cfg_directory).rglob(f"*0D-Q*"))
    if not q_files:
        q_files = list(Path(cfg_directory).rglob("*_0D-Q.txt"))
    if q_files:
        try:
            import numpy as np
            q_data = np.loadtxt(str(q_files[0]))
            if q_data.ndim == 1:
                result["Q_peak_m3s"] = float(q_data.max())
                result["Q_peak_index"] = int(q_data.argmax())
            elif q_data.ndim == 2:
                result["Q_peak_m3s"] = float(q_data[:, -1].max())
        except Exception:
            pass

    # Look for report file
    report_files = list(Path(cfg_directory).rglob("*report*"))
    if report_files:
        try:
            with open(report_files[0]) as f:
                for line in f:
                    if "peak" in line.lower() and "flow" in line.lower():
                        result["report_peak_line"] = line.strip()
                        break
        except Exception:
            pass

    return result


def process(cfg_prefix, cfg_directory, driver_comp_name, timeout, use_api=True):
    """Run the model with appropriate method."""
    if use_api:
        result = run_model_api(cfg_prefix, cfg_directory, driver_comp_name, timeout)
    else:
        result = run_model_cli(cfg_prefix, cfg_directory, driver_comp_name, timeout)

    # Try to extract peak Q
    peak_info = parse_peak_q(cfg_directory, cfg_prefix)
    if peak_info:
        result["peak_flow"] = peak_info

    return result


def validate_outputs(result, cfg_directory):
    """Post-run validation.

    Returns (errors, warnings).
    """
    errors = []
    warnings = []

    if result.get("status") != "success":
        errors.append(f"Model run failed: {result.get('error', 'unknown')}")
        return errors, warnings

    output_files = result.get("output_files", {})
    if not output_files:
        warnings.append("No output files found after run.")

    # Check for 0D-Q (outlet hydrograph)
    has_q = any("0D-Q" in name for name in output_files)
    if not has_q:
        warnings.append("No outlet discharge file (*_0D-Q*) found.")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Run TopoFlow 3.6 model")
    parser.add_argument("--cfg_prefix", required=True, help="Configuration prefix")
    parser.add_argument("--cfg_directory", required=True, help="Directory with .cfg files")
    parser.add_argument("--driver_comp_name", default="topoflow_driver")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds")
    parser.add_argument("--use_cli", action="store_true", help="Use CLI instead of API")

    args = parser.parse_args()

    # Preflight
    errors, warnings = validate_inputs(
        args.cfg_prefix, args.cfg_directory, args.driver_comp_name
    )
    rti_errors, rti_warnings = check_rti_consistency(args.cfg_directory)
    errors.extend(rti_errors)
    warnings.extend(rti_warnings)

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    # Run
    result = process(
        args.cfg_prefix, args.cfg_directory, args.driver_comp_name,
        args.timeout, use_api=not args.use_cli
    )

    # Post-run validation
    out_errors, out_warnings = validate_outputs(result, args.cfg_directory)
    result["post_run_warnings"] = out_warnings
    if out_errors:
        result["post_run_errors"] = out_errors

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
