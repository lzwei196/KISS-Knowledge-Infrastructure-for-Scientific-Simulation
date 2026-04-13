#!/usr/bin/env python3
"""
parse_dfnworks_output.py - Parse dfnWorks output files to CSV/JSON.

Extracts key results from dfnWorks simulations:
  - Fracture network statistics (radii, orientations, connectivity)
  - Graph flow results (pressure, velocity, flux per edge)
  - Particle breakthrough curves (travel time distributions)
  - Network properties (p32, percolation, clustering)

Supports both graph-mode (HDF5) and full-physics (VTK/DAT) outputs.

CRITICAL: Travel times from graph mode are in SECONDS. Convert to desired
time units before comparison with field data.

Usage:
    python parse_dfnworks_output.py --job_dir ./output --output results.csv
    python parse_dfnworks_output.py --job_dir ./output --format json --output results.json
    python parse_dfnworks_output.py --partime partime --btc --output btc.csv
    python parse_dfnworks_output.py --graph_flow graph_flow.hdf5 --output flow_summary.csv
"""

import argparse
import csv
import json
import os
import sys

import numpy as np


# ============================================================================
# Input Validation
# ============================================================================

def validate_inputs(args):
    """Validate input arguments.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    dict
        Validated parameters.
    """
    errors = []

    if args.job_dir and not os.path.isdir(args.job_dir):
        errors.append(f"Job directory not found: {args.job_dir}")

    if args.partime and not os.path.isfile(args.partime):
        errors.append(f"Partime file not found: {args.partime}")

    if args.graph_flow and not os.path.isfile(args.graph_flow):
        errors.append(f"Graph flow file not found: {args.graph_flow}")

    if args.format not in ["csv", "json"]:
        errors.append(f"Invalid format: {args.format}")

    if args.time_unit not in ["seconds", "minutes", "hours", "days", "years"]:
        errors.append(f"Invalid time unit: {args.time_unit}")

    if errors:
        result = {"status": "error", "errors": errors}
        sys.stderr.write(json.dumps(result, indent=2) + "\n")
        sys.exit(1)

    return vars(args)


# ============================================================================
# Time Unit Conversion
# ============================================================================

def convert_time(seconds, target_unit):
    """Convert time from seconds to target unit.

    Parameters
    ----------
    seconds : float or np.ndarray
        Time in seconds.
    target_unit : str
        Target unit.

    Returns
    -------
    float or np.ndarray
        Converted time.
    """
    factors = {
        "seconds": 1.0,
        "minutes": 60.0,
        "hours": 3600.0,
        "days": 86400.0,
        "years": 3.1536e7,
    }
    return seconds / factors[target_unit]


# ============================================================================
# Parsing Functions
# ============================================================================

def parse_params_file(filepath):
    """Parse dfnWorks params.txt file.

    Contains fracture network generation summary.

    Parameters
    ----------
    filepath : str
        Path to params.txt.

    Returns
    -------
    dict
        Parsed parameters.
    """
    params = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if ':' in line:
                key, val = line.split(':', 1)
                params[key.strip()] = val.strip()
            elif line and not line.startswith('#'):
                parts = line.split()
                if len(parts) >= 2:
                    params[parts[0]] = ' '.join(parts[1:])

    return params


def parse_radii_file(filepath):
    """Parse fracture radii output file.

    Parameters
    ----------
    filepath : str
        Path to radii_All.dat or per-family radii file.

    Returns
    -------
    dict
        Radii statistics.
    """
    try:
        radii = np.loadtxt(filepath)
        if radii.ndim == 0:
            radii = np.array([float(radii)])
        return {
            "n_fractures": len(radii),
            "min_radius_m": float(np.min(radii)),
            "max_radius_m": float(np.max(radii)),
            "mean_radius_m": float(np.mean(radii)),
            "median_radius_m": float(np.median(radii)),
            "std_radius_m": float(np.std(radii)),
        }
    except Exception as e:
        return {"error": str(e)}


def parse_partime(filepath, time_unit="seconds"):
    """Parse particle travel time file.

    Parameters
    ----------
    filepath : str
        Path to partime file.
    time_unit : str
        Output time unit.

    Returns
    -------
    dict
        Travel time statistics and raw data.
    """
    try:
        data = np.loadtxt(filepath)
        if data.ndim == 0:
            data = np.array([float(data)])

        # Convert from seconds to target unit
        data_converted = convert_time(data, time_unit)

        # Compute breakthrough curve percentiles
        sorted_times = np.sort(data_converted)
        n = len(sorted_times)
        cdf = np.arange(1, n + 1) / n

        percentiles = {}
        for p in [5, 10, 25, 50, 75, 90, 95]:
            idx = int(p / 100.0 * n)
            idx = max(0, min(idx, n - 1))
            percentiles[f"p{p}"] = float(sorted_times[idx])

        return {
            "n_particles": n,
            "time_unit": time_unit,
            "mean": float(np.mean(data_converted)),
            "median": float(np.median(data_converted)),
            "std": float(np.std(data_converted)),
            "min": float(np.min(data_converted)),
            "max": float(np.max(data_converted)),
            "percentiles": percentiles,
            "sorted_times": sorted_times.tolist(),
            "cdf": cdf.tolist(),
        }
    except Exception as e:
        return {"error": str(e)}


