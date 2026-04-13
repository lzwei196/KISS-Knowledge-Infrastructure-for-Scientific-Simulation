#!/usr/bin/env python3
"""
convert_forcing_to_quincy.py
Convert meteorological forcing data to QUINCY-expected format.

Supports three data sources:
  1. FLUXNET2015 FULLSET (daily or monthly CSV)
  2. CMFD (China Meteorological Forcing Dataset, NetCDF)
  3. MSWX (Multi-Source Weather, NetCDF)

QUINCY expects:
    SW_IN (W/m2), TA (deg C), VPD (hPa), PRECIP (mm/day), CO2 (ppm)
    Plus optional: LW_IN (W/m2), WIND (m/s), PA (kPa)

UNIT TRAPS:
    - FLUXNET2015 VPD is in hPa (model uses hPa internally)
    - CMFD/MSWX temperature in K -> must subtract 273.15 for deg C
    - CMFD precipitation in kg/m2/s -> multiply by 86400 for mm/day
    - MSWX precipitation in mm/3hr -> sum 8 steps per day
    - FLUXNET2015 missing value is -9999 (must replace with NaN)

Follows validate -> process -> validate pattern.

Usage:
    # Convert FLUXNET2015 monthly
    python convert_forcing_to_quincy.py \\
        --source fluxnet --input /path/to/FULLSET_MM.csv \\
        --output quincy_forcing.csv --lat 61.85 --lon 24.29

    # Convert CMFD forcing
    python convert_forcing_to_quincy.py \\
        --source cmfd --input /path/to/cmfd_dir/ \\
        --output quincy_forcing.csv --lat 30.5 --lon 114.3 \\
        --start-year 2000 --end-year 2010

    # Validate existing forcing file
    python convert_forcing_to_quincy.py \\
        --source quincy --input quincy_forcing.csv --operation validate
"""

import os
import sys
import csv
import json
import math
import argparse
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple


# ============================================================================
# QUINCY expected variables and physical ranges
# ============================================================================

QUINCY_VARIABLES = {
    "SW_IN":  {"units": "W/m2",    "description": "Incoming shortwave radiation",
               "valid_range": (0.0, 500.0)},
    "TA":     {"units": "degC",    "description": "Air temperature at 2m",
               "valid_range": (-60.0, 55.0)},
    "VPD":    {"units": "hPa",     "description": "Vapor pressure deficit",
               "valid_range": (0.0, 80.0)},
    "PRECIP": {"units": "mm/day",  "description": "Precipitation rate",
               "valid_range": (0.0, 200.0)},
    "CO2":    {"units": "ppm",     "description": "Atmospheric CO2 concentration",
               "valid_range": (250.0, 600.0)},
}

# FLUXNET2015 column mapping
FLUXNET_COLUMN_MAP = {
    "SW_IN_F":          "SW_IN",
    "SW_IN_F_MDS":      "SW_IN",
    "TA_F":             "TA",
    "TA_F_MDS":         "TA",
    "VPD_F":            "VPD",
    "VPD_F_MDS":        "VPD",
    "P_F":              "PRECIP",
    "CO2_F_MDS":        "CO2",
    # Observations for comparison
    "GPP_NT_VUT_REF":   "GPP_OBS",
    "NEE_VUT_REF":      "NEE_OBS",
    "RECO_NT_VUT_REF":  "RECO_OBS",
    "LE_F_MDS":         "LE_OBS",
    "H_F_MDS":          "H_OBS",
}

FLUXNET_MISSING = -9999


# ============================================================================
# Daylength calculation
# ============================================================================

def calc_daylength_hours(lat_deg, month):
    """
    Calculate approximate daylength in hours for a given latitude and month.
    Uses day-of-year at mid-month and standard astronomical formula.
    """
    doy_mid = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]
    doy = doy_mid[month - 1]
    decl = 23.45 * math.sin(math.radians(360 * (284 + doy) / 365))
    decl_rad = math.radians(decl)
    lat_rad = math.radians(lat_deg)

    cos_ha = -math.tan(lat_rad) * math.tan(decl_rad)
    cos_ha = max(-1.0, min(1.0, cos_ha))
    ha = math.degrees(math.acos(cos_ha))
    return 2.0 * ha / 15.0


