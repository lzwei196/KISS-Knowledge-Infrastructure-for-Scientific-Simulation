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


def shared_grid(coord_sets, resolution=30, margin_cells=5):
    """Build ONE regular grid that covers every perimeter passed in.

    This is the whole point of the function. Rasterising the simulated and the
    observed fire on their OWN bounding boxes and then padding both from index
    (0,0) silently TRANSLATES one fire onto the other: two fires 5 km apart can
    then score a high overlap, and two concentric fires can score zero. Every
    area-overlap score (Sorensen, Jaccard/CSI, POD, FAR) is only defined on a
    common, co-registered grid.
    """
    pts = [np.asarray(c, dtype=float) for c in coord_sets if c is not None and len(c) >= 3]
    if not pts:
        return None
    allpts = np.vstack(pts)
    xmin, ymin = allpts.min(axis=0)
    xmax, ymax = allpts.max(axis=0)
    pad = margin_cells * resolution
    xmin -= pad; ymin -= pad; xmax += pad; ymax += pad
    nx = max(int(np.ceil((xmax - xmin) / resolution)), 1)
    ny = max(int(np.ceil((ymax - ymin) / resolution)), 1)
    return {"xmin": float(xmin), "ymin": float(ymin), "nx": int(nx), "ny": int(ny),
            "res": float(resolution)}


def rasterize_on_grid(coords, grid):
    """Rasterise one closed perimeter onto the SHARED grid (even-odd fill)."""
    if grid is None or coords is None or len(coords) < 3:
        return None
    c = np.asarray(coords, dtype=float)
    if not np.allclose(c[0], c[-1]):
        c = np.vstack([c, c[:1]])
    res, xmin, ymin = grid["res"], grid["xmin"], grid["ymin"]
    nx, ny = grid["nx"], grid["ny"]
    xs = xmin + (np.arange(nx) + 0.5) * res
    ys = ymin + (np.arange(ny) + 0.5) * res
    X, Y = np.meshgrid(xs, ys)

    try:                                    # exact, fast C fill when available
        from matplotlib.path import Path as _MPath
        inside = _MPath(c).contains_points(
            np.column_stack([X.ravel(), Y.ravel()])).reshape(ny, nx)
        return inside
    except Exception:
        pass

    # Vectorised even-odd ray casting (no per-cell Python loop).
    inside = np.zeros((ny, nx), dtype=bool)
    x1, y1 = c[:-1, 0], c[:-1, 1]
    x2, y2 = c[1:, 0], c[1:, 1]
    for xa, ya, xb, yb in zip(x1, y1, x2, y2):
        if ya == yb:
            continue
        straddles = (Y > min(ya, yb)) & (Y <= max(ya, yb))
        xint = xa + (Y - ya) * (xb - xa) / (yb - ya)
        inside ^= straddles & (X < xint)
    return inside


def raster_area_ha(raster, grid):
    if raster is None or grid is None:
        return 0.0
    return float(raster.sum()) * grid["res"] ** 2 / 10000.0


def overlap_scores(sim, obs):
    """Area-overlap scores for two co-registered burned masks.

    Reference convention (Filippi et al. 2014, NHESS 14, 3077, Sect. 3): burned
    footprints are graded by area overlap -- Sorensen SC = 2|A n B|/(|A|+|B|)
    and Jaccard, which for two binary masks IS the Critical Success Index
    CSI = hits/(hits+misses+false_alarms). CSI is the determining score for the
    dag's `event_detection` family, so it must be emitted, not just Sorensen.
    """
    out = {"sorensen_coefficient": np.nan, "csi": np.nan, "pod": np.nan, "far": np.nan}
    if sim is None or obs is None or sim.shape != obs.shape:
        return out
    hits = int((sim & obs).sum())
    false_alarms = int((sim & ~obs).sum())
    misses = int((obs & ~sim).sum())
    denom = hits + misses + false_alarms
    out["hits"] = hits
    out["misses"] = misses
    out["false_alarms"] = false_alarms
    out["csi"] = round(hits / denom, 4) if denom else 0.0
    tot = int(sim.sum()) + int(obs.sum())
    out["sorensen_coefficient"] = round(2.0 * hits / tot, 4) if tot else 0.0
    out["pod"] = round(hits / (hits + misses), 4) if (hits + misses) else 0.0
    out["far"] = round(false_alarms / (hits + false_alarms), 4) if (hits + false_alarms) else 0.0
    if obs.sum():
        out["overestimation"] = round(false_alarms / int(obs.sum()), 4)
        out["underestimation"] = round(misses / int(obs.sum()), 4)
    return out


def sorensen_coefficient(raster_a, raster_b):
    """Backward-compatible wrapper; both rasters MUST share one grid."""
    return overlap_scores(raster_a, raster_b)["sorensen_coefficient"]


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

    sim_coords = None
    if sim_perims:
        last_key = max(sim_perims.keys())
        sim_coords = sim_perims[last_key]["coords"]

    obs_coords = None
    if args.observed:
        ext_obs = Path(args.observed).suffix.lower()
        if ext_obs == ".geojson":
            obs_perims = load_geojson(args.observed)
        else:
            obs_perims = load_perimeter_csv(args.observed)
        print(f"Observed: {len(obs_perims)} perimeters loaded")
        if obs_perims:
            obs_coords = obs_perims[max(obs_perims.keys())]["coords"]

    # ONE grid covering both fires -> the masks are co-registered in space.
    grid = shared_grid([sim_coords, obs_coords], resolution=args.resolution)
    results["grid"] = grid

    sim_raster = rasterize_on_grid(sim_coords, grid)
    obs_raster = rasterize_on_grid(obs_coords, grid)

    if sim_coords is not None:
        sim_area = raster_area_ha(sim_raster, grid)
        sim_perim_len = perimeter_length(sim_coords)
        results["simulated_area_ha"] = round(sim_area, 2)
        results["simulated_perimeter_m"] = round(sim_perim_len, 1)
        results["simulated_n_points"] = len(sim_coords)
        print(f"Simulated burned area: {sim_area:.1f} ha")
        print(f"Simulated perimeter: {sim_perim_len:.0f} m")

    if obs_coords is not None:
        obs_area = raster_area_ha(obs_raster, grid)
        results["observed_area_ha"] = round(obs_area, 2)
        results["observed_perimeter_m"] = round(perimeter_length(obs_coords), 1)

        results.update(overlap_scores(sim_raster, obs_raster))

        if obs_area > 0:
            results["area_ratio"] = round(results["simulated_area_ha"] / obs_area, 3)

        print(f"Observed burned area: {obs_area:.1f} ha")
        print(f"CSI: {results['csi']}  Sorensen: {results['sorensen_coefficient']}  "
              f"POD: {results['pod']}  FAR: {results['far']}")
        print(f"Area ratio (sim/obs): {results.get('area_ratio')}")

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
    parser.add_argument("--resolution", type=float, default=30.0,
                        help="Shared-grid cell size, in the CRS units of the inputs "
                             "(metres for UTM). Both fires are rasterised on this ONE grid.")
    args = parser.parse_args()

    validate_inputs(args)
    results = process(args)

    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Results written: {args.output}")

    validate_outputs(args.output)


if __name__ == "__main__":
    main()
