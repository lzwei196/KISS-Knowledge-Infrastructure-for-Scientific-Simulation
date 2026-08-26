#!/usr/bin/env python3
"""
run_wflow_full_pipeline.py — End-to-end wflow simulation pipeline.

Orchestrates stages s0-s5 (config -> build -> forcing -> params -> execute -> postprocess)
in sequence, with validation at each step.

Usage:
    python run_wflow_full_pipeline.py \
      --basin_name chaohe --lat 40.77 --lon 116.85 \
      --start_year 2000 --end_year 2010 \
      --resolution 0.25 --forcing cmfd \
      --shapefile /path/to/basin.shp \
      --forcing_dir /path/to/vic/forcing \
      --output_base /path/to/outputs

    python run_wflow_full_pipeline.py --config /path/to/wflow_config.yaml
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


HYDROCRAFT_ROOT = Path("KISSPATH_ROOT")
TOOLS_ROOT = HYDROCRAFT_ROOT / "models" / "wflow" / "knowledge_infrastructure" / "tools"
PYTHON = str(HYDROCRAFT_ROOT / "python_env" / "bin" / "python")


def run_tool(script_path, args_list, description, timeout=3600):
    """Run a tool script and return its JSON output."""
    cmd = [PYTHON, str(script_path)] + args_list
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  {description}", file=sys.stderr)
    print(f"  Command: {' '.join(cmd[:5])}...", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        elapsed = time.time() - start

        # Parse JSON output
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            output = {"stdout": result.stdout[-1000:], "stderr": result.stderr[-1000:]}

        output["_elapsed"] = round(elapsed, 1)
        output["_return_code"] = result.returncode

        if result.returncode != 0:
            print(f"  FAILED (exit code {result.returncode})", file=sys.stderr)
            if result.stderr:
                print(f"  stderr: {result.stderr[-500:]}", file=sys.stderr)
        else:
            print(f"  SUCCESS ({elapsed:.1f}s)", file=sys.stderr)

        return output

    except subprocess.TimeoutExpired:
        return {"status": "timeout", "_elapsed": timeout}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="wflow full pipeline")
    parser.add_argument("--config", type=str, default="")
    parser.add_argument("--basin_name", type=str, default="")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--start_year", type=int, default=2000)
    parser.add_argument("--end_year", type=int, default=2010)
    parser.add_argument("--resolution", type=float, default=0.25)
    parser.add_argument("--forcing", type=str, default="cmfd")
    parser.add_argument("--shapefile", type=str, default="")
    parser.add_argument("--forcing_dir", type=str, default="")
    parser.add_argument("--output_base", type=str, default="")
    parser.add_argument("--skip_build", action="store_true")
    parser.add_argument("--skip_forcing", action="store_true")
    parser.add_argument("--sediment", action="store_true")
    args = parser.parse_args()

    pipeline_start = time.time()
    results = {}

    # --- Stage 0: Configuration ---
    if not args.config:
        if not args.basin_name:
            print("ERROR: --basin_name or --config required", file=sys.stderr)
            sys.exit(1)

        config_args = [
            "--basin_name", args.basin_name,
            "--lat", str(args.lat),
            "--lon", str(args.lon),
            "--start_year", str(args.start_year),
            "--end_year", str(args.end_year),
            "--resolution", str(args.resolution),
            "--forcing", args.forcing,
        ]
        if args.shapefile:
            config_args.extend(["--shapefile", args.shapefile])
        if args.sediment:
            config_args.append("--sediment")

        output_base = args.output_base or str(
            HYDROCRAFT_ROOT / "outputs" / f"{args.basin_name}_{args.start_year}_{args.end_year}_wflow"
        )
        config_path = os.path.join(output_base, "wflow_config.yaml")
        config_args.extend(["--output", config_path])

        results["s0_config"] = run_tool(
            TOOLS_ROOT / "s0_config" / "setup_wflow_config.py",
            config_args,
            "Stage 0: Configuration",
        )
    else:
        config_path = args.config

    # --- Stage 1: Build model ---
    if not args.skip_build:
        build_args = ["--config", config_path]
        if args.shapefile:
            build_args.extend(["--shapefile", args.shapefile])

        results["s1_build"] = run_tool(
            TOOLS_ROOT / "s1_hydromt" / "run_hydromt_build.py",
            build_args,
            "Stage 1: Build wflow model (staticmaps)",
            timeout=1800,
        )

    # --- Stage 2: Forcing ---
    if not args.skip_forcing and args.forcing_dir:
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)

        forcing_args = [
            "--forcing_dir", args.forcing_dir,
            "--grid_nc", config["paths"]["staticmaps"],
            "--start_year", str(config["simulation"]["start_year"]),
            "--end_year", str(config["simulation"]["end_year"]),
            "--output", config["paths"]["forcing_nc"],
        ]

        results["s2_forcing"] = run_tool(
            TOOLS_ROOT / "s2_forcing" / "convert_forcing_to_wflow.py",
            forcing_args,
            "Stage 2: Convert forcing data",
            timeout=7200,
        )

    # --- Stage 3: Generate TOML ---
    toml_args = [
        "--config", config_path,
        "--output", str(Path(config_path).parent / "wflow_project" / "wflow_sbm.toml"),
    ]
    results["s3_toml"] = run_tool(
        TOOLS_ROOT / "s3_parameters" / "generate_wflow_toml.py",
        toml_args,
        "Stage 3: Generate wflow TOML",
    )

    # --- Stage 4: Execute wflow ---
    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)

    toml_path = config["paths"]["wflow_toml"]
    exec_args = ["--toml", toml_path, "--timeout", "7200"]

    results["s4_execute"] = run_tool(
        TOOLS_ROOT / "s4_execution" / "run_wflow.py",
        exec_args,
        "Stage 4: Execute wflow_sbm",
        timeout=7200,
    )

    # --- Stage 5: Extract discharge ---
    if results.get("s4_execute", {}).get("status") == "success":
        discharge_args = [
            "--output_nc", config["paths"]["output_grid_nc"],
            "--output", os.path.join(config["paths"]["output_dir"], "discharge.csv"),
        ]
        if args.lat:
            discharge_args.extend(["--lat", str(args.lat), "--lon", str(args.lon)])

        results["s5_discharge"] = run_tool(
            TOOLS_ROOT / "s5_postprocess" / "extract_discharge.py",
            discharge_args,
            "Stage 5: Extract discharge",
        )

    # --- Summary ---
    total_elapsed = time.time() - pipeline_start
    summary = {
        "status": "complete",
        "total_elapsed_seconds": round(total_elapsed, 1),
        "stages_completed": sum(
            1 for r in results.values()
            if r.get("status") == "success" or r.get("_return_code") == 0
        ),
        "stages_total": len(results),
        "results": {k: v.get("status", "unknown") for k, v in results.items()},
    }

    print(json.dumps(summary, indent=2))
    sys.exit(0 if all(
        r.get("status") == "success" or r.get("_return_code") == 0
        for r in results.values()
    ) else 1)


if __name__ == "__main__":
    main()
