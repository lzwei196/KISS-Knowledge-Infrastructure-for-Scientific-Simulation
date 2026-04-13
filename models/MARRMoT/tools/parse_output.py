"""
MARRMoT Output Parser
======================
Parse MARRMoT simulation output (CSV from run_marrmot.py or raw Octave
output) into standardized CSV and compute validation metrics against
observed streamflow.

Metrics computed:
  - NSE  (Nash-Sutcliffe Efficiency)
  - KGE  (Kling-Gupta Efficiency, 2009 formulation)
  - PBIAS (Percent Bias)
  - RMSE (Root Mean Square Error)
  - r    (Pearson correlation coefficient)

CRITICAL: Observed streamflow must be in mm/d, same as MARRMoT output.
  If observations are in m3/s, convert: Q_mm_d = Q_m3s * 86400 / (A_km2 * 1e6) * 1000
  Getting this wrong produces NSE << 0 and huge PBIAS (dt_010).

Usage:
  python parse_output.py --input run_output.json \
    --observed observed_q.csv \
    --output results.csv \
    --figure validation.png

  python parse_output.py --input marrmot_timeseries.csv \
    --output results.csv
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def validate_inputs(args):
    """Validate input files and arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.observed and not os.path.isfile(args.observed):
        errors.append(f"Observed data file not found: {args.observed}")

    if args.area_km2 is not None and args.area_km2 <= 0:
        errors.append(f"Catchment area must be positive, got {args.area_km2}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency. Perfect = 1, baseline = 0."""
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return np.nan
    ss_res = np.sum((obs - sim) ** 2)
    ss_tot = np.sum((obs - np.mean(obs)) ** 2)
    if ss_tot == 0:
        return np.nan
    return 1 - ss_res / ss_tot


def compute_kge(obs, sim):
    """
    Kling-Gupta Efficiency (Gupta et al. 2009).
    Returns KGE and components (r, alpha, beta).
    """
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return np.nan, (np.nan, np.nan, np.nan)

    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else np.nan
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else np.nan

    kge = 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)
    return kge, (r, alpha, beta)


def compute_pbias(obs, sim):
    """Percent Bias. 0 = perfect, positive = model overestimates."""
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if np.sum(obs) == 0:
        return np.nan
    return 100.0 * np.sum(sim - obs) / np.sum(obs)


def compute_rmse(obs, sim):
    """Root Mean Square Error."""
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return np.nan
    return np.sqrt(np.mean((obs - sim) ** 2))


def load_simulated(input_path):
    """Load simulated data from JSON or CSV."""
    if input_path.endswith(".json"):
        with open(input_path) as f:
            data = json.load(f)
        csv_path = data.get("output_csv", None)
        if csv_path and os.path.isfile(csv_path):
            return load_csv_timeseries(csv_path), data
        return None, data
    else:
        return load_csv_timeseries(input_path), {}


def load_csv_timeseries(csv_path):
    """Load timeseries CSV (timestep, Q_mm_d, Ea_mm_d)."""
    if pd is not None:
        df = pd.read_csv(csv_path)
        return df
    else:
        # Fallback: numpy
        data = np.genfromtxt(csv_path, delimiter=",", skip_header=1)
        return data


def load_observed(obs_path, area_km2=None, obs_col="Q_mm_d",
                  date_col="date", obs_unit="mm_d"):
    """
    Load observed streamflow. Convert m3/s to mm/d if needed.
    """
    if pd is None:
        print(json.dumps({"status": "error",
                          "errors": ["pandas required for observed data"]}))
        sys.exit(1)

    df = pd.read_csv(obs_path, parse_dates=[date_col] if date_col in
                     pd.read_csv(obs_path, nrows=0).columns else False)

    if obs_col not in df.columns:
        # Try common alternatives
        for alt in ["Q", "discharge", "flow", "q_mm_d", "streamflow"]:
            if alt in df.columns:
                obs_col = alt
                break

    if obs_col not in df.columns:
        return None, f"Column '{obs_col}' not found in {obs_path}"

    q_obs = df[obs_col].values.astype(float)

    # Convert units if needed
    if obs_unit == "m3_s" and area_km2:
        q_obs = q_obs * 86400.0 / (area_km2 * 1e6) * 1000.0
        print(f"Converted observed Q from m3/s to mm/d (area={area_km2} km2)",
              file=sys.stderr)
    elif obs_unit == "m3_s" and not area_km2:
        print("WARNING: Observed Q in m3/s but no --area-km2 provided! "
              "Cannot convert to mm/d (dt_010).", file=sys.stderr)

    return q_obs, None


