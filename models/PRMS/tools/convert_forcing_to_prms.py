#!/usr/bin/env python3
"""
convert_forcing_to_prms.py — Convert global gridded forcing to PRMS data/CBH files.

Handles two modes:
  1. Station-based: Creates a single PRMS data file with station observations
  2. Climate-by-HRU (CBH): Creates per-HRU files (tmax.cbh, tmin.cbh, precip.cbh)

Supports input from: CMFD, ERA5, MSWX, CSV station data, NetCDF grids.

CRITICAL UNIT CONVERSIONS:
  - Temperature: Celsius -> Fahrenheit  (F = C * 9/5 + 32)
  - Precipitation: mm/day -> inches/day (in = mm / 25.4)
  - Solar radiation: W/m2 -> Langleys/day (Ly = W/m2 * 0.0864)
  - Wind speed: m/s -> m/s (no conversion)
  - Streamflow: m3/s -> cfs (cfs = cms / 0.028317)

Usage:
  python convert_forcing_to_prms.py \\
    --input_dir /path/to/forcing \\
    --output_dir /path/to/prms_input \\
    --mode cbh \\
    --start_date 1980-10-01 \\
    --end_date 2010-09-30 \\
    --nhru 10 \\
    --input_format cmfd
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CELSIUS_TO_FAHRENHEIT_SCALE = 9.0 / 5.0
CELSIUS_TO_FAHRENHEIT_OFFSET = 32.0
MM_TO_INCHES = 1.0 / 25.4  # 0.03937
WM2_TO_LANGLEYS = 0.0864  # W/m2 * 86400 s/day / 1e6 J/MJ * 1e4 cm2/m2 / 4.184 J/cal
CMS_TO_CFS = 1.0 / 0.028316847
M_TO_FEET = 1.0 / 0.3048


def validate_inputs(input_dir: str, input_format: str, nhru: int,
                    start_date: str, end_date: str) -> dict:
    """Validate all inputs before processing.

    Returns:
        dict with validated parameters and detected issues.

    Raises:
        ValueError: If critical validation fails.
    """
    issues = []
    input_path = Path(input_dir)

    if not input_path.exists():
        raise ValueError(f"Input directory does not exist: {input_dir}")

    if input_format not in ("cmfd", "era5", "mswx", "csv", "netcdf"):
        raise ValueError(f"Unknown input format: {input_format}. "
                         f"Supported: cmfd, era5, mswx, csv, netcdf")

    if nhru < 1:
        raise ValueError(f"nhru must be >= 1, got {nhru}")

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"Date format error (use YYYY-MM-DD): {e}")

    if end_dt <= start_dt:
        raise ValueError(f"end_date ({end_date}) must be after start_date ({start_date})")

    ndays = (end_dt - start_dt).days + 1
    print(f"[validate] Period: {start_date} to {end_date} ({ndays} days)")
    print(f"[validate] Format: {input_format}, nhru: {nhru}")

    return {
        "input_path": input_path,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "ndays": ndays,
        "issues": issues,
    }


def celsius_to_fahrenheit(temp_c: np.ndarray) -> np.ndarray:
    """Convert temperature from Celsius to Fahrenheit.

    TRAP: PRMS internally expects ALL temperatures in Fahrenheit.
    Feeding Celsius causes snow partitioning to fail silently.
    tmax_allsnow defaults to 32F; 0C in Celsius = 32F, but if you
    feed 0 without converting, PRMS interprets it as 0F = -17.8C.
    """
    temp_f = temp_c * CELSIUS_TO_FAHRENHEIT_SCALE + CELSIUS_TO_FAHRENHEIT_OFFSET
    return temp_f


def mm_to_inches(precip_mm: np.ndarray) -> np.ndarray:
    """Convert precipitation from mm/day to inches/day.

    TRAP: PRMS expects inches. 1 mm = 0.03937 inches.
    Feeding mm directly gives 25.4x too much precipitation.
    """
    precip_in = precip_mm * MM_TO_INCHES
    # Ensure non-negative
    precip_in = np.maximum(precip_in, 0.0)
    return precip_in


def cms_to_cfs(flow_cms: np.ndarray) -> np.ndarray:
    """Convert streamflow from m3/s to cfs.

    TRAP: PRMS default runoff_units=0 means cfs.
    If you set runoff_units=1, PRMS expects cms.
    """
    return flow_cms * CMS_TO_CFS


def wm2_to_langleys(swrad_wm2: np.ndarray) -> np.ndarray:
    """Convert solar radiation from W/m2 to Langleys/day.

    1 Langley = 1 cal/cm2. Daily total: W/m2 * 86400 / (41840) = Ly/day
    Simplified: W/m2 * 0.0864 = Ly/day (approximately).
    """
    return swrad_wm2 * WM2_TO_LANGLEYS


def read_csv_forcing(input_path: Path, start_dt: datetime,
                     end_dt: datetime) -> pd.DataFrame:
    """Read forcing data from CSV files.

    Expected CSV format:
        date,tmax,tmin,precip,runoff[,solrad,humidity,wind_speed]
        Units: Celsius, Celsius, mm/day, m3/s[, W/m2, %, m/s]
    """
    csv_files = sorted(input_path.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {input_path}")

    # Read first CSV file
    df = pd.read_csv(csv_files[0], parse_dates=["date"])
    df = df.set_index("date")

    # Filter to requested period
    mask = (df.index >= start_dt) & (df.index <= end_dt)
    df = df.loc[mask]

    if len(df) == 0:
        raise ValueError(f"No data found in period {start_dt} to {end_dt}")

    return df


def read_netcdf_forcing(input_path: Path, start_dt: datetime,
                        end_dt: datetime, nhru: int) -> dict:
    """Read forcing data from NetCDF files (CMFD/ERA5/MSWX format).

    Returns dict of {variable_name: np.ndarray of shape (ndays, nhru)}.
    """
    try:
        import xarray as xr
    except ImportError:
        raise ImportError("xarray required for NetCDF input: pip install xarray")

    nc_files = sorted(input_path.glob("*.nc")) + sorted(input_path.glob("*.nc4"))
    if not nc_files:
        raise FileNotFoundError(f"No NetCDF files found in {input_path}")

    data = {}
    for ncf in nc_files:
        ds = xr.open_dataset(ncf)
        # Detect time variable
        time_var = None
        for tname in ("time", "Time", "date", "DATE"):
            if tname in ds.dims or tname in ds.coords:
                time_var = tname
                break

        if time_var:
            ds = ds.sel({time_var: slice(str(start_dt.date()), str(end_dt.date()))})

        for var in ds.data_vars:
            arr = ds[var].values
            if arr.ndim == 1:
                # Single station/point — broadcast to nhru
                arr = np.tile(arr.reshape(-1, 1), (1, nhru))
            elif arr.ndim >= 2:
                # Take spatial mean or first nhru points
                if arr.shape[-1] >= nhru:
                    arr = arr[..., :nhru]
                else:
                    arr = np.tile(arr, (1, nhru // arr.shape[-1] + 1))[:, :nhru]
            data[var.lower()] = arr
        ds.close()

    return data


def process_forcing(input_path: Path, input_format: str, start_dt: datetime,
                    end_dt: datetime, nhru: int) -> dict:
    """Process forcing data: read + unit conversions.

    Returns dict with converted arrays ready for PRMS.
    """
    ndays = (end_dt - start_dt).days + 1

    if input_format == "csv":
        df = read_csv_forcing(input_path, start_dt, end_dt)
        result = {}

        if "tmax" in df.columns:
            tmax_c = df["tmax"].values
            result["tmax"] = celsius_to_fahrenheit(tmax_c).reshape(-1, 1)
            result["tmax"] = np.tile(result["tmax"], (1, nhru))
            print(f"[convert] tmax: {tmax_c.min():.1f}-{tmax_c.max():.1f} C -> "
                  f"{result['tmax'][:, 0].min():.1f}-{result['tmax'][:, 0].max():.1f} F")

        if "tmin" in df.columns:
            tmin_c = df["tmin"].values
            result["tmin"] = celsius_to_fahrenheit(tmin_c).reshape(-1, 1)
            result["tmin"] = np.tile(result["tmin"], (1, nhru))
            print(f"[convert] tmin: {tmin_c.min():.1f}-{tmin_c.max():.1f} C -> "
                  f"{result['tmin'][:, 0].min():.1f}-{result['tmin'][:, 0].max():.1f} F")

        if "precip" in df.columns:
            precip_mm = df["precip"].values
            result["precip"] = mm_to_inches(precip_mm).reshape(-1, 1)
            result["precip"] = np.tile(result["precip"], (1, nhru))
            print(f"[convert] precip: {precip_mm.mean():.2f} mm/d -> "
                  f"{result['precip'][:, 0].mean():.4f} in/d")

        if "runoff" in df.columns:
            runoff_cms = df["runoff"].values
            result["runoff"] = cms_to_cfs(runoff_cms).reshape(-1, 1)

        if "solrad" in df.columns:
            solrad_wm2 = df["solrad"].values
            result["solrad"] = wm2_to_langleys(solrad_wm2).reshape(-1, 1)

        result["dates"] = pd.date_range(start_dt, end_dt, freq="D")
        return result

    elif input_format in ("cmfd", "era5", "mswx", "netcdf"):
        raw = read_netcdf_forcing(input_path, start_dt, end_dt, nhru)
        result = {}

        # Detect and convert temperature variables
        for tvar in ("tmax", "t2m_max", "tasmax", "tmp_max"):
            if tvar in raw:
                raw_vals = raw[tvar]
                # Detect if already Fahrenheit (values > 100 likely F)
                if np.nanmean(raw_vals) < 60:  # likely Celsius
                    result["tmax"] = celsius_to_fahrenheit(raw_vals)
                    print(f"[convert] tmax ({tvar}): C -> F")
                else:
                    result["tmax"] = raw_vals
                break

        for tvar in ("tmin", "t2m_min", "tasmin", "tmp_min"):
            if tvar in raw:
                raw_vals = raw[tvar]
                if np.nanmean(raw_vals) < 60:
                    result["tmin"] = celsius_to_fahrenheit(raw_vals)
                    print(f"[convert] tmin ({tvar}): C -> F")
                else:
                    result["tmin"] = raw_vals
                break

        for pvar in ("precip", "pr", "prcp", "precipitation", "tp"):
            if pvar in raw:
                raw_vals = raw[pvar]
                # Detect scale: if mean > 1, likely mm/day
                if np.nanmean(raw_vals) > 0.1:
                    result["precip"] = mm_to_inches(raw_vals)
                    print(f"[convert] precip ({pvar}): mm -> inches")
                else:
                    # Could be m/day (ERA5) — convert to mm then inches
                    result["precip"] = mm_to_inches(raw_vals * 1000.0)
                    print(f"[convert] precip ({pvar}): m -> inches")
                break

        result["dates"] = pd.date_range(start_dt, end_dt, freq="D")[:raw.get("tmax", raw.get(list(raw.keys())[0])).shape[0]]
        return result

    else:
        raise ValueError(f"Unsupported format: {input_format}")


def write_data_file(output_dir: str, data: dict, nhru: int) -> str:
    """Write PRMS data file (station-based mode).

    Format: info string, variable headers, #### delimiter, daily data.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    data_file = output_path / "prms.data"

    variables = []
    var_arrays = []

    if "tmax" in data:
        variables.append(("tmax", 1))
        var_arrays.append(data["tmax"][:, 0:1])

    if "tmin" in data:
        variables.append(("tmin", 1))
        var_arrays.append(data["tmin"][:, 0:1])

    if "precip" in data:
        variables.append(("precip", 1))
        var_arrays.append(data["precip"][:, 0:1])

    if "runoff" in data:
        variables.append(("runoff", 1))
        var_arrays.append(data["runoff"][:, 0:1])

    if "solrad" in data:
        variables.append(("solrad", 1))
        var_arrays.append(data["solrad"][:, 0:1])

    all_data = np.hstack(var_arrays) if var_arrays else np.zeros((len(data["dates"]), 0))

    with open(data_file, "w") as f:
        f.write("PRMS data file generated by convert_forcing_to_prms.py\n")
        for vname, vcount in variables:
            f.write(f"{vname} {vcount}\n")
        f.write("####\n")

        for i, dt in enumerate(data["dates"]):
            date_str = f"{dt.year} {dt.month} {dt.day} 0 0 0"
            vals = " ".join(f"{v:.4f}" for v in all_data[i])
            f.write(f"{date_str} {vals}\n")

    print(f"[write] Data file: {data_file} ({len(data['dates'])} days)")
    return str(data_file)


