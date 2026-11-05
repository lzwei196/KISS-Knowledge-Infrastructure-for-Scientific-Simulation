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

    # Check gauge files (Clawpack 5.x: gaugeNNNNN.txt; older: fort.gauge)
    gauge_file = os.path.join(args.output_dir, "fort.gauge")
    if not os.path.isfile(gauge_file) and not _gauge_txt_files(args.output_dir):
        warnings.append("No gaugeNNNNN.txt or fort.gauge file — no gauge data available")
    if _gauge_bin_files(args.output_dir):
        warnings.append("Binary gauge files (gauge*.bin) are not parsed by this tool")

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
    if len(lines) >= 7 and lines[6].split():  # Clawpack 5.x: "ascii   format" / "binary..."
        meta["format"] = lines[6].split()[0]
    return meta


_GRID_HEADER_NAMES = {"grid_number", "AMR_level", "mx", "my", "mz",
                      "xlow", "ylow", "zlow", "dx", "dy", "dz"}


def _parse_fort_q(filepath, meqn=None, ndim=2):
    """Parse a fort.qNNNN file (ASCII) and return the solution for all AMR grids.

    Each grid is a header of "value name" lines (grid_number, AMR_level, mx, my, xlow,
    ylow, dx, dy) followed by mx*my cell records, one cell per line; Clawpack 5.x puts a
    blank line after every row of cells. Every record has the same number of columns
    (GeoClaw 5.x: h, hu, hv, eta), which must equal meqn from fort.t when it is given.
    Raises ValueError on a truncated or malformed grid.
    """
    with open(filepath, "r") as f:
        lines = [l.split() for l in f]

    grids = []
    i, n = 0, len(lines)
    while i < n:
        if not lines[i]:
            i += 1
            continue
        header = {}
        while i < n and len(lines[i]) == 2 and lines[i][1] in _GRID_HEADER_NAMES:
            value, name = lines[i]
            header[name] = int(value) if name in ("grid_number", "AMR_level", "mx", "my", "mz") \
                else float(value)
            i += 1
        missing = [k for k in ("grid_number", "AMR_level", "mx", "my", "xlow", "ylow", "dx")
                   if k not in header]
        if missing:
            raise ValueError(f"{filepath}: line {i + 1}: expected a grid header, missing {missing}")
        header.setdefault("dy", header["dx"])
        mx, my = header["mx"], header["my"]
        ncell = mx * my * header.get("mz", 1)

        values = []
        ncol = None
        while len(values) < ncell and i < n:
            if lines[i]:
                if ncol is None:
                    ncol = len(lines[i])
                    if meqn is not None and ncol != meqn:
                        raise ValueError(f"{filepath}: line {i + 1}: {ncol} values per cell, "
                                         f"fort.t declares meqn = {meqn}")
                elif len(lines[i]) != ncol:
                    raise ValueError(f"{filepath}: line {i + 1}: {len(lines[i])} values, "
                                     f"expected {ncol} (grid {header['grid_number']})")
                values.append([float(v) for v in lines[i]])
            i += 1
        if len(values) < ncell:
            raise ValueError(f"{filepath}: grid {header['grid_number']} is truncated: "
                             f"{len(values)} of {ncell} cells")

        q = np.array(values).reshape(my, mx, ncol) if "mz" not in header else np.array(values)
        header["ncol"] = ncol
        header["q"] = q

        # Compute derived quantities
        h = q[..., 0]
        hu = q[..., 1]
        hv = q[..., 2] if ncol > 2 else np.zeros_like(h)

        # Compute velocity (avoid division by zero in dry cells)
        dry = h < 1e-6
        with np.errstate(divide="ignore", invalid="ignore"):
            u = np.where(dry, 0.0, hu / h)
            v = np.where(dry, 0.0, hv / h)
        speed = np.sqrt(u**2 + v**2)

        header["h_max"] = float(np.max(h))
        header["h_mean"] = float(np.mean(h[~dry])) if np.any(~dry) else 0.0
        header["speed_max"] = float(np.max(speed))

        grids.append(header)

    return grids


def _gauge_txt_files(outdir):
    """Clawpack 5.x ASCII gauge files gaugeNNNNN.txt (not gauges.data)."""
    return sorted(f for f in glob.glob(os.path.join(outdir, "gauge*.txt"))
                  if re.fullmatch(r"gauge\d+\.txt", os.path.basename(f)))


