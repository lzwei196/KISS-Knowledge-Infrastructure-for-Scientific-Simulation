#!/usr/bin/env python3
"""
run_rhessys.py — Execution wrapper for the RHESSys model binary.

Validates inputs, constructs the command line, runs the model, and checks
for common failure modes.

Usage:
    python run_rhessys.py \
        --binary rhessys7.4 \
        --worldfile worldfiles/w8TC.world \
        --worldhdr worldfiles/w8TC.hdr \
        --tecfile tecfiles/tec.test \
        --flowtable flowtables/w8TC.flow \
        --prefix out/test \
        --start "1988 10 1 1" --end "2000 10 1 1" \
        --basin --grow

    python run_rhessys.py \
        --binary rhessys7.4 \
        --worldfile w.world --worldhdr w.hdr \
        --tecfile tec.test --flowtable w.flow \
        --prefix out/run1 \
        --start "2000 1 1 1" --end "2010 12 31 1" \
        --basin --grow \
        --sensitivity 0.35 651.39 \
        --sensitivity-vert 0.35 651.39 \
        --sensitivity-vert-alt 1.08 1.19 \
        --groundwater 0.01 0.1
"""

import argparse
import json
import os
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate all required input files and parameters before execution."""
    errors = []
    warnings = []

    # Check binary
    binary = args.binary
    if not os.path.isfile(binary):
        # Try common locations
        for alt in ["./rhessys7.4", "../rhessys/rhessys7.4", "/usr/local/bin/rhessys7.4"]:
            if os.path.isfile(alt):
                binary = alt
                break
        else:
            errors.append(f"Binary not found: {args.binary}")

    if os.path.isfile(binary) and not os.access(binary, os.X_OK):
        errors.append(f"Binary not executable: {binary}")

    # Check input files
    for name, path in [
        ("worldfile", args.worldfile),
        ("worldhdr", args.worldhdr),
        ("tecfile", args.tecfile),
    ]:
        if not os.path.isfile(path):
            errors.append(f"{name} not found: {path}")

    if args.flowtable and not os.path.isfile(args.flowtable):
        errors.append(f"flowtable not found: {args.flowtable}")

    # Check output filter file if specified
    if args.output_filter and not os.path.isfile(args.output_filter):
        errors.append(f"output filter not found: {args.output_filter}")

    # Validate date format
    for name, val in [("start", args.start), ("end", args.end)]:
        parts = val.strip().split()
        if len(parts) != 4:
            errors.append(f"{name} date must be 'YYYY M D H', got: {val}")
        else:
            try:
                y, m, d, h = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                if y < 1900 or y > 2100:
                    warnings.append(f"{name} year {y} seems unusual")
                if m < 1 or m > 12:
                    errors.append(f"{name} month {m} out of range")
                if d < 1 or d > 31:
                    errors.append(f"{name} day {d} out of range")
                if h < 1 or h > 24:
                    errors.append(f"{name} hour {h} out of range (RHESSys uses 1-24)")
            except ValueError:
                errors.append(f"{name} date contains non-integer values: {val}")

    # Validate sensitivity parameters
    if args.sensitivity:
        if len(args.sensitivity) < 2:
            errors.append("--sensitivity requires at least 2 values (m, Ksat)")
        elif any(v <= 0 for v in args.sensitivity):
            errors.append("Sensitivity parameters must be > 0 (dt_013)")

    # Check TEC file has events after start date
    if os.path.isfile(args.tecfile):
        _check_tec_dates(args.tecfile, args.start, warnings)

    # Check output directory exists
    output_dir = os.path.dirname(args.prefix)
    if output_dir and not os.path.isdir(output_dir):
        warnings.append(f"Output directory does not exist, will create: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)

    result = {"binary": binary, "errors": errors, "warnings": warnings}
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return result


def _check_tec_dates(tecfile, start_str, warnings):
    """Check that TEC events are after the simulation start date."""
    start_parts = start_str.strip().split()
    try:
        sy, sm, sd = int(start_parts[0]), int(start_parts[1]), int(start_parts[2])
    except (IndexError, ValueError):
        return

    with open(tecfile) as f:
        has_output_event = False
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 5:
                try:
                    ty, tm, td = int(parts[0]), int(parts[1]), int(parts[2])
                    event = parts[4]
                    if "print" in event and "on" in event:
                        if (ty, tm, td) >= (sy, sm, sd):
                            has_output_event = True
                except (ValueError, IndexError):
                    pass

        if not has_output_event:
            warnings.append(
                "TRAP dt_014: No print_*_on events found in TEC file after start date. "
                "No output will be produced."
            )


# ---------------------------------------------------------------------------
# Build command
# ---------------------------------------------------------------------------

def build_command(args, binary):
    """Build the RHESSys command line."""
    cmd = [binary]

    # Required files
    cmd.extend(["-w", args.worldfile])
    cmd.extend(["-whdr", args.worldhdr])
    cmd.extend(["-t", args.tecfile])
    cmd.extend(["-pre", args.prefix])

    # Date range
    cmd.extend(["-st"] + args.start.strip().split())
    cmd.extend(["-ed"] + args.end.strip().split())

    # Routing
    if args.flowtable:
        cmd.extend(["-r", args.flowtable])

    # Stream routing
    if args.streamtable:
        cmd.extend(["-str", args.streamtable])

    # Output filter
    if args.output_filter:
        cmd.extend(["-of", args.output_filter])

    # Output levels
    if args.basin:
        cmd.append("-b")
    if args.hillslope:
        cmd.append("-h")
    if args.zone:
        cmd.append("-z")
    if args.patch:
        cmd.append("-p")
    if args.canopy:
        cmd.append("-c")

    # Growth mode
    if args.grow:
        cmd.append("-g")

    # Sensitivity parameters
    if args.sensitivity:
        cmd.extend(["-s"] + [str(v) for v in args.sensitivity])
    if args.sensitivity_vert:
        cmd.extend(["-sv"] + [str(v) for v in args.sensitivity_vert])
    if args.sensitivity_vert_alt:
        cmd.extend(["-svalt"] + [str(v) for v in args.sensitivity_vert_alt])

    # Groundwater
    if args.groundwater:
        cmd.extend(["-gw"] + [str(v) for v in args.groundwater])

    # Verbose
    if args.verbose:
        cmd.extend(["-v", str(args.verbose)])

    return cmd


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_model(cmd, timeout=None):
    """Execute the model and capture output."""
    print(f"Running: {' '.join(cmd)}")

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - t0

        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_s": round(elapsed, 1),
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Process timed out after {timeout}s",
            "elapsed_s": timeout,
        }
    except FileNotFoundError:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Binary not found: {cmd[0]}",
            "elapsed_s": 0,
        }


# ---------------------------------------------------------------------------
# Post-run validation
# ---------------------------------------------------------------------------

def validate_run(result, prefix):
    """Check the run result for common failure modes."""
    errors = []
    warnings = []

    if result["returncode"] != 0:
        stderr = result["stderr"]
        if "Segmentation fault" in stderr or "segfault" in stderr.lower():
            errors.append(
                "SEGFAULT: likely flow table / worldfile mismatch (dt_015). "
                "Verify all worldfile patches exist in flow table."
            )
        elif "cannot open" in stderr.lower():
            errors.append(f"File open error: {stderr[:200]}")
        else:
            errors.append(f"Model exited with code {result['returncode']}: {stderr[:500]}")

    # Check if output files were created
    for ext in ["_basin.daily", "_basin.yearly", "_basin.monthly"]:
        fpath = prefix + ext
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            if size == 0:
                warnings.append(f"Empty output file: {fpath}")
            break
    else:
        # Check for CSV output
        import glob
        csv_files = glob.glob(prefix + "*.csv")
        if not csv_files:
            warnings.append(
                "No output files found. Check TEC file has print events "
                "after start date (dt_014)."
            )

    return {"errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RHESSys execution wrapper with input validation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # Required
    parser.add_argument("--binary", required=True, help="Path to rhessys binary")
    parser.add_argument("--worldfile", required=True, help="World file (.world)")
    parser.add_argument("--worldhdr", required=True, help="World header file (.hdr)")
    parser.add_argument("--tecfile", required=True, help="TEC file")
    parser.add_argument("--prefix", required=True, help="Output file prefix")
    parser.add_argument("--start", required=True, help="Start date: 'YYYY M D H'")
    parser.add_argument("--end", required=True, help="End date: 'YYYY M D H'")

    # Optional files
    parser.add_argument("--flowtable", default=None, help="Flow routing table")
    parser.add_argument("--streamtable", default=None, help="Stream routing table")
    parser.add_argument("--output-filter", default=None, help="Output filter YAML")

    # Output levels
    parser.add_argument("--basin", action="store_true", help="Basin output (-b)")
    parser.add_argument("--hillslope", action="store_true", help="Hillslope output (-h)")
    parser.add_argument("--zone", action="store_true", help="Zone output (-z)")
    parser.add_argument("--patch", action="store_true", help="Patch output (-p)")
    parser.add_argument("--canopy", action="store_true", help="Canopy stratum output (-c)")
    parser.add_argument("--grow", action="store_true", help="Enable BGC grow mode (-g)")

    # Calibration/sensitivity
    parser.add_argument("--sensitivity", nargs="+", type=float, default=None,
                        help="Horizontal sensitivity: m Ksat [soil_depth]")
    parser.add_argument("--sensitivity-vert", nargs="+", type=float, default=None,
                        help="Vertical sensitivity: m Ksat")
    parser.add_argument("--sensitivity-vert-alt", nargs=2, type=float, default=None,
                        help="Alt vertical: pore_size_index psi_air_entry")
    parser.add_argument("--groundwater", nargs=2, type=float, default=None,
                        help="Groundwater: sat_to_gw_coeff gw_loss_coeff")

    # Execution
    parser.add_argument("--verbose", type=int, default=None, choices=[0, 1, 2, 3],
                        help="Verbose level (0-3)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600)")

    args = parser.parse_args()

    # Step 1: Validate inputs
    val_result = validate_inputs(args)
    binary = val_result["binary"]

    # Step 2: Build command
    cmd = build_command(args, binary)

    # Step 3: Run model
    run_result = run_model(cmd, timeout=args.timeout)

    print(f"Exit code: {run_result['returncode']}")
    print(f"Elapsed: {run_result['elapsed_s']}s")

    if run_result["stdout"]:
        print(f"STDOUT (last 500 chars): ...{run_result['stdout'][-500:]}")
    if run_result["stderr"]:
        print(f"STDERR (last 500 chars): ...{run_result['stderr'][-500:]}")

    # Step 4: Validate output
    post_val = validate_run(run_result, args.prefix)

    for w in post_val["warnings"]:
        print(f"WARNING: {w}")

    status = "ok" if run_result["returncode"] == 0 and not post_val["errors"] else "error"
    all_errors = post_val["errors"]

    output = {
        "status": status,
        "returncode": run_result["returncode"],
        "elapsed_s": run_result["elapsed_s"],
        "command": " ".join(cmd),
    }
    if all_errors:
        output["errors"] = all_errors
    if post_val["warnings"]:
        output["warnings"] = post_val["warnings"]

    print(json.dumps(output, indent=2))

    sys.exit(0 if status == "ok" else 1)


if __name__ == "__main__":
    main()
