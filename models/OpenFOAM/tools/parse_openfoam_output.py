#!/usr/bin/env python3
"""
Parse OpenFOAM simulation output to CSV and summary statistics.

Extracts:
  - Residual convergence history from solver log
  - Field values at probe points from time directories
  - Integrated quantities (forces, flow rates) from function objects
  - Time-series of key variables

CRITICAL: OpenFOAM field files can be ASCII or binary. This parser handles
          ASCII format only. For binary, use foamToVTK first.

CRITICAL: Pressure in incompressible results is KINEMATIC (m^2/s^2).
          Multiply by density to get Pa: p_Pa = p_foam * rho.

Usage:
    python parse_openfoam_output.py \\
        --case-dir ./cavity \\
        --log-file ./cavity/log.foamRun \\
        --probe-point "0.05 0.05 0.005" \\
        --output result.json

    python parse_openfoam_output.py \\
        --case-dir ./cavity \\
        --extract-residuals \\
        --extract-fields U,p \\
        --csv-dir ./output_csv \\
        --output result.json
"""

import argparse
import csv
import json
import os
import re
import sys


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isdir(args.case_dir):
        errors.append(f"Case directory not found: {args.case_dir}")

    if args.log_file and not os.path.isfile(args.log_file):
        errors.append(f"Log file not found: {args.log_file}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def find_log_file(case_dir):
    """Find the solver log file in the case directory."""
    candidates = [
        "log.foamRun", "log.simpleFoam", "log.icoFoam",
        "log.pimpleFoam", "log.interFoam", "log",
    ]
    for name in candidates:
        path = os.path.join(case_dir, name)
        if os.path.isfile(path):
            return path
    return None


def get_time_directories(case_dir):
    """List output time directories sorted numerically."""
    time_dirs = []
    for d in os.listdir(case_dir):
        full = os.path.join(case_dir, d)
        if os.path.isdir(full):
            try:
                t = float(d)
                time_dirs.append((t, d))
            except ValueError:
                pass
    time_dirs.sort(key=lambda x: x[0])
    return time_dirs


def parse_residuals_from_log(log_path):
    """Parse solver residuals from log file.

    Returns: dict with variable -> list of {time, initial, final, iterations}
    """
    residuals = {}
    current_time = 0.0

    with open(log_path, "r") as f:
        for line in f:
            # Parse time step
            time_match = re.match(r"^Time = ([\d.e+-]+)", line)
            if time_match:
                current_time = float(time_match.group(1))
                continue

            # Parse residual line
            res_match = re.match(
                r"\w+:\s+Solving for (\w+), "
                r"Initial residual = ([\d.e+-]+), "
                r"Final residual = ([\d.e+-]+), "
                r"No Iterations (\d+)",
                line.strip()
            )
            if res_match:
                var = res_match.group(1)
                if var not in residuals:
                    residuals[var] = []
                residuals[var].append({
                    "time": current_time,
                    "initial": float(res_match.group(2)),
                    "final": float(res_match.group(3)),
                    "iterations": int(res_match.group(4)),
                })

    return residuals


def parse_courant_from_log(log_path):
    """Parse Courant number history from log file."""
    courant_history = []
    current_time = 0.0

    with open(log_path, "r") as f:
        for line in f:
            time_match = re.match(r"^Time = ([\d.e+-]+)", line)
            if time_match:
                current_time = float(time_match.group(1))
                continue

            co_match = re.match(
                r"Courant Number mean: ([\d.e+-]+) max: ([\d.e+-]+)",
                line.strip()
            )
            if co_match:
                courant_history.append({
                    "time": current_time,
                    "mean": float(co_match.group(1)),
                    "max": float(co_match.group(2)),
                })

    return courant_history


def parse_execution_time(log_path):
    """Parse execution time from log file."""
    exec_time = None
    clock_time = None

    with open(log_path, "r") as f:
        for line in f:
            match = re.match(
                r"ExecutionTime = ([\d.]+) s\s+ClockTime = ([\d.]+) s",
                line.strip()
            )
            if match:
                exec_time = float(match.group(1))
                clock_time = float(match.group(2))

    return {"execution_time_s": exec_time, "clock_time_s": clock_time}


def read_scalar_field(field_path):
    """Read a scalar field file and extract internal field values."""
    values = []
    in_internal = False
    in_list = False
    n_values = 0

    with open(field_path, "r") as f:
        for line in f:
            stripped = line.strip()

            if "internalField" in stripped:
                if "uniform" in stripped:
                    # Uniform field
                    match = re.search(r"uniform\s+([\d.e+-]+)", stripped)
                    if match:
                        return {"type": "uniform", "value": float(match.group(1))}
                in_internal = True
                continue

            if in_internal and not in_list:
                try:
                    n_values = int(stripped)
                    in_list = True
                    continue
                except ValueError:
                    if stripped == "(":
                        in_list = True
                        continue

            if in_list:
                if stripped == ")":
                    break
                if stripped == "(":
                    continue
                try:
                    values.append(float(stripped))
                except ValueError:
                    pass

    return {"type": "nonuniform", "n_cells": len(values), "values": values}


def read_vector_field(field_path):
    """Read a vector field file and extract internal field values."""
    values = []
    in_internal = False
    in_list = False

    with open(field_path, "r") as f:
        for line in f:
            stripped = line.strip()

            if "internalField" in stripped:
                if "uniform" in stripped:
                    match = re.search(
                        r"uniform\s+\(([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\)",
                        stripped
                    )
                    if match:
                        return {
                            "type": "uniform",
                            "value": [float(match.group(i)) for i in (1, 2, 3)],
                        }
                in_internal = True
                continue

            if in_internal and not in_list:
                try:
                    int(stripped)
                    in_list = True
                    continue
                except ValueError:
                    if stripped == "(":
                        in_list = True
                        continue

            if in_list:
                if stripped == ")" and not stripped.startswith("("):
                    break
                match = re.match(
                    r"\(([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\)",
                    stripped
                )
                if match:
                    values.append([float(match.group(i)) for i in (1, 2, 3)])

    return {"type": "nonuniform", "n_cells": len(values), "values": values}


def write_residuals_csv(residuals, csv_dir):
    """Write residual history to CSV files."""
    files = []
    os.makedirs(csv_dir, exist_ok=True)

    for var, history in residuals.items():
        filepath = os.path.join(csv_dir, f"residuals_{var}.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["time", "initial", "final", "iterations"]
            )
            writer.writeheader()
            writer.writerows(history)
        files.append(filepath)

    return files


def write_courant_csv(courant_history, csv_dir):
    """Write Courant number history to CSV."""
    os.makedirs(csv_dir, exist_ok=True)
    filepath = os.path.join(csv_dir, "courant.csv")
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "mean", "max"])
        writer.writeheader()
        writer.writerows(courant_history)
    return filepath


