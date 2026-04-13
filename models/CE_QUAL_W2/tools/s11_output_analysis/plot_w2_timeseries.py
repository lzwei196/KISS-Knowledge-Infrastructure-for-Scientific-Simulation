#!/usr/bin/env python3
"""
plot_w2_timeseries.py — Generate time series plots from CE-QUAL-W2 output.

Plots temperature, DO, water level, and discharge at specified locations.

Usage:
    python plot_w2_timeseries.py \
        --run_dir /path/to/run \
        --output timeseries.png \
        --title "Reservoir Time Series"
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def process(args):
    """Main processing."""
    if not HAS_MPL:
        print(json.dumps({"status": "error", "errors": ["matplotlib not available"]}))
        return 2

    run_dir = Path(args.run_dir)

    # Collect all time series data
    tsr_data = {}
    for tsr_file in sorted(run_dir.glob("tsr_*.opt")):
        data = []
        with open(tsr_file) as f:
            for line in f:
                if line.startswith("$") or line.strip() == "":
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        row = [float(p) for p in parts]
                        data.append(row)
                    except ValueError:
                        continue
        if data:
            df = pd.DataFrame(data)
            tsr_data[tsr_file.name] = df

    # Also check spreadsheet files
    spr_data = {}
    for spr_file in sorted(run_dir.glob("spr_*.opt")):
        try:
            df = pd.read_csv(spr_file, sep=r"\s+", comment="$", header=None)
            if not df.empty:
                spr_data[spr_file.name] = df
        except Exception:
            pass

    all_data = {**tsr_data, **spr_data}

    if not all_data:
        print(json.dumps({"status": "warning",
                          "warnings": ["No time series data found"]}))
        return 0

    # Create figure
    n_panels = min(len(all_data), 4)
    fig, axes = plt.subplots(n_panels, 1, figsize=(12, 3 * n_panels), squeeze=False)

    for idx, (fname, df) in enumerate(list(all_data.items())[:4]):
        ax = axes[idx, 0]

        if len(df.columns) >= 2:
            x = df.iloc[:, 0]
            for col in range(1, min(len(df.columns), 4)):
                ax.plot(x, df.iloc[:, col], label=f"Col {col}", linewidth=0.8)

        ax.set_xlabel("Julian Day")
        ax.set_ylabel("Value")
        ax.set_title(fname)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    fig.suptitle(args.title or "CE-QUAL-W2 Time Series", fontsize=14, fontweight="bold")
    plt.tight_layout()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    plt.savefig(args.output, dpi=150, bbox_inches="tight")
    plt.close()

    result = {
        "status": "success",
        "output_file": args.output,
        "n_timeseries": len(all_data),
        "files_plotted": list(all_data.keys())[:4],
    }
    print(json.dumps(result, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Plot CE-QUAL-W2 time series")
    parser.add_argument("--run_dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--title", default="CE-QUAL-W2 Time Series")
    args = parser.parse_args()
    sys.exit(process(args))


if __name__ == "__main__":
    main()
