#!/usr/bin/env python3
"""
convert_forcing_to_lpjguess.py
Convert meteorological forcing data to LPJ-GUESS expected format.

Supported sources:
  1. FLUXNET2015 FULLSET (daily DD or monthly MM CSV)
  2. CMFD (China Meteorological Forcing Dataset) NetCDF
  3. MSWX (Multi-Source Weather) NetCDF

LPJ-GUESS (analytic reimplementation) expects:
    date, SW_IN (W/m2), TA (deg C), VPD (hPa), P (mm/day)

UNIT TRAPS:
    - FLUXNET missing value is -9999 -> must convert to NaN
    - FLUXNET VPD is in hPa (good, no conversion needed)
    - CMFD temperature is in K -> subtract 273.15 for deg C
    - CMFD precipitation is in kg/m2/s -> multiply by 86400 for mm/day
    - MSWX temperature is in K -> subtract 273.15 for deg C
    - MSWX precipitation is in mm/3hr -> sum 8 steps per day
    - Some datasets provide VPD in kPa -> multiply by 10 for hPa
    - Some datasets provide VPD in Pa -> divide by 100 for hPa
    - SW_IN must be total incoming shortwave (not net radiation)

Usage:
    # FLUXNET2015 daily
    python convert_forcing_to_lpjguess.py \\
        --source fluxnet \\
        --input /path/to/FLX_SITE_FULLSET_DD.csv \\
        --output forcing_lpjguess.csv

    # FLUXNET2015 monthly
    python convert_forcing_to_lpjguess.py \\
        --source fluxnet \\
        --input /path/to/FLX_SITE_FULLSET_MM.csv \\
        --output forcing_lpjguess.csv \\
        --timestep monthly

    # CMFD gridded
    python convert_forcing_to_lpjguess.py \\
        --source cmfd \\
        --input /path/to/cmfd_dir/ \\
        --lat 40.48 --lon 116.97 \\
        --start-year 2000 --end-year 2010 \\
        --output forcing_lpjguess.csv

    # MSWX gridded
    python convert_forcing_to_lpjguess.py \\
        --source mswx \\
        --input /path/to/mswx_dir/ \\
        --lat 60.08 --lon 24.29 \\
        --start-year 2000 --end-year 2010 \\
        --output forcing_lpjguess.csv
"""

import os
import sys
import math
import argparse
import csv
from datetime import datetime, timedelta

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None


# ============================================================================
# Physical constants
# ============================================================================

KELVIN_OFFSET = 273.15            # K -> deg C
SECONDS_PER_DAY = 86400.0         # s/day
FLUXNET_MISSING = -9999           # FLUXNET fill value
PAR_FRACTION = 0.48               # Fraction of SW that is PAR


# ============================================================================
# Column name search helpers
# ============================================================================

# FLUXNET2015 column name candidates (in priority order)
FLUXNET_COLUMN_CANDIDATES = {
    "SW_IN": ["SW_IN_F", "SW_IN_F_MDS", "SW_IN", "SW_IN_ERA"],
    "TA":    ["TA_F", "TA_F_MDS", "TA_ERA", "TA"],
    "VPD":   ["VPD_F", "VPD_F_MDS", "VPD_ERA", "VPD"],
    "P":     ["P_F", "P_F_MDS", "P_ERA", "P"],
}


def find_column(columns, candidates):
    """Find first matching column from candidates list."""
    for c in candidates:
        if c in columns:
            return c
    return None


# ============================================================================
# Input validation
# ============================================================================

