#!/usr/bin/env python3
"""
parse_adcirc_output.py — Parse ADCIRC output files (fort.63/64, maxele, netCDF)
and extract results to CSV format for analysis.

Supports:
  - ASCII fort.63 (water elevation time series)
  - ASCII fort.64 (velocity time series)
  - ASCII maxele.63 (maximum elevation)
  - netCDF output files (fort.63.nc, maxele.63.nc, etc.)
  - Station extraction by coordinates (nearest node)

Output:
  - CSV file with time series at specified stations or all nodes
  - Summary statistics (max, min, mean, timing)
  - JSON summary report

Unit notes:
  - All output elevations are in meters relative to geoid
  - Velocities are in m/s (depth-averaged for 2D)
  - Time reference is seconds since cold start (convert via STATIM in fort.15)

Usage:
    # Extract all nodes from ASCII fort.63
    python parse_adcirc_output.py --work_dir ./run --format ascii \
        --output_csv results.csv --variables elevation

    # Extract specific stations
    python parse_adcirc_output.py --work_dir ./run --format ascii \
        --output_csv stations.csv --variables elevation,velocity \
        --stations "29.95,-90.07;30.03,-89.93"

    # Parse netCDF output
    python parse_adcirc_output.py --work_dir ./run --format netcdf \
        --output_csv results.csv --variables elevation
"""

import argparse
import csv
import json
import logging
import os
import sys

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DRY_VALUE = -99999.0  # ADCIRC sentinel for dry nodes
EARTH_RADIUS_M = 6378206.4


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate input parameters."""
    errors = []

    if not os.path.isdir(args.work_dir):
        errors.append(f"Work directory not found: {args.work_dir}")

    if args.format not in ("ascii", "netcdf"):
        errors.append(f"Unsupported format: {args.format}")

    valid_vars = {"elevation", "velocity", "wind", "pressure", "maxele", "maxvel"}
    requested = set(args.variables.split(","))
    unknown = requested - valid_vars
    if unknown:
        errors.append(f"Unknown variables: {unknown}. Valid: {valid_vars}")

    if args.stations:
        try:
            for pair in args.stations.split(";"):
                lat, lon = pair.split(",")
                float(lat)
                float(lon)
        except (ValueError, AttributeError):
            errors.append("Stations must be 'lat,lon;lat,lon' format")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} validation error(s)")


def validate_outputs(output_csv, summary_json):
    """Validate output files."""
    errors = []

    if output_csv and not os.path.isfile(output_csv):
        errors.append(f"Output CSV not created: {output_csv}")
    elif output_csv:
        with open(output_csv) as f:
            reader = csv.reader(f)
            header = next(reader, None)
            row_count = sum(1 for _ in reader)
        if row_count == 0:
            errors.append("Output CSV has no data rows")
        else:
            logger.info(f"Output CSV: {row_count} rows, {len(header)} columns")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} output validation error(s)")

    logger.info("Output validation passed")


# ---------------------------------------------------------------------------
# Mesh reader (for node coordinates / station matching)
# ---------------------------------------------------------------------------
def read_mesh_nodes(work_dir):
    """Read node coordinates from fort.14.

    Returns:
        nodes: dict of node_id → (lon, lat, depth)
        nn: total number of nodes
    """
    fort14 = os.path.join(work_dir, "fort.14")
    if not os.path.isfile(fort14):
        raise FileNotFoundError(f"fort.14 not found in {work_dir}")

    nodes = {}
    with open(fort14) as f:
        _header = f.readline()  # Grid name
        ne_nn = f.readline().strip().split()
        ne, nn = int(ne_nn[0]), int(ne_nn[1])

        for _ in range(nn):
            parts = f.readline().strip().split()
            nid = int(parts[0])
            x = float(parts[1])  # longitude
            y = float(parts[2])  # latitude
            dp = float(parts[3])  # depth (positive below geoid)
            nodes[nid] = (x, y, dp)

    logger.info(f"Read {nn} nodes from fort.14")
    return nodes, nn


def find_nearest_nodes(nodes, stations_str):
    """Find nearest mesh nodes to specified station coordinates.

    Args:
        nodes: dict of node_id → (lon, lat, depth)
        stations_str: "lat,lon;lat,lon;..." string

    Returns:
        list of (station_idx, node_id, lat, lon, distance_km)
    """
    results = []
    node_ids = list(nodes.keys())
    node_coords = np.array([(nodes[n][1], nodes[n][0]) for n in node_ids])  # lat, lon

    for si, pair in enumerate(stations_str.split(";")):
        lat, lon = [float(x) for x in pair.split(",")]

        # Haversine distance
        dlat = np.radians(node_coords[:, 0] - lat)
        dlon = np.radians(node_coords[:, 1] - lon)
        a = (np.sin(dlat / 2) ** 2 +
             np.cos(np.radians(lat)) *
             np.cos(np.radians(node_coords[:, 0])) *
             np.sin(dlon / 2) ** 2)
        dist_km = 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a)) / 1000

        nearest_idx = np.argmin(dist_km)
        nearest_nid = node_ids[nearest_idx]
        nearest_dist = dist_km[nearest_idx]

        results.append((si, nearest_nid, lat, lon, nearest_dist))
        logger.info(
            f"Station {si}: ({lat:.4f},{lon:.4f}) → "
            f"node {nearest_nid} (dist={nearest_dist:.2f} km)"
        )

    return results


# ---------------------------------------------------------------------------
# ASCII output readers
# ---------------------------------------------------------------------------
def read_fort63_ascii(filepath, node_filter=None):
    """Read ASCII fort.63 (water surface elevation time series).

    Format:
        Header: RUNDES, RUNID, AGRID (3 lines typically merged)
        NDSETSE NSTAE DTDP*NSPOOLE NSPOOLE IRTYPE
        Then for each timestep:
            TIME IT
            node1_value
            node2_value
            ...

    Args:
        filepath: Path to fort.63
        node_filter: Set of node IDs to extract (None = all)

    Returns:
        times: list of float (seconds since cold start)
        data: dict of node_id → list of values
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Not found: {filepath}")

    times = []
    data = {}

    with open(filepath) as f:
        # Skip header lines
        header1 = f.readline()  # RUNDES, RUNID, etc.
        header2 = f.readline().strip().split()
        ndsets = int(header2[0])  # number of datasets (timesteps)
        nn_out = int(header2[1])  # number of nodes in output

        logger.info(f"fort.63: {ndsets} timesteps, {nn_out} nodes")

        for ds in range(ndsets):
            time_line = f.readline().strip().split()
            t = float(time_line[0])
            times.append(t)

            for _ in range(nn_out):
                parts = f.readline().strip().split()
                nid = int(parts[0])
                val = float(parts[1])

                if node_filter and nid not in node_filter:
                    continue

                if nid not in data:
                    data[nid] = []
                data[nid].append(val if val > DRY_VALUE else np.nan)

    return times, data