def calc_daylength_hours_doy(lat_deg, doy):
    """Calculate daylength in hours from latitude and day of year."""
    decl = -23.4856 * math.cos(2.0 * math.pi * (doy + 10) / 365.0)
    decl_rad = math.radians(decl)
    lat_rad = math.radians(lat_deg)

    arg = -math.tan(lat_rad) * math.tan(decl_rad)
    if arg < -1.0:
        return 24.0  # polar day
    elif arg > 1.0:
        return 0.0   # polar night
    else:
        ha = math.acos(arg)
        return 2.0 * ha * 24.0 / (2.0 * math.pi)


# ============================================================================
# Saturation vapor pressure
# ============================================================================

def calc_svp_hpa(temp_c):
    """Saturation vapor pressure in hPa from temperature in deg C (Tetens)."""
    return 6.107 * math.exp(17.38 * temp_c / (temp_c + 239.0))


# ============================================================================
# Validation: Stage 1 (inputs)
# ============================================================================

def validate_inputs(source, input_path, lat=None, lon=None,
                    start_year=None, end_year=None):
    """
    Validate input parameters before processing.

    Parameters
    ----------
    source : str
        Data source: 'fluxnet', 'cmfd', 'mswx', or 'quincy'
    input_path : str
        Path to input file or directory
    lat : float or None
        Site latitude
    lon : float or None
        Site longitude
    start_year : int or None
        Start year (for CMFD/MSWX)
    end_year : int or None
        End year (for CMFD/MSWX)

    Returns
    -------
    list of str
        Error messages (empty if valid)
    """
    errors = []

    # Check input exists
    if source in ("fluxnet", "quincy"):
        if not os.path.isfile(input_path):
            errors.append(f"Input file not found: {input_path}")
    elif source in ("cmfd", "mswx"):
        if not os.path.isdir(input_path):
            errors.append(f"Input directory not found: {input_path}")

    # Check coordinates
    if lat is not None:
        if lat < -90 or lat > 90:
            errors.append(f"Latitude out of range [-90, 90]: {lat}")
    if lon is not None:
        if lon < -180 or lon > 360:
            errors.append(f"Longitude out of range [-180, 360]: {lon}")

    # Check year range for gridded sources
    if source in ("cmfd", "mswx"):
        if start_year is None or end_year is None:
            errors.append("--start-year and --end-year required for CMFD/MSWX")
        elif start_year > end_year:
            errors.append(f"start_year ({start_year}) > end_year ({end_year})")
        elif end_year - start_year > 200:
            errors.append(f"Year span too large: {end_year - start_year}")

    # Check FLUXNET file looks right
    if source == "fluxnet" and os.path.isfile(input_path):
        with open(input_path, 'r') as f:
            header = f.readline().strip()
        if "TIMESTAMP" not in header:
            errors.append(
                f"FLUXNET file missing TIMESTAMP column in header. "
                f"Got: {header[:80]}..."
            )

    if errors:
        for e in errors:
            print(f"INPUT ERROR: {e}", file=sys.stderr)

    return errors


# ============================================================================
# Validation: Stage 3 (outputs)
# ============================================================================

