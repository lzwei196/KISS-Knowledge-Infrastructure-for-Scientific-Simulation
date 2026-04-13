#!/usr/bin/env python3
"""
parse_esmf_output.py — Extract fields from ESMF output NetCDF to CSV/analysis format.

Handles:
  - Multi-variable NetCDF output files
  - Time-series extraction at specific grid points
  - Spatial field extraction at specific timesteps
  - Basic statistics and data quality checks

Pipeline stage: s7_postprocess
Pattern: validate → process → validate

Usage:
    python parse_esmf_output.py \
        --input output.nc \
        --variables temperature,precipitation \
        --output results.csv \
        --extract-type timeseries \
        --lat 40.0 --lon 116.0
"""

import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def validate_input(input_path: str) -> dict:
    """Validate input NetCDF file exists and is readable.

    TRAP: ESMF output may use different fill value conventions.
    Check _FillValue attribute — common mismatch is NaN vs -9999.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    size = os.path.getsize(input_path)
    if size == 0:
        raise ValueError(f"Input file is empty: {input_path}")

    info = {"path": input_path, "size_bytes": size}

    # Try to read NetCDF metadata
    try:
        from netCDF4 import Dataset
        with Dataset(input_path, "r") as ds:
            info["variables"] = list(ds.variables.keys())
            info["dimensions"] = {k: len(v) for k, v in ds.dimensions.items()}
            info["global_attrs"] = {k: str(ds.getncattr(k)) for k in ds.ncattrs()}

            # Check for fill value issues
            for vname, var in ds.variables.items():
                if hasattr(var, "_FillValue"):
                    fv = var._FillValue
                    if np.isnan(fv) if isinstance(fv, float) else False:
                        logger.info("%s: _FillValue is NaN", vname)
                    elif fv == -9999 or fv == -9999.0:
                        logger.info("%s: _FillValue is -9999", vname)

            logger.info("NetCDF: %d variables, dimensions=%s",
                        len(info["variables"]), info["dimensions"])
    except ImportError:
        logger.warning("netCDF4 not available; limited validation")
    except Exception as e:
        logger.warning("Could not read NetCDF metadata: %s", e)

    return info


def extract_timeseries(input_path: str, variables: list,
                       lat: float, lon: float) -> dict:
    """Extract time series at nearest grid point.

    TRAP: Coordinate matching uses nearest-neighbor. If the grid is
    coarse, the nearest point may be far from the requested location.
    Always check the actual coordinates of the matched point.

    TRAP: If coordinates are stored as 0-360 longitude but you pass
    -180 to 180, the matching will fail silently with wrong data.
    """
    try:
        from netCDF4 import Dataset, num2date
    except ImportError:
        raise ImportError("netCDF4 required for extract_timeseries")

    result = {"metadata": {}, "timeseries": {}}

    with Dataset(input_path, "r") as ds:
        # Find coordinate variables
        lat_var, lon_var = _find_coord_vars(ds)
        if lat_var is None:
            raise ValueError("Cannot find latitude coordinate variable")

        lats = ds.variables[lat_var][:]
        lons = ds.variables[lon_var][:]

        # Handle longitude wrapping
        # TRAP: lon may be 0-360 or -180-180
        if lon < 0 and np.min(lons) >= 0:
            lon_query = lon + 360.0
            logger.info("Adjusted query longitude: %.2f → %.2f (0-360 convention)", lon, lon_query)
        elif lon > 180 and np.min(lons) < 0:
            lon_query = lon - 360.0
            logger.info("Adjusted query longitude: %.2f → %.2f (-180-180 convention)", lon, lon_query)
        else:
            lon_query = lon

        # Find nearest grid point
        if lats.ndim == 1:
            j_idx = np.argmin(np.abs(lats - lat))
            i_idx = np.argmin(np.abs(lons - lon_query))
            actual_lat = float(lats[j_idx])
            actual_lon = float(lons[i_idx])
        else:
            # 2D coordinate arrays
            dist = np.sqrt((lats - lat) ** 2 + (lons - lon_query) ** 2)
            j_idx, i_idx = np.unravel_index(np.argmin(dist), dist.shape)
            actual_lat = float(lats[j_idx, i_idx])
            actual_lon = float(lons[j_idx, i_idx])

        distance_deg = np.sqrt((actual_lat - lat) ** 2 + (actual_lon - lon_query) ** 2)
        if distance_deg > 1.0:
            logger.warning(
                "Nearest grid point (%.2f, %.2f) is %.2f° from requested (%.2f, %.2f)",
                actual_lat, actual_lon, distance_deg, lat, lon
            )

        result["metadata"]["requested"] = {"lat": lat, "lon": lon}
        result["metadata"]["matched"] = {"lat": actual_lat, "lon": actual_lon,
                                          "distance_deg": float(distance_deg)}

        # Extract time axis
        if "time" in ds.variables:
            time_var = ds.variables["time"]
            try:
                times = num2date(time_var[:], time_var.units,
                                 calendar=getattr(time_var, "calendar", "standard"))
                result["timeseries"]["time"] = [str(t) for t in times]
            except Exception:
                result["timeseries"]["time"] = time_var[:].tolist()
        else:
            logger.warning("No time variable found")

        # Extract requested variables
        for vname in variables:
            if vname not in ds.variables:
                logger.warning("Variable '%s' not found in dataset", vname)
                continue

            var = ds.variables[vname]
            ndim = var.ndim

            # Extract based on dimensionality
            if ndim == 1:  # time only
                data = var[:]
            elif ndim == 2:  # time × space or lat × lon
                dim_names = [d.name if hasattr(d, 'name') else str(d) for d in var.get_dims()] if hasattr(var, 'get_dims') else []
                if "time" in str(dim_names):
                    data = var[:, j_idx * 1 + i_idx] if lats.ndim == 1 else var[:, j_idx]
                else:
                    data = var[j_idx, i_idx]
            elif ndim == 3:  # time × lat × lon
                data = var[:, j_idx, i_idx]
            elif ndim == 4:  # time × level × lat × lon
                data = var[:, 0, j_idx, i_idx]  # surface level
                logger.info("4D variable %s: extracting surface level (index 0)", vname)
            else:
                logger.warning("Cannot extract %dD variable '%s'", ndim, vname)
                continue

            # Handle masked/fill values
            if hasattr(data, "filled"):
                data = data.filled(np.nan)
            data = np.asarray(data, dtype=np.float64)

            result["timeseries"][vname] = data.tolist()

            # Statistics
            valid = data[np.isfinite(data)]
            if len(valid) > 0:
                stats = {
                    "min": float(np.min(valid)),
                    "max": float(np.max(valid)),
                    "mean": float(np.mean(valid)),
                    "std": float(np.std(valid)),
                    "n_valid": int(len(valid)),
                    "n_total": int(len(data)),
                    "units": getattr(ds.variables[vname], "units", "unknown"),
                }
                result["metadata"][vname] = stats
                logger.info("%s: mean=%.4g, range=[%.4g, %.4g], units=%s",
                            vname, stats["mean"], stats["min"], stats["max"], stats["units"])

    return result


def _find_coord_vars(ds) -> tuple:
    """Find latitude and longitude variable names in a NetCDF dataset."""
    lat_names = ["lat", "latitude", "grid_center_lat", "XLAT", "nav_lat", "y"]
    lon_names = ["lon", "longitude", "grid_center_lon", "XLONG", "nav_lon", "x"]

    lat_var = None
    lon_var = None
    for name in lat_names:
        if name in ds.variables:
            lat_var = name
            break
    for name in lon_names:
        if name in ds.variables:
            lon_var = name
            break

    return lat_var, lon_var


def write_csv(result: dict, output_path: str):
    """Write extracted data to CSV format."""
    ts = result.get("timeseries", {})
    if not ts:
        logger.warning("No timeseries data to write")
        return

    keys = list(ts.keys())
    nrows = max(len(v) for v in ts.values() if isinstance(v, list)) if ts else 0

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        for i in range(nrows):
            row = []
            for k in keys:
                vals = ts[k]
                if isinstance(vals, list) and i < len(vals):
                    row.append(vals[i])
                else:
                    row.append("")
            writer.writerow(row)

    logger.info("Wrote CSV: %s (%d rows, %d columns)", output_path, nrows, len(keys))


def write_json(result: dict, output_path: str):
    """Write extracted data and metadata to JSON."""
    json_path = output_path.replace(".csv", ".json")
    with open(json_path, "w") as f:
        json.dump(result["metadata"], f, indent=2, default=str)
    logger.info("Wrote metadata JSON: %s", json_path)


def validate_output(output_path: str, expected_vars: list) -> dict:
    """Validate the output CSV file."""
    if not os.path.isfile(output_path):
        raise RuntimeError(f"Output file not created: {output_path}")

    size = os.path.getsize(output_path)
    if size == 0:
        raise RuntimeError(f"Output file is empty: {output_path}")

    # Check CSV header
    with open(output_path, "r") as f:
        header = f.readline().strip().split(",")

    missing = [v for v in expected_vars if v not in header]
    if missing:
        logger.warning("Variables missing from output: %s", missing)

    # Count rows
    with open(output_path, "r") as f:
        nrows = sum(1 for _ in f) - 1  # exclude header

    validation = {
        "file": output_path,
        "size_bytes": size,
        "columns": header,
        "nrows": nrows,
        "missing_vars": missing,
    }

    logger.info("Output validated: %s (%d rows, %d columns)", output_path, nrows, len(header))
    return validation


def main():
    parser = argparse.ArgumentParser(description="Parse ESMF output to CSV")
    parser.add_argument("--input", "-i", required=True, help="Input NetCDF file")
    parser.add_argument("--variables", "-v", required=True,
                        help="Comma-separated variable names")
    parser.add_argument("--output", "-o", required=True, help="Output CSV file")
    parser.add_argument("--extract-type", default="timeseries",
                        choices=["timeseries", "spatial"],
                        help="Extraction type")
    parser.add_argument("--lat", type=float, default=0.0, help="Latitude for timeseries")
    parser.add_argument("--lon", type=float, default=0.0, help="Longitude for timeseries")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    # Validate input
    info = validate_input(args.input)

    # Process
    variables = [v.strip() for v in args.variables.split(",")]

    if args.extract_type == "timeseries":
        result = extract_timeseries(args.input, variables, args.lat, args.lon)
    else:
        logger.error("Spatial extraction not yet implemented")
        sys.exit(1)

    # Write output
    write_csv(result, args.output)
    write_json(result, args.output)

    # Validate
    validate_output(args.output, variables)

    logger.info("Done. Results written to %s", args.output)


if __name__ == "__main__":
    main()