def read_fort64_ascii(filepath, node_filter=None):
    """Read ASCII fort.64 (velocity time series).

    Each node has 2 values per timestep: u, v components (m/s).

    Returns:
        times: list of float
        u_data, v_data: dicts of node_id → list of values
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Not found: {filepath}")

    times = []
    u_data = {}
    v_data = {}

    with open(filepath) as f:
        header1 = f.readline()
        header2 = f.readline().strip().split()
        ndsets = int(header2[0])
        nn_out = int(header2[1])

        logger.info(f"fort.64: {ndsets} timesteps, {nn_out} nodes")

        for ds in range(ndsets):
            time_line = f.readline().strip().split()
            t = float(time_line[0])
            times.append(t)

            for _ in range(nn_out):
                parts = f.readline().strip().split()
                nid = int(parts[0])
                u = float(parts[1])
                v = float(parts[2])

                if node_filter and nid not in node_filter:
                    continue

                if nid not in u_data:
                    u_data[nid] = []
                    v_data[nid] = []

                u_data[nid].append(u if u > DRY_VALUE else np.nan)
                v_data[nid].append(v if v > DRY_VALUE else np.nan)

    return times, u_data, v_data


def read_maxele_ascii(filepath):
    """Read ASCII maxele.63 (maximum elevation at each node).

    Returns:
        dict of node_id → max_elevation (meters)
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Not found: {filepath}")

    maxele = {}
    with open(filepath) as f:
        header1 = f.readline()
        header2 = f.readline().strip().split()
        nn = int(header2[1])

        # Skip time/iteration line
        f.readline()

        for _ in range(nn):
            parts = f.readline().strip().split()
            nid = int(parts[0])
            val = float(parts[1])
            maxele[nid] = val if val > DRY_VALUE else np.nan

    logger.info(f"maxele.63: {len(maxele)} nodes")
    return maxele


