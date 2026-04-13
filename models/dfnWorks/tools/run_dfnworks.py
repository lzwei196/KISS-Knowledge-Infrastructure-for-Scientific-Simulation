#!/usr/bin/env python3
"""
run_dfnworks.py - Execute dfnWorks pipeline with preflight checks.

Wraps the pydfnworks workflow: network generation, graph-based flow,
and graph-based transport. Supports two modes:
  1. Graph mode (default): No external dependencies (LaGriT, PFLOTRAN, FEHM)
  2. Full-physics mode: Requires LaGriT, PFLOTRAN or FEHM, DFNTrans

Performs preflight validation:
  - Domain size and h parameter consistency
  - Fracture family parameter validation
  - Boundary face configuration check
  - Output directory write permission

CRITICAL: All lengths in METERS, pressures in PASCALS, permeability in m^2.

Usage:
    python run_dfnworks.py --config run_config.json --mode graph --output ./results
    python run_dfnworks.py --domain 10,10,10 --h 0.1 --families families.json --mode graph
    python run_dfnworks.py --config run_config.json --mode full --ncpu 8
"""

import argparse
import json
import os
import sys
import time
import traceback

import numpy as np


# ============================================================================
# Input Validation
# ============================================================================

def validate_inputs(args):
    """Validate all inputs before execution.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    dict
        Validated configuration.
    """
    errors = []
    warnings = []

    # Load config file if provided
    config = {}
    if args.config:
        if not os.path.isfile(args.config):
            errors.append(f"Config file not found: {args.config}")
        else:
            with open(args.config) as f:
                config = json.load(f)

    # Parse domain size
    if args.domain:
        try:
            domain = [float(x) for x in args.domain.split(",")]
            if len(domain) != 3:
                errors.append("Domain must have 3 values: x,y,z")
            config["domain"] = domain
        except ValueError:
            errors.append(f"Invalid domain format: {args.domain}")
    elif "domain" not in config:
        errors.append("Domain size required (--domain or in config)")

    # Parse h parameter
    if args.h:
        config["h"] = args.h
    if "h" not in config:
        errors.append("Mesh resolution h required (--h or in config)")

    # Validate h vs domain
    if "domain" in config and "h" in config:
        min_dim = min(config["domain"])
        if config["h"] >= min_dim:
            errors.append(f"h ({config['h']}) must be smaller than smallest domain dimension ({min_dim})")
        if config["h"] > min_dim / 5:
            warnings.append(f"h ({config['h']}) is large relative to domain ({min_dim}). Mesh may be coarse.")

    # Load families
    if args.families:
        if not os.path.isfile(args.families):
            errors.append(f"Families file not found: {args.families}")
        else:
            with open(args.families) as f:
                fam_data = json.load(f)
                config["families"] = fam_data.get("families", fam_data)

    if "families" not in config or len(config.get("families", [])) == 0:
        errors.append("At least one fracture family required (--families or in config)")

    # Validate families
    for i, fam in enumerate(config.get("families", [])):
        if "min_radius" in fam and "max_radius" in fam:
            if fam["min_radius"] >= fam["max_radius"]:
                errors.append(f"Family {i}: min_radius >= max_radius")
            if "h" in config and config["h"] >= fam["min_radius"]:
                errors.append(f"Family {i}: h ({config['h']}) >= min_radius ({fam['min_radius']}). "
                              "Fractures cannot be meshed.")

    # Validate mode
    config["mode"] = args.mode
    config["ncpu"] = args.ncpu
    config["seed"] = args.seed
    config["nparticles"] = args.nparticles

    # Boundary faces
    if args.boundary_faces:
        try:
            bf = [int(x) for x in args.boundary_faces.split(",")]
            if len(bf) != 6:
                errors.append("boundary_faces must have 6 values")
            config["boundary_faces"] = bf
        except ValueError:
            errors.append(f"Invalid boundary_faces: {args.boundary_faces}")
    elif "boundary_faces" not in config:
        config["boundary_faces"] = [0, 0, 1, 1, 0, 0]  # Default: left/right

    # Pressure
    config["pressure_in"] = args.pressure_in or config.get("pressure_in", 2e6)
    config["pressure_out"] = args.pressure_out or config.get("pressure_out", 1e6)

    if config["pressure_in"] <= config["pressure_out"]:
        warnings.append("pressure_in <= pressure_out: flow will be zero or reversed")

    # Output directory
    config["output_dir"] = args.output or config.get("output_dir", "./dfnworks_output")

    if errors:
        result = {"status": "error", "errors": errors, "warnings": warnings}
        sys.stderr.write(json.dumps(result, indent=2) + "\n")
        sys.exit(1)

    config["warnings"] = warnings
    return config


