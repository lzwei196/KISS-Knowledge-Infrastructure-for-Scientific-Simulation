#!/usr/bin/env python3
"""Parse icepack simulation output to CSV and summary statistics.

Reads simulation result JSON (from run_icepack_simulation.py) or raw
Firedrake checkpoint files and extracts time series of velocity,
thickness, and derived quantities into a clean CSV format.

Pipeline stage: s7 (post-processing / output parsing)
Pattern: validate → process → validate
"""

import sys
import os
import json
import argparse
import logging
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs(input_path: str, input_type: str = "json") -> dict:
    """Validate input file exists and is readable.

    Parameters
    ----------
    input_path : str
        Path to simulation results JSON or checkpoint directory.
    input_type : str
        Type of input: 'json' or 'checkpoint'.

    Returns
    -------
    dict
        Validated parameters.
    """
    errors = []
    if not os.path.exists(input_path):
        errors.append(f"Input not found: {input_path}")

    if input_type == "json" and os.path.isfile(input_path):
        try:
            with open(input_path) as f:
                data = json.load(f)
            if "times" not in data:
                errors.append("JSON missing 'times' key — not a valid simulation result")
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON: {e}")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError("; ".join(errors))

    logger.info("Input validation passed: %s (type=%s)", input_path, input_type)
    return {"input_path": input_path, "input_type": input_type}


def process(input_path: str, input_type: str, output_dir: str) -> dict:
    """Parse simulation outputs and write CSV files.

    Parameters
    ----------
    input_path : str
        Path to simulation result file.
    input_type : str
        'json' or 'checkpoint'.
    output_dir : str
        Directory for CSV output files.

    Returns
    -------
    dict
        Paths to output CSV files and summary statistics.
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}

    if input_type == "json":
        with open(input_path) as f:
            data = json.load(f)

        times = np.array(data["times"])
        max_velocity = np.array(data.get("max_velocity", []))
        mean_thickness = np.array(data.get("mean_thickness", []))
        min_thickness = np.array(data.get("min_thickness", []))

        # Write time series CSV
        csv_path = os.path.join(output_dir, "timeseries.csv")
        header = "time_yr,max_velocity_myr,mean_thickness_m,min_thickness_m"
        n = len(times)
        out_data = np.column_stack([
            times[:n],
            max_velocity[:n] if len(max_velocity) else np.full(n, np.nan),
            mean_thickness[:n] if len(mean_thickness) else np.full(n, np.nan),
            min_thickness[:n] if len(min_thickness) else np.full(n, np.nan),
        ])
        np.savetxt(csv_path, out_data, delimiter=",", header=header, comments="")
        results["timeseries_csv"] = csv_path
        logger.info("Wrote time series CSV: %s (%d records)", csv_path, n)

        # Compute summary statistics
        stats = {
            "n_timesteps": n,
            "total_time_yr": float(times[-1]) if n > 0 else 0,
            "final_max_velocity_myr": float(max_velocity[-1]) if len(max_velocity) else None,
            "final_mean_thickness_m": float(mean_thickness[-1]) if len(mean_thickness) else None,
            "velocity_trend": "stable",
            "thickness_trend": "stable",
        }

        # Detect trends
        if len(max_velocity) >= 10:
            v_start = np.mean(max_velocity[:5])
            v_end = np.mean(max_velocity[-5:])
            if v_end > v_start * 1.1:
                stats["velocity_trend"] = "accelerating"
            elif v_end < v_start * 0.9:
                stats["velocity_trend"] = "decelerating"

        if len(mean_thickness) >= 10:
            h_start = np.mean(mean_thickness[:5])
            h_end = np.mean(mean_thickness[-5:])
            if h_end > h_start * 1.01:
                stats["thickness_trend"] = "thickening"
            elif h_end < h_start * 0.99:
                stats["thickness_trend"] = "thinning"

        # Mass balance check
        if len(mean_thickness) >= 2:
            dh = mean_thickness[-1] - mean_thickness[0]
            stats["total_thickness_change_m"] = float(dh)
            logger.info(
                "Total mean thickness change: %+.2f m over %.1f yr",
                dh, times[-1]
            )

        stats_path = os.path.join(output_dir, "summary_stats.json")
        with open(stats_path, "w") as f:
            json.dump(stats, f, indent=2)
        results["stats"] = stats
        results["stats_path"] = stats_path
        logger.info("Summary statistics: %s", json.dumps(stats, indent=2))

    elif input_type == "checkpoint":
        logger.info("Checkpoint parsing: reading Firedrake HDF5 files...")
        # For checkpoint files, we need Firedrake to reconstruct fields
        try:
            import firedrake
            # List available checkpoint files
            h5_files = sorted(Path(input_path).glob("*.h5"))
            if not h5_files:
                logger.error("No .h5 checkpoint files found in %s", input_path)
                results["error"] = "No checkpoint files"
                return results

            logger.info("Found %d checkpoint files", len(h5_files))
            results["n_checkpoints"] = len(h5_files)
            results["checkpoint_files"] = [str(f) for f in h5_files]
        except ImportError:
            logger.warning(
                "Firedrake not available — cannot read checkpoint files. "
                "Install Firedrake to parse checkpoint data."
            )
            results["error"] = "Firedrake not installed"

    return results


def validate_outputs(results: dict) -> bool:
    """Validate output CSV files and statistics.

    Parameters
    ----------
    results : dict
        Output from process().

    Returns
    -------
    bool
        True if outputs are valid.
    """
    ok = True

    if "error" in results:
        logger.error("Processing error: %s", results["error"])
        return False

    # Check CSV exists and has data
    csv_path = results.get("timeseries_csv")
    if csv_path:
        if not os.path.isfile(csv_path):
            logger.error("Time series CSV not written: %s", csv_path)
            ok = False
        else:
            data = np.genfromtxt(csv_path, delimiter=",", skip_header=1)
            if data.size == 0:
                logger.error("Time series CSV is empty")
                ok = False
            elif np.all(np.isnan(data[:, 1])):
                logger.warning("All velocity values are NaN — simulation may have failed")

    # Check for NaN explosion
    stats = results.get("stats", {})
    final_v = stats.get("final_max_velocity_myr")
    if final_v is not None and (np.isnan(final_v) or final_v > 50000):
        logger.warning(
            "Final max velocity = %s — possible numerical instability",
            final_v
        )
        ok = False

    # Check thickness didn't go negative
    final_h = stats.get("final_mean_thickness_m")
    if final_h is not None and final_h < 0:
        logger.error("Negative mean thickness — mass conservation violated")
        ok = False

    if ok:
        logger.info("Output validation passed.")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Parse icepack simulation output to CSV")
    parser.add_argument("--input", required=True, help="Path to simulation result JSON or checkpoint dir")
    parser.add_argument("--type", default="json", choices=["json", "checkpoint"],
                        help="Input type")
    parser.add_argument("--output-dir", default="./parsed_output", help="Output directory")
    args = parser.parse_args()

    params = validate_inputs(args.input, args.type)
    results = process(params["input_path"], params["input_type"], args.output_dir)
    valid = validate_outputs(results)

    if not valid:
        logger.error("Output validation failed")
        sys.exit(1)

    logger.info("Done. Output: %s", results)


if __name__ == "__main__":
    main()
