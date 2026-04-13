#!/usr/bin/env python3
"""BMI Output Extractor.

Extracts model state variables from a BMI-wrapped model instance using
getter functions and writes results to CSV or NetCDF format.

Pipeline stage: S4 — Output Extraction
Pattern: validate_inputs → extract_data → validate_outputs
"""

import csv
import logging
import os
import sys
from typing import Any

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs(
    bmi_instance: Any,
    var_names: list[str] | None = None,
    output_format: str = "csv",
    output_path: str = "bmi_extract.csv",
) -> dict:
    """Validate extraction inputs.

    Parameters
    ----------
    bmi_instance : object
        An initialized BMI model instance (initialize already called).
    var_names : list of str, optional
        Variable names to extract. If None, all output variables are used.
    output_format : str
        Output format: 'csv' or 'netcdf'.
    output_path : str
        Path for the output file.

    Returns
    -------
    dict
        Validated extraction parameters.

    Raises
    ------
    ValueError
        If output format is unsupported or no variables found.
    """
    if output_format not in ("csv", "netcdf"):
        raise ValueError(
            f"Unsupported output format: '{output_format}'. Use 'csv' or 'netcdf'."
        )

    # Discover available output variables
    if var_names is None:
        if hasattr(bmi_instance, "get_output_var_names"):
            var_names = list(bmi_instance.get_output_var_names())
        else:
            raise ValueError(
                "No variable names provided and model has no "
                "get_output_var_names method"
            )

    if not var_names:
        raise ValueError("No variables to extract")

    # Query metadata for each variable
    var_meta = {}
    for name in var_names:
        meta = {"name": name}
        try:
            meta["units"] = bmi_instance.get_var_units(name)
        except Exception:
            meta["units"] = "unknown"
        try:
            meta["type"] = bmi_instance.get_var_type(name)
        except Exception:
            meta["type"] = "float64"
        try:
            meta["nbytes"] = bmi_instance.get_var_nbytes(name)
            meta["itemsize"] = bmi_instance.get_var_itemsize(name)
            meta["n_items"] = meta["nbytes"] // meta["itemsize"]
        except Exception:
            meta["n_items"] = 1
        try:
            grid_id = bmi_instance.get_var_grid(name)
            meta["grid_id"] = grid_id
            meta["grid_type"] = bmi_instance.get_grid_type(grid_id)
            meta["grid_size"] = bmi_instance.get_grid_size(grid_id)
            meta["grid_rank"] = bmi_instance.get_grid_rank(grid_id)
        except Exception:
            meta["grid_id"] = 0
            meta["grid_type"] = "scalar"
            meta["grid_size"] = 1
            meta["grid_rank"] = 0

        var_meta[name] = meta
        logger.info(
            f"Variable '{name}': units={meta['units']}, "
            f"grid={meta.get('grid_type', '?')}, "
            f"n_items={meta['n_items']}"
        )

    return {
        "bmi": bmi_instance,
        "var_names": var_names,
        "var_meta": var_meta,
        "output_format": output_format,
        "output_path": output_path,
    }


def extract_data(params: dict) -> dict:
    """Extract current state of all specified variables.

    Parameters
    ----------
    params : dict
        Validated parameters from validate_inputs.

    Returns
    -------
    dict
        Extracted data with variable names as keys.
    """
    bmi = params["bmi"]
    extracted = {}

    current_time = bmi.get_current_time()
    time_units = (
        bmi.get_time_units() if hasattr(bmi, "get_time_units") else "unknown"
    )
    extracted["_time"] = current_time
    extracted["_time_units"] = time_units

    for name in params["var_names"]:
        meta = params["var_meta"][name]
        n_items = meta["n_items"]

        try:
            dest = np.empty(n_items, dtype=float)
            bmi.get_value(name, dest)
            extracted[name] = {
                "values": dest.copy(),
                "units": meta["units"],
                "grid_type": meta.get("grid_type", "unknown"),
                "shape": None,
            }

            # Attempt to get grid shape for reshaping
            if meta.get("grid_rank", 0) >= 2:
                try:
                    shape = np.empty(meta["grid_rank"], dtype=int)
                    bmi.get_grid_shape(meta["grid_id"], shape)
                    extracted[name]["shape"] = tuple(shape)
                except Exception:
                    pass

            logger.info(
                f"Extracted '{name}': {n_items} values, "
                f"range=[{dest.min():.4g}, {dest.max():.4g}]"
            )

        except Exception as e:
            logger.warning(f"Failed to extract '{name}': {e}")
            extracted[name] = {
                "values": None,
                "units": meta["units"],
                "error": str(e),
            }

    return extracted


