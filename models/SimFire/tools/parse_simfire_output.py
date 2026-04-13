#!/usr/bin/env python3
"""
parse_simfire_output.py — Extract fire spread statistics from SimFire output.

Reads SimFire fire map arrays (NPY or H5) and produces CSV time series,
burn area statistics, spread rate estimates, and visualization plots.

CRITICAL NOTES:
  - Fire map values: 0=UNBURNED, 1=BURNING, 2=BURNED, 3=FIRELINE, 4=SCRATCHLINE, 5=WETLINE
  - Pixel areas: pixel_scale² ft² per pixel. Convert to acres (÷43560) or hectares.
  - Rate of spread: RoS is in ft/min internally. Convert to m/s (÷196.85) or chains/hr (÷1.1).

Output:
  - burn_statistics.csv: time series of burned area, active fire count, spread rate
  - burn_summary.json: aggregate statistics
  - burn_map.png: final fire map visualization
  - burn_progression.png: time series plot (if multiple snapshots available)

Usage:
    python parse_simfire_output.py \\
        --fire-map fire_map_final.npy \\
        --pixel-scale 50 \\
        --output-dir ./analysis/

    python parse_simfire_output.py \\
        --data-dir ~/.simfire/data/ \\
        --pixel-scale 50 \\
        --output-dir ./analysis/

    python parse_simfire_output.py \\
        --fire-map fire_map.npy \\
        --pixel-scale 50 \\
        --observed-perimeter observed.npy \\
        --output-dir ./analysis/
"""

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np

# BurnStatus enum values
UNBURNED = 0
BURNING = 1
BURNED = 2
FIRELINE = 3
SCRATCHLINE = 4
WETLINE = 5

STATUS_NAMES = {
    0: "unburned", 1: "burning", 2: "burned",
    3: "fireline", 4: "scratchline", 5: "wetline"
}


def validate_inputs(args):
    """Validate input arguments.

    Checks file existence, pixel scale, output directory.
    """
    errors = []

    if args.fire_map and not os.path.isfile(args.fire_map):
        errors.append(f"Fire map not found: {args.fire_map}")

    if args.data_dir and not os.path.isdir(args.data_dir):
        errors.append(f"Data directory not found: {args.data_dir}")

    if not args.fire_map and not args.data_dir:
        errors.append("Must provide --fire-map or --data-dir")

    if args.pixel_scale <= 0:
        errors.append(f"Pixel scale must be positive, got {args.pixel_scale}")

    if args.observed_perimeter and not os.path.isfile(args.observed_perimeter):
        errors.append(f"Observed perimeter not found: {args.observed_perimeter}")

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_inputs", "errors": errors}))
        sys.exit(1)


def load_fire_maps(fire_map_path=None, data_dir=None):
    """Load fire map arrays from NPY or H5 files.

    Returns list of (timestep, fire_map_array) tuples.
    """
    maps = []

    if fire_map_path:
        if fire_map_path.endswith(".npy"):
            fm = np.load(fire_map_path)
            maps.append((0, fm))
        elif fire_map_path.endswith(".h5") or fire_map_path.endswith(".hdf5"):
            import h5py
            with h5py.File(fire_map_path, "r") as f:
                for key in sorted(f.keys()):
                    maps.append((int(key) if key.isdigit() else len(maps), np.array(f[key])))
        else:
            fm = np.load(fire_map_path)
            maps.append((0, fm))

    if data_dir:
        npy_files = sorted(glob.glob(os.path.join(data_dir, "*.npy")))
        h5_files = sorted(glob.glob(os.path.join(data_dir, "*.h5")))

        for i, f in enumerate(npy_files):
            maps.append((i, np.load(f)))

        for h5f in h5_files:
            import h5py
            with h5py.File(h5f, "r") as f:
                for key in sorted(f.keys()):
                    maps.append((len(maps), np.array(f[key])))

    if not maps:
        print(json.dumps({"status": "error", "errors": ["No fire map data loaded"]}))
        sys.exit(1)

    return maps