def validate_inputs(source, input_path, output_path, lat=None, lon=None,
                    start_year=None, end_year=None, timestep="daily"):
    """
    Validate all input parameters before processing.

    Returns list of error strings (empty if all OK).
    """
    errors = []
    warnings = []

    # Source type
    valid_sources = ["fluxnet", "cmfd", "mswx"]
    if source not in valid_sources:
        errors.append(f"Unknown source '{source}'. Must be one of: {valid_sources}")

    # Input path
    if source == "fluxnet":
        if not os.path.isfile(input_path):
            errors.append(f"FLUXNET input file not found: {input_path}")
        elif not input_path.endswith(".csv"):
            warnings.append(f"FLUXNET input does not end with .csv: {input_path}")
    else:
        if not os.path.isdir(input_path):
            errors.append(f"Input directory not found: {input_path}")

    # Coordinates (required for gridded data)
    if source in ("cmfd", "mswx"):
        if lat is None or lon is None:
            errors.append(f"--lat and --lon required for source={source}")
        elif not -90 <= lat <= 90:
            errors.append(f"Latitude out of range: {lat}")
        elif not -180 <= lon <= 360:
            errors.append(f"Longitude out of range: {lon}")

    # Year range (required for gridded data)
    if source in ("cmfd", "mswx"):
        if start_year is None or end_year is None:
            errors.append(f"--start-year and --end-year required for source={source}")
        elif start_year > end_year:
            errors.append(f"start_year ({start_year}) > end_year ({end_year})")
        elif end_year - start_year > 200:
            errors.append(f"Year span too large: {end_year - start_year} years")

    # Timestep
    if timestep not in ("daily", "monthly"):
        errors.append(f"Timestep must be 'daily' or 'monthly', got '{timestep}'")

    # Output directory must exist
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.isdir(output_dir):
        errors.append(f"Output directory does not exist: {output_dir}")

    # Print results
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)

    return errors


# ============================================================================
# Output validation
# ============================================================================

def validate_outputs(output_path, expected_rows=None):
    """
    Validate the generated forcing file for physical plausibility.

    Returns True if valid, False if critical issues found.
    """
    if not os.path.isfile(output_path):
        print(f"ERROR: Output file not created: {output_path}", file=sys.stderr)
        return False

    size = os.path.getsize(output_path)
    if size == 0:
        print(f"ERROR: Output file is empty: {output_path}", file=sys.stderr)
        return False

    warnings = []
    n_rows = 0
    n_nan = {"SW_IN": 0, "TA": 0, "VPD": 0, "P": 0}

    with open(output_path, "r") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        if columns is None:
            print(f"ERROR: Could not read CSV header from {output_path}", file=sys.stderr)
            return False

        required = ["SW_IN", "TA", "VPD"]
        for req in required:
            if req not in columns:
                warnings.append(f"Missing required column: {req}")

        sw_vals = []
        ta_vals = []
        vpd_vals = []
        p_vals = []

        for row in reader:
            n_rows += 1

            try:
                sw = float(row.get("SW_IN", "nan"))
                ta = float(row.get("TA", "nan"))
                vpd = float(row.get("VPD", "nan"))
                p = float(row.get("P", "nan")) if "P" in row else float("nan")
            except (ValueError, TypeError):
                continue

            if math.isnan(sw):
                n_nan["SW_IN"] += 1
            else:
                sw_vals.append(sw)
            if math.isnan(ta):
                n_nan["TA"] += 1
            else:
                ta_vals.append(ta)
            if math.isnan(vpd):
                n_nan["VPD"] += 1
            else:
                vpd_vals.append(vpd)
            if math.isnan(p):
                n_nan["P"] += 1
            else:
                p_vals.append(p)

    # Row count check
    if expected_rows is not None and n_rows != expected_rows:
        warnings.append(f"Expected {expected_rows} rows, got {n_rows}")

    if n_rows == 0:
        print(f"ERROR: No data rows in output", file=sys.stderr)
        return False

    # NaN fraction warnings
    for var, count in n_nan.items():
        frac = count / n_rows
        if frac > 0.5:
            warnings.append(f"{var}: {frac:.0%} missing values (>50%)")
        elif frac > 0.1:
            warnings.append(f"{var}: {frac:.0%} missing values (>10%)")

    # Physical range checks
    if sw_vals:
        sw_min, sw_max = min(sw_vals), max(sw_vals)
        if sw_min < -1:
            warnings.append(f"SW_IN min={sw_min:.1f} W/m2 is negative")
        if sw_max > 600:
            warnings.append(f"SW_IN max={sw_max:.1f} W/m2 unusually high (>600)")
        if sw_max > 1400:
            warnings.append(f"CRITICAL: SW_IN max={sw_max:.1f} W/m2 exceeds solar constant")

    if ta_vals:
        ta_min, ta_max = min(ta_vals), max(ta_vals)
        if ta_min > 100:
            warnings.append(
                f"CRITICAL: TA min={ta_min:.1f} -- values >100 suggest Kelvin not converted to Celsius!"
            )
        if ta_max > 60:
            warnings.append(f"TA max={ta_max:.1f} C unusually high")
        if ta_min < -80:
            warnings.append(f"TA min={ta_min:.1f} C unusually low")

    if vpd_vals:
        vpd_min, vpd_max = min(vpd_vals), max(vpd_vals)
        if vpd_min < 0:
            warnings.append(f"VPD min={vpd_min:.2f} hPa is negative (should be >= 0)")
        if vpd_max > 100:
            warnings.append(
                f"VPD max={vpd_max:.1f} hPa very high -- check units. "
                f"FLUXNET VPD is in hPa; if in Pa, divide by 100."
            )
        if vpd_max < 0.5:
            warnings.append(
                f"VPD max={vpd_max:.3f} hPa very low -- check units. "
                f"If in kPa, multiply by 10 for hPa."
            )

    if p_vals:
        p_min, p_max = min(p_vals), max(p_vals)
        if p_min < 0:
            warnings.append(f"Precipitation min={p_min:.2f} mm/day is negative")
        if p_max > 500:
            warnings.append(
                f"Precipitation max={p_max:.1f} mm/day extremely high -- "
                f"check units (should be mm/day, not kg/m2/s)"
            )

    # Report
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    critical = any("CRITICAL" in w for w in warnings)
    if not warnings:
        print(f"Output validated: {n_rows} rows, all values within expected ranges")
    elif not critical:
        print(f"Output has {len(warnings)} warnings but no critical issues ({n_rows} rows)")
    else:
        print(f"Output has CRITICAL issues -- check unit conversions!", file=sys.stderr)

    return not critical


