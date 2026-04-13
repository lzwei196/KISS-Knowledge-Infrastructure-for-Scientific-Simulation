#!/usr/bin/env python3
"""
generate_nodes.py
=================
Generate computational node discretization from soil horizon depths using
the nlayer_gen algorithm (RZWQM's built-in half-way rule).

The algorithm places nodes at increasing spacing with depth, constrained to
align with horizon boundaries. Maximum node count is 300 (MAXNOD).

Uses nlayer_gen() and write_soil_node_to_dat() from rzwqm_file.py.

Inputs:
    project_path    - RZWQM2 project root path
    station_id      - Station or grid identifier
    horizon_depths  - Comma-separated list of horizon depths in cm (ascending)
                      e.g., "15,30,60,100,200"

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
PROJECT_PATH = ""       # RZWQM2 project root path
STATION_ID = ""         # Station or grid identifier
HORIZON_DEPTHS = ""     # Comma-separated horizon depths in cm

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))

MAXNOD = 300


def validate_inputs(project_path, station_id, horizon_depths_raw):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not project_path:
        errors.append("PROJECT_PATH is required.")
    elif not os.path.isdir(project_path):
        errors.append(f"PROJECT_PATH does not exist: {project_path}")

    if not station_id:
        errors.append("STATION_ID is required.")

    if not horizon_depths_raw:
        errors.append("HORIZON_DEPTHS is required (comma-separated depths in cm).")

    # Parse horizon depths
    depths = []
    if horizon_depths_raw:
        try:
            depths = [float(d.strip()) for d in horizon_depths_raw.split(',')]
        except ValueError:
            errors.append(f"HORIZON_DEPTHS must be comma-separated numbers, got: {horizon_depths_raw}")

    if depths:
        # Check ascending order
        for i in range(1, len(depths)):
            if depths[i] <= depths[i - 1]:
                errors.append(
                    f"Horizon depths must be in ascending order. "
                    f"depth[{i}]={depths[i]} <= depth[{i-1}]={depths[i-1]}"
                )
                break

        # Check maximum depth
        if depths[-1] > 3000:
            errors.append(f"Maximum horizon depth is 3000 cm, got: {depths[-1]}")

        # Check minimum spacing
        for i in range(1, len(depths)):
            if depths[i] - depths[i - 1] < 2:
                errors.append(
                    f"Horizons too close: depth[{i}]={depths[i]} - depth[{i-1}]={depths[i-1]} "
                    f"= {depths[i] - depths[i-1]} cm (minimum ~2 cm for node generation)."
                )

    # Check RZWQM.dat exists
    dat_path = None
    if project_path and station_id:
        dat_path = os.path.join(project_path, station_id, 'RZWQM.dat')
        if not os.path.isfile(dat_path):
            alt_path = os.path.join(project_path, station_id, 'rzwqm.dat')
            if os.path.isfile(alt_path):
                dat_path = alt_path
            else:
                errors.append(f"RZWQM.dat not found: {dat_path}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'project_path': project_path,
        'station_id': station_id,
        'horizon_depths': depths,
        'dat_path': dat_path
    }


def process(args):
    """
    Generate nodes and write to RZWQM.dat.
    Returns (success, error_msg, summary).
    """
    from rzwqm_file import RZWQM

    project_path = args['project_path']
    station_id = args['station_id']
    horizon_depths = args['horizon_depths']

    try:
        rz = RZWQM(project_path, station_id)

        # Generate node data using nlayer_gen algorithm
        node_data = rz.generate_node_data(horizon_depths)

        if not node_data:
            return False, (
                "nlayer_gen failed: could not generate valid node discretization. "
                "Try adjusting horizon depths (merge thin horizons or reduce total depth)."
            ), None

        num_nodes = len(node_data)
        if num_nodes > MAXNOD:
            return False, (
                f"Too many nodes generated ({num_nodes} > MAXNOD={MAXNOD}). "
                f"Reduce the number of horizons or increase spacing."
            ), None

        # Write nodes to RZWQM.dat
        rz.write_soil_node_to_dat(node_data)

        # Extract node depths for summary
        node_depths = [entry[1] for entry in node_data]

        summary = {
            'num_nodes': num_nodes,
            'num_horizons': len(horizon_depths),
            'horizon_depths_cm': horizon_depths,
            'min_node_spacing': round(min(entry[2] for entry in node_data), 2),
            'max_node_spacing': round(max(entry[2] for entry in node_data), 2),
            'deepest_node_cm': node_depths[-1] if node_depths else 0
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(args):
    """Verify that nodes were written correctly."""
    from rzwqm_file import RZWQM

    errors = []

    try:
        rz = RZWQM(args['project_path'], args['station_id'])
        nodes = rz.parse_soil_discretization_nodes()

        if not nodes:
            errors.append("No nodes found in RZWQM.dat after write.")

        if len(nodes) > MAXNOD:
            errors.append(f"Node count {len(nodes)} exceeds MAXNOD={MAXNOD}.")

        # Check that horizon boundaries are represented in the node list
        for depth in args['horizon_depths']:
            depth_int = int(depth)
            if depth_int not in nodes:
                # Allow small deviations from nlayer_gen adjustments
                close = any(abs(n - depth_int) <= 2 for n in nodes)
                if not close:
                    errors.append(
                        f"Horizon boundary {depth} cm not found in node list."
                    )

    except Exception as e:
        errors.append(f"Could not verify outputs: {e}")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    project_path = sys.argv[1] if len(sys.argv) > 1 else PROJECT_PATH
    station_id = sys.argv[2] if len(sys.argv) > 2 else STATION_ID
    horizon_depths_raw = sys.argv[3] if len(sys.argv) > 3 else HORIZON_DEPTHS

    # Ensure project_path ends with separator for RZWQM class compatibility
    if project_path and not project_path.endswith(('/', '\\')):
        project_path = project_path + '/'

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(project_path, station_id, horizon_depths_raw)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(args)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "dat_file": args['dat_path'],
        "summary": summary,
        "message": (
            f"Node discretization complete. {summary['num_nodes']} nodes generated "
            f"for {summary['num_horizons']} horizons. "
            f"Node spacing: {summary['min_node_spacing']}-{summary['max_node_spacing']} cm."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
