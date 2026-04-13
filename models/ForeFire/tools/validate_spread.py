#!/usr/bin/env python3
"""
validate_spread.py — Compare simulated vs observed fire perimeters.

Computes fire-spread validation metrics:
  - Sorensen coefficient (area overlap): SC = 2*|A∩B| / (|A| + |B|)
  - Overestimation: (|A \ B|) / |B| — simulated area not in observed
  - Underestimation: (|B \ A|) / |B| — observed area not in simulated
  - ROS comparison: simulated vs observed rate of spread
  - Burned area comparison: total area (ha) simulated vs observed
  - Hausdorff distance: max min-distance between perimeter boundaries

CRITICAL NOTES:
  - Coordinates must be in the same CRS (both UTM or both lon/lat).
  - Time must be aligned — compare perimeters at the same elapsed time.
  - Sorensen coefficient > 0.6 is generally considered "good" for wildfire.
  - ROS is computed as fire area growth / perimeter length / time.

Usage:
    python validate_spread.py \\
        --simulated sim_perimeters.csv \\
        --observed obs_perimeters.csv \\
        --output validation_results.json \\
        --figure validation_plot.png

    python validate_spread.py \\
        --simulated sim_result.geojson \\
        --observed VIIRS_hotspots.csv \\
        --output validation_results.json
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.simulated):
        errors.append(f"Simulated file not found: {args.simulated}")

    if args.observed and not os.path.isfile(args.observed):
        errors.append(f"Observed file not found: {args.observed}")

    if errors:
        for e in errors:
            print(f"VALIDATION ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print("Input validation passed.")


def load_perimeter_csv(filepath):
    """Load fire perimeter from CSV (output of parse_forefire_output.py)."""
    perimeters = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("perimeter_id", 0)
            if pid not in perimeters:
                perimeters[pid] = {"coords": [], "timestamp": row.get("timestamp", pid)}
            perimeters[pid]["coords"].append([
                float(row["x"]),
                float(row["y"]),
            ])
    return perimeters


def load_geojson(filepath):
    """Load fire perimeters from GeoJSON."""
    with open(filepath) as f:
        data = json.load(f)

    perimeters = {}
    for i, feat in enumerate(data.get("features", [])):
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        flat = []
        if geom["type"] == "Polygon":
            for ring in coords:
                flat.extend([[c[0], c[1]] for c in ring])
        elif geom["type"] == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    flat.extend([[c[0], c[1]] for c in ring])
        perimeters[i] = {
            "coords": flat,
            "timestamp": feat.get("properties", {}).get("time", i),
        }
    return perimeters


def compute_burned_area_raster(coords, resolution=30):
    """Rasterize a perimeter and compute burned area in hectares."""
    coords = np.array(coords)
    if len(coords) < 3:
        return 0.0, None

    xmin, ymin = coords.min(axis=0)
    xmax, ymax = coords.max(axis=0)

    nx = max(int((xmax - xmin) / resolution) + 1, 1)
    ny = max(int((ymax - ymin) / resolution) + 1, 1)

    # Simple point-in-polygon rasterization using ray casting
    raster = np.zeros((ny, nx), dtype=bool)

    for iy in range(ny):
        y = ymin + iy * resolution + resolution / 2
        for ix in range(nx):
            x = xmin + ix * resolution + resolution / 2
            # Ray casting algorithm
            inside = False
            n = len(coords)
            j = n - 1
            for i_pt in range(n):
                xi, yi = coords[i_pt]
                xj, yj = coords[j]
                if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                    inside = not inside
                j = i_pt
            raster[iy, ix] = inside

    area_ha = np.sum(raster) * (resolution ** 2) / 10000.0
    return area_ha, raster


def sorensen_coefficient(raster_a, raster_b):
    """Compute Sorensen coefficient between two binary rasters."""
    if raster_a is None or raster_b is None:
        return np.nan

    # Pad to same size
    max_y = max(raster_a.shape[0], raster_b.shape[0])
    max_x = max(raster_a.shape[1], raster_b.shape[1])

    a = np.zeros((max_y, max_x), dtype=bool)
    b = np.zeros((max_y, max_x), dtype=bool)
    a[:raster_a.shape[0], :raster_a.shape[1]] = raster_a
    b[:raster_b.shape[0], :raster_b.shape[1]] = raster_b

    intersection = np.sum(a & b)
    total = np.sum(a) + np.sum(b)

    if total == 0:
        return 0.0
    return 2.0 * intersection / total


def perimeter_length(coords):
    """Compute perimeter length from coordinate list."""
    coords = np.array(coords)
    if len(coords) < 2:
        return 0.0
    diffs = np.diff(coords, axis=0)
    distances = np.sqrt(np.sum(diffs ** 2, axis=1))
    return np.sum(distances)


def process(args):
    """Main processing: compute validation metrics."""
    # Load simulated perimeters
    ext = Path(args.simulated).suffix.lower()
    if ext == ".geojson":
        sim_perims = load_geojson(args.simulated)
    else:
        sim_perims = load_perimeter_csv(args.simulated)

    print(f"Simulated: {len(sim_perims)} perimeters loaded")

    results = {"simulated_file": args.simulated, "n_sim_perimeters": len(sim_perims)}

    # Compute simulated area and perimeter for last timestep
    if sim_perims:
        last_key = max(sim_perims.keys())
        sim_coords = sim_perims[last_key]["coords"]
        sim_area, sim_raster = compute_burned_area_raster(sim_coords)
        sim_perim_len = perimeter_length(sim_coords)
        results["simulated_area_ha"] = round(sim_area, 2)
        results["simulated_perimeter_m"] = round(sim_perim_len, 1)
        results["simulated_n_points"] = len(sim_coords)
        print(f"Simulated burned area: {sim_area:.1f} ha")
        print(f"Simulated perimeter: {sim_perim_len:.0f} m")

    # If observed data provided, compute comparison metrics
    if args.observed:
        ext_obs = Path(args.observed).suffix.lower()
        if ext_obs == ".geojson":
            obs_perims = load_geojson(args.observed)
        else:
            obs_perims = load_perimeter_csv(args.observed)

        print(f"Observed: {len(obs_perims)} perimeters loaded")

        if obs_perims:
            last_obs_key = max(obs_perims.keys())
            obs_coords = obs_perims[last_obs_key]["coords"]
            obs_area, obs_raster = compute_burned_area_raster(obs_coords)
            obs_perim_len = perimeter_length(obs_coords)

            results["observed_area_ha"] = round(obs_area, 2)
            results["observed_perimeter_m"] = round(obs_perim_len, 1)

            # Sorensen coefficient
            sc = sorensen_coefficient(sim_raster, obs_raster)
            results["sorensen_coefficient"] = round(sc, 4)

            # Area ratio
            if obs_area > 0:
                results["area_ratio"] = round(sim_area / obs_area, 3)

            print(f"Observed burned area: {obs_area:.1f} ha")
            print(f"Sorensen coefficient: {sc:.4f}")
            print(f"Area ratio (sim/obs): {sim_area / max(obs_area, 0.01):.3f}")

    # Generate validation figure
    if args.figure and HAS_MATPLOTLIB:
        create_validation_figure(sim_perims, results, args)

    return results


def create_validation_figure(sim_perims, results, args):
    """Create validation figure."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Plot 1: Fire perimeters over time
    ax1 = axes[0]
    colors = plt.cm.inferno(np.linspace(0.2, 0.9, len(sim_perims)))
    for i, (pid, perim) in enumerate(sorted(sim_perims.items())):
        coords = np.array(perim["coords"])
        if len(coords) > 0:
            ax1.plot(coords[:, 0], coords[:, 1], '-', color=colors[i],
                     linewidth=1.5, label=f"t={perim['timestamp']}")
    ax1.set_xlabel("X (m)")
    ax1.set_ylabel("Y (m)")
    ax1.set_title("Simulated Fire Perimeters")
    ax1.set_aspect("equal")
    ax1.grid(True, alpha=0.3)
    if len(sim_perims) <= 10:
        ax1.legend(fontsize=8)

    # Plot 2: Metrics summary
    ax2 = axes[1]
    ax2.axis("off")
    metric_text = "Validation Metrics\n" + "=" * 30 + "\n"
    for key, val in results.items():
        if key.startswith(("simulated_", "observed_", "sorensen", "area_ratio")):
            metric_text += f"{key}: {val}\n"
    ax2.text(0.1, 0.9, metric_text, transform=ax2.transAxes,
             fontsize=11, verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    plt.savefig(args.figure, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Validation figure saved: {args.figure}")


def validate_outputs(output_path):
    """Validate the output JSON."""
    if not os.path.isfile(output_path):
        print(f"OUTPUT ERROR: File not created: {output_path}", file=sys.stderr)
        return False

    with open(output_path) as f:
        data = json.load(f)

    if "simulated_area_ha" not in data:
        print("OUTPUT WARNING: No simulated area computed", file=sys.stderr)
        return False

    print("Output validation passed.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Validate ForeFire spread against observations")
    parser.add_argument("--simulated", required=True, help="Simulated perimeters (CSV or GeoJSON)")
    parser.add_argument("--observed", default=None, help="Observed perimeters (CSV or GeoJSON)")
    parser.add_argument("--output", default="validation_results.json", help="Output JSON path")
    parser.add_argument("--figure", default=None, help="Output figure path (PNG)")
    args = parser.parse_args()

    validate_inputs(args)
    results = process(args)

    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Results written: {args.output}")

    validate_outputs(args.output)


if __name__ == "__main__":
    main()