# ============================================================================
# Saturation vapor pressure (for computing VPD from humidity)
# ============================================================================

def calc_svp(temp_c):
    """Saturation vapor pressure in hPa from temperature in deg C (Tetens)."""
    return 6.107 * math.exp(17.38 * temp_c / (temp_c + 239.0))


def calc_vpd_from_rh(temp_c, rh_pct):
    """Compute VPD (hPa) from temperature (C) and relative humidity (%)."""
    svp = calc_svp(temp_c)
    vpd = svp * (1.0 - rh_pct / 100.0)
    return max(0.0, vpd)


def calc_vpd_from_spechum(temp_c, spechum_kgkg, pres_pa):
    """Compute VPD (hPa) from temperature, specific humidity, and pressure."""
    svp_pa = calc_svp(temp_c) * 100.0  # hPa -> Pa
    e_act = spechum_kgkg * pres_pa / (0.622 + 0.378 * spechum_kgkg)
    vpd_pa = max(0.0, svp_pa - e_act)
    return vpd_pa / 100.0  # Pa -> hPa


# ============================================================================
# FLUXNET2015 converter
# ============================================================================

def convert_fluxnet(input_path, output_path, timestep="daily"):
    """
    Convert FLUXNET2015 FULLSET CSV to LPJ-GUESS forcing CSV.

    Handles both daily (DD) and monthly (MM) files.
    FLUXNET missing values (-9999) are converted to NaN.
    VPD is already in hPa in FLUXNET2015 (no conversion needed).

    Parameters
    ----------
    input_path : str
        Path to FLUXNET2015 CSV file (FULLSET_DD or FULLSET_MM)
    output_path : str
        Path to output CSV
    timestep : str
        "daily" or "monthly"
    """
    if pd is None:
        print("ERROR: pandas required for FLUXNET conversion. pip install pandas",
              file=sys.stderr)
        sys.exit(1)

    print(f"Loading FLUXNET data: {input_path}")
    df = pd.read_csv(input_path)

    # Replace FLUXNET missing values
    df = df.replace(FLUXNET_MISSING, np.nan)
    df = df.replace(float(FLUXNET_MISSING), np.nan)

    # Parse timestamps
    if "TIMESTAMP" in df.columns:
        ts = df["TIMESTAMP"].astype(str)
    elif "TIMESTAMP_START" in df.columns:
        ts = df["TIMESTAMP_START"].astype(str)
    else:
        print(f"ERROR: No TIMESTAMP column. Columns: {list(df.columns)[:20]}",
              file=sys.stderr)
        sys.exit(1)

    if timestep == "monthly":
        # Monthly: YYYYMM format
        df["year"] = ts.str[:4].astype(int)
        df["month"] = ts.str[4:6].astype(int)
        df["day"] = 15  # mid-month
        df["date"] = pd.to_datetime(
            df["year"].astype(str) + "-" +
            df["month"].astype(str).str.zfill(2) + "-15"
        )
    else:
        # Daily: YYYYMMDD format
        ts_str = ts.str[:8]
        df["date"] = pd.to_datetime(ts_str, format="%Y%m%d", errors="coerce")
        df["year"] = df["date"].dt.year
        df["month"] = df["date"].dt.month
        df["day"] = df["date"].dt.day

    # Find columns
    columns_found = {}
    for target, candidates in FLUXNET_COLUMN_CANDIDATES.items():
        col = find_column(df.columns.tolist(), candidates)
        if col is not None:
            columns_found[target] = col
        else:
            print(f"WARNING: No column found for {target}. "
                  f"Tried: {candidates}", file=sys.stderr)

    # Build output dataframe
    out = pd.DataFrame()
    out["date"] = df["date"]
    out["year"] = df["year"]
    out["month"] = df["month"]

    # SW_IN: W/m2 (FLUXNET already in W/m2)
    if "SW_IN" in columns_found:
        out["SW_IN"] = df[columns_found["SW_IN"]].astype(float)
        # Clip negative values (nighttime artifacts)
        out["SW_IN"] = out["SW_IN"].clip(lower=0.0)
    else:
        out["SW_IN"] = np.nan

    # TA: deg C (FLUXNET already in deg C)
    if "TA" in columns_found:
        out["TA"] = df[columns_found["TA"]].astype(float)
    else:
        out["TA"] = np.nan

    # VPD: hPa (FLUXNET already in hPa)
    if "VPD" in columns_found:
        out["VPD"] = df[columns_found["VPD"]].astype(float)
        # Clip negative VPD
        out["VPD"] = out["VPD"].clip(lower=0.0)
    else:
        out["VPD"] = np.nan

    # Precipitation: mm/day (FLUXNET P_F is in mm/day for DD, mm/month for MM)
    if "P" in columns_found:
        out["P"] = df[columns_found["P"]].astype(float)
        out["P"] = out["P"].clip(lower=0.0)
        if timestep == "monthly":
            # Convert mm/month to mm/day (approximate)
            days_in_month = df["date"].dt.days_in_month
            out["P"] = out["P"] / days_in_month
    else:
        out["P"] = np.nan

    # Drop rows where all forcing is NaN
    out = out.dropna(subset=["SW_IN", "TA", "VPD"], how="all").reset_index(drop=True)

    # Write output
    out.to_csv(output_path, index=False, float_format="%.4f",
               na_rep="NaN")
    print(f"FLUXNET forcing written: {output_path} ({len(out)} rows)")

    return len(out)


