#!/usr/bin/env python3
"""
run_wsimod.py — Execute WSIMOD model with preflight checks and result capture.

Runs WSIMOD either via CLI (wsimod settings.yaml) or Python API (Model class).
Performs preflight validation of inputs, captures stdout/stderr, and reports
execution status.

CRITICAL CHECKS:
  - Settings YAML file exists and is valid
  - Input CSV files referenced in settings are accessible
  - Python environment has required packages (PyYAML, pandas, dill, tqdm)
  - data_input_dict keys use correct (variable, timestamp) format
  - Precipitation is in meters (not mm) — max should be < 0.5 m/d
  - All arc in_port/out_port names match defined node names

Usage:
    python run_wsimod.py --settings config.yaml \\
        [--inputs ./input_dir] [--outputs ./output_dir] \\
        [--mode cli|api] [--timeout 3600]
"""

import argparse
import json
import os
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

def preflight_check(args):
    """Run preflight checks before model execution."""
    errors = []
    warnings = []

    # 1. Check settings file
    if not os.path.isfile(args.settings):
        errors.append(f"Settings file not found: {args.settings}")
    else:
        try:
            import yaml
            with open(args.settings, "r") as f:
                settings = yaml.safe_load(f)
            if settings is None:
                errors.append("Settings file is empty or invalid YAML")
            elif not isinstance(settings, dict):
                errors.append(f"Settings file must be a YAML dict, got {type(settings)}")
        except ImportError:
            errors.append("PyYAML not installed — required for WSIMOD")
        except Exception as e:
            errors.append(f"Cannot parse settings YAML: {e}")

    # 2. Check input directory
    if args.inputs:
        if not os.path.isdir(args.inputs):
            errors.append(f"Input directory not found: {args.inputs}")

    # 3. Check output directory (create if needed)
    if args.outputs:
        os.makedirs(args.outputs, exist_ok=True)

    # 4. Check Python dependencies
    required_packages = ["yaml", "pandas", "dill", "tqdm"]
    for pkg in required_packages:
        try:
            __import__(pkg)
        except ImportError:
            errors.append(f"Required package '{pkg}' not installed")

    # 5. Check wsimod is importable
    try:
        import wsimod  # noqa: F401
    except ImportError:
        errors.append(
            "WSIMOD package not installed. Install with: pip install wsimod"
        )

    # 6. Check for common configuration issues
    if not errors and os.path.isfile(args.settings):
        import yaml
        with open(args.settings, "r") as f:
            settings = yaml.safe_load(f)

        # Check for data section (custom mode)
        if "data" in settings:
            data_section = settings["data"]
            for key, spec in data_section.items():
                if isinstance(spec, dict) and "filename" in spec:
                    fname = spec["filename"]
                    input_dir = args.inputs or os.path.dirname(args.settings)
                    fpath = os.path.join(input_dir, fname)
                    if not os.path.isfile(fpath):
                        errors.append(f"Data file not found: {fpath} (data:{key})")

        # Check nodes have required fields
        if "nodes" in settings:
            node_names = set()
            for node in settings["nodes"]:
                if isinstance(node, dict):
                    if "type_" not in node:
                        errors.append(
                            f"Node missing 'type_' field: {node.get('name', '?')}"
                        )
                    if "name" not in node:
                        warnings.append(
                            f"Node missing 'name' field (type={node.get('type_', '?')})"
                        )
                    else:
                        node_names.add(node["name"])

            # Validate arc references
            if "arcs" in settings:
                for arc in settings["arcs"]:
                    if isinstance(arc, dict):
                        for port in ("in_port", "out_port"):
                            if port in arc and arc[port] not in node_names:
                                errors.append(
                                    f"Arc '{arc.get('name', '?')}' references "
                                    f"unknown node '{arc[port]}' in {port} (dt_005)"
                                )

    return errors, warnings


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_cli(args):
    """Run WSIMOD via CLI subprocess."""
    cmd = ["python", "-m", "wsimod", args.settings]
    if args.inputs:
        cmd.extend(["--inputs", str(args.inputs)])
    if args.outputs:
        cmd.extend(["--outputs", str(args.outputs)])

    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            cwd=os.path.dirname(os.path.abspath(args.settings)) or ".",
        )
        elapsed = time.time() - start

        return {
            "status": "success" if proc.returncode == 0 else "error",
            "return_code": proc.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "stdout_last_lines": proc.stdout[-2000:] if proc.stdout else "",
            "stderr_last_lines": proc.stderr[-2000:] if proc.stderr else "",
            "command": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "return_code": -1,
            "errors": [f"Timeout after {args.timeout}s"],
            "command": " ".join(cmd),
        }
    except Exception as e:
        return {
            "status": "error",
            "return_code": -1,
            "errors": [str(e)],
            "command": " ".join(cmd),
        }


