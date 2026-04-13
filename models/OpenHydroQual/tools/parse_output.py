#!/usr/bin/env python3
"""
parse_output.py - Parse OpenHydroQual output files and compute metrics.

Reads the OHQ output CSV (output.txt), extracts time series for selected
variables, computes performance metrics, and optionally generates plots.

CRITICAL: OHQ output time is in DAYS from simulation start.
CRITICAL: Column names follow the pattern "block_name:variable_name" or
  "link_name:variable_name".
CRITICAL: Concentration units in output are g/m^3 (= mg/L).

Usage:
  python parse_output.py --input output.txt --output results.csv

  python parse_output.py --input output.txt --output results.csv \\
    --variables "Pond (6):O2:concentration,Pond (6):DOM:concentration" \\
    --plot results.png

  python parse_output.py --input output.txt --observed observed.csv \\
    --output results.csv --metrics --plot validation.png
"""

import argparse
import csv
import json
import math
import os
import sys


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.observed and not os.path.isfile(args.observed):
        errors.append(f"Observed data file not found: {args.observed}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def read_ohq_output(filepath):
    """Read OHQ output CSV file.

    Returns:
        headers: list of column names
        data: list of rows, each row is a list of floats
    """
    headers = []
    data = []

    with open(filepath, "r") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if not row:
                continue

            # First non-empty row with non-numeric first field is header
            if i == 0:
                try:
                    float(row[0])
                    # No header, all numeric
                    headers = [f"col_{j}" for j in range(len(row))]
                    headers[0] = "time"
                    data.append([float(x) if x.strip() else float("nan") for x in row])
                except ValueError:
                    headers = [h.strip() for h in row]
                    continue

            try:
                values = []
                for x in row:
                    x = x.strip()
                    if x == "" or x.lower() == "nan":
                        values.append(float("nan"))
                    else:
                        values.append(float(x))
                data.append(values)
            except ValueError:
                continue

    return headers, data


def extract_variable(headers, data, variable_name):
    """Extract a single variable time series from output data.

    Args:
        headers: column headers
        data: 2D data array
        variable_name: exact column name or substring match

    Returns:
        times: list of time values
        values: list of variable values
    """
    # Try exact match first
    col_idx = None
    for i, h in enumerate(headers):
        if h == variable_name:
            col_idx = i
            break

    # Try substring match
    if col_idx is None:
        for i, h in enumerate(headers):
            if variable_name.lower() in h.lower():
                col_idx = i
                break

    if col_idx is None:
        return None, None

    times = []
    values = []
    time_idx = 0  # First column is always time

    for row in data:
        if len(row) > col_idx:
            t = row[time_idx]
            v = row[col_idx]
            if not (math.isnan(t) or math.isnan(v)):
                times.append(t)
                values.append(v)

    return times, values


def compute_nse(obs, sim):
    """Compute Nash-Sutcliffe Efficiency.

    NSE = 1 - sum((obs-sim)^2) / sum((obs-mean(obs))^2)
    Range: -inf to 1. NSE=1 is perfect, NSE>0.5 is acceptable.
    """
    if len(obs) != len(sim) or len(obs) < 2:
        return float("nan")

    mean_obs = sum(obs) / len(obs)
    ss_res = sum((o - s) ** 2 for o, s in zip(obs, sim))
    ss_tot = sum((o - mean_obs) ** 2 for o in obs)

    if ss_tot == 0:
        return float("nan")

    return 1.0 - ss_res / ss_tot


def compute_rmse(obs, sim):
    """Compute Root Mean Square Error."""
    if len(obs) != len(sim) or len(obs) == 0:
        return float("nan")

    mse = sum((o - s) ** 2 for o, s in zip(obs, sim)) / len(obs)
    return math.sqrt(mse)


def compute_pbias(obs, sim):
    """Compute Percent Bias.

    PBIAS = 100 * sum(obs-sim) / sum(obs)
    Optimal = 0. Positive = underestimation.
    """
    if len(obs) != len(sim) or len(obs) == 0:
        return float("nan")

    sum_obs = sum(obs)
    if sum_obs == 0:
        return float("nan")

    return 100.0 * sum(o - s for o, s in zip(obs, sim)) / sum_obs


def compute_r_squared(obs, sim):
    """Compute coefficient of determination (R^2)."""
    if len(obs) != len(sim) or len(obs) < 2:
        return float("nan")

    n = len(obs)
    mean_o = sum(obs) / n
    mean_s = sum(sim) / n

    cov = sum((o - mean_o) * (s - mean_s) for o, s in zip(obs, sim))
    var_o = sum((o - mean_o) ** 2 for o in obs)
    var_s = sum((s - mean_s) ** 2 for s in sim)

    denom = math.sqrt(var_o * var_s)
    if denom == 0:
        return float("nan")

    r = cov / denom
    return r ** 2


def compute_kge(obs, sim):
    """Compute Kling-Gupta Efficiency.

    KGE = 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2)
    where r=correlation, alpha=std_sim/std_obs, beta=mean_sim/mean_obs
    """
    if len(obs) != len(sim) or len(obs) < 2:
        return float("nan")

    n = len(obs)
    mean_o = sum(obs) / n
    mean_s = sum(sim) / n

    if mean_o == 0:
        return float("nan")

    std_o = math.sqrt(sum((o - mean_o) ** 2 for o in obs) / n)
    std_s = math.sqrt(sum((s - mean_s) ** 2 for s in sim) / n)

    if std_o == 0:
        return float("nan")

    cov = sum((o - mean_o) * (s - mean_s) for o, s in zip(obs, sim)) / n
    r = cov / (std_o * std_s) if std_s > 0 else 0

    alpha = std_s / std_o
    beta = mean_s / mean_o

    kge = 1.0 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return kge


def generate_plot(times, variables_data, output_path, obs_data=None, metrics=None):
    """Generate a time series plot using matplotlib.

    Args:
        times: list of time values
        variables_data: dict of {name: values}
        output_path: path to save PNG
        obs_data: optional dict of {name: (times, values)} for observations
        metrics: optional dict of metric values to display
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return {"error": "matplotlib not installed"}

    fig, axes = plt.subplots(
        len(variables_data), 1,
        figsize=(12, 3 * len(variables_data)),
        sharex=True
    )

    if len(variables_data) == 1:
        axes = [axes]

    for ax, (name, values) in zip(axes, variables_data.items()):
        # Simulated
        ax.plot(times[:len(values)], values, color="#2563EB",
                linewidth=1.5, label="Simulated")

        # Observed
        if obs_data and name in obs_data:
            ot, ov = obs_data[name]
            ax.plot(ot, ov, "o", color="black", markersize=3,
                    label="Observed", zorder=5)

        ax.set_ylabel(name.split(":")[-1] if ":" in name else name)
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(True, alpha=0.3)

        # Add metrics box
        if metrics and name in metrics:
            m = metrics[name]
            text = "\n".join(f"{k}={v:.3f}" for k, v in m.items())
            ax.text(0.98, 0.95, text, transform=ax.transAxes,
                    fontsize=8, verticalalignment="top",
                    horizontalalignment="right",
                    bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

    axes[-1].set_xlabel("Time (days)")
    fig.suptitle("OpenHydroQual Simulation Results", fontsize=12)
    plt.tight_layout()

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()

    return {"saved": output_path}


def write_csv_output(filepath, headers_out, data_out, times):
    """Write extracted variables to clean CSV."""
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time"] + list(headers_out.keys()))
        for i, t in enumerate(times):
            row = [f"{t:.6f}"]
            for name, values in headers_out.items():
                if i < len(values):
                    row.append(f"{values[i]:.6f}")
                else:
                    row.append("")
            writer.writerow(row)


def process(args):
    """Parse output and compute metrics."""
    result = {"status": "success", "warnings": []}

    # Read output
    headers, data = read_ohq_output(args.input)
    result["n_columns"] = len(headers)
    result["n_rows"] = len(data)
    result["columns"] = headers

    if not data:
        result["status"] = "error"
        result["errors"] = ["No data rows found in output file"]
        return result

    # Extract requested variables
    variables = {}
    times = None

    if args.variables:
        var_names = [v.strip() for v in args.variables.split(",")]
    else:
        # Default: extract all non-time columns
        var_names = [h for h in headers if h.lower() != "time" and h != "col_0"]

    for vname in var_names:
        t, v = extract_variable(headers, data, vname)
        if t is not None:
            variables[vname] = v
            if times is None:
                times = t
        else:
            result["warnings"].append(f"Variable not found: {vname}")

    if not variables:
        result["status"] = "error"
        result["errors"] = ["No matching variables found in output"]
        return result

    result["extracted_variables"] = list(variables.keys())
    for name, values in variables.items():
        result[f"stats_{name}"] = {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
            "n": len(values),
        }

    # Write CSV output
    if args.output:
        outdir = os.path.dirname(args.output)
        if outdir:
            os.makedirs(outdir, exist_ok=True)
        write_csv_output(args.output, variables, data, times)
        result["output_file"] = args.output

    # Compute metrics if observed data provided
    metrics_dict = {}
    if args.observed and args.metrics:
        obs_headers, obs_data = read_ohq_output(args.observed)
        for vname in variables:
            obs_t, obs_v = extract_variable(obs_headers, obs_data, vname)
            if obs_t is not None and obs_v is not None:
                sim_v = variables[vname]
                # Align by length (simple approach)
                n = min(len(obs_v), len(sim_v))
                metrics_dict[vname] = {
                    "NSE": round(compute_nse(obs_v[:n], sim_v[:n]), 4),
                    "RMSE": round(compute_rmse(obs_v[:n], sim_v[:n]), 4),
                    "PBIAS": round(compute_pbias(obs_v[:n], sim_v[:n]), 4),
                    "R2": round(compute_r_squared(obs_v[:n], sim_v[:n]), 4),
                    "KGE": round(compute_kge(obs_v[:n], sim_v[:n]), 4),
                }
        result["metrics"] = metrics_dict

    # Generate plot
    if args.plot:
        plot_result = generate_plot(
            times, variables, args.plot,
            metrics=metrics_dict if metrics_dict else None
        )
        result["plot"] = plot_result

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse OpenHydroQual output and compute metrics"
    )
    parser.add_argument("--input", required=True,
                        help="Path to OHQ output file (output.txt)")
    parser.add_argument("--output", default=None,
                        help="Path to write extracted CSV")
    parser.add_argument("--variables", default=None,
                        help="Comma-separated list of variables to extract")
    parser.add_argument("--observed", default=None,
                        help="Path to observed data CSV for comparison")
    parser.add_argument("--metrics", action="store_true",
                        help="Compute performance metrics (requires --observed)")
    parser.add_argument("--plot", default=None,
                        help="Path to save plot PNG")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
