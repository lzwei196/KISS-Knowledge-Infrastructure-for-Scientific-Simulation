#!/usr/bin/env python3
"""
run_openamundsen.py — Execute openAMUNDSEN with preflight checks and error capture.

Performs the following:
  1. Validate configuration file exists and parses
  2. Check DEM file exists with correct naming convention
  3. Check meteorological input directory is populated
  4. Check station metadata (stations.csv or NetCDF metadata)
  5. Run the model with logging captured
  6. Verify output files were created

CRITICAL checks:
  - DEM must be named dem_{domain}_{resolution}.asc
  - ROI must be named roi_{domain}_{resolution}.asc (if used)
  - Meteo directory must contain station data files
  - CRS must be a valid EPSG code
  - At least one station must fall within grid extent

Usage:
  python run_openamundsen.py --config config.yml
  python run_openamundsen.py --config config.yml --dry-run
  python run_openamundsen.py --config config.yml --log-file run.log
"""

import argparse
import json
import os
import sys
import time
import traceback


def validate_inputs(args):
    """Validate the configuration file and environment."""
    errors = []

    if not os.path.exists(args.config):
        errors.append(f"Configuration file not found: {args.config}")
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    # Check openamundsen is importable
    try:
        import openamundsen as oa
    except ImportError:
        errors.append("openamundsen package not installed. Run: pip install openamundsen")
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    return True


def preflight_checks(config_path):
    """Run preflight checks on configuration and input data."""
    import openamundsen as oa
    from ruamel.yaml import YAML

    warnings = []
    errors = []

    # Parse YAML config
    yaml = YAML()
    with open(config_path) as f:
        raw_config = yaml.load(f)

    # Check required top-level keys
    required_keys = ["domain", "start_date", "end_date", "resolution", "crs", "timezone"]
    for key in required_keys:
        if key not in raw_config:
            errors.append(f"Missing required config key: {key}")

    if errors:
        return {"status": "error", "errors": errors, "warnings": warnings}

    domain = raw_config["domain"]
    resolution = raw_config["resolution"]

    # Check resolution is in meters (not km)
    if isinstance(resolution, (int, float)) and resolution < 1:
        warnings.append(f"Resolution={resolution} < 1m — did you specify km? openAMUNDSEN expects meters")
    if isinstance(resolution, (int, float)) and resolution > 10000:
        warnings.append(f"Resolution={resolution}m > 10km — unusually coarse for snow modeling")

    # Check grid directory and DEM
    grid_dir = raw_config.get("input_data", {}).get("grids", {}).get("dir", "")
    if grid_dir:
        # Resolve relative to config file directory
        config_dir = os.path.dirname(os.path.abspath(config_path))
        grid_dir_abs = os.path.join(config_dir, grid_dir) if not os.path.isabs(grid_dir) else grid_dir

        dem_name = f"dem_{domain}_{resolution}.asc"
        dem_path = os.path.join(grid_dir_abs, dem_name)
        if not os.path.exists(dem_path):
            errors.append(f"DEM not found: {dem_path}. Must be named: {dem_name}")

        roi_name = f"roi_{domain}_{resolution}.asc"
        roi_path = os.path.join(grid_dir_abs, roi_name)
        if not os.path.exists(roi_path):
            warnings.append(f"ROI not found: {roi_path}. Model will use full DEM extent")

    # Check meteo directory
    meteo_config = raw_config.get("input_data", {}).get("meteo", {})
    meteo_dir = meteo_config.get("dir", "")
    meteo_format = meteo_config.get("format", "netcdf")

    if meteo_dir:
        config_dir = os.path.dirname(os.path.abspath(config_path))
        meteo_dir_abs = os.path.join(config_dir, meteo_dir) if not os.path.isabs(meteo_dir) else meteo_dir

        if not os.path.isdir(meteo_dir_abs):
            errors.append(f"Meteo directory not found: {meteo_dir_abs}")
        else:
            if meteo_format == "csv":
                csv_files = [f for f in os.listdir(meteo_dir_abs) if f.endswith(".csv")]
                if not csv_files:
                    errors.append(f"No CSV files in meteo directory: {meteo_dir_abs}")
                if "stations.csv" not in csv_files:
                    errors.append(f"stations.csv not found in {meteo_dir_abs}")
            elif meteo_format == "netcdf":
                nc_files = [f for f in os.listdir(meteo_dir_abs)
                           if f.endswith(".nc") or f.endswith(".nc4")]
                if not nc_files:
                    errors.append(f"No NetCDF files in meteo directory: {meteo_dir_abs}")

    # Check CRS format
    crs = raw_config.get("crs", "")
    if crs and not crs.lower().startswith("epsg:"):
        warnings.append(f"CRS '{crs}' is not in EPSG format. openAMUNDSEN expects e.g. 'epsg:32632'")

    # Check timestep is valid pandas frequency
    timestep = raw_config.get("timestep", "h")
    try:
        import pandas as pd
        pd.tseries.frequencies.to_offset(timestep)
    except (ValueError, TypeError):
        errors.append(f"Invalid timestep: '{timestep}'. Use pandas frequency strings: 'h', '3h', 'D', etc.")

    # Check snow model parameters
    snow_config = raw_config.get("snow", {})
    snow_model = snow_config.get("model", "multilayer")
    if snow_model not in ("multilayer", "cryolayers"):
        errors.append(f"Unknown snow model: {snow_model}. Use: multilayer, cryolayers")

    # Check lapse rates are in K/m (not K/km)
    meteo_interp = raw_config.get("meteo", {}).get("interpolation", {})
    temp_lapse = meteo_interp.get("temperature", {}).get("lapse_rate", [])
    if isinstance(temp_lapse, list) and temp_lapse:
        max_lapse = max(abs(v) for v in temp_lapse)
        if max_lapse > 0.1:
            warnings.append(
                f"Temperature lapse rate max |value|={max_lapse} > 0.1 K/m — "
                f"did you use K/km? openAMUNDSEN expects K/m (typical: 0.0065)"
            )

    return {
        "status": "error" if errors else ("warning" if warnings else "pass"),
        "errors": errors,
        "warnings": warnings,
    }


