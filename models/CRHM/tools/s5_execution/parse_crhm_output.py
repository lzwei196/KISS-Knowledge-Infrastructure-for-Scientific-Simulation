#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      parse_crhm_output
Stage:        s5_execution
Description:  Parse CRHM tab-delimited output to CSV and optionally NetCDF.

CRHM STD output format:
  Row 1: Variable names (tab-separated), prefixed with "date"
  Row 2: Units (tab-separated), prefixed with "()"
  Row 3+: Data (tab-separated), date in first column

Date formats depend on -t flag:
  YYYYMMDD: "2000 1 1 1 0" (space-separated YYYY M D H min)
  ISO:      "2000-01-01T01:00"
  MS:       floating point Excel date number

Variable naming: "module.variable(HRU_index)"
  e.g., "PBSM.SWE(1)", "Netroute.WS_outflow(1)"

CRITICAL: Row 2 is units, NOT data. Parsing must skip row 2.
If you don't skip units row, the first "data" row will be strings
like "(mm)", "(W/m^2)" -- pandas will silently convert the entire
column to object dtype, and all downstream math will fail.

Inputs:
  --output_path:   CRHM output file
  --output_format: csv, netcdf, or both
  --output_dir:    Directory for parsed files

Exit codes:
  0 -- success
  1 -- input error
  2 -- processing error
  3 -- output validation failed
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Parse CRHM output")
    parser.add_argument("--output_path", type=str, required=True, help="CRHM output file")
    parser.add_argument("--output_format", type=str, default="both",
                        choices=["csv", "netcdf", "both"], help="Output format")
    parser.add_argument("--output_dir", type=str, required=True, help="Output directory")
    return parser.parse_args()


def validate_inputs(output_path, output_dir):
    errors = []
    if not Path(output_path).exists():
        errors.append(f"CRHM output not found: {output_path}")
    if not output_dir:
        errors.append("Output directory not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def detect_date_format(first_data_line):
    """Detect CRHM output date format."""
    parts = first_data_line.strip().split("\t")
    if not parts:
        return "unknown"
    date_str = parts[0].strip()

    if "T" in date_str:
        return "ISO"
    elif "." in date_str and len(date_str) < 10:
        return "MS"
    else:
        return "YYYYMMDD"


def parse_datetime(date_str, fmt):
    """Parse CRHM date string to datetime."""
    from datetime import datetime

    date_str = date_str.strip()

    if fmt == "ISO":
        return datetime.fromisoformat(date_str)
    elif fmt == "MS":
        # Excel date number
        from datetime import timedelta
        days = float(date_str)
        return datetime(1899, 12, 30) + timedelta(days=days)
    elif fmt == "YYYYMMDD":
        # "YYYY M D H min" or "YYYY MM DD HH mm"
        parts = date_str.split()
        if len(parts) >= 4:
            return datetime(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
        elif len(parts) == 3:
            return datetime(int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            return datetime.strptime(date_str, "%Y%m%d")
    else:
        raise ValueError(f"Unknown date format: {fmt}")


def process(output_path, output_format, output_dir):
    """Parse CRHM output to structured format."""
    import numpy as np

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # errors="replace": CRHM's units row uses a Latin-1 degree sign for hru_t
    # ("(ºC)" = byte 0xBA), which crashes a strict-UTF-8 read.
    with open(output_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    if len(lines) < 3:
        logger.error("Output file has fewer than 3 lines")
        sys.exit(2)

    # Row 1: Variable names
    header_line = lines[0].strip()
    col_names = header_line.split("\t")

    # Row 2: Units -- SKIP THIS ROW (see docstring)
    units_line = lines[1].strip()
    units = units_line.split("\t")
    logger.info(f"Columns: {len(col_names)}")
    logger.info(f"Variables: {', '.join(col_names[:5])}...")

    # Detect date format from first data line
    date_fmt = detect_date_format(lines[2])
    logger.info(f"Date format: {date_fmt}")

    # Parse data rows
    datetimes = []
    data_rows = []
    parse_errors = 0

    for i, line in enumerate(lines[2:], start=3):
        stripped = line.strip()
        if not stripped:
            continue

        parts = stripped.split("\t")
        if len(parts) < 2:
            parse_errors += 1
            continue

        try:
            dt = parse_datetime(parts[0], date_fmt)
            values = []
            for v in parts[1:]:
                try:
                    values.append(float(v.strip()))
                except ValueError:
                    values.append(float("nan"))
            datetimes.append(dt)
            data_rows.append(values)
        except Exception as e:
            parse_errors += 1
            if parse_errors <= 3:
                logger.warning(f"Line {i}: parse error: {e}")

    if parse_errors > 3:
        logger.warning(f"... and {parse_errors - 3} more parse errors")

    if not data_rows:
        logger.error("No data rows parsed successfully")
        sys.exit(2)

    # Build arrays
    n_rows = len(data_rows)
    n_cols = len(col_names) - 1  # exclude date column
    data_array = np.full((n_rows, n_cols), np.nan)
    for i, row in enumerate(data_rows):
        for j, val in enumerate(row[:n_cols]):
            data_array[i, j] = val

    var_names = col_names[1:]  # exclude date column
    var_units = units[1:] if len(units) > 1 else ["" for _ in var_names]

    results = []

    # Write CSV
    if output_format in ("csv", "both"):
        csv_path = out_dir / "crhm_results.csv"
        with open(csv_path, "w") as f:
            f.write("datetime," + ",".join(var_names) + "\n")
            for i, dt in enumerate(datetimes):
                vals = ",".join(f"{data_array[i, j]:.6g}" for j in range(n_cols))
                f.write(f"{dt.isoformat()},{vals}\n")
        logger.info(f"CSV written: {csv_path} ({n_rows} rows, {n_cols} columns)")
        results.append(str(csv_path))

    # Write NetCDF
    if output_format in ("netcdf", "both"):
        try:
            import xarray as xr
            import pandas as pd

            time_index = pd.DatetimeIndex(datetimes)
            data_vars = {}
            for j, var_name in enumerate(var_names):
                clean_name = var_name.replace(".", "_").replace("(", "_").replace(")", "")
                unit = var_units[j] if j < len(var_units) else ""
                data_vars[clean_name] = xr.DataArray(
                    data=data_array[:, j],
                    dims=["time"],
                    attrs={"units": unit, "original_name": var_name},
                )

            ds = xr.Dataset(data_vars, coords={"time": time_index})
            ds.attrs["source"] = "CRHM output"
            ds.attrs["history"] = f"Parsed from {Path(output_path).name}"

            nc_path = out_dir / "crhm_results.nc"
            ds.to_netcdf(nc_path)
            logger.info(f"NetCDF written: {nc_path}")
            results.append(str(nc_path))
        except ImportError:
            logger.warning("xarray not available, skipping NetCDF output")

    return results


def validate_outputs(results):
    errors = []
    for path in results:
        if not Path(path).exists():
            errors.append(f"Output not created: {path}")
        elif Path(path).stat().st_size == 0:
            errors.append(f"Output file is empty: {path}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs(args.output_path, args.output_dir)

    try:
        results = process(args.output_path, args.output_format, args.output_dir)
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(results)

    print(json.dumps({"status": "success", "outputs": results}))
    sys.exit(0)