def validate_outputs(data, n_expected_rows=None):
    """
    Validate converted forcing data against physical ranges.

    Parameters
    ----------
    data : dict
        Keys are variable names, values are numpy arrays
    n_expected_rows : int or None
        Expected number of data rows

    Returns
    -------
    list of str
        Warning/error messages
    """
    warnings = []

    # Check row count
    lengths = {k: len(v) for k, v in data.items()
               if isinstance(v, np.ndarray)}
    if lengths:
        n_rows = list(lengths.values())[0]
        if n_expected_rows is not None and n_rows != n_expected_rows:
            warnings.append(
                f"Expected {n_expected_rows} rows, got {n_rows}")
        if n_rows == 0:
            warnings.append("No data rows in output")
            return warnings

    # Check required variables
    required = ["SW_IN", "TA", "VPD", "PRECIP", "CO2"]
    for var in required:
        if var not in data or not isinstance(data[var], np.ndarray):
            warnings.append(f"Missing required variable: {var}")
            continue

        values = data[var]
        valid = values[~np.isnan(values)]
        if len(valid) == 0:
            warnings.append(f"{var}: all values are NaN")
            continue

        meta = QUINCY_VARIABLES.get(var, {})
        lo, hi = meta.get("valid_range", (-1e10, 1e10))
        vmin, vmax = float(np.min(valid)), float(np.max(valid))

        # Check for unit conversion errors
        if var == "TA" and vmax > 200:
            warnings.append(
                f"TA max={vmax:.1f} degC -- likely in Kelvin (subtract 273.15)")
        if var == "TA" and vmin < -80:
            warnings.append(
                f"TA min={vmin:.1f} degC -- unrealistically cold")

        if var == "PRECIP" and vmax > 500:
            warnings.append(
                f"PRECIP max={vmax:.1f} mm/day -- likely in kg/m2/s "
                f"(multiply by 86400)")
        if var == "PRECIP" and np.any(valid < 0):
            warnings.append(f"PRECIP has negative values")

        if var == "VPD" and vmax > 100:
            warnings.append(
                f"VPD max={vmax:.1f} hPa -- possibly in Pa (divide by 100)")

        if var == "SW_IN" and np.any(valid < 0):
            warnings.append(f"SW_IN has negative values")

        if var == "CO2" and vmax < 200:
            warnings.append(
                f"CO2 max={vmax:.1f} ppm -- unrealistically low, check data")

        # Check for constant values (possible fill issue)
        if len(valid) > 10 and np.std(valid) < 1e-10:
            warnings.append(
                f"{var}: all values constant ({valid[0]:.4g}) -- "
                f"possible fill value or extraction error")

        # Check for -9999 remnants
        if np.any(valid == FLUXNET_MISSING):
            warnings.append(
                f"{var}: contains -9999 values (FLUXNET missing not replaced)")

    for w in warnings:
        print(f"OUTPUT WARNING: {w}", file=sys.stderr)

    if not warnings:
        n = list(lengths.values())[0] if lengths else 0
        present = [v for v in required if v in data]
        print(f"Output validated: {n} rows, {len(present)}/{len(required)} "
              f"required variables present, ranges OK")

    return warnings


# ============================================================================
# FLUXNET2015 reader
# ============================================================================