def write_cbh_data_skeleton(output_dir: str, data: dict) -> str:
    """Write the minimal PRMS data file required ALONGSIDE CBH files.

    Even when temp/precip are supplied per-HRU via CBH (climate_hru module),
    PRMS still requires a `data_file` to drive the simulation clock and the obs
    module. With nobs=0 (no observed streamflow) the data file declares NO
    variables — just the info header, the `####` delimiter, and one
    `year month day hour min sec` row per timestep. This matches the proven
    working nuxia example (prms.data: header + #### + bare date rows). Without
    this file the generated control's data_file path does not exist and PRMS
    aborts at startup, so CBH mode was previously incomplete.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    data_file = output_path / "prms.data"
    with open(data_file, "w") as f:
        f.write("PRMS data file (no observations) generated by convert_forcing_to_prms.py\n")
        f.write("####\n")
        for dt in data["dates"]:
            f.write(f"{dt.year} {dt.month} {dt.day} 0 0 0\n")
    print(f"[write] Data skeleton (nobs=0): {data_file} ({len(data['dates'])} days)")
    return str(data_file)


def write_cbh_files(output_dir: str, data: dict, nhru: int) -> list:
    """Write Climate-By-HRU (CBH) files for climate_hru module.

    Each CBH file: header line, #### delimiter, daily per-HRU values.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    written = []

    for varname in ("tmax", "tmin", "precip"):
        if varname not in data:
            continue

        cbh_file = output_path / f"{varname}.cbh"
        arr = data[varname]  # (ndays, nhru)
        ndays_actual = arr.shape[0]

        with open(cbh_file, "w") as f:
            f.write(f"{varname} {nhru}\n")
            f.write("#" * 40 + "\n")

            for i in range(ndays_actual):
                dt = data["dates"][i]
                date_str = f"{dt.year} {dt.month} {dt.day} 0 0 0"
                vals = " ".join(f"{v:.4f}" for v in arr[i])
                f.write(f"{date_str} {vals}\n")

        print(f"[write] CBH file: {cbh_file} ({ndays_actual} days, {nhru} HRUs)")
        written.append(str(cbh_file))

    return written


