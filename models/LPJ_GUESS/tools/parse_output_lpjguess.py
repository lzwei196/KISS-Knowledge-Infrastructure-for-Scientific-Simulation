#!/usr/bin/env python3
"""
parse_output_lpjguess.py
Parse and post-process LPJ-GUESS model output.

This tool:
1. Validates the raw model output CSV
2. Extracts GPP, NEE, Reco (and optionally NPP, Ra, Rh) timeseries
3. Computes temporal aggregations (daily -> monthly, monthly -> annual)
4. Computes validation metrics against observations (if available)
5. Produces clean output CSV and optional summary statistics

Usage:
    # Basic parsing
    python parse_output_lpjguess.py \\
        --input model_output.csv \\
        --output-csv parsed_output.csv

    # With monthly aggregation
    python parse_output_lpjguess.py \\
        --input model_output.csv \\
        --output-csv parsed_monthly.csv \\
        --aggregate monthly

    # With validation metrics
    python parse_output_lpjguess.py \\
        --input model_output.csv \\
        --output-csv parsed_output.csv \\
        --obs-gpp obs_GPP \\
        --obs-nee obs_NEE \\
        --metrics-json metrics.json

    # Summary statistics only
    python parse_output_lpjguess.py \\
        --input model_output.csv \\
        --summary-csv summary.csv
"""

import os
import sys
import json
import math
import argparse
import csv

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from scipy import stats as scipy_stats
except ImportError:
    scipy_stats = None


# ============================================================================
# Output variable definitions
# ============================================================================

OUTPUT_VARIABLES = {
    "GPP": {
        "long_name": "Gross Primary Production",
        "units": "umol CO2/m2/s",
        "min_valid": 0.0,
        "max_valid": 50.0,
    },
    "Ra": {
        "long_name": "Autotrophic respiration",
        "units": "umol CO2/m2/s",
        "min_valid": 0.0,
        "max_valid": 30.0,
    },
    "Rh": {
        "long_name": "Heterotrophic respiration",
        "units": "umol CO2/m2/s",
        "min_valid": 0.0,
        "max_valid": 20.0,
    },
    "Reco": {
        "long_name": "Ecosystem respiration",
        "units": "umol CO2/m2/s",
        "min_valid": 0.0,
        "max_valid": 40.0,
    },
    "NEE": {
        "long_name": "Net Ecosystem Exchange",
        "units": "umol CO2/m2/s",
        "min_valid": -30.0,
        "max_valid": 20.0,
    },
    "NPP": {
        "long_name": "Net Primary Production",
        "units": "umol CO2/m2/s",
        "min_valid": -5.0,
        "max_valid": 30.0,
    },
}


# ============================================================================
# Input validation
# ============================================================================