def load_fluxnet(filepath, lat, temporal="auto"):
    """
    Load FLUXNET2015 FULLSET CSV and convert to QUINCY forcing.

    Parameters
    ----------
    filepath : str
        Path to FULLSET_DD.csv or FULLSET_MM.csv
    lat : float
        Site latitude (for daylength calculation)
    temporal : str
        'daily', 'monthly', or 'auto' (detect from filename)

    Returns
    -------
    dict with numpy arrays for each variable, plus 'time' list
    """
    # Auto-detect temporal resolution
    if temporal == "auto":
        basename = os.path.basename(filepath).upper()
        if "_DD" in basename or "DAILY" in basename:
            temporal = "daily"
        elif "_MM" in basename or "MONTHLY" in basename:
            temporal = "monthly"
        else:
            temporal = "monthly"
        print(f"  Auto-detected temporal resolution: {temporal}")

    # Read CSV
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("ERROR: Empty FLUXNET file", file=sys.stderr)
        return {}

    n = len(rows)
    print(f"  Read {n} rows from {os.path.basename(filepath)}")

    # Initialize output arrays
    data = {
        "SW_IN": np.full(n, np.nan),
        "TA": np.full(n, np.nan),
        "VPD": np.full(n, np.nan),
        "PRECIP": np.full(n, np.nan),
        "CO2": np.full(n, np.nan),
        "DAYLENGTH": np.full(n, np.nan),
        "YEAR": np.zeros(n, dtype=int),
        "MONTH": np.zeros(n, dtype=int),
        # Observations (for comparison)
        "GPP_OBS": np.full(n, np.nan),
        "NEE_OBS": np.full(n, np.nan),
        "RECO_OBS": np.full(n, np.nan),
        "LE_OBS": np.full(n, np.nan),
        "H_OBS": np.full(n, np.nan),
    }
    times = []

    available_cols = set(rows[0].keys())

    for i, row in enumerate(rows):
        # Parse timestamp
        ts = row.get("TIMESTAMP", "")
        if temporal == "monthly":
            # YYYYMM format
            if len(ts) >= 6:
                year = int(ts[:4])
                month = int(ts[4:6])
                data["YEAR"][i] = year
                data["MONTH"][i] = month
                times.append(f"{year}-{month:02d}")
                data["DAYLENGTH"][i] = calc_daylength_hours(lat, month)
        elif temporal == "daily":
            # YYYYMMDD format
            if len(ts) >= 8:
                year = int(ts[:4])
                month = int(ts[4:6])
                day = int(ts[6:8])
                data["YEAR"][i] = year
                data["MONTH"][i] = month
                doy = (datetime(year, month, day) -
                       datetime(year, 1, 1)).days + 1
                times.append(f"{year}-{month:02d}-{day:02d}")
                data["DAYLENGTH"][i] = calc_daylength_hours_doy(lat, doy)

        # Map FLUXNET columns to QUINCY variables
        for fluxnet_col, quincy_var in FLUXNET_COLUMN_MAP.items():
            if fluxnet_col in available_cols and quincy_var in data:
                try:
                    val = float(row[fluxnet_col])
                    # Replace FLUXNET missing value with NaN
                    if val == FLUXNET_MISSING or val <= FLUXNET_MISSING:
                        val = np.nan
                    data[quincy_var][i] = val
                except (ValueError, TypeError):
                    pass

    data["time"] = times

    # Fill CO2 gaps with global trend if >50% missing
    co2 = data["CO2"]
    if np.isnan(co2).sum() > n * 0.5:
        print("  WARNING: >50% CO2 missing, filling with global trend "
              "(360 ppm in 1996 + 2.1 ppm/yr)", file=sys.stderr)
        years = data["YEAR"]
        data["CO2"] = np.where(
            np.isnan(co2),
            360.0 + (years - 1996) * 2.1,
            co2
        )

    # Report coverage
    for var in ["SW_IN", "TA", "VPD", "PRECIP", "CO2"]:
        valid_pct = (1 - np.isnan(data[var]).sum() / n) * 100
        print(f"  {var}: {valid_pct:.1f}% valid")

    return data


# ============================================================================
# CMFD reader
# ============================================================================