# ============================================================================
# CMFD converter
# ============================================================================

def convert_cmfd(input_dir, output_path, lat, lon, start_year, end_year):
    """
    Convert CMFD (China Meteorological Forcing Dataset) to LPJ-GUESS forcing.

    CMFD provides 3-hourly data in NetCDF:
      - temp: air temperature (K)
      - prec: precipitation rate (kg/m2/s)
      - srad: downward shortwave radiation (W/m2)
      - shum: specific humidity (kg/kg)
      - pres: surface pressure (Pa)
      - wind: wind speed (m/s)

    UNIT CONVERSIONS:
      - Temperature: K -> deg C  (subtract 273.15)
      - Precipitation: kg/m2/s -> mm/day  (multiply by 86400)
      - VPD: computed from temperature, specific humidity, and pressure

    Parameters
    ----------
    input_dir : str
        CMFD data directory
    output_path : str
        Output CSV path
    lat, lon : float
        Site coordinates
    start_year, end_year : int
        Year range (inclusive)
    """
    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required for CMFD conversion. pip install netCDF4",
              file=sys.stderr)
        sys.exit(1)

    if pd is None:
        print("ERROR: pandas required. pip install pandas", file=sys.stderr)
        sys.exit(1)

    print(f"Converting CMFD data: {input_dir}")
    print(f"  Location: lat={lat}, lon={lon}")
    print(f"  Period: {start_year}-{end_year}")

    import glob as globmod

    rows = []
    for year in range(start_year, end_year + 1):
        print(f"  Processing CMFD year {year}...")

        # Find files for this year (temp, srad, prec, shum, pres)
        var_data = {}
        for var_name, cmfd_name in [("temp", "temp"), ("srad", "srad"),
                                     ("prec", "prec"), ("shum", "shum"),
                                     ("pres", "pres")]:
            pattern = os.path.join(input_dir, f"**/*{cmfd_name}*{year}*.nc")
            files = sorted(globmod.glob(pattern, recursive=True))
            if not files:
                pattern = os.path.join(input_dir, cmfd_name, f"*{year}*.nc")
                files = sorted(globmod.glob(pattern))
            if not files:
                print(f"  WARNING: No CMFD file for {cmfd_name}/{year}", file=sys.stderr)
                var_data[var_name] = None
                continue

            # Read nearest grid point from first matching file
            all_vals = []
            for fpath in files:
                ds = nc.Dataset(fpath, "r")
                lats = ds.variables["lat"][:]
                lons = ds.variables["lon"][:]
                ilat = int(np.argmin(np.abs(lats - lat)))
                ilon = int(np.argmin(np.abs(lons - lon)))

                data_vars = [v for v in ds.variables
                             if v not in ("lat", "lon", "time", "latitude", "longitude")]
                if data_vars:
                    vals = ds.variables[data_vars[0]][:, ilat, ilon]
                    all_vals.extend(vals.tolist())
                ds.close()

            var_data[var_name] = np.array(all_vals) if all_vals else None

        # Aggregate 3-hourly to daily
        if var_data.get("temp") is None or var_data.get("srad") is None:
            print(f"  WARNING: Skipping year {year} (missing essential variables)",
                  file=sys.stderr)
            continue

        ndays = 366 if _is_leap_year(year) else 365
        steps_per_day = 8  # 3-hourly

        for var_name in var_data:
            if var_data[var_name] is not None:
                expected = ndays * steps_per_day
                actual = len(var_data[var_name])
                if actual < expected:
                    var_data[var_name] = np.pad(
                        var_data[var_name],
                        (0, expected - actual),
                        mode="edge"
                    )
                var_data[var_name] = var_data[var_name][:expected]

        for doy in range(ndays):
            i0 = doy * steps_per_day
            i1 = i0 + steps_per_day
            date = datetime(year, 1, 1) + timedelta(days=doy)

            # Temperature: K -> C
            if var_data.get("temp") is not None:
                ta_k = np.mean(var_data["temp"][i0:i1])
                ta_c = ta_k - KELVIN_OFFSET
            else:
                ta_c = float("nan")

            # SW radiation: daily mean W/m2
            if var_data.get("srad") is not None:
                sw_in = float(np.mean(var_data["srad"][i0:i1]))
                sw_in = max(0.0, sw_in)
            else:
                sw_in = float("nan")

            # Precipitation: kg/m2/s -> mm/day
            if var_data.get("prec") is not None:
                p_rate = np.mean(var_data["prec"][i0:i1])
                p_mmday = p_rate * SECONDS_PER_DAY
                p_mmday = max(0.0, p_mmday)
            else:
                p_mmday = float("nan")

            # VPD: compute from specific humidity and pressure
            if (var_data.get("shum") is not None and
                    var_data.get("pres") is not None and
                    not math.isnan(ta_c)):
                shum = float(np.mean(var_data["shum"][i0:i1]))
                pres = float(np.mean(var_data["pres"][i0:i1]))
                vpd_hpa = calc_vpd_from_spechum(ta_c, shum, pres)
            else:
                vpd_hpa = float("nan")

            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "year": year,
                "month": date.month,
                "SW_IN": round(sw_in, 4),
                "TA": round(ta_c, 4),
                "VPD": round(vpd_hpa, 4),
                "P": round(p_mmday, 4),
            })

    # Write output
    if not rows:
        print("ERROR: No data rows generated", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "year", "month",
                                                "SW_IN", "TA", "VPD", "P"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"CMFD forcing written: {output_path} ({len(rows)} rows)")
    return len(rows)


