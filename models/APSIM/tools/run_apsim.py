#!/usr/bin/env python3
"""
run_apsim.py — Execute APSIM simulation with preflight checks.

Wraps the APSIM CLI (`apsim run`) with:
  1. Preflight validation (binary exists, .apsimx valid, .met reachable)
  2. Execution with timeout and resource monitoring
  3. Post-run validation (output .db exists, non-empty, no fatal errors)

Usage:
  python run_apsim.py --apsimx simulation.apsimx --binary /path/to/apsim \\
      --csv --timeout 3600 --verbose

  python run_apsim.py --apsimx simulation.apsimx --dotnet-project /path/to/ApsimX \\
      --timeout 1800
"""

import argparse
import json
import os
import subprocess
import sys
import time
import re


def validate_inputs(args):
    """Preflight checks before running APSIM."""
    errors = []
    warnings = []

    # Check .apsimx file
    if not os.path.isfile(args.apsimx):
        errors.append(f"Simulation file not found: {args.apsimx}")
    else:
        # Validate JSON structure
        try:
            with open(args.apsimx) as f:
                sim = json.load(f)
            if "$type" not in sim:
                warnings.append("Missing $type in root node — may not be a valid .apsimx file")
            if "Children" not in sim:
                warnings.append("Missing Children in root node — empty simulation?")
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in {args.apsimx}: {e}")

    # Check binary
    binary = args.binary
    if binary and not os.path.isfile(binary):
        # Try common locations
        alt_paths = [
            os.path.join(args.dotnet_project or "", "APSIM.Cli", "bin", "Release", "net8.0", "apsim"),
            os.path.join(args.dotnet_project or "", "APSIM.Cli", "bin", "Debug", "net8.0", "apsim"),
        ]
        found = False
        for alt in alt_paths:
            if os.path.isfile(alt):
                binary = alt
                found = True
                break
        if not found and not args.dotnet_project:
            errors.append(f"APSIM binary not found: {args.binary}")

    # Check .met file references in simulation
    if os.path.isfile(args.apsimx):
        try:
            with open(args.apsimx) as f:
                content = f.read()
            # Find all .met file references
            met_pattern = r'"FileName"\s*:\s*"([^"]*\.met)"'
            met_files = re.findall(met_pattern, content)
            apsimx_dir = os.path.dirname(os.path.abspath(args.apsimx))
            for met_ref in met_files:
                # Resolve %root% macro
                resolved = met_ref.replace("%root%", apsimx_dir)
                if not os.path.isfile(resolved):
                    warnings.append(f"Referenced .met file not found: {met_ref} (resolved: {resolved})")
        except Exception:
            pass

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return binary, warnings


def process(args, binary, preflight_warnings):
    """Execute APSIM simulation."""
    # Build command
    if args.dotnet_project and not binary:
        # Use dotnet run
        cmd = [
            "dotnet", "run",
            "--project", os.path.join(args.dotnet_project, "APSIM.Cli"),
            "-c", "Release", "-f", "net8.0",
            "--", "run", os.path.abspath(args.apsimx),
        ]
    else:
        cmd = [binary or "apsim", "run", os.path.abspath(args.apsimx)]

    # Add flags
    if args.csv:
        cmd.append("--csv")
    if args.verbose:
        cmd.append("--verbose")
    if args.single_threaded:
        cmd.append("--single-threaded")
    if args.cpu_count:
        cmd.extend(["--cpu-count", str(args.cpu_count)])
    if args.simulation_names:
        cmd.extend(["--simulation-names", args.simulation_names])

    # Execute
    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            cwd=os.path.dirname(os.path.abspath(args.apsimx)) or ".",
        )
        elapsed = round(time.time() - start_time, 1)

        stdout = proc.stdout[:5000] if proc.stdout else ""
        stderr = proc.stderr[:5000] if proc.stderr else ""

        result = {
            "status": "ok" if proc.returncode == 0 else "error",
            "return_code": proc.returncode,
            "elapsed_s": elapsed,
            "command": " ".join(cmd),
            "stdout": stdout,
            "stderr": stderr,
            "preflight_warnings": preflight_warnings,
        }

    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start_time, 1)
        result = {
            "status": "timeout",
            "elapsed_s": elapsed,
            "command": " ".join(cmd),
            "timeout_s": args.timeout,
            "preflight_warnings": preflight_warnings,
        }

    except FileNotFoundError:
        result = {
            "status": "error",
            "errors": [f"Binary not found: {cmd[0]}. Build APSIM first or provide --binary path."],
            "command": " ".join(cmd),
            "preflight_warnings": preflight_warnings,
        }

    return result


def validate_outputs(result, args):
    """Post-run validation: check output files exist and are valid."""
    warnings = list(result.get("preflight_warnings", []))

    if result["status"] != "ok":
        result["warnings"] = warnings
        return result

    # Check for output .db file
    apsimx_path = os.path.abspath(args.apsimx)
    db_path = os.path.splitext(apsimx_path)[0] + ".db"

    if os.path.isfile(db_path):
        db_size = os.path.getsize(db_path)
        result["output_db"] = db_path
        result["output_db_size_bytes"] = db_size
        if db_size < 1000:
            warnings.append(f"Output database is very small ({db_size} bytes) — may contain no data")
    else:
        warnings.append(f"Expected output database not found: {db_path}")

    # Check for CSV if requested
    if args.csv:
        csv_pattern = os.path.splitext(apsimx_path)[0] + ".*.csv"
        import glob
        csv_files = glob.glob(csv_pattern)
        result["csv_files"] = csv_files
        if not csv_files:
            warnings.append("CSV export requested but no CSV files found")

    # Check stderr for common errors
    stderr = result.get("stderr", "")
    if "FATAL" in stderr.upper() or "EXCEPTION" in stderr.upper():
        warnings.append("FATAL or EXCEPTION found in stderr — check logs")

    if "System.NullReferenceException" in stderr:
        warnings.append("NullReferenceException — likely missing model component or parameter")

    if "Could not find" in stderr:
        warnings.append("Missing file or component referenced in simulation")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(description="Run APSIM simulation with preflight checks")
    parser.add_argument("--apsimx", required=True, help="Path to .apsimx simulation file")
    parser.add_argument("--binary", type=str, default=None,
                        help="Path to APSIM CLI binary (apsim or apsim.dll)")
    parser.add_argument("--dotnet-project", type=str, default=None,
                        help="Path to ApsimX source directory (uses dotnet run)")
    parser.add_argument("--csv", action="store_true", help="Export reports to CSV")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--single-threaded", action="store_true", help="Run sequentially")
    parser.add_argument("--cpu-count", type=int, default=None, help="Max threads")
    parser.add_argument("--simulation-names", type=str, default=None,
                        help="Regex filter for simulation names")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds (default 3600)")

    args = parser.parse_args()

    binary, preflight_warnings = validate_inputs(args)
    result = process(args, binary, preflight_warnings)
    result = validate_outputs(result, args)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
