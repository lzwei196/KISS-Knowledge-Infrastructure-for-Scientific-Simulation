#!/usr/bin/env python3
"""
plot_reservoir_operations.py — Multi-panel visualization of reservoir operations.

Creates a 3-panel figure:
  Panel 1: Storage volume vs time with control curve overlay
  Panel 2: Inflow vs release vs spill
  Panel 3: Supply reliability (demand vs actual supply)

Usage:
    python plot_reservoir_operations.py \
        --storage_csv results/storage_timeseries.csv \
        --release_csv results/release_timeseries.csv \
        --inflow_csv inflow.csv \
        --rules_json operating_rules.json \
        --output results/reservoir_operations.png \
        --title "Meishan Reservoir Operations"

    # Minimal (just storage + release):
    python plot_reservoir_operations.py \
        --storage_csv results/storage_timeseries.csv \
        --release_csv results/release_timeseries.csv \
        --output results/reservoir_operations.png

Output:
    PNG figure file.
    Exit codes: 0 = success, 2 = input error, 3 = runtime error
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def load_storage(csv_path):
    """Load storage timeseries CSV."""
    df = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
    return df


def load_release(csv_path):
    """Load release/flow timeseries CSV."""
    df = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
    return df


def load_inflow(csv_path):
    """Load inflow CSV."""
    df = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
    return df


def load_control_curve(rules_json_path):
    """Load monthly control curve from rules JSON."""
    with open(rules_json_path, "r") as f:
        data = json.load(f)
    targets = data.get("monthly_targets", {})
    fractions = targets.get("fractions", [])
    volumes = targets.get("volumes_m3", [])
    capacity_m3 = data.get("capacity_m3", None)
    return fractions, volumes, capacity_m3


def plot_operations(storage_df, release_df, inflow_df=None,
                    control_fractions=None, capacity_m3=None,
                    title="Reservoir Operations", output_path="reservoir_ops.png"):
    """Create multi-panel figure."""

    n_panels = 2
    if release_df is not None:
        # Check if there are demand columns
        demand_cols = [c for c in release_df.columns
                       if any(k in c.lower() for k in ["demand", "irrigation",
                                                         "municipal", "environmental"])]
        if demand_cols:
            n_panels = 3

    fig, axes = plt.subplots(n_panels, 1, figsize=(14, 4 * n_panels),
                              sharex=True)
    if n_panels == 1:
        axes = [axes]

    # ── Panel 1: Storage ──
    ax = axes[0]
    vol_cols = [c for c in storage_df.columns if "volume" in c.lower()]

    for col in vol_cols:
        label = col.replace("_volume_m3", "").replace("_", " ").title()
        values_mcm = storage_df[col] / 1e6
        ax.fill_between(storage_df.index, 0, values_mcm,
                        alpha=0.3, label=f"{label} Storage")
        ax.plot(storage_df.index, values_mcm, linewidth=0.8)

    # Control curve overlay
    if control_fractions and capacity_m3:
        # Map monthly fractions to dates
        dates = storage_df.index
        curve_values = np.array([
            control_fractions[d.month - 1] * capacity_m3 / 1e6
            for d in dates
        ])
        ax.plot(dates, curve_values, "r--", linewidth=1.5,
                label="Control Curve", alpha=0.8)

    # Max and min lines
    if capacity_m3:
        ax.axhline(y=capacity_m3 / 1e6, color="darkred", linestyle=":",
                   linewidth=0.8, alpha=0.5, label="Max Capacity")
        ax.axhline(y=capacity_m3 * 0.10 / 1e6, color="orange", linestyle=":",
                   linewidth=0.8, alpha=0.5, label="Dead Storage (10%)")

    ax.set_ylabel("Storage (MCM)")
    ax.set_title(f"{title} — Storage Volume")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)

    # ── Panel 2: Flows ──
    ax = axes[1]

    # Inflow
    if inflow_df is not None and "inflow_m3s" in inflow_df.columns:
        ax.plot(inflow_df.index, inflow_df["inflow_m3s"],
                color="steelblue", linewidth=0.6, alpha=0.7, label="Inflow")

    # Release and spill
    if release_df is not None:
        release_cols = [c for c in release_df.columns if "release" in c.lower()]
        spill_cols = [c for c in release_df.columns if "spill" in c.lower()]
        downstream_cols = [c for c in release_df.columns if "downstream" in c.lower()]

        for col in release_cols:
            ax.plot(release_df.index, release_df[col],
                    color="darkgreen", linewidth=0.8, label="Release")
        for col in spill_cols:
            ax.fill_between(release_df.index, 0, release_df[col],
                            color="red", alpha=0.3, label="Spill")
        for col in downstream_cols:
            ax.plot(release_df.index, release_df[col],
                    color="purple", linewidth=0.6, alpha=0.6,
                    label="Downstream Total")

    ax.set_ylabel("Flow (m\u00b3/s)")
    ax.set_title(f"{title} — Inflow vs Release")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)

    # ── Panel 3: Demand satisfaction (if applicable) ──
    if n_panels >= 3 and demand_cols:
        ax = axes[2]
        colors = ["teal", "orange", "purple", "brown"]
        for i, col in enumerate(demand_cols):
            color = colors[i % len(colors)]
            label = col.replace("_m3s", "").replace("_", " ").title()
            ax.plot(release_df.index, release_df[col],
                    color=color, linewidth=0.8, label=label)

        ax.set_ylabel("Flow (m\u00b3/s)")
        ax.set_title(f"{title} — Demand Satisfaction")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3)

    # Format x-axis
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    axes[-1].xaxis.set_major_locator(mdates.YearLocator())
    plt.xticks(rotation=45)
    axes[-1].set_xlabel("Date")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Plot reservoir operations results"
    )

    parser.add_argument("--storage_csv", type=str, required=True,
                        help="Storage timeseries CSV")
    parser.add_argument("--release_csv", type=str, default=None,
                        help="Release/flow timeseries CSV")
    parser.add_argument("--inflow_csv", type=str, default=None,
                        help="Inflow timeseries CSV (optional)")
    parser.add_argument("--rules_json", type=str, default=None,
                        help="Operating rules JSON for control curve overlay")
    parser.add_argument("--capacity_mcm", type=float, default=None,
                        help="Reservoir capacity in MCM (for reference lines)")

    parser.add_argument("--output", type=str, required=True,
                        help="Output PNG file path")
    parser.add_argument("--title", type=str, default="Reservoir Operations",
                        help="Figure title")

    args = parser.parse_args()

    try:
        # Load data
        storage_df = load_storage(args.storage_csv)

        release_df = None
        if args.release_csv:
            release_df = load_release(args.release_csv)

        inflow_df = None
        if args.inflow_csv:
            inflow_df = load_inflow(args.inflow_csv)

        # Control curve
        control_fractions = None
        capacity_m3 = None
        if args.rules_json:
            control_fractions, _, capacity_m3 = load_control_curve(args.rules_json)

        if args.capacity_mcm:
            capacity_m3 = args.capacity_mcm * 1e6

        # Plot
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        plot_operations(
            storage_df, release_df, inflow_df,
            control_fractions, capacity_m3,
            title=args.title,
            output_path=str(out_path)
        )

        print(json.dumps({
            "status": "OK",
            "output": str(out_path),
            "panels": 3 if release_df is not None else 1,
        }))
        sys.exit(0)

    except Exception as e:
        print(json.dumps({"error": str(e), "status": "FAIL"}))
        sys.exit(3)


if __name__ == "__main__":
    main()