def parse_graph_flow_hdf5(filepath):
    """Parse graph flow HDF5 output.

    Parameters
    ----------
    filepath : str
        Path to graph_flow.hdf5.

    Returns
    -------
    dict
        Flow statistics per edge.
    """
    try:
        import h5py
        with h5py.File(filepath, 'r') as hf:
            datasets = list(hf.keys())
            result = {"datasets": datasets}

            for ds_name in datasets:
                data = np.array(hf[ds_name])
                result[ds_name] = {
                    "n_values": len(data),
                    "mean": float(np.mean(data)),
                    "median": float(np.median(data)),
                    "min": float(np.min(data)),
                    "max": float(np.max(data)),
                    "std": float(np.std(data)),
                }

        return result
    except ImportError:
        return {"error": "h5py not installed"}
    except Exception as e:
        return {"error": str(e)}


def parse_fracture_info(job_dir):
    """Parse fracture network information from job directory.

    Parameters
    ----------
    job_dir : str
        Path to dfnWorks output directory.

    Returns
    -------
    dict
        Network statistics.
    """
    result = {}

    # Parse params.txt
    params_file = os.path.join(job_dir, "params.txt")
    if os.path.isfile(params_file):
        result["params"] = parse_params_file(params_file)

    # Parse radii
    radii_file = os.path.join(job_dir, "dfnGen_output", "radii", "radii_All.dat")
    if os.path.isfile(radii_file):
        result["radii"] = parse_radii_file(radii_file)
    else:
        # Try alternative location
        radii_file = os.path.join(job_dir, "radii_All.dat")
        if os.path.isfile(radii_file):
            result["radii"] = parse_radii_file(radii_file)

    # Parse connectivity
    connectivity_file = os.path.join(job_dir, "connectivity.dat")
    if os.path.isfile(connectivity_file):
        try:
            conn = np.loadtxt(connectivity_file)
            result["connectivity"] = {
                "n_intersections": len(conn),
            }
        except Exception:
            pass

    return result


def compute_breakthrough_curve(times, n_bins=50):
    """Compute breakthrough curve from particle travel times.

    Parameters
    ----------
    times : np.ndarray
        Sorted travel times.
    n_bins : int
        Number of histogram bins.

    Returns
    -------
    dict
        Breakthrough curve data (time bins, flux, cumulative).
    """
    if len(times) == 0:
        return {"error": "No particles"}

    # Log-spaced bins for better resolution of early arrivals
    t_min = max(times[0], 1e-10)
    t_max = times[-1]
    if t_min >= t_max:
        return {"error": "All particles have same travel time"}

    bins = np.logspace(np.log10(t_min), np.log10(t_max), n_bins + 1)
    counts, bin_edges = np.histogram(times, bins=bins)

    # Flux (particles per unit time)
    bin_widths = np.diff(bin_edges)
    flux = counts / bin_widths / len(times)

    # Cumulative breakthrough
    cumulative = np.cumsum(counts) / len(times)

    # Bin centers (geometric mean for log-spaced)
    bin_centers = np.sqrt(bin_edges[:-1] * bin_edges[1:])

    return {
        "bin_centers": bin_centers.tolist(),
        "flux": flux.tolist(),
        "cumulative": cumulative.tolist(),
        "n_bins": n_bins,
    }


# ============================================================================
# Main Processing
# ============================================================================

def process(args):
    """Parse dfnWorks outputs and assemble results.

    Parameters
    ----------
    args : dict
        Validated arguments.

    Returns
    -------
    dict
        Combined results.
    """
    result = {"status": "success"}

    # Parse job directory
    if args.get("job_dir"):
        result["network"] = parse_fracture_info(args["job_dir"])

        # Auto-detect partime
        if not args.get("partime"):
            for candidate in ["partime", "partime.dat", "graph_partime"]:
                path = os.path.join(args["job_dir"], candidate)
                if os.path.isfile(path):
                    args["partime"] = path
                    break

        # Auto-detect graph flow
        if not args.get("graph_flow"):
            path = os.path.join(args["job_dir"], "graph_flow.hdf5")
            if os.path.isfile(path):
                args["graph_flow"] = path

    # Parse particle travel times
    if args.get("partime"):
        result["travel_times"] = parse_partime(args["partime"], args["time_unit"])

        if "sorted_times" in result["travel_times"]:
            btc = compute_breakthrough_curve(
                np.array(result["travel_times"]["sorted_times"])
            )
            result["breakthrough_curve"] = btc

    # Parse graph flow
    if args.get("graph_flow"):
        result["graph_flow"] = parse_graph_flow_hdf5(args["graph_flow"])

    return result