def validate_outputs(data: dict) -> list:
    """Post-conversion validation checks.

    Returns list of warning messages.
    """
    warnings = []

    if "tmax" in data:
        tmax_mean = np.nanmean(data["tmax"])
        if tmax_mean < 20:
            warnings.append(
                f"WARNING: Mean tmax = {tmax_mean:.1f}F — suspiciously low. "
                f"Did you forget Celsius-to-Fahrenheit conversion?"
            )
        if tmax_mean > 120:
            warnings.append(
                f"WARNING: Mean tmax = {tmax_mean:.1f}F — unrealistically high. "
                f"Check input data."
            )

    if "tmin" in data and "tmax" in data:
        if np.any(data["tmin"] > data["tmax"]):
            n_bad = np.sum(data["tmin"] > data["tmax"])
            warnings.append(
                f"WARNING: tmin > tmax for {n_bad} values. Check data integrity."
            )

    if "precip" in data:
        precip_max = np.nanmax(data["precip"])
        precip_mean = np.nanmean(data["precip"])
        if precip_max > 20:  # > 20 inches/day = 508 mm/day
            warnings.append(
                f"WARNING: Max precip = {precip_max:.2f} in/day — unrealistically high. "
                f"Possible unit error (mm not converted to inches)."
            )
        if precip_mean > 1:
            warnings.append(
                f"WARNING: Mean precip = {precip_mean:.4f} in/day — high for most basins."
            )

    for w in warnings:
        print(f"  {w}")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert global forcing data to PRMS data/CBH files"
    )
    parser.add_argument("--input_dir", required=True, help="Input forcing directory")
    parser.add_argument("--output_dir", required=True, help="Output directory for PRMS files")
    parser.add_argument("--mode", choices=["station", "cbh"], default="cbh",
                        help="Output mode: station (data file) or cbh (per-HRU files)")
    parser.add_argument("--start_date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--nhru", type=int, required=True, help="Number of HRUs")
    parser.add_argument("--input_format", default="csv",
                        choices=["csv", "cmfd", "era5", "mswx", "netcdf"],
                        help="Input data format")
    args = parser.parse_args()

    # Step 1: Validate inputs
    print("=" * 60)
    print("PRMS Forcing Converter")
    print("=" * 60)
    validated = validate_inputs(
        args.input_dir, args.input_format, args.nhru,
        args.start_date, args.end_date
    )

    # Step 2: Process (read + convert units)
    print("\n--- Processing ---")
    data = process_forcing(
        validated["input_path"], args.input_format,
        validated["start_dt"], validated["end_dt"], args.nhru
    )

    # Step 3: Validate converted data
    print("\n--- Validating outputs ---")
    warnings = validate_outputs(data)

    # Step 4: Write output files
    print("\n--- Writing output ---")
    if args.mode == "station":
        output_file = write_data_file(args.output_dir, data, args.nhru)
        print(f"\nOutput: {output_file}")
    else:
        output_files = write_cbh_files(args.output_dir, data, args.nhru)
        # CBH mode also needs the companion data_file (clock + obs module).
        data_skeleton = write_cbh_data_skeleton(args.output_dir, data)
        output_files.append(data_skeleton)
        print(f"\nOutputs: {output_files}")

    if warnings:
        print(f"\n*** {len(warnings)} warnings — review before running PRMS ***")
        sys.exit(1)
    else:
        print("\nAll checks passed.")


if __name__ == "__main__":
    main()
