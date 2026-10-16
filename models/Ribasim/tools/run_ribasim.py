#!/usr/bin/env python3
"""
run_ribasim.py — Execute Ribasim with preflight validation and error handling.

Runs the Ribasim model binary (or Python API) with comprehensive pre-run
checks, runtime monitoring, and post-run output validation.

Pattern: validate → process → validate

Usage:
    python run_ribasim.py \
        --toml_path my_model/ribasim.toml \
        --ribasim_bin /path/to/ribasim \
        --threads 4 \
        --timeout 3600
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

EXPECTED_OUTPUTS = ("basin.nc", "flow.nc", "basin_state.nc")


def snapshot_outputs(toml_path: Path) -> dict:
    """Record existing products without deleting or changing them."""
    with toml_path.open("rb") as stream:
        config = tomllib.load(stream)
    directory = toml_path.parent / config.get("results_dir", "results")
    snapshot = {}
    for name in EXPECTED_OUTPUTS:
        path = directory / name
        if path.exists():
            stat = path.stat()
            snapshot[name] = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        else:
            snapshot[name] = None
    return snapshot


def output_freshness_errors(toml_path: Path, before: dict) -> list[str]:
    after = snapshot_outputs(toml_path)
    return [f"Output was not created or updated by this run: {name}"
            for name in EXPECTED_OUTPUTS if after[name] is None or after[name] == before[name]]


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
def preflight_check_toml(toml_path: Path) -> list[str]:
    """Validate TOML configuration file exists and has required fields."""
    errors = []

    if not toml_path.exists():
        errors.append(f"TOML file not found: {toml_path}")
        return errors

    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            # Fallback: basic text check
            content = toml_path.read_text()
            for field in ["starttime", "endtime", "crs"]:
                if field not in content:
                    errors.append(f"Missing required field '{field}' in TOML")
            return errors

    with open(toml_path, "rb") as f:
        config = tomllib.load(f)

    required = ["starttime", "endtime", "crs"]
    for field in required:
        if field not in config:
            errors.append(f"Missing required field '{field}' in TOML")

    # Check input_dir exists
    input_dir = toml_path.parent / config.get("input_dir", "input")
    if not input_dir.exists():
        errors.append(f"Input directory not found: {input_dir}")

    # Check GeoPackage exists
    gpkg = input_dir / "database.gpkg"
    if not gpkg.exists():
        errors.append(f"GeoPackage not found: {gpkg}")

    # Check results_dir can be created
    results_dir = toml_path.parent / config.get("results_dir", "results")
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        errors.append(f"Cannot create results directory: {e}")

    return errors


def preflight_check_binary(ribasim_bin: str | None) -> tuple[str | None, list[str]]:
    """Locate and validate Ribasim binary."""
    errors = []

    # Search order: explicit path → RIBASIM_HOME → PATH
    if ribasim_bin:
        if Path(ribasim_bin).is_file() and os.access(ribasim_bin, os.X_OK):
            return str(Path(ribasim_bin).resolve()), errors
        return None, [f"Requested Ribasim binary is missing or not executable: {ribasim_bin}"]

    # Check RIBASIM_HOME env var
    ribasim_home = os.environ.get("RIBASIM_HOME")
    if ribasim_home:
        bin_path = Path(ribasim_home) / "bin" / "ribasim"
        if bin_path.exists():
            return str(bin_path), errors
        bin_path = Path(ribasim_home) / "ribasim"
        if bin_path.exists():
            return str(bin_path), errors

    # Check PATH
    found = shutil.which("ribasim")
    if found:
        return found, errors

    # Try Python API as fallback
    try:
        import ribasim
        return "__python_api__", errors
    except ImportError:
        pass

    errors.append(
        "Ribasim binary not found. Set --ribasim_bin, RIBASIM_HOME env var, "
        "or ensure 'ribasim' is on PATH. Alternatively, install the Python package."
    )
    return None, errors


def preflight_check_gpkg(gpkg_path: Path) -> list[str]:
    """Validate GeoPackage structure."""
    errors = []

    if not gpkg_path.exists():
        errors.append(f"GeoPackage not found: {gpkg_path}")
        return errors

    try:
        import sqlite3
        conn = sqlite3.connect(str(gpkg_path))
        cursor = conn.cursor()

        # Check for Node table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Node'")
        if not cursor.fetchone():
            # Try lowercase
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='node'")
            if not cursor.fetchone():
                errors.append("Missing 'Node' table in GeoPackage")

        # Check for Link/Edge table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        has_link = any("link" in t.lower() or "edge" in t.lower() for t in tables)
        if not has_link:
            errors.append("Missing 'Link' or 'Edge' table in GeoPackage")

        # List all tables for diagnostics
        print(f"  GeoPackage tables: {tables}")

        conn.close()
    except Exception as e:
        errors.append(f"Cannot read GeoPackage: {e}")

    return errors


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def run_with_binary(
    binary_path: str, toml_path: Path, threads: int = 1, timeout: int = 3600
) -> dict:
    """Run Ribasim using the compiled binary."""
    env = os.environ.copy()
    if threads > 1:
        env["JULIA_NUM_THREADS"] = str(threads)

    cmd = [binary_path, str(toml_path)]
    print(f"  Command: {' '.join(cmd)}")
    print(f"  Threads: {threads}")
    print(f"  Timeout: {timeout}s")

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(toml_path.parent),
        )
        elapsed = time.time() - start_time

        return {
            "method": "binary",
            "binary": binary_path,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_s": round(elapsed, 2),
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "method": "binary",
            "binary": binary_path,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Timeout after {timeout}s",
            "elapsed_s": timeout,
            "success": False,
        }
    except Exception as e:
        return {
            "method": "binary",
            "binary": binary_path,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "elapsed_s": time.time() - start_time,
            "success": False,
        }


def run_with_python_api(toml_path: Path) -> dict:
    """Run Ribasim using the Python API (JuliaCall)."""
    start_time = time.time()
    try:
        import ribasim
        ribasim.run_ribasim(str(toml_path))
        elapsed = time.time() - start_time
        return {
            "method": "python_api",
            "returncode": 0,
            "stdout": "Model completed successfully via Python API",
            "stderr": "",
            "elapsed_s": round(elapsed, 2),
            "success": True,
        }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "method": "python_api",
            "returncode": 1,
            "stdout": "",
            "stderr": str(e),
            "elapsed_s": round(elapsed, 2),
            "success": False,
        }


# ---------------------------------------------------------------------------
# Post-run validation
# ---------------------------------------------------------------------------
def expected_output_steps(config: dict) -> int | None:
    """Number of time rows Ribasim writes to basin.nc / flow.nc.

    Ribasim core (core/src/config.jl convert_saveat, callback.jl
    save_flow_cb with save_start=false, write.jl basin_data which drops the
    last saved time) writes one row per saveat interval, labelled by the
    interval START; the final timestamp (endtime) is never a row. So:
      finite saveat > 0 -> ceil((endtime - starttime) / saveat) rows
      saveat = Inf      -> 1 row (whole period)
      saveat = 0        -> one row per solver step (count not known: None)
    Returns None when the count cannot be known in advance.
    """
    import datetime as _dt
    import math

    start, end = config.get("starttime"), config.get("endtime")
    if not isinstance(start, _dt.datetime) or not isinstance(end, _dt.datetime):
        return None
    duration = (end - start).total_seconds()
    saveat = float(config.get("solver", {}).get("saveat", 86400.0))
    if duration <= 0:
        return None
    if saveat == math.inf:
        return 1
    if saveat > 0 and math.isfinite(saveat):
        return math.ceil(duration / saveat)
    return None


def validate_output(toml_path: Path) -> list[str]:
    """Validate output files after a run: present, readable, right length."""
    errors = []

    with open(toml_path, "rb") as f:
        config = tomllib.load(f)

    results_dir = toml_path.parent / config.get("results_dir", "results")
    if not results_dir.exists():
        errors.append(f"Results directory not found: {results_dir}")
        return errors

    optional_files = ["control.nc", "allocation.nc", "subgrid_level.nc", "solver_stats.nc"]
    for fname in optional_files:
        fpath = results_dir / fname
        if fpath.exists():
            print(f"  Optional output found: {fname} ({fpath.stat().st_size} bytes)")

    # engine="h5netcdf": the HydroCraft python_env's netCDF4/HDF5 build fails
    # with "NetCDF: HDF error" on Ribasim's CF NetCDF outputs; h5netcdf reads
    # them correctly. EVERY expected file is opened, so a corrupt file that
    # is merely large enough cannot pass.
    try:
        import xarray as xr
    except ImportError as e:
        return errors + [f"Cannot validate NetCDF outputs: {e}"]

    expected = expected_output_steps(config)
    for fname in EXPECTED_OUTPUTS:
        fpath = results_dir / fname
        if not fpath.exists():
            errors.append(f"Missing expected output: {fpath}")
            continue
        if fpath.stat().st_size < 100:
            errors.append(f"Output file appears empty: {fpath} ({fpath.stat().st_size} bytes)")
            continue
        try:
            with xr.open_dataset(fpath, engine="h5netcdf") as ds:
                if not ds.data_vars:
                    errors.append(f"{fname} has no data variables")
                # Read every variable's values (one at a time) so a damaged
                # data chunk is found here, not later by the user.
                for name in list(ds.variables):
                    ds[name].values
                if fname == "basin_state.nc":
                    # end state: one value per Basin, no time axis needed
                    continue
                n_times = ds.sizes.get("time", 0)
                print(f"  {fname}: {n_times} timesteps (expected {expected if expected is not None else '>= 1'})")
                if n_times < 1:
                    errors.append(f"{fname} has no timesteps — solver may have failed")
                elif expected is not None and n_times != expected:
                    errors.append(
                        f"{fname} has {n_times} timestep(s) but starttime/endtime/saveat "
                        f"give {expected} — run may be cut short"
                    )
        except Exception as e:
            errors.append(f"Cannot read {fname}: {e}")

    return errors


# ---------------------------------------------------------------------------
# Batch execution (one solver session for many models)
# ---------------------------------------------------------------------------
def run_batch(args) -> None:
    """Run every TOML listed in --toml_batch_file in one Ribasim session.

    Success requires a zero session exit and fresh, valid outputs for EVERY
    model. Partial results are recorded, but cannot make a failed batch pass.
    """
    batch_file = Path(args.toml_batch_file)
    if not batch_file.exists():
        print(f"FATAL: batch file not found: {batch_file}")
        sys.exit(1)
    report_path = batch_file.parent / "batch_run_report.json"
    # Replace any earlier report at once so an early stop cannot leave an
    # old "success": true behind.
    report_path.write_text(json.dumps({"batch_file": str(batch_file), "success": False,
                                       "status": "started; batch did not finish"}, indent=2))

    toml_paths = [
        Path(line.strip()).resolve()
        for line in batch_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not toml_paths:
        print("FATAL: batch file lists no TOML paths")
        sys.exit(1)

    if not args.skip_preflight:
        print(f"[1/3] Preflight checks on {len(toml_paths)} models...")
        for tp in toml_paths:
            errors = preflight_check_toml(tp)
            if errors:
                print(f"FATAL: TOML validation failed for {tp}:")
                for e in errors:
                    print(f"  - {e}")
                sys.exit(1)

    binary_path, errors = preflight_check_binary(args.ribasim_bin)
    if errors or not binary_path or binary_path == "__python_api__":
        print("FATAL: batch mode needs the Ribasim CLI binary:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"[2/3] Running Ribasim batch ({len(toml_paths)} models, one session)...")
    env = os.environ.copy()
    if args.threads > 1:
        env["JULIA_NUM_THREADS"] = str(args.threads)
    cmd = [binary_path] + [str(p) for p in toml_paths]
    before = {str(tp): snapshot_outputs(tp) for tp in toml_paths}
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=args.timeout, env=env,
        )
        batch_rc = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired as e:
        batch_rc = -1
        stdout = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = f"Timeout after {args.timeout}s: {e.stderr or ''}"
        print(f"  Batch TIMED OUT after {args.timeout}s")
    except OSError as e:
        batch_rc, stdout, stderr = -1, "", str(e)
    elapsed = time.time() - start_time
    print(f"  Batch finished in {elapsed:.1f}s (session exit code {batch_rc})")

    print("[3/3] Validating per-model outputs...")
    statuses = {}
    n_ok = 0
    for tp in toml_paths:
        errors = output_freshness_errors(tp, before[str(tp)]) + validate_output(tp)
        ok = batch_rc == 0 and not errors
        statuses[str(tp)] = {"success": ok, "outputs_valid_and_fresh": not errors,
                             "output_errors": errors}
        n_ok += ok
        print(f"  {'OK  ' if ok else 'FAIL'} {tp}")

    report = {
        "success": batch_rc == 0 and n_ok == len(toml_paths),
        "batch_file": str(batch_file),
        "method": "binary_batch",
        "binary": str(binary_path),
        "n_models": len(toml_paths),
        "n_success": n_ok,
        "elapsed_s": round(elapsed, 2),
        "session_returncode": batch_rc,
        "models": statuses,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nBatch report: {report_path}")
    label = "SUCCESS" if report["success"] else "FAILED"
    print(f"{label}: {n_ok}/{len(toml_paths)} models passed; session exit code {batch_rc}.")
    if not report["success"]:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Run Ribasim with validation")
    parser.add_argument("--toml_path", help="Path to ribasim.toml")
    parser.add_argument("--toml_batch_file",
                        help="Text file with one ribasim.toml path per line: all "
                             "models run sequentially in ONE solver session so "
                             "JIT compilation cost is paid once (calibration "
                             "batches). Mutually exclusive with --toml_path.")
    parser.add_argument("--ribasim_bin", help="Path to Ribasim binary")
    parser.add_argument("--threads", type=int, default=1, help="Number of threads")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds")
    parser.add_argument("--skip_preflight", action="store_true", help="Skip preflight checks")
    args = parser.parse_args()

    if bool(args.toml_path) == bool(args.toml_batch_file):
        print("FATAL: provide exactly one of --toml_path or --toml_batch_file")
        sys.exit(1)

    if args.toml_batch_file:
        run_batch(args)
        return

    toml_path = Path(args.toml_path).resolve()
    report_path = toml_path.parent / "run_report.json"

    def write_report(report: dict) -> None:
        report_path.write_text(json.dumps(report, indent=2))
        print(f"\nRun report: {report_path}")

    # Replace any earlier report at once: if this run stops early (preflight
    # failure, crash, timeout), an old "success": true must not remain.
    if toml_path.parent.is_dir():
        write_report({"toml_path": str(toml_path), "success": False,
                      "status": "started; run did not finish",
                      "output_errors": []})

    # --- Preflight checks ---
    if not args.skip_preflight:
        print("[1/3] Preflight checks...")

        errors = preflight_check_toml(toml_path)
        if errors:
            print("FATAL: TOML validation failed:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)

        binary_path, errors = preflight_check_binary(args.ribasim_bin)
        if errors:
            print("FATAL: Binary not found:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)

        # Check GeoPackage
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                tomllib = None

        if tomllib:
            with open(toml_path, "rb") as f:
                config = tomllib.load(f)
            input_dir = toml_path.parent / config.get("input_dir", "input")
            gpkg_path = input_dir / "database.gpkg"
            errors = preflight_check_gpkg(gpkg_path)
            if errors:
                print("FATAL: GeoPackage validation failed:")
                for e in errors:
                    print(f"  - {e}")
                sys.exit(1)

        print("  All preflight checks passed.")
    else:
        binary_path, _ = preflight_check_binary(args.ribasim_bin)

    # --- Run model ---
    print("[2/3] Running Ribasim...")
    before = snapshot_outputs(toml_path)
    if binary_path == "__python_api__":
        result = run_with_python_api(toml_path)
    elif binary_path:
        result = run_with_binary(binary_path, toml_path, args.threads, args.timeout)
    else:
        print("FATAL: No Ribasim binary or Python API available")
        sys.exit(1)

    if result["success"]:
        print(f"  Model completed in {result['elapsed_s']}s")
    else:
        print(f"  Model FAILED (exit code {result['returncode']})")
        if result["stderr"]:
            print(f"  STDERR: {result['stderr'][:500]}")
        write_report({
            "toml_path": str(toml_path),
            "method": result["method"],
            "success": False,
            "status": "model process failed or timed out",
            "elapsed_s": result["elapsed_s"],
            "returncode": result["returncode"],
            "stderr_tail": (result.get("stderr") or "")[-4000:],
            "output_errors": [],
        })
        sys.exit(1)

    # --- Post-run validation ---
    print("[3/3] Validating outputs...")
    errors = output_freshness_errors(toml_path, before) + validate_output(toml_path)
    if errors:
        print("WARNING: Output validation issues:")
        for e in errors:
            print(f"  - {e}")

    # Write run report
    report = {
        "toml_path": str(toml_path),
        "method": result["method"],
        "success": result["success"] and not errors,
        "elapsed_s": result["elapsed_s"],
        "returncode": result["returncode"],
        "output_errors": errors,
    }
    write_report(report)

    if result["success"] and not errors:
        print("SUCCESS: Model run completed and outputs validated.")
    elif result["success"]:
        print("FAILED: Model exited zero but outputs failed validation.")
        sys.exit(1)


if __name__ == "__main__":
    main()