def write_csv(extracted: dict, output_path: str, var_meta: dict) -> str:
    """Write extracted data to CSV file.

    For scalar variables, writes a single column.
    For grid variables, writes summary statistics.

    Parameters
    ----------
    extracted : dict
        Data from extract_data.
    output_path : str
        CSV file path.
    var_meta : dict
        Variable metadata.

    Returns
    -------
    str
        Absolute path to written file.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    time_val = extracted.get("_time", 0.0)
    time_units = extracted.get("_time_units", "unknown")

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header comment
        f.write(f"# BMI Output Extraction at t={time_val} {time_units}\n")

        # For each variable, write a section
        for var_name, data in extracted.items():
            if var_name.startswith("_"):
                continue
            if data.get("values") is None:
                continue

            values = data["values"]
            units = data["units"]
            shape = data.get("shape")

            f.write(f"\n# Variable: {var_name} [{units}]\n")

            if len(values) == 1:
                writer.writerow([var_name, values[0], units])
            else:
                # Summary statistics
                writer.writerow(
                    ["statistic", "value"]
                )
                writer.writerow(["variable", var_name])
                writer.writerow(["units", units])
                writer.writerow(["count", len(values)])
                writer.writerow(["mean", f"{np.mean(values):.6g}"])
                writer.writerow(["std", f"{np.std(values):.6g}"])
                writer.writerow(["min", f"{np.min(values):.6g}"])
                writer.writerow(["max", f"{np.max(values):.6g}"])
                if shape:
                    writer.writerow(["shape", str(shape)])

                # Full data (flattened)
                f.write(f"# Full data ({len(values)} values, flattened):\n")
                writer.writerow(["index", var_name])
                for i, v in enumerate(values):
                    writer.writerow([i, f"{v:.6g}"])

    logger.info(f"CSV written to {output_path}")
    return os.path.abspath(output_path)


def write_netcdf(extracted: dict, output_path: str, var_meta: dict) -> str:
    """Write extracted data to NetCDF file.

    Parameters
    ----------
    extracted : dict
        Data from extract_data.
    output_path : str
        NetCDF file path.
    var_meta : dict
        Variable metadata.

    Returns
    -------
    str
        Absolute path to written file.
    """
    try:
        from netCDF4 import Dataset
    except ImportError:
        logger.error("netCDF4 not installed. Install with: pip install netCDF4")
        raise

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with Dataset(output_path, "w", format="NETCDF4") as ds:
        ds.title = "BMI Output Extraction"
        ds.time_value = float(extracted.get("_time", 0.0))
        ds.time_units = extracted.get("_time_units", "unknown")

        for var_name, data in extracted.items():
            if var_name.startswith("_"):
                continue
            if data.get("values") is None:
                continue

            values = data["values"]
            meta = var_meta.get(var_name, {})
            shape = data.get("shape")

            if shape:
                # Create dimensions
                dim_names = []
                for i, s in enumerate(shape):
                    dim_name = f"{var_name}_dim{i}"
                    if dim_name not in ds.dimensions:
                        ds.createDimension(dim_name, s)
                    dim_names.append(dim_name)

                var = ds.createVariable(
                    var_name, "f8", tuple(dim_names), zlib=True
                )
                var[:] = values.reshape(shape)
            else:
                dim_name = f"{var_name}_n"
                ds.createDimension(dim_name, len(values))
                var = ds.createVariable(
                    var_name, "f8", (dim_name,), zlib=True
                )
                var[:] = values

            var.units = data.get("units", "unknown")

    logger.info(f"NetCDF written to {output_path}")
    return os.path.abspath(output_path)


def validate_outputs(output_path: str, expected_vars: list[str]) -> bool:
    """Validate the output file exists and contains expected data.

    Parameters
    ----------
    output_path : str
        Path to the output file.
    expected_vars : list of str
        Variable names that should be in the output.

    Returns
    -------
    bool
        True if validation passes.
    """
    if not os.path.isfile(output_path):
        logger.error(f"Output file not found: {output_path}")
        return False

    file_size = os.path.getsize(output_path)
    if file_size == 0:
        logger.error("Output file is empty")
        return False

    logger.info(
        f"Output validation passed: {output_path} ({file_size} bytes)"
    )
    return True


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract BMI model output variables"
    )
    parser.add_argument(
        "module", help="Python module containing the BMI class"
    )
    parser.add_argument(
        "class_name", help="Name of the BMI class"
    )
    parser.add_argument(
        "config_file", help="Path to model config file"
    )
    parser.add_argument(
        "--vars",
        nargs="+",
        default=None,
        help="Variable names to extract (default: all output vars)",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "netcdf"],
        default="csv",
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="bmi_extract.csv",
        help="Output file path",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=0,
        help="Number of update steps before extraction (default: 0 = extract initial state)",
    )

    args = parser.parse_args()

    # Import and initialize model
    import importlib

    try:
        mod = importlib.import_module(args.module)
        bmi_class = getattr(mod, args.class_name)
        bmi_instance = bmi_class()
        bmi_instance.initialize(args.config_file)
    except Exception as e:
        logger.error(f"Cannot initialize BMI model: {e}")
        sys.exit(1)

    # Run update steps
    for i in range(args.steps):
        bmi_instance.update()

    # validate → extract → write → validate
    params = validate_inputs(
        bmi_instance, args.vars, args.format, args.output
    )
    extracted = extract_data(params)

    if args.format == "csv":
        output_file = write_csv(extracted, args.output, params["var_meta"])
    else:
        output_file = write_netcdf(extracted, args.output, params["var_meta"])

    validate_outputs(output_file, params["var_names"])

    # Cleanup
    bmi_instance.finalize()


if __name__ == "__main__":
    main()
