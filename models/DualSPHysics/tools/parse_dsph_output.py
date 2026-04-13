#!/usr/bin/env python3
"""
parse_dsph_output.py — Parse DualSPHysics bi4 output and extract to CSV.

Reads DualSPHysics binary output (Part_XXXX.bi4) and extracts particle data
at specified measurement points into CSV time series. Also parses RUN.out
for simulation statistics.

Since bi4 is a proprietary binary format, this tool:
1. Uses MeasureTool binary for point interpolation (if available)
2. Parses PartVTK-generated VTK files as fallback
3. Parses RUN.out and CSV files from the simulation

Output CSV columns typically:
  Time, PosX, PosY, PosZ, VelX, VelY, VelZ, Rhop, Press

Usage:
    python parse_dsph_output.py --dirdata output/data --points points.txt \\
        --output results.csv --vars vel,press,rhop
    python parse_dsph_output.py --dirdata output/data --run_out output/RUN.out \\
        --output summary.csv --mode summary
"""

import argparse
import csv
import glob
import json
import os
import re
import struct
import sys


def validate_inputs(args):
    """Validate input paths and parameters."""
    errors = []
    warnings = []

    # Check data directory
    if args.dirdata and not os.path.isdir(args.dirdata):
        errors.append(f"Data directory not found: {args.dirdata}")

    # Check for bi4 files
    if args.dirdata and os.path.isdir(args.dirdata):
        bi4_files = glob.glob(os.path.join(args.dirdata, "Part_*.bi4"))
        if not bi4_files:
            errors.append(f"No Part_*.bi4 files in {args.dirdata}")
        else:
            if len(bi4_files) < 2:
                warnings.append("Only 1 output file — simulation may not "
                                "have completed.")

    # Check points file
    if args.points and not os.path.exists(args.points):
        errors.append(f"Points file not found: {args.points}")

    # Check output directory
    out_dir = os.path.dirname(args.output)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # Check bin_dir for MeasureTool
    if args.bin_dir:
        mt = os.path.join(args.bin_dir, "MeasureTool_linux64")
        if not os.path.exists(mt):
            warnings.append(f"MeasureTool not found at {mt}. "
                            "Will parse VTK/CSV fallback.")

    result = {"status": "error" if errors else "ok", "errors": errors,
              "warnings": warnings}
    if errors:
        print(json.dumps(result, indent=2), file=sys.stderr)
    return result


def parse_run_out(run_out_path):
    """Parse RUN.out for simulation summary statistics.

    Returns dict with simulation metadata and per-step statistics.
    """
    if not os.path.exists(run_out_path):
        return {"error": f"File not found: {run_out_path}"}

    with open(run_out_path) as f:
        content = f.read()

    info = {}

    # Version
    ver_match = re.search(r"DualSPHysics\d?\s+v([\d.]+)", content)
    if ver_match:
        info["version"] = ver_match.group(1)

    # Particle counts
    for label, key in [("Total particles", "total_particles"),
                       ("Boundary particles", "boundary_particles"),
                       ("Fluid particles", "fluid_particles"),
                       ("Fixed particles", "fixed_particles"),
                       ("Moving particles", "moving_particles"),
                       ("Floating particles", "floating_particles")]:
        m = re.search(rf"{label}:\s*(\d+)", content)
        if m:
            info[key] = int(m.group(1))

    # dp
    dp_match = re.search(r"Dp:\s*([\d.eE+-]+)", content)
    if dp_match:
        info["dp"] = float(dp_match.group(1))

    # Smoothing length
    h_match = re.search(r"[Hh]:\s*([\d.eE+-]+)", content)
    if h_match:
        info["h"] = float(h_match.group(1))

    # Time info
    tmax_match = re.search(r"TimeMax:\s*([\d.eE+-]+)", content)
    if tmax_match:
        info["time_max"] = float(tmax_match.group(1))

    # Parse PART output lines
    # Format: "Part_XXXX  Time:0.1200  dt:3.3e-05  Parts:125402  ..."
    part_pattern = re.compile(
        r"Part_(\d+)\s+Time:([\d.eE+-]+)\s+dt:([\d.eE+-]+)\s+"
        r"Parts:(\d+)")
    parts_data = []
    for m in part_pattern.finditer(content):
        parts_data.append({
            "part": int(m.group(1)),
            "time": float(m.group(2)),
            "dt": float(m.group(3)),
            "particles": int(m.group(4)),
        })
    info["parts"] = parts_data
    info["n_parts"] = len(parts_data)

    # Excluded particles
    excl_pattern = re.compile(r"Particles excluded:\s*(\d+)")
    excluded = [int(m.group(1)) for m in excl_pattern.finditer(content)]
    info["max_excluded"] = max(excluded) if excluded else 0

    # Final time
    if parts_data:
        info["final_time"] = parts_data[-1]["time"]
        info["final_dt"] = parts_data[-1]["dt"]

    return info


def run_measuretool(args, bin_dir):
    """Use MeasureTool to interpolate at measurement points."""
    import subprocess

    mt = os.path.join(bin_dir, "MeasureTool_linux64")

    # Build variable list
    vars_flag = "-vars:-all"
    if args.vars:
        for v in args.vars.split(","):
            vars_flag += f",+{v.strip()}"
    else:
        vars_flag += ",+vel,+press,+rhop"

    cmd = [
        mt,
        "-dirdata", args.dirdata,
        "-points", args.points,
        "-onlytype:-all,+fluid",
        vars_flag,
        "-savecsv", args.output.replace(".csv", ""),
    ]

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = env.get("LD_LIBRARY_PATH", "") + ":" + bin_dir

    print(f"Running MeasureTool: {' '.join(cmd)}")

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                          timeout=600)

    if proc.returncode != 0:
        return {"status": "error", "stderr": proc.stderr[:2000],
                "stdout": proc.stdout[:2000]}

    # Find generated CSV files
    csv_pattern = args.output.replace(".csv", "") + "*.csv"
    csv_files = glob.glob(csv_pattern)

    return {"status": "ok", "csv_files": csv_files,
            "stdout": proc.stdout[:1000]}