def _gauge_bin_files(outdir):
    return sorted(f for f in glob.glob(os.path.join(outdir, "gauge*.bin*"))
                  if re.fullmatch(r"gauge\d+\.bin\w*", os.path.basename(f)))


def _parse_gauge_txt(filepath):
    """Parse one Clawpack 5.x gaugeNNNNN.txt file.

    Header lines start with '#': '# gauge_id= 1 location=( x y ) num_var= 4'.
    Data columns: level, time, then num_var values (GeoClaw: h, hu, hv, eta), then aux.
    Returns (gauge_id, {"time", "level", "q"}), or (gauge_id, None) for the header of a
    binary gauge ('# file format binary..., time series in .bin file').
    """
    gauge_id, num_var, binary = None, None, False
    times, levels, qs = [], [], []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if re.search(r"file format\s+binary", line):
                    binary = True
                m = re.search(r"gauge_id=\s*(\d+)", line)
                if m:
                    gauge_id = int(m.group(1))
                m = re.search(r"num_var=\s*(\d+)", line)
                if m:
                    num_var = int(m.group(1))
                continue
            parts = line.split()
            nq = num_var if num_var is not None else len(parts) - 2
            if len(parts) < 2 + nq:
                raise ValueError(f"{filepath}: short gauge record: {line[:80]}")
            levels.append(int(float(parts[0])))
            times.append(float(parts[1]))
            qs.append([float(v) for v in parts[2:2 + nq]])
    if gauge_id is None:
        m = re.search(r"gauge(\d+)\.txt$", os.path.basename(filepath))
        gauge_id = int(m.group(1))
    if binary:
        return gauge_id, None
    return gauge_id, {"time": np.array(times), "level": levels, "q": np.array(qs)}


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

    # Parse all frames (fort.tNNNN paired with fort.qNNNN by frame number)
    def _frame_numbers(prefix):
        return {os.path.basename(f)[len(prefix):]
                for f in glob.glob(os.path.join(outdir, prefix + "*"))
                if re.fullmatch(re.escape(prefix) + r"\d+", os.path.basename(f))}
    t_nums, q_nums = _frame_numbers("fort.t"), _frame_numbers("fort.q")
    if t_nums != q_nums:
        raise ValueError("fort.t / fort.q frames do not pair up: only fort.t for "
                         f"{sorted(t_nums - q_nums)}, only fort.q for {sorted(q_nums - t_nums)}")

    frames = []
    for num in sorted(t_nums, key=int):
        tf = os.path.join(outdir, "fort.t" + num)
        qf = os.path.join(outdir, "fort.q" + num)
        meta = _parse_fort_t(tf)
        if not all(k in meta for k in ("time", "meqn", "ngrids")):
            raise ValueError(f"{tf}: incomplete frame header (time/meqn/ngrids missing)")
        if meta.get("format", "ascii") != "ascii":
            raise ValueError(f"{tf}: output format '{meta['format']}' is not supported "
                             "(only ASCII fort.q is read)")
        grids = _parse_fort_q(qf, meqn=meta["meqn"])
        if "ngrids" in meta and len(grids) != meta["ngrids"]:
            raise ValueError(f"{qf}: {len(grids)} grids read, {tf} declares {meta['ngrids']}")

        frame = {
            "frame": int(num),
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

    # Parse gauges: Clawpack 5.x gaugeNNNNN.txt, else the old fort.gauge
    gauge_data = {}
    gauge_txt = _gauge_txt_files(outdir)
    gauge_file = os.path.join(outdir, "fort.gauge")
    if gauge_txt:
        for gf in gauge_txt:
            gid, gdata = _parse_gauge_txt(gf)
            if gdata is None:  # header of a binary gauge: data are in the .bin file
                result["warnings"].append(f"gauge {gid}: binary time series ({gf} is only the "
                                          "header), not parsed")
                continue
            if gid in gauge_data:
                raise ValueError(f"gauge id {gid} appears in more than one file ({gf})")
            gauge_data[gid] = gdata
    elif os.path.isfile(gauge_file):
        gauge_data = _parse_gauge_file(gauge_file)
    if gauge_data:
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
    try:
        result, gauge_data = process(args, input_warnings)
    except (ValueError, OSError, IndexError) as e:
        result = {"status": "error", "output_dir": args.output_dir,
                  "errors": [f"{type(e).__name__}: {e}"], "warnings": input_warnings}
        text = json.dumps(result, indent=2, default=str)
        if args.json_output:
            with open(args.json_output, "w") as f:
                f.write(text)
        print(text)
        sys.exit(1)

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