# ============================================================================
# MSWX converter
# ============================================================================

def convert_mswx(input_dir, output_path, lat, lon, start_year, end_year):
    """
    Convert MSWX (Multi-Source Weather) 3-hourly data to LPJ-GUESS forcing.

    MSWX provides:
      - Temp: air temperature (K)
      - P: precipitation (mm/3hr)
      - SWd: downward shortwave radiation (W/m2)
      - spechum: specific humidity (kg/kg)
      - Pres: surface pressure (Pa)

    UNIT CONVERSIONS:
      - Temperature: K -> deg C  (subtract 273.15)
      - Precipitation: mm/3hr -> mm/day  (sum 8 steps per day)
      - VPD: computed from specific humidity and pressure

    Parameters
    ----------
    input_dir : str
        MSWX data directory
    output_path : str
        Output CSV path
    lat, lon : float
        Site coordinates
    start_year, end_year : int
        Year range (inclusive)
    """
    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required for MSWX conversion. pip install netCDF4",
              file=sys.stderr)
        sys.exit(1)

    if pd is None:
        print("ERROR: pandas required. pip install pandas", file=sys.stderr)
        sys.exit(1)

    print(f"Converting MSWX data: {input_dir}")
    print(f"  Location: lat={lat}, lon={lon}")
    print(f"  Period: {start_year}-{end_year}")

    import glob as globmod

    rows = []
    for year in range(start_year, end_year + 1):
        print(f"  Processing MSWX year {year}...")

        var_data = {}
        for var_name, mswx_name in [("temp", "Temp"), ("swd", "SWd"),
                                     ("prec", "P"), ("shum", "spechum"),
                                     ("pres", "Pres")]:
            var_dir = os.path.join(input_dir, mswx_name)
            if not os.path.isdir(var_dir):
                var_dir = input_dir

            pattern = os.path.join(var_dir, f"**/*{year}*.nc")
            files = sorted(globmod.glob(pattern, recursive=True))
            if not files:
                pattern = os.path.join(var_dir, f"*{year}*.nc")
                files = sorted(globmod.glob(pattern))
            if not files:
                print(f"  WARNING: No MSWX file for {mswx_name}/{year}", file=sys.stderr)
                var_data[var_name] = None
                continue

            all_vals = []
            for fpath in files:
                ds = nc.Dataset(fpath, "r")
                lats = ds.variables["lat"][:]
                lons = ds.variables["lon"][:]
                ilat = int(np.argmin(np.abs(lats - lat)))
                ilon = int(np.argmin(np.abs(lons - lon)))

                data_vars = [v for v in ds.variables
                             if v not in ("lat", "lon", "time")]
                if data_vars:
                    vals = ds.variables[data_vars[0]][:, ilat, ilon]
                    all_vals.extend(vals.tolist())
                ds.close()

            var_data[var_name] = np.array(all_vals) if all_vals else None

        # Aggregate to daily (365-day year for MSWX standard)
        ndays = 365
        steps_per_day = 8

        for var_name in var_data:
            if var_data[var_name] is not None:
                expected = ndays * steps_per_day
                actual = len(var_data[var_name])
                if actual < expected:
                    var_data[var_name] = np.pad(
                        var_data[var_name],
                        (0, expected - actual),
                        mode="edge"
                    )
                var_data[var_name] = var_data[var_name][:expected]

        if var_data.get("temp") is None or var_data.get("swd") is None:
            print(f"  WARNING: Skipping year {year} (missing essential variables)",
                  file=sys.stderr)
            continue

        for doy in range(ndays):
            i0 = doy * steps_per_day
            i1 = i0 + steps_per_day
            date = datetime(year, 1, 1) + timedelta(days=doy)

            # Temperature: K -> C
            if var_data.get("temp") is not None:
                ta_c = float(np.mean(var_data["temp"][i0:i1])) - KELVIN_OFFSET
            else:
                ta_c = float("nan")

            # SW radiation: daily mean
            if var_data.get("swd") is not None:
                sw_in = max(0.0, float(np.mean(var_data["swd"][i0:i1])))
            else:
                sw_in = float("nan")

            # Precipitation: mm/3hr -> mm/day (sum over 8 steps)
            if var_data.get("prec") is not None:
                p_mmday = max(0.0, float(np.sum(var_data["prec"][i0:i1])))
            else:
                p_mmday = float("nan")

            # VPD from specific humidity and pressure
            if (var_data.get("shum") is not None and
                    var_data.get("pres") is not None and
                    not math.isnan(ta_c)):
                shum = float(np.mean(var_data["shum"][i0:i1]))
                pres = float(np.mean(var_data["pres"][i0:i1]))
                vpd_hpa = calc_vpd_from_spechum(ta_c, shum, pres)
            else:
                vpd_hpa = float("nan")

            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "year": year,
                "month": date.month,
                "SW_IN": round(sw_in, 4),
                "TA": round(ta_c, 4),
                "VPD": round(vpd_hpa, 4),
                "P": round(p_mmday, 4),
            })

    if not rows:
        print("ERROR: No data rows generated", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "year", "month",
                                                "SW_IN", "TA", "VPD", "P"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"MSWX forcing written: {output_path} ({len(rows)} rows)")
    return len(rows)


