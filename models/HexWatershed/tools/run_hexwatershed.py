#!/usr/bin/env python3
"""
run_hexwatershed.py — Build configuration and execute the HexWatershed binary.

This tool generates the main configuration JSON from user parameters, validates
all paths and settings, then executes the hexwatershed binary. It captures stdout,
stderr, and return code, and reports structured results.

CRITICAL: The binary expects exactly ONE argument: the path to the config JSON.
CRITICAL: All paths in the config must be absolute paths.
CRITICAL: sWorkspace_output_hexwatershed directory must exist or the binary will fail.

Usage:
    python run_hexwatershed.py --binary ./hexwatershed \
        --mesh-type hexagon --mesh-input /data/mesh/ \
        --output-dir /data/output/ \
        --accumulation-threshold 0.01

    python run_hexwatershed.py --binary ./hexwatershed \
        --config /path/to/existing_config.json
"""

import argparse
import json
import os
import subprocess
import sys
import time


def validate_inputs(args):
    """Validate all input arguments before processing."""
    errors = []
    warnings = []

    # Check binary exists
    if not os.path.isfile(args.binary):
        errors.append(f"HexWatershed binary not found: {args.binary}")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"Binary is not executable: {args.binary}. Run: chmod +x {args.binary}")

    if args.config:
        # Using existing config
        if not os.path.isfile(args.config):
            errors.append(f"Config file not found: {args.config}")
    else:
        # Building config from parameters
        if not args.mesh_input:
            errors.append("--mesh-input is required when not using --config")
        elif not os.path.isdir(args.mesh_input):
            errors.append(f"Mesh input directory not found: {args.mesh_input}")

        if not args.output_dir:
            errors.append("--output-dir is required when not using --config")

        # Validate accumulation threshold interpretation
        if args.accumulation_threshold is not None:
            t = args.accumulation_threshold
            if 1.0 <= t < 10.0:
                warnings.append(
                    f"UNIT TRAP: Accumulation threshold {t} is ≥1.0, so it will be "
                    f"treated as an ABSOLUTE cell count (not a ratio). "
                    f"For ratio-based threshold, use a value < 1.0 (e.g., 0.01 = top 1%)."
                )

        # Validate missing value
        if args.missing_value == 0.0:
            warnings.append(
                "UNIT TRAP: Missing value is 0.0. If DEM has actual 0.0 elevations "
                "(sea level), they will be treated as nodata. Use -9999.0 instead."
            )

    if errors:
        result = {"status": "error", "errors": errors, "warnings": warnings}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    return args, warnings


def build_config(args):
    """Build HexWatershed configuration JSON from command-line parameters."""
    output_hex = os.path.join(os.path.abspath(args.output_dir), "hexwatershed")
    os.makedirs(output_hex, exist_ok=True)

    config = {
        "sMesh_type": args.mesh_type,
        "iFlag_global": args.global_mode,
        "iFlag_flowline": 1 if args.basins_file else 0,
        "iFlag_multiple_outlet": args.multiple_outlet,
        "iFlag_stream_grid_option": args.stream_grid_option,
        "iFlag_stream_burning_topology": args.stream_burning_topology,
        "iFlag_hillslope": args.hillslope,
        "iFlag_animation": args.animation,
        "iFlag_vtk": args.vtk,
        "iFlag_debug": args.debug,
        "iFlag_elevation_profile": args.elevation_profile,
        "iFlag_resample_method": args.resample_method,
        "nOutlet": args.n_outlet,
        "iCase_index": args.case_index,
        "dMissing_value_dem": args.missing_value,
        "dAccumulation_threshold": args.accumulation_threshold,
        "dBreach_threshold": args.breach_threshold,
        "sWorkspace_input": os.path.abspath(args.mesh_input),
        "sWorkspace_output": os.path.abspath(args.output_dir),
        "sWorkspace_output_hexwatershed": output_hex,
        "sDate": time.strftime("%Y-%m-%d"),
    }

    if args.basins_file:
        config["sFilename_basins"] = os.path.abspath(args.basins_file)

    # Write config to output directory
    config_path = os.path.join(os.path.abspath(args.output_dir), "hexwatershed_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return config, config_path


def run_binary(binary_path, config_path, timeout=3600):
    """Execute the HexWatershed binary and capture output."""
    cmd = [os.path.abspath(binary_path), os.path.abspath(config_path)]

    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(binary_path) or ".",
        )

        elapsed = time.time() - start_time

        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout[:5000],  # Limit output size
            "stderr": proc.stderr[:5000],
            "elapsed_seconds": round(elapsed, 2),
            "command": " ".join(cmd),
        }

    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Process timed out after {timeout} seconds",
            "elapsed_seconds": timeout,
            "command": " ".join(cmd),
        }
    except FileNotFoundError:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": f"Binary not found: {binary_path}",
            "elapsed_seconds": 0,
            "command": " ".join(cmd),
        }