def parse_existing_csv(csv_path):
    """Parse an existing CSV output file from MeasureTool or simulation."""
    if not os.path.exists(csv_path):
        return {"error": f"CSV not found: {csv_path}"}

    rows = []
    with open(csv_path) as f:
        # DualSPHysics CSV uses semicolon or comma separator
        sample = f.readline()
        f.seek(0)
        sep = ";" if ";" in sample else ","
        reader = csv.DictReader(f, delimiter=sep)
        for row in reader:
            rows.append(row)

    return {
        "n_rows": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "data": rows,
    }


def extract_summary_csv(run_info, output_path):
    """Generate a summary CSV from RUN.out parsed data."""
    if "parts" not in run_info or not run_info["parts"]:
        return {"error": "No PART data found in RUN.out"}

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["part", "time", "dt",
                                                "particles"])
        writer.writeheader()
        for p in run_info["parts"]:
            writer.writerow(p)

    return {"status": "ok", "output": output_path,
            "n_rows": len(run_info["parts"])}


def validate_output(output_path):
    """Validate the generated output."""
    warnings = []

    if not os.path.exists(output_path):
        return ["Output file not created"]

    size = os.path.getsize(output_path)
    if size < 50:
        warnings.append(f"Output file very small ({size} bytes)")

    # Check CSV can be read
    try:
        with open(output_path) as f:
            reader = csv.reader(f)
            header = next(reader)
            n_rows = sum(1 for _ in reader)
        if n_rows == 0:
            warnings.append("CSV has header but no data rows")
    except Exception as e:
        warnings.append(f"CSV read error: {e}")

    return warnings


def process(args):
    """Main pipeline: validate -> extract -> validate output."""
    # 1. Validate inputs
    result = validate_inputs(args)
    if result["status"] == "error":
        return result

    all_warnings = result.get("warnings", [])

    # 2. Process based on mode
    if args.mode == "summary":
        # Parse RUN.out for summary
        run_out_path = args.run_out
        if not run_out_path:
            # Try to find RUN.out
            parent = os.path.dirname(args.dirdata)
            run_out_path = os.path.join(parent, "RUN.out")

        run_info = parse_run_out(run_out_path)
        if "error" in run_info:
            return {"status": "error", "errors": [run_info["error"]]}

        csv_result = extract_summary_csv(run_info, args.output)
        if "error" in csv_result:
            return {"status": "error", "errors": [csv_result["error"]]}

        return {
            "status": "ok",
            "mode": "summary",
            "output": args.output,
            "simulation_info": {
                k: v for k, v in run_info.items() if k != "parts"
            },
            "n_timesteps": run_info.get("n_parts", 0),
            "warnings": all_warnings,
        }

    elif args.mode == "points":
        # Use MeasureTool for point interpolation
        bin_dir = args.bin_dir
        if bin_dir and os.path.exists(
                os.path.join(bin_dir, "MeasureTool_linux64")):
            mt_result = run_measuretool(args, bin_dir)
            if mt_result["status"] == "ok":
                # Validate output
                out_warnings = validate_output(args.output)
                all_warnings.extend(out_warnings)
                return {
                    "status": "ok",
                    "mode": "points",
                    "csv_files": mt_result.get("csv_files", []),
                    "warnings": all_warnings,
                }
            else:
                all_warnings.append("MeasureTool failed, trying CSV fallback")

        # Fallback: parse existing CSV files
        csv_pattern = os.path.join(os.path.dirname(args.dirdata),
                                   "**", "*.csv")
        csv_files = glob.glob(csv_pattern, recursive=True)
        if csv_files:
            return {
                "status": "ok",
                "mode": "csv_fallback",
                "csv_files": csv_files,
                "warnings": all_warnings +
                            ["Using existing CSV files (no MeasureTool)"],
            }
        else:
            return {
                "status": "error",
                "errors": ["No MeasureTool and no existing CSV files found"],
            }

    else:
        # Parse existing CSV
        if os.path.exists(args.output):
            csv_data = parse_existing_csv(args.output)
            return {"status": "ok", "mode": "parse", "data": csv_data,
                    "warnings": all_warnings}
        else:
            return {"status": "error",
                    "errors": [f"File not found: {args.output}"]}


def main():
    parser = argparse.ArgumentParser(
        description="Parse DualSPHysics output")
    parser.add_argument("--dirdata", required=True,
                        help="Data directory with Part_*.bi4 files")
    parser.add_argument("--output", "-o", required=True,
                        help="Output CSV file path")
    parser.add_argument("--mode", default="summary",
                        choices=["summary", "points", "parse"],
                        help="Extraction mode")
    parser.add_argument("--points", help="Points file for interpolation")
    parser.add_argument("--vars", help="Variables to extract (comma-sep)")
    parser.add_argument("--bin_dir", help="Binary tools directory")
    parser.add_argument("--run_out", help="Path to RUN.out file")

    args = parser.parse_args()
    result = process(args)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