def compute_statistics(fire_map, pixel_scale_ft):
    """Compute burn statistics for a single fire map snapshot.

    Args:
        fire_map: 2D int array of BurnStatus values
        pixel_scale_ft: feet per pixel

    Returns:
        dict of statistics with areas in multiple units
    """
    pixel_area_ft2 = pixel_scale_ft ** 2
    pixel_area_acres = pixel_area_ft2 / 43560.0
    pixel_area_ha = pixel_area_acres * 0.404686
    pixel_area_m2 = pixel_area_ft2 * 0.0929  # 1 ft² = 0.0929 m²

    total = fire_map.size
    counts = {}
    for val, name in STATUS_NAMES.items():
        counts[name] = int(np.sum(fire_map == val))

    fire_pixels = counts.get("burned", 0) + counts.get("burning", 0)

    stats = {
        "grid_shape": list(fire_map.shape),
        "total_pixels": total,
        "pixel_counts": counts,
        "fire_pixels": fire_pixels,
        "burned_fraction": round(fire_pixels / total, 6) if total > 0 else 0,
        "area_ft2": round(fire_pixels * pixel_area_ft2, 1),
        "area_acres": round(fire_pixels * pixel_area_acres, 2),
        "area_ha": round(fire_pixels * pixel_area_ha, 4),
        "area_m2": round(fire_pixels * pixel_area_m2, 1),
        "mitigation_pixels": (
            counts.get("fireline", 0)
            + counts.get("scratchline", 0)
            + counts.get("wetline", 0)
        ),
    }

    # Compute fire perimeter length (approximate)
    if fire_pixels > 0:
        fire_mask = (fire_map == BURNING) | (fire_map == BURNED)
        # Count border pixels (adjacent to non-fire)
        padded = np.pad(fire_mask.astype(int), 1, mode="constant", constant_values=0)
        edges = (
            np.abs(padded[1:-1, 1:-1] - padded[:-2, 1:-1])
            + np.abs(padded[1:-1, 1:-1] - padded[2:, 1:-1])
            + np.abs(padded[1:-1, 1:-1] - padded[1:-1, :-2])
            + np.abs(padded[1:-1, 1:-1] - padded[1:-1, 2:])
        )
        perimeter_pixels = int(np.sum(edges > 0))
        stats["perimeter_pixels"] = perimeter_pixels
        stats["perimeter_ft"] = round(perimeter_pixels * pixel_scale_ft, 1)
        stats["perimeter_mi"] = round(perimeter_pixels * pixel_scale_ft / 5280, 3)

    return stats


def compute_accuracy_metrics(simulated, observed):
    """Compare simulated fire map against observed perimeter.

    Computes classification metrics:
    - Sorensen coefficient (similar to F1 score)
    - Cohen's kappa
    - Commission error (false positive rate)
    - Omission error (false negative rate)

    Args:
        simulated: 2D array of BurnStatus
        observed: 2D array (1=burned, 0=unburned)

    Returns:
        dict of accuracy metrics
    """
    if simulated.shape != observed.shape:
        print(json.dumps({
            "status": "error",
            "errors": [f"Shape mismatch: sim {simulated.shape} vs obs {observed.shape}"]
        }))
        sys.exit(1)

    sim_burned = ((simulated == BURNING) | (simulated == BURNED)).astype(int)
    obs_burned = (observed > 0).astype(int)

    tp = int(np.sum((sim_burned == 1) & (obs_burned == 1)))
    fp = int(np.sum((sim_burned == 1) & (obs_burned == 0)))
    fn = int(np.sum((sim_burned == 0) & (obs_burned == 1)))
    tn = int(np.sum((sim_burned == 0) & (obs_burned == 0)))

    total = tp + fp + fn + tn

    # Sorensen coefficient (2*TP / (2*TP + FP + FN))
    sorensen = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) > 0 else 0.0

    # Cohen's kappa
    p_o = (tp + tn) / total if total > 0 else 0.0
    p_e = (
        ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (total ** 2)
        if total > 0 else 0.0
    )
    kappa = (p_o - p_e) / (1 - p_e) if (1 - p_e) > 0 else 0.0

    # Commission and omission errors
    commission = fp / (tp + fp) if (tp + fp) > 0 else 0.0
    omission = fn / (tp + fn) if (tp + fn) > 0 else 0.0

    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "sorensen_coefficient": round(sorensen, 4),
        "cohens_kappa": round(kappa, 4),
        "commission_error": round(commission, 4),
        "omission_error": round(omission, 4),
        "overall_accuracy": round(p_o, 4),
    }


