#!/usr/bin/env python3
"""
run_wflow.py — Execute wflow via Julia subprocess with progress monitoring.

Calls the Julia wflow_runner.jl script which loads Wflow.jl and runs the model.

IMPORTANT RUNTIME NOTES:
  - First run in a Julia session takes 30-60 seconds for JIT compilation.
    This is NORMAL, not an error. Subsequent runs are fast (~5s startup).
  - Use --threads auto for multi-threaded execution (Julia native parallelism).
  - wflow loads the entire domain into memory. For large basins (>50,000 km2),
    monitor memory usage.
  - Typical runtimes: 1-30 min depending on domain size and period.

Usage:
    python run_wflow.py --toml /path/to/wflow_sbm.toml
    python run_wflow.py --toml /path/to/wflow_sbm.toml --threads 4 --timeout 7200
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


HYDROCRAFT_ROOT = Path("/mnt/disk1/Hydrocraft_server")
JULIA_BINARY_DEFAULT = str(HYDROCRAFT_ROOT / "model" / "julia-1.10.7" / "bin" / "julia")
JULIA_ENV_DEFAULT = str(
    HYDROCRAFT_ROOT / "models" / "wflow" / "knowledge_infrastructure" / "julia"
)
WFLOW_RUNNER = str(
    HYDROCRAFT_ROOT
    / "models"
    / "wflow"
    / "knowledge_infrastructure"
    / "julia"
    / "wflow_runner.jl"
)


def validate_inputs(args):
    """Preflight checks before running wflow."""
    errors = []
    warnings = []

    # Check Julia binary
    julia_bin = args.julia_binary or JULIA_BINARY_DEFAULT
    if not os.path.exists(julia_bin):
        # Try system Julia
        import shutil
        system_julia = shutil.which("julia")
        if system_julia:
            julia_bin = system_julia
            warnings.append(f"Using system Julia: {julia_bin}")
        else:
            errors.append(
                f"Julia binary not found at {julia_bin}. "
                "Install Julia: https://julialang.org/downloads/"
            )

    # Check TOML file
    if not os.path.exists(args.toml):
        errors.append(f"TOML config not found: {args.toml}")
    else:
        # Quick TOML validation
        with open(args.toml) as f:
            content = f.read()

        if "starttime" not in content:
            errors.append("TOML missing 'starttime' in [calendar] section")
        if "endtime" not in content:
            errors.append("TOML missing 'endtime' in [calendar] section")
        if "path_static" not in content and "path_forcing" not in content:
            warnings.append("TOML may be missing input paths (path_static, path_forcing)")

        # Check referenced files exist.
        #
        # Wflow.jl resolves input.path_static / input.path_forcing relative to
        # the TOP-LEVEL `dir_input`, which is itself relative to the TOML's own
        # directory (see Wflow.jl `Config`, and the shipped developer example
        # where dir_input = "data/input" and path_static =
        # "staticmaps-moselle.nc" resolve to data/input/staticmaps-moselle.nc).
        # Joining path_static straight onto dirname(toml) ignores dir_input and
        # hard-FAILS every TOML written in the standard upstream layout — this
        # tool refused to run Deltares' own example with "Static maps file not
        # found: <toml_dir>/staticmaps-moselle.nc" (2026-08-08).  dir_input is
        # optional and defaults to the TOML's directory.
        import re
        toml_base = os.path.dirname(os.path.abspath(args.toml))
        dir_in_match = re.search(r'^\s*dir_input\s*=\s*"([^"]+)"', content,
                                 re.MULTILINE)
        input_base = toml_base
        if dir_in_match:
            d = dir_in_match.group(1)
            input_base = d if os.path.isabs(d) else os.path.join(toml_base, d)

        static_match = re.search(r'path_static\s*=\s*"([^"]+)"', content)
        if static_match:
            static_path = static_match.group(1)
            if not os.path.isabs(static_path):
                static_path = os.path.join(input_base, static_path)
            if not os.path.exists(static_path):
                errors.append(f"Static maps file not found: {static_path}")

        forcing_match = re.search(r'path_forcing\s*=\s*"([^"]+)"', content)
        if forcing_match:
            forcing_path = forcing_match.group(1)
            if not os.path.isabs(forcing_path):
                forcing_path = os.path.join(input_base, forcing_path)
            if not os.path.exists(forcing_path):
                errors.append(f"Forcing file not found: {forcing_path}")

    # Check wflow_runner.jl
    if not os.path.exists(WFLOW_RUNNER):
        errors.append(f"wflow_runner.jl not found: {WFLOW_RUNNER}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return warnings, julia_bin


def process(args, warnings, julia_bin):
    """Run wflow via Julia subprocess."""
    julia_env = args.julia_env or JULIA_ENV_DEFAULT
    toml_path = os.path.abspath(args.toml)

    cmd = [
        julia_bin,
        f"--project={julia_env}",
        f"--threads={args.threads}",
        WFLOW_RUNNER,
        toml_path,
    ]

    print(f"Executing wflow...", file=sys.stderr)
    print(f"  Julia: {julia_bin}", file=sys.stderr)
    print(f"  TOML: {toml_path}", file=sys.stderr)
    print(f"  Threads: {args.threads}", file=sys.stderr)
    print(f"  Timeout: {args.timeout}s", file=sys.stderr)
    print(
        f"  NOTE: First run may take 30-60s for Julia JIT compilation.",
        file=sys.stderr,
    )

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            cwd=os.path.dirname(toml_path),
        )
        elapsed = time.time() - start_time

        stdout_lines = result.stdout.strip().split("\n") if result.stdout else []
        stderr_lines = result.stderr.strip().split("\n") if result.stderr else []

        if result.returncode == 0:
            status = "success"
        elif result.returncode == 2:
            status = "julia_load_error"
        elif result.returncode == 3:
            status = "model_execution_error"
        else:
            status = "failed"

        # Check output files
        output_files = {}
        toml_dir = os.path.dirname(toml_path)
        for pattern in ["output/*.nc", "output.csv", "outstates.nc",
                        "output_grid.nc", "output_scalar.nc"]:
            import glob
            for fpath in glob.glob(os.path.join(toml_dir, pattern)):
                fname = os.path.basename(fpath)
                output_files[fname] = {
                    "path": fpath,
                    "size_mb": round(os.path.getsize(fpath) / 1e6, 1),
                }
        # Also check the configured output DIRECTORY. Wflow.jl writes every
        # output (netcdf_grid / netcdf_scalar / csv / outstates) into the
        # top-level `dir_output`, relative to the TOML's own directory; the
        # per-block `path = "..."` keys are FILE names inside it, not
        # directories, so globbing them as a dir silently found nothing.
        import re
        with open(toml_path) as f:
            toml_content = f.read()
        dir_out_match = re.search(r'^\s*dir_output\s*=\s*"([^"]+)"', toml_content,
                                  re.MULTILINE)
        if dir_out_match:
            out_dir = dir_out_match.group(1)
            if not os.path.isabs(out_dir):
                out_dir = os.path.join(toml_dir, out_dir)
            if os.path.isdir(out_dir):
                for pat in ("*.nc", "*.csv"):
                    for fpath in glob.glob(os.path.join(out_dir, pat)):
                        fname = os.path.basename(fpath)
                        output_files[fname] = {
                            "path": fpath,
                            "size_mb": round(os.path.getsize(fpath) / 1e6, 1),
                        }

        return {
            "status": status,
            "return_code": result.returncode,
            "elapsed_seconds": round(elapsed, 1),
            "elapsed_formatted": f"{int(elapsed//3600):02d}:{int(elapsed%3600//60):02d}:{int(elapsed%60):02d}",
            "output_files": output_files,
            "stdout_last_lines": stdout_lines[-15:] if stdout_lines else [],
            "stderr_last_lines": stderr_lines[-10:] if stderr_lines else [],
            "warnings": warnings,
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            "status": "timeout",
            "elapsed_seconds": round(elapsed, 1),
            "timeout_seconds": args.timeout,
            "message": f"wflow exceeded timeout of {args.timeout}s. "
                       f"Increase --timeout for longer simulations.",
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"Julia binary not found: {julia_bin}",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser(
        description="Execute wflow model via Julia subprocess"
    )
    parser.add_argument("--toml", type=str, required=True,
                        help="Path to wflow TOML configuration file")
    parser.add_argument("--julia_binary", type=str, default="",
                        help=f"Julia binary path (default: {JULIA_BINARY_DEFAULT})")
    parser.add_argument("--julia_env", type=str, default="",
                        help=f"Julia project environment (default: {JULIA_ENV_DEFAULT})")
    parser.add_argument("--threads", type=str, default="auto",
                        help="Julia thread count (default: auto)")
    parser.add_argument("--timeout", type=int, default=7200,
                        help="Max runtime in seconds (default: 7200 = 2 hours)")
    args = parser.parse_args()

    warnings, julia_bin = validate_inputs(args)
    result = process(args, warnings, julia_bin)

    print(json.dumps(result, indent=2))

    if result["status"] == "success":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
