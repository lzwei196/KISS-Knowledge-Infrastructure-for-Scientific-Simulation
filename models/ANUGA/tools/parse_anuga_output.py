#!/usr/bin/env python3
"""
parse_anuga_output.py — Extract stage, velocity, and discharge from ANUGA SWW output.

Reads an ANUGA SWW (NetCDF) output file and extracts:
  - Stage time series at specified gauge points
  - Discharge through user-defined cross-sections (via get_flow_through_cross_section)
  - Summary statistics and performance metrics

ANUGA solves for stage (water surface elevation) and momentum (uh, vh).
Discharge is computed from momentum integrated across a cross-section polyline.

Usage:
    # Extract discharge at outlet cross-section
    python parse_anuga_output.py \
        --sww_file ./output/anuga_sim.sww \
        --cross_section "-2500,0,2500,0" \
        --output_csv ./output/discharge.csv

    # Extract stage at a gauge point
    python parse_anuga_output.py \
        --sww_file ./output/anuga_sim.sww \
        --gauge_xy "0,0" \
        --output_csv ./output/stage.csv

Output:
    discharge.csv — columns: time_seconds, discharge_m3s
    stage.csv — columns: time_seconds, stage_m, depth_m
    output_summary.json — metadata and statistics
"""

import argparse
import csv
import json
import logging
import os
import sys

import numpy as np

# Ensure ki_tools_common is importable
_ki_common = "/mnt/disk1/Hydrocraft_server/models/ki_tools_common"
if _ki_common not in sys.path:
    sys.path.insert(0, _ki_common)

