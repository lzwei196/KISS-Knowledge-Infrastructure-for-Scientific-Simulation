#!/usr/bin/env python3
"""
Execution wrapper for HAIL-CAESAR model.

Handles:
  1. Compilation (make) if binary not found
  2. Parameter file validation (pre-flight checks)
  3. Model execution with OpenMP configuration
  4. Output existence checks (post-flight)
  5. Runtime monitoring and error capture

Usage:
    python run_caesar.py \\
        --source_dir /path/to/HAIL-CAESAR \\
        --data_dir /path/to/input_data/ \\
        --param_file simulation.params \\
        --num_threads 4
"""

import argparse
import subprocess
import sys
import os
import time
import shutil
from pathlib import Path


def validate_source(source_dir: str) -> str:
    """Validate source directory and find/build binary."""
    source = Path(source_dir)
    makefile = source / "Makefile"
    binary = source / "bin" / "HAIL-CAESAR.exe"

    if not makefile.exists():
        raise FileNotFoundError(f"Makefile not found in {source_dir}")

    if not binary.exists():
        print("Binary not found. Compiling...")
        compile_model(source_dir)

    if not binary.exists():
        raise RuntimeError(f"Compilation failed. Binary not found: {binary}")

    print(f"Binary found: {binary}")
    return str(binary)


