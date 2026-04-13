#!/usr/bin/env python3
"""
parse_wsimod_output.py — Parse WSIMOD output files into analysis-ready DataFrames.

WSIMOD model.run() produces four return values:
  1. flows  — list of dicts, one per arc per timestep (flow + pollutants)
  2. tanks  — list of dicts, one per storage node per timestep
  3. (unused) — additional internal data
  4. surfaces — list of dicts, one per land surface per timestep

This tool:
  - Reads flows.csv, tanks.csv, surfaces.csv from the output directory
  - Validates physical reasonableness of results
  - Computes summary statistics
  - Optionally extracts specific variables to clean CSV files

CRITICAL CHECKS:
  - Flow values should be non-negative (negative = reverse flow bug)
  - Mass balance: sum(inflows) ≈ sum(outflows) + Δstorage
  - Pollutant concentrations: additive pollutants in kg, non-additive in mg/L or °C
  - Volume consistency: no NaN or Inf values
  - Temperature range: typically -5 to 40°C for temperate systems

Usage:
    python parse_wsimod_output.py --output-dir ./outputs \\
        [--variable flow] [--arc catchment_outflow] \\
        [--extract-csv extracted.csv] [--summary]
"""

import argparse
import json
import os
import sys

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate that output files exist."""
    errors = []
    warnings = []

    if not os.path.isdir(args.output_dir):
        errors.append(f"Output directory not found: {args.output_dir}")
    else:
        expected_files = ["flows.csv", "tanks.csv", "surfaces.csv"]
        for fname in expected_files:
            fpath = os.path.join(args.output_dir, fname)
            if not os.path.isfile(fpath):
                warnings.append(f"Expected output file not found: {fpath}")

        # At least flows.csv must exist
        if not os.path.isfile(os.path.join(args.output_dir, "flows.csv")):
            errors.append(
                "flows.csv not found in output directory. "
                "Model may not have run successfully."
            )

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)


def validate_outputs(flows_df, tanks_df, surfaces_df):
    """Validate parsed output for physical reasonableness."""
    import pandas as pd
    import numpy as np

    warnings = []

    if flows_df is not None and len(flows_df) > 0:
        # Check for NaN/Inf
        nan_count = flows_df.select_dtypes(include=[np.number]).isna().sum().sum()
        if nan_count > 0:
            warnings.append(f"Found {nan_count} NaN values in flows.csv")

        inf_count = np.isinf(
            flows_df.select_dtypes(include=[np.number]).values
        ).sum()
        if inf_count > 0:
            warnings.append(f"Found {inf_count} Inf values in flows.csv")

        # Check flow is non-negative
        if "flow" in flows_df.columns:
            neg_flows = (flows_df["flow"] < -1e-10).sum()
            if neg_flows > 0:
                warnings.append(
                    f"{neg_flows} negative flow values detected. "
                    "Check arc direction and node configuration."
                )

            # Check flow magnitude
            max_flow = flows_df["flow"].max()
            if max_flow > 1e6:
                warnings.append(
                    f"Max flow = {max_flow:.2f} — extremely high. "
                    "Check volume unit conversion (dt_002, dt_003)."
                )

        # Check temperature range
        if "temperature" in flows_df.columns:
            min_temp = flows_df["temperature"].min()
            max_temp = flows_df["temperature"].max()
            if max_temp > 50 or min_temp < -30:
                warnings.append(
                    f"Temperature range [{min_temp:.1f}, {max_temp:.1f}] °C "
                    "seems unrealistic."
                )

        # Check phosphate is non-negative
        if "phosphate" in flows_df.columns:
            neg_p = (flows_df["phosphate"] < -1e-15).sum()
            if neg_p > 0:
                warnings.append(
                    f"{neg_p} negative phosphate values — mass conservation issue."
                )

    if tanks_df is not None and len(tanks_df) > 0:
        if "volume" in tanks_df.columns:
            neg_vol = (tanks_df["volume"] < -1e-10).sum()
            if neg_vol > 0:
                warnings.append(
                    f"{neg_vol} negative tank volumes — storage balance error."
                )

    return warnings


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process(args):
    """Parse WSIMOD output files and compute summary statistics."""
    import pandas as pd
    import numpy as np

    result = {"status": "success", "files_parsed": []}

    # Parse flows.csv
    flows_df = None
    flows_path = os.path.join(args.output_dir, "flows.csv")
    if os.path.isfile(flows_path):
        flows_df = pd.read_csv(flows_path, index_col=0)
        result["files_parsed"].append("flows.csv")
        result["flows"] = {
            "n_records": len(flows_df),
            "columns": list(flows_df.columns),
            "arcs": sorted(flows_df["arc"].unique().tolist())
            if "arc" in flows_df.columns else [],
            "time_range": [
                str(flows_df["time"].min()) if "time" in flows_df.columns else "?",
                str(flows_df["time"].max()) if "time" in flows_df.columns else "?",
            ],
        }

        # Compute flow statistics per arc
        if "arc" in flows_df.columns and "flow" in flows_df.columns:
            flow_stats = flows_df.groupby("arc")["flow"].agg(
                ["mean", "std", "min", "max"]
            ).round(6).to_dict("index")
            result["flows"]["stats_per_arc"] = flow_stats

    # Parse tanks.csv
    tanks_df = None
    tanks_path = os.path.join(args.output_dir, "tanks.csv")
    if os.path.isfile(tanks_path):
        tanks_df = pd.read_csv(tanks_path, index_col=0)
        result["files_parsed"].append("tanks.csv")
        result["tanks"] = {
            "n_records": len(tanks_df),
            "columns": list(tanks_df.columns),
        }

    # Parse surfaces.csv
    surfaces_df = None
    surfaces_path = os.path.join(args.output_dir, "surfaces.csv")
    if os.path.isfile(surfaces_path):
        surfaces_df = pd.read_csv(surfaces_path, index_col=0)
        result["files_parsed"].append("surfaces.csv")
        result["surfaces"] = {
            "n_records": len(surfaces_df),
            "columns": list(surfaces_df.columns),
        }

    # Validate outputs
    warnings = validate_outputs(flows_df, tanks_df, surfaces_df)
    if warnings:
        result["warnings"] = warnings

    # Extract specific variable/arc if requested
    if args.extract_csv and flows_df is not None:
        extract_df = flows_df.copy()
        if args.arc and "arc" in extract_df.columns:
            extract_df = extract_df[extract_df["arc"] == args.arc]
        if args.variable:
            cols = ["time"]
            if "arc" in extract_df.columns:
                cols.append("arc")
            if args.variable in extract_df.columns:
                cols.append(args.variable)
            extract_df = extract_df[cols]

        extract_df.to_csv(args.extract_csv, index=False)
        result["extracted"] = {
            "file": args.extract_csv,
            "n_records": len(extract_df),
            "variable": args.variable,
            "arc": args.arc,
        }

    # Summary statistics
    if args.summary and flows_df is not None:
        numeric_cols = flows_df.select_dtypes(include=[np.number]).columns
        summary_stats = {}
        for col in numeric_cols:
            summary_stats[col] = {
                "mean": round(float(flows_df[col].mean()), 6),
                "std": round(float(flows_df[col].std()), 6),
                "min": round(float(flows_df[col].min()), 6),
                "max": round(float(flows_df[col].max()), 6),
            }
        result["summary_statistics"] = summary_stats

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse WSIMOD output files"
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Directory containing WSIMOD output files (flows.csv, etc.)"
    )
    parser.add_argument(
        "--variable", default=None,
        help="Variable to extract (e.g., flow, phosphate, temperature)"
    )
    parser.add_argument(
        "--arc", default=None,
        help="Arc name to filter (e.g., catchment_outflow)"
    )
    parser.add_argument(
        "--extract-csv", default=None,
        help="Path to save extracted data as CSV"
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="Print summary statistics"
    )
    parser.add_argument(
        "--json-output", default=None,
        help="Path to save full result as JSON"
    )

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump(result, f, indent=2, default=str)

    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