# HydroCraft python env
_penv = "/mnt/disk1/Hydrocraft_server/python_env/lib/python3.12/site-packages"
if _penv not in sys.path:
    sys.path.insert(0, _penv)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate input parameters."""
    errors = []

    if not os.path.isfile(args.sww_file):
        errors.append(f"SWW file not found: {args.sww_file}")

    if not args.cross_section and not args.gauge_xy and not args.inundation_extent:
        errors.append("Must specify --cross_section, --gauge_xy and/or --inundation_extent")

    if args.inundation_extent:
        if args.center_lat is None or args.center_lon is None:
            errors.append("--inundation_extent requires --center_lat and --center_lon")
        if not args.obs_mask or not os.path.isfile(args.obs_mask):
            errors.append("--inundation_extent requires a readable --obs_mask: %s" % args.obs_mask)

    if args.cross_section:
        try:
            coords = [float(x) for x in args.cross_section.split(",")]
            if len(coords) != 4:
                errors.append("--cross_section must be 'x1,y1,x2,y2' (4 values)")
        except ValueError:
            errors.append("--cross_section must be numeric 'x1,y1,x2,y2'")

    if args.gauge_xy:
        try:
            coords = [float(x) for x in args.gauge_xy.split(",")]
            if len(coords) != 2:
                errors.append("--gauge_xy must be 'x,y' (2 values)")
        except ValueError:
            errors.append("--gauge_xy must be numeric 'x,y'")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} validation error(s)")


def validate_outputs(output_csv, summary_json):
    """Validate output files."""
    errors = []

    if output_csv and os.path.isfile(output_csv):
        with open(output_csv) as f:
            reader = csv.reader(f)
            header = next(reader, None)
            rows = list(reader)
        if len(rows) == 0:
            errors.append(f"Output CSV {output_csv} has no data rows")
        else:
            logger.info(f"Output CSV: {len(rows)} rows, {len(header)} columns")
    elif output_csv:
        errors.append(f"Output CSV not created: {output_csv}")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} output validation error(s)")

    logger.info("Output validation passed")


# ---------------------------------------------------------------------------
# SWW readers
# ---------------------------------------------------------------------------
def extract_discharge(sww_file, cross_section_coords):
    """Extract discharge time series through a cross-section from SWW file.

    Uses anuga.get_flow_through_cross_section for post-simulation extraction.

    Args:
        sww_file: Path to SWW file
        cross_section_coords: [x1, y1, x2, y2]

    Returns:
        times: numpy array of time values (seconds)
        discharge: numpy array of discharge values (m³/s)
    """
    import anuga

    x1, y1, x2, y2 = cross_section_coords
    polyline = [[x1, y1], [x2, y2]]

    logger.info(f"Extracting discharge through cross-section "
                f"({x1},{y1}) → ({x2},{y2})")

    time_vals, Q_vals = anuga.get_flow_through_cross_section(
        sww_file, polyline, verbose=False
    )

    times = np.array(time_vals, dtype=np.float64)
    discharge = np.array(Q_vals, dtype=np.float64)

    logger.info(f"Extracted {len(times)} timesteps, "
                f"Q range: {np.min(discharge):.4f} to {np.max(discharge):.4f} m³/s")

    return times, discharge


def extract_stage_at_gauge(sww_file, gauge_xy, snap_to_channel_m=0.0,
                           diagnostics=None):
    """Extract stage and depth time series at a gauge point from SWW file.

    Reads the SWW NetCDF directly and finds the nearest mesh vertex to the
    gauge point.

    Args:
        sww_file: Path to SWW file
        gauge_xy: [x, y] in the ABSOLUTE frame (metres from the domain centre,
            +/-extent_m/2) — the same frame --inlet_xy uses. The SWW stores
            mesh-relative x/y plus xllcorner/yllcorner and this function adds
            them back, so do NOT pass mesh-relative coordinates.
        snap_to_channel_m: if > 0, snap the extraction point to the LOWEST-
            elevation vertex within this radius of the gauge. A stream gauge
            records the water surface of the channel, but its published
            lat/lon is a bank/structure position; on a 30-90 m DEM the nearest
            mesh vertex is routinely a bank cell that never wets, which yields
            a CONSTANT stage equal to the bank elevation and a meaningless
            NSE. Snapping to the local channel low point is the physically
            correct comparison location. The snap distance and elevation drop
            are logged and returned so the choice stays auditable.
        diagnostics: optional dict, filled with the extraction diagnostics.

    Returns:
        times: numpy array of time values (seconds)
        stage: numpy array of stage values (m)
        depth: numpy array of water depth values (m)
    """
    from anuga.file.netcdf import NetCDFFile

    gx, gy = gauge_xy

    nc = NetCDFFile(sww_file, "r")
    try:
        x = np.asarray(nc.variables["x"][:], dtype=float)
        y = np.asarray(nc.variables["y"][:], dtype=float)
        time_var = np.asarray(nc.variables["time"][:], dtype=float)
        stage_var = np.asarray(nc.variables["stage"][:], dtype=float)
        elev_var = np.asarray(nc.variables["elevation"][:], dtype=float)

        xllcorner = float(getattr(nc, "xllcorner", 0.0))
        yllcorner = float(getattr(nc, "yllcorner", 0.0))
    finally:
        nc.close()

    x_abs = x + xllcorner
    y_abs = y + yllcorner

    # Handle elevation: may be time-varying or constant
    elev_all = elev_var if elev_var.ndim == 1 else elev_var[0, :]

    # Find nearest vertex
    dist = np.sqrt((x_abs - gx) ** 2 + (y_abs - gy) ** 2)
    nearest_idx = int(np.argmin(dist))
    nearest_dist = float(dist[nearest_idx])

    if nearest_dist > 0.0 and not np.isfinite(nearest_dist):
        raise ValueError("Gauge point produced a non-finite mesh distance")

    logger.info(f"Gauge ({gx},{gy}): nearest vertex {nearest_idx}, "
                f"distance {nearest_dist:.2f} m, "
                f"elevation {elev_all[nearest_idx]:.2f} m")

    idx = nearest_idx
    snap_dist = 0.0
    if snap_to_channel_m and snap_to_channel_m > 0.0:
        within = np.flatnonzero(dist <= float(snap_to_channel_m))
        if within.size == 0:
            raise ValueError(
                f"No mesh vertex within {snap_to_channel_m} m of the gauge "
                f"({gx}, {gy}); --snap_to_channel_m is smaller than the mesh "
                "spacing, or the gauge lies outside the domain."
            )
        idx = int(within[int(np.argmin(elev_all[within]))])
        snap_dist = float(dist[idx])
        logger.info(
            "Snapped to channel low point within %.0f m: vertex %d at "
            "%.1f m from the gauge, elevation %.2f m (was %.2f m at the "
            "nearest vertex; drop %.2f m)",
            snap_to_channel_m, idx, snap_dist, elev_all[idx],
            elev_all[nearest_idx], elev_all[nearest_idx] - elev_all[idx],
        )

    elev_at_gauge = float(elev_all[idx])
    stage = stage_var[:, idx]
    depth = np.maximum(stage - elev_at_gauge, 0.0)

    # A gauge vertex that never wets returns a constant stage == elevation.
    # That is not a model result; report it loudly rather than let a flat
    # series be scored as if it were one.
    wet_frac = float(np.mean(depth > 1e-3))
    if wet_frac < 0.5:
        logger.warning(
            "Gauge vertex is wet in only %.0f%% of stored timesteps "
            "(depth > 1 mm); the stage series is partly the dry bed "
            "elevation, not a simulated water surface. Consider "
            "--snap_to_channel_m or a finer mesh.", 100 * wet_frac)

    if diagnostics is not None:
        diagnostics.update({
            "gauge_xy_abs": [float(gx), float(gy)],
            "nearest_vertex": nearest_idx,
            "nearest_vertex_distance_m": round(nearest_dist, 2),
            "nearest_vertex_elevation_m": round(float(elev_all[nearest_idx]), 3),
            "snap_to_channel_m": float(snap_to_channel_m or 0.0),
            "used_vertex": idx,
            "used_vertex_distance_m": round(snap_dist or nearest_dist, 2),
            "used_vertex_elevation_m": round(elev_at_gauge, 3),
            "wet_fraction": round(wet_frac, 4),
            "n_vertices": int(x_abs.size),
        })

    return time_var, stage, depth


# ---------------------------------------------------------------------------
# Inundation extent (dag output validation_rank 1; determining_metric csi)
# ---------------------------------------------------------------------------
def compute_inundation_extent(sww_file, center_lat, center_lon,
                              depth_threshold, obs_mask):
    """Peak inundation extent from SWW vs an observed flood mask.

    Model wet/dry = max over time of (stage - elevation) > depth_threshold.
    Mesh (0..extent) is mapped to lon/lat with the same equirectangular
    mapping run_anuga.build_bounding_polygon/latlon_to_utm use.
    Observed mask: GFD GeoTIFF band 1 'flooded' (-inf nodata, 0 dry, 1 wet).
    Returns a dict of footprint, contingency counts and CSI/POD/FAR.
    """
    import rasterio
    from scipy.spatial import cKDTree
    from anuga.file.netcdf import NetCDFFile

    nc = NetCDFFile(sww_file, "r")
    try:
        x = np.asarray(nc.variables["x"][:], dtype=float)
        y = np.asarray(nc.variables["y"][:], dtype=float)
        stage = np.asarray(nc.variables["stage"][:], dtype=float)
        elev = np.asarray(nc.variables["elevation"][:], dtype=float)
    finally:
        nc.close()

    elev2 = elev if elev.ndim == 1 else elev[0]
    peak = np.maximum(stage - elev2[None, :], 0.0).max(axis=0)
    wet = peak > depth_threshold

    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * np.cos(np.radians(center_lat))
    cx = 0.5 * (x.min() + x.max())
    cy = 0.5 * (y.min() + y.max())
    lon_v = center_lon + (x - cx) / m_per_deg_lon
    lat_v = center_lat + (y - cy) / m_per_deg_lat
    lon_min, lon_max = float(lon_v.min()), float(lon_v.max())
    lat_min, lat_max = float(lat_v.min()), float(lat_v.max())

    logger.info("Model footprint lon[%.4f,%.4f] lat[%.4f,%.4f]; "
                "peak depth max=%.3f m; wet vertices (>%.3g m)=%d/%d"
                % (lon_min, lon_max, lat_min, lat_max, peak.max(),
                   depth_threshold, int(wet.sum()), wet.size))

    with rasterio.open(obs_mask) as src:
        obs_crs = str(src.crs)
        full = src.read(1)
        obs_valid_pixels = int(np.isfinite(full).sum())
        del full
        r0, c0 = src.index(lon_min, lat_max)
        r1, c1 = src.index(lon_max, lat_min)
        r0, r1 = min(r0, r1), max(r0, r1)
        c0, c1 = min(c0, c1), max(c0, c1)
        r0 = max(0, r0); c0 = max(0, c0)
        r1 = min(src.height - 1, r1); c1 = min(src.width - 1, c1)
        win = rasterio.windows.Window(c0, r0, c1 - c0 + 1, r1 - r0 + 1)
        band = src.read(1, window=win)
        wt = src.window_transform(win)

    nr, nc_ = band.shape
    rr, cc = np.mgrid[0:nr, 0:nc_]
    lons = wt.c + (cc + 0.5) * wt.a
    lats = wt.f + (rr + 0.5) * wt.e

    keep = (np.isfinite(band) & (lons >= lon_min) & (lons <= lon_max)
            & (lats >= lat_min) & (lats <= lat_max))
    obs_wet = band[keep] == 1
    px_lon = lons[keep]
    px_lat = lats[keep]

    tree = cKDTree(np.column_stack([lon_v, lat_v]))
    _, idx = tree.query(np.column_stack([px_lon, px_lat]), k=1)
    mod_wet = wet[idx]

    hits = int(np.sum(obs_wet & mod_wet))
    misses = int(np.sum(obs_wet & ~mod_wet))
    fa = int(np.sum(~obs_wet & mod_wet))
    cn = int(np.sum(~obs_wet & ~mod_wet))

    csi = hits / (hits + misses + fa) if (hits + misses + fa) else None
    pod = hits / (hits + misses) if (hits + misses) else None
    far = fa / (hits + fa) if (hits + fa) else None

    logger.info("Categorical scores over %d pixels: CSI=%s POD=%s FAR=%s "
                "(hits=%d misses=%d FA=%d)"
                % (int(keep.sum()),
                   "%.6f" % csi if csi is not None else "NA",
                   "%.6f" % pod if pod is not None else "NA",
                   "%.6f" % far if far is not None else "NA",
                   hits, misses, fa))

    return {
        "sww_file": sww_file,
        "center_lat": center_lat,
        "center_lon": center_lon,
        "depth_threshold_m": depth_threshold,
        "model_footprint": {"lon_min": lon_min, "lon_max": lon_max,
                            "lat_min": lat_min, "lat_max": lat_max},
        "peak_depth_max_m": round(float(peak.max()), 4),
        "wet_vertices": int(wet.sum()),
        "n_vertices": int(wet.size),
        "obs_crs": obs_crs,
        "obs_valid_pixels": obs_valid_pixels,
        "obs_pixels_in_model_footprint": int(keep.sum()),
        "hits": hits, "misses": misses,
        "false_alarms": fa, "correct_negatives": cn,
        "obs_wet_in_footprint": int(obs_wet.sum()),
        "model_wet_in_footprint": int(mod_wet.sum()),
        "csi": round(csi, 6) if csi is not None else None,
        "pod": round(pod, 6) if pod is not None else None,
        "far": round(far, 6) if far is not None else None,
    }


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def compute_statistics(values, variable_name):
    """Compute summary statistics for a time series."""
    arr = np.array(values, dtype=float)
    valid = arr[np.isfinite(arr)]

    if len(valid) == 0:
        return {"variable": variable_name, "count": 0, "warning": "No valid data"}

    stats = {
        "variable": variable_name,
        "count": len(valid),
        "min": round(float(np.min(valid)), 6),
        "max": round(float(np.max(valid)), 6),
        "mean": round(float(np.mean(valid)), 6),
        "std": round(float(np.std(valid)), 6),
    }

    if variable_name == "discharge_m3s":
        stats["total_volume_m3"] = round(float(np.trapz(valid)), 2)
        if stats["max"] > 10000:
            stats["warning"] = (
                f"Max discharge {stats['max']:.1f} m³/s is very high — "
                f"check mesh resolution and forcing"
            )

    return stats


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process(args):
    """Main pipeline: validate → extract → write → validate."""

    # Step 1: Validate inputs
    validate_inputs(args)

    output_dir = os.path.dirname(args.output_csv) or "."
    os.makedirs(output_dir, exist_ok=True)

    all_stats = []

    # Step 2: Extract discharge if cross-section specified
    if args.cross_section:
        coords = [float(x) for x in args.cross_section.split(",")]
        times, discharge = extract_discharge(args.sww_file, coords)

        # Write discharge CSV
        discharge_csv = args.output_csv
        with open(discharge_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time_seconds", "discharge_m3s"])
            for t, q in zip(times, discharge):
                writer.writerow([f"{t:.1f}", f"{q:.6f}"])

        logger.info(f"Wrote {discharge_csv}")
        all_stats.append(compute_statistics(discharge, "discharge_m3s"))

    # Step 3: Extract stage at gauge if specified
    gauge_diag = {}
    if args.gauge_xy:
        gcoords = [float(x) for x in args.gauge_xy.split(",")]
        times, stage, depth = extract_stage_at_gauge(
            args.sww_file, gcoords,
            snap_to_channel_m=args.snap_to_channel_m,
            diagnostics=gauge_diag,
        )

        # Write stage CSV (separate file if discharge also requested)
        if args.cross_section:
            stage_csv = args.output_csv.replace(".csv", "_stage.csv")
        else:
            stage_csv = args.output_csv

        with open(stage_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time_seconds", "stage_m", "depth_m"])
            for t, s, d in zip(times, stage, depth):
                writer.writerow([f"{t:.1f}", f"{s:.6f}", f"{d:.6f}"])

        logger.info(f"Wrote {stage_csv}")
        all_stats.append(compute_statistics(stage, "stage_m"))
        all_stats.append(compute_statistics(depth, "depth_m"))

    # Step 3b: Inundation extent + categorical scores
    if args.inundation_extent:
        res = compute_inundation_extent(
            args.sww_file, args.center_lat, args.center_lon,
            args.depth_threshold, args.obs_mask,
        )
        csi_path = os.path.join(output_dir, "inundation_csi.json")
        with open(csi_path, "w") as f:
            json.dump(res, f, indent=2)
        logger.info("Inundation-extent result: csi=%s" % res["csi"])

        # --output_csv is declared required, and validate_outputs() hard-
        # fails if it is absent. In inundation-only mode nothing else
        # writes it, so emit the scores there; when a discharge/stage
        # series owns --output_csv, write a sibling instead of clobbering.
        if args.cross_section or args.gauge_xy:
            inund_csv = args.output_csv.replace(".csv", "_inundation.csv")
        else:
            inund_csv = args.output_csv
        with open(inund_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value"])
            for _k in ("csi", "pod", "far", "hits", "misses",
                       "false_alarms", "correct_negatives",
                       "obs_wet_in_footprint", "model_wet_in_footprint",
                       "obs_pixels_in_model_footprint", "peak_depth_max_m",
                       "wet_vertices", "n_vertices", "depth_threshold_m"):
                writer.writerow([_k, res[_k]])
        logger.info(f"Wrote {inund_csv}")
        all_stats.append({"variable": "inundation_extent", "count": 1,
                          "csi": res["csi"], "pod": res["pod"],
                          "far": res["far"]})

    # Step 4: Write summary JSON
    summary = {
        "sww_file": args.sww_file,
        "n_timesteps": len(times) if 'times' in dir() else 0,
        "statistics": all_stats,
    }

    if args.cross_section:
        summary["cross_section"] = args.cross_section
    if args.gauge_xy:
        summary["gauge_xy"] = args.gauge_xy
        summary["gauge_extraction"] = gauge_diag
    if args.inundation_extent:
        summary["inundation_extent"] = res

    summary_path = args.output_csv.replace(".csv", "_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Summary written to {summary_path}")

    # Step 5: Validate outputs
    validate_outputs(args.output_csv, summary_path)

    # Print statistics
    for stat in all_stats:
        logger.info(
            f"  {stat['variable']}: "
            f"min={stat.get('min', 'N/A')}, max={stat.get('max', 'N/A')}, "
            f"mean={stat.get('mean', 'N/A')}"
        )
        if "warning" in stat:
            logger.warning(f"  {stat['warning']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Parse ANUGA SWW output — extract stage, depth, and discharge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--sww_file", required=True,
                        help="Path to ANUGA SWW output file")
    parser.add_argument("--cross_section", default=None,
                        help="Cross-section for discharge: 'x1,y1,x2,y2' (meters)")
    parser.add_argument("--gauge_xy", default=None,
                        help="Gauge point for stage extraction: 'x,y' in the "
                             "ABSOLUTE frame (metres from the domain centre, "
                             "+/-extent_m/2) — same frame as run_anuga.py "
                             "--inlet_xy, NOT mesh-relative")
    parser.add_argument("--gauge_latlon", default=None,
                        help="Gauge point as 'lat,lon'; converted to the "
                             "absolute frame using --center_lat/--center_lon "
                             "and run_anuga.latlon_to_domain_xy. Alternative "
                             "to --gauge_xy")
    parser.add_argument("--snap_to_channel_m", type=float, default=0.0,
                        help="Snap the stage-extraction point to the lowest-"
                             "elevation mesh vertex within this radius (m). A "
                             "published gauge lat/lon is a bank position; on a "
                             "30-90 m DEM the nearest vertex is often a bank "
                             "cell that never wets and returns a constant "
                             "stage. 0 disables snapping (default)")
    parser.add_argument("--output_csv", required=True,
                        help="Output CSV file path (also used to locate the output dir)")
    parser.add_argument("--inundation_extent", action="store_true",
                        help="Compute peak inundation extent and CSI/POD/FAR vs --obs_mask")
    parser.add_argument("--center_lat", type=float, default=None,
                        help="Domain center latitude (must match run_anuga.py --lat)")
    parser.add_argument("--center_lon", type=float, default=None,
                        help="Domain center longitude (must match run_anuga.py --lon)")
    parser.add_argument("--depth_threshold", type=float, default=0.1,
                        help="Depth (m) above which a cell counts as flooded")
    parser.add_argument("--obs_mask", default=None,
                        help="Observed flood mask GeoTIFF (GFD band 1 = flooded)")

    args = parser.parse_args()

    if args.gauge_latlon:
        if args.gauge_xy:
            parser.error("Give --gauge_xy or --gauge_latlon, not both")
        if args.center_lat is None or args.center_lon is None:
            parser.error("--gauge_latlon requires --center_lat and --center_lon")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from run_anuga import latlon_to_domain_xy
        glat, glon = (float(v) for v in args.gauge_latlon.split(","))
        gx, gy = latlon_to_domain_xy(args.center_lat, args.center_lon,
                                     glat, glon)
        args.gauge_xy = f"{gx},{gy}"
        logger.info("Gauge lat/lon (%.5f, %.5f) -> absolute frame "
                    "(%.0f, %.0f) m", glat, glon, gx, gy)

    process(args)


if __name__ == "__main__":
    main()