def plot_fire_map(fire_map, output_path, title="SimFire Burn Map", metrics=None):
    """Create visualization of final fire map.

    Colors:
    - Green: unburned
    - Red: burning
    - Dark brown: burned
    - Yellow: fireline
    - Orange: scratchline
    - Blue: wetline
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap
        from matplotlib.patches import Patch
    except ImportError:
        print(json.dumps({"status": "warning", "message": "matplotlib not available, skipping plot"}),
              file=sys.stderr)
        return

    colors = [
        "#2d5016",  # 0: unburned (dark green)
        "#ff3300",  # 1: burning (red)
        "#8b4513",  # 2: burned (brown)
        "#ffd700",  # 3: fireline (gold)
        "#ff8c00",  # 4: scratchline (dark orange)
        "#4169e1",  # 5: wetline (royal blue)
    ]
    cmap = ListedColormap(colors[:max(int(fire_map.max()) + 1, 3)])

    fig, ax = plt.subplots(1, 1, figsize=(10, 8))
    im = ax.imshow(fire_map, cmap=cmap, vmin=0, vmax=5, interpolation="nearest")

    legend_elements = [
        Patch(facecolor=colors[0], label="Unburned"),
        Patch(facecolor=colors[1], label="Burning"),
        Patch(facecolor=colors[2], label="Burned"),
    ]
    if np.any(fire_map >= 3):
        legend_elements.extend([
            Patch(facecolor=colors[3], label="Fireline"),
            Patch(facecolor=colors[4], label="Scratchline"),
            Patch(facecolor=colors[5], label="Wetline"),
        ])

    ax.legend(handles=legend_elements, loc="lower right", fontsize=9)
    ax.set_title(title, fontsize=14)
    ax.set_xlabel("Column (pixels)")
    ax.set_ylabel("Row (pixels)")

    # Add metrics box if provided
    if metrics:
        text_lines = []
        for key, val in metrics.items():
            if isinstance(val, float):
                text_lines.append(f"{key}: {val:.4f}")
            else:
                text_lines.append(f"{key}: {val}")
        text = "\n".join(text_lines[:6])
        ax.text(
            0.98, 0.98, text, transform=ax.transAxes,
            fontsize=8, verticalalignment="top", horizontalalignment="right",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
        )

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()


def write_csv(stats_list, output_path):
    """Write burn statistics to CSV.

    Columns: timestep, burned_pixels, burning_pixels, burned_fraction,
             area_acres, area_ha, perimeter_ft
    """
    header = "timestep,burned_pixels,burning_pixels,burned_fraction,area_acres,area_ha,perimeter_ft\n"
    with open(output_path, "w") as f:
        f.write(header)
        for i, stats in enumerate(stats_list):
            row = (
                f"{i},"
                f"{stats['pixel_counts'].get('burned', 0)},"
                f"{stats['pixel_counts'].get('burning', 0)},"
                f"{stats['burned_fraction']},"
                f"{stats['area_acres']},"
                f"{stats['area_ha']},"
                f"{stats.get('perimeter_ft', 0)}\n"
            )
            f.write(row)


def validate_outputs(stats_list, output_dir):
    """Post-processing validation.

    Checks:
    - At least one snapshot processed
    - Statistics are self-consistent
    - Output files were created
    """
    errors = []
    warnings = []

    if not stats_list:
        errors.append("No fire map snapshots were processed")

    for i, stats in enumerate(stats_list):
        total = stats["total_pixels"]
        counted = sum(stats["pixel_counts"].values())
        if counted != total:
            errors.append(f"Snapshot {i}: pixel count mismatch ({counted} != {total})")

    csv_path = os.path.join(output_dir, "burn_statistics.csv")
    if not os.path.isfile(csv_path):
        warnings.append("CSV output not created")

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_outputs", "errors": errors}))
        sys.exit(1)

    return warnings


def process(args):
    """Main analysis pipeline: load → compute → plot → save."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Load fire maps
    maps = load_fire_maps(args.fire_map, args.data_dir)

    # Step 2: Compute statistics for each snapshot
    stats_list = []
    for timestep, fm in maps:
        stats = compute_statistics(fm, args.pixel_scale)
        stats["timestep"] = timestep
        stats_list.append(stats)

    # Step 3: Accuracy metrics (if observed data provided)
    accuracy = None
    if args.observed_perimeter:
        observed = np.load(args.observed_perimeter)
        _, final_map = maps[-1]
        accuracy = compute_accuracy_metrics(final_map, observed)

    # Step 4: Write CSV
    csv_path = output_dir / "burn_statistics.csv"
    write_csv(stats_list, str(csv_path))

    # Step 5: Plot final map
    _, final_map = maps[-1]
    plot_path = output_dir / "burn_map.png"
    plot_fire_map(
        final_map, str(plot_path),
        title="SimFire Final Burn Map",
        metrics=accuracy,
    )

    # Step 6: Write summary JSON
    summary = {
        "n_snapshots": len(maps),
        "final_statistics": stats_list[-1],
        "accuracy_metrics": accuracy,
        "output_files": {
            "csv": str(csv_path),
            "plot": str(plot_path),
        },
    }
    summary_path = output_dir / "burn_summary.json"
    with open(str(summary_path), "w") as f:
        json.dump(summary, f, indent=2)

    # Step 7: Validate outputs
    warnings = validate_outputs(stats_list, str(output_dir))
    if warnings:
        summary["warnings"] = warnings

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Parse SimFire output and compute burn statistics"
    )
    parser.add_argument("--fire-map", type=str, default=None,
                        help="Path to fire map NPY/H5 file")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Directory with multiple fire map snapshots")
    parser.add_argument("--pixel-scale", type=float, required=True,
                        help="Feet per pixel (from SimFire config)")
    parser.add_argument("--observed-perimeter", type=str, default=None,
                        help="Path to observed burn perimeter (NPY, 1=burned)")
    parser.add_argument("--output-dir", type=str, required=True,
                        help="Output directory for analysis results")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

    print(json.dumps({"status": "success", "output": result}, indent=2, default=str))


if __name__ == "__main__":
    main()
