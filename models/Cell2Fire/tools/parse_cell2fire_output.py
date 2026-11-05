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
import re
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


# ── File discovery ──────────────────────────────────────────────────────────
# C2F-W names per-simulation files with the simulation number zero-padded to
# the width of str(nsims) (Cell2Fire.cpp widthSims): MessagesFile01.csv for
# 20 sims, MessagesFile001.csv for 113 sims.  Grid folders are Grids<sim>
# (no padding) holding ForestGrid<k>.csv snapshots / final grid.

class Cell2FireParseError(ValueError):
    """An output file exists but cannot be read."""


def _numbered_files(folder: Path, stem: str, ext: str) -> dict:
    """{number: path} for files named <stem><digits><ext> (any zero padding)."""
    out = {}
    if not folder.exists():
        return out
    pat = re.compile(rf"^{re.escape(stem)}(\d+){re.escape(ext)}$")
    for f in folder.iterdir():
        m = pat.match(f.name)
        if m and f.is_file():
            n = int(m.group(1))
            if n in out:
                raise Cell2FireParseError(f"two files for number {n}: {out[n].name}, {f.name}")
            out[n] = f
    return dict(sorted(out.items()))


def _grid_files(output_folder: str) -> dict:
    """{sim: [ForestGrid paths sorted by number]} from Grids/Grids<sim>/."""
    grid_dir = Path(output_folder) / "Grids"
    out = {}
    if not grid_dir.exists():
        return out
    for d in grid_dir.iterdir():
        m = re.match(r"^Grids(\d+)$", d.name)
        if m and d.is_dir():
            files = _numbered_files(d, "ForestGrid", ".csv")
            if not files and (d / "FinalGrid.csv").exists():   # legacy name
                files = {0: d / "FinalGrid.csv"}
            sim = int(m.group(1))
            if sim in out:
                raise Cell2FireParseError(f"two grid folders for simulation {sim} in {grid_dir}")
            out[sim] = list(files.values())
    return dict(sorted(out.items()))


def _read_asc(path: Path) -> np.ndarray:
    """ESRI ASCII grid -> 2-D array; checks the data size against the header."""
    hdr = _read_asc_header(str(path))
    try:
        data = np.loadtxt(str(path), skiprows=6, ndmin=2)
    except Exception as e:
        raise Cell2FireParseError(f"{path}: {e}")
    nr, nc = hdr.get("nrows"), hdr.get("ncols")
    if nr is None or nc is None or data.shape != (int(nr), int(nc)):
        raise Cell2FireParseError(f"{path}: data shape {data.shape} does not match header "
                                  f"nrows={nr} ncols={nc}")
    return data


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
    files = _numbered_files(msg_dir, "MessagesFile", ".csv")
    for sim_idx, msg_file in files.items():
        if not 1 <= sim_idx <= nsims:
            continue

        try:
            with open(msg_file, "r") as f:
                reader = csv.reader(f)
                for row in reader:
                    if not any(c.strip() for c in row):
                        continue  # blank line
                    if len(row) < 3:
                        raise ValueError(f"row with fewer than 3 fields: {row}")
                    try:
                        sender = int(row[0])
                        receiver = int(row[1])
                        time_period = float(row[2])
                    except ValueError:
                        # C2F-W message files have no header: a non-numeric
                        # row is a damaged file, not something to skip.
                        raise ValueError(f"non-numeric row: {row}")
                    all_rows.append({
                        "sim": sim_idx,
                        "sender": sender,
                        "receiver": receiver,
                        "time_period": time_period,
                    })
        except Exception as e:
            raise Cell2FireParseError(f"Error reading {msg_file}: {e}")

    return pd.DataFrame(all_rows, columns=["sim", "sender", "receiver", "time_period"])