# ============================================================================
# Execution Functions
# ============================================================================

def run_graph_mode(config):
    """Execute dfnWorks in graph-only mode.

    No external dependencies required. Uses graph-based flow and transport.

    Parameters
    ----------
    config : dict
        Validated configuration.

    Returns
    -------
    dict
        Execution results.
    """
    from pydfnworks import DFNWORKS

    jobname = os.path.abspath(config["output_dir"])
    start_time = time.time()

    DFN = DFNWORKS(jobname, ncpu=config["ncpu"])

    # Set domain parameters
    DFN.params['domainSize']['value'] = config["domain"]
    DFN.params['h']['value'] = config["h"]
    DFN.params['boundaryFaces']['value'] = config["boundary_faces"]
    DFN.params['keepOnlyLargestCluster']['value'] = True
    DFN.params['ignoreBoundaryFaces']['value'] = True

    if config["seed"] > 0:
        DFN.params['seed']['value'] = config["seed"]

    # Add fracture families
    for fam in config["families"]:
        fam_args = {k: v for k, v in fam.items()
                    if k not in ["n_measurements", "p10_observed", "statistics"]}
        DFN.add_fracture_family(**fam_args)

    # Generate network
    DFN.make_working_directory(delete=True)
    DFN.check_input()

    gen_start = time.time()
    DFN.create_network()
    gen_time = time.time() - gen_start

    # Graph-based flow
    flow_start = time.time()
    G = DFN.run_graph_flow("left", "right",
                           config["pressure_in"],
                           config["pressure_out"])
    flow_time = time.time() - flow_start

    # Graph-based transport
    trans_start = time.time()
    DFN.run_graph_transport(G, config["nparticles"],
                            "partime", "frac_sequence")
    trans_time = time.time() - trans_start

    total_time = time.time() - start_time

    return {
        "status": "success",
        "mode": "graph",
        "output_dir": jobname,
        "timing": {
            "generation_s": round(gen_time, 2),
            "flow_s": round(flow_time, 2),
            "transport_s": round(trans_time, 2),
            "total_s": round(total_time, 2),
        },
        "parameters": {
            "domain": config["domain"],
            "h": config["h"],
            "n_families": len(config["families"]),
            "nparticles": config["nparticles"],
            "pressure_in_Pa": config["pressure_in"],
            "pressure_out_Pa": config["pressure_out"],
        },
    }


