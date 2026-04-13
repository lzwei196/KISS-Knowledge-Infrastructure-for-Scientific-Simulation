#!/usr/bin/env python3
"""
Validate HEC-HMS simulation against observed discharge.

Computes NSE, KGE, PBIAS, Pearson r between simulated and observed daily
discharge. Produces validation figure with time series and scatter plot.

Usage:
  python3 validate_hms.py \
    --sim_csv ./discharge_daily.csv \
    --obs_file /path/to/51080_bengbu.txt \
    --start_date 1981-01-01 --end_date 1990-12-31 \
    --output_figure ./validation.png
"""

import argparse
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check all input files exist."""
    errors = []
    if not os.path.isfile(args.sim_csv):
        errors.append(f"Simulation CSV not found: {args.sim_csv}")
    if not os.path.isfile(args.obs_file):
        errors.append(f"Observation file not found: {args.obs_file}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print("[validate_inputs] All inputs found.")


# ---------------------------------------------------------------------------
# Read observation data
# ---------------------------------------------------------------------------
def read_observations(obs_file):
    """
    Read observed discharge from Bengbu gauge file.
    Format: tab-separated: stcd | dates(YYYY-MM-DD) | z(water_level) | Q(discharge_m3s) | name
    """
    print(f"[read_obs] Reading: {obs_file}")

    # Try reading with tab separator
    try:
        df = pd.read_csv(obs_file, sep=r"\s+", header=None,
                         names=["stcd", "date", "z", "Q", "name"],
                         parse_dates=["date"], na_values=["-9999", "-99", "NA", ""])
    except Exception:
        # Fallback: try different separators
        df = pd.read_csv(obs_file, sep=None, engine="python", header=None,
                         parse_dates=[1], na_values=["-9999", "-99", "NA", ""])
        df.columns = ["stcd", "date", "z", "Q", "name"][:len(df.columns)]

    df = df.dropna(subset=["date"])
    df = df.set_index("date")
    df = df.sort_index()

    # Convert Q to numeric
    df["Q"] = pd.to_numeric(df["Q"], errors="coerce")

    # Drop invalid values
    df = df[df["Q"] > 0]

    print(f"  Period: {df.index[0]} to {df.index[-1]}")
    print(f"  Valid records: {len(df)}")
    print(f"  Mean Q: {df['Q'].mean():.1f} m³/s, Max Q: {df['Q'].max():.1f} m³/s")

    return df


# ---------------------------------------------------------------------------
# Read simulated discharge
# ---------------------------------------------------------------------------
def read_simulation(sim_csv):
    """Read simulated discharge CSV."""
    df = pd.read_csv(sim_csv, index_col=0, parse_dates=True)

    # Find discharge column
    q_col = None
    for col in ["sim_discharge_m3s", "q_total_m3s", "Q_m3s", "discharge"]:
        if col in df.columns:
            q_col = col
            break
    if q_col is None:
        q_col = df.columns[0]

    print(f"[read_sim] Using column: {q_col}")
    print(f"  Period: {df.index[0]} to {df.index[-1]}, {len(df)} days")
    return df, q_col


# ---------------------------------------------------------------------------
# Compute validation metrics
# ---------------------------------------------------------------------------
def compute_metrics(obs, sim):
    """
    Compute all validation metrics.

    Returns dict with: NSE, KGE, PBIAS, r, rmse, mean_obs, mean_sim
    """
    # Remove NaN pairs
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs = obs[mask]
    sim = sim[mask]

    if len(obs) < 10:
        print("ERROR: Too few valid data points for metrics")
        return None

    n = len(obs)
    obs_mean = np.mean(obs)
    sim_mean = np.mean(sim)
    obs_std = np.std(obs)
    sim_std = np.std(sim)

    # Nash-Sutcliffe Efficiency
    ss_res = np.sum((sim - obs) ** 2)
    ss_tot = np.sum((obs - obs_mean) ** 2)
    nse = 1.0 - ss_res / ss_tot if ss_tot > 0 else -999

    # Pearson correlation
    r = np.corrcoef(obs, sim)[0, 1] if len(obs) > 1 else 0

    # Kling-Gupta Efficiency
    alpha = sim_std / obs_std if obs_std > 0 else 0
    beta = sim_mean / obs_mean if obs_mean > 0 else 0
    kge = 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)

    # Percent Bias
    pbias = 100.0 * np.sum(sim - obs) / np.sum(obs) if np.sum(obs) > 0 else 999

    # RMSE
    rmse = np.sqrt(np.mean((sim - obs) ** 2))

    metrics = {
        "NSE": round(float(nse), 4),
        "KGE": round(float(kge), 4),
        "PBIAS": round(float(pbias), 2),
        "r": round(float(r), 4),
        "RMSE": round(float(rmse), 2),
        "n_days": int(n),
        "mean_obs_m3s": round(float(obs_mean), 1),
        "mean_sim_m3s": round(float(sim_mean), 1),
    }

    print("\n[metrics] Validation Results:")
    print(f"  NSE   = {metrics['NSE']:.4f}")
    print(f"  KGE   = {metrics['KGE']:.4f}")
    print(f"  PBIAS = {metrics['PBIAS']:.2f}%")
    print(f"  r     = {metrics['r']:.4f}")
    print(f"  RMSE  = {metrics['RMSE']:.1f} m³/s")
    print(f"  N     = {metrics['n_days']} days")

    if nse < 0:
        print("  WARNING: NSE < 0 — model is worse than mean! Check unit conversions.")

    return metrics


# ---------------------------------------------------------------------------
# Create validation figure
# ---------------------------------------------------------------------------
def create_figure(obs_dates, obs_q, sim_dates, sim_q, metrics, output_figure, title=""):
    """Create two-panel validation figure."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter, YearLocator

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [2, 1]})

    # --- Top panel: Time series ---
    ax1.plot(obs_dates, obs_q, color="black", linewidth=0.6, alpha=0.8, label="Observed")
    ax1.plot(sim_dates, sim_q, color="#2563EB", linewidth=0.6, alpha=0.7, label="Simulated")

    # Metrics box
    metrics_text = (
        f"NSE = {metrics['NSE']:.3f}\n"
        f"KGE = {metrics['KGE']:.3f}\n"
        f"PBIAS = {metrics['PBIAS']:.1f}%\n"
        f"r = {metrics['r']:.3f}"
    )
    ax1.text(0.02, 0.97, metrics_text, transform=ax1.transAxes,
             fontsize=9, verticalalignment="top",
             bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

    ax1.set_ylabel("Discharge (m³/s)")
    ax1.set_title(title or "HEC-HMS Validation")
    ax1.legend(loc="upper right", fontsize=9)
    ax1.xaxis.set_major_locator(YearLocator())
    ax1.xaxis.set_major_formatter(DateFormatter("%Y"))
    ax1.grid(True, alpha=0.3)

    # --- Bottom panel: Scatter plot ---
    # Align dates
    common_mask = ~(np.isnan(obs_q) | np.isnan(sim_q))
    obs_clean = obs_q[common_mask]
    sim_clean = sim_q[common_mask]

    ax2.scatter(obs_clean, sim_clean, s=2, alpha=0.3, color="#2563EB")
    q_max = max(np.nanmax(obs_clean), np.nanmax(sim_clean)) * 1.1
    ax2.plot([0, q_max], [0, q_max], "k--", linewidth=0.8, alpha=0.5, label="1:1 line")
    ax2.set_xlabel("Observed Q (m³/s)")
    ax2.set_ylabel("Simulated Q (m³/s)")
    ax2.set_title("Scatter: Simulated vs Observed")
    ax2.set_xlim(0, q_max)
    ax2.set_ylim(0, q_max)
    ax2.set_aspect("equal")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_figure) or ".", exist_ok=True)
    plt.savefig(output_figure, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n[figure] Saved: {output_figure}")


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------
def process(args):
    """Main validation workflow."""
    print("=" * 60)
    print("HEC-HMS Validation (Simulated vs Observed Discharge)")
    print("=" * 60)

    # 1. Read data
    obs_df = read_observations(args.obs_file)
    sim_df, q_col = read_simulation(args.sim_csv)

    # 2. Align time series
    start = pd.Timestamp(args.start_date) if args.start_date else max(obs_df.index[0], sim_df.index[0])
    end = pd.Timestamp(args.end_date) if args.end_date else min(obs_df.index[-1], sim_df.index[-1])

    obs_period = obs_df.loc[start:end, "Q"]
    sim_period = sim_df.loc[start:end, q_col]

    # Resample both to daily and align
    obs_daily = obs_period.resample("D").mean()
    sim_daily = sim_period.resample("D").mean()

    # Merge on common dates
    merged = pd.DataFrame({"obs": obs_daily, "sim": sim_daily}).dropna()
    print(f"\n[align] Common period: {merged.index[0]} to {merged.index[-1]}, {len(merged)} days")

    # 3. Compute metrics
    metrics = compute_metrics(merged["obs"].values, merged["sim"].values)

    # 4. Create figure
    if args.output_figure:
        station_name = os.path.basename(args.obs_file).replace(".txt", "")
        title = f"hydrology — Bengbu 1981-1990"
        create_figure(
            merged.index, merged["obs"].values,
            merged.index, merged["sim"].values,
            metrics, args.output_figure, title=title
        )

    # 5. Write metrics JSON
    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"[write] Metrics: {args.output_json}")

    return metrics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Validate HEC-HMS against observations")
    parser.add_argument("--sim_csv", required=True, help="Simulated discharge CSV")
    parser.add_argument("--obs_file", required=True, help="Observed discharge file")
    parser.add_argument("--start_date", default=None, help="Validation start date")
    parser.add_argument("--end_date", default=None, help="Validation end date")
    parser.add_argument("--output_figure", default=None, help="Output figure path")
    parser.add_argument("--output_json", default=None, help="Output metrics JSON")
    args = parser.parse_args()

    validate_inputs(args)
    metrics = process(args)
    return metrics


if __name__ == "__main__":
    main()
