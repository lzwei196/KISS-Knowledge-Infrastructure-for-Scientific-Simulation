#!/usr/bin/env python3
"""parse_daisy_output.py — Parse Daisy .dlf output files into CSV and DataFrames.

Reads Daisy Log File (.dlf) format, extracts header metadata and tabular data,
and produces clean CSV files for analysis.

Usage:
    python parse_daisy_output.py \\
        --work-dir /path/to/simulation \\
        --output-dir /path/to/csv_output \\
        --files harvest.dlf field_water.dlf field_nitrogen.dlf
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(work_dir, files):
    """Validate that DLF files exist."""
    errors = []

    if not os.path.isdir(work_dir):
        errors.append(f"Work directory not found: {work_dir}")
        raise FileNotFoundError("\n  ".join(errors))

    found = []
    for f in files:
        fpath = os.path.join(work_dir, f) if not os.path.isabs(f) else f
        if os.path.isfile(fpath):
            found.append(fpath)
        else:
            print(f"WARNING: File not found, skipping: {f}")

    if not found:
        errors.append("No valid .dlf files found")
        raise FileNotFoundError("\n  ".join(errors))

    return found


def validate_outputs(results):
    """Validate parsed output data quality."""
    warnings = []

    for name, data in results.items():
        df = data.get("dataframe")
        if df is None or df.empty:
            warnings.append(f"{name}: empty DataFrame")
            continue

        # Check for all-NaN columns
        all_nan = [c for c in df.columns if df[c].isna().all()]
        if all_nan:
            warnings.append(f"{name}: all-NaN columns: {all_nan}")

        # Check row count
        if len(df) < 2:
            warnings.append(f"{name}: only {len(df)} rows — very short simulation?")

    for w in warnings:
        print(f"WARNING: {w}")

    return len(warnings) == 0


# ---------------------------------------------------------------------------
# DLF parser
# ---------------------------------------------------------------------------

def parse_dlf_header(filepath):
    """Parse the header section of a DLF file.

    Returns
    -------
    dict
        Header metadata: version, logfile, run time, parameters.
    int
        Line number where data section begins.
    """
    header = {}
    data_start = 0

    with open(filepath) as f:
        for i, line in enumerate(f):
            stripped = line.strip()

            # First line: dlf-0.0 -- Description
            if i == 0 and stripped.startswith("dlf-0.0"):
                header["description"] = stripped.split("--", 1)[-1].strip()
                continue

            # Metadata lines: KEY: value
            if ":" in stripped and not stripped.startswith("-"):
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                if key.upper() in ("VERSION", "LOGFILE", "RUN", "COLUMN",
                                    "SIMFILE", "SIM", "INTERVAL", "LOG",
                                    "CHEMICAL"):
                    header[key.lower()] = value
                continue

            # Separator line: dashes
            if stripped.startswith("----"):
                data_start = i + 1
                break

    return header, data_start


def parse_dlf_data(filepath, data_start):
    """Parse the data section of a DLF file.

    Parameters
    ----------
    filepath : str
        Path to .dlf file.
    data_start : int
        Line number where column names begin (after ---- separator).

    Returns
    -------
    pd.DataFrame
        Parsed data with proper column names and types.
    dict
        Column units mapping.
    """
    with open(filepath) as f:
        lines = f.readlines()

    if data_start >= len(lines):
        return pd.DataFrame(), {}

    # Column names line
    col_line = lines[data_start].strip()
    col_names = col_line.split("\t") if "\t" in col_line else col_line.split()

    # Units line (may or may not exist)
    units = {}
    data_body_start = data_start + 1
    if data_body_start < len(lines):
        unit_line = lines[data_body_start].strip()
        unit_parts = unit_line.split("\t") if "\t" in unit_line else unit_line.split()
        # Check if this is actually a unit line (contains typical unit strings)
        if any(u in unit_line.lower() for u in ["year", "month", "day", "mm", "kg",
                                                   "mg", "cm", "m^2", "ha", "/",
                                                   "w/m", "dgc"]):
            for name, unit in zip(col_names, unit_parts):
                units[name] = unit
            data_body_start += 1

    # Parse data lines
    data_rows = []
    for line in lines[data_body_start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split("\t") if "\t" in stripped else stripped.split()
        if len(parts) >= len(col_names):
            data_rows.append(parts[:len(col_names)])
        elif len(parts) > 0:
            # Pad with NaN
            padded = parts + [np.nan] * (len(col_names) - len(parts))
            data_rows.append(padded)

    if not data_rows:
        return pd.DataFrame(columns=col_names), units

    df = pd.DataFrame(data_rows, columns=col_names)

    # Convert numeric columns
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass  # Keep as string

    # Create datetime column if year/month/day present
    if all(c in df.columns for c in ["year", "month", "mday"]):
        try:
            hour_col = df["hour"] if "hour" in df.columns else 0
            df["datetime"] = pd.to_datetime(
                df[["year", "month"]].assign(day=df["mday"]),
                errors="coerce"
            )
        except Exception:
            pass

    return df, units


def parse_dlf(filepath):
    """Parse a complete DLF file.

    Returns
    -------
    dict
        header: metadata
        dataframe: pd.DataFrame
        units: column→unit mapping
        filepath: source path
    """
    header, data_start = parse_dlf_header(filepath)
    df, units = parse_dlf_data(filepath, data_start)

    return {
        "header": header,
        "dataframe": df,
        "units": units,
        "filepath": filepath,
    }


# ---------------------------------------------------------------------------
# Harvest summary extractor
# ---------------------------------------------------------------------------

def extract_harvest_summary(harvest_result):
    """Extract key harvest metrics from parsed harvest.dlf.

    Returns
    -------
    list of dict
        One entry per harvest event with crop, yield, N uptake, etc.
    """
    df = harvest_result["dataframe"]
    if df.empty:
        return []

    events = []
    for _, row in df.iterrows():
        event = {}

        if "crop" in row:
            event["crop"] = row["crop"]
        if "year" in row:
            event["year"] = int(row["year"]) if pd.notna(row["year"]) else None
        if "month" in row:
            event["month"] = int(row["month"]) if pd.notna(row["month"]) else None

        # Yield components (Mg DM/ha)
        for comp in ["stem_DM", "leaf_DM", "dead_DM", "sorg_DM"]:
            if comp in row and pd.notna(row[comp]):
                event[comp] = float(row[comp])

        # Total yield
        dm_components = [event.get(c, 0) for c in ["stem_DM", "leaf_DM", "dead_DM", "sorg_DM"]]
        event["total_DM"] = sum(dm_components)

        # N components (kg N/ha)
        for comp in ["stem_N", "leaf_N", "dead_N", "sorg_N"]:
            if comp in row and pd.notna(row[comp]):
                event[comp] = float(row[comp])

        n_components = [event.get(c, 0) for c in ["stem_N", "leaf_N", "dead_N", "sorg_N"]]
        event["total_N"] = sum(n_components)

        # Stress and efficiency. The harvest.dlf column headers emitted by the
        # log-std.dai 'harvest' log use the short names WStress/NStress/WP_ET/HI,
        # so map those onto the documented long-form keys (the SKILL.md output
        # table calls them water_stress_days / harvest_index etc.).
        alias = {
            "water_stress_days": ["water_stress_days", "WStress"],
            "nitrogen_stress_days": ["nitrogen_stress_days", "NStress"],
            "water_productivity": ["water_productivity", "WP_ET"],
            "harvest_index": ["harvest_index", "HI"],
        }
        for metric, candidates in alias.items():
            for col in candidates:
                if col in row and pd.notna(row[col]):
                    event[metric] = float(row[col])
                    break

        events.append(event)

    return events


# ---------------------------------------------------------------------------
# Water balance extractor
# ---------------------------------------------------------------------------

def extract_water_balance(water_result):
    """Extract water balance summary from field_water.dlf.

    Returns
    -------
    dict
        Annual or total water balance components.
    """
    df = water_result["dataframe"]
    if df.empty:
        return {}

    # Sum flux columns
    flux_cols = [c for c in df.columns if c not in
                 ["year", "month", "mday", "hour", "datetime"]]

    balance = {}
    for col in flux_cols:
        if df[col].dtype in (np.float64, np.int64, float, int):
            balance[col] = {
                "total": float(df[col].sum()),
                "mean": float(df[col].mean()),
                "unit": water_result["units"].get(col, "unknown"),
            }

    return balance


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process(work_dir, output_dir, files=None):
    """Parse all DLF files in a simulation directory.

    Parameters
    ----------
    work_dir : str
        Directory containing .dlf files.
    output_dir : str
        Directory for CSV output files.
    files : list of str, optional
        Specific files to parse. If None, parse all .dlf files.

    Returns
    -------
    dict
        Parsed results for each file.
    """
    # Step 1: Find files
    if files is None:
        files = [f.name for f in Path(work_dir).glob("*.dlf")]

    validated_files = validate_inputs(work_dir, files)

    os.makedirs(output_dir, exist_ok=True)

    # Step 2: Parse each file
    results = {}
    for fpath in validated_files:
        fname = os.path.basename(fpath)
        print(f"Parsing: {fname}")

        parsed = parse_dlf(fpath)
        results[fname] = parsed

        # Write CSV
        df = parsed["dataframe"]
        if not df.empty:
            csv_name = fname.replace(".dlf", ".csv")
            csv_path = os.path.join(output_dir, csv_name)
            df.to_csv(csv_path, index=False)
            print(f"  → {csv_path} ({len(df)} rows, {len(df.columns)} columns)")

    # Step 3: Validate outputs
    validate_outputs(results)

    # Step 4: Extract summaries
    summaries = {}

    if "harvest.dlf" in results:
        summaries["harvest"] = extract_harvest_summary(results["harvest.dlf"])
        if summaries["harvest"]:
            print("\n=== Harvest Summary ===")
            for h in summaries["harvest"]:
                crop = h.get("crop", "?")
                total_dm = h.get("total_DM", 0)
                sorg_dm = h.get("sorg_DM", 0)
                total_n = h.get("total_N", 0)
                hi = h.get("harvest_index", 0)
                print(f"  {crop}: total={total_dm:.2f} Mg DM/ha, "
                      f"grain={sorg_dm:.2f} Mg DM/ha, "
                      f"N={total_n:.1f} kg N/ha, HI={hi:.2f}")

    if "field_water.dlf" in results:
        summaries["water_balance"] = extract_water_balance(results["field_water.dlf"])

    # Write summary JSON
    summary_path = os.path.join(output_dir, "summary.json")

    # Convert for JSON serialization
    def make_serializable(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    with open(summary_path, "w") as f:
        json.dump(summaries, f, indent=2, default=make_serializable)
    print(f"\nSummary written to {summary_path}")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse Daisy .dlf output files to CSV")
    parser.add_argument("--work-dir", required=True,
                        help="Directory containing .dlf files")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory for CSV files (default: work-dir/csv)")
    parser.add_argument("--files", nargs="*", default=None,
                        help="Specific .dlf files to parse (default: all)")

    args = parser.parse_args()

    output_dir = args.output_dir or os.path.join(args.work_dir, "csv")

    process(
        work_dir=args.work_dir,
        output_dir=output_dir,
        files=args.files,
    )


if __name__ == "__main__":
    main()