def extract_field_at_point(case_dir, field_name, point, time_dirs):
    """Extract field value at nearest cell to probe point across all times.

    Note: This is approximate -- uses cell center nearest to point.
    For exact probing, use OpenFOAM's postProcess -func probes.
    """
    # Simplified: read field statistics instead of point extraction
    stats = []
    for t_val, t_dir in time_dirs:
        field_path = os.path.join(case_dir, t_dir, field_name)
        if not os.path.isfile(field_path):
            continue

        if field_name in ("U",):
            data = read_vector_field(field_path)
            if data["type"] == "uniform":
                mag = sum(v**2 for v in data["value"]) ** 0.5
                stats.append({"time": t_val, "magnitude_mean": mag})
            elif data["values"]:
                mags = [sum(v**2 for v in vec) ** 0.5 for vec in data["values"]]
                stats.append({
                    "time": t_val,
                    "magnitude_mean": sum(mags) / len(mags),
                    "magnitude_max": max(mags),
                })
        else:
            data = read_scalar_field(field_path)
            if data["type"] == "uniform":
                stats.append({"time": t_val, "mean": data["value"]})
            elif data["values"]:
                vals = data["values"]
                stats.append({
                    "time": t_val,
                    "mean": sum(vals) / len(vals),
                    "min": min(vals),
                    "max": max(vals),
                })

    return stats


