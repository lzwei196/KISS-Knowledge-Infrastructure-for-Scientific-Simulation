#!/usr/bin/env python3
"""
Parse EPIC output files (ACY, DGN, etc.) to structured CSV/DataFrame.

Pipeline: locate output files → parse fixed-width → compute derived vars → export
Pattern:  validate inputs → process → validate outputs

Output types handled:
  - ACY: Annual Crop Yield (yearly yield, biomass, LAI)
  - DGN: Daily General Output (daily biomass, soil water, N status)
  - ACM: Annual Carbon/Nitrogen Mass
  - DHS: Daily Hydrology Summary
"""

import os
import sys
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------------------------
# Output file specifications
# ---------------------------------------------------------------------------
# All EPIC output files: skip first 10 rows, whitespace-delimited, header at row 11
SKIP_ROWS = 10


def validate_inputs(file_path: str, file_type: str) -> list:
    """Validate that output file exists and has content."""
    errors = []

    if not os.path.exists(file_path):
        errors.append(f"ERROR: Output file not found: {file_path}")
        return errors

    if os.path.getsize(file_path) == 0:
        errors.append(f"ERROR: Output file is empty: {file_path}")
        return errors

    # Check minimum line count (header + at least 1 data row)
    with open(file_path, "r") as f:
        lines = f.readlines()
    if len(lines) < SKIP_ROWS + 2:
        errors.append(
            f"ERROR: Output file has only {len(lines)} lines "
            f"(need at least {SKIP_ROWS + 2})"
        )

    return errors


def parse_acy(file_path: str) -> pd.DataFrame:
    """
    Parse EPIC ACY (Annual Crop Yield) file.

    Returns DataFrame with columns: YR, CPNM (crop name), and all yield metrics.
    Key variables:
      YLDG: Grain yield (t/ha)
      YLDF: Forage yield (t/ha)
      BIOM: Total biomass (t/ha)
      YLN:  Yield N content (kg/ha)
      YLP:  Yield P content (kg/ha)
      LAI:  Peak LAI
      WS:   Water stress days
      NS:   Nitrogen stress days
      TS:   Temperature stress days
    """
    df = pd.read_csv(file_path, sep=r"\s+", skiprows=SKIP_ROWS,
                     encoding="utf-8", encoding_errors="replace")

    # Clean column names
    df.columns = [c.strip() for c in df.columns]

    # Ensure year column
    if "YR" in df.columns:
        df["YR"] = df["YR"].astype(int)

    return df


def parse_dgn(file_path: str) -> pd.DataFrame:
    """
    Parse EPIC DGN (Daily General Output) file.

    Returns DataFrame indexed by date with daily simulation values.
    Key variables:
      BIOM: Total biomass (t/ha)
      RW:   Root weight (t/ha)
      LAI:  Leaf area index
      WS:   Water stress factor
      NS:   Nitrogen stress factor
      TS:   Temperature stress factor
      AS:   Aeration stress factor
      SS:   Salt stress factor

    Derived:
      AGB = BIOM - RW  (above-ground biomass)
    """
    df = pd.read_csv(file_path, sep=r"\s+", skiprows=SKIP_ROWS,
                     encoding="utf-8", encoding_errors="replace")

    df.columns = [c.strip() for c in df.columns]

    # Build datetime from Y, M, D columns
    if all(c in df.columns for c in ["Y", "M", "D"]):
        df["date"] = pd.to_datetime(
            df[["Y", "M", "D"]].rename(
                columns={"Y": "year", "M": "month", "D": "day"}
            )
        )
        df = df.set_index("date")

    # Compute above-ground biomass
    if "BIOM" in df.columns and "RW" in df.columns:
        df["AGB"] = df["BIOM"] - df["RW"]

    return df


def parse_acm(file_path: str) -> pd.DataFrame:
    """Parse EPIC ACM (Annual Carbon/Nitrogen Mass) file."""
    df = pd.read_csv(file_path, sep=r"\s+", skiprows=SKIP_ROWS,
                     encoding="utf-8", encoding_errors="replace")
    df.columns = [c.strip() for c in df.columns]
    return df


def parse_dhs(file_path: str) -> pd.DataFrame:
    """Parse EPIC DHS (Daily Hydrology Summary) file."""
    df = pd.read_csv(file_path, sep=r"\s+", skiprows=SKIP_ROWS,
                     encoding="utf-8", encoding_errors="replace")
    df.columns = [c.strip() for c in df.columns]

    if all(c in df.columns for c in ["Y", "M", "D"]):
        df["date"] = pd.to_datetime(
            df[["Y", "M", "D"]].rename(
                columns={"Y": "year", "M": "month", "D": "day"}
            )
        )
        df = df.set_index("date")

    return df