# ---------------------------------------------------------------------------
# netCDF reader
# ---------------------------------------------------------------------------
def read_netcdf_output(work_dir, variables, node_filter=None):
    """Read ADCIRC netCDF output files.

    Returns:
        dict of variable → {times, data}
    """
    try:
        import netCDF4 as nc
    except ImportError:
        raise ImportError("netCDF4 required for netcdf format: pip install netCDF4")

    results = {}

    var_to_file = {
        "elevation": "fort.63.nc",
        "velocity": "fort.64.nc",
        "maxele": "maxele.63.nc",
        "wind": "fort.73.nc",
        "pressure": "fort.74.nc",
    }

    for var in variables:
        fname = var_to_file.get(var)
        if not fname:
            continue

        fpath = os.path.join(work_dir, fname)
        if not os.path.isfile(fpath):
            logger.warning(f"netCDF file not found: {fpath}")
            continue

        with nc.Dataset(fpath) as ds:
            if "time" in ds.variables:
                times = ds.variables["time"][:]
            else:
                times = [0]

            if var == "elevation" and "zeta" in ds.variables:
                vals = ds.variables["zeta"][:]
            elif var == "velocity":
                u = ds.variables.get("u-vel", ds.variables.get("u", None))
                v = ds.variables.get("v-vel", ds.variables.get("v", None))
                if u is not None and v is not None:
                    vals = np.sqrt(u[:] ** 2 + v[:] ** 2)
                else:
                    continue
            elif var == "maxele" and "zeta_max" in ds.variables:
                vals = ds.variables["zeta_max"][:]
            else:
                # Try generic variable name
                var_names = [v for v in ds.variables if v not in
                             ("time", "x", "y", "depth", "node", "element")]
                if var_names:
                    vals = ds.variables[var_names[0]][:]
                else:
                    continue

            # Replace fill values with NaN
            if hasattr(vals, "filled"):
                vals = vals.filled(np.nan)
            vals = np.where(vals <= DRY_VALUE, np.nan, vals)

            results[var] = {"times": list(times), "data": vals}
            logger.info(f"Read {var} from {fname}: shape={vals.shape}")

    return results


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------
def write_csv(output_path, times, columns, data_dict, nodes_info=None):
    """Write parsed data to CSV.

    Args:
        output_path: Output CSV file path
        times: list of timestamps
        columns: list of column names
        data_dict: dict of column_name → list of values
        nodes_info: optional dict of node_id → (lon, lat)
    """
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        header = ["time_s"] + columns
        if nodes_info:
            header = ["node_id", "lon", "lat"] + header
        writer.writerow(header)

        if nodes_info:
            # Write per-node data
            for nid in sorted(data_dict.keys()):
                vals = data_dict[nid]
                lon, lat = nodes_info.get(nid, (0, 0))[:2]
                for ti, t in enumerate(times):
                    row = [nid, f"{lon:.6f}", f"{lat:.6f}", f"{t:.1f}"]
                    if isinstance(vals, list) and ti < len(vals):
                        row.append(f"{vals[ti]:.6f}" if not np.isnan(vals[ti]) else "")
                    writer.writerow(row)
        else:
            # Write simple time series
            for ti, t in enumerate(times):
                row = [f"{t:.1f}"]
                for col in columns:
                    if col in data_dict and ti < len(data_dict[col]):
                        v = data_dict[col][ti]
                        row.append(f"{v:.6f}" if not np.isnan(v) else "")
                    else:
                        row.append("")
                writer.writerow(row)

    logger.info(f"Wrote {output_path}")


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def compute_statistics(data, variable_name="elevation"):
    """Compute summary statistics from parsed data."""
    all_vals = []
    if isinstance(data, dict):
        for nid, vals in data.items():
            all_vals.extend([v for v in vals if not np.isnan(v)])
    elif isinstance(data, np.ndarray):
        all_vals = data[~np.isnan(data)].tolist()

    if not all_vals:
        return {"count": 0, "warning": "No valid data"}

    arr = np.array(all_vals)
    stats = {
        "variable": variable_name,
        "count": len(arr),
        "min": round(float(np.min(arr)), 4),
        "max": round(float(np.max(arr)), 4),
        "mean": round(float(np.mean(arr)), 4),
        "std": round(float(np.std(arr)), 4),
        "p05": round(float(np.percentile(arr, 5)), 4),
        "p95": round(float(np.percentile(arr, 95)), 4),
    }

    # Check for suspicious values
    if variable_name == "elevation" and stats["max"] > 30:
        stats["warning"] = (
            f"Max elevation {stats['max']:.1f}m is very high — "
            f"check for unit or stability issues"
        )
    if variable_name == "velocity" and stats["max"] > 20:
        stats["warning"] = (
            f"Max velocity {stats['max']:.1f} m/s is very high — "
            f"check CFL and stability"
        )

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def process(args):
    """Main pipeline: validate → read → extract → write → validate."""

    # Step 1: Validate inputs
    validate_inputs(args)

    variables = args.variables.split(",")

    # Step 2: Read mesh for coordinate mapping
    nodes = None
    node_filter = None
    station_nodes = None

    if args.stations:
        nodes, nn = read_mesh_nodes(args.work_dir)
        station_nodes = find_nearest_nodes(nodes, args.stations)
        node_filter = {sn[1] for sn in station_nodes}

    # Step 3: Read output data
    all_stats = []

    if args.format == "ascii":
        combined_data = {}
        times = []

        for var in variables:
            if var == "elevation":
                fpath = os.path.join(args.work_dir, "fort.63")
                if os.path.isfile(fpath):
                    times, data = read_fort63_ascii(fpath, node_filter)
                    combined_data.update(data)
                    all_stats.append(compute_statistics(data, "elevation"))

            elif var == "velocity":
                fpath = os.path.join(args.work_dir, "fort.64")
                if os.path.isfile(fpath):
                    vt, u_data, v_data = read_fort64_ascii(fpath, node_filter)
                    if not times:
                        times = vt
                    # Compute speed
                    for nid in u_data:
                        speed = [
                            np.sqrt(u ** 2 + v ** 2)
                            for u, v in zip(u_data[nid], v_data[nid])
                        ]
                        combined_data[f"speed_{nid}"] = speed
                    all_stats.append(compute_statistics(
                        {n: [np.sqrt(u**2+v**2) for u, v in zip(u_data[n], v_data[n])]
                         for n in u_data},
                        "velocity"
                    ))

            elif var == "maxele":
                fpath = os.path.join(args.work_dir, "maxele.63")
                if os.path.isfile(fpath):
                    maxele = read_maxele_ascii(fpath)
                    all_stats.append(compute_statistics(
                        {n: [v] for n, v in maxele.items()}, "maxele"
                    ))

        # Write CSV
        if combined_data and times:
            nodes_info = None
            if nodes:
                nodes_info = nodes
            write_csv(
                args.output_csv, times, variables, combined_data, nodes_info
            )

    elif args.format == "netcdf":
        nc_results = read_netcdf_output(args.work_dir, variables, node_filter)
        for var, vdata in nc_results.items():
            all_stats.append(compute_statistics(vdata["data"], var))

    # Step 4: Write summary JSON
    summary = {
        "work_dir": args.work_dir,
        "format": args.format,
        "variables": variables,
        "statistics": all_stats,
    }
    if station_nodes:
        summary["stations"] = [
            {"idx": s[0], "node_id": s[1],
             "target_lat": s[2], "target_lon": s[3],
             "distance_km": round(s[4], 3)}
            for s in station_nodes
        ]

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
            f"min={stat.get('min','N/A')}, max={stat.get('max','N/A')}, "
            f"mean={stat.get('mean','N/A')}"
        )
        if "warning" in stat:
            logger.warning(f"  {stat['warning']}")


def main():
    parser = argparse.ArgumentParser(
        description="Parse ADCIRC output files and extract to CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--work_dir", required=True,
                        help="ADCIRC run directory containing output files")
    parser.add_argument("--format", choices=["ascii", "netcdf"],
                        default="ascii",
                        help="Output file format (default: ascii)")
    parser.add_argument("--output_csv", required=True,
                        help="Output CSV file path")
    parser.add_argument("--variables", default="elevation",
                        help="Comma-separated: elevation,velocity,maxele,wind,pressure")
    parser.add_argument("--stations", default=None,
                        help="Station coords: 'lat,lon;lat,lon' (extracts nearest nodes)")

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
