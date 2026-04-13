#!/usr/bin/env python3
"""
parse_geoclaw_output.py — Parse GeoClaw output files and extract results to CSV.

Reads fort.q (solution), fort.t (timing), fort.gauge (gauge time series),
and fgmax (maximum values) files from a GeoClaw _output directory and
converts them to CSV format for analysis.

OUTPUT VARIABLES:
  - h:   water depth (meters)
  - hu:  x-momentum (m²/s) — divide by h to get u velocity
  - hv:  y-momentum (m²/s) — divide by h to get v velocity
  - eta: surface elevation (meters) = h + bathymetry
  - speed: water speed (m/s) = sqrt((hu/h)² + (hv/h)²)

Pattern: validate_inputs → process → validate_outputs
"""

import argparse
import json
import os
import sys
import re
import glob
import numpy as np


def validate_inputs(args):
    """Phase 1: Validate input directory and files."""
    errors = []
    warnings = []

    # Check output directory
    if not os.path.isdir(args.output_dir):
        errors.append(f"Output directory not found: {args.output_dir}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    # Check for expected files
    q_files = sorted(glob.glob(os.path.join(args.output_dir, "fort.q*")))
    t_files = sorted(glob.glob(os.path.join(args.output_dir, "fort.t*")))

    if not q_files:
        errors.append(f"No fort.q files found in {args.output_dir}")
    if not t_files:
        warnings.append(f"No fort.t files found — timing info unavailable")

    # Check gauge file
    gauge_file = os.path.join(args.output_dir, "fort.gauge")
    if not os.path.isfile(gauge_file):
        warnings.append("No fort.gauge file — no gauge data available")

    # Check requested format
    if args.format not in ["csv", "json", "numpy"]:
        errors.append(f"format must be csv, json, or numpy, got {args.format}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return warnings


def _parse_fort_t(filepath):
    """Parse a fort.tNNNN file to extract frame metadata."""
    meta = {}
    with open(filepath, "r") as f:
        lines = f.readlines()

    if len(lines) >= 6:
        meta["time"] = float(lines[0].split()[0])
        meta["meqn"] = int(lines[1].split()[0])
        meta["ngrids"] = int(lines[2].split()[0])
        meta["naux"] = int(lines[3].split()[0])
        meta["ndim"] = int(lines[4].split()[0])
        meta["nghost"] = int(lines[5].split()[0])
    return meta


def _parse_fort_q(filepath, meqn=3, ndim=2):
    """Parse a fort.qNNNN file to extract solution data for all AMR grids."""
    grids = []

    with open(filepath, "r") as f:
        content = f.read()

    # Split by grid headers
    # Each grid starts with a header block containing grid_number, AMR_level, mx, my, etc.
    blocks = content.strip().split("\n\n")

    i = 0
    while i < len(blocks):
        block = blocks[i].strip()
        if not block:
            i += 1
            continue

        lines = block.split("\n")

        # Try to parse as header
        try:
            header = {}
            if len(lines) >= 7:
                header["grid_number"] = int(lines[0].split()[0])
                header["AMR_level"] = int(lines[1].split()[0])
                header["mx"] = int(lines[2].split()[0])
                header["my"] = int(lines[3].split()[0])
                header["xlow"] = float(lines[4].split()[0])
                header["ylow"] = float(lines[5].split()[0])
                header["dx"] = float(lines[6].split()[0])
                header["dy"] = float(lines[7].split()[0]) if len(lines) > 7 else header["dx"]

                # Data follows in next block or remaining lines
                data_lines = lines[8:] if len(lines) > 8 else []
                if not data_lines and i + 1 < len(blocks):
                    i += 1
                    data_lines = blocks[i].strip().split("\n")

                mx = header["mx"]
                my = header["my"]

                # Parse data values
                values = []
                for dl in data_lines:
                    vals = dl.split()
                    values.extend([float(v) for v in vals])

                expected = mx * my * meqn
                if len(values) >= expected:
                    q = np.array(values[:expected]).reshape(my, mx, meqn)
                    header["q"] = q

                    # Compute derived quantities
                    h = q[:, :, 0]
                    hu = q[:, :, 1]
                    hv = q[:, :, 2] if meqn > 2 else np.zeros_like(h)

                    # Compute velocity (avoid division by zero in dry cells)
                    dry = h < 1e-6
                    u = np.where(dry, 0.0, hu / h)
                    v = np.where(dry, 0.0, hv / h)
                    speed = np.sqrt(u**2 + v**2)

                    header["h_max"] = float(np.max(h))
                    header["h_mean"] = float(np.mean(h[~dry])) if np.any(~dry) else 0.0
                    header["speed_max"] = float(np.max(speed))

                grids.append(header)
        except (ValueError, IndexError):
            pass

        i += 1

    return grids


def _parse_gauge_file(filepath):
    """Parse fort.gauge file to extract gauge time series."""
    gauges = {}

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                gauge_id = int(parts[0])
                level = int(parts[1])
                t = float(parts[2])
                q_vals = [float(v) for v in parts[3:]]

                if gauge_id not in gauges:
                    gauges[gauge_id] = {"time": [], "level": [], "q": []}
                gauges[gauge_id]["time"].append(t)
                gauges[gauge_id]["level"].append(level)
                gauges[gauge_id]["q"].append(q_vals)
            except (ValueError, IndexError):
                continue

    # Convert to numpy arrays
    for gid in gauges:
        gauges[gid]["time"] = np.array(gauges[gid]["time"])
        gauges[gid]["q"] = np.array(gauges[gid]["q"])

    return gauges


def process(args, input_warnings):
    """Phase 2: Parse output files and extract data."""
    warnings = list(input_warnings)
    outdir = args.output_dir

    result = {
        "status": "success",
        "output_dir": outdir,
        "warnings": warnings,
    }

    # Parse all frames
    t_files = sorted(glob.glob(os.path.join(outdir, "fort.t*")))
    q_files = sorted(glob.glob(os.path.join(outdir, "fort.q*")))

    frames = []
    for tf, qf in zip(t_files, q_files):
        meta = _parse_fort_t(tf)
        grids = _parse_fort_q(qf, meqn=meta.get("meqn", 3))

        frame = {
            "frame": int(re.search(r"\d+", os.path.basename(tf)).group()),
            "time": meta.get("time", 0.0),
            "n_grids": len(grids),
            "h_max": max((g.get("h_max", 0) for g in grids), default=0),
            "speed_max": max((g.get("speed_max", 0) for g in grids), default=0),
        }
        frames.append(frame)

    result["n_frames"] = len(frames)
    result["frames"] = frames
    if frames:
        result["time_range"] = [frames[0]["time"], frames[-1]["time"]]

    # Parse gauges
    gauge_file = os.path.join(outdir, "fort.gauge")
    gauge_data = {}
    if os.path.isfile(gauge_file):
        gauge_data = _parse_gauge_file(gauge_file)
        result["n_gauges"] = len(gauge_data)
        result["gauge_ids"] = list(gauge_data.keys())

    # Write CSV output
    if args.outfile:
        _write_output(args.outfile, args.format, frames, gauge_data)
        result["outfile"] = args.outfile

    return result, gauge_data


def _write_output(outfile, fmt, frames, gauge_data):
    """Write parsed data to output file."""
    if fmt == "csv":
        with open(outfile, "w") as f:
            # Write frame summary
            f.write("# Frame Summary\n")
            f.write("frame,time_s,n_grids,h_max_m,speed_max_ms\n")
            for fr in frames:
                f.write(f"{fr['frame']},{fr['time']:.6f},{fr['n_grids']},"
                        f"{fr['h_max']:.6f},{fr['speed_max']:.6f}\n")

            # Write gauge data
            for gid, gdata in gauge_data.items():
                f.write(f"\n# Gauge {gid}\n")
                n_q = gdata["q"].shape[1] if len(gdata["q"].shape) > 1 else 0
                header = "time_s"
                if n_q >= 1:
                    header += ",h_m"
                if n_q >= 2:
                    header += ",hu_m2s"
                if n_q >= 3:
                    header += ",hv_m2s"
                if n_q >= 4:
                    header += ",eta_m"
                f.write(header + "\n")

                for i in range(len(gdata["time"])):
                    row = f"{gdata['time'][i]:.6f}"
                    for j in range(min(n_q, 4)):
                        row += f",{gdata['q'][i, j]:.6f}"
                    f.write(row + "\n")

    elif fmt == "json":
        data = {
            "frames": frames,
            "gauges": {
                str(gid): {
                    "time": gdata["time"].tolist(),
                    "q": gdata["q"].tolist(),
                }
                for gid, gdata in gauge_data.items()
            },
        }
        with open(outfile, "w") as f:
            json.dump(data, f, indent=2)

    elif fmt == "numpy":
        # Save as .npz file
        arrays = {}
        for gid, gdata in gauge_data.items():
            arrays[f"gauge_{gid}_time"] = gdata["time"]
            arrays[f"gauge_{gid}_q"] = gdata["q"]
        arrays["frame_times"] = np.array([f["time"] for f in frames])
        arrays["frame_h_max"] = np.array([f["h_max"] for f in frames])
        np.savez(outfile, **arrays)


def validate_outputs(result, gauge_data):
    """Phase 3: Validate parsed results for physical consistency."""
    warnings = result.get("warnings", [])

    # Check frame count
    if result.get("n_frames", 0) == 0:
        warnings.append("CRITICAL: No frames were parsed")
    elif result.get("n_frames", 0) == 1:
        warnings.append("WARNING: Only 1 frame parsed — may only have initial condition")

    # Check for unrealistic values
    frames = result.get("frames", [])
    for fr in frames:
        if fr.get("h_max", 0) > 1000:
            warnings.append(
                f"WARNING: Frame {fr['frame']} has h_max={fr['h_max']:.1f}m "
                f"(>1000m is unrealistic for most applications)"
            )
        if fr.get("speed_max", 0) > 300:
            warnings.append(
                f"WARNING: Frame {fr['frame']} has speed_max={fr['speed_max']:.1f}m/s "
                f"(>300m/s suggests numerical instability)"
            )

    # Check gauges for NaN
    for gid, gdata in gauge_data.items():
        if np.any(np.isnan(gdata["q"])):
            warnings.append(f"CRITICAL: Gauge {gid} contains NaN values")
        if np.any(np.isinf(gdata["q"])):
            warnings.append(f"CRITICAL: Gauge {gid} contains Inf values")

    # Check if h_max decreases monotonically (might indicate dissipation)
    if len(frames) > 2:
        h_maxes = [f["h_max"] for f in frames]
        if all(h_maxes[i] >= h_maxes[i + 1] for i in range(len(h_maxes) - 1)):
            if h_maxes[-1] < 0.01 * h_maxes[0] and h_maxes[0] > 0:
                warnings.append(
                    "WARNING: h_max decreased by >99% — possible excessive dissipation "
                    "from high Manning coefficient or low-order scheme"
                )

    # Check output file was written
    if "outfile" in result:
        if not os.path.isfile(result["outfile"]):
            warnings.append(f"CRITICAL: Output file not created: {result['outfile']}")
        else:
            size = os.path.getsize(result["outfile"])
            result["outfile_size_bytes"] = size
            if size < 100:
                warnings.append(f"WARNING: Output file is very small ({size} bytes)")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse GeoClaw output files and extract results to CSV"
    )
    parser.add_argument("--output-dir", required=True,
                        help="GeoClaw _output directory")
    parser.add_argument("--outfile", default=None,
                        help="Output file path (CSV/JSON/NPZ)")
    parser.add_argument("--format", default="csv",
                        choices=["csv", "json", "numpy"],
                        help="Output format (default: csv)")
    parser.add_argument("--json-output", default=None,
                        help="Write result metadata JSON to this file")

    args = parser.parse_args()

    # Phase 1: Validate inputs
    input_warnings = validate_inputs(args)

    # Phase 2: Process
    result, gauge_data = process(args, input_warnings)

    # Phase 3: Validate outputs
    result = validate_outputs(result, gauge_data)

    # Remove large arrays from result for JSON serialization
    for fr in result.get("frames", []):
        fr.pop("grids", None)

    # Write JSON result
    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump(result, f, indent=2, default=str)
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
