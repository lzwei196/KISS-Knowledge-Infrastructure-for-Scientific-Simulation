#!/home/server/knowledge-dissection-toolkit/auto_dissect/_work/PyMT/venv/bin/python
"""Parse PyMT model output variables and export to CSV.

Purpose:
    Extract model output variables at the current time step or from
    a completed run. Handles unit conversion, grid reshaping, and
    multi-variable extraction. Supports both live model queries and
    NetCDF post-processing.

Usage:
    python parse_output.py --model Waves --vars "wave_height,wave_period" --output results.csv
    python parse_output.py --netcdf output.nc --vars "temperature" --output temp.csv

Critical Rules:
    - get_value() returns FLAT 1D arrays; use grid_shape() to reshape
    - Unit strings must be UDUNITS-compatible (gimli.units)
    - NetCDF files may use UGRID format with face/edge variables
    - Time is in model-specific units — always record time_units
"""

import argparse
import csv
import json
import os
import sys


def validate_inputs(args):
    """Validate input parameters."""
    errors = []

    if not args.model and not args.netcdf:
        errors.append("Either --model or --netcdf is required")

    if args.model and args.netcdf:
        errors.append("Use --model OR --netcdf, not both")

    if not args.vars:
        errors.append("--vars is required (comma-separated variable names)")

    if args.netcdf and not os.path.exists(args.netcdf):
        errors.append(f"NetCDF file not found: {args.netcdf}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def parse_from_model(model_name, var_names, target_units, params, duration, output_file):
    """Run model and extract variables at each time step.

    Parameters
    ----------
    model_name : str
        PyMT model name.
    var_names : list of str
        Variable names to extract.
    target_units : dict
        Optional unit conversions {var_name: target_unit_string}.
    params : dict
        Parameter overrides for setup.
    duration : float or None
        Run duration in model time units.
    output_file : str
        CSV output path.

    Returns
    -------
    dict
        Status and summary statistics.
    """
    import numpy as np
    from pymt import MODELS

    model_cls = getattr(MODELS, model_name, None)
    if model_cls is None:
        return {"status": "error", "errors": [f"Model '{model_name}' not found"]}

    model = model_cls()
    result = {"status": "running", "variables": {}}

    try:
        # Setup and initialize
        setup_kwargs = {}
        if params:
            setup_kwargs.update(params)
        cfg_file, cfg_dir = model.setup(**setup_kwargs)
        model.initialize(cfg_file, dir=cfg_dir)

        # Validate variable names
        all_vars = set(model.output_var_names) | set(model.input_var_names)
        valid_vars = [v for v in var_names if v in all_vars]
        invalid_vars = [v for v in var_names if v not in all_vars]
        if invalid_vars:
            result.setdefault("warnings", []).append(
                f"Unknown variables skipped: {invalid_vars}"
            )

        if not valid_vars:
            return {"status": "error", "errors": ["No valid variables found"]}

        # Collect metadata
        var_meta = {}
        for var in valid_vars:
            grid_id = model.var_grid(var)
            var_meta[var] = {
                "units": str(model.var_units(var)),
                "dtype": str(model.var_type(var)),
                "grid": grid_id,
                "grid_type": str(model.grid_type(grid_id)) if grid_id is not None else "scalar",
            }

        # Run and capture
        target_time = model.end_time if duration is None else model.start_time + duration
        rows = []
        time_units = str(model.time_units)

        while model.time < target_time:
            model.update()
            row = {"time": float(model.time), "time_units": time_units}

            for var in valid_vars:
                kwargs = {}
                if var in target_units:
                    kwargs["units"] = target_units[var]

                try:
                    val = model.get_value(var, **kwargs)
                    if val.size == 1:
                        row[var] = float(val.flat[0])
                    else:
                        # For multi-element arrays, store mean, min, max
                        row[f"{var}_mean"] = float(np.mean(val))
                        row[f"{var}_min"] = float(np.min(val))
                        row[f"{var}_max"] = float(np.max(val))
                except Exception as e:
                    row[var] = None
                    result.setdefault("warnings", []).append(
                        f"Failed to get {var} at t={model.time}: {e}"
                    )

            rows.append(row)

        # Write CSV
        if rows and output_file:
            fieldnames = list(rows[0].keys())
            with open(output_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            result["output_file"] = output_file

        # Summary
        result["status"] = "success"
        result["n_timesteps"] = len(rows)
        result["time_range"] = [rows[0]["time"], rows[-1]["time"]] if rows else []
        result["time_units"] = time_units
        result["variable_metadata"] = var_meta

    except Exception as e:
        result["status"] = "error"
        result["errors"] = [str(e)]
    finally:
        try:
            model.finalize()
        except Exception:
            pass

    return result


def parse_from_netcdf(nc_path, var_names, output_file):
    """Extract variables from a NetCDF output file.

    Parameters
    ----------
    nc_path : str
        Path to NetCDF file.
    var_names : list of str
        Variable names to extract.
    output_file : str
        CSV output path.

    Returns
    -------
    dict
        Status and variable metadata.
    """
    import numpy as np

    try:
        import xarray as xr
    except ImportError:
        return {"status": "error", "errors": ["xarray not installed"]}

    result = {"status": "running", "variables": {}}

    try:
        ds = xr.open_dataset(nc_path)

        available = list(ds.data_vars)
        valid_vars = [v for v in var_names if v in available]
        invalid = [v for v in var_names if v not in available]

        if invalid:
            result.setdefault("warnings", []).append(
                f"Variables not in NetCDF: {invalid}. Available: {available}"
            )

        if not valid_vars:
            return {
                "status": "error",
                "errors": [f"No requested variables found. Available: {available}"],
            }

        # Extract to DataFrame
        subset = ds[valid_vars]
        df = subset.to_dataframe().reset_index()

        # Write CSV
        if output_file:
            df.to_csv(output_file, index=False)
            result["output_file"] = output_file

        # Metadata
        for var in valid_vars:
            da = ds[var]
            result["variables"][var] = {
                "shape": list(da.shape),
                "dims": list(da.dims),
                "units": da.attrs.get("units", "unknown"),
                "min": float(np.nanmin(da.values)),
                "max": float(np.nanmax(da.values)),
                "mean": float(np.nanmean(da.values)),
            }

        result["status"] = "success"
        result["n_records"] = len(df)
        ds.close()

    except Exception as e:
        result["status"] = "error"
        result["errors"] = [str(e)]

    return result


def process(args):
    """Main processing logic."""
    validate_inputs(args)

    var_names = [v.strip() for v in args.vars.split(",")]

    target_units = {}
    if args.units:
        pairs = args.units.split(",")
        for pair in pairs:
            k, v = pair.split("=")
            target_units[k.strip()] = v.strip()

    if args.netcdf:
        return parse_from_netcdf(args.netcdf, var_names, args.output)

    params = {}
    if args.params:
        params = json.loads(args.params)

    return parse_from_model(
        args.model, var_names, target_units, params, args.duration, args.output
    )


def main():
    parser = argparse.ArgumentParser(
        description="Parse PyMT model output to CSV"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--model", "-m", type=str, help="PyMT model name")
    group.add_argument("--netcdf", "-n", type=str, help="NetCDF file path")

    parser.add_argument("--vars", "-v", required=True, help="Comma-separated variable names")
    parser.add_argument("--output", "-o", type=str, default="output.csv", help="Output CSV path")
    parser.add_argument("--units", type=str, help="Unit conversions: var1=unit1,var2=unit2")
    parser.add_argument("--params", type=str, help="JSON parameter overrides (model mode)")
    parser.add_argument("--duration", type=float, help="Run duration (model mode)")
    args = parser.parse_args()

    result = process(args)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
