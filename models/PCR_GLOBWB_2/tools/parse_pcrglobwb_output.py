#!/usr/bin/env python3
"""
PCR-GLOBWB 2 Output Parser
============================
Extracts model results from PCR-GLOBWB 2 NetCDF output files to CSV
time series for analysis, validation, and visualization.

Pipeline stage: s7 (Output Analysis)
Pattern: validate_inputs → process → validate_outputs

Output structure:
  outputDir/netcdf/
    discharge_dailyTot_output.nc
    totalRunoff_dailyTot_output.nc
    gwRecharge_dailyTot_output.nc
    actualET_monthTot_output.nc
    ...

Extraction targets:
  - Discharge at specified gauge locations (lat/lon or row/col)
  - Basin-average runoff, ET, storage
  - Time series in CSV format for validation
"""

import os
import sys
import argparse
import logging
from datetime import datetime

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(netcdf_dir, variable=None, lat=None, lon=None):
    """Validate input NetCDF directory and parameters."""
    errors = []

    if not os.path.exists(netcdf_dir):
        errors.append(f"NetCDF directory not found: {netcdf_dir}")
    else:
        nc_files = [f for f in os.listdir(netcdf_dir) if f.endswith(".nc")]
        if not nc_files:
            errors.append(f"No .nc files found in {netcdf_dir}")
        else:
            logger.info(f"Found {len(nc_files)} NetCDF file(s) in {netcdf_dir}")
            for f in sorted(nc_files)[:10]:
                logger.info(f"  {f}")

    if lat is not None and (lat < -90 or lat > 90):
        errors.append(f"Invalid latitude: {lat}")
    if lon is not None and (lon < -180 or lon > 360):
        errors.append(f"Invalid longitude: {lon}")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"Input validation failed: {len(errors)} error(s)")

    logger.info("Input validation passed.")
    return True


def validate_outputs(output_csv):
    """Validate output CSV file."""
    if not os.path.exists(output_csv):
        raise FileNotFoundError(f"Output CSV not created: {output_csv}")

    # Check file has content
    with open(output_csv, "r") as f:
        lines = f.readlines()

    if len(lines) < 2:
        raise ValueError(f"Output CSV has only {len(lines)} line(s) — no data")

    header = lines[0].strip()
    n_data = len(lines) - 1
    logger.info(f"Output CSV: {n_data} data rows, columns: {header}")

    # Quick stats on first numeric column
    try:
        values = []
        for line in lines[1:]:
            parts = line.strip().split(",")
            if len(parts) >= 2:
                try:
                    values.append(float(parts[1]))
                except ValueError:
                    pass
        if values:
            arr = np.array(values)
            logger.info(
                f"Value statistics: min={np.min(arr):.4f}, max={np.max(arr):.4f}, "
                f"mean={np.mean(arr):.4f}, std={np.std(arr):.4f}"
            )
            if np.all(arr == 0):
                logger.warning("All values are zero — check extraction location/variable")
    except Exception as e:
        logger.warning(f"Could not compute stats: {e}")

    logger.info("Output validation passed.")
    return True


# ---------------------------------------------------------------------------
# Extraction functions
# ---------------------------------------------------------------------------

def find_nearest_cell(lats, lons, target_lat, target_lon):
    """Find nearest grid cell to target coordinates."""
    lat_idx = np.argmin(np.abs(lats - target_lat))
    lon_idx = np.argmin(np.abs(lons - target_lon))
    actual_lat = float(lats[lat_idx])
    actual_lon = float(lons[lon_idx])
    logger.info(
        f"Target: ({target_lat}, {target_lon}) -> "
        f"Nearest cell: ({actual_lat}, {actual_lon}) "
        f"[idx: {lat_idx}, {lon_idx}]"
    )
    return lat_idx, lon_idx


def list_output_variables(netcdf_dir):
    """List all available output variables and their files."""
    if nc is None:
        raise ImportError("netCDF4 required")

    variables = {}
    nc_files = sorted([f for f in os.listdir(netcdf_dir) if f.endswith(".nc")])

    for fname in nc_files:
        filepath = os.path.join(netcdf_dir, fname)
        try:
            with nc.Dataset(filepath, "r") as ds:
                for vname in ds.variables:
                    if vname not in ("time", "lat", "lon", "latitude", "longitude"):
                        units = getattr(ds.variables[vname], "units", "unknown")
                        shape = ds.variables[vname].shape
                        variables[vname] = {
                            "file": fname,
                            "units": units,
                            "shape": shape,
                        }
        except Exception as e:
            logger.warning(f"Could not read {fname}: {e}")

    return variables


