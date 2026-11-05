#!/usr/bin/env python3
"""run_daisy.py — Execution wrapper for the Daisy model.

Locates the Daisy binary, validates input files, runs the simulation,
and captures output/errors. Supports timeout protection and log parsing.

Usage:
    python run_daisy.py \\
        --dai-file test.dai \\
        --work-dir /tmp/daisy-run \\
        --binary /path/to/daisy \\
        --timeout 600
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
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(dai_file, work_dir, binary_path):
    """Validate that all required inputs exist before running.

    Returns
    -------
    dict
        Validated paths and metadata.
    """
    errors = []

    # Check binary
    if not os.path.isfile(binary_path):
        errors.append(f"Daisy binary not found: {binary_path}")
    elif not os.access(binary_path, os.X_OK):
        errors.append(f"Daisy binary not executable: {binary_path}")

    # Check .dai file
    if not os.path.isfile(dai_file):
        errors.append(f"Setup file not found: {dai_file}")

    # Check work directory
    if not os.path.isdir(work_dir):
        try:
            os.makedirs(work_dir, exist_ok=True)
        except OSError as e:
            errors.append(f"Cannot create work directory: {work_dir} ({e})")

    if errors:
        raise FileNotFoundError("Input validation failed:\n  " + "\n  ".join(errors))

    # Parse .dai file to find referenced files
    referenced_files = []
    if os.path.isfile(dai_file):
        with open(dai_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("(input file"):
                    # Extract filename from (input file "xxx.dai")
                    parts = line.split('"')
                    if len(parts) >= 2:
                        referenced_files.append(parts[1])
                elif line.startswith("(weather"):
                    parts = line.split('"')
                    if len(parts) >= 2:
                        referenced_files.append(parts[1])

    # Check referenced files (warnings only — they may be in lib/)
    for ref in referenced_files:
        ref_path = os.path.join(work_dir, ref)
        if not os.path.isfile(ref_path):
            print(f"NOTE: Referenced file '{ref}' not in work dir (may be in Daisy lib/)")

    return {
        "binary": binary_path,
        "dai_file": dai_file,
        "work_dir": work_dir,
        "referenced_files": referenced_files,
    }


def validate_outputs(work_dir, expected_outputs=None):
    """Validate simulation outputs after run.

    Returns
    -------
    dict
        Found output files and their sizes.
    """
    outputs = {}
    warnings = []

    # Find all .dlf files
    dlf_files = list(Path(work_dir).glob("*.dlf"))
    for dlf in dlf_files:
        size = dlf.stat().st_size
        outputs[dlf.name] = {
            "path": str(dlf),
            "size_bytes": size,
        }
        if size == 0:
            warnings.append(f"Empty output file: {dlf.name}")

    # Check daisy.log
    log_file = os.path.join(work_dir, "daisy.log")
    if os.path.isfile(log_file):
        outputs["daisy.log"] = {
            "path": log_file,
            "size_bytes": os.path.getsize(log_file),
        }
    else:
        warnings.append("daisy.log not found")

    # Check for checkpoint
    checkpoints = list(Path(work_dir).glob("checkpoint-*.dai"))
    if checkpoints:
        outputs["checkpoint"] = {
            "path": str(checkpoints[0]),
            "count": len(checkpoints),
        }

    if not dlf_files:
        warnings.append("No .dlf output files found — simulation may have failed")

    for w in warnings:
        print(f"WARNING: {w}")

    return outputs


# ---------------------------------------------------------------------------
# Binary / library locator
# ---------------------------------------------------------------------------

# Server defaults (same as preflight_check.py DAISY_BIN / DAISY_REPO and
# tools/calib_run.py).
DEFAULT_DAISY_BIN = "KISSPATH_KI_ROOT/Daisy/bin/daisy"
DEFAULT_DAISY_HOME = "KISSPATH_KI_ROOT/Daisy/source/repo"


def _is_exe(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def find_daisy_binary(explicit_path=None, source_dir=None):
    """Locate the Daisy binary.

    Search order:
    1. Explicit path (--binary flag) -- must be valid, no fall-through
    2. $DAISY_BIN -- must be valid, no fall-through
    3. Build directory within source (--source-dir)
    4. Server default (DEFAULT_DAISY_BIN, as in preflight_check.py)
    5. System PATH (only if the server default is missing)

    Raises FileNotFoundError for an invalid explicit/env binary.
    """
    for src, val in (("--binary", explicit_path), ("$DAISY_BIN", os.environ.get("DAISY_BIN"))):
        if val is not None:   # given (even empty) -> must be valid, no fall-through
            if val and _is_exe(val):
                return os.path.abspath(val)
            raise FileNotFoundError(
                f"Daisy binary from {src} not found or not executable: {val}")

    candidates = []

    if source_dir:
        # Check common build locations
        for build_dir in [
            "build/linux-gcc-portable",
            "build/linux-gcc-native",
            "build/linux-clang-native",
            "build",
        ]:
            candidates.append(os.path.join(source_dir, build_dir, "daisy"))

    for c in candidates:
        if _is_exe(c):
            return os.path.abspath(c)

    if os.path.exists(DEFAULT_DAISY_BIN):
        if _is_exe(DEFAULT_DAISY_BIN):
            return DEFAULT_DAISY_BIN
        raise FileNotFoundError(
            f"server default Daisy binary exists but is not an executable file: {DEFAULT_DAISY_BIN}")

    # System PATH -- only when the server default is missing
    system_daisy = shutil.which("daisy")
    if system_daisy and _is_exe(system_daisy):
        return os.path.abspath(system_daisy)

    return None


def _has_daisy_lib(home):
    return bool(home) and os.path.isdir(os.path.join(home, "lib"))


def find_daisy_home(source_dir=None, binary=None):
    """Find the Daisy home (the dir holding lib/ with tillage.dai, crop.dai, ...).

    Order: --source-dir, <binary dir>/../source/repo, server default.
    Returns an absolute path or None.
    """
    cands = [source_dir]
    if binary:
        cands.append(os.path.join(os.path.dirname(os.path.realpath(binary)),
                                  "..", "source", "repo"))
    cands.append(DEFAULT_DAISY_HOME)
    for c in cands:
        if _has_daisy_lib(c):
            return os.path.abspath(c)
    return None


def daisy_env(binary, source_dir=None, daisy_home=None):
    """Environment for the Daisy subprocess.

    Daisy finds its parameter library (lib/tillage.dai, crop.dai, log.dai, ...)
    through $DAISYPATH, else through $DAISYHOME ("." + HOME/lib + HOME/sample),
    else the compiled-in home /opt/daisy, which does not exist on this server
    -> "Unknown 'action' model 'plowing'".  So:
      * explicit daisy_home (--daisy-home): must hold lib/; sets DAISYHOME and
        drops an inherited DAISYPATH (explicit choice wins, reported);
      * else, if the caller set DAISYPATH or DAISYHOME: leave the env untouched;
      * else: set DAISYHOME to the found home (same search path as
        tools/calib_run.py's DAISYPATH=.:<repo>/lib:<repo>/sample).
    Raises FileNotFoundError for an invalid explicit home.
    """
    env = dict(os.environ)
    if daisy_home is not None:
        if not _has_daisy_lib(daisy_home):
            raise FileNotFoundError(
                f"--daisy-home has no lib/ directory: {daisy_home}")
        home = os.path.abspath(daisy_home)
        if "DAISYPATH" in env:
            print(f"NOTE: --daisy-home given; ignoring inherited DAISYPATH={env['DAISYPATH']}")
            del env["DAISYPATH"]
        env["DAISYHOME"] = home
        print(f"Daisy library: DAISYHOME={home} (from --daisy-home)")
        return env
    if "DAISYPATH" in env or "DAISYHOME" in env:
        print("Daisy library: using caller's "
              + ", ".join(f"{k}={env[k]}" for k in ("DAISYPATH", "DAISYHOME") if k in env))
        return env
    home = find_daisy_home(source_dir, binary)
    if home is None:
        print("WARNING: Daisy library dir (lib/) not found and DAISYPATH/DAISYHOME not set; "
              "Daisy will look in its built-in home and library models may be unknown.")
        return env
    env["DAISYHOME"] = home
    print(f"Daisy library: DAISYHOME={home} (set by run_daisy)")
    return env


# ---------------------------------------------------------------------------
# Log parser
# ---------------------------------------------------------------------------

def parse_daisy_log(log_path):
    """Parse daisy.log for errors and warnings.

    Returns
    -------
    dict
        Parsed log with errors, warnings, and summary.
    """
    result = {
        "errors": [],
        "warnings": [],
        "simulation_time": None,
        "success": False,
    }

    if not os.path.isfile(log_path):
        result["errors"].append("daisy.log not found")
        return result

    with open(log_path) as f:
        lines = f.readlines()

    for line in lines:
        line_lower = line.lower().strip()
        if "error" in line_lower:
            result["errors"].append(line.strip())
        elif "warning" in line_lower:
            result["warnings"].append(line.strip())
        elif "simulation" in line_lower and "done" in line_lower:
            result["success"] = True
        elif "done" == line_lower or "simulation ended" in line_lower:
            result["success"] = True

    return result


# ---------------------------------------------------------------------------
# Main execution pipeline
# ---------------------------------------------------------------------------

def process(dai_file, work_dir, binary_path, timeout=600, source_dir=None,
            daisy_home=None):
    """Run a Daisy simulation.

    Parameters
    ----------
    dai_file : str
        Path to the main .dai setup file.
    work_dir : str
        Working directory for the simulation run.
    binary_path : str or None
        Path to Daisy binary, or None to auto-detect.
    timeout : int
        Timeout in seconds.
    source_dir : str or None
        Path to Daisy source for binary search.
    daisy_home : str or None
        Daisy home holding lib/ (sets DAISYHOME).  If None and neither
        DAISYPATH nor DAISYHOME is set, it is found automatically.

    Returns
    -------
    dict
        Run result with exit code, outputs, log parse, and timing.
    """
    # Step 1: Find binary
    binary = find_daisy_binary(binary_path, source_dir)
    if binary is None:
        raise FileNotFoundError(
            "Cannot find Daisy binary. Specify --binary or build from source first.")

    print(f"Using binary: {binary}")
    env = daisy_env(binary, source_dir, daisy_home)

    # Step 2: Validate inputs
    validated = validate_inputs(dai_file, work_dir, binary)

    # Step 3: Prepare working directory
    dai_basename = os.path.basename(dai_file)
    work_dai = os.path.join(work_dir, dai_basename)

    # Copy .dai file to work dir if not already there
    if os.path.abspath(dai_file) != os.path.abspath(work_dai):
        shutil.copy2(dai_file, work_dai)

    # Step 4: Run simulation
    cmd = [binary, dai_basename]
    print(f"Running: {' '.join(cmd)} in {work_dir}")

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        elapsed = timeout
        exit_code = -1
        stdout = ""
        stderr = f"Simulation timed out after {timeout} seconds"
    except Exception as e:
        elapsed = time.time() - start_time
        exit_code = -2
        stdout = ""
        stderr = str(e)

    print(f"Exit code: {exit_code}, elapsed: {elapsed:.1f}s")

    if stdout:
        print(f"STDOUT (first 500 chars):\n{stdout[:500]}")
    if stderr:
        print(f"STDERR (first 500 chars):\n{stderr[:500]}")

    # Step 5: Parse log
    log_path = os.path.join(work_dir, "daisy.log")
    log_parse = parse_daisy_log(log_path)

    # Step 6: Validate outputs
    outputs = validate_outputs(work_dir)

    run_result = {
        "binary": binary,
        "dai_file": dai_file,
        "work_dir": work_dir,
        "exit_code": exit_code,
        "elapsed_seconds": elapsed,
        "stdout": stdout[:2000],
        "stderr": stderr[:2000],
        "log": log_parse,
        "outputs": outputs,
    }

    # Summary
    n_dlf = len([k for k in outputs if k.endswith(".dlf")])
    if exit_code == 0 and n_dlf > 0:
        print(f"SUCCESS: {n_dlf} .dlf output files generated in {elapsed:.1f}s")
    elif exit_code == 0:
        print(f"Completed with exit code 0 but no .dlf files found")
    else:
        print(f"FAILED with exit code {exit_code}")
        if log_parse["errors"]:
            print(f"  Errors: {log_parse['errors'][:3]}")

    return run_result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run a Daisy simulation with validation and log parsing")
    parser.add_argument("--dai-file", required=True,
                        help="Path to main .dai setup file")
    parser.add_argument("--work-dir", default=".",
                        help="Working directory for simulation")
    parser.add_argument("--binary", default=None,
                        help="Path to Daisy binary (auto-detected if not given)")
    parser.add_argument("--source-dir", default=None,
                        help="Path to Daisy source tree (for binary search)")
    parser.add_argument("--daisy-home", default=None,
                        help="Daisy home holding lib/ (sets DAISYHOME). Default: keep "
                             "the caller's DAISYPATH/DAISYHOME, else --source-dir, "
                             "<binary>/../source/repo, server default")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Timeout in seconds (default: 600)")
    parser.add_argument("--output-json", default=None,
                        help="Write run result to JSON file")

    args = parser.parse_args()

    try:
        result = process(
            dai_file=args.dai_file,
            work_dir=args.work_dir,
            binary_path=args.binary,
            timeout=args.timeout,
            source_dir=args.source_dir,
            daisy_home=args.daisy_home,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Result written to {args.output_json}")

    if result["exit_code"] != 0:
        print(f"ERROR: Daisy run failed (exit code {result['exit_code']})",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