def compile_model(source_dir: str) -> None:
    """Compile HAIL-CAESAR using make."""
    print(f"Running make in {source_dir}...")

    result = subprocess.run(
        ["make", "-j4"],
        cwd=source_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        print(f"STDOUT:\n{result.stdout}")
        print(f"STDERR:\n{result.stderr}")
        raise RuntimeError(f"Compilation failed with return code {result.returncode}")

    print("Compilation successful.")


def _resolve(rel: str, *bases) -> str:
    """Resolve a params-file path the SAME way the binary will.

    HAIL-CAESAR builds every input path as ``read_path + "/" + fname`` and
    resolves it against the process working directory (see src/main.cpp:
    argv[1] locates only the PARAMETER file, never the data files). A relative
    read_path is therefore relative to the RUN directory, which for the shipped
    Boscastle example is ``<repo>/test`` (see test/run_tests.sh), NOT the repo
    root and NOT the data dir. Try every plausible base and return the first
    that exists, else the first candidate for the error message.
    """
    cands = [rel] + [os.path.join(b, rel) for b in bases if b]
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


def validate_params(data_dir: str, param_file: str, run_cwd: str = None) -> dict:
    """Parse and validate parameter file. Returns key parameters.

    ``run_cwd`` is the directory the model binary will be launched from; a
    relative ``read_path``/``write_path`` in the params file is resolved
    against it (and against data_dir as a fallback).
    """
    param_path = os.path.join(data_dir, param_file)
    if not os.path.isfile(param_path):
        raise FileNotFoundError(f"Parameter file not found: {param_path}")

    params = {}
    with open(param_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip().lower()
                value = value.strip()
                # Remove inline comments
                if "#" in value:
                    value = value[:value.index("#")].strip()
                if value:
                    params[key] = value

    # Critical checks
    errors = []

    # Check DEM exists
    dem_name = params.get("read_fname", "")
    dem_ext = params.get("dem_read_extension", "asc")
    read_path = params.get("read_path", data_dir)
    if dem_name:
        dem_file = _resolve(os.path.join(read_path, f"{dem_name}.{dem_ext}"),
                            run_cwd, data_dir)
        if not os.path.isfile(dem_file):
            errors.append(
                f"DEM file not found: {dem_file} "
                f"(read_path={read_path!r} resolved against cwd={run_cwd!r} "
                f"and data_dir={data_dir!r})")
    else:
        errors.append("read_fname not set in parameter file")

    # Check rainfall file
    rain_file = params.get("rainfall_data_file", "")
    rain_on = params.get("rainfall_data_on", "no")
    if rain_on.lower() == "yes" and rain_file:
        rain_path = _resolve(os.path.join(read_path, rain_file),
                             run_cwd, data_dir)
        if not os.path.isfile(rain_path):
            errors.append(f"Rainfall file not found: {rain_path}")

    # Check write path. The binary does NOT create it (triplet T014), and it
    # must be created where the binary will resolve it -- i.e. against run_cwd.
    write_path = params.get("write_path", "")
    if write_path:
        wp = write_path if os.path.isabs(write_path) else \
            os.path.join(run_cwd or data_dir, write_path)
        os.makedirs(wp, exist_ok=True)
        params["_resolved_write_path"] = wp

    # Check numerical parameters
    max_run = params.get("max_run_duration", "0")
    if int(max_run) <= 0:
        errors.append(f"max_run_duration must be > 0, got {max_run}")

    courant = float(params.get("courant_number", "0.7"))
    if courant < 0.3 or courant > 0.7:
        print(f"WARNING: courant_number={courant} outside recommended range [0.3, 0.7]")

    mannings = float(params.get("mannings_n", "0.04"))
    if mannings < 0.01 or mannings > 0.3:
        print(f"WARNING: mannings_n={mannings} outside typical range [0.01, 0.3]")

    m_value = float(params.get("topmodel_m_value", "0.005"))
    if m_value < 0.001 or m_value > 0.1:
        print(f"WARNING: topmodel_m_value={m_value} outside typical range [0.001, 0.1]")

    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        raise ValueError(f"Parameter validation failed with {len(errors)} error(s)")

    print(f"Parameter validation passed. Duration: {max_run} hours, "
          f"Courant: {courant}, Manning's: {mannings}")
    return params


def _tail(path: str, nbytes: int = 8000) -> str:
    """Last nbytes of a log file (the model prints one line per iteration)."""
    try:
        size = os.path.getsize(path)
        with open(path, "r", errors="replace") as f:
            if size > nbytes:
                f.seek(size - nbytes)
            return f.read()
    except OSError:
        return ""


def run_model(binary_path: str, data_dir: str, param_file: str,
              num_threads: int = 1, timeout_sec: int = 7200,
              log_file: str = None, run_cwd: str = None) -> dict:
    """Execute HAIL-CAESAR model.

    ``timeout_sec <= 0`` means NO time limit -- required for multi-month /
    multi-year catchment runs, which are launched detached and are expected to
    take hours. ``log_file`` streams stdout+stderr straight to disk instead of
    buffering it in memory: HAIL-CAESAR prints a line per iteration, so a long
    run buffered via capture_output grows without bound and gives a watcher no
    progress signal at all.
    """
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(num_threads)

    cmd = [binary_path, data_dir, param_file]
    print(f"Running: {' '.join(cmd)}")
    print(f"OMP_NUM_THREADS={num_threads}")
    no_limit = timeout_sec is None or timeout_sec <= 0
    print(f"Timeout: {'NONE' if no_limit else str(timeout_sec) + 's'}")
    if log_file:
        print(f"Streaming model stdout/stderr -> {log_file}")

    # The binary resolves a RELATIVE read_path/write_path against ITS cwd.
    # dirname(binary) (=<repo>/bin) matches no documented invocation; the
    # shipped test script runs from <repo>/test. Default to the repo root
    # (parent of bin/) and let the caller override with run_cwd.
    cwd_eff = run_cwd or os.path.dirname(os.path.dirname(
        os.path.abspath(binary_path))) or "."
    print(f"Working directory: {cwd_eff}")
    start_time = time.time()
    wait_for = None if no_limit else timeout_sec

    try:
        if log_file:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            with open(log_file, "w") as lf:
                proc = subprocess.Popen(
                    cmd, stdout=lf, stderr=subprocess.STDOUT, env=env,
                    cwd=cwd_eff,
                )
                rc = proc.wait(timeout=wait_for)
            stdout_txt, stderr_txt = _tail(log_file), ""
        else:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=wait_for,
                env=env,
                cwd=cwd_eff,
            )
            rc, stdout_txt, stderr_txt = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        raise RuntimeError(
            f"Model timed out after {elapsed:.0f}s (limit: {timeout_sec}s)"
        )

    elapsed = time.time() - start_time

    class _Res:
        pass
    result = _Res()
    result.returncode, result.stdout, result.stderr = rc, stdout_txt, stderr_txt

    output = {
        "returncode": result.returncode,
        "elapsed_sec": elapsed,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

    if result.returncode != 0:
        print(f"Model exited with code {result.returncode}")
        print(f"STDERR: {result.stderr[:2000]}")
        print(f"STDOUT (last 1000 chars): {result.stdout[-1000:]}")
    else:
        print(f"Model completed successfully in {elapsed:.1f}s")

    return output


def validate_output(params: dict) -> dict:
    """Check that expected output files exist."""
    # use the path resolved against the model's cwd, not the raw relative one
    write_path = params.get("_resolved_write_path") or params.get("write_path", ".")
    write_fname = params.get("write_fname", "catchment.dat")

    results = {}

    # Check timeseries file
    ts_file = os.path.join(write_path, write_fname)
    if os.path.isfile(ts_file):
        size = os.path.getsize(ts_file)
        with open(ts_file, "r") as f:
            n_lines = sum(1 for _ in f)
        results["timeseries"] = {"path": ts_file, "size_bytes": size, "lines": n_lines}
        print(f"Timeseries output: {ts_file} ({n_lines} lines, {size} bytes)")
    else:
        print(f"WARNING: Timeseries file not found: {ts_file}")
        results["timeseries"] = None

    # Check raster outputs
    raster_types = {
        "waterdepth": params.get("waterdepth_outfile_name", "WaterDepths"),
        "elevation": params.get("write_elevation_file", "Elevations"),
        "grainsize": params.get("grainsize_file", "Grainz"),
    }

    dem_ext = params.get("dem_write_extension", "asc")

    for rtype, prefix in raster_types.items():
        if not prefix:
            continue
        # Look for first output raster
        import glob
        pattern = os.path.join(write_path, f"{prefix}*.{dem_ext}")
        files = sorted(glob.glob(pattern))
        if files:
            results[rtype] = {"count": len(files), "first": files[0], "last": files[-1]}
            print(f"Raster output ({rtype}): {len(files)} files")
        else:
            results[rtype] = None

    return results


def main():
    parser = argparse.ArgumentParser(description="HAIL-CAESAR execution wrapper")
    parser.add_argument("--source_dir", required=True,
                        help="Path to HAIL-CAESAR source directory")
    parser.add_argument("--data_dir", required=True,
                        help="Path to input data directory")
    parser.add_argument("--param_file", required=True,
                        help="Name of parameter file")
    parser.add_argument("--num_threads", type=int, default=1,
                        help="Number of OpenMP threads")
    parser.add_argument("--timeout", type=int, default=7200,
                        help="Timeout in seconds (default 2 hours). "
                             "Use 0 for NO limit (multi-month catchment runs).")
    parser.add_argument("--cwd", default=None,
                        help="Directory to launch the binary from. A RELATIVE "
                             "read_path/write_path in the .params file is "
                             "resolved against this (shipped Boscastle example: "
                             "<source_dir>/test). Default: <source_dir>.")
    parser.add_argument("--log_file", default=None,
                        help="Stream model stdout/stderr to this file instead of "
                             "buffering it in memory (use for long runs)")
    parser.add_argument("--skip_compile", action="store_true",
                        help="Skip compilation step")

    args = parser.parse_args()

    # Step 1: Validate source and compile
    if not args.skip_compile:
        binary = validate_source(args.source_dir)
    else:
        binary = os.path.join(args.source_dir, "bin", "HAIL-CAESAR.exe")
        if not os.path.isfile(binary):
            raise FileNotFoundError(f"Binary not found: {binary}")

    # Step 2: Validate parameters
    run_cwd = args.cwd or args.source_dir
    params = validate_params(args.data_dir, args.param_file, run_cwd)

    # Step 3: Run model
    run_result = run_model(
        binary, args.data_dir, args.param_file,
        args.num_threads, args.timeout, args.log_file, run_cwd
    )

    # Step 4: Validate output
    if run_result["returncode"] == 0:
        output_info = validate_output(params)
    else:
        print("Skipping output validation due to model failure.")
        output_info = {}

    # Summary
    print("\n=== Execution Summary ===")
    print(f"Return code: {run_result['returncode']}")
    print(f"Elapsed time: {run_result['elapsed_sec']:.1f}s")
    if output_info.get("timeseries"):
        print(f"Timeseries: {output_info['timeseries']['lines']} rows")
    print("Done.")


if __name__ == "__main__":
    main()