def load_cmfd(cmfd_dir, lat, lon, start_year, end_year):
    """
    Load CMFD (China Meteorological Forcing Dataset) data.

    CMFD provides: temp (K), precip (kg/m2/s), srad (W/m2), pres (Pa),
                   wind (m/s), shum (kg/kg) at 0.1-degree, 3-hourly.

    Parameters
    ----------
    cmfd_dir : str
        Path to CMFD data directory
    lat, lon : float
        Site coordinates
    start_year, end_year : int
        Year range (inclusive)

    Returns
    -------
    dict with numpy arrays (daily values)
    """
    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required for CMFD. Install: pip install netCDF4",
              file=sys.stderr)
        sys.exit(1)

    all_data = {
        "SW_IN": [], "TA": [], "VPD": [], "PRECIP": [], "CO2": [],
        "DAYLENGTH": [], "YEAR": [], "MONTH": [], "time": [],
    }

    for year in range(start_year, end_year + 1):
        print(f"  Processing CMFD year {year}...")
        for month in range(1, 13):
            # Try to read monthly CMFD file
            patterns = [
                os.path.join(cmfd_dir, f"temp/temp_CMFD_V0106_B-01_01mo_050km_{year}{month:02d}*.nc"),
                os.path.join(cmfd_dir, f"{year}", f"*{year}{month:02d}*.nc"),
            ]

            # Placeholder: in real use, read actual NetCDF
            # For now, generate synthetic with correct units
            doy_mid = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]
            dl = calc_daylength_hours(lat, month)

            # UNIT CONVERSION: K -> degC
            # ta_k = read_from_netcdf(...)  # K
            # ta_c = ta_k - 273.15          # CRITICAL: K -> degC

            # UNIT CONVERSION: kg/m2/s -> mm/day
            # precip_kgm2s = read_from_netcdf(...)
            # precip_mmday = precip_kgm2s * 86400.0  # CRITICAL: kg/m2/s -> mm/day

            all_data["YEAR"].append(year)
            all_data["MONTH"].append(month)
            all_data["time"].append(f"{year}-{month:02d}")
            all_data["DAYLENGTH"].append(dl)
            all_data["SW_IN"].append(np.nan)
            all_data["TA"].append(np.nan)
            all_data["VPD"].append(np.nan)
            all_data["PRECIP"].append(np.nan)
            all_data["CO2"].append(360.0 + (year - 1996) * 2.1)

    # Convert lists to arrays
    for key in ["SW_IN", "TA", "VPD", "PRECIP", "CO2", "DAYLENGTH"]:
        all_data[key] = np.array(all_data[key])
    for key in ["YEAR", "MONTH"]:
        all_data[key] = np.array(all_data[key], dtype=int)

    print(f"  CMFD: prepared {len(all_data['time'])} monthly records "
          f"({start_year}-{end_year})")
    print("  NOTE: CMFD reader requires actual NetCDF data files. "
          "Placeholder values returned.", file=sys.stderr)

    return all_data


# ============================================================================
# MSWX reader
# ============================================================================

def load_mswx(mswx_dir, lat, lon, start_year, end_year):
    """
    Load MSWX (Multi-Source Weather) 3-hourly data and aggregate to daily/monthly.

    MSWX provides: Tair (K), P (mm/3hr), SWd (W/m2), LWd (W/m2),
                   wind (m/s), Pres (Pa), spechum (kg/kg) at 0.1-degree.

    Parameters
    ----------
    mswx_dir : str
        Path to MSWX data directory
    lat, lon : float
        Site coordinates
    start_year, end_year : int
        Year range (inclusive)

    Returns
    -------
    dict with numpy arrays (monthly aggregated values)
    """
    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required for MSWX. Install: pip install netCDF4",
              file=sys.stderr)
        sys.exit(1)

    all_data = {
        "SW_IN": [], "TA": [], "VPD": [], "PRECIP": [], "CO2": [],
        "DAYLENGTH": [], "YEAR": [], "MONTH": [], "time": [],
    }

    for year in range(start_year, end_year + 1):
        print(f"  Processing MSWX year {year}...")
        for month in range(1, 13):
            dl = calc_daylength_hours(lat, month)

            # UNIT CONVERSION: K -> degC
            # tair_3h_k = read_mswx_variable("Temp", ...)  # K
            # tair_3h_c = tair_3h_k - 273.15  # CRITICAL: K -> degC
            # ta_monthly = np.mean(tair_3h_c)

            # UNIT CONVERSION: mm/3hr -> mm/day
            # precip_3h = read_mswx_variable("P", ...)  # mm/3hr
            # For daily: sum 8 steps per day
            # precip_daily = np.sum(precip_3h.reshape(-1, 8), axis=1)  # mm/day
            # precip_monthly_mean = np.mean(precip_daily)

            # VPD from specific humidity and pressure
            # shum = read_mswx_variable("spechum", ...)
            # pres = read_mswx_variable("Pres", ...)
            # e_act = shum * pres / (0.622 + 0.378 * shum)  # Pa
            # e_sat = calc_svp_hpa(ta) * 100  # Pa
            # vpd_hpa = max(0, (e_sat - e_act)) / 100.0  # hPa

            all_data["YEAR"].append(year)
            all_data["MONTH"].append(month)
            all_data["time"].append(f"{year}-{month:02d}")
            all_data["DAYLENGTH"].append(dl)
            all_data["SW_IN"].append(np.nan)
            all_data["TA"].append(np.nan)
            all_data["VPD"].append(np.nan)
            all_data["PRECIP"].append(np.nan)
            all_data["CO2"].append(360.0 + (year - 1996) * 2.1)

    for key in ["SW_IN", "TA", "VPD", "PRECIP", "CO2", "DAYLENGTH"]:
        all_data[key] = np.array(all_data[key])
    for key in ["YEAR", "MONTH"]:
        all_data[key] = np.array(all_data[key], dtype=int)

    print(f"  MSWX: prepared {len(all_data['time'])} monthly records "
          f"({start_year}-{end_year})")
    print("  NOTE: MSWX reader requires actual NetCDF data files. "
          "Placeholder values returned.", file=sys.stderr)

    return all_data


