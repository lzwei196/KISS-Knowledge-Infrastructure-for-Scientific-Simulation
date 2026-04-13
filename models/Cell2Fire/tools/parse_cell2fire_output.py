#!/usr/bin/env python3
"""
Parse Cell2Fire output files into structured data.

Extracts:
  - Burn probability maps (from multiple simulation grids)
  - Fire spread messages (cell-to-cell propagation)
  - Rate of spread, flame length, intensity per cell
  - Summary statistics across simulations

Usage:
  python parse_cell2fire_output.py --output-folder ./results --nsims 10 \\
      --instance-folder ./data/ScottAndBurgan/Vilopriu_2013-asc \\
      --export-dir ./parsed_results
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ── Validation ──────────────────────────────────────────────────────────────

def validate_inputs(output_folder: str, nsims: int) -> list:
    """Validate that Cell2Fire output folder exists and has expected structure."""
    warnings = []
    folder = Path(output_folder)

    if not folder.exists():
        raise FileNotFoundError(f"Output folder does not exist: {output_folder}")

    # Check for Messages
    msg_dir = folder / "Messages"
    if msg_dir.exists():
        msg_files = list(msg_dir.glob("MessagesFile*.csv"))
        if len(msg_files) < nsims:
            warnings.append(
                f"WARNING: Expected {nsims} message files, found {len(msg_files)}"
            )
    else:
        warnings.append("INFO: No Messages directory found")

    # Check for Grids
    grid_dir = folder / "Grids"
    if grid_dir.exists():
        grid_subdirs = [d for d in grid_dir.iterdir() if d.is_dir()]
        if len(grid_subdirs) < nsims:
            warnings.append(
                f"WARNING: Expected {nsims} grid subdirs, found {len(grid_subdirs)}"
            )
    else:
        warnings.append("INFO: No Grids directory found")

    return warnings


def validate_outputs(export_dir: str) -> list:
    """Validate exported parsed results."""
    warnings = []

    if not os.path.exists(export_dir):
        warnings.append(f"ERROR: Export directory not created: {export_dir}")
        return warnings

    files = os.listdir(export_dir)
    if not files:
        warnings.append("WARNING: Export directory is empty")

    return warnings


# ── Parsers ─────────────────────────────────────────────────────────────────

def parse_messages(output_folder: str, nsims: int) -> pd.DataFrame:
    """
    Parse fire spread messages from all simulations.

    Returns DataFrame with columns: sim, sender, receiver, time_period
    """
    msg_dir = Path(output_folder) / "Messages"
    if not msg_dir.exists():
        return pd.DataFrame(columns=["sim", "sender", "receiver", "time_period"])

    all_rows = []
    for sim_idx in range(1, nsims + 1):
        msg_file = msg_dir / f"MessagesFile{sim_idx}.csv"
        if not msg_file.exists():
            # Try alternate naming: MessagesFile01.csv
            msg_file = msg_dir / f"MessagesFile{sim_idx:02d}.csv"
        if not msg_file.exists():
            continue

        try:
            with open(msg_file, "r") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 3:
                        try:
                            sender = int(row[0])
                            receiver = int(row[1])
                            time_period = float(row[2])
                            all_rows.append({
                                "sim": sim_idx,
                                "sender": sender,
                                "receiver": receiver,
                                "time_period": time_period,
                            })
                        except (ValueError, IndexError):
                            continue  # Skip header or malformed rows
        except Exception as e:
            print(f"WARNING: Error reading {msg_file}: {e}", file=sys.stderr)

    return pd.DataFrame(all_rows)


def parse_final_grids(output_folder: str, nsims: int, nrows: int = None, ncols: int = None) -> np.ndarray:
    """
    Parse final burned grids from all simulations.

    Returns 3D array: (nsims, nrows, ncols) with 0=unburned, 1=burned.
    If nrows/ncols not provided, inferred from first grid file.
    """
    grid_dir = Path(output_folder) / "Grids"
    if not grid_dir.exists():
        return np.array([])

    grids = []
    for sim_idx in range(1, nsims + 1):
        # Try different naming conventions
        candidates = [
            grid_dir / f"Grids{sim_idx}" / "FinalGrid.csv",
            grid_dir / f"Grids{sim_idx:02d}" / "FinalGrid.csv",
        ]

        grid_data = None
        for candidate in candidates:
            if candidate.exists():
                try:
                    grid_data = np.loadtxt(str(candidate), delimiter=",")
                    break
                except Exception:
                    continue

        if grid_data is not None:
            grids.append(grid_data)

    if not grids:
        return np.array([])

    return np.array(grids)


def compute_burn_probability(grids: np.ndarray) -> np.ndarray:
    """
    Compute burn probability from multiple simulation grids.

    Parameters
    ----------
    grids : np.ndarray
        3D array (nsims, nrows, ncols) with 0/1 values.

    Returns
    -------
    2D array (nrows, ncols) with values 0.0-1.0.
    """
    if grids.size == 0:
        return np.array([])
    return np.mean(grids > 0, axis=0)


def parse_ros_files(output_folder: str, nsims: int) -> pd.DataFrame:
    """Parse Rate of Spread files from all simulations."""
    ros_dir = Path(output_folder) / "RateOfSpread"
    if not ros_dir.exists():
        return pd.DataFrame()

    all_dfs = []
    for sim_idx in range(1, nsims + 1):
        ros_file = ros_dir / f"ROSFile{sim_idx}.csv"
        if not ros_file.exists():
            continue
        try:
            df = pd.read_csv(ros_file, header=None, names=["cell", "ros"])
            df["sim"] = sim_idx
            all_dfs.append(df)
        except Exception:
            continue

    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()


def parse_intensity_files(output_folder: str, nsims: int) -> pd.DataFrame:
    """Parse fire intensity files from all simulations."""
    int_dir = Path(output_folder) / "Intensity"
    if not int_dir.exists():
        return pd.DataFrame()

    all_dfs = []
    for sim_idx in range(1, nsims + 1):
        int_file = int_dir / f"IntensityFile{sim_idx}.csv"
        if not int_file.exists():
            continue
        try:
            df = pd.read_csv(int_file, header=None, names=["cell", "intensity"])
            df["sim"] = sim_idx
            all_dfs.append(df)
        except Exception:
            continue

    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()


def parse_ignition_log(output_folder: str) -> pd.DataFrame:
    """Parse the ignition and weather log."""
    log_file = Path(output_folder) / "ignition_and_weather_log.csv"
    if not log_file.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(log_file)
    except Exception:
        return pd.DataFrame()


# ── Summary statistics ──────────────────────────────────────────────────────

def compute_summary(
    messages: pd.DataFrame,
    grids: np.ndarray,
    nsims: int,
    cell_area: float = None,
) -> dict:
    """
    Compute summary statistics across all simulations.

    Parameters
    ----------
    messages : pd.DataFrame
        Parsed messages.
    grids : np.ndarray
        Final grids (nsims, nrows, ncols).
    nsims : int
        Number of simulations.
    cell_area : float, optional
        Area of each cell in hectares.

    Returns
    -------
    dict with summary statistics.
    """
    summary = {"nsims": nsims}

    if grids.size > 0:
        # Burned cells per simulation
        burned_per_sim = np.sum(grids > 0, axis=(1, 2))
        summary["mean_burned_cells"] = float(np.mean(burned_per_sim))
        summary["std_burned_cells"] = float(np.std(burned_per_sim))
        summary["min_burned_cells"] = int(np.min(burned_per_sim))
        summary["max_burned_cells"] = int(np.max(burned_per_sim))
        summary["total_cells"] = int(grids.shape[1] * grids.shape[2])
        summary["mean_burn_fraction"] = float(
            np.mean(burned_per_sim) / (grids.shape[1] * grids.shape[2])
        )

        if cell_area is not None:
            summary["mean_burned_area_ha"] = float(np.mean(burned_per_sim) * cell_area)
            summary["std_burned_area_ha"] = float(np.std(burned_per_sim) * cell_area)

        # Burn probability
        bp = compute_burn_probability(grids)
        summary["max_burn_probability"] = float(np.max(bp))
        summary["mean_burn_probability"] = float(np.mean(bp[bp > 0])) if np.any(bp > 0) else 0.0

    if not messages.empty:
        # Fire spread statistics
        periods_per_sim = messages.groupby("sim")["time_period"].max()
        summary["mean_fire_duration_periods"] = float(periods_per_sim.mean())
        summary["max_fire_duration_periods"] = int(periods_per_sim.max())

    return summary


# ── Export ──────────────────────────────────────────────────────────────────

def export_results(
    output_folder: str,
    export_dir: str,
    nsims: int,
    instance_folder: str = None,
) -> dict:
    """
    Parse all Cell2Fire outputs and export to structured files.

    Returns dict with file paths and summary statistics.
    """
    os.makedirs(export_dir, exist_ok=True)

    # Parse everything
    input_warnings = validate_inputs(output_folder, nsims)
    for w in input_warnings:
        print(w, file=sys.stderr)

    messages = parse_messages(output_folder, nsims)
    grids = parse_final_grids(output_folder, nsims)

    # Get cell area from instance folder
    cell_area = None
    if instance_folder:
        fuel_asc = Path(instance_folder) / "fuels.asc"
        if fuel_asc.exists():
            hdr = _read_asc_header(str(fuel_asc))
            if "cellsize" in hdr:
                # Cell area in hectares (cellsize is in meters)
                cell_area = (hdr["cellsize"] ** 2) / 10000.0

    # Compute summary
    summary = compute_summary(messages, grids, nsims, cell_area)

    # Export messages
    if not messages.empty:
        msg_path = os.path.join(export_dir, "all_messages.csv")
        messages.to_csv(msg_path, index=False)
        summary["messages_file"] = msg_path

    # Export burn probability
    if grids.size > 0:
        bp = compute_burn_probability(grids)
        bp_path = os.path.join(export_dir, "burn_probability.csv")
        np.savetxt(bp_path, bp, delimiter=",", fmt="%.4f")
        summary["burn_probability_file"] = bp_path

    # Export summary
    import json
    summary_path = os.path.join(export_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Validate exports
    export_warnings = validate_outputs(export_dir)
    for w in export_warnings:
        print(w, file=sys.stderr)

    summary["warnings"] = input_warnings + export_warnings
    return summary


def _read_asc_header(filepath: str) -> dict:
    """Read ASC grid file header."""
    header = {}
    try:
        with open(filepath, "r") as f:
            for _ in range(6):
                line = f.readline().strip()
                parts = line.split()
                if len(parts) == 2:
                    key = parts[0].lower()
                    try:
                        header[key] = int(parts[1])
                    except ValueError:
                        try:
                            header[key] = float(parts[1])
                        except ValueError:
                            pass
    except Exception:
        pass
    return header


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Parse Cell2Fire output files")
    parser.add_argument("--output-folder", required=True, help="Cell2Fire output folder")
    parser.add_argument("--nsims", type=int, required=True, help="Number of simulations")
    parser.add_argument("--instance-folder", default=None,
                        help="Instance folder (for cell area calculation)")
    parser.add_argument("--export-dir", required=True, help="Directory for parsed results")

    args = parser.parse_args()

    result = export_results(
        args.output_folder, args.export_dir, args.nsims, args.instance_folder
    )

    print(f"\n{'='*60}")
    print(f"Cell2Fire Output Summary")
    print(f"{'='*60}")
    print(f"Simulations:           {result.get('nsims', 'N/A')}")
    print(f"Mean burned cells:     {result.get('mean_burned_cells', 'N/A'):.1f}")
    print(f"Mean burn fraction:    {result.get('mean_burn_fraction', 'N/A'):.3f}")
    if "mean_burned_area_ha" in result:
        print(f"Mean burned area (ha): {result['mean_burned_area_ha']:.1f}")
    if "mean_fire_duration_periods" in result:
        print(f"Mean fire duration:    {result['mean_fire_duration_periods']:.1f} periods")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