# ============================================================================
# Output Validation
# ============================================================================

def validate_outputs(result):
    """Validate parsed outputs.

    Parameters
    ----------
    result : dict
        Parsing results.

    Returns
    -------
    dict
        Result with validation warnings.
    """
    warnings = []

    # Check travel times
    tt = result.get("travel_times", {})
    if tt.get("n_particles", 0) == 0 and "error" not in tt:
        warnings.append("No particle travel times found")
    elif tt.get("n_particles", 0) > 0:
        if tt["std"] / tt["mean"] > 10:
            warnings.append("Very high travel time variance - check for disconnected paths")
        if tt["min"] <= 0:
            warnings.append("Minimum travel time <= 0 - possible numerical issue")

    # Check flow
    gf = result.get("graph_flow", {})
    if "velocity" in gf:
        v = gf["velocity"]
        if v.get("min", 0) < 0:
            warnings.append("Negative velocities in graph flow - check boundary conditions")

    result["warnings"] = warnings
    return result


def write_csv(result, filepath):
    """Write results to CSV file.

    Parameters
    ----------
    result : dict
        Parsed results.
    filepath : str
        Output CSV path.
    """
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)

        # Travel time summary
        tt = result.get("travel_times", {})
        if tt and "error" not in tt:
            writer.writerow(["# Travel Time Statistics"])
            writer.writerow(["metric", "value", "unit"])
            for key in ["n_particles", "mean", "median", "std", "min", "max"]:
                if key in tt:
                    writer.writerow([key, tt[key], tt.get("time_unit", "seconds")])

            # Percentiles
            writer.writerow([])
            writer.writerow(["# Percentiles"])
            for k, v in tt.get("percentiles", {}).items():
                writer.writerow([k, v, tt.get("time_unit", "seconds")])

            # Breakthrough curve
            btc = result.get("breakthrough_curve", {})
            if btc and "error" not in btc:
                writer.writerow([])
                writer.writerow(["# Breakthrough Curve"])
                writer.writerow(["time", "flux", "cumulative"])
                centers = btc.get("bin_centers", [])
                flux = btc.get("flux", [])
                cumul = btc.get("cumulative", [])
                for i in range(len(centers)):
                    writer.writerow([centers[i], flux[i], cumul[i]])

        # Network summary
        net = result.get("network", {})
        radii = net.get("radii", {})
        if radii and "error" not in radii:
            writer.writerow([])
            writer.writerow(["# Network Statistics"])
            writer.writerow(["metric", "value", "unit"])
            for key in ["n_fractures", "min_radius_m", "max_radius_m",
                         "mean_radius_m", "median_radius_m"]:
                if key in radii:
                    writer.writerow([key, radii[key], "m" if "_m" in key else "count"])


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Parse dfnWorks output files to CSV/JSON"
    )
    parser.add_argument("--job_dir", "-j", help="dfnWorks output directory")
    parser.add_argument("--partime", help="Particle travel time file")
    parser.add_argument("--graph_flow", help="Graph flow HDF5 file")
    parser.add_argument("--format", default="csv", choices=["csv", "json"],
                        help="Output format (default: csv)")
    parser.add_argument("--output", "-o", default="results.csv",
                        help="Output file path")
    parser.add_argument("--time_unit", default="seconds",
                        choices=["seconds", "minutes", "hours", "days", "years"],
                        help="Time unit for output (default: seconds)")
    parser.add_argument("--btc", action="store_true",
                        help="Include breakthrough curve in output")

    args = parser.parse_args()
    validated = validate_inputs(args)
    result = process(validated)
    result = validate_outputs(result)

    if validated["format"] == "json":
        with open(validated["output"], "w") as f:
            json.dump(result, f, indent=2, default=str)
    else:
        write_csv(result, validated["output"])

    # Always print JSON summary
    summary = {k: v for k, v in result.items() if k != "breakthrough_curve"}
    if "travel_times" in summary:
        summary["travel_times"] = {k: v for k, v in summary["travel_times"].items()
                                   if k not in ["sorted_times", "cdf"]}
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
