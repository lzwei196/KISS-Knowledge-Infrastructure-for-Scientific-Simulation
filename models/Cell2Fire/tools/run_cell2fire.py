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

  # Exact engine command (no tool-added flags), e.g. the official C2F-W
  # sb-asc test; only the options given are passed:
  python run_cell2fire.py --engine-defaults --instance-folder model/sb-asc \\
      --output-folder test_results/sb-asc --nsims 113 --output-messages --grids \\
      --out-intensity --model S --seed 123 --ignitions-log --scenario 1 \\
      --log-file test_results/sb-asc/log.txt

By default (no --engine-defaults) the tool adds its usual flags
(--nthreads 1 --fmc 100 --scenario 3 --weather rows --Fire-Period-Length 1.0
--Weather-Period-Length 60 --ROS-CV 0.0 --output-messages --final-grid
--ignitionsLog) unless the caller sets them; that is unchanged.

Binary: --binary (path, or name on PATH) -> $CELL2FIRE_BIN -> server default
(the binary preflight_check.py checks).  An invalid --binary / $CELL2FIRE_BIN
is an error, never a silent fall-back.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Server default binary (same as preflight_check.py CELL2FIRE_BINARY).
DEFAULT_CELL2FIRE_BIN = ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
                         "Cell2Fire/source/repo/Cell2Fire/Cell2Fire")

# The tool's classic values for flags it adds unless --engine-defaults.
TOOL_DEFAULTS = {
    "nthreads": 1, "fmc": 100, "scenario": 3, "weather": "rows",
    "fire_period_len": 1.0, "weather_period_len": 60, "ros_cv": 0.0,
    "output_messages": True, "final_grid": True, "ignitions_log": True,
}