def validate_outputs(df: pd.DataFrame, file_type: str) -> list:
    """Validate parsed output data."""
    errors = []

    if df.empty:
        errors.append(f"ERROR: Parsed {file_type} DataFrame is empty")
        return errors

    if file_type == "ACY":
        if "YLDG" in df.columns:
            yld = df["YLDG"]
            if yld.max() > 50:
                errors.append(
                    f"WARNING: Max yield = {yld.max():.1f} t/ha — unusually high. "
                    f"Check crop parameters and PHU."
                )
            if (yld == 0).all():
                errors.append(
                    "WARNING: All yields are 0 — crop may not have matured. "
                    "Check PHU, planting date, and weather data coverage."
                )

    if file_type == "DGN":
        if "BIOM" in df.columns:
            biom = df["BIOM"]
            if biom.max() == 0:
                errors.append(
                    "WARNING: Max biomass = 0 in DGN — simulation produced no growth"
                )
            if biom.max() > 100:
                errors.append(
                    f"WARNING: Max biomass = {biom.max():.1f} t/ha — very high"
                )

        if "WS" in df.columns:
            ws_mean = df["WS"].mean()
            if ws_mean > 0.5:
                errors.append(
                    f"WARNING: Mean water stress = {ws_mean:.2f} — "
                    f"crop may be severely water-limited"
                )

    return errors


def export_summary(acy_df: pd.DataFrame, dgn_df: pd.DataFrame,
                   output_path: str, site_id: str):
    """Export summary statistics to JSON."""
    summary = {"site_id": site_id}

    if acy_df is not None and not acy_df.empty:
        if "YLDG" in acy_df.columns:
            summary["yield_mean_tha"] = float(acy_df["YLDG"].mean())
            summary["yield_max_tha"] = float(acy_df["YLDG"].max())
            summary["yield_min_tha"] = float(acy_df["YLDG"].min())
            summary["yield_std_tha"] = float(acy_df["YLDG"].std())
        if "CPNM" in acy_df.columns:
            summary["crops"] = acy_df["CPNM"].unique().tolist()
        summary["n_years"] = int(acy_df["YR"].nunique()) if "YR" in acy_df.columns else 0

    if dgn_df is not None and not dgn_df.empty:
        if "BIOM" in dgn_df.columns:
            summary["peak_biomass_tha"] = float(dgn_df["BIOM"].max())
        if "LAI" in dgn_df.columns:
            summary["peak_lai"] = float(dgn_df["LAI"].max())
        if "AGB" in dgn_df.columns:
            summary["peak_agb_tha"] = float(dgn_df["AGB"].max())
        summary["n_days"] = len(dgn_df)

    import json
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"Summary written to {output_path}")
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Parse EPIC output files to CSV/JSON"
    )
    parser.add_argument("--output-dir", required=True,
                        help="Directory containing EPIC output files")
    parser.add_argument("--site-id", required=True,
                        help="Site identifier")
    parser.add_argument("--export-csv", action="store_true",
                        help="Export parsed data to CSV")
    parser.add_argument("--export-summary", action="store_true",
                        help="Export summary statistics to JSON")

    args = parser.parse_args()

    acy_df = None
    dgn_df = None

    # Parse ACY
    acy_path = os.path.join(args.output_dir, f"{args.site_id}.ACY")
    acy_errors = validate_inputs(acy_path, "ACY")
    if not any("ERROR" in e for e in acy_errors):
        acy_df = parse_acy(acy_path)
        val_errors = validate_outputs(acy_df, "ACY")
        for e in val_errors:
            print(e)

        if args.export_csv:
            csv_path = os.path.join(args.output_dir, f"{args.site_id}_ACY.csv")
            acy_df.to_csv(csv_path, index=False)
            print(f"ACY exported to {csv_path}")

        print(f"\nACY Summary ({args.site_id}):")
        print(f"  Years: {acy_df['YR'].nunique() if 'YR' in acy_df.columns else 'N/A'}")
        if "YLDG" in acy_df.columns:
            print(f"  Mean yield: {acy_df['YLDG'].mean():.2f} t/ha")
            print(f"  Max yield:  {acy_df['YLDG'].max():.2f} t/ha")
    else:
        for e in acy_errors:
            print(e)

    # Parse DGN
    dgn_path = os.path.join(args.output_dir, f"{args.site_id}.DGN")
    dgn_errors = validate_inputs(dgn_path, "DGN")
    if not any("ERROR" in e for e in dgn_errors):
        dgn_df = parse_dgn(dgn_path)
        val_errors = validate_outputs(dgn_df, "DGN")
        for e in val_errors:
            print(e)

        if args.export_csv:
            csv_path = os.path.join(args.output_dir, f"{args.site_id}_DGN.csv")
            dgn_df.to_csv(csv_path)
            print(f"DGN exported to {csv_path}")

        print(f"\nDGN Summary ({args.site_id}):")
        print(f"  Days: {len(dgn_df)}")
        if "BIOM" in dgn_df.columns:
            print(f"  Peak biomass: {dgn_df['BIOM'].max():.2f} t/ha")
        if "AGB" in dgn_df.columns:
            print(f"  Peak AGB:     {dgn_df['AGB'].max():.2f} t/ha")
        if "LAI" in dgn_df.columns:
            print(f"  Peak LAI:     {dgn_df['LAI'].max():.2f}")
    else:
        for e in dgn_errors:
            print(e)

    # Export summary
    if args.export_summary:
        summary_path = os.path.join(args.output_dir, f"{args.site_id}_summary.json")
        export_summary(acy_df, dgn_df, summary_path, args.site_id)


if __name__ == "__main__":
    main()
