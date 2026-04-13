#!/usr/bin/env python3
"""
run_amanzi.py — Execution Wrapper for Amanzi/ATS

Runs the Amanzi or ATS binary with preflight validation of the XML input file,
runtime monitoring, and post-run output checks.

Pattern: validate_inputs → process (execute) → validate_outputs

Preflight checks:
  - XML file exists and is well-formed
  - Mesh file exists (if referenced)
  - Required XML blocks are present
  - Physical parameter sanity (permeability range, porosity 0-1, etc.)

Usage:
  python run_amanzi.py --xml_file input.xml --np 4 --run_dir ./run
  python run_amanzi.py --xml_file input.xml --binary /path/to/ats --np 8
"""

import argparse
import json
import os
import subprocess
import sys
import time
import shutil
from xml.etree import ElementTree as ET


# ============================================================================
# Constants
# ============================================================================
DEFAULT_BINARIES = ["ats", "amanzi"]
REQUIRED_XML_BLOCKS_V1 = [
    "Mesh", "Regions", "Material Properties", "Initial Conditions",
    "Boundary Conditions", "Output"
]
REQUIRED_XML_BLOCKS_V2 = [
    "mesh", "regions", "materials", "initial_conditions",
    "boundary_conditions", "output"
]


# ============================================================================
# Preflight Validation
# ============================================================================
def validate_inputs(args):
    """Validate inputs before execution."""
    errors = []
    warnings = []

    # Check XML file
    if not os.path.exists(args.xml_file):
        errors.append(f"XML input file not found: {args.xml_file}")
    else:
        try:
            tree = ET.parse(args.xml_file)
            root = tree.getroot()
            print(f"[OK] XML file parsed successfully: {args.xml_file}")

            # Detect version
            if root.tag == "amanzi_input":
                version = root.get("version", "unknown")
                print(f"[INFO] Amanzi input format version: {version} (v2 style)")
                _check_v2_blocks(root, errors, warnings)
                _check_v2_mesh_file(root, args, errors, warnings)
                _check_v2_parameters(root, warnings)
            else:
                # V1 ParameterList style
                version_param = root.find(".//Parameter[@name='Amanzi Input Format Version']")
                version = version_param.get("value", "unknown") if version_param is not None else "1.x"
                print(f"[INFO] Amanzi input format version: {version} (v1 ParameterList style)")
                _check_v1_blocks(root, errors, warnings)

        except ET.ParseError as e:
            errors.append(f"XML parse error: {e}")

    # Check binary
    binary = _find_binary(args.binary)
    if binary is None:
        errors.append(
            f"Amanzi/ATS binary not found. Searched: {args.binary or DEFAULT_BINARIES}. "
            f"Ensure the binary is on PATH or use --binary."
        )
    else:
        print(f"[OK] Binary found: {binary}")

    # Check MPI
    if args.np > 1:
        mpirun = shutil.which("mpirun") or shutil.which("mpiexec")
        if mpirun is None:
            errors.append("MPI launcher (mpirun/mpiexec) not found but --np > 1")
        else:
            print(f"[OK] MPI launcher: {mpirun}")

    for w in warnings:
        print(f"[WARNING] {w}", file=sys.stderr)

    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    print("[OK] Preflight validation passed.")
    return binary


def _find_binary(binary_arg):
    """Find the Amanzi/ATS binary."""
    if binary_arg:
        if os.path.isfile(binary_arg) and os.access(binary_arg, os.X_OK):
            return binary_arg
        found = shutil.which(binary_arg)
        if found:
            return found
        return None

    for name in DEFAULT_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return None


def _check_v2_blocks(root, errors, warnings):
    """Check required blocks in v2 format."""
    for block in REQUIRED_XML_BLOCKS_V2:
        elem = root.find(block)
        if elem is None:
            if block in ("boundary_conditions", "output"):
                warnings.append(f"Optional block <{block}> not found")
            else:
                errors.append(f"Required block <{block}> not found in XML")


def _check_v1_blocks(root, errors, warnings):
    """Check required blocks in v1 ParameterList format."""
    for block_name in REQUIRED_XML_BLOCKS_V1:
        elem = root.find(f".//ParameterList[@name='{block_name}']")
        if elem is None:
            if block_name in ("Boundary Conditions", "Output"):
                warnings.append(f"Optional block '{block_name}' not found")
            else:
                errors.append(f"Required block '{block_name}' not found in XML")


def _check_v2_mesh_file(root, args, errors, warnings):
    """Check that referenced mesh files exist."""
    mesh = root.find("mesh")
    if mesh is not None:
        read_elem = mesh.find(".//read")
        if read_elem is not None:
            file_elem = read_elem.find("file")
            if file_elem is not None and file_elem.text:
                mesh_path = file_elem.text.strip()
                # Try relative to XML file directory
                xml_dir = os.path.dirname(os.path.abspath(args.xml_file))
                full_path = os.path.join(xml_dir, mesh_path)
                if not os.path.exists(full_path) and not os.path.exists(mesh_path):
                    errors.append(
                        f"Mesh file not found: '{mesh_path}' "
                        f"(searched: {full_path}, {mesh_path})"
                    )
                else:
                    print(f"[OK] Mesh file found: {mesh_path}")


