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

CHOOSING THE RIGHT FILE (dt_027)
--------------------------------
PCR-GLOBWB writes ONE FILE PER (variable, aggregation) pair, and every one of
them holds a variable with the SAME name. Asking for `discharge` when the
output directory holds both

    discharge_annuaAvg_output.nc     (11 annual means)
    discharge_dailyTot_output.nc     (4018 daily values)

is ambiguous, and resolving it by alphabetical order silently returns the
11-value annual series to a caller that asked for a daily hydrograph. Pass
``--aggregation dailyTot`` (the dag declares discharge is emitted in
``discharge_dailyTot_output.nc``). When the variable resolves to more than one
file and no ``--aggregation`` is given, this tool now RAISES rather than
guessing.
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

AGGREGATIONS = ("dailyTot", "monthTot", "monthAvg", "monthEnd", "monthMax",
                "annuaTot", "annuaAvg", "annuaEnd", "annuaMax")


def resolve_output_file(netcdf_dir, variable, aggregation=None):
    """Return the single NetCDF holding `variable` at `aggregation`.

    PCR-GLOBWB names its outputs `{variable}_{aggregation}_output.nc`. When
    `aggregation` is given, that file is selected by NAME -- never by scanning
    variables in directory order. When it is omitted and the variable resolves
    to exactly one file, that file is used; when it resolves to several, this
    raises instead of silently taking the alphabetically-first one (which for
    `discharge` is `discharge_annuaAvg_output.nc`, an 11-value annual series).
    """
    if aggregation is not None and aggregation not in AGGREGATIONS:
        raise ValueError(f"Unknown aggregation '{aggregation}'. "
                         f"Valid: {list(AGGREGATIONS)}")

    if aggregation:
        fname = f"{variable}_{aggregation}_output.nc"
        path = os.path.join(netcdf_dir, fname)
        if not os.path.exists(path):
            present = sorted(f for f in os.listdir(netcdf_dir)
                             if f.startswith(f"{variable}_") and f.endswith(".nc"))
            raise FileNotFoundError(
                f"{fname} not found in {netcdf_dir}. "
                f"Present for '{variable}': {present or 'none'}. "
                f"Add '{variable}' to the matching out*NC line of "
                f"[reportingOptions] in the .ini."
            )
        logger.info(f"Selected {fname} by explicit --aggregation {aggregation}")
        return path

    # Match on the .ini reporting name in the FILE name first -- the variable
    # inside `actualET_monthTot_output.nc` is called `land_surface_evaporation`,
    # so scanning ds.variables alone would miss it.
    candidates = [f for f in sorted(os.listdir(netcdf_dir))
                  if f.startswith(f"{variable}_") and f.endswith("_output.nc")]

    if not candidates:
        for fname in sorted(os.listdir(netcdf_dir)):
            if not fname.endswith(".nc"):
                continue
            try:
                with nc.Dataset(os.path.join(netcdf_dir, fname), "r") as ds:
                    if variable in ds.variables:
                        candidates.append(fname)
            except Exception as e:
                logger.warning(f"Could not read {fname}: {e}")

    if not candidates:
        raise KeyError(
            f"Variable '{variable}' not found in any .nc under {netcdf_dir}. "
            f"Available: {sorted(list_output_variables(netcdf_dir))}"
        )
    if len(candidates) > 1:
        raise ValueError(
            f"dt_027: '{variable}' is present in {len(candidates)} output files "
            f"{candidates}. These are different temporal aggregations of the same "
            f"variable and are NOT interchangeable. Pass --aggregation "
            f"(one of {list(AGGREGATIONS)}) to choose explicitly."
        )
    logger.info(f"Selected {candidates[0]} (sole file containing '{variable}')")
    return os.path.join(netcdf_dir, candidates[0])


_COORD_NAMES = ("time", "lat", "lon", "latitude", "longitude")


def resolve_variable_in(ds, variable, path):
    """Name of `variable` INSIDE its output file.

    The .ini reporting name and the NetCDF variable name are not the same: the
    file `actualET_monthTot_output.nc` carries a variable called
    `land_surface_evaporation`. Prefer an exact match; otherwise, since
    PCR-GLOBWB writes exactly one data variable per output file, take that one.
    """
    if variable in ds.variables:
        return variable
    data_vars = [v for v in ds.variables if v not in _COORD_NAMES]
    if len(data_vars) == 1:
        logger.info(f"'{variable}' is stored as '{data_vars[0]}' in "
                    f"{os.path.basename(path)}")
        return data_vars[0]
    raise KeyError(
        f"'{variable}' not in {os.path.basename(path)} and its data variables "
        f"{data_vars} are ambiguous."
    )


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


def extract_point_timeseries(netcdf_dir, variable, lat, lon, output_csv,
                             aggregation=None):
    """Extract time series at a single point (lat/lon) to CSV.

    Args:
        netcdf_dir: Directory containing PCR-GLOBWB output NetCDF files
        variable: Variable name (e.g., 'discharge', 'totalRunoff')
        lat: Target latitude
        lon: Target longitude
        output_csv: Output CSV file path
        aggregation: Temporal aggregation, e.g. 'dailyTot' (see dt_027)
    """
    if nc is None:
        raise ImportError("netCDF4 required for extraction")

    target_file = resolve_output_file(netcdf_dir, variable, aggregation)

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
        data_var = ds.variables[resolve_variable_in(ds, variable, target_file)]
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
                          cell_area_nc=None, aggregation=None):
    """Extract basin-average time series using a landmask.

    Args:
        netcdf_dir: Directory containing output NetCDF files
        variable: Variable name
        landmask_nc: Landmask NetCDF (boolean/binary)
        output_csv: Output CSV file
        cell_area_nc: Cell area NetCDF (m2) for area-weighted average
        aggregation: Temporal aggregation, e.g. 'monthTot' (see dt_027)
    """
    if nc is None:
        raise ImportError("netCDF4 required")

    target_file = resolve_output_file(netcdf_dir, variable, aggregation)

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
        data_var = ds.variables[resolve_variable_in(ds, variable, target_file)]
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
            landmask_nc=None, cell_area_nc=None, mode="point", aggregation=None):
    """Main extraction dispatcher."""
    if mode == "point" and lat is not None and lon is not None:
        extract_point_timeseries(netcdf_dir, variable, lat, lon, output_csv,
                                 aggregation=aggregation)
    elif mode == "basin" and landmask_nc:
        extract_basin_average(netcdf_dir, variable, landmask_nc, output_csv,
                              cell_area_nc, aggregation=aggregation)
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
    parser.add_argument(
        "--aggregation", "-a", default=None, choices=list(AGGREGATIONS),
        help="Temporal aggregation of the output file to read, e.g. dailyTot. "
             "REQUIRED whenever the variable was reported at more than one "
             "aggregation (dt_027)."
    )
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
                landmask_nc=args.landmask, cell_area_nc=args.cell_area,
                mode="basin", aggregation=args.aggregation)
    elif args.lat is not None and args.lon is not None:
        process(args.netcdf_dir, args.variable, args.output,
                lat=args.lat, lon=args.lon, mode="point",
                aggregation=args.aggregation)
        validate_outputs(args.output)
    else:
        summarize_outputs(args.netcdf_dir)


if __name__ == "__main__":
    main()