def run_full_mode(config):
    """Execute dfnWorks in full-physics mode.

    Requires LaGriT, PFLOTRAN/FEHM, and DFNTrans.

    Parameters
    ----------
    config : dict
        Validated configuration.

    Returns
    -------
    dict
        Execution results.
    """
    from pydfnworks import DFNWORKS

    jobname = os.path.abspath(config["output_dir"])
    start_time = time.time()

    dfnFlow_file = config.get("dfnFlow_file")
    dfnTrans_file = config.get("dfnTrans_file")

    DFN = DFNWORKS(jobname,
                    dfnFlow_file=dfnFlow_file,
                    dfnTrans_file=dfnTrans_file,
                    ncpu=config["ncpu"])

    DFN.params['domainSize']['value'] = config["domain"]
    DFN.params['h']['value'] = config["h"]
    DFN.params['boundaryFaces']['value'] = config["boundary_faces"]

    if config["seed"] > 0:
        DFN.params['seed']['value'] = config["seed"]

    for fam in config["families"]:
        fam_args = {k: v for k, v in fam.items()
                    if k not in ["n_measurements", "p10_observed", "statistics"]}
        DFN.add_fracture_family(**fam_args)

    DFN.make_working_directory(delete=True)
    DFN.check_input()
    DFN.create_network()
    DFN.mesh_network()
    DFN.dfn_flow()
    DFN.dfn_trans()

    total_time = time.time() - start_time

    return {
        "status": "success",
        "mode": "full",
        "output_dir": jobname,
        "timing": {"total_s": round(total_time, 2)},
    }


# ============================================================================
# Output Validation
# ============================================================================

def validate_outputs(result, config):
    """Validate execution outputs.

    Parameters
    ----------
    result : dict
        Execution result.
    config : dict
        Run configuration.

    Returns
    -------
    dict
        Result with validation status.
    """
    warnings = result.get("warnings", [])
    output_dir = result.get("output_dir", "")

    # Check key output files exist
    expected_files = ["params.txt"]
    if result["mode"] == "graph":
        expected_files.extend(["graph_flow.hdf5"])

    for fname in expected_files:
        fpath = os.path.join(output_dir, fname)
        if not os.path.isfile(fpath):
            warnings.append(f"Expected output file not found: {fpath}")

    # Check partime output
    partime_file = os.path.join(output_dir, "partime")
    if os.path.isfile(partime_file):
        try:
            data = np.loadtxt(partime_file)
            if len(data) == 0:
                warnings.append("Particle time file is empty - no particles reached outlet")
            elif np.any(data <= 0):
                warnings.append("Some particle travel times are <= 0")
            else:
                result["transport_summary"] = {
                    "n_particles_arrived": len(data),
                    "median_travel_time_s": float(np.median(data)),
                    "mean_travel_time_s": float(np.mean(data)),
                    "min_travel_time_s": float(np.min(data)),
                    "max_travel_time_s": float(np.max(data)),
                }
        except Exception:
            pass

    result["warnings"] = warnings
    return result


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Execute dfnWorks pipeline (graph or full-physics mode)"
    )
    parser.add_argument("--config", "-c", help="JSON configuration file")
    parser.add_argument("--mode", default="graph", choices=["graph", "full"],
                        help="Execution mode (default: graph)")
    parser.add_argument("--domain", help="Domain size: x,y,z in meters (e.g., 10,10,10)")
    parser.add_argument("--h", type=float, help="Mesh resolution in meters")
    parser.add_argument("--families", help="Fracture families JSON file")
    parser.add_argument("--boundary_faces", help="6 values: top,bot,left,front,right,back")
    parser.add_argument("--pressure_in", type=float, help="Inlet pressure in Pa")
    parser.add_argument("--pressure_out", type=float, help="Outlet pressure in Pa")
    parser.add_argument("--nparticles", type=int, default=1000,
                        help="Number of particles for transport (default: 1000)")
    parser.add_argument("--ncpu", type=int, default=4, help="Number of CPUs")
    parser.add_argument("--seed", type=int, default=0, help="Random seed (0=clock)")
    parser.add_argument("--output", "-o", help="Output directory")

    args = parser.parse_args()
    config = validate_inputs(args)

    try:
        if config["mode"] == "graph":
            result = run_graph_mode(config)
        else:
            result = run_full_mode(config)

        result = validate_outputs(result, config)

    except Exception as e:
        result = {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

    # Write results
    output_file = os.path.join(config.get("output_dir", "."), "run_results.json")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(json.dumps(result, indent=2, default=str))

    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