# ============================================================================
# Export to QUINCY forcing CSV
# ============================================================================

def export_forcing_csv(data, output_path):
    """
    Export converted forcing data to QUINCY-format CSV.

    Parameters
    ----------
    data : dict
        Forcing data with numpy arrays
    output_path : str
        Output CSV file path
    """
    times = data.get("time", [])
    n = len(times)

    # Columns to write
    columns = ["YEAR", "MONTH", "SW_IN", "TA", "VPD", "PRECIP", "CO2",
               "DAYLENGTH"]
    obs_columns = ["GPP_OBS", "NEE_OBS", "RECO_OBS", "LE_OBS", "H_OBS"]

    # Include obs columns if present
    write_cols = list(columns)
    for oc in obs_columns:
        if oc in data and isinstance(data[oc], np.ndarray):
            if not np.all(np.isnan(data[oc])):
                write_cols.append(oc)

    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)

        # Header
        header = ["TIMESTAMP"] + write_cols
        writer.writerow(header)

        # Units row
        units_map = {
            "YEAR": "year", "MONTH": "month",
            "SW_IN": "W/m2", "TA": "degC", "VPD": "hPa",
            "PRECIP": "mm/day", "CO2": "ppm", "DAYLENGTH": "hours",
            "GPP_OBS": "umol/m2/s", "NEE_OBS": "umol/m2/s",
            "RECO_OBS": "umol/m2/s", "LE_OBS": "W/m2", "H_OBS": "W/m2",
        }
        units_row = [""] + [units_map.get(c, "") for c in write_cols]
        writer.writerow(units_row)

        # Data rows
        for i in range(n):
            row = [times[i] if i < len(times) else ""]
            for col in write_cols:
                if col in data:
                    arr = data[col]
                    if isinstance(arr, np.ndarray) and i < len(arr):
                        val = arr[i]
                        if np.isnan(val):
                            row.append("NaN")
                        elif col in ("YEAR", "MONTH"):
                            row.append(str(int(val)))
                        else:
                            row.append(f"{val:.4f}")
                    else:
                        row.append("NaN")
                else:
                    row.append("NaN")
            writer.writerow(row)

    print(f"  QUINCY forcing written: {output_path} "
          f"({n} timesteps, {len(write_cols)} variables)")


# ============================================================================
# Main conversion pipeline
# ============================================================================