def validate_input_file(filepath):
    """Validate the model output file before parsing."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return False

    size = os.path.getsize(filepath)
    if size == 0:
        print(f"ERROR: File is empty: {filepath}", file=sys.stderr)
        return False

    # Check header
    with open(filepath) as f:
        header = f.readline().strip()

    if "GPP" not in header:
        print(f"WARNING: Output file header does not contain 'GPP': {header[:200]}",
              file=sys.stderr)

    print(f"Input file: {filepath} ({size} bytes)")
    return True


# ============================================================================
# Output validation (parsed data)
# ============================================================================

def validate_parsed_data(df, variables=None):
    """
    Validate parsed data for physical plausibility.

    Parameters
    ----------
    df : DataFrame
        Parsed model output
    variables : list of str or None
        Variable names to check (default: all known)

    Returns
    -------
    list of warning strings
    """
    if variables is None:
        variables = [v for v in OUTPUT_VARIABLES if v in df.columns]

    warnings = []
    nrows = len(df)
    print(f"Validating parsed data: {nrows} rows, variables: {variables}")

    for var_name in variables:
        if var_name not in df.columns:
            continue
        if var_name not in OUTPUT_VARIABLES:
            continue

        meta = OUTPUT_VARIABLES[var_name]
        vals = df[var_name].dropna().values

        if len(vals) == 0:
            warnings.append(f"{var_name}: all values are NaN")
            continue

        n_nan = nrows - len(vals)
        if n_nan > 0:
            frac = n_nan / nrows
            if frac > 0.1:
                warnings.append(f"{var_name}: {frac:.0%} missing values")

        vmin, vmax = float(np.min(vals)), float(np.max(vals))
        vmean = float(np.mean(vals))

        if vmin < meta["min_valid"]:
            warnings.append(
                f"{var_name}: min={vmin:.4f} below expected minimum "
                f"{meta['min_valid']} {meta['units']}"
            )
        if vmax > meta["max_valid"]:
            warnings.append(
                f"{var_name}: max={vmax:.4f} above expected maximum "
                f"{meta['max_valid']} {meta['units']}"
            )

        print(f"  {var_name}: min={vmin:.4f}, max={vmax:.4f}, "
              f"mean={vmean:.4f} {meta['units']}")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if not warnings:
        print("Parsed data validated: all values within expected ranges")

    return warnings


# ============================================================================
# Validation metrics
# ============================================================================

def compute_metrics(obs, sim, name=""):
    """
    Compute validation metrics for paired obs/sim arrays.

    Computes: R, RMSE, bias, NSE, KGE
    Handles NaN values gracefully.

    Parameters
    ----------
    obs : array-like
        Observations
    sim : array-like
        Simulated values
    name : str
        Variable name for display

    Returns
    -------
    dict of metrics
    """
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)

    mask = ~np.isnan(obs) & ~np.isnan(sim)
    if mask.sum() < 3:
        return {"n": int(mask.sum()), "error": "insufficient data"}

    o = obs[mask]
    s = sim[mask]
    n = len(o)

    # Bias
    bias = float(np.mean(s - o))

    # RMSE
    rmse = float(np.sqrt(np.mean((s - o) ** 2)))

    # Pearson R
    if scipy_stats is not None:
        r, p_val = scipy_stats.pearsonr(o, s)
        r = float(r)
        p_val = float(p_val)
    else:
        # Fallback: manual Pearson R
        o_mean, s_mean = np.mean(o), np.mean(s)
        cov = np.mean((o - o_mean) * (s - s_mean))
        r = cov / (max(np.std(o), 1e-10) * max(np.std(s), 1e-10))
        r = float(r)
        p_val = float("nan")

    # NSE (Nash-Sutcliffe Efficiency)
    ss_res = np.sum((s - o) ** 2)
    ss_tot = np.sum((o - np.mean(o)) ** 2)
    nse = float(1.0 - ss_res / max(ss_tot, 1e-10))

    # KGE (Kling-Gupta Efficiency)
    r_kge = np.corrcoef(o, s)[0, 1]
    alpha = np.std(s) / max(np.std(o), 1e-10)
    mean_o = np.mean(o)
    mean_s = np.mean(s)
    if abs(mean_o) > 0.01:
        beta = mean_s / mean_o
    else:
        beta = 1.0 + (mean_s - mean_o) / max(np.std(o), 1e-10)
    kge = float(1.0 - np.sqrt(
        (r_kge - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2
    ))

    metrics = {
        "n": n,
        "R": round(r, 4),
        "p_value": round(p_val, 6),
        "RMSE": round(rmse, 4),
        "bias": round(bias, 4),
        "NSE": round(nse, 4),
        "KGE": round(kge, 4),
    }

    print(f"  [{name}] n={n}, R={r:.3f}, RMSE={rmse:.3f}, "
          f"bias={bias:.3f}, NSE={nse:.3f}, KGE={kge:.3f}")

    return metrics


# ============================================================================
# Temporal aggregation
# ============================================================================

def aggregate_to_monthly(df):
    """
    Aggregate daily data to monthly means.

    Requires 'year' and 'month' columns in input.
    """
    if "year" not in df.columns or "month" not in df.columns:
        print("WARNING: Cannot aggregate to monthly without 'year' and 'month' columns",
              file=sys.stderr)
        return df

    # Identify numeric columns to aggregate
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    exclude = ["year", "month", "day"]
    agg_cols = [c for c in numeric_cols if c not in exclude]

    df_monthly = (
        df.groupby(["year", "month"])[agg_cols]
        .mean()
        .reset_index()
    )

    print(f"Aggregated to monthly: {len(df)} -> {len(df_monthly)} rows")
    return df_monthly


def aggregate_to_annual(df):
    """
    Aggregate to annual means.

    Requires 'year' column in input.
    """
    if "year" not in df.columns:
        print("WARNING: Cannot aggregate to annual without 'year' column",
              file=sys.stderr)
        return df

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    exclude = ["year", "month", "day"]
    agg_cols = [c for c in numeric_cols if c not in exclude]

    df_annual = (
        df.groupby("year")[agg_cols]
        .mean()
        .reset_index()
    )

    print(f"Aggregated to annual: {len(df)} -> {len(df_annual)} rows")
    return df_annual


# ============================================================================
# Summary statistics
# ============================================================================

def compute_summary(df, output_csv=None):
    """
    Compute summary statistics for each variable.

    Returns dict of {variable: {min, max, mean, std, count}}.
    """
    summary = {}
    variables = [v for v in OUTPUT_VARIABLES if v in df.columns]

    for var_name in variables:
        vals = df[var_name].dropna().values
        if len(vals) == 0:
            summary[var_name] = {"count": 0}
            continue

        summary[var_name] = {
            "count": int(len(vals)),
            "min": round(float(np.min(vals)), 6),
            "max": round(float(np.max(vals)), 6),
            "mean": round(float(np.mean(vals)), 6),
            "std": round(float(np.std(vals)), 6),
            "median": round(float(np.median(vals)), 6),
            "p05": round(float(np.percentile(vals, 5)), 6),
            "p95": round(float(np.percentile(vals, 95)), 6),
        }

    if output_csv:
        with open(output_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["variable", "count", "min", "max", "mean",
                             "std", "median", "p05", "p95"])
            for var_name, stats in summary.items():
                if "count" in stats and stats["count"] > 0:
                    writer.writerow([
                        var_name,
                        stats["count"],
                        stats["min"],
                        stats["max"],
                        stats["mean"],
                        stats["std"],
                        stats["median"],
                        stats["p05"],
                        stats["p95"],
                    ])
        print(f"Summary written to {output_csv}")

    return summary


# ============================================================================
# Main parsing pipeline
# ============================================================================

def parse_output(input_path, output_csv=None, aggregate=None,
                 obs_gpp_col=None, obs_nee_col=None, obs_reco_col=None,
                 metrics_json=None, summary_csv=None,
                 variables=None):
    """
    Full output parsing pipeline: validate -> load -> aggregate -> metrics -> export.

    Parameters
    ----------
    input_path : str
        Path to raw model output CSV (from run_lpjguess.py)
    output_csv : str or None
        Path to write parsed output CSV
    aggregate : str or None
        "monthly" or "annual" for temporal aggregation
    obs_gpp_col, obs_nee_col, obs_reco_col : str or None
        Column names for observed variables (for metrics)
    metrics_json : str or None
        Path to write validation metrics JSON
    summary_csv : str or None
        Path to write summary statistics CSV
    variables : list of str or None
        Variables to extract (default: all available)

    Returns
    -------
    dict with status, metrics, summary
    """
    if pd is None:
        print("ERROR: pandas required. pip install pandas", file=sys.stderr)
        return {"status": "error", "errors": ["pandas not installed"]}

    # --- Validate input ---
    if not validate_input_file(input_path):
        return {"status": "error", "errors": ["Input validation failed"]}

    # --- Load data ---
    print(f"Loading model output: {input_path}")
    df = pd.read_csv(input_path)
    print(f"  {len(df)} rows, columns: {list(df.columns)}")

    # Convert numeric columns
    for col in df.columns:
        if col not in ("date",):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # --- Validate parsed data ---
    if variables is None:
        variables = [v for v in OUTPUT_VARIABLES if v in df.columns]
    data_warnings = validate_parsed_data(df, variables)

    # --- Temporal aggregation ---
    if aggregate == "monthly":
        df = aggregate_to_monthly(df)
    elif aggregate == "annual":
        df = aggregate_to_annual(df)

    # --- Compute validation metrics ---
    all_metrics = {}
    metric_pairs = []
    if obs_gpp_col and obs_gpp_col in df.columns and "GPP" in df.columns:
        metric_pairs.append(("GPP", "GPP", obs_gpp_col))
    if obs_nee_col and obs_nee_col in df.columns and "NEE" in df.columns:
        metric_pairs.append(("NEE", "NEE", obs_nee_col))
    if obs_reco_col and obs_reco_col in df.columns and "Reco" in df.columns:
        metric_pairs.append(("Reco", "Reco", obs_reco_col))

    if metric_pairs:
        print("\n=== Validation Metrics ===")
        for name, sim_col, obs_col in metric_pairs:
            obs_vals = df[obs_col].values
            sim_vals = df[sim_col].values
            met = compute_metrics(obs_vals, sim_vals, name)
            all_metrics[name] = met

    if metrics_json and all_metrics:
        with open(metrics_json, "w") as f:
            json.dump(all_metrics, f, indent=2)
        print(f"Metrics written to {metrics_json}")

    # --- Summary statistics ---
    summary = compute_summary(df, summary_csv)

    # --- Write output CSV ---
    if output_csv:
        # Select columns to output
        out_cols = []
        for col in ["date", "year", "month"]:
            if col in df.columns:
                out_cols.append(col)
        for var in variables:
            if var in df.columns:
                out_cols.append(var)
        # Also include observation columns
        for obs_col in [obs_gpp_col, obs_nee_col, obs_reco_col]:
            if obs_col and obs_col in df.columns and obs_col not in out_cols:
                out_cols.append(obs_col)

        df_out = df[out_cols] if out_cols else df
        df_out.to_csv(output_csv, index=False, float_format="%.6f",
                      na_rep="NaN")
        print(f"Parsed output written: {output_csv} ({len(df_out)} rows)")

    return {
        "status": "success",
        "n_rows": len(df),
        "variables": variables,
        "metrics": all_metrics,
        "summary": summary,
        "data_warnings": data_warnings,
    }


# ============================================================================
# CLI entry point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Parse and post-process LPJ-GUESS model output",
    )
    parser.add_argument("--input", required=True,
                        help="Raw model output CSV (from run_lpjguess.py)")
    parser.add_argument("--output-csv", default=None,
                        help="Parsed output CSV file")
    parser.add_argument("--aggregate", choices=["monthly", "annual"],
                        default=None,
                        help="Temporal aggregation level")
    parser.add_argument("--obs-gpp", default=None,
                        help="Column name for observed GPP")
    parser.add_argument("--obs-nee", default=None,
                        help="Column name for observed NEE")
    parser.add_argument("--obs-reco", default=None,
                        help="Column name for observed Reco")
    parser.add_argument("--metrics-json", default=None,
                        help="Write validation metrics to JSON")
    parser.add_argument("--summary-csv", default=None,
                        help="Write summary statistics to CSV")
    parser.add_argument("--variables", nargs="+", default=None,
                        help="Variables to extract (default: all)")

    args = parser.parse_args()

    if args.output_csv is None and args.summary_csv is None and args.metrics_json is None:
        print("WARNING: No output specified. Use --output-csv, --summary-csv, "
              "or --metrics-json", file=sys.stderr)

    result = parse_output(
        input_path=args.input,
        output_csv=args.output_csv,
        aggregate=args.aggregate,
        obs_gpp_col=args.obs_gpp,
        obs_nee_col=args.obs_nee,
        obs_reco_col=args.obs_reco,
        metrics_json=args.metrics_json,
        summary_csv=args.summary_csv,
        variables=args.variables,
    )

    print(f"\nResult: {json.dumps(result, indent=2, default=str)}")
    sys.exit(0 if result["status"] == "success" else 1)