# ============================================================================
# Helpers
# ============================================================================

def _is_leap_year(year):
    """Check if a year is a leap year."""
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


# ============================================================================
# Main conversion dispatcher
# ============================================================================

def convert_forcing(source, input_path, output_path, lat=None, lon=None,
                    start_year=None, end_year=None, timestep="daily"):
    """
    Main entry point: validate inputs, convert, validate outputs.

    Parameters
    ----------
    source : str
        One of "fluxnet", "cmfd", "mswx"
    input_path : str
        Input file (FLUXNET CSV) or directory (CMFD/MSWX)
    output_path : str
        Output CSV path
    lat, lon : float or None
        Required for gridded sources
    start_year, end_year : int or None
        Required for gridded sources
    timestep : str
        "daily" or "monthly"

    Returns
    -------
    dict with status, n_rows, output_path, warnings
    """
    # --- Validate inputs ---
    errors = validate_inputs(source, input_path, output_path, lat, lon,
                             start_year, end_year, timestep)
    if errors:
        return {"status": "error", "errors": errors}

    # --- Convert ---
    n_rows = 0
    if source == "fluxnet":
        n_rows = convert_fluxnet(input_path, output_path, timestep)
    elif source == "cmfd":
        n_rows = convert_cmfd(input_path, output_path, lat, lon,
                              start_year, end_year)
    elif source == "mswx":
        n_rows = convert_mswx(input_path, output_path, lat, lon,
                              start_year, end_year)

    # --- Validate outputs ---
    output_ok = validate_outputs(output_path, expected_rows=n_rows)

    return {
        "status": "success" if output_ok else "warning",
        "n_rows": n_rows,
        "output_path": output_path,
    }


