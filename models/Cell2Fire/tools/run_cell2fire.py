#!/usr/bin/env python3
"""
Execution wrapper for Cell2Fire (C2F-W) binary.

Performs:
  1. Preflight validation (instance folder structure, raster alignment, weather format)
  2. Execution of the Cell2Fire binary with specified CLI arguments
  3. Post-flight validation (output folder structure, non-empty results)

Usage:
  python run_cell2fire.py --binary ./Cell2Fire \\
      --instance-folder ./data/ScottAndBurgan/Vilopriu_2013-asc \\
      --output-folder ./results \\
      --model S --nsims 10 --nthreads 4 --seed 123 \\
      --scenario 2 --fmc 66 --cros

  python run_cell2fire.py --binary ./Cell2Fire \\
      --instance-folder ./data/CanadianFBP/dogrib-asc \\
      --output-folder ./results \\
      --model C --nsims 5 --cros
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ── Preflight validation ────────────────────────────────────────────────────

def validate_instance_folder(instance_folder: str, model: str) -> list:
    """
    Validate Cell2Fire instance folder contents before execution.
    Returns list of warnings. Raises on fatal errors.
    """
    warnings = []
    folder = Path(instance_folder)

    if not folder.exists():
        raise FileNotFoundError(f"Instance folder does not exist: {instance_folder}")

    # Check for fuel raster (required)
    fuel_files = list(folder.glob("fuels.*"))
    fuel_files = [f for f in fuel_files if f.suffix in (".asc", ".tif")]
    if not fuel_files:
        raise FileNotFoundError(f"No fuels.asc or fuels.tif found in {instance_folder}")

    # Check for elevation raster (required)
    elev_files = list(folder.glob("elevation.*"))
    elev_files = [f for f in elev_files if f.suffix in (".asc", ".tif")]
    if not elev_files:
        raise FileNotFoundError(f"No elevation.asc or elevation.tif found in {instance_folder}")

    # Check for weather file (required)
    weather_file = folder / "Weather.csv"
    weather_dir = folder / "Weathers"
    if not weather_file.exists() and not weather_dir.exists():
        raise FileNotFoundError(
            f"No Weather.csv or Weathers/ directory found in {instance_folder}"
        )

    # Check for lookup table
    if model in ("S", "K", "P"):
        lookup = folder / "spain_lookup_table.csv"
        if not lookup.exists():
            warnings.append(
                f"WARNING: spain_lookup_table.csv not found in {instance_folder}. "
                "Cell2Fire may use built-in defaults."
            )
    elif model == "C":
        lookup = folder / "fbp_lookup_table.csv"
        if not lookup.exists():
            warnings.append(
                f"WARNING: fbp_lookup_table.csv not found in {instance_folder}. "
                "Cell2Fire may use built-in defaults."
            )

    # Check raster alignment (ASC files only)
    asc_files = list(folder.glob("*.asc"))
    if len(asc_files) >= 2:
        headers = {}
        for asc in asc_files:
            hdr = _read_asc_header(str(asc))
            if hdr:
                headers[asc.name] = hdr

        if len(headers) >= 2:
            ref_name = list(headers.keys())[0]
            ref = headers[ref_name]
            for name, hdr in headers.items():
                if name == ref_name:
                    continue
                if hdr.get("ncols") != ref.get("ncols") or hdr.get("nrows") != ref.get("nrows"):
                    warnings.append(
                        f"WARNING: Raster dimension mismatch! {ref_name}: "
                        f"{ref.get('ncols')}x{ref.get('nrows')}, "
                        f"{name}: {hdr.get('ncols')}x{hdr.get('nrows')}"
                    )
                if hdr.get("cellsize") != ref.get("cellsize"):
                    warnings.append(
                        f"WARNING: Cell size mismatch! {ref_name}: {ref.get('cellsize')}, "
                        f"{name}: {hdr.get('cellsize')}"
                    )

    # Check weather format
    if weather_file.exists():
        _validate_weather_file(str(weather_file), model, warnings)

    return warnings


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
        return {}
    return header


def _validate_weather_file(filepath: str, model: str, warnings: list):
    """Check weather CSV for obvious format issues."""
    try:
        with open(filepath, "r") as f:
            header_line = f.readline().strip()
            first_data = f.readline().strip()

        cols = [c.strip() for c in header_line.split(",")]

        if model in ("S", "K"):
            expected = {"Instance", "datetime", "WS", "WD", "FireScenario"}
            missing = expected - set(cols)
            if missing:
                warnings.append(
                    f"WARNING: Weather.csv missing columns for S&B model: {missing}. "
                    f"Found: {cols}"
                )
        elif model == "C":
            expected = {"Scenario", "datetime", "WS", "WD"}
            missing = expected - set(cols)
            if missing:
                warnings.append(
                    f"WARNING: Weather.csv missing columns for FBP model: {missing}. "
                    f"Found: {cols}"
                )

        if not first_data:
            warnings.append("WARNING: Weather.csv has no data rows")

    except Exception as e:
        warnings.append(f"WARNING: Could not read Weather.csv: {e}")


# ── Output validation ───────────────────────────────────────────────────────

def validate_outputs(output_folder: str, nsims: int, flags: dict) -> list:
    """Validate Cell2Fire outputs after execution."""
    warnings = []
    folder = Path(output_folder)

    if not folder.exists():
        warnings.append(f"ERROR: Output folder does not exist: {output_folder}")
        return warnings

    # Check for Messages
    if flags.get("output_messages"):
        msg_dir = folder / "Messages"
        if msg_dir.exists():
            msg_files = list(msg_dir.glob("MessagesFile*.csv"))
            if len(msg_files) < nsims:
                warnings.append(
                    f"WARNING: Expected {nsims} message files, found {len(msg_files)}"
                )
        else:
            warnings.append("WARNING: Messages directory not created despite --output-messages")

    # Check for Grids
    if flags.get("final_grid") or flags.get("grids"):
        grid_dir = folder / "Grids"
        if not grid_dir.exists():
            warnings.append("WARNING: Grids directory not created")

    # Check for ignition log
    log_file = folder / "ignition_and_weather_log.csv"
    if not log_file.exists():
        warnings.append("NOTE: ignition_and_weather_log.csv not found (may be normal)")

    return warnings


# ── Execution ───────────────────────────────────────────────────────────────

def run_cell2fire(
    binary: str,
    instance_folder: str,
    output_folder: str,
    model: str = "S",
    nsims: int = 1,
    seed: int = 123,
    nthreads: int = 1,
    fmc: int = 100,
    scenario: int = 3,
    weather: str = "rows",
    cros: bool = False,
    output_messages: bool = True,
    final_grid: bool = True,
    grids: bool = False,
    out_ros: bool = False,
    out_intensity: bool = False,
    out_fl: bool = False,
    ignitions_log: bool = True,
    max_fire_periods: int = -1,
    fire_period_len: float = 1.0,
    weather_period_len: int = 60,
    ros_cv: float = 0.0,
    extra_args: list = None,
) -> dict:
    """
    Run Cell2Fire binary with full preflight and post-flight validation.

    Returns dict with: returncode, stdout, stderr, runtime_s, warnings.
    """
    # ── Preflight ───────────────────────────────────────────────────────
    print(f"[preflight] Validating instance folder: {instance_folder}")
    preflight_warnings = validate_instance_folder(instance_folder, model)
    for w in preflight_warnings:
        print(f"  {w}", file=sys.stderr)

    # Ensure output folder exists and is empty
    os.makedirs(output_folder, exist_ok=True)
    existing = os.listdir(output_folder)
    if existing:
        print(f"[preflight] WARNING: Output folder not empty ({len(existing)} items). "
              "Results may be unreliable.", file=sys.stderr)

    # Resolve binary path
    binary_path = shutil.which(binary) or binary
    if not os.path.isfile(binary_path):
        raise FileNotFoundError(f"Cell2Fire binary not found: {binary}")
    if not os.access(binary_path, os.X_OK):
        raise PermissionError(f"Cell2Fire binary not executable: {binary_path}")

    # ── Build command ───────────────────────────────────────────────────
    cmd = [
        binary_path,
        "--input-instance-folder", instance_folder,
        "--output-folder", output_folder,
        "--sim", model,
        "--nsims", str(nsims),
        "--seed", str(seed),
        "--nthreads", str(nthreads),
        "--fmc", str(fmc),
        "--scenario", str(scenario),
        "--weather", weather,
        "--Fire-Period-Length", str(fire_period_len),
        "--Weather-Period-Length", str(weather_period_len),
        "--ROS-CV", str(ros_cv),
    ]

    if max_fire_periods > 0:
        cmd.extend(["--max-fire-periods", str(max_fire_periods)])
    if cros:
        cmd.append("--cros")
    if output_messages:
        cmd.append("--output-messages")
    if final_grid:
        cmd.append("--final-grid")
    if grids:
        cmd.append("--grids")
    if out_ros:
        cmd.append("--out-ros")
    if out_intensity:
        cmd.append("--out-intensity")
    if out_fl:
        cmd.append("--out-fl")
    if ignitions_log:
        cmd.append("--ignitionsLog")
    if extra_args:
        cmd.extend(extra_args)

    # ── Execute ─────────────────────────────────────────────────────────
    cmd_str = " ".join(cmd)
    print(f"[execute] Running: {cmd_str}")

    t0 = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=3600,  # 1 hour max
    )
    runtime = time.time() - t0

    print(f"[execute] Finished in {runtime:.1f}s with return code {result.returncode}")

    if result.returncode != 0:
        print(f"[execute] STDERR:\n{result.stderr[:2000]}", file=sys.stderr)

    # ── Post-flight ─────────────────────────────────────────────────────
    flags = {
        "output_messages": output_messages,
        "final_grid": final_grid,
        "grids": grids,
    }
    postflight_warnings = validate_outputs(output_folder, nsims, flags)
    for w in postflight_warnings:
        print(f"  {w}", file=sys.stderr)

    return {
        "returncode": result.returncode,
        "stdout": result.stdout[:5000],
        "stderr": result.stderr[:2000],
        "runtime_s": round(runtime, 2),
        "command": cmd_str,
        "preflight_warnings": preflight_warnings,
        "postflight_warnings": postflight_warnings,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run Cell2Fire with validation")
    parser.add_argument("--binary", default="Cell2Fire", help="Path to Cell2Fire binary")
    parser.add_argument("--instance-folder", required=True, help="Instance folder path")
    parser.add_argument("--output-folder", required=True, help="Output folder path")
    parser.add_argument("--model", default="S", choices=["S", "C", "K", "P"])
    parser.add_argument("--nsims", type=int, default=1)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--nthreads", type=int, default=1)
    parser.add_argument("--fmc", type=int, default=100)
    parser.add_argument("--scenario", type=int, default=3)
    parser.add_argument("--cros", action="store_true")
    parser.add_argument("--no-messages", action="store_true")
    parser.add_argument("--no-final-grid", action="store_true")
    parser.add_argument("--grids", action="store_true")
    parser.add_argument("--out-ros", action="store_true")
    parser.add_argument("--out-intensity", action="store_true")
    parser.add_argument("--out-fl", action="store_true")
    parser.add_argument("--max-fire-periods", type=int, default=-1)

    args = parser.parse_args()

    result = run_cell2fire(
        binary=args.binary,
        instance_folder=args.instance_folder,
        output_folder=args.output_folder,
        model=args.model,
        nsims=args.nsims,
        seed=args.seed,
        nthreads=args.nthreads,
        fmc=args.fmc,
        scenario=args.scenario,
        cros=args.cros,
        output_messages=not args.no_messages,
        final_grid=not args.no_final_grid,
        grids=args.grids,
        out_ros=args.out_ros,
        out_intensity=args.out_intensity,
        out_fl=args.out_fl,
        max_fire_periods=args.max_fire_periods,
    )

    if result["returncode"] == 0:
        print(f"\nSUCCESS: Cell2Fire completed in {result['runtime_s']}s")
    else:
        print(f"\nFAILED: Cell2Fire exited with code {result['returncode']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