def grid_output_kind(output_folder: str, run_log: str = None) -> str:
    """'final' if the engine's stdout log (run_log, default
    <output_folder>/log.txt, e.g. written by run_cell2fire.py --log-file)
    shows "FinalGrid: true": the engine then writes the final grid as the
    LAST ForestGrid file of each Grids<sim>/.  'unverified' if grids exist
    but there is no such proof (with --grids the files are timed snapshots,
    and even a single file can be the ignition snapshot).  'none' if no grids."""
    if not _grid_files(output_folder):
        return "none"
    log = Path(run_log) if run_log else Path(output_folder) / "log.txt"
    try:
        if log.is_file() and re.search(r"^FinalGrid:\s*true\b", log.read_text(errors="replace"), re.M):
            return "final"
    except OSError:
        pass
    return "unverified"


def count_output_files(output_folder: str, nsims: int) -> int:
    """Recognised per-simulation output files (message files, grid files)
    for simulations 1..nsims.  An empty message file (no spread) counts."""
    out = Path(output_folder)
    n = sum(1 for k in _numbered_files(out / "Messages", "MessagesFile", ".csv") if 1 <= k <= nsims)
    n += sum(len(v) for k, v in _grid_files(output_folder).items() if 1 <= k <= nsims)
    return n


def parse_final_grids(output_folder: str, nsims: int, nrows: int = None, ncols: int = None) -> np.ndarray:
    """
    Parse the LATEST written ForestGrid of each simulation (Grids/Grids<sim>/).

    This is the final burned grid only for runs made with --final-grid (see
    grid_output_kind()).  Without it the latest file is a timed snapshot that
    can miss cells burnt later; use parse_scars_from_messages() then.

    Returns 3D array: (n, nrows, ncols) with 0=unburned, 1=burned.
    """
    grids = []
    for sim_idx, files in _grid_files(output_folder).items():
        if not 1 <= sim_idx <= nsims or not files:
            continue
        try:
            grids.append(np.loadtxt(str(files[-1]), delimiter=",", ndmin=2))
        except Exception as e:
            raise Cell2FireParseError(f"Error reading {files[-1]}: {e}")

    if not grids:
        return np.array([])

    return np.array(grids)


def parse_scars_from_messages(output_folder: str, nsims: int, nrows: int, ncols: int) -> np.ndarray:
    """
    Final burned grid of each simulation rebuilt from the outputs:
    ignition cell (ignition_and_weather_log.csv) + every cell that received a
    spread message.  Needs --output-messages and --ignitionsLog.  Cell ids are
    1-based, row-major (as in C2F-W).  Returns (n, nrows, ncols) or empty.
    """
    out = Path(output_folder)
    ign_file = out / "ignition_and_weather_log.csv"
    msg_files = _numbered_files(out / "Messages", "MessagesFile", ".csv")
    if not ign_file.exists() or not msg_files:
        return np.array([])
    ign = {}
    with open(ign_file) as f:
        rows = list(csv.reader(f))
    for i, row in enumerate(rows[1:], 1):
        try:
            ign[i] = int(row[1])
        except (IndexError, ValueError):
            raise Cell2FireParseError(f"{ign_file}: bad row {i}: {row}")
    ncell = nrows * ncols
    scars = []
    for sim_idx, f in msg_files.items():
        if not 1 <= sim_idx <= nsims:
            continue
        if sim_idx not in ign:
            raise Cell2FireParseError(f"{ign_file}: no ignition row for simulation {sim_idx}")
        cells = {ign[sim_idx]}
        try:
            m = np.loadtxt(str(f), delimiter=",", ndmin=2)
        except Exception as e:
            raise Cell2FireParseError(f"Error reading {f}: {e}")
        if m.size:
            cells |= {int(c) for c in m[:, 1]}
        flat = np.zeros(ncell)
        for c in cells:
            if not 1 <= c <= ncell:
                raise Cell2FireParseError(f"{f}: cell id {c} outside 1..{ncell}")
            flat[c - 1] = 1
        scars.append(flat.reshape(nrows, ncols))
    return np.array(scars) if scars else np.array([])


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