# ============================================================================
# CLI entry point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Convert meteorological forcing data to LPJ-GUESS format.\n"
            "Supports FLUXNET2015, CMFD, and MSWX as input sources."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # FLUXNET daily\n"
            "  python convert_forcing_to_lpjguess.py \\\n"
            "      --source fluxnet --input SITE_FULLSET_DD.csv --output forcing.csv\n\n"
            "  # CMFD gridded\n"
            "  python convert_forcing_to_lpjguess.py \\\n"
            "      --source cmfd --input /path/to/cmfd/ \\\n"
            "      --lat 40.48 --lon 116.97 \\\n"
            "      --start-year 2000 --end-year 2010 --output forcing.csv\n"
        ),
    )
    parser.add_argument("--source", required=True,
                        choices=["fluxnet", "cmfd", "mswx"],
                        help="Forcing data source type")
    parser.add_argument("--input", required=True,
                        help="Input file (FLUXNET CSV) or directory (CMFD/MSWX)")
    parser.add_argument("--output", required=True,
                        help="Output CSV file path")
    parser.add_argument("--lat", type=float, default=None,
                        help="Latitude (required for CMFD/MSWX)")
    parser.add_argument("--lon", type=float, default=None,
                        help="Longitude (required for CMFD/MSWX)")
    parser.add_argument("--start-year", type=int, default=None,
                        help="Start year (required for CMFD/MSWX)")
    parser.add_argument("--end-year", type=int, default=None,
                        help="End year (required for CMFD/MSWX)")
    parser.add_argument("--timestep", choices=["daily", "monthly"],
                        default="daily",
                        help="Temporal resolution (default: daily)")

    args = parser.parse_args()

    result = convert_forcing(
        source=args.source,
        input_path=args.input,
        output_path=args.output,
        lat=args.lat,
        lon=args.lon,
        start_year=args.start_year,
        end_year=args.end_year,
        timestep=args.timestep,
    )

    if result["status"] == "error":
        sys.exit(1)
    elif result["status"] == "warning":
        sys.exit(0)
    else:
        sys.exit(0)
