#!/usr/bin/env python3
"""
Visualize SWAP model results.

Generates publication-quality plots:
1. Water balance bar chart (annual)
2. Soil moisture profile timeseries
3. Daily ET and rainfall timeseries
4. Validation scatter plot (observed vs simulated)

Usage:
    python plot_swap_results.py \\
        --parsed-dir /path/to/parsed/ \\
        --output-dir /path/to/figures/ \\
        --title "Hupselbrook 2002-2004"
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle
except ImportError:
    print("ERROR: matplotlib required. Install with: pip install matplotlib",
          file=sys.stderr)
    sys.exit(1)


# HydroCraft standard colors
COLOR_OBS = "black"
COLOR_SIM = "#2563EB"
COLOR_RAIN = "#3B82F6"
COLOR_ET = "#EF4444"
COLOR_DRAIN = "#10B981"
COLOR_IRRIG = "#F59E0B"
COLOR_INTERC = "#8B5CF6"


def validate_inputs(parsed_dir):
    """Check that parsed output directory exists and has data."""
    if not os.path.isdir(parsed_dir):
        print(f"ERROR: Parsed directory not found: {parsed_dir}", file=sys.stderr)
        sys.exit(1)
    files = list(Path(parsed_dir).glob("*.csv")) + list(Path(parsed_dir).glob("*.json"))
    if not files:
        print(f"ERROR: No data files in {parsed_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] Found {len(files)} data files in {parsed_dir}")


def read_csv_records(filepath):
    """Read CSV file into list of dicts."""
    records = []
    if not os.path.isfile(filepath):
        return records
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record = {}
            for k, v in row.items():
                try:
                    record[k] = float(v)
                except (ValueError, TypeError):
                    record[k] = v
            records.append(record)
    return records


def plot_water_balance(balances, output_path, title=""):
    """
    Bar chart of annual water balance components.

    In (positive): Rain, Irrigation, Bottom flux
    Out (negative): Interception, Runoff, Transpiration, Evaporation, Drainage
    """
    if not balances:
        print("  [SKIP] No water balance data for plotting")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    years = [b.get("year", i) for i, b in enumerate(balances)]
    x = np.arange(len(years))
    width = 0.35

    # Input components
    rain = [b.get("rain", 0) for b in balances]
    irrig = [b.get("irrigation", 0) for b in balances]

    # Output components
    transp = [b.get("transpiration", 0) for b in balances]
    evap = [b.get("soil_evaporation", 0) for b in balances]
    drain = [b.get("drainage", 0) for b in balances]
    interc = [b.get("interception", 0) for b in balances]
    runoff = [b.get("runoff", 0) for b in balances]

    # Stack input bars
    ax.bar(x - width / 2, rain, width, label="Rainfall", color=COLOR_RAIN)
    ax.bar(x - width / 2, irrig, width, bottom=rain, label="Irrigation",
           color=COLOR_IRRIG)

    # Stack output bars (negative)
    transp_neg = [-v for v in transp]
    evap_neg = [-v for v in evap]
    drain_neg = [-v for v in drain]
    interc_neg = [-v for v in interc]

    bottom = np.zeros(len(years))
    ax.bar(x + width / 2, transp_neg, width, label="Transpiration", color=COLOR_ET)
    bottom += np.array(transp_neg)
    ax.bar(x + width / 2, evap_neg, width, bottom=bottom, label="Soil evap.",
           color="#FB923C")
    bottom += np.array(evap_neg)
    ax.bar(x + width / 2, drain_neg, width, bottom=bottom, label="Drainage",
           color=COLOR_DRAIN)
    bottom += np.array(drain_neg)
    ax.bar(x + width / 2, interc_neg, width, bottom=bottom, label="Interception",
           color=COLOR_INTERC)

    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_xlabel("Year")
    ax.set_ylabel("Water flux (cm)")
    ax.set_title(f"SWAP Annual Water Balance — {title}" if title else
                 "SWAP Annual Water Balance")
    ax.set_xticks(x)
    ax.set_xticklabels([str(int(y)) for y in years])
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"  [OK] Water balance plot: {output_path}")


def plot_timeseries(records, output_path, title=""):
    """
    Daily timeseries of rainfall and ET.
    """
    if not records:
        print("  [SKIP] No daily records for timeseries plot")
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # Try to extract dates and values
    days = []
    rain_vals = []
    tact_vals = []
    eact_vals = []

    for r in records:
        # The cumulative-day column in result.inc is `Dcum` — not `daycum`.
        day = r.get("Dcum", r.get("dcum", r.get("DCUM", None)))
        if day is not None:
            days.append(float(day))
            rain_vals.append(float(r.get("rain", r.get("Rain", 0))))
            tact_vals.append(float(r.get("tact", r.get("Tact", 0))))
            eact_vals.append(float(r.get("eact", r.get("Eact", 0))))

    if not days:
        print("  [SKIP] Could not extract timeseries data")
        return

    days = np.array(days)
    rain_vals = np.array(rain_vals)
    tact_vals = np.array(tact_vals)
    eact_vals = np.array(eact_vals)

    # Rainfall (inverted)
    ax1.bar(days, rain_vals * 10, width=1, color=COLOR_RAIN, alpha=0.7,
            label="Rainfall")
    ax1.invert_yaxis()
    ax1.set_ylabel("Rainfall (mm/d)")
    ax1.legend(loc="lower right")
    ax1.set_title(f"SWAP Daily Fluxes — {title}" if title else "SWAP Daily Fluxes")

    # ET
    ax2.plot(days, tact_vals * 10, color=COLOR_ET, linewidth=0.8,
             label="Transpiration", alpha=0.8)
    ax2.plot(days, eact_vals * 10, color="#FB923C", linewidth=0.8,
             label="Soil evaporation", alpha=0.8)
    ax2.set_ylabel("Flux (mm/d)")
    ax2.set_xlabel("Days since simulation start")
    ax2.legend(loc="upper right")
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"  [OK] Timeseries plot: {output_path}")


def plot_validation(obs_data, sim_data, output_path, variable_name="Soil Moisture",
                    units="cm³/cm³", title=""):
    """
    Scatter plot of observed vs simulated values with metrics.

    Parameters
    ----------
    obs_data : array-like
        Observed values
    sim_data : array-like
        Simulated values (same length)
    output_path : str
        Path to save figure
    """
    obs = np.array(obs_data)
    sim = np.array(sim_data)

    # Remove NaN pairs
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs = obs[mask]
    sim = sim[mask]

    if len(obs) < 2:
        print("  [SKIP] Insufficient data for validation plot")
        return

    # Metrics
    bias = np.mean(sim - obs)
    rmse = np.sqrt(np.mean((sim - obs) ** 2))
    r = np.corrcoef(obs, sim)[0, 1] if len(obs) > 2 else 0
    nse = 1 - np.sum((sim - obs) ** 2) / np.sum((obs - np.mean(obs)) ** 2)

    fig, ax = plt.subplots(figsize=(7, 7))

    ax.scatter(obs, sim, c=COLOR_SIM, alpha=0.6, s=20, edgecolors="none")

    # 1:1 line
    vmin = min(obs.min(), sim.min())
    vmax = max(obs.max(), sim.max())
    margin = 0.05 * (vmax - vmin)
    ax.plot([vmin - margin, vmax + margin], [vmin - margin, vmax + margin],
            "k--", linewidth=1, label="1:1 line")

    # Metrics box
    metrics_text = (
        f"N = {len(obs)}\n"
        f"Bias = {bias:.4f} {units}\n"
        f"RMSE = {rmse:.4f} {units}\n"
        f"R = {r:.3f}\n"
        f"NSE = {nse:.3f}"
    )
    props = dict(boxstyle="round", facecolor="wheat", alpha=0.8)
    ax.text(0.05, 0.95, metrics_text, transform=ax.transAxes,
            fontsize=10, verticalalignment="top", bbox=props)

    ax.set_xlabel(f"Observed {variable_name} ({units})", fontsize=12)
    ax.set_ylabel(f"Simulated {variable_name} ({units})", fontsize=12)
    ax.set_title(f"SWAP Validation — {title}" if title else
                 f"SWAP Validation: {variable_name}")
    ax.set_aspect("equal")
    ax.set_xlim(vmin - margin, vmax + margin)
    ax.set_ylim(vmin - margin, vmax + margin)
    ax.grid(alpha=0.3)
    ax.legend()

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"  [OK] Validation plot: {output_path}")

    return {"bias": bias, "rmse": rmse, "r": r, "nse": nse, "n": len(obs)}


def validate_outputs(output_dir):
    """Check that figures were generated."""
    figures = list(Path(output_dir).glob("*.png"))
    if not figures:
        print(f"[WARN] No figures generated in {output_dir}")
        return False
    print(f"[OK] Generated {len(figures)} figures in {output_dir}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Plot SWAP results")
    parser.add_argument("--parsed-dir", type=str, required=True,
                        help="Directory with parsed CSV files")
    parser.add_argument("--output-dir", type=str, required=True,
                        help="Directory for output figures")
    parser.add_argument("--title", type=str, default="",
                        help="Plot title suffix")
    args = parser.parse_args()

    validate_inputs(args.parsed_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    # Load data
    balance_path = os.path.join(args.parsed_dir, "water_balance.csv")
    balances = read_csv_records(balance_path)
    plot_water_balance(
        balances,
        os.path.join(args.output_dir, "water_balance.png"),
        title=args.title,
    )

    inc_path = os.path.join(args.parsed_dir, "daily_increments.csv")
    inc_records = read_csv_records(inc_path)
    plot_timeseries(
        inc_records,
        os.path.join(args.output_dir, "daily_fluxes.png"),
        title=args.title,
    )

    validate_outputs(args.output_dir)


if __name__ == "__main__":
    main()
