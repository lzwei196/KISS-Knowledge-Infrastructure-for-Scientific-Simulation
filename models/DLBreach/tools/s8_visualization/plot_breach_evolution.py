#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
==========================================
Tool ID:      plot_breach_evolution
Stage:        s8_visualization
Description:  Plot DLBreach breach geometry evolution over time showing
              breach bottom width, top width, bottom elevation, side slope,
              and flow area changes.

Inputs:
  --breach_csv:   CSV from extract_breach_results
  --output:       Output PNG path
  --title:        Plot title (optional)

Outputs:
  - PNG plot file
  - JSON with plot_path

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
    data = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        for h in headers:
            data[h] = []
        for row in reader:
            for h in headers:
                data[h].append(float(row[h]))
    return data


def main():
    parser = argparse.ArgumentParser(description="Plot DLBreach breach geometry evolution")
    parser.add_argument("--breach_csv", type=str, required=True, help="Breach results CSV")
    parser.add_argument("--output", type=str, required=True, help="Output PNG path")
    parser.add_argument("--title", type=str, default="Breach Geometry Evolution",
                        help="Plot title")
    parser.add_argument("--json_output", type=str, help="Output JSON metadata")
    args = parser.parse_args()

    result = {
        "plot_path": None,
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
        bottom_width = np.array(data["breach_bottom_width_m"])
        top_width = np.array(data["breach_top_width_m"])
        bottom_elev = np.array(data["breach_bottom_elev_m"])
        flow_area = np.array(data["breach_flow_area_m2"])
        side_slope = np.array(data["breach_side_slope_vh"])
        cumvol = np.array(data["cumulative_volume_m3"])
        breach_q = np.array(data["breach_flow_m3s"])

        fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True)

        # --- Panel 1: Breach widths ---
        ax = axes[0, 0]
        ax.plot(time, bottom_width, color="brown", linewidth=1.5, label="Bottom width")
        ax.plot(time, top_width, color="red", linewidth=1.5, label="Top width")
        ax.fill_between(time, bottom_width, top_width, alpha=0.2, color="red")
        ax.set_ylabel("Width (m)")
        ax.set_title("Breach Width")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

        # --- Panel 2: Breach bottom elevation ---
        ax = axes[0, 1]
        ax.plot(time, bottom_elev, color="brown", linewidth=1.5)
        ax.fill_between(time, 0, bottom_elev, alpha=0.2, color="brown")
        ax.set_ylabel("Elevation (m)")
        ax.set_title("Breach Bottom Elevation")
        ax.grid(True, alpha=0.3)

        # --- Panel 3: Flow area ---
        ax = axes[1, 0]
        ax.plot(time, flow_area, color="tab:blue", linewidth=1.5)
        ax.fill_between(time, 0, flow_area, alpha=0.2, color="tab:blue")
        ax.set_ylabel("Area (m$^2$)")
        ax.set_title("Breach Flow Area")
        ax.grid(True, alpha=0.3)

        # --- Panel 4: Side slope ---
        ax = axes[1, 1]
        ax.plot(time, side_slope, color="tab:orange", linewidth=1.5)
        ax.set_ylabel("Side Slope (V/H)")
        ax.set_title("Breach Side Slope")
        ax.grid(True, alpha=0.3)

        # --- Panel 5: Breach discharge (reference) ---
        ax = axes[2, 0]
        ax.plot(time, breach_q, color="tab:red", linewidth=1.5)
        ax.fill_between(time, 0, breach_q, alpha=0.2, color="tab:red")
        ax.set_xlabel("Time (hours)")
        ax.set_ylabel("Discharge (m$^3$/s)")
        ax.set_title("Breach Discharge")
        ax.grid(True, alpha=0.3)

        # --- Panel 6: Cumulative volume ---
        ax = axes[2, 1]
        # Display in million m3 if large
        if cumvol[-1] > 1e6:
            ax.plot(time, cumvol / 1e6, color="tab:purple", linewidth=1.5)
            ax.set_ylabel("Volume (10$^6$ m$^3$)")
        else:
            ax.plot(time, cumvol, color="tab:purple", linewidth=1.5)
            ax.set_ylabel("Volume (m$^3$)")
        ax.set_xlabel("Time (hours)")
        ax.set_title("Cumulative Outflow Volume")
        ax.grid(True, alpha=0.3)

        fig.suptitle(args.title, fontsize=14, fontweight="bold", y=1.01)
        plt.tight_layout()

        # Save
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close()

        result["plot_path"] = str(output_path)
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
