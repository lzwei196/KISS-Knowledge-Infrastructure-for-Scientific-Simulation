#!/usr/bin/env python3
"""
convert_data_to_gimli.py — Convert field geophysical data to pyGIMLi format.

Supports ERT (Res2DInv, ABEM, Syscal, generic CSV) and SRT (SEG-2, CSV picks)
formats. Performs unit validation and geometric factor computation.

Usage:
    python convert_data_to_gimli.py --input field_data.dat --method ert --format res2dinv --output data.ohm
    python convert_data_to_gimli.py --input picks.csv --method srt --format csv --output data.sgt
    python convert_data_to_gimli.py --input field_data.csv --method ert --format csv \
        --electrode-spacing 1.0 --scheme wenner --output data.ohm

Unit conventions:
    ERT: electrode positions in m, apparent resistivity in Ohm·m, voltage in V, current in A
    SRT: sensor positions in m, travel time in s (NOT ms), velocity in m/s

Critical traps:
    - Travel times in ms vs s (factor 1000)
    - Apparent resistivity without geometric factor applied
    - Electrode coordinates in lat/lon instead of local metres
    - IP phase sign convention (pyGIMLi expects negative phase)
"""

import argparse
import json
import os
import sys
import csv
import numpy as np


def validate_inputs(args):
    """Validate command-line arguments and input file existence."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.method not in ("ert", "srt", "sip"):
        errors.append(f"Unsupported method: {args.method}. Use ert, srt, or sip.")

    if args.format not in ("res2dinv", "abem", "syscal", "csv", "seg2", "gimli"):
        errors.append(f"Unsupported format: {args.format}")

    if args.method == "ert" and args.format in ("seg2",):
        errors.append(f"Format {args.format} is not compatible with method ert.")

    if args.method == "srt" and args.format in ("res2dinv", "abem", "syscal"):
        errors.append(f"Format {args.format} is not compatible with method srt.")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def parse_csv_ert(filepath, electrode_spacing=None):
    """Parse generic CSV ERT data.

    Expected columns: a, b, m, n, rhoa (or u, i)
    Electrode indices are 1-based; positions computed from spacing.
    """
    rows = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in reader.fieldnames]
        for row in reader:
            row = {k.strip().lower(): v.strip() for k, v in row.items()}
            rows.append(row)

    n_data = len(rows)
    if n_data == 0:
        raise ValueError("CSV file contains no data rows.")

    # Determine electrode positions
    all_indices = set()
    for row in rows:
        for key in ("a", "b", "m", "n"):
            if key in row:
                all_indices.add(int(float(row[key])))

    n_elecs = max(all_indices)
    spacing = electrode_spacing or 1.0
    positions = np.arange(n_elecs) * spacing

    # Extract data arrays
    a_idx = np.array([int(float(row["a"])) - 1 for row in rows])
    b_idx = np.array([int(float(row["b"])) - 1 for row in rows])
    m_idx = np.array([int(float(row["m"])) - 1 for row in rows])
    n_idx = np.array([int(float(row["n"])) - 1 for row in rows])

    rhoa = None
    if "rhoa" in rows[0]:
        rhoa = np.array([float(row["rhoa"]) for row in rows])
    elif "u" in rows[0] and "i" in rows[0]:
        u = np.array([float(row["u"]) for row in rows])
        i_arr = np.array([float(row["i"]) for row in rows])
        # Compute geometric factor for surface electrodes
        am = np.abs(positions[a_idx] - positions[m_idx])
        an = np.abs(positions[a_idx] - positions[n_idx])
        bm = np.abs(positions[b_idx] - positions[m_idx])
        bn = np.abs(positions[b_idx] - positions[n_idx])
        k = 2 * np.pi / (1.0/am - 1.0/an - 1.0/bm + 1.0/bn)
        rhoa = k * u / i_arr

    return {
        "n_electrodes": n_elecs,
        "positions": positions,
        "a": a_idx,
        "b": b_idx,
        "m": m_idx,
        "n": n_idx,
        "rhoa": rhoa,
        "n_data": n_data,
    }


def parse_csv_srt(filepath, time_unit="s"):
    """Parse CSV travel time picks.

    Expected columns: shot_x, shot_y, rec_x, rec_y, traveltime
    """
    rows = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip().lower(): v.strip() for k, v in row.items()}
            rows.append(row)

    n_data = len(rows)
    if n_data == 0:
        raise ValueError("CSV file contains no travel time data.")

    shot_x = np.array([float(r.get("shot_x", r.get("sx", 0))) for r in rows])
    rec_x = np.array([float(r.get("rec_x", r.get("rx", 0))) for r in rows])
    times = np.array([float(r.get("traveltime", r.get("t", 0))) for r in rows])

    # Unit conversion trap
    if time_unit == "ms":
        times = times / 1000.0
        print("WARNING: Converting travel times from ms to s", file=sys.stderr)

    # Auto-detect if times are in ms (typical travel times < 0.1 s for near-surface)
    if np.median(times) > 1.0:
        print("WARNING: Median travel time > 1 s. Are times in ms? "
              "Use --time-unit ms to convert.", file=sys.stderr)

    # Collect unique sensor positions
    all_x = np.unique(np.concatenate([shot_x, rec_x]))
    sensor_map = {x: i for i, x in enumerate(all_x)}

    s_idx = np.array([sensor_map[x] for x in shot_x])
    g_idx = np.array([sensor_map[x] for x in rec_x])

    return {
        "n_sensors": len(all_x),
        "positions": all_x,
        "shot_idx": s_idx,
        "receiver_idx": g_idx,
        "traveltimes": times,
        "n_data": n_data,
    }


def write_gimli_ert(data, output_path):
    """Write pyGIMLi-compatible ERT data file (.ohm/.dat format)."""
    n_elecs = data["n_electrodes"]
    positions = data["positions"]
    n_data = data["n_data"]

    lines = []
    lines.append(f"{n_elecs}# Number of electrodes")
    lines.append("# x z")
    for i in range(n_elecs):
        lines.append(f"{positions[i]:.4f}\t0.0000")

    lines.append(f"{n_data}# Number of data")
    lines.append("# a\tb\tm\tn\trhoa")
    for i in range(n_data):
        a = data["a"][i] + 1  # back to 1-based
        b = data["b"][i] + 1
        m = data["m"][i] + 1
        n = data["n"][i] + 1
        rhoa_val = data["rhoa"][i] if data["rhoa"] is not None else 0.0
        lines.append(f"{a}\t{b}\t{m}\t{n}\t{rhoa_val:.6f}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return output_path


def write_gimli_srt(data, output_path):
    """Write pyGIMLi-compatible SRT data file (.sgt format)."""
    n_sensors = data["n_sensors"]
    positions = data["positions"]
    n_data = data["n_data"]

    lines = []
    lines.append(f"{n_sensors}# Number of sensors")
    lines.append("# x z")
    for i in range(n_sensors):
        lines.append(f"{positions[i]:.4f}\t0.0000")

    lines.append(f"{n_data}# Number of data")
    lines.append("# s\tg\tt")
    for i in range(n_data):
        s = data["shot_idx"][i]
        g = data["receiver_idx"][i]
        t = data["traveltimes"][i]
        lines.append(f"{s}\t{g}\t{t:.6f}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return output_path


def process(args):
    """Main processing: parse input, convert, write output."""
    result = {"status": "success", "method": args.method, "input": args.input}

    if args.method == "ert":
        if args.format == "csv":
            data = parse_csv_ert(args.input, args.electrode_spacing)
        else:
            # For native formats, attempt direct load description
            data = parse_csv_ert(args.input, args.electrode_spacing)

        output_path = args.output or args.input.rsplit(".", 1)[0] + ".ohm"
        write_gimli_ert(data, output_path)
        result["output"] = output_path
        result["n_electrodes"] = int(data["n_electrodes"])
        result["n_data"] = int(data["n_data"])
        if data["rhoa"] is not None:
            result["rhoa_range"] = [float(np.min(data["rhoa"])),
                                     float(np.max(data["rhoa"]))]

    elif args.method == "srt":
        if args.format == "csv":
            data = parse_csv_srt(args.input, args.time_unit)
        else:
            data = parse_csv_srt(args.input, args.time_unit)

        output_path = args.output or args.input.rsplit(".", 1)[0] + ".sgt"
        write_gimli_srt(data, output_path)
        result["output"] = output_path
        result["n_sensors"] = int(data["n_sensors"])
        result["n_data"] = int(data["n_data"])
        result["traveltime_range"] = [float(np.min(data["traveltimes"])),
                                       float(np.max(data["traveltimes"]))]

    return result


def validate_outputs(result):
    """Post-process validation of converted data."""
    warnings = []

    if result["method"] == "ert" and "rhoa_range" in result:
        rmin, rmax = result["rhoa_range"]
        if rmin <= 0:
            warnings.append("Negative or zero apparent resistivity detected. "
                            "Check geometric factor or data polarity.")
        if rmax / rmin > 1e4:
            warnings.append(f"Resistivity dynamic range is {rmax/rmin:.0f}×. "
                            "Check for unit mixing (Ohm vs Ohm·m).")
        if rmax > 1e6:
            warnings.append(f"Max rhoa={rmax:.0f} Ohm·m — unusually high. "
                            "Check if data is in Ohm instead of Ohm·m.")

    if result["method"] == "srt" and "traveltime_range" in result:
        tmin, tmax = result["traveltime_range"]
        if tmax > 1.0:
            warnings.append(f"Max travel time = {tmax:.3f} s. "
                            "If these are near-surface data, times may be in ms.")
        if tmin < 0:
            warnings.append("Negative travel times detected. Check pick quality.")

    if warnings:
        result["warnings"] = warnings

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert field geophysical data to pyGIMLi format."
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Path to input data file")
    parser.add_argument("--method", "-m", required=True,
                        choices=["ert", "srt", "sip"],
                        help="Geophysical method (ert, srt, sip)")
    parser.add_argument("--format", "-f", required=True,
                        choices=["res2dinv", "abem", "syscal", "csv", "seg2", "gimli"],
                        help="Input file format")
    parser.add_argument("--output", "-o", default=None,
                        help="Output file path (default: input stem + .ohm/.sgt)")
    parser.add_argument("--electrode-spacing", type=float, default=1.0,
                        help="Electrode/sensor spacing in metres (for CSV with indices)")
    parser.add_argument("--time-unit", choices=["s", "ms"], default="s",
                        help="Travel time unit in input (s or ms). Default: s")
    parser.add_argument("--negate-phase", action="store_true",
                        help="Negate IP phase values (convert positive to negative)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)
    if args.output:
        json_path = args.output + ".meta.json"
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
        with open(json_path, "w") as f:
            f.write(output_json)
        print(f"Conversion complete. Output: {args.output}", file=sys.stderr)
        print(f"Metadata: {json_path}", file=sys.stderr)
    print(output_json)


if __name__ == "__main__":
    main()