def extract_point_timeseries(netcdf_dir, variable, lat, lon, output_csv):
    """Extract time series at a single point (lat/lon) to CSV.

    Args:
        netcdf_dir: Directory containing PCR-GLOBWB output NetCDF files
        variable: Variable name (e.g., 'discharge', 'totalRunoff')
        lat: Target latitude
        lon: Target longitude
        output_csv: Output CSV file path
    """
    if nc is None:
        raise ImportError("netCDF4 required for extraction")

    # Find the file containing this variable
    nc_files = sorted([f for f in os.listdir(netcdf_dir) if f.endswith(".nc")])
    target_file = None

    for fname in nc_files:
        filepath = os.path.join(netcdf_dir, fname)
        try:
            with nc.Dataset(filepath, "r") as ds:
                if variable in ds.variables:
                    target_file = filepath
                    break
        except Exception:
            continue

    if target_file is None:
        # Try pattern matching
        for fname in nc_files:
            if variable.lower() in fname.lower():
                target_file = os.path.join(netcdf_dir, fname)
                break

    if target_file is None:
        available = list_output_variables(netcdf_dir)
        raise KeyError(
            f"Variable '{variable}' not found. Available: {list(available.keys())}"
        )

    logger.info(f"Extracting '{variable}' from {target_file}")

    with nc.Dataset(target_file, "r") as ds:
        # Get coordinate arrays
        lat_var = ds.variables.get("lat", ds.variables.get("latitude"))
        lon_var = ds.variables.get("lon", ds.variables.get("longitude"))

        if lat_var is None or lon_var is None:
            raise ValueError("Cannot find lat/lon coordinates in output file")

        lats = lat_var[:]
        lons = lon_var[:]

        # Find nearest cell
        lat_idx, lon_idx = find_nearest_cell(lats, lons, lat, lon)

        # Get time
        time_var = ds.variables["time"]
        time_units = time_var.units
        time_calendar = getattr(time_var, "calendar", "standard")
        dates = nc.num2date(time_var[:], time_units, time_calendar)

        # Extract data
        data_var = ds.variables[variable]
        units = getattr(data_var, "units", "unknown")

        if len(data_var.shape) == 3:  # time, lat, lon
            values = data_var[:, lat_idx, lon_idx]
        elif len(data_var.shape) == 2:  # time, cells (1D grid)
            # Find cell index
            values = data_var[:, lat_idx * len(lons) + lon_idx]
        else:
            raise ValueError(f"Unexpected data shape: {data_var.shape}")

    # Write CSV
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
    with open(output_csv, "w") as f:
        f.write(f"date,{variable}\n")
        for i, date in enumerate(dates):
            date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
            val = float(values[i]) if not np.isnan(values[i]) else ""
            f.write(f"{date_str},{val}\n")

    logger.info(f"Extracted {len(dates)} timesteps to {output_csv}")
    logger.info(f"  Variable: {variable} ({units})")
    logger.info(f"  Location: ({float(lats[lat_idx]):.4f}, {float(lons[lon_idx]):.4f})")

    return output_csv


