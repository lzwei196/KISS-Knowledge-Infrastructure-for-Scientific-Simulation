#!/usr/bin/env python3
"""
convert_forcing_to_wasp.py -- Convert lake observation data to WASP forcing format.

Reads WQP (Water Quality Portal) lake observation CSV files and EPA NLA
(National Lakes Assessment) profile data, cleans and aligns them temporally,
and outputs a unified JSON forcing file for the WASP water quality model.

Handles multiple lakes: DeGray, Jordan, Erie, Mead.

WASP expects:
  - Temperature:     deg C (daily or event-based)
  - Dissolved oxygen: mg/L
  - Chlorophyll-a:   ug/L
  - Depth:           m
  - Day of year:     integer 1-366

CRITICAL UNIT TRAPS:
  - WQP temperature may be in Fahrenheit. If mean T > 50, likely F (dt_001).
  - WQP DO may be in % saturation instead of mg/L. Values > 20 are suspect (dt_004).
  - WQP depth may be in feet. Check MeasureUnitCode column (dt_005).
  - Chlorophyll-a may be in mg/L instead of ug/L. If median < 0.1, likely mg/L (dt_007).
  - NLA profile depth column varies by survey year (DEPTH, DEPTH_M, etc.).
  - Negative or zero DO values are instrument artifacts -- filter them.

Usage:
    python convert_forcing_to_wasp.py \\
        --wqp-dir /path/to/wqp/Lake_Erie_Central \\
        --output forcing.json

    python convert_forcing_to_wasp.py \\
        --wqp-dir /path/to/wqp/Lake_Erie_Central \\
        --profile-csv /path/to/profiles/erie_profiles.csv \\
        --nla-csv /path/to/nla2017_profile.csv \\
        --nla-chem-csv /path/to/nla2017_water_chem.csv \\
        --temp-unit F --depth-unit ft \\
        --output forcing.json

    python convert_forcing_to_wasp.py \\
        --wqp-dir /path/to/wqp/Jordan_Lake \\
        --min-year 2005 --max-year 2020 \\
        --output forcing.json
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None


# ---- Unit conversion constants ------------------------------------------------
F_TO_C_OFFSET = -32.0
F_TO_C_SCALE = 5.0 / 9.0
K_TO_C = -273.15
FT_TO_M = 0.3048
CM_TO_M = 0.01
UG_L_PER_MG_L = 1000.0


# ---- Physical plausibility bounds --------------------------------------------
TEMP_RANGE_C = (-2.0, 40.0)        # deg C, surface lake water
DO_RANGE_MG_L = (0.0, 20.0)        # mg/L, physically possible
CHLA_RANGE_UG_L = (0.0, 500.0)     # ug/L, extreme bloom cap
DEPTH_RANGE_M = (0.0, 400.0)       # m, deepest US lake ~594m but 400 is safe cap
DOY_RANGE = (1, 366)

# WQP column name conventions
WQP_DATE_COL = "ActivityStartDate"
WQP_VALUE_COL = "ResultMeasureValue"
WQP_DEPTH_COLS = [
    "ActivityDepthHeightMeasure/MeasureValue",
    "ResultDepthHeightMeasure/MeasureValue",
]
WQP_CHAR_COL = "CharacteristicName"
WQP_UNIT_COL = "ResultMeasure/MeasureUnitCode"
WQP_DEPTH_UNIT_COL = "ActivityDepthHeightMeasure/MeasureUnitCode"
WQP_STATUS_COL = "ResultStatusIdentifier"


def validate_inputs(args):
    """Validate all inputs before processing. Returns list of errors."""
    errors = []

    if args.wqp_dir and not os.path.isdir(args.wqp_dir):
        errors.append(f"WQP directory does not exist: {args.wqp_dir}")

    if args.profile_csv and not os.path.isfile(args.profile_csv):
        errors.append(f"Profile CSV does not exist: {args.profile_csv}")

    if args.nla_csv and not os.path.isfile(args.nla_csv):
        errors.append(f"NLA CSV does not exist: {args.nla_csv}")

    if args.nla_chem_csv and not os.path.isfile(args.nla_chem_csv):
        errors.append(f"NLA chemistry CSV does not exist: {args.nla_chem_csv}")

    if not args.wqp_dir and not args.profile_csv and not args.nla_csv:
        errors.append(
            "At least one data source required: --wqp-dir, --profile-csv, or --nla-csv")

    valid_temp_units = ["C", "F", "K"]
    if args.temp_unit not in valid_temp_units:
        errors.append(
            f"Invalid temp unit '{args.temp_unit}'. Must be one of {valid_temp_units}")

    valid_depth_units = ["m", "ft", "cm"]
    if args.depth_unit not in valid_depth_units:
        errors.append(
            f"Invalid depth unit '{args.depth_unit}'. Must be one of {valid_depth_units}")

    if args.min_year and args.max_year and args.min_year > args.max_year:
        errors.append(
            f"min_year ({args.min_year}) > max_year ({args.max_year})")

    if pd is None:
        errors.append("pandas is required but not installed. Run: pip install pandas")

    return errors


def convert_temperature(values, from_unit):
    """Convert temperature to deg C.

    CRITICAL: WQP temperature in Fahrenheit produces T_mean ~60 in a
    temperate lake. The seasonal model will fit but produce wrong DO
    saturation values (dt_001).
    """
    if from_unit == "C":
        return values
    elif from_unit == "F":
        return (values + F_TO_C_OFFSET) * F_TO_C_SCALE
    elif from_unit == "K":
        return values + K_TO_C
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")


def convert_depth(values, from_unit):
    """Convert depth to meters.

    CRITICAL: Using feet as meters makes thermocline appear 3x deeper
    than reality, collapsing the temperature profile (dt_005).
    """
    if from_unit == "m":
        return values
    elif from_unit == "ft":
        return values * FT_TO_M
    elif from_unit == "cm":
        return values * CM_TO_M
    else:
        raise ValueError(f"Unknown depth unit: {from_unit}")


def detect_temp_unit(values, log):
    """Auto-detect temperature unit from value statistics.

    Returns 'C', 'F', or 'K' with confidence note.
    """
    median_val = float(np.nanmedian(values))
    if median_val > 200:
        log.append(f"[AUTO-DETECT] Median temp = {median_val:.1f}, likely Kelvin")
        return "K"
    elif median_val > 50:
        log.append(f"[AUTO-DETECT] Median temp = {median_val:.1f}, likely Fahrenheit")
        return "F"
    else:
        log.append(f"[AUTO-DETECT] Median temp = {median_val:.1f}, assuming Celsius")
        return "C"


def detect_depth_unit(values, log):
    """Auto-detect depth unit from value statistics."""
    max_val = float(np.nanmax(values))
    if max_val > 300:
        log.append(
            f"[AUTO-DETECT] Max depth = {max_val:.1f}, likely feet or cm")
        return "ft"  # ambiguous, but feet more common in US WQP data
    return "m"


def load_wqp_variable(csv_path, log):
    """Load a single-variable WQP CSV file.

    WQP exports one variable per CSV in the lake-specific directories.
    Returns DataFrame with _date, _value, _depth columns.
    """
    df = pd.read_csv(csv_path, low_memory=False)
    log.append(f"  Loaded {csv_path}: {len(df)} rows")

    # Parse date
    df["_date"] = pd.to_datetime(df.get(WQP_DATE_COL), errors="coerce")

    # Parse value
    df["_value"] = pd.to_numeric(df.get(WQP_VALUE_COL), errors="coerce")

    # Parse depth from multiple candidate columns
    df["_depth"] = np.nan
    for dc in WQP_DEPTH_COLS:
        if dc in df.columns:
            depth_vals = pd.to_numeric(df[dc], errors="coerce")
            # Fill in where _depth is still NaN
            mask = df["_depth"].isna() & depth_vals.notna()
            df.loc[mask, "_depth"] = depth_vals[mask]

    # Quality filtering: exclude rejected/preliminary data
    if WQP_STATUS_COL in df.columns:
        n_before = len(df)
        reject_mask = df[WQP_STATUS_COL].str.lower().isin(
            ["rejected", "preliminary"]).fillna(False)
        df = df[~reject_mask]
        n_removed = n_before - len(df)
        if n_removed > 0:
            log.append(f"    Removed {n_removed} rejected/preliminary records")

    return df


def load_profile_csv(csv_path, log):
    """Load a WQP discrete_profiles CSV (multi-variable with CharacteristicName).

    Returns DataFrame with _date, _value, _depth, _variable columns.
    """
    df = pd.read_csv(csv_path, low_memory=False)
    log.append(f"  Loaded profile: {csv_path}: {len(df)} rows")

    df["_date"] = pd.to_datetime(df.get(WQP_DATE_COL), errors="coerce")
    df["_value"] = pd.to_numeric(df.get(WQP_VALUE_COL), errors="coerce")

    # Depth
    df["_depth"] = np.nan
    for dc in WQP_DEPTH_COLS:
        if dc in df.columns:
            depth_vals = pd.to_numeric(df[dc], errors="coerce")
            mask = df["_depth"].isna() & depth_vals.notna()
            df.loc[mask, "_depth"] = depth_vals[mask]

    # Variable classification from CharacteristicName
    df["_variable"] = "unknown"
    if WQP_CHAR_COL in df.columns:
        char = df[WQP_CHAR_COL].str.lower().fillna("")
        df.loc[char.str.contains("temperature"), "_variable"] = "temperature"
        df.loc[char.str.contains("dissolved oxygen|^do$|oxygen, dissolved"),
               "_variable"] = "do"
        df.loc[char.str.contains("chlorophyll"), "_variable"] = "chla"
        df.loc[char.str.contains("phosphorus"), "_variable"] = "tp"
        df.loc[char.str.contains("secchi"), "_variable"] = "secchi"

    return df


def load_nla_profiles(nla_csv, log):
    """Load NLA (National Lakes Assessment) profile data.

    NLA profiles have columns like DEPTH, TEMPERATURE, DO_mgl, SITE_ID.
    Column names vary by survey year.
    """
    df = pd.read_csv(nla_csv, low_memory=False, encoding="latin-1")
    log.append(f"  Loaded NLA profile: {nla_csv}: {len(df)} rows")
    log.append(f"    Columns: {list(df.columns)[:15]}")

    # Find depth column
    depth_col = None
    for c in df.columns:
        if c.upper() in ("DEPTH", "DEPTH_M", "SAMPLE_DEPTH"):
            depth_col = c
            break
    if depth_col is None:
        for c in df.columns:
            if "DEPTH" in c.upper():
                depth_col = c
                break

    # Find temperature column
    temp_col = None
    for c in df.columns:
        if c.upper() in ("TEMPERATURE", "TEMP_C", "TEMPERATURE_C", "TEMP"):
            temp_col = c
            break
    if temp_col is None:
        for c in df.columns:
            if "TEMP" in c.upper():
                temp_col = c
                break

    # Find DO column
    do_col = None
    for c in df.columns:
        cl = c.upper()
        if cl in ("DO_MGL", "DISSOLVED_OXYGEN", "DO", "OXYGEN"):
            do_col = c
            break
    if do_col is None:
        for c in df.columns:
            cl = c.upper()
            if ("DO_" in cl or cl.startswith("DO")) and "DOC" not in cl:
                do_col = c
                break

    log.append(f"    depth={depth_col}, temp={temp_col}, DO={do_col}")

    result = pd.DataFrame()
    if depth_col:
        result["_depth"] = pd.to_numeric(df[depth_col], errors="coerce")
    if temp_col:
        result["_temp"] = pd.to_numeric(df[temp_col], errors="coerce")
    if do_col:
        result["_do"] = pd.to_numeric(df[do_col], errors="coerce")
    if "SITE_ID" in df.columns:
        result["_site_id"] = df["SITE_ID"]
    if "VISIT_NO" in df.columns:
        result["_visit"] = df["VISIT_NO"]

    return result


def load_nla_chemistry(nla_chem_csv, log):
    """Load NLA water chemistry data for TSI computation.

    Returns dict with Chl-a, TP, Secchi arrays (across all lakes).
    """
    df = pd.read_csv(nla_chem_csv, low_memory=False, encoding="latin-1")
    log.append(f"  Loaded NLA chemistry: {nla_chem_csv}: {len(df)} rows")

    result = {"chla": None, "tp": None, "secchi": None}

    if "ANALYTE" in df.columns and "RESULT" in df.columns:
        # Long format (ANALYTE/RESULT columns)
        for analyte_name, key in [("CHLA", "chla"), ("PTL", "tp"),
                                   ("SECCHI", "secchi")]:
            mask = df["ANALYTE"] == analyte_name
            if mask.any():
                vals = pd.to_numeric(df.loc[mask, "RESULT"], errors="coerce")
                vals = vals.dropna()
                vals = vals[vals > 0]
                if len(vals) > 0:
                    result[key] = vals.values
                    log.append(f"    NLA {analyte_name}: {len(vals)} values, "
                               f"median={float(np.median(vals)):.2f}")
    else:
        # Wide format (column per variable)
        for col_pattern, key in [("CHL", "chla"), ("PTL", "tp"),
                                  ("SECCHI", "secchi")]:
            for c in df.columns:
                if col_pattern in c.upper() and "CHLORIDE" not in c.upper():
                    vals = pd.to_numeric(df[c], errors="coerce").dropna()
                    vals = vals[vals > 0]
                    if len(vals) > 0:
                        result[key] = vals.values
                        log.append(f"    NLA {c}: {len(vals)} values")
                    break

    return result


def discover_wqp_files(wqp_dir, log):
    """Discover WQP CSV files in a lake directory.

    Returns dict mapping variable keyword to file path.
    """
    files = {}
    if not os.path.isdir(wqp_dir):
        return files

    for fname in sorted(os.listdir(wqp_dir)):
        if not fname.endswith(".csv"):
            continue
        fpath = os.path.join(wqp_dir, fname)
        stem = os.path.splitext(fname)[0].lower()

        # Count rows for info
        try:
            with open(fpath) as f:
                n_rows = sum(1 for _ in f) - 1
        except Exception:
            n_rows = -1

        # Classify by filename
        if "temperature" in stem or "temp" in stem:
            files["temperature"] = {"path": fpath, "rows": n_rows}
        elif "dissolved_oxygen" in stem or "do" == stem.split("_")[-1]:
            files["do"] = {"path": fpath, "rows": n_rows}
        elif "chlorophyll" in stem or "chla" in stem:
            files["chla"] = {"path": fpath, "rows": n_rows}
        elif "phosphorus" in stem:
            files["tp"] = {"path": fpath, "rows": n_rows}
        elif "secchi" in stem:
            files["secchi"] = {"path": fpath, "rows": n_rows}
        elif "profile" in stem:
            files["profile"] = {"path": fpath, "rows": n_rows}

    for var, info in files.items():
        log.append(f"  Found: {var} ({info['rows']} rows) -> {info['path']}")

    return files


def clean_and_align(df, var_name, temp_unit, depth_unit,
                    min_year, max_year, log):
    """Clean a WQP variable DataFrame: filter, convert units, add DOY.

    Returns cleaned DataFrame with _date, _value, _depth, _doy columns.
    """
    # Drop rows without date or value
    clean = df.dropna(subset=["_value", "_date"]).copy()

    # Year filter
    if min_year:
        clean = clean[clean["_date"].dt.year >= min_year]
    if max_year:
        clean = clean[clean["_date"].dt.year <= max_year]

    if len(clean) == 0:
        log.append(f"    {var_name}: no data after year filter")
        return clean

    # Unit conversion for temperature
    if var_name == "temperature":
        # Auto-detect unit if needed
        detected_unit = detect_temp_unit(clean["_value"].values, log)
        unit = temp_unit if temp_unit != "auto" else detected_unit
        clean["_value"] = convert_temperature(clean["_value"].values, unit)

        # Physical range filter
        mask = (clean["_value"] >= TEMP_RANGE_C[0]) & \
               (clean["_value"] <= TEMP_RANGE_C[1])
        n_removed = (~mask).sum()
        clean = clean[mask]
        if n_removed > 0:
            log.append(f"    {var_name}: removed {n_removed} out-of-range values")

    elif var_name == "do":
        # Check for percent saturation
        median_do = float(clean["_value"].median())
        if median_do > 20:
            log.append(
                f"    [WARN] {var_name}: median = {median_do:.1f}, "
                "possibly % saturation not mg/L (dt_004)")

        mask = (clean["_value"] >= DO_RANGE_MG_L[0]) & \
               (clean["_value"] <= DO_RANGE_MG_L[1])
        clean = clean[mask]

    elif var_name == "chla":
        # Check for mg/L vs ug/L
        median_chla = float(clean["_value"].median())
        if 0 < median_chla < 0.1:
            log.append(
                f"    [WARN] {var_name}: median = {median_chla:.4f}, "
                "possibly mg/L not ug/L -- multiplying by 1000 (dt_007)")
            clean["_value"] = clean["_value"] * UG_L_PER_MG_L

        mask = (clean["_value"] >= CHLA_RANGE_UG_L[0]) & \
               (clean["_value"] <= CHLA_RANGE_UG_L[1])
        clean = clean[mask]

    # Depth conversion
    if "_depth" in clean.columns:
        depth_vals = clean["_depth"].dropna()
        if len(depth_vals) > 0:
            detected_depth_unit = detect_depth_unit(depth_vals.values, log)
            d_unit = depth_unit if depth_unit != "auto" else detected_depth_unit
            clean.loc[clean["_depth"].notna(), "_depth"] = convert_depth(
                clean.loc[clean["_depth"].notna(), "_depth"].values, d_unit)

    # Add day of year
    clean["_doy"] = clean["_date"].dt.dayofyear

    # Sort by date
    clean = clean.sort_values("_date").reset_index(drop=True)

    n_valid = len(clean)
    val_range = (float(clean["_value"].min()), float(clean["_value"].max()))
    log.append(
        f"    {var_name}: {n_valid} valid records, "
        f"range=[{val_range[0]:.2f}, {val_range[1]:.2f}]")

    return clean


def process(args):
    """Main processing: load all data sources, clean, align, output JSON."""
    log = []
    log.append("WASP Forcing Data Conversion")
    log.append("=" * 50)

    output = {
        "temperature": None,
        "do": None,
        "chla": None,
        "tp": None,
        "secchi": None,
        "profiles": None,
        "nla_profiles": None,
        "nla_chemistry": None,
        "stats": {},
    }

    # --- 1. Discover and load WQP data ---
    if args.wqp_dir:
        log.append(f"\n[1] Discovering WQP data in {args.wqp_dir}")
        wqp_files = discover_wqp_files(args.wqp_dir, log)

        for var_key, var_info in wqp_files.items():
            if var_key == "profile":
                continue  # handled separately

            log.append(f"\n  Processing {var_key} ...")
            df = load_wqp_variable(var_info["path"], log)
            df = clean_and_align(df, var_key, args.temp_unit, args.depth_unit,
                                 args.min_year, args.max_year, log)

            if len(df) > 0:
                records = []
                for _, row in df.iterrows():
                    rec = {
                        "date": row["_date"].strftime("%Y-%m-%d"),
                        "value": round(float(row["_value"]), 4),
                        "doy": int(row["_doy"]),
                    }
                    if pd.notna(row.get("_depth")):
                        rec["depth_m"] = round(float(row["_depth"]), 2)
                    records.append(rec)

                output[var_key] = records
                output["stats"][var_key] = {
                    "n_records": len(records),
                    "mean": round(float(df["_value"].mean()), 4),
                    "std": round(float(df["_value"].std()), 4),
                    "min": round(float(df["_value"].min()), 4),
                    "max": round(float(df["_value"].max()), 4),
                    "date_range": [
                        df["_date"].min().strftime("%Y-%m-%d"),
                        df["_date"].max().strftime("%Y-%m-%d"),
                    ],
                    "n_with_depth": int(df["_depth"].notna().sum()),
                }

        # Load profile file if found
        if "profile" in wqp_files:
            log.append("\n  Loading WQP profile data ...")
            prof_df = load_profile_csv(wqp_files["profile"]["path"], log)

            profile_records = []
            for var_type in ["temperature", "do"]:
                var_df = prof_df[prof_df["_variable"] == var_type].copy()
                var_df = var_df.dropna(subset=["_depth", "_value"])
                if var_type == "temperature":
                    var_df = var_df[
                        (var_df["_value"] >= TEMP_RANGE_C[0]) &
                        (var_df["_value"] <= TEMP_RANGE_C[1]) &
                        (var_df["_depth"] >= 0)]
                elif var_type == "do":
                    var_df = var_df[
                        (var_df["_value"] >= DO_RANGE_MG_L[0]) &
                        (var_df["_value"] <= DO_RANGE_MG_L[1]) &
                        (var_df["_depth"] >= 0)]

                for _, row in var_df.iterrows():
                    rec = {
                        "variable": var_type,
                        "depth_m": round(float(row["_depth"]), 2),
                        "value": round(float(row["_value"]), 4),
                    }
                    if pd.notna(row.get("_date")):
                        rec["date"] = row["_date"].strftime("%Y-%m-%d")
                        rec["doy"] = int(row["_date"].dayofyear)
                    profile_records.append(rec)

            if profile_records:
                output["profiles"] = profile_records
                log.append(f"    Profile records: {len(profile_records)}")

    # --- 2. Load NLA profile data ---
    if args.nla_csv:
        log.append(f"\n[2] Loading NLA profile data")
        nla_df = load_nla_profiles(args.nla_csv, log)

        if len(nla_df) > 0 and "_depth" in nla_df.columns:
            # Find best deep lake site
            if "_site_id" in nla_df.columns:
                valid = nla_df.dropna(subset=["_depth"])
                if "_temp" in valid.columns:
                    valid = valid.dropna(subset=["_temp"])
                site_stats = valid.groupby("_site_id").agg(
                    n=("_depth", "count"),
                    max_d=("_depth", "max")).reset_index()
                site_stats["score"] = site_stats["n"] * site_stats["max_d"]
                site_stats = site_stats.sort_values("score", ascending=False)

                if len(site_stats) > 0:
                    best_site = site_stats.iloc[0]["_site_id"]
                    site_data = nla_df[nla_df["_site_id"] == best_site]
                    log.append(
                        f"    Best NLA site: {best_site} "
                        f"(n={len(site_data)}, max_depth="
                        f"{site_data['_depth'].max():.0f}m)")

                    nla_records = []
                    for _, row in site_data.iterrows():
                        rec = {"depth_m": round(float(row["_depth"]), 2)}
                        if "_temp" in row and pd.notna(row["_temp"]):
                            rec["temperature_c"] = round(float(row["_temp"]), 2)
                        if "_do" in row and pd.notna(row["_do"]):
                            rec["do_mg_l"] = round(float(row["_do"]), 2)
                        nla_records.append(rec)

                    output["nla_profiles"] = {
                        "site_id": str(best_site),
                        "records": nla_records,
                    }

    # --- 3. Load NLA chemistry ---
    if args.nla_chem_csv:
        log.append(f"\n[3] Loading NLA chemistry data")
        nla_chem = load_nla_chemistry(args.nla_chem_csv, log)

        chem_output = {}
        for key in ["chla", "tp", "secchi"]:
            if nla_chem[key] is not None:
                vals = nla_chem[key]
                chem_output[key] = {
                    "n": len(vals),
                    "median": round(float(np.median(vals)), 4),
                    "mean": round(float(np.mean(vals)), 4),
                    "p10": round(float(np.percentile(vals, 10)), 4),
                    "p90": round(float(np.percentile(vals, 90)), 4),
                }
        if chem_output:
            output["nla_chemistry"] = chem_output

    return output, log


def validate_outputs(output, log):
    """Check converted outputs for physical plausibility.

    Returns True if no critical errors, False otherwise.
    """
    critical = False

    for var_key in ["temperature", "do", "chla"]:
        if output.get(var_key) is None:
            continue

        stats = output.get("stats", {}).get(var_key, {})
        mean_val = stats.get("mean", 0)

        if var_key == "temperature":
            if mean_val > 50:
                log.append(
                    f"[CRITICAL] Mean temperature = {mean_val:.1f} C -- "
                    "likely still in Fahrenheit (dt_001)")
                critical = True
            elif mean_val > 35:
                log.append(
                    f"[WARN] Mean temperature = {mean_val:.1f} C -- "
                    "unusually high for a lake")

        elif var_key == "do":
            if mean_val > 20:
                log.append(
                    f"[CRITICAL] Mean DO = {mean_val:.1f} -- "
                    "likely % saturation not mg/L (dt_004)")
                critical = True
            elif mean_val < 1:
                log.append(
                    f"[WARN] Mean DO = {mean_val:.2f} mg/L -- "
                    "unusually low, check data quality")

        elif var_key == "chla":
            if stats.get("max", 0) > 500:
                log.append(
                    f"[WARN] Max Chl-a = {stats['max']:.1f} ug/L -- "
                    "extreme value, verify units")

    # Cross-check: if temperature data exists, verify seasonal pattern
    if output.get("temperature"):
        records = output["temperature"]
        doy_vals = np.array([r["doy"] for r in records])
        temp_vals = np.array([r["value"] for r in records])

        # Summer (DOY 150-250) should be warmer than winter (DOY 1-60, 320-365)
        summer_mask = (doy_vals >= 150) & (doy_vals <= 250)
        winter_mask = (doy_vals <= 60) | (doy_vals >= 320)

        if summer_mask.sum() > 10 and winter_mask.sum() > 10:
            t_summer = np.mean(temp_vals[summer_mask])
            t_winter = np.mean(temp_vals[winter_mask])
            if t_summer < t_winter:
                log.append(
                    "[WARN] Summer temps lower than winter -- "
                    "possible Southern Hemisphere lake or data issue")

    log.append(f"\nOutput validation {'PASSED' if not critical else 'FAILED'}")
    return not critical


def main():
    parser = argparse.ArgumentParser(
        description="Convert WQP/NLA lake data to WASP forcing format")

    # Data sources
    parser.add_argument("--wqp-dir", default=None,
                        help="WQP lake directory containing per-variable CSVs")
    parser.add_argument("--profile-csv", default=None,
                        help="WQP discrete profile CSV (multi-variable)")
    parser.add_argument("--nla-csv", default=None,
                        help="NLA profile CSV (depth/temp/DO)")
    parser.add_argument("--nla-chem-csv", default=None,
                        help="NLA water chemistry CSV (Chl-a, TP, Secchi)")

    # Unit overrides
    parser.add_argument("--temp-unit", default="C",
                        choices=["C", "F", "K", "auto"],
                        help="Source temperature unit (default: C, auto=detect)")
    parser.add_argument("--depth-unit", default="m",
                        choices=["m", "ft", "cm", "auto"],
                        help="Source depth unit (default: m, auto=detect)")

    # Temporal filtering
    parser.add_argument("--min-year", type=int, default=None,
                        help="Minimum year to include")
    parser.add_argument("--max-year", type=int, default=None,
                        help="Maximum year to include")

    # Output
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    args = parser.parse_args()

    # Step 1: validate inputs
    errors = validate_inputs(args)
    if errors:
        result = {"status": "error", "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Step 2: process
    output, log = process(args)

    # Step 3: validate outputs
    outputs_ok = validate_outputs(output, log)

    # Step 4: build result
    result = {
        "status": "success" if outputs_ok else "warning",
        "model": "WASP",
        "output": output,
        "log": log,
    }

    # Step 5: write output
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    # Print summary
    if result["status"] == "error":
        print(json.dumps(result, indent=2))
        sys.exit(1)
    else:
        for line in log:
            print(line)
        print(f"\nOutput written to {args.output}")


if __name__ == "__main__":
    main()
