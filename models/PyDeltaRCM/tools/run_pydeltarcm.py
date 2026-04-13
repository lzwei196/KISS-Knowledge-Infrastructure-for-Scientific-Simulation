#!/usr/bin/env python3
"""
Execution wrapper for pyDeltaRCM.

Runs the model with preflight validation, progress reporting,
and post-run output verification.

Pattern: validate config → preflight checks → execute → validate output
"""

import argparse
import json
import os
import sys
import time
import yaml


def validate_config_file(config_path: str) -> list:
    """Validate a YAML configuration file before running.

    Parameters
    ----------
    config_path : str
        Path to the YAML config file.

    Returns
    -------
    list
        List of error strings. Empty means valid.
    """
    errors = []

    if not os.path.isfile(config_path):
        errors.append(f"Config file not found: {config_path}")
        return errors

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        errors.append(f"YAML parse error: {e}")
        return errors

    if config is None:
        errors.append("Config file is empty")
        return errors

    # Check critical constraints
    if "dx" in config:
        dx = config["dx"]
        length = config.get("Length", 5000)
        width = config.get("Width", 10000)
        if dx <= 0:
            errors.append(f"dx must be positive, got {dx}")
        if dx > length:
            errors.append(f"dx ({dx}) > Length ({length})")
        if dx > width:
            errors.append(f"dx ({dx}) > Width ({width})")

    # Check gamma stability
    S0 = config.get("S0", 0.00015)
    dx = config.get("dx", 50)
    u0 = config.get("u0", 1.0)
    gamma = 9.81 * S0 * dx / (u0 ** 2)
    if gamma > 0.1:
        errors.append(
            f"gamma = {gamma:.4f} > 0.1 — model will likely be unstable"
        )

    # Check f_bedload range
    fb = config.get("f_bedload", 0.5)
    if fb < 0 or fb > 1:
        errors.append(f"f_bedload must be in [0, 1], got {fb}")

    # Check output directory
    out_dir = config.get("out_dir", "deltaRCM_Output")
    parent = os.path.dirname(os.path.abspath(out_dir))
    if not os.path.isdir(parent):
        errors.append(f"Parent directory of out_dir does not exist: {parent}")

    return errors


def preflight_checks() -> list:
    """Run preflight checks for pyDeltaRCM dependencies.

    Returns
    -------
    list
        List of warning strings. Empty means all dependencies available.
    """
    warnings = []

    try:
        import pyDeltaRCM
        warnings.append(f"pyDeltaRCM version: {pyDeltaRCM.__version__}")
    except ImportError:
        warnings.append("ERROR: pyDeltaRCM not installed. Run: pip install pyDeltaRCM")
        return warnings

    try:
        import numpy
        warnings.append(f"numpy version: {numpy.__version__}")
    except ImportError:
        warnings.append("ERROR: numpy not found")

    try:
        import numba
        warnings.append(f"numba version: {numba.__version__}")
    except ImportError:
        warnings.append("ERROR: numba not found — JIT compilation will fail")

    try:
        import netCDF4
        warnings.append(f"netCDF4 version: {netCDF4.__version__}")
    except ImportError:
        warnings.append("WARNING: netCDF4 not found — output saving will fail")

    try:
        import matplotlib
        warnings.append(f"matplotlib version: {matplotlib.__version__}")
    except ImportError:
        warnings.append("WARNING: matplotlib not found — figure saving disabled")

    return warnings


def run_model(
    config_path: str,
    timesteps: int = None,
    time_years: float = None,
    If: float = 0.05,
    progress_interval: int = 10,
    dry_run: bool = False,
) -> dict:
    """Run pyDeltaRCM with the given configuration.

    Parameters
    ----------
    config_path : str
        Path to YAML configuration file.
    timesteps : int, optional
        Number of timesteps to run. If None, uses time_years.
    time_years : float, optional
        Simulation duration in years of model time.
    If : float
        Intermittency factor (for time_years to timestep conversion).
    progress_interval : int
        Print progress every N timesteps.
    dry_run : bool
        If True, only validate without running.

    Returns
    -------
    dict
        Run results with status, timing, and output info.
    """
    import pyDeltaRCM

    result = {
        "status": "pending",
        "config_path": os.path.abspath(config_path),
        "errors": [],
        "warnings": [],
    }

    # Validate config
    errors = validate_config_file(config_path)
    if any("ERROR" in e or "must" in e.lower() or ">" in e for e in errors):
        result["status"] = "failed"
        result["errors"] = errors
        return result

    if dry_run:
        result["status"] = "dry_run_ok"
        result["warnings"] = errors
        return result

    # Initialize model
    t_start = time.time()
    try:
        delta = pyDeltaRCM.DeltaModel(input_file=config_path)
    except Exception as e:
        result["status"] = "init_failed"
        result["errors"].append(f"Initialization failed: {str(e)}")
        return result

    result["dt_seconds"] = float(delta._dt)
    result["grid_shape"] = [delta.L, delta.W]
    result["gamma"] = float(delta.gamma)

    # Determine number of timesteps
    if timesteps is not None:
        n_steps = timesteps
    elif time_years is not None:
        total_seconds = time_years * 365.25 * 86400
        n_steps = int(total_seconds / delta._dt)
    else:
        n_steps = 100  # default

    result["n_timesteps"] = n_steps

    # Run
    try:
        for t in range(n_steps):
            delta.update()
            if (t + 1) % progress_interval == 0:
                elapsed = time.time() - t_start
                rate = (t + 1) / elapsed
                eta = (n_steps - t - 1) / rate if rate > 0 else 0
                print(
                    f"  Step {t+1}/{n_steps} | "
                    f"Model time: {delta._time:.0f}s ({delta._time/86400:.1f} days) | "
                    f"Rate: {rate:.1f} steps/s | "
                    f"ETA: {eta:.0f}s"
                )
    except Exception as e:
        result["status"] = "run_failed"
        result["errors"].append(f"Run failed at step {t}: {str(e)}")
        try:
            delta.finalize()
        except Exception:
            pass
        return result

    # Finalize
    try:
        delta.finalize()
    except Exception as e:
        result["warnings"].append(f"Finalization warning: {str(e)}")

    t_end = time.time()
    result["status"] = "completed"
    result["wall_time_seconds"] = t_end - t_start
    result["final_model_time_seconds"] = float(delta._time)
    result["final_model_time_days"] = float(delta._time / 86400)
    result["output_dir"] = delta.prefix_abspath

    return result