def extract_basin_average(netcdf_dir, variable, landmask_nc, output_csv,
                          cell_area_nc=None):
    """Extract basin-average time series using a landmask.

    Args:
        netcdf_dir: Directory containing output NetCDF files
        variable: Variable name
        landmask_nc: Landmask NetCDF (boolean/binary)
        output_csv: Output CSV file
        cell_area_nc: Cell area NetCDF (m2) for area-weighted average
    """
    if nc is None:
        raise ImportError("netCDF4 required")

    # Find variable file
    nc_files = sorted([f for f in os.listdir(netcdf_dir) if f.endswith(".nc")])
    target_file = None
    for fname in nc_files:
        filepath = os.path.join(netcdf_dir, fname)
        try:
            with nc.Dataset(filepath, "r") as ds:
                if variable in ds.variables:
                    target_file = filepath
                    break
        except Exception:
            continue

    if target_file is None:
        for fname in nc_files:
            if variable.lower() in fname.lower():
                target_file = os.path.join(netcdf_dir, fname)
                break

    if target_file is None:
        raise KeyError(f"Variable '{variable}' not found in {netcdf_dir}")

    # Read landmask
    with nc.Dataset(landmask_nc, "r") as ds:
        mask_vars = [v for v in ds.variables if v not in ("lat", "lon", "latitude", "longitude", "time")]
        mask = ds.variables[mask_vars[0]][:]
        mask = np.where(mask > 0, 1.0, np.nan)

    # Read cell area if provided
    weights = mask.copy()
    if cell_area_nc and os.path.exists(cell_area_nc):
        with nc.Dataset(cell_area_nc, "r") as ds:
            area_vars = [v for v in ds.variables if v not in ("lat", "lon", "latitude", "longitude", "time")]
            area = ds.variables[area_vars[0]][:]
            weights = mask * area

    # Extract and average
    with nc.Dataset(target_file, "r") as ds:
        time_var = ds.variables["time"]
        dates = nc.num2date(time_var[:], time_var.units, getattr(time_var, "calendar", "standard"))
        data_var = ds.variables[variable]
        units = getattr(data_var, "units", "unknown")

        os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
        with open(output_csv, "w") as f:
            f.write(f"date,{variable}_basin_avg\n")
            for t in range(len(dates)):
                data_t = data_var[t, :, :] * mask
                if cell_area_nc:
                    avg = float(np.nansum(data_t * weights) / np.nansum(weights))
                else:
                    avg = float(np.nanmean(data_t))
                date_str = dates[t].strftime("%Y-%m-%d") if hasattr(dates[t], "strftime") else str(dates[t])
                f.write(f"{date_str},{avg}\n")

    logger.info(f"Basin average of '{variable}' written to {output_csv}")


def summarize_outputs(netcdf_dir):
    """Print a summary of all output variables."""
    variables = list_output_variables(netcdf_dir)

    print(f"\n{'='*70}")
    print(f"PCR-GLOBWB 2 Output Summary: {netcdf_dir}")
    print(f"{'='*70}")
    print(f"{'Variable':<40} {'Units':<15} {'Shape'}")
    print(f"{'-'*70}")
    for vname, info in sorted(variables.items()):
        print(f"{vname:<40} {info['units']:<15} {info['shape']}")
    print(f"{'='*70}")
    print(f"Total: {len(variables)} variables in {len(set(v['file'] for v in variables.values()))} files")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(netcdf_dir, variable, output_csv, lat=None, lon=None,
            landmask_nc=None, cell_area_nc=None, mode="point"):
    """Main extraction dispatcher."""
    if mode == "point" and lat is not None and lon is not None:
        extract_point_timeseries(netcdf_dir, variable, lat, lon, output_csv)
    elif mode == "basin" and landmask_nc:
        extract_basin_average(netcdf_dir, variable, landmask_nc, output_csv, cell_area_nc)
    elif mode == "summary":
        summarize_outputs(netcdf_dir)
    else:
        raise ValueError(
            "Specify either --lat/--lon for point extraction, "
            "--landmask for basin average, or --summary"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Parse PCR-GLOBWB 2 output NetCDF to CSV"
    )
    parser.add_argument("netcdf_dir", help="Path to output netcdf/ directory")
    parser.add_argument("--variable", "-v", default="discharge", help="Variable to extract")
    parser.add_argument("--lat", type=float, default=None, help="Target latitude")
    parser.add_argument("--lon", type=float, default=None, help="Target longitude")
    parser.add_argument("--output", "-o", default="output.csv", help="Output CSV file")
    parser.add_argument("--landmask", default=None, help="Landmask NetCDF for basin average")
    parser.add_argument("--cell-area", default=None, help="Cell area NetCDF (m2)")
    parser.add_argument("--summary", action="store_true", help="Print output summary only")

    args = parser.parse_args()

    # Validate
    validate_inputs(args.netcdf_dir, args.variable, args.lat, args.lon)

    if args.summary:
        process(args.netcdf_dir, args.variable, args.output, mode="summary")
    elif args.landmask:
        process(args.netcdf_dir, args.variable, args.output,
                landmask_nc=args.landmask, cell_area_nc=args.cell_area, mode="basin")
    elif args.lat is not None and args.lon is not None:
        process(args.netcdf_dir, args.variable, args.output,
                lat=args.lat, lon=args.lon, mode="point")
        validate_outputs(args.output)
    else:
        summarize_outputs(args.netcdf_dir)


if __name__ == "__main__":
    main()
