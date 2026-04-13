#!/usr/bin/env python3
"""
plot_w2_curtain.py — Generate 2D longitudinal-vertical curtain plots.

The signature CE-QUAL-W2 visualization: distance from upstream (x-axis) vs
depth (y-axis) with temperature or other variable as color fill.

Usage:
    python plot_w2_curtain.py \
        --run_dir /path/to/run \
        --grid_json /path/to/reservoir_grid.json \
        --variable temperature \
        --output curtain_plot.png \
        --title "Reservoir Temperature Curtain"
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def parse_snapshot_for_curtain(snp_path, n_segments, n_layers):
    """Extract 2D fields from snapshot file for curtain plotting."""
    snapshots = []
    current_jday = None
    current_data = []

    with open(snp_path) as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue

            # Detect new snapshot
            import re
            jday_match = re.search(r'(\d+\.\d+)', line)
            if ("JDAY" in line.upper() or "SNAPSHOT" in line.upper()) and jday_match:
                if current_jday is not None and current_data:
                    snapshots.append({"jday": current_jday, "data": np.array(current_data)})
                current_jday = float(jday_match.group(1))
                current_data = []
                continue

            # Parse numeric data
            parts = line.split()
            try:
                values = [float(p) for p in parts]
                if len(values) >= 2:
                    current_data.append(values)
            except ValueError:
                pass

    if current_jday is not None and current_data:
        snapshots.append({"jday": current_jday, "data": np.array(current_data)})

    return snapshots


def process(args):
    """Main processing."""
    if not HAS_MPL:
        print(json.dumps({"status": "error", "errors": ["matplotlib not available"]}))
        return 2

    run_dir = Path(args.run_dir)

    # Load grid
    with open(args.grid_json) as f:
        grid = json.load(f)

    seg_distances = grid.get("segment_distances_km", [])
    layer_elevations = grid.get("layer_elevations_m", [])
    surface_elev = grid.get("surface_elevation_m", 100)
    bottom_elevs = grid.get("bottom_elevations_m", [])
    n_seg = grid["n_segments"]
    n_layers = grid["n_layers"]

    # Parse snapshot files
    snp_files = sorted(run_dir.glob("snp_*.opt"))
    if not snp_files:
        # Try to build from time series files or spreadsheet
        print(json.dumps({"status": "warning",
                          "warnings": ["No snapshot files found. Cannot generate curtain plot."]}))
        return 0

    all_snapshots = []
    for sf in snp_files:
        all_snapshots.extend(parse_snapshot_for_curtain(str(sf), n_seg, n_layers))

    if not all_snapshots:
        print(json.dumps({"status": "warning",
                          "warnings": ["No parseable snapshots found"]}))
        return 0

    # Select snapshots to plot (up to 4 panels: quarterly)
    n_snaps = len(all_snapshots)
    if n_snaps <= 4:
        selected = all_snapshots
    else:
        indices = np.linspace(0, n_snaps - 1, 4, dtype=int)
        selected = [all_snapshots[i] for i in indices]

    # Create figure
    n_panels = len(selected)
    fig, axes = plt.subplots(n_panels, 1, figsize=(14, 4 * n_panels), squeeze=False)

    for idx, snap in enumerate(selected):
        ax = axes[idx, 0]
        data = snap["data"]

        if len(data.shape) == 2 and data.shape[0] > 1 and data.shape[1] > 1:
            # Create meshgrid for pcolormesh
            x = np.array(seg_distances[:data.shape[1]]) if len(seg_distances) >= data.shape[1] else np.arange(data.shape[1])
            y = np.array(layer_elevations[:data.shape[0]]) if len(layer_elevations) >= data.shape[0] else np.arange(data.shape[0])

            if len(x) >= 2 and len(y) >= 2:
                im = ax.pcolormesh(x, y, data[:len(y), :len(x)],
                                   cmap="RdYlBu_r", shading="auto")
                plt.colorbar(im, ax=ax, label=args.variable or "Temperature (C)")

                # Plot bottom topography
                if bottom_elevs and len(bottom_elevs) >= len(x):
                    ax.fill_between(x, [min(y)] * len(x),
                                   bottom_elevs[:len(x)],
                                   color="saddlebrown", alpha=0.7)
            else:
                ax.text(0.5, 0.5, "Insufficient data for curtain plot",
                       transform=ax.transAxes, ha="center")

        ax.set_xlabel("Distance from upstream (km)")
        ax.set_ylabel("Elevation (m ASL)")
        ax.set_title(f"JDAY = {snap['jday']:.1f}")

    fig.suptitle(args.title or "CE-QUAL-W2 Curtain Plot", fontsize=14, fontweight="bold")
    plt.tight_layout()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    plt.savefig(args.output, dpi=150, bbox_inches="tight")
    plt.close()

    result = {
        "status": "success",
        "output_file": args.output,
        "n_panels": n_panels,
        "snapshot_jdays": [s["jday"] for s in selected],
    }
    print(json.dumps(result, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Plot CE-QUAL-W2 curtain (2D lon-vert)")
    parser.add_argument("--run_dir", required=True)
    parser.add_argument("--grid_json", required=True)
    parser.add_argument("--variable", default="temperature")
    parser.add_argument("--output", required=True)
    parser.add_argument("--title", default="CE-QUAL-W2 Curtain Plot")
    args = parser.parse_args()
    sys.exit(process(args))


if __name__ == "__main__":
    main()