def make_validation_figure(obs, sim, metrics, figure_path, title="MARRMoT"):
    """Create validation figure: observed vs simulated hydrograph."""
    if not HAS_MPL:
        print("matplotlib not available, skipping figure", file=sys.stderr)
        return

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), height_ratios=[3, 1],
                              sharex=True)

    timesteps = np.arange(len(sim))

    # Hydrograph
    ax = axes[0]
    ax.plot(timesteps, obs[:len(sim)], color="black", linewidth=0.8,
            label="Observed", alpha=0.8)
    ax.plot(timesteps, sim, color="#2563EB", linewidth=0.8,
            label="Simulated", alpha=0.8)
    ax.set_ylabel("Streamflow (mm/d)")
    ax.set_title(title)
    ax.legend(loc="upper left")

    # Metrics box
    metrics_text = "\n".join([
        f"NSE = {metrics.get('NSE', np.nan):.3f}",
        f"KGE = {metrics.get('KGE', np.nan):.3f}",
        f"PBIAS = {metrics.get('PBIAS', np.nan):.1f}%",
        f"r = {metrics.get('r', np.nan):.3f}",
    ])
    props = dict(boxstyle="round", facecolor="white", alpha=0.9,
                 edgecolor="gray")
    ax.text(0.98, 0.95, metrics_text, transform=ax.transAxes,
            fontsize=10, verticalalignment="top", horizontalalignment="right",
            bbox=props, fontfamily="monospace")

    # Residuals
    ax2 = axes[1]
    residuals = sim - obs[:len(sim)]
    ax2.bar(timesteps, residuals, color="#2563EB", alpha=0.5, width=1.0)
    ax2.axhline(y=0, color="black", linewidth=0.5)
    ax2.set_ylabel("Residual (mm/d)")
    ax2.set_xlabel("Timestep (days)")

    plt.tight_layout()
    os.makedirs(os.path.dirname(figure_path) or ".", exist_ok=True)
    plt.savefig(figure_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved figure to {figure_path}", file=sys.stderr)


def process(args):
    """Main processing: parse output and compute metrics."""
    sim_df, run_info = load_simulated(args.input)

    if sim_df is None:
        return {"status": "error",
                "errors": ["Could not load simulated timeseries"]}

    if isinstance(sim_df, np.ndarray):
        q_sim = sim_df[:, 1]  # Q_mm_d column
        ea_sim = sim_df[:, 2] if sim_df.shape[1] > 2 else None
    else:
        q_sim = sim_df["Q_mm_d"].values
        ea_sim = sim_df["Ea_mm_d"].values if "Ea_mm_d" in sim_df.columns else None

    result = {
        "status": "success",
        "n_timesteps": len(q_sim),
        "Q_mean_mm_d": float(np.nanmean(q_sim)),
        "Q_max_mm_d": float(np.nanmax(q_sim)),
        "Q_total_mm": float(np.nansum(q_sim)),
        "warnings": [],
    }

    if ea_sim is not None:
        result["Ea_mean_mm_d"] = float(np.nanmean(ea_sim))
        result["Ea_total_mm"] = float(np.nansum(ea_sim))

    # Compute metrics if observed data available
    metrics = {}
    if args.observed:
        q_obs, err = load_observed(
            args.observed, args.area_km2, args.obs_col,
            args.date_col, args.obs_unit)

        if err:
            result["warnings"].append(f"Could not load observed data: {err}")
        elif q_obs is not None:
            # Align lengths
            n = min(len(q_sim), len(q_obs))
            q_s = q_sim[:n]
            q_o = q_obs[:n]

            nse = compute_nse(q_o, q_s)
            kge, (r, alpha, beta) = compute_kge(q_o, q_s)
            pbias = compute_pbias(q_o, q_s)
            rmse = compute_rmse(q_o, q_s)

            metrics = {
                "NSE": round(float(nse), 4),
                "KGE": round(float(kge), 4),
                "r": round(float(r), 4),
                "alpha": round(float(alpha), 4),
                "beta": round(float(beta), 4),
                "PBIAS": round(float(pbias), 2),
                "RMSE": round(float(rmse), 4),
                "n_obs": n,
            }
            result["metrics"] = metrics

            # Sanity check: if NSE < -1, likely unit mismatch
            if nse < -1:
                result["warnings"].append(
                    f"NSE = {nse:.2f} << 0 -- likely unit mismatch "
                    "between simulated and observed (dt_010)")

            # Generate figure
            if args.figure:
                title = run_info.get("model", "MARRMoT")
                make_validation_figure(q_o, q_s, metrics,
                                       args.figure, title=title)
                result["figure"] = args.figure

    # Write output CSV
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write("timestep,Q_sim_mm_d")
            if ea_sim is not None:
                f.write(",Ea_sim_mm_d")
            f.write("\n")
            for i in range(len(q_sim)):
                f.write(f"{i+1},{q_sim[i]:.6f}")
                if ea_sim is not None:
                    f.write(f",{ea_sim[i]:.6f}")
                f.write("\n")
        result["output_csv"] = args.output

    return result


def validate_outputs(result):
    """Validate parsed outputs."""
    if result["status"] != "success":
        return result

    warnings = result.get("warnings", [])

    if result["Q_mean_mm_d"] < 0:
        warnings.append("Negative mean streamflow -- check model output")
    if result["Q_mean_mm_d"] > 100:
        warnings.append("Mean Q > 100 mm/d -- unrealistically high")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse MARRMoT output and compute validation metrics")
    parser.add_argument("--input", required=True,
                        help="Input file (JSON from run_marrmot.py or CSV)")
    parser.add_argument("--observed", default=None,
                        help="Observed streamflow CSV")
    parser.add_argument("--obs-col", default="Q_mm_d",
                        help="Observed Q column name")
    parser.add_argument("--obs-unit", default="mm_d",
                        choices=["mm_d", "m3_s"],
                        help="Unit of observed streamflow")
    parser.add_argument("--area-km2", type=float, default=None,
                        help="Catchment area in km2 (for m3/s to mm/d)")
    parser.add_argument("--date-col", default="date",
                        help="Date column name in observed CSV")
    parser.add_argument("--output", default=None,
                        help="Output CSV file")
    parser.add_argument("--figure", default=None,
                        help="Output figure path (PNG)")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