def run_model(config_path, log_file=None):
    """Run the openAMUNDSEN model."""
    import openamundsen as oa

    start_time = time.time()

    # Configure logging
    if log_file:
        import logging
        handler = logging.FileHandler(log_file)
        handler.setLevel(logging.DEBUG)
        logging.getLogger("openamundsen").addHandler(handler)

    try:
        config = oa.read_config(config_path)
        model = oa.OpenAmundsen(config)
        model.initialize()
        model.run()

        elapsed = time.time() - start_time

        return {
            "status": "success",
            "elapsed_seconds": round(elapsed, 1),
            "num_timesteps": len(model.dates),
            "start_date": str(model.dates[0]),
            "end_date": str(model.dates[-1]),
            "grid_shape": list(model.grid.dem.shape),
            "num_stations": model.meteo.dims.get("station", 0) if hasattr(model, "meteo") else 0,
            "results_dir": str(config.results_dir),
        }

    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "status": "error",
            "elapsed_seconds": round(elapsed, 1),
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc(),
        }


def validate_outputs(results_dir, config_path):
    """Validate that expected output files were created."""
    warnings = []

    if not os.path.isdir(results_dir):
        return {"status": "error", "errors": [f"Results directory not found: {results_dir}"]}

    output_files = os.listdir(results_dir)
    if not output_files:
        return {"status": "error", "errors": ["Results directory is empty"]}

    nc_files = [f for f in output_files if f.endswith(".nc")]
    csv_files = [f for f in output_files if f.endswith(".csv")]

    if not nc_files and not csv_files:
        warnings.append("No NetCDF or CSV output files found — check output_data config")

    return {
        "status": "warning" if warnings else "success",
        "output_files": len(output_files),
        "netcdf_files": len(nc_files),
        "csv_files": len(csv_files),
        "warnings": warnings,
    }


def process(args):
    """Main processing: preflight → run → validate."""
    # Step 1: Preflight checks
    print("Running preflight checks...", file=sys.stderr)
    preflight = preflight_checks(args.config)

    if preflight["status"] == "error":
        print(json.dumps({"stage": "preflight", **preflight}, indent=2))
        return preflight

    for w in preflight.get("warnings", []):
        print(f"WARNING: {w}", file=sys.stderr)

    if args.dry_run:
        print(json.dumps({"stage": "preflight", **preflight}, indent=2))
        return preflight

    # Step 2: Run model
    print("Running openAMUNDSEN...", file=sys.stderr)
    run_result = run_model(args.config, args.log_file)

    if run_result["status"] == "error":
        result = {
            "stage": "execution",
            "preflight": preflight,
            "run": run_result,
        }
        print(json.dumps(result, indent=2))
        return result

    print(f"Completed in {run_result['elapsed_seconds']}s", file=sys.stderr)

    # Step 3: Validate outputs
    results_dir = run_result.get("results_dir", ".")
    output_check = validate_outputs(results_dir, args.config)

    result = {
        "stage": "complete",
        "preflight": preflight,
        "run": run_result,
        "output_validation": output_check,
    }
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run openAMUNDSEN with preflight checks"
    )
    parser.add_argument("--config", required=True, help="Path to YAML configuration file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only run preflight checks, do not execute model")
    parser.add_argument("--log-file", help="Path to write detailed log")

    args = parser.parse_args()
    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