def convert_forcing(source, input_path, output_path, lat, lon,
                    start_year=None, end_year=None, temporal="auto"):
    """
    Full conversion pipeline: validate -> process -> validate.

    Parameters
    ----------
    source : str
        'fluxnet', 'cmfd', 'mswx'
    input_path : str
        Input file or directory
    output_path : str
        Output CSV path
    lat, lon : float
        Site coordinates
    start_year, end_year : int or None
        Year range (CMFD/MSWX)
    temporal : str
        Temporal resolution override ('daily', 'monthly', 'auto')

    Returns
    -------
    dict with status information
    """
    # Stage 1: Validate inputs
    print("Stage 1: Validating inputs...")
    errors = validate_inputs(source, input_path, lat, lon,
                             start_year, end_year)
    if errors:
        return {"status": "error", "stage": "input_validation", "errors": errors}

    # Stage 2: Process
    print(f"Stage 2: Loading {source} data...")
    if source == "fluxnet":
        data = load_fluxnet(input_path, lat, temporal)
    elif source == "cmfd":
        data = load_cmfd(input_path, lat, lon, start_year, end_year)
    elif source == "mswx":
        data = load_mswx(input_path, lat, lon, start_year, end_year)
    else:
        return {"status": "error", "message": f"Unknown source: {source}"}

    if not data:
        return {"status": "error", "message": "No data loaded"}

    # Export
    print("Stage 2b: Exporting forcing CSV...")
    export_forcing_csv(data, output_path)

    # Stage 3: Validate outputs
    print("Stage 3: Validating outputs...")
    warnings = validate_outputs(data)

    result = {
        "status": "success" if not warnings else "completed_with_warnings",
        "source": source,
        "input_file": input_path,
        "output_file": output_path,
        "n_timesteps": len(data.get("time", [])),
        "variables": [v for v in QUINCY_VARIABLES if v in data],
        "warnings": warnings,
    }

    return result


def validate_existing(input_path):
    """
    Validate an existing QUINCY forcing CSV file.

    Parameters
    ----------
    input_path : str
        Path to QUINCY forcing CSV

    Returns
    -------
    dict with validation results
    """
    if not os.path.isfile(input_path):
        return {"status": "error", "message": f"File not found: {input_path}"}

    # Read CSV
    with open(input_path, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return {"status": "error", "message": "Empty file"}

    # Skip units row if present
    first_row = rows[0]
    if any(v in str(first_row) for v in ["W/m2", "degC", "hPa", "mm/day", "ppm"]):
        rows = rows[1:]

    n = len(rows)
    data = {}
    for var in QUINCY_VARIABLES:
        if var in rows[0]:
            vals = []
            for row in rows:
                try:
                    v = float(row[var])
                    vals.append(v)
                except (ValueError, TypeError):
                    vals.append(np.nan)
            data[var] = np.array(vals)

    warnings = validate_outputs(data)

    return {
        "status": "success" if not warnings else "completed_with_warnings",
        "n_rows": n,
        "variables_found": list(data.keys()),
        "warnings": warnings,
    }


# ============================================================================
# CLI entry point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert meteorological forcing data to QUINCY format. "
                    "Supports FLUXNET2015, CMFD, and MSWX sources."
    )
    parser.add_argument("--source", required=True,
                        choices=["fluxnet", "cmfd", "mswx", "quincy"],
                        help="Data source type")
    parser.add_argument("--input", required=True,
                        help="Input file (FLUXNET CSV) or directory (CMFD/MSWX)")
    parser.add_argument("--output", default=None,
                        help="Output QUINCY forcing CSV")
    parser.add_argument("--operation", choices=["convert", "validate"],
                        default="convert",
                        help="Operation mode (default: convert)")
    parser.add_argument("--lat", type=float, default=None,
                        help="Site latitude (degrees, required for conversion)")
    parser.add_argument("--lon", type=float, default=None,
                        help="Site longitude (degrees)")
    parser.add_argument("--start-year", type=int, default=None,
                        help="Start year (CMFD/MSWX)")
    parser.add_argument("--end-year", type=int, default=None,
                        help="End year (CMFD/MSWX)")
    parser.add_argument("--temporal", choices=["daily", "monthly", "auto"],
                        default="auto",
                        help="Temporal resolution (default: auto-detect)")
    args = parser.parse_args()

    if args.operation == "validate":
        result = validate_existing(args.input)
    else:
        if args.lat is None:
            print("ERROR: --lat required for conversion", file=sys.stderr)
            sys.exit(1)
        if args.output is None:
            print("ERROR: --output required for conversion", file=sys.stderr)
            sys.exit(1)
        result = convert_forcing(
            args.source, args.input, args.output,
            args.lat, args.lon,
            args.start_year, args.end_year,
            args.temporal,
        )

    print(json.dumps(result, indent=2))

    if result.get("status") == "error":
        sys.exit(1)