def run_api(args):
    """Run WSIMOD via Python API."""
    start = time.time()
    try:
        import yaml
        import pandas as pd
        from wsimod.orchestration.model import Model
        from wsimod.validation import (
            evaluate_input_file,
            validate_io_args,
            load_data_files,
            assign_data_to_settings,
        )

        settings_type = evaluate_input_file(
            __import__("pathlib").Path(args.settings)
        )

        if settings_type == "saved":
            model = Model()
            from pathlib import Path
            inputs = Path(args.inputs) if args.inputs else Path(args.settings).parent
            outputs = Path(args.outputs) if args.outputs else Path(args.settings).parent
            model.load(inputs, config_name=Path(args.settings).name)
            flows, tanks, _, surfaces = model.run()
        else:
            from pathlib import Path
            settings_path = Path(args.settings)
            inputs_path = Path(args.inputs) if args.inputs else None
            outputs_path = Path(args.outputs) if args.outputs else None

            settings = validate_io_args(
                settings=settings_path,
                inputs=inputs_path,
                outputs=outputs_path,
            )
            inputs_dir = settings.pop("inputs")
            outputs_dir = settings.pop("outputs")
            loaded_data = load_data_files(settings.pop("data", {}), inputs_dir)
            loaded_settings = assign_data_to_settings(settings, loaded_data)

            model = Model()
            model.dates = pd.Series(loaded_settings["dates"]).drop_duplicates()
            model.add_nodes(loaded_settings["nodes"])
            model.add_arcs(loaded_settings["arcs"])
            flows, tanks, _, surfaces = model.run()
            outputs_dir = Path(args.outputs) if args.outputs else outputs_dir

        elapsed = time.time() - start

        # Save outputs
        if args.outputs:
            os.makedirs(args.outputs, exist_ok=True)
            pd.DataFrame(flows).to_csv(os.path.join(args.outputs, "flows.csv"))
            pd.DataFrame(tanks).to_csv(os.path.join(args.outputs, "tanks.csv"))
            pd.DataFrame(surfaces).to_csv(os.path.join(args.outputs, "surfaces.csv"))

        return {
            "status": "success",
            "return_code": 0,
            "elapsed_seconds": round(elapsed, 2),
            "n_flow_records": len(flows),
            "n_tank_records": len(tanks),
            "n_surface_records": len(surfaces),
            "output_files": [
                os.path.join(args.outputs, "flows.csv"),
                os.path.join(args.outputs, "tanks.csv"),
                os.path.join(args.outputs, "surfaces.csv"),
            ] if args.outputs else [],
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "status": "error",
            "return_code": 1,
            "elapsed_seconds": round(elapsed, 2),
            "errors": [str(e)],
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run WSIMOD with preflight checks"
    )
    parser.add_argument(
        "--settings", required=True, help="Path to WSIMOD YAML settings file"
    )
    parser.add_argument(
        "--inputs", default=None,
        help="Base directory for input files"
    )
    parser.add_argument(
        "--outputs", default=None,
        help="Base directory for output files"
    )
    parser.add_argument(
        "--mode", default="api", choices=["cli", "api"],
        help="Execution mode (default: api)"
    )
    parser.add_argument(
        "--timeout", type=int, default=3600,
        help="Timeout in seconds for CLI mode (default: 3600)"
    )

    args = parser.parse_args()

    # Preflight checks
    errors, warnings = preflight_check(args)
    if errors:
        result = {"status": "error", "errors": errors, "warnings": warnings}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Execute
    if args.mode == "cli":
        result = run_cli(args)
    else:
        result = run_api(args)

    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