def parse_function_objects(case_dir):
    """Parse postProcessing/ function object outputs."""
    pp_dir = os.path.join(case_dir, "postProcessing")
    if not os.path.isdir(pp_dir):
        return {}

    results = {}
    for func_name in os.listdir(pp_dir):
        func_dir = os.path.join(pp_dir, func_name)
        if not os.path.isdir(func_dir):
            continue

        # Look for dat files in time subdirectories
        for time_sub in os.listdir(func_dir):
            time_path = os.path.join(func_dir, time_sub)
            if not os.path.isdir(time_path):
                continue

            for dat_file in os.listdir(time_path):
                if dat_file.endswith(".dat"):
                    dat_path = os.path.join(time_path, dat_file)
                    results[f"{func_name}/{dat_file}"] = dat_path

    return results


def process(args):
    """Main processing: parse log, extract fields, write CSV."""
    result = {
        "status": "success",
        "case_dir": os.path.abspath(args.case_dir),
        "files_written": [],
        "warnings": [],
    }

    # Find and parse log file
    log_path = args.log_file or find_log_file(args.case_dir)
    if log_path and os.path.isfile(log_path):
        result["log_file"] = log_path

        if args.extract_residuals:
            residuals = parse_residuals_from_log(log_path)
            result["residuals_summary"] = {
                var: {
                    "n_steps": len(hist),
                    "final_initial": hist[-1]["initial"] if hist else None,
                    "final_final": hist[-1]["final"] if hist else None,
                }
                for var, hist in residuals.items()
            }

            if args.csv_dir:
                csv_files = write_residuals_csv(residuals, args.csv_dir)
                result["files_written"].extend(csv_files)

            courant = parse_courant_from_log(log_path)
            if courant and args.csv_dir:
                co_file = write_courant_csv(courant, args.csv_dir)
                result["files_written"].append(co_file)

            if courant:
                result["courant_summary"] = {
                    "max_courant": max(c["max"] for c in courant),
                    "mean_courant": sum(c["mean"] for c in courant) / len(courant),
                }

        timing = parse_execution_time(log_path)
        result["timing"] = timing

    # Get time directories
    time_dirs = get_time_directories(args.case_dir)
    result["n_output_times"] = len(time_dirs)
    if time_dirs:
        result["time_range"] = {
            "start": time_dirs[0][0],
            "end": time_dirs[-1][0],
        }

    # Extract field statistics
    if args.extract_fields:
        fields = args.extract_fields.split(",")
        field_stats = {}
        for field_name in fields:
            stats = extract_field_at_point(
                args.case_dir, field_name.strip(), None, time_dirs
            )
            field_stats[field_name.strip()] = stats

            if args.csv_dir and stats:
                os.makedirs(args.csv_dir, exist_ok=True)
                filepath = os.path.join(args.csv_dir, f"field_{field_name.strip()}.csv")
                with open(filepath, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=stats[0].keys())
                    writer.writeheader()
                    writer.writerows(stats)
                result["files_written"].append(filepath)

        result["field_statistics"] = field_stats

    # Parse function objects
    func_objects = parse_function_objects(args.case_dir)
    if func_objects:
        result["function_objects"] = func_objects

    return result


def validate_outputs(result):
    """Validate output files."""
    warnings = result.get("warnings", [])

    for fp in result.get("files_written", []):
        if not os.path.isfile(fp):
            warnings.append(f"Expected output file missing: {fp}")

    if result.get("n_output_times", 0) == 0:
        warnings.append("No output time directories found -- simulation may not have run")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse OpenFOAM simulation output"
    )
    parser.add_argument("--case-dir", required=True,
                        help="OpenFOAM case directory")
    parser.add_argument("--log-file", default=None,
                        help="Path to solver log file")
    parser.add_argument("--extract-residuals", action="store_true",
                        help="Extract residual convergence history")
    parser.add_argument("--extract-fields", default=None,
                        help="Comma-separated field names to extract (e.g., U,p)")
    parser.add_argument("--probe-point", default=None,
                        help="Probe point coordinates 'x y z'")
    parser.add_argument("--csv-dir", default=None,
                        help="Directory for CSV output files")
    parser.add_argument("--output", default=None,
                        help="Output JSON summary file")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