def resolve_binary(binary=None):
    """--binary -> $CELL2FIRE_BIN -> server default; invalid explicit/env -> error."""
    for src, val in (("--binary", binary), ("$CELL2FIRE_BIN", os.environ.get("CELL2FIRE_BIN"))):
        if val is not None:
            path = (shutil.which(val) if os.sep not in val else val) if val else None
            if not path or not os.path.isfile(path):
                raise FileNotFoundError(f"Cell2Fire binary from {src} not found: {val!r}")
            if not os.access(path, os.X_OK):
                raise PermissionError(f"Cell2Fire binary from {src} not executable: {path}")
            return path
    if os.path.isfile(DEFAULT_CELL2FIRE_BIN) and os.access(DEFAULT_CELL2FIRE_BIN, os.X_OK):
        return DEFAULT_CELL2FIRE_BIN
    raise FileNotFoundError(
        f"Cell2Fire binary not found: no --binary, no $CELL2FIRE_BIN, and the server "
        f"default is missing or not executable: {DEFAULT_CELL2FIRE_BIN}")


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

    # Elevation raster is optional: the engine fills a missing elevation with
    # NaN ("No elevation.asc file, filling with NaN"), as in C2F-W's own tests.
    elev_files = list(folder.glob("elevation.*"))
    elev_files = [f for f in elev_files if f.suffix in (".asc", ".tif")]
    if not elev_files:
        warnings.append(
            f"WARNING: No elevation.asc or elevation.tif in {instance_folder}; "
            "Cell2Fire will run without elevation (filled with NaN, no slope effect "
            "from elevation)."
        )

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
    nthreads: int = None,
    fmc: int = None,
    scenario: int = None,
    weather: str = None,
    cros: bool = False,
    output_messages: bool = None,
    final_grid: bool = None,
    grids: bool = False,
    out_ros: bool = False,
    out_intensity: bool = False,
    out_fl: bool = False,
    ignitions_log: bool = None,
    max_fire_periods: int = -1,
    fire_period_len: float = None,
    weather_period_len: int = None,
    ros_cv: float = None,
    extra_args: list = None,
    engine_defaults: bool = False,
    log_file: str = None,
    timeout: int = 3600,
) -> dict:
    """
    Run Cell2Fire binary with full preflight and post-flight validation.

    Options left as None get the tool's classic value (TOOL_DEFAULTS) -- the
    same command as before -- unless engine_defaults=True, in which case they
    are not passed and the engine uses its own defaults.  binary=None:
    $CELL2FIRE_BIN, then the server default.  log_file: write the engine's
    full stdout there.

    Returns dict with: returncode, stdout, stderr, runtime_s, warnings.
    """
    opts = dict(nthreads=nthreads, fmc=fmc, scenario=scenario, weather=weather,
                fire_period_len=fire_period_len, weather_period_len=weather_period_len,
                ros_cv=ros_cv, output_messages=output_messages, final_grid=final_grid,
                ignitions_log=ignitions_log)
    if not engine_defaults:
        opts = {k: (TOOL_DEFAULTS[k] if v is None else v) for k, v in opts.items()}
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
    binary_path = resolve_binary(binary)

    # ── Build command ───────────────────────────────────────────────────
    # (order and values identical to the classic tool when not engine_defaults)
    cmd = [
        binary_path,
        "--input-instance-folder", instance_folder,
        "--output-folder", output_folder,
        "--sim", model,
        "--nsims", str(nsims),
        "--seed", str(seed),
    ]
    for key, flag in (("nthreads", "--nthreads"), ("fmc", "--fmc"),
                      ("scenario", "--scenario"), ("weather", "--weather"),
                      ("fire_period_len", "--Fire-Period-Length"),
                      ("weather_period_len", "--Weather-Period-Length"),
                      ("ros_cv", "--ROS-CV")):
        if opts[key] is not None:
            cmd.extend([flag, str(opts[key])])

    if max_fire_periods > 0:
        cmd.extend(["--max-fire-periods", str(max_fire_periods)])
    if cros:
        cmd.append("--cros")
    if opts["output_messages"]:
        cmd.append("--output-messages")
    if opts["final_grid"]:
        cmd.append("--final-grid")
    if grids:
        cmd.append("--grids")
    if out_ros:
        cmd.append("--out-ros")
    if out_intensity:
        cmd.append("--out-intensity")
    if out_fl:
        cmd.append("--out-fl")
    if opts["ignitions_log"]:
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
        timeout=timeout,  # default 1 hour max
    )
    runtime = time.time() - t0
    if log_file:
        with open(log_file, "w") as fh:
            fh.write(result.stdout)

    print(f"[execute] Finished in {runtime:.1f}s with return code {result.returncode}")

    if result.returncode != 0:
        print(f"[execute] STDERR:\n{result.stderr[:2000]}", file=sys.stderr)

    # ── Post-flight ─────────────────────────────────────────────────────
    flags = {
        "output_messages": opts["output_messages"],
        "final_grid": opts["final_grid"],
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
    parser.add_argument("--binary", default=None,
                        help="Cell2Fire binary (path or name on PATH); default: "
                             "$CELL2FIRE_BIN, then the server binary")
    parser.add_argument("--instance-folder", required=True, help="Instance folder path")
    parser.add_argument("--output-folder", required=True, help="Output folder path")
    parser.add_argument("--model", default="S", choices=["S", "C", "K", "P"])
    parser.add_argument("--nsims", type=int, default=1)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--nthreads", type=int, default=None, help="(tool default 1)")
    parser.add_argument("--fmc", type=int, default=None, help="(tool default 100)")
    parser.add_argument("--scenario", type=int, default=None, help="(tool default 3)")
    parser.add_argument("--weather", default=None, help="(tool default rows)")
    parser.add_argument("--fire-period-length", type=float, default=None,
                        help="(tool default 1.0)")
    parser.add_argument("--weather-period-length", type=int, default=None,
                        help="(tool default 60)")
    parser.add_argument("--ros-cv", type=float, default=None, help="(tool default 0.0)")
    parser.add_argument("--cros", action="store_true")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--output-messages", dest="output_messages", action="store_true",
                   default=None, help="(on by default unless --engine-defaults)")
    g.add_argument("--no-messages", dest="output_messages", action="store_false")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--final-grid", dest="final_grid", action="store_true",
                   default=None, help="(on by default unless --engine-defaults)")
    g.add_argument("--no-final-grid", dest="final_grid", action="store_false")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--ignitions-log", dest="ignitions_log", action="store_true",
                   default=None, help="(on by default unless --engine-defaults)")
    g.add_argument("--no-ignitions-log", dest="ignitions_log", action="store_false")
    parser.add_argument("--grids", action="store_true")
    parser.add_argument("--out-ros", action="store_true")
    parser.add_argument("--out-intensity", action="store_true")
    parser.add_argument("--out-fl", action="store_true")
    parser.add_argument("--max-fire-periods", type=int, default=-1)
    parser.add_argument("--engine-defaults", action="store_true",
                        help="Pass only the options given (plus instance/output folder, "
                             "--sim, --nsims, --seed); do not add the tool's default flags")
    parser.add_argument("--log-file", default=None,
                        help="Write the engine's full stdout to this file")
    parser.add_argument("--timeout", type=int, default=3600)

    args = parser.parse_args()

    try:
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
            weather=args.weather,
            cros=args.cros,
            output_messages=args.output_messages,
            final_grid=args.final_grid,
            grids=args.grids,
            out_ros=args.out_ros,
            out_intensity=args.out_intensity,
            out_fl=args.out_fl,
            ignitions_log=args.ignitions_log,
            max_fire_periods=args.max_fire_periods,
            fire_period_len=args.fire_period_length,
            weather_period_len=args.weather_period_length,
            ros_cv=args.ros_cv,
            engine_defaults=args.engine_defaults,
            log_file=args.log_file,
            timeout=args.timeout,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    if result["returncode"] == 0:
        print(f"\nSUCCESS: Cell2Fire completed in {result['runtime_s']}s")
    else:
        print(f"\nFAILED: Cell2Fire exited with code {result['returncode']}"
              + ("" if result["stderr"].strip() else " (no stderr output)"))
        print(f"ERROR: Cell2Fire exited with code {result['returncode']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
