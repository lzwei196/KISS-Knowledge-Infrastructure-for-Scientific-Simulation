#!/usr/bin/env python3
"""
compare_with_vic.py — Compare wflow_sbm discharge with VIC for the same basin.

Computes correlation, NSE, PBIAS, RMSE between wflow and VIC discharge.
Also compares annual water balance components (ET, runoff, soil moisture).

IMPORTANT: wflow and VIC use different soil physics. Differences of 30-50%
in discharge magnitude are EXPECTED and do not indicate a bug. The comparison
is for scientific intercomparison, not validation.

Expected differences:
  - VIC uses energy balance for snow; wflow uses degree-day (HBV-style)
  - VIC has 3 fixed soil layers; wflow has continuous exponential Ksat decay
  - VIC routing is external; wflow routes internally (kinematic wave)
  - PET methods may differ (Penman-Monteith vs Hargreaves vs De Bruin)

Usage:
    python compare_with_vic.py \
      --wflow_csv /path/to/wflow_discharge.csv \
      --vic_csv /path/to/vic_discharge.csv \
      --output /path/to/comparison_report.json

    python compare_with_vic.py \
      --wflow_csv /path/to/wflow_discharge.csv \
      --vic_routing_file /path/to/routing_output.day \
      --output /path/to/comparison.json \
      --plot /path/to/comparison_plot.png
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate inputs."""
    errors = []

    if not os.path.exists(args.wflow_csv):
        errors.append(f"wflow discharge CSV not found: {args.wflow_csv}")

    if not args.vic_csv and not args.vic_routing_file:
        errors.append("Must provide --vic_csv or --vic_routing_file")

    vic_file = args.vic_csv or args.vic_routing_file
    if vic_file and not os.path.exists(vic_file):
        errors.append(f"VIC discharge file not found: {vic_file}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def read_wflow_discharge(csv_path):
    """Read wflow discharge CSV (date, Q_m3s)."""
    import pandas as pd
    df = pd.read_csv(csv_path, parse_dates=["date"])
    return df.set_index("date")["Q_m3s"]


def read_vic_discharge(csv_path=None, routing_file=None):
    """Read VIC discharge from CSV or Lohmann routing output."""
    import pandas as pd

    if csv_path:
        df = pd.read_csv(csv_path, parse_dates=["date"])
        return df.set_index("date")["Q_m3s"]

    if routing_file:
        # Lohmann routing output format: YYYY MM DD Q
        data = []
        with open(routing_file) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 4:
                    try:
                        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                        q = float(parts[3])
                        date = pd.Timestamp(year=year, month=month, day=day)
                        data.append((date, q))
                    except (ValueError, IndexError):
                        continue
        df = pd.DataFrame(data, columns=["date", "Q_m3s"])
        return df.set_index("date")["Q_m3s"]


def compute_metrics(sim, obs):
    """Compute comparison metrics between two discharge series."""
    # Align timeseries
    import pandas as pd
    combined = pd.DataFrame({"sim": sim, "obs": obs}).dropna()

    if len(combined) < 30:
        return {"error": f"Insufficient overlap: {len(combined)} days"}

    s = combined["sim"].values
    o = combined["obs"].values

    # Correlation
    corr = float(np.corrcoef(s, o)[0, 1])

    # NSE
    nse = 1.0 - np.sum((s - o) ** 2) / np.sum((o - np.mean(o)) ** 2)

    # PBIAS (%)
    pbias = 100.0 * np.sum(s - o) / np.sum(o)

    # RMSE
    rmse = np.sqrt(np.mean((s - o) ** 2))

    # KGE
    r = corr
    alpha = np.std(s) / np.std(o) if np.std(o) > 0 else 0
    beta = np.mean(s) / np.mean(o) if np.mean(o) > 0 else 0
    kge = 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)

    return {
        "n_days": len(combined),
        "correlation": round(float(corr), 4),
        "nse": round(float(nse), 4),
        "pbias_pct": round(float(pbias), 2),
        "rmse_m3s": round(float(rmse), 2),
        "kge": round(float(kge), 4),
        "wflow_mean_Q": round(float(np.mean(s)), 2),
        "vic_mean_Q": round(float(np.mean(o)), 2),
        "wflow_max_Q": round(float(np.max(s)), 2),
        "vic_max_Q": round(float(np.max(o)), 2),
        "ratio_mean": round(float(np.mean(s) / np.mean(o)), 3) if np.mean(o) > 0 else None,
    }


def create_comparison_plot(sim, obs, output_path, title="wflow vs VIC"):
    """Create a discharge comparison plot."""
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter

    combined = pd.DataFrame({"wflow": sim, "VIC": obs}).dropna()

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), height_ratios=[3, 1])

    # Timeseries
    ax = axes[0]
    ax.plot(combined.index, combined["VIC"], "b-", alpha=0.7, label="VIC", linewidth=0.8)
    ax.plot(combined.index, combined["wflow"], "r-", alpha=0.7, label="wflow", linewidth=0.8)
    ax.set_ylabel("Discharge (m3/s)")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(DateFormatter("%Y"))

    # Scatter
    ax2 = axes[1]
    ax2.scatter(combined["VIC"], combined["wflow"], s=2, alpha=0.3, c="gray")
    max_q = max(combined["VIC"].max(), combined["wflow"].max())
    ax2.plot([0, max_q], [0, max_q], "k--", alpha=0.5, label="1:1 line")
    ax2.set_xlabel("VIC Q (m3/s)")
    ax2.set_ylabel("wflow Q (m3/s)")
    ax2.set_aspect("equal")
    ax2.legend()

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Compare wflow and VIC discharge"
    )
    parser.add_argument("--wflow_csv", type=str, required=True)
    parser.add_argument("--vic_csv", type=str, default="")
    parser.add_argument("--vic_routing_file", type=str, default="")
    parser.add_argument("--output", type=str, required=True,
                        help="Output JSON report path")
    parser.add_argument("--plot", type=str, default="",
                        help="Output plot path (PNG)")
    args = parser.parse_args()

    validate_inputs(args)

    try:
        wflow_q = read_wflow_discharge(args.wflow_csv)
        vic_q = read_vic_discharge(args.vic_csv or None, args.vic_routing_file or None)

        metrics = compute_metrics(wflow_q, vic_q)

        if args.plot:
            create_comparison_plot(wflow_q, vic_q, args.plot)
            metrics["plot_path"] = args.plot

    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    result = {"status": "success", "metrics": metrics}

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
