#!/usr/bin/env python3
"""
run_ogs.py — Execute OpenGeoSys simulation with preflight checks and output validation.

Generates a complete .prj project file from parameters and templates, runs the OGS
binary, monitors convergence, and validates output. Follows the
validate→process→validate pattern.

CRITICAL CONSTRAINTS:
  - OGS binary must be compiled or available at specified path
  - All input files (mesh .vtu, geometry .gml, boundary submeshes) must exist
  - Project file (.prj) is XML — malformed XML crashes immediately
  - Time values in seconds, pressures in Pa, temperatures in K
  - Output VTU files named: {prefix}_ts_{timestep}_t_{time}.vtu
  - Non-zero exit code from OGS means simulation failure

Usage:
    python run_ogs.py --prj project.prj --ogs_binary ./build/bin/ogs --output_dir results/
    python run_ogs.py --prj project.prj --ogs_binary ogs --output_dir results/ --timeout 3600
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from xml.etree import ElementTree as ET


def validate_inputs(args):
    """Validate inputs before running OGS."""
    errors = []
    warnings = []

    # Check project file
    if not os.path.isfile(args.prj):
        errors.append(f"Project file not found: {args.prj}")
    else:
        # Validate XML structure
        try:
            tree = ET.parse(args.prj)
            root = tree.getroot()
            if root.tag != "OpenGeoSysProject":
                errors.append(f"Root element is '{root.tag}', expected 'OpenGeoSysProject'")

            # Check for required sections
            required_sections = ["processes", "time_loop", "parameters",
                                 "process_variables", "nonlinear_solvers", "linear_solvers"]
            for section in required_sections:
                if root.find(section) is None and root.find(f".//{section}") is None:
                    warnings.append(f"Section <{section}> not found in project file")

            # Check mesh files exist
            prj_dir = os.path.dirname(os.path.abspath(args.prj))
            mesh_dir = args.mesh_dir if args.mesh_dir else prj_dir

            # Find mesh elements
            for mesh_elem in root.iter("mesh"):
                mesh_file = mesh_elem.text.strip() if mesh_elem.text else ""
                if mesh_file:
                    mesh_path = os.path.join(mesh_dir, mesh_file)
                    if not os.path.isfile(mesh_path):
                        errors.append(f"Mesh file not found: {mesh_path}")

            # Check process type
            for proc in root.iter("process"):
                proc_type = proc.find("type")
                if proc_type is not None:
                    valid_types = [
                        "LIQUID_FLOW", "RICHARDS_FLOW", "STEADY_STATE_DIFFUSION",
                        "HEAT_CONDUCTION", "HT", "HYDRO_MECHANICS",
                        "THERMO_MECHANICS", "SMALL_DEFORMATION", "LARGE_DEFORMATION",
                        "RICHARDS_MECHANICS", "THERMO_RICHARDS_FLOW",
                        "THERMO_RICHARDS_MECHANICS", "TH2M", "COMPONENT_TRANSPORT",
                        "HEAT_TRANSPORT_BHE", "THERMO_HYDRO_MECHANICS",
                        "TWO_PHASE_FLOW_PP", "RICHARDS_COMPONENT_TRANSPORT",
                        "WELLBORE_SIMULATOR", "STOKES_FLOW",
                    ]
                    if proc_type.text and proc_type.text.strip() not in valid_types:
                        warnings.append(f"Unknown process type: {proc_type.text.strip()}")

            # Check time values are reasonable (should be in seconds)
            for t_end in root.iter("t_end"):
                if t_end.text:
                    try:
                        t_val = float(t_end.text.strip())
                        if 0 < t_val < 3600:
                            warnings.append(
                                f"t_end = {t_val} s ({t_val/3600:.2f} hrs) — "
                                f"very short. Did you forget to convert days→seconds? "
                                f"(1 day = 86400 s)"
                            )
                    except ValueError:
                        pass

            # Check for zero storage in transient problems
            for prop in root.iter("property"):
                name_elem = prop.find("name")
                value_elem = prop.find("value")
                if (name_elem is not None and value_elem is not None
                        and name_elem.text and name_elem.text.strip() == "storage"):
                    try:
                        if float(value_elem.text.strip()) == 0.0:
                            warnings.append(
                                "storage = 0.0 — transient simulation will have no temporal evolution. "
                                "Set to ~1e-9 1/Pa for confined aquifer."
                            )
                    except (ValueError, AttributeError):
                        pass

        except ET.ParseError as e:
            errors.append(f"XML parse error in project file: {e}")

    # Check OGS binary
    if args.ogs_binary:
        # Check if it's an absolute path or in PATH
        if os.path.isabs(args.ogs_binary):
            if not os.path.isfile(args.ogs_binary):
                errors.append(f"OGS binary not found: {args.ogs_binary}")
            elif not os.access(args.ogs_binary, os.X_OK):
                errors.append(f"OGS binary not executable: {args.ogs_binary}")
        else:
            # Check if in PATH
            result = subprocess.run(["which", args.ogs_binary],
                                    capture_output=True, text=True)
            if result.returncode != 0:
                errors.append(f"OGS binary '{args.ogs_binary}' not found in PATH")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return warnings


def run_simulation(args, preflight_warnings):
    """Execute OGS simulation and capture output."""
    warnings = list(preflight_warnings)

    # Prepare output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Build command
    cmd = [args.ogs_binary, args.prj, "-o", args.output_dir]

    if args.mesh_dir:
        cmd.extend(["-m", args.mesh_dir])

    if args.log_level:
        cmd.extend(["-l", args.log_level])

    # Run OGS
    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            cwd=os.path.dirname(os.path.abspath(args.prj)) or ".",
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "command": " ".join(cmd),
            "timeout_seconds": args.timeout,
            "warnings": warnings,
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "errors": [f"OGS binary not found: {args.ogs_binary}"],
            "warnings": warnings,
        }

    elapsed = time.time() - start_time

    # Parse OGS log output
    stdout = proc.stdout
    stderr = proc.stderr
    log_text = stdout + "\n" + stderr

    # Check for convergence issues
    nonlinear_iterations = re.findall(r"Iteration #(\d+)", log_text)
    convergence_failures = re.findall(r"[Nn]onlinear solver.*diverge|[Nn]ot converged", log_text)
    nan_errors = re.findall(r"[Nn][Aa][Nn]|nan|inf\b", log_text)
    timestep_count = len(re.findall(r"=== Time stepping.*===|time step.*\d+", log_text, re.IGNORECASE))

    if convergence_failures:
        warnings.append(f"Convergence failures detected: {len(convergence_failures)} occurrences")
    if nan_errors:
        warnings.append(f"NaN/Inf detected in output: {len(nan_errors)} occurrences")

    # Find output files
    output_vtus = sorted(glob.glob(os.path.join(args.output_dir, "*.vtu")))
    output_pvds = sorted(glob.glob(os.path.join(args.output_dir, "*.pvd")))

    if proc.returncode != 0 and not output_vtus:
        return {
            "status": "error",
            "command": " ".join(cmd),
            "return_code": proc.returncode,
            "elapsed_seconds": elapsed,
            "stdout_tail": stdout[-2000:] if stdout else "",
            "stderr_tail": stderr[-2000:] if stderr else "",
            "errors": [f"OGS exited with code {proc.returncode}"],
            "warnings": warnings,
        }

    # Parse timesteps from output file names
    timesteps = []
    for vtu in output_vtus:
        match = re.search(r"_ts_(\d+)_t_([\d.eE+-]+)\.vtu", vtu)
        if match:
            timesteps.append({
                "step": int(match.group(1)),
                "time_s": float(match.group(2)),
                "file": vtu,
            })

    result = {
        "status": "success" if proc.returncode == 0 else "completed_with_errors",
        "command": " ".join(cmd),
        "return_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "output_dir": args.output_dir,
        "n_vtu_files": len(output_vtus),
        "n_pvd_files": len(output_pvds),
        "pvd_file": output_pvds[0] if output_pvds else None,
        "timesteps": timesteps[:10],  # First 10 for summary
        "total_timesteps": len(timesteps),
        "max_nonlinear_iterations": max([int(x) for x in nonlinear_iterations]) if nonlinear_iterations else 0,
        "stdout_head": stdout[:500] if stdout else "",
        "stderr_head": stderr[:500] if stderr else "",
        "warnings": warnings,
    }

    return result


def validate_outputs(result):
    """Validate simulation outputs."""
    if result["status"] not in ("success", "completed_with_errors"):
        return result

    warnings = result.get("warnings", [])

    if result["n_vtu_files"] == 0:
        warnings.append("No VTU output files generated — simulation may have failed silently")
        result["status"] = "error"

    if result["total_timesteps"] <= 1:
        warnings.append("Only initial condition output — no time evolution computed")

    if result["max_nonlinear_iterations"] >= 10:
        warnings.append(
            f"Max nonlinear iterations = {result['max_nonlinear_iterations']} — "
            "near divergence. Consider reducing timestep or switching solver."
        )

    if result["elapsed_seconds"] > 300:
        warnings.append(f"Simulation took {result['elapsed_seconds']:.0f}s — may need optimization")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run OpenGeoSys simulation with preflight checks and output validation"
    )
    parser.add_argument("--prj", type=str, required=True, help="Path to OGS project file (.prj)")
    parser.add_argument("--ogs_binary", type=str, default="ogs", help="Path to OGS binary (default: 'ogs' in PATH)")
    parser.add_argument("--output_dir", type=str, required=True, help="Output directory for results")
    parser.add_argument("--mesh_dir", type=str, default=None, help="Directory containing mesh files")
    parser.add_argument("--log_level", type=str, default=None, help="Log level (debug, info, warn, error)")
    parser.add_argument("--timeout", type=int, default=7200, help="Timeout in seconds (default 7200)")

    args = parser.parse_args()

    preflight_warnings = validate_inputs(args)
    result = run_simulation(args, preflight_warnings)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)

    # Write summary
    summary_path = os.path.join(args.output_dir, "run_summary.json")
    os.makedirs(args.output_dir, exist_ok=True)
    with open(summary_path, "w") as f:
        f.write(output_json)

    print(f"Summary written to {summary_path}", file=sys.stderr)
    print(output_json)


if __name__ == "__main__":
    main()
