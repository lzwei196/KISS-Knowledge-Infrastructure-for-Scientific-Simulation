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
    if ribasim_bin and Path(ribasim_bin).exists():
        return ribasim_bin, errors

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
def validate_output(toml_path: Path) -> list[str]:
    """Validate output files after a successful run."""
    errors = []
    warnings = []

    # Read TOML to find results_dir
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            results_dir = toml_path.parent / "results"
            if not results_dir.exists():
                errors.append(f"Results directory not found: {results_dir}")
                return errors
            return errors

    with open(toml_path, "rb") as f:
        config = tomllib.load(f)

    results_dir = toml_path.parent / config.get("results_dir", "results")
    if not results_dir.exists():
        errors.append(f"Results directory not found: {results_dir}")
        return errors

    # Check expected output files
    expected_files = ["basin.nc", "flow.nc", "basin_state.nc"]
    optional_files = ["control.nc", "allocation.nc", "subgrid_level.nc", "solver_stats.nc"]

    for fname in expected_files:
        fpath = results_dir / fname
        if not fpath.exists():
            errors.append(f"Missing expected output: {fpath}")
        elif fpath.stat().st_size < 100:
            errors.append(f"Output file appears empty: {fpath} ({fpath.stat().st_size} bytes)")

    for fname in optional_files:
        fpath = results_dir / fname
        if fpath.exists():
            print(f"  Optional output found: {fname} ({fpath.stat().st_size} bytes)")

    # Quick NetCDF sanity check
    try:
        import xarray as xr
        basin_nc = results_dir / "basin.nc"
        if basin_nc.exists():
            ds = xr.open_dataset(basin_nc)
            n_times = ds.dims.get("time", 0)
            print(f"  basin.nc: {n_times} timesteps")
            if n_times < 2:
                errors.append(f"basin.nc has only {n_times} timestep(s) — solver may have failed")
            ds.close()
    except ImportError:
        pass
    except Exception as e:
        errors.append(f"Cannot read basin.nc: {e}")

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Run Ribasim with validation")
    parser.add_argument("--toml_path", required=True, help="Path to ribasim.toml")
    parser.add_argument("--ribasim_bin", help="Path to Ribasim binary")
    parser.add_argument("--threads", type=int, default=1, help="Number of threads")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds")
    parser.add_argument("--skip_preflight", action="store_true", help="Skip preflight checks")
    args = parser.parse_args()

    toml_path = Path(args.toml_path).resolve()

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
        sys.exit(1)

    # --- Post-run validation ---
    print("[3/3] Validating outputs...")
    errors = validate_output(toml_path)
    if errors:
        print("WARNING: Output validation issues:")
        for e in errors:
            print(f"  - {e}")

    # Write run report
    report = {
        "toml_path": str(toml_path),
        "method": result["method"],
        "success": result["success"],
        "elapsed_s": result["elapsed_s"],
        "returncode": result["returncode"],
        "output_errors": errors,
    }
    report_path = toml_path.parent / "run_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nRun report: {report_path}")

    if result["success"] and not errors:
        print("SUCCESS: Model run completed and outputs validated.")
    elif result["success"]:
        print("PARTIAL SUCCESS: Model ran but output validation has warnings.")


if __name__ == "__main__":
    main()
