#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
==========================================
Tool ID:      plot_breach_hydrograph
Stage:        s8_visualization
Description:  Plot DLBreach breach outflow hydrograph showing breach flow,
              spillway/gate flow, total discharge, and water levels.

Inputs:
  --breach_csv:   CSV from extract_breach_results
  --output:       Output PNG path
  --title:        Plot title (optional)

Outputs:
  - PNG plot file
  - JSON with plot_path, peak_q_annotation

Exit codes:
  0 -- success
  1 -- results file not found
  2 -- plotting error
  3 -- output image not generated
"""

import sys
import json
import csv
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def read_results(filepath):
    """Read breach results CSV."""
    data = {"time_hr": [], "breach_flow_m3s": [], "spillway_gate_flow_m3s": [],
            "upstream_wsl_m": [], "downstream_wsl_m": [],
            "breach_bottom_elev_m": [], "breach_top_width_m": []}

    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in data:
                data[key].append(float(row[key]))

    return data


def main():
    parser = argparse.ArgumentParser(description="Plot DLBreach breach hydrograph")
    parser.add_argument("--breach_csv", type=str, required=True, help="Breach results CSV")
    parser.add_argument("--output", type=str, required=True, help="Output PNG path")
    parser.add_argument("--title", type=str, default="DLBreach Dam Breach Simulation",
                        help="Plot title")
    parser.add_argument("--json_output", type=str, help="Output JSON metadata")
    args = parser.parse_args()

    result = {
        "plot_path": None,
        "peak_q_annotation": None,
        "status": "error",
        "errors": [],
    }

    if not Path(args.breach_csv).exists():
        result["errors"].append(f"CSV not found: {args.breach_csv}")
        print(json.dumps(result, indent=2))
        sys.exit(1)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        data = read_results(args.breach_csv)

        time = np.array(data["time_hr"])
        breach_q = np.array(data["breach_flow_m3s"])
        spill_q = np.array(data["spillway_gate_flow_m3s"])
        total_q = breach_q + spill_q
        us_wsl = np.array(data["upstream_wsl_m"])
        ds_wsl = np.array(data["downstream_wsl_m"])

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                        gridspec_kw={"height_ratios": [2, 1]})

        # --- Top panel: Discharge ---
        ax1.fill_between(time, 0, breach_q, alpha=0.3, color="tab:red", label="Breach flow")
        ax1.plot(time, breach_q, color="tab:red", linewidth=1.5)
        if np.max(spill_q) > 0:
            ax1.plot(time, spill_q, color="tab:blue", linewidth=1.0, linestyle="--",
                     label="Spillway/gate flow")
            ax1.plot(time, total_q, color="black", linewidth=1.5, label="Total discharge")

        # Annotate peak
        peak_idx = np.argmax(breach_q)
        peak_q = breach_q[peak_idx]
        peak_t = time[peak_idx]
        ax1.annotate(
            f"Peak: {peak_q:.0f} m$^3$/s\nt = {peak_t:.1f} hr",
            xy=(peak_t, peak_q),
            xytext=(peak_t + (time[-1] - time[0]) * 0.1, peak_q * 0.85),
            arrowprops=dict(arrowstyle="->", color="red"),
            fontsize=10, color="red",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8),
        )

        ax1.set_ylabel("Discharge (m$^3$/s)", fontsize=12)
        ax1.set_title(args.title, fontsize=14, fontweight="bold")
        ax1.legend(loc="upper right", fontsize=10)
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(bottom=0)

        # --- Bottom panel: Water levels ---
        ax2.plot(time, us_wsl, color="tab:blue", linewidth=1.5, label="Upstream WSL")
        ax2.plot(time, ds_wsl, color="tab:green", linewidth=1.5, label="Downstream WSL")
        breach_bottom = np.array(data["breach_bottom_elev_m"])
        ax2.plot(time, breach_bottom, color="brown", linewidth=1.0, linestyle=":",
                 label="Breach bottom")

        ax2.set_xlabel("Time (hours)", fontsize=12)
        ax2.set_ylabel("Elevation (m above base)", fontsize=12)
        ax2.legend(loc="best", fontsize=10)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()

        # Save
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close()

        result["plot_path"] = str(output_path)
        result["peak_q_annotation"] = f"Peak: {peak_q:.0f} m3/s at t={peak_t:.1f} hr"
        result["status"] = "success"
        logger.info(f"Plot saved: {output_path}")

    except ImportError as e:
        result["errors"].append(f"matplotlib not available: {e}")
        print(json.dumps(result, indent=2))
        sys.exit(2)
    except Exception as e:
        result["errors"].append(f"Plotting error: {e}")
        logger.error(f"Error: {e}")
        print(json.dumps(result, indent=2))
        sys.exit(2)

    if args.json_output:
        Path(args.json_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_output).write_text(json.dumps(result, indent=2))

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