def process(args, input_warnings):
    """Build config (if needed) and run the model."""
    result = {"status": "success", "warnings": list(input_warnings)}

    # Step 1: Get or build config
    if args.config:
        config_path = os.path.abspath(args.config)
        with open(config_path, "r") as f:
            config = json.load(f)
    else:
        config, config_path = build_config(args)

    result["config_path"] = config_path
    result["config"] = config

    # Step 2: Validate output directory exists
    output_hex = config.get("sWorkspace_output_hexwatershed", "")
    if output_hex and not os.path.isdir(output_hex):
        os.makedirs(output_hex, exist_ok=True)

    # Step 3: Run the binary
    run_result = run_binary(args.binary, config_path, args.timeout)
    result["run"] = run_result

    if run_result["returncode"] != 0:
        result["status"] = "error"
        result["errors"] = [
            f"HexWatershed exited with code {run_result['returncode']}",
            run_result["stderr"][:500] if run_result["stderr"] else "No stderr output",
        ]
    else:
        # Check for output files
        if output_hex and os.path.isdir(output_hex):
            output_files = os.listdir(output_hex)
            result["output_files"] = output_files
            result["n_output_files"] = len(output_files)

            # Count watershed files
            watershed_files = [f for f in output_files if f.startswith("watershed_") and f.endswith(".json")]
            result["n_watersheds"] = len(watershed_files)

    return result


def validate_outputs(result):
    """Check outputs for common issues."""
    if result.get("status") != "success":
        return result

    if result.get("n_output_files", 0) == 0:
        result["warnings"].append(
            "No output files generated. Check that input mesh and config are correct."
        )

    if result.get("n_watersheds", 0) == 0:
        result["warnings"].append(
            "No watershed JSON files in output. Possible causes: "
            "wrong outlet cell ID, no valid cells in mesh, or stream grid option mismatch."
        )

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Build config and run HexWatershed binary"
    )

    # Binary path
    parser.add_argument(
        "--binary", type=str, required=True,
        help="Path to hexwatershed executable"
    )

    # Config options (mutually exclusive approaches)
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to existing config JSON (skips config generation)"
    )

    # Parameters for config generation
    parser.add_argument("--mesh-type", type=str, default="hexagon")
    parser.add_argument("--mesh-input", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--basins-file", type=str, default=None)
    parser.add_argument("--accumulation-threshold", type=float, default=0.01)
    parser.add_argument("--breach-threshold", type=float, default=0.0)
    parser.add_argument("--missing-value", type=float, default=-9999.0)
    parser.add_argument("--global-mode", type=int, default=0)
    parser.add_argument("--multiple-outlet", type=int, default=0)
    parser.add_argument("--stream-grid-option", type=int, default=2)
    parser.add_argument("--stream-burning-topology", type=int, default=0)
    parser.add_argument("--hillslope", type=int, default=0)
    parser.add_argument("--animation", type=int, default=0)
    parser.add_argument("--vtk", type=int, default=0)
    parser.add_argument("--debug", type=int, default=0)
    parser.add_argument("--elevation-profile", type=int, default=0)
    parser.add_argument("--resample-method", type=int, default=1)
    parser.add_argument("--n-outlet", type=int, default=1)
    parser.add_argument("--case-index", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=3600)

    args = parser.parse_args()
    args, input_warnings = validate_inputs(args)
    result = process(args, input_warnings)
    result = validate_outputs(result)

    # Remove large config from printed output
    summary = {k: v for k, v in result.items() if k != "config"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