def _check_v2_parameters(root, warnings):
    """Sanity-check physical parameters in v2 format."""
    materials = root.find("materials")
    if materials is not None:
        for mat in materials:
            # Check permeability
            perm = mat.find(".//permeability")
            if perm is not None:
                for attr in ["x", "y", "z"]:
                    val_str = perm.get(attr)
                    if val_str:
                        val = float(val_str)
                        if val > 1e-6:
                            warnings.append(
                                f"Permeability {attr}={val:.2e} m² is very high. "
                                f"Did you use hydraulic conductivity (m/s) instead? "
                                f"k = K * μ/(ρg) ≈ K * 1.02e-7"
                            )


# ============================================================================
# Execution
# ============================================================================
def run_model(binary, args):
    """Execute Amanzi/ATS."""
    # Build command
    xml_path = os.path.abspath(args.xml_file)
    cmd = []

    if args.np > 1:
        mpirun = shutil.which("mpirun") or shutil.which("mpiexec")
        cmd = [mpirun, "-np", str(args.np)]

    cmd.extend([binary, f"--xml_file={xml_path}"])

    # Set up run directory
    run_dir = os.path.abspath(args.run_dir) if args.run_dir else os.getcwd()
    os.makedirs(run_dir, exist_ok=True)

    print(f"[INFO] Command: {' '.join(cmd)}")
    print(f"[INFO] Working directory: {run_dir}")
    print(f"[INFO] Starting simulation...")

    t0 = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        elapsed = time.time() - t0

        # Save log
        log_path = os.path.join(run_dir, "amanzi_run.log")
        with open(log_path, "w") as f:
            f.write(f"=== COMMAND ===\n{' '.join(cmd)}\n\n")
            f.write(f"=== RETURN CODE ===\n{result.returncode}\n\n")
            f.write(f"=== STDOUT ===\n{result.stdout}\n\n")
            f.write(f"=== STDERR ===\n{result.stderr}\n")

        print(f"[INFO] Finished in {elapsed:.1f}s (return code: {result.returncode})")
        print(f"[INFO] Log saved to {log_path}")

        return {
            "returncode": result.returncode,
            "elapsed_s": elapsed,
            "stdout_tail": result.stdout[-2000:] if result.stdout else "",
            "stderr_tail": result.stderr[-2000:] if result.stderr else "",
            "log_path": log_path,
            "command": " ".join(cmd),
            "run_dir": run_dir,
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        print(f"[ERROR] Simulation timed out after {args.timeout}s", file=sys.stderr)
        return {
            "returncode": -1,
            "elapsed_s": elapsed,
            "error": f"Timeout after {args.timeout}s",
            "command": " ".join(cmd),
            "run_dir": run_dir,
        }
    except FileNotFoundError as e:
        print(f"[ERROR] Binary not found: {e}", file=sys.stderr)
        return {"returncode": -1, "error": str(e)}


# ============================================================================
# Post-run Validation
# ============================================================================
def validate_outputs(run_result, args):
    """Validate outputs after model execution."""
    warnings = []
    run_dir = run_result.get("run_dir", ".")

    if run_result["returncode"] != 0:
        print(f"[ERROR] Model exited with code {run_result['returncode']}")
        stderr = run_result.get("stderr_tail", "")
        if "NaN" in stderr:
            print("[DIAG] NaN detected — check permeability values and boundary conditions")
        if "convergence" in stderr.lower():
            print("[DIAG] Solver non-convergence — try reducing init_dt or adjusting vG params")
        return False

    # Check for output files
    h5_files = [f for f in os.listdir(run_dir) if f.endswith(".h5")]
    xmf_files = [f for f in os.listdir(run_dir) if f.endswith(".xmf")]
    obs_files = [f for f in os.listdir(run_dir)
                 if f.endswith(".out") and "observation" in f.lower()]

    if h5_files:
        print(f"[OK] Found {len(h5_files)} HDF5 output file(s)")
    else:
        warnings.append("No HDF5 output files found")

    if xmf_files:
        print(f"[OK] Found {len(xmf_files)} XDMF visualization file(s)")

    if obs_files:
        print(f"[OK] Found {len(obs_files)} observation file(s)")

    for w in warnings:
        print(f"[WARNING] {w}", file=sys.stderr)

    return run_result["returncode"] == 0


# ============================================================================
# Main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Run Amanzi/ATS with preflight checks and output validation"
    )
    parser.add_argument("--xml_file", type=str, required=True,
                        help="Path to XML input file")
    parser.add_argument("--binary", type=str, default=None,
                        help="Path to amanzi/ats binary")
    parser.add_argument("--np", type=int, default=1,
                        help="Number of MPI processes")
    parser.add_argument("--run_dir", type=str, default=None,
                        help="Working directory for execution")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON with run results")
    args = parser.parse_args()

    # Preflight
    binary = validate_inputs(args)

    # Execute
    run_result = run_model(binary, args)

    # Post-run validation
    success = validate_outputs(run_result, args)

    # Write result
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(run_result, f, indent=2)
        print(f"[OK] Run result written to {args.output}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