def _parse_cell_rasters(folder: Path, stem: str, value_name: str, nsims: int) -> pd.DataFrame:
    """Per-simulation ESRI ASCII rasters <stem><n>.asc -> long table with ALL
    cells: cell (1-based, row-major as C2F-W), <value_name>, sim."""
    all_dfs = []
    for sim_idx, f in _numbered_files(folder, stem, ".asc").items():
        if not 1 <= sim_idx <= nsims:
            continue
        data = _read_asc(f)
        all_dfs.append(pd.DataFrame({"cell": np.arange(1, data.size + 1),
                                     value_name: data.ravel(), "sim": sim_idx}))
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()


def parse_ros_files(output_folder: str, nsims: int) -> pd.DataFrame:
    """Parse Rate of Spread rasters (--out-ros: RateOfSpread/ROSFile<n>.asc)."""
    return _parse_cell_rasters(Path(output_folder) / "RateOfSpread", "ROSFile", "ros", nsims)


def parse_intensity_files(output_folder: str, nsims: int) -> pd.DataFrame:
    """Parse surface Byram intensity rasters (--out-intensity:
    SurfaceIntensity/SurfaceIntensity<n>.asc)."""
    return _parse_cell_rasters(Path(output_folder) / "SurfaceIntensity", "SurfaceIntensity",
                               "intensity", nsims)


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
    kind = grid_output_kind(output_folder)
    grids = parse_final_grids(output_folder, nsims)
    grid_source = "final_grid" if kind == "final" else "none"
    if kind != "final":
        # No proof of final grids: rebuild final scars from messages +
        # ignitions when possible (grid shape from a grid file or fuels.asc).
        shape = grids.shape[1:] if grids.size else None
        if shape is None and instance_folder:
            h = _read_asc_header(str(Path(instance_folder) / "fuels.asc"))
            if "nrows" in h and "ncols" in h:
                shape = (int(h["nrows"]), int(h["ncols"]))
        scars = (parse_scars_from_messages(output_folder, nsims, int(shape[0]), int(shape[1]))
                 if shape else np.array([]))
        if scars.size:
            grids, grid_source = scars, "messages+ignitions"
        elif grids.size:
            grid_source = "latest_grid_unverified"
            input_warnings.append(
                "WARNING: burned grids are the LATEST ForestGrid file of each simulation; "
                "there is no proof it is the final grid (no 'FinalGrid: true' in log.txt) "
                "and no messages + ignition log to rebuild the scar")
            print(input_warnings[-1], file=sys.stderr)

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
    summary["grid_source"] = grid_source

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

    try:
        if not Path(args.output_folder).is_dir():
            raise Cell2FireParseError(f"output folder not found: {args.output_folder}")
        if count_output_files(args.output_folder, args.nsims) == 0:
            raise Cell2FireParseError(
                f"no MessagesFile<n>.csv or Grids<n>/ForestGrid<k>.csv for simulations "
                f"1..{args.nsims} in {args.output_folder}: nothing to parse")
        result = export_results(
            args.output_folder, args.export_dir, args.nsims, args.instance_folder
        )
    except (OSError, Cell2FireParseError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    def _fmt(key, spec):
        v = result.get(key)
        return format(v, spec) if isinstance(v, (int, float)) else "N/A"

    print(f"\n{'='*60}")
    print(f"Cell2Fire Output Summary")
    print(f"{'='*60}")
    print(f"Simulations:           {result.get('nsims', 'N/A')}")
    print(f"Burned grids from:     {result.get('grid_source', 'N/A')}")
    print(f"Mean burned cells:     {_fmt('mean_burned_cells', '.1f')}")
    print(f"Mean burn fraction:    {_fmt('mean_burn_fraction', '.3f')}")
    if "mean_burned_area_ha" in result:
        print(f"Mean burned area (ha): {result['mean_burned_area_ha']:.1f}")
    if "mean_fire_duration_periods" in result:
        print(f"Mean fire duration:    {result['mean_fire_duration_periods']:.1f} periods")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