def validate_output(output_dir: str) -> dict:
    """Validate model output after a run.

    Parameters
    ----------
    output_dir : str
        Path to the output directory.

    Returns
    -------
    dict
        Validation results.
    """
    results = {"valid": True, "checks": [], "errors": []}

    # Check output directory exists
    if not os.path.isdir(output_dir):
        results["valid"] = False
        results["errors"].append(f"Output directory not found: {output_dir}")
        return results

    # Check for NetCDF output
    nc_path = os.path.join(output_dir, "pyDeltaRCM_output.nc")
    if os.path.isfile(nc_path):
        results["checks"].append(f"NetCDF output found: {nc_path}")
        size_mb = os.path.getsize(nc_path) / (1024 * 1024)
        results["checks"].append(f"NetCDF size: {size_mb:.1f} MB")

        try:
            import netCDF4
            ds = netCDF4.Dataset(nc_path, "r")
            results["variables"] = list(ds.variables.keys())
            results["dimensions"] = {
                k: len(v) for k, v in ds.dimensions.items()
            }
            ds.close()
        except Exception as e:
            results["errors"].append(f"NetCDF read error: {e}")
    else:
        results["checks"].append("No NetCDF output (grids not saved)")

    # Check for log file
    log_files = [f for f in os.listdir(output_dir) if f.endswith(".log")]
    if log_files:
        results["checks"].append(f"Log file: {log_files[0]}")
    else:
        results["errors"].append("No log file found")

    # Check for figure files
    fig_files = [f for f in os.listdir(output_dir) if f.endswith(".png")]
    results["checks"].append(f"Figure files: {len(fig_files)}")

    if results["errors"]:
        results["valid"] = False

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Run pyDeltaRCM with preflight checks and output validation"
    )
    parser.add_argument("config", help="Path to YAML configuration file")
    parser.add_argument("--timesteps", type=int, help="Number of timesteps")
    parser.add_argument("--time-years", type=float, help="Duration in model years")
    parser.add_argument("--If", type=float, default=0.05, help="Intermittency factor")
    parser.add_argument("--progress", type=int, default=10,
                        help="Progress print interval")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only validate, don't run")
    parser.add_argument("--output-json", type=str, help="Save results to JSON")

    args = parser.parse_args()

    print("=" * 60)
    print("pyDeltaRCM Execution Wrapper")
    print("=" * 60)

    # Preflight
    print("\n--- Preflight Checks ---")
    preflight = preflight_checks()
    for msg in preflight:
        print(f"  {msg}")

    if any("ERROR" in msg for msg in preflight):
        print("\nPreflight FAILED. Fix errors before running.")
        sys.exit(1)

    # Config validation
    print(f"\n--- Config Validation: {args.config} ---")
    config_errors = validate_config_file(args.config)
    for msg in config_errors:
        print(f"  {msg}")

    # Run
    print("\n--- Running Model ---")
    result = run_model(
        args.config,
        timesteps=args.timesteps,
        time_years=args.time_years,
        If=args.If,
        progress_interval=args.progress,
        dry_run=args.dry_run,
    )

    print(f"\nStatus: {result['status']}")
    if result.get("wall_time_seconds"):
        print(f"Wall time: {result['wall_time_seconds']:.1f} seconds")
    if result.get("final_model_time_days"):
        print(f"Model time: {result['final_model_time_days']:.1f} days")

    if result.get("errors"):
        print("\nErrors:")
        for e in result["errors"]:
            print(f"  {e}")

    # Output validation
    if result.get("output_dir"):
        print(f"\n--- Output Validation: {result['output_dir']} ---")
        ov = validate_output(result["output_dir"])
        for c in ov["checks"]:
            print(f"  {c}")
        if ov["errors"]:
            for e in ov["errors"]:
                print(f"  ERROR: {e}")
        result["output_validation"] = ov

    # Save results
    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nResults saved to: {args.output_json}")

    sys.exit(0 if result["status"] in ("completed", "dry_run_ok") else 1)


if __name__ == "__main__":
    main()
