#!/usr/bin/env python3
"""
Parse GR4J output, compute efficiency metrics, and create validation plots.

Pipeline stage: s5 (Output parsing) and s6 (Validation)
Pattern: validate inputs -> process -> validate outputs

Outputs:
  - Summary CSV with key variables
  - Efficiency metrics (NSE, KGE, PBIAS, RMSE, R2)
  - Validation hydrograph plot (observed vs simulated)
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(output_csv: str, qobs_csv: str = None) -> list:
    """Validate input files before parsing."""
    errors = []

    if not Path(output_csv).exists():
        errors.append(f"Output CSV not found: {output_csv}")
        return errors

    df = pd.read_csv(output_csv, nrows=5)
    if "Qsim_mm" not in df.columns:
        errors.append("Missing 'Qsim_mm' column in output CSV")
    if "Date" not in df.columns:
        errors.append("Missing 'Date' column in output CSV")

    if qobs_csv and not Path(qobs_csv).exists():
        errors.append(f"Observed discharge file not found: {qobs_csv}")

    return errors


def validate_outputs(metrics: dict) -> list:
    """Validate computed metrics."""
    warnings = []

    nse = metrics.get("NSE")
    if nse is not None and nse < 0:
        warnings.append(
            f"NSE = {nse:.4f} < 0 — model is worse than mean. "
            "Check forcing data, unit conversions, or parameter values."
        )

    kge = metrics.get("KGE")
    if kge is not None and kge < 0:
        warnings.append(
            f"KGE = {kge:.4f} < 0 — poor model performance."
        )

    pbias = metrics.get("PBIAS")
    if pbias is not None and abs(pbias) > 50:
        warnings.append(
            f"PBIAS = {pbias:.1f}% — large volume bias. "
            "Check precipitation and PE units."
        )

    return warnings


# ---------------------------------------------------------------------------
# Efficiency metrics
# ---------------------------------------------------------------------------

def compute_nse(obs: np.ndarray, sim: np.ndarray) -> float:
    """Nash-Sutcliffe Efficiency."""
    mask = ~(np.isnan(obs) | np.isnan(sim))
    if mask.sum() < 10:
        return np.nan
    o, s = obs[mask], sim[mask]
    ss_res = np.sum((o - s) ** 2)
    ss_tot = np.sum((o - np.mean(o)) ** 2)
    if ss_tot == 0:
        return 0.0
    return 1.0 - ss_res / ss_tot


def compute_kge(obs: np.ndarray, sim: np.ndarray) -> float:
    """Kling-Gupta Efficiency."""
    mask = ~(np.isnan(obs) | np.isnan(sim))
    if mask.sum() < 10:
        return np.nan
    o, s = obs[mask], sim[mask]

    r = np.corrcoef(o, s)[0, 1]
    alpha = np.std(s) / np.std(o) if np.std(o) > 0 else 1.0
    beta = np.mean(s) / np.mean(o) if np.mean(o) > 0 else 1.0

    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def compute_pbias(obs: np.ndarray, sim: np.ndarray) -> float:
    """Percent Bias (%)."""
    mask = ~(np.isnan(obs) | np.isnan(sim))
    if mask.sum() < 10:
        return np.nan
    o, s = obs[mask], sim[mask]
    if np.sum(o) == 0:
        return np.nan
    return 100.0 * np.sum(s - o) / np.sum(o)


def compute_rmse(obs: np.ndarray, sim: np.ndarray) -> float:
    """Root Mean Square Error."""
    mask = ~(np.isnan(obs) | np.isnan(sim))
    if mask.sum() < 10:
        return np.nan
    o, s = obs[mask], sim[mask]
    return np.sqrt(np.mean((o - s) ** 2))


def compute_r2(obs: np.ndarray, sim: np.ndarray) -> float:
    """Coefficient of determination R2."""
    mask = ~(np.isnan(obs) | np.isnan(sim))
    if mask.sum() < 10:
        return np.nan
    o, s = obs[mask], sim[mask]
    r = np.corrcoef(o, s)[0, 1]
    return r ** 2


def compute_all_metrics(obs: np.ndarray, sim: np.ndarray) -> dict:
    """Compute all efficiency metrics."""
    return {
        "NSE": round(compute_nse(obs, sim), 4),
        "KGE": round(compute_kge(obs, sim), 4),
        "PBIAS": round(compute_pbias(obs, sim), 2),
        "RMSE": round(compute_rmse(obs, sim), 4),
        "R2": round(compute_r2(obs, sim), 4),
        "n_valid": int(np.sum(~(np.isnan(obs) | np.isnan(sim)))),
        "obs_mean": round(float(np.nanmean(obs)), 4),
        "sim_mean": round(float(np.nanmean(sim)), 4),
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_validation(dates, obs, sim, precip, metrics,
                     output_png: str, title: str = "GR4J Validation"):
    """
    Create validation hydrograph plot.

    Parameters
    ----------
    dates    : array of datetime
    obs      : array of observed Q [mm/d]
    sim      : array of simulated Q [mm/d]
    precip   : array of precipitation [mm/d]
    metrics  : dict of metrics
    output_png : output path for PNG
    title    : plot title
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8),
                                     gridspec_kw={"height_ratios": [1, 3]},
                                     sharex=True)

    # --- Precipitation (inverted, top panel) ---
    ax1.bar(dates, precip, color="#4A90D9", alpha=0.7, width=1.0)
    ax1.invert_yaxis()
    ax1.set_ylabel("Precip [mm/d]")
    ax1.set_title(title, fontsize=14, fontweight="bold")

    # --- Discharge (bottom panel) ---
    mask = ~np.isnan(obs)
    ax2.plot(dates[mask], obs[mask], color="black", linewidth=0.8,
             label="Observed", alpha=0.9)
    ax2.plot(dates, sim, color="#2563EB", linewidth=0.8,
             label="Simulated (GR4J)", alpha=0.9)
    ax2.set_ylabel("Discharge [mm/d]")
    ax2.set_xlabel("Date")
    ax2.legend(loc="upper left", fontsize=10)

    # --- Metrics box ---
    metric_text = (
        f"NSE = {metrics['NSE']:.4f}\n"
        f"KGE = {metrics['KGE']:.4f}\n"
        f"PBIAS = {metrics['PBIAS']:.1f}%\n"
        f"RMSE = {metrics['RMSE']:.3f} mm/d"
    )
    ax2.text(0.98, 0.95, metric_text,
             transform=ax2.transAxes, fontsize=10,
             verticalalignment="top", horizontalalignment="right",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor="gray", alpha=0.9),
             fontfamily="monospace")

    # --- Formatting ---
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    plt.xticks(rotation=45)
    plt.tight_layout()

    # --- Save ---
    fig.savefig(output_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[parse_output] Saved validation plot to {output_png}")


# ---------------------------------------------------------------------------
# Main: parse and analyze
# ---------------------------------------------------------------------------

def parse_gr4j_output(
    output_csv: str,
    forcing_csv: str = None,
    qobs_column: str = "Qobs_mm",
    metrics_json: str = None,
    plot_png: str = None,
    summary_csv: str = None,
    catchment_name: str = "Unknown",
) -> dict:
    """
    Parse GR4J output and compute validation metrics.

    Parameters
    ----------
    output_csv     : path to GR4J output CSV (from run_gr4j)
    forcing_csv    : path to forcing CSV (contains Qobs if available)
    qobs_column    : column name for observed discharge in forcing CSV
    metrics_json   : output path for metrics JSON
    plot_png       : output path for validation plot
    summary_csv    : output path for summary CSV
    catchment_name : name for plot title

    Returns
    -------
    result : dict with metrics and file paths
    """
    # --- Validate inputs ---
    errors = validate_inputs(output_csv)
    if errors:
        raise ValueError("Input validation failed:\n" + "\n".join(errors))

    # --- Read model output ---
    df_sim = pd.read_csv(output_csv, parse_dates=["Date"])

    result = {
        "n_timesteps": len(df_sim),
        "start_date": str(df_sim["Date"].iloc[0].date()),
        "end_date": str(df_sim["Date"].iloc[-1].date()),
        "qsim_mean": float(df_sim["Qsim_mm"].mean()),
        "qsim_max": float(df_sim["Qsim_mm"].max()),
    }

    # --- Merge with observed Q if available ---
    obs = None
    if forcing_csv and Path(forcing_csv).exists():
        df_forc = pd.read_csv(forcing_csv, parse_dates=["Date"])
        if qobs_column in df_forc.columns:
            df_merged = df_sim.merge(df_forc[["Date", qobs_column, "Precip_mm"]],
                                       on="Date", how="left", suffixes=("", "_forc"))
            obs = df_merged[qobs_column].values
            sim = df_merged["Qsim_mm"].values
            precip = df_merged.get("Precip_mm", df_merged.get("Precip_mm_forc"))
            if precip is None:
                precip = np.zeros_like(sim)
            else:
                precip = precip.values

            # --- Compute metrics ---
            metrics = compute_all_metrics(obs, sim)
            result["metrics"] = metrics

            # --- Validate outputs ---
            warnings = validate_outputs(metrics)
            for w in warnings:
                print(f"[parse_output] WARNING: {w}")

            # --- Plot ---
            if plot_png:
                dates = df_merged["Date"].values
                plot_validation(
                    dates=dates, obs=obs, sim=sim, precip=precip,
                    metrics=metrics, output_png=plot_png,
                    title=f"GR4J Validation — {catchment_name}",
                )
                result["plot"] = plot_png

    # --- Write summary CSV ---
    if summary_csv:
        df_sim.to_csv(summary_csv, index=False)
        result["summary_csv"] = summary_csv

    # --- Write metrics JSON ---
    if metrics_json and "metrics" in result:
        with open(metrics_json, "w") as f:
            json.dump(result, f, indent=2, default=str)
        result["metrics_json"] = metrics_json

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse GR4J output and compute validation metrics"
    )
    parser.add_argument("--output-csv", required=True,
                        help="GR4J output CSV from run_gr4j")
    parser.add_argument("--forcing-csv", help="Forcing CSV with Qobs column")
    parser.add_argument("--qobs-col", default="Qobs_mm",
                        help="Column name for observed discharge")
    parser.add_argument("--metrics-json", help="Output metrics JSON path")
    parser.add_argument("--plot-png", help="Output validation plot path")
    parser.add_argument("--summary-csv", help="Output summary CSV path")
    parser.add_argument("--name", default="Unknown", help="Catchment name")

    args = parser.parse_args()
    result = parse_gr4j_output(
        output_csv=args.output_csv,
        forcing_csv=args.forcing_csv,
        qobs_column=args.qobs_col,
        metrics_json=args.metrics_json,
        plot_png=args.plot_png,
        summary_csv=args.summary_csv,
        catchment_name=args.name,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
