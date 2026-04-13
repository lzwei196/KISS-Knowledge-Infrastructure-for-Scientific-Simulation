#!/usr/bin/env python3
"""
Generate OpenFOAM mesh from domain parameters using blockMesh.

Creates system/blockMeshDict from domain extents, resolution, and boundary
patch definitions. Optionally runs blockMesh and checkMesh.

CRITICAL: The convertToMeters factor is applied to ALL vertex coordinates.
          If vertices are in meters, use 1. If in mm, use 0.001.
          Getting this wrong silently scales the entire domain.

CRITICAL: Patch names defined here must EXACTLY match those used in 0/U,
          0/p, and other boundary condition files. Case-sensitive.

CRITICAL: For 2D simulations, the thin direction patches must be type
          'empty'. Forgetting this causes OpenFOAM to treat 2D as 3D.

Usage:
    python generate_mesh.py \\
        --case-dir ./myCase \\
        --x-range 0 1 \\
        --y-range 0 0.1 \\
        --z-range 0 0.01 \\
        --nx 100 --ny 20 --nz 1 \\
        --convert-to-meters 1 \\
        --patches inlet:patch,outlet:patch,walls:wall,frontAndBack:empty \\
        --run-blockmesh \\
        --output result.json
"""

import argparse
import json
import os
import subprocess
import sys


FOAM_HEADER = """FoamFile
{{
    format      ascii;
    class       dictionary;
    location    "system";
    object      blockMeshDict;
}}"""


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.x_range[0] >= args.x_range[1]:
        errors.append(f"x_range: min ({args.x_range[0]}) must be < max ({args.x_range[1]})")
    if args.y_range[0] >= args.y_range[1]:
        errors.append(f"y_range: min ({args.y_range[0]}) must be < max ({args.y_range[1]})")
    if args.z_range[0] >= args.z_range[1]:
        errors.append(f"z_range: min ({args.z_range[0]}) must be < max ({args.z_range[1]})")

    if args.nx < 1 or args.ny < 1 or args.nz < 1:
        errors.append("Cell counts (nx, ny, nz) must be >= 1")

    if args.convert_to_meters <= 0:
        errors.append(f"convertToMeters must be > 0, got {args.convert_to_meters}")

    # Check for 2D case: nz=1 should have empty patches
    if args.nz == 1 and args.patches:
        patch_types = dict(p.split(":") for p in args.patches.split(",") if ":" in p)
        has_empty = any(v == "empty" for v in patch_types.values())
        if not has_empty:
            errors.append(
                "nz=1 (2D case) but no 'empty' patch type defined. "
                "The thin direction patches MUST be type 'empty'. "
                "Add e.g. frontAndBack:empty"
            )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def generate_block_mesh_dict(args):
    """Generate blockMeshDict content string."""
    x0, x1 = args.x_range
    y0, y1 = args.y_range
    z0, z1 = args.z_range

    # Parse patches
    patches = {}
    if args.patches:
        for entry in args.patches.split(","):
            name, ptype = entry.strip().split(":")
            patches[name.strip()] = ptype.strip()
    else:
        # Default patches
        patches = {
            "inlet": "patch",
            "outlet": "patch",
            "walls": "wall",
            "frontAndBack": "empty",
        }

    # Vertices for hex block (8 vertices)
    vertices = [
        (x0, y0, z0),  # 0
        (x1, y0, z0),  # 1
        (x1, y1, z0),  # 2
        (x0, y1, z0),  # 3
        (x0, y0, z1),  # 4
        (x1, y0, z1),  # 5
        (x1, y1, z1),  # 6
        (x0, y1, z1),  # 7
    ]

    # Default face assignments for a single hex block
    # Face vertex ordering follows OpenFOAM convention
    face_map = {
        "inlet": [(0, 4, 7, 3)],       # x-min face
        "outlet": [(2, 6, 5, 1)],       # x-max face
        "walls": [(3, 7, 6, 2), (1, 5, 4, 0)],  # y-max and y-min
        "frontAndBack": [(0, 3, 2, 1), (4, 5, 6, 7)],  # z-min and z-max
    }

    # Build content
    header = FOAM_HEADER.format()

    vert_str = "\n".join(f"    ({v[0]} {v[1]} {v[2]})" for v in vertices)

    grading = f"simpleGrading ({args.grading_x} {args.grading_y} {args.grading_z})"

    patch_blocks = []
    for name, ptype in patches.items():
        faces = face_map.get(name, [])
        face_strs = "\n".join(
            f"            ({' '.join(str(i) for i in face)})"
            for face in faces
        )
        patch_blocks.append(f"""    {name}
    {{
        type {ptype};
        faces
        (
{face_strs}
        );
    }}""")

    content = f"""{header}

convertToMeters {args.convert_to_meters};

vertices
(
{vert_str}
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({args.nx} {args.ny} {args.nz}) {grading}
);

boundary
(
{chr(10).join(patch_blocks)}
);
"""
    return content


def write_block_mesh_dict(case_dir, content):
    """Write blockMeshDict to system/ directory."""
    filepath = os.path.join(case_dir, "system", "blockMeshDict")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def run_blockmesh(case_dir, foam_bashrc=None):
    """Run blockMesh utility."""
    env = os.environ.copy()
    if foam_bashrc and os.path.isfile(foam_bashrc):
        cmd = f"source {foam_bashrc} && blockMesh -case {case_dir}"
        proc = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True, text=True, timeout=120
        )
    else:
        proc = subprocess.run(
            ["blockMesh", "-case", case_dir],
            capture_output=True, text=True, env=env, timeout=120
        )
    return {
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
    }


def run_checkmesh(case_dir, foam_bashrc=None):
    """Run checkMesh utility."""
    env = os.environ.copy()
    if foam_bashrc and os.path.isfile(foam_bashrc):
        cmd = f"source {foam_bashrc} && checkMesh -case {case_dir}"
        proc = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True, text=True, timeout=120
        )
    else:
        proc = subprocess.run(
            ["checkMesh", "-case", case_dir],
            capture_output=True, text=True, env=env, timeout=120
        )
    return {
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-1000:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
    }


def process(args):
    """Generate blockMeshDict and optionally run blockMesh."""
    result = {
        "status": "success",
        "files_written": [],
        "mesh_stats": {},
        "warnings": [],
    }

    # Generate and write blockMeshDict
    content = generate_block_mesh_dict(args)
    filepath = write_block_mesh_dict(args.case_dir, content)
    result["files_written"].append(filepath)

    # Calculate mesh statistics
    dx = (args.x_range[1] - args.x_range[0]) / args.nx * args.convert_to_meters
    dy = (args.y_range[1] - args.y_range[0]) / args.ny * args.convert_to_meters
    dz = (args.z_range[1] - args.z_range[0]) / args.nz * args.convert_to_meters
    n_cells = args.nx * args.ny * args.nz

    result["mesh_stats"] = {
        "n_cells": n_cells,
        "dx_m": dx,
        "dy_m": dy,
        "dz_m": dz,
        "domain_x_m": (args.x_range[1] - args.x_range[0]) * args.convert_to_meters,
        "domain_y_m": (args.y_range[1] - args.y_range[0]) * args.convert_to_meters,
        "domain_z_m": (args.z_range[1] - args.z_range[0]) * args.convert_to_meters,
        "aspect_ratio": max(dx, dy, dz) / min(dx, dy, dz) if min(dx, dy, dz) > 0 else float("inf"),
    }

    # Aspect ratio warning
    ar = result["mesh_stats"]["aspect_ratio"]
    if ar > 20:
        result["warnings"].append(
            f"High cell aspect ratio ({ar:.1f}). "
            "May cause convergence issues. Consider adjusting resolution."
        )

    # Run blockMesh
    if args.run_blockmesh:
        bm_result = run_blockmesh(args.case_dir, args.foam_bashrc)
        result["blockMesh"] = bm_result
        if bm_result["returncode"] != 0:
            result["status"] = "error"
            result["errors"] = [f"blockMesh failed: {bm_result['stderr_tail']}"]
            return result

        # Run checkMesh
        cm_result = run_checkmesh(args.case_dir, args.foam_bashrc)
        result["checkMesh"] = cm_result

    return result


def validate_outputs(result):
    """Validate output files exist."""
    warnings = result.get("warnings", [])
    for fp in result.get("files_written", []):
        if not os.path.isfile(fp):
            warnings.append(f"Expected output file missing: {fp}")
    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate OpenFOAM blockMeshDict and run mesh generation"
    )
    parser.add_argument("--case-dir", required=True,
                        help="OpenFOAM case directory")
    parser.add_argument("--x-range", nargs=2, type=float, required=True,
                        metavar=("XMIN", "XMAX"),
                        help="X domain range")
    parser.add_argument("--y-range", nargs=2, type=float, required=True,
                        metavar=("YMIN", "YMAX"),
                        help="Y domain range")
    parser.add_argument("--z-range", nargs=2, type=float, required=True,
                        metavar=("ZMIN", "ZMAX"),
                        help="Z domain range")
    parser.add_argument("--nx", type=int, default=20,
                        help="Number of cells in X")
    parser.add_argument("--ny", type=int, default=20,
                        help="Number of cells in Y")
    parser.add_argument("--nz", type=int, default=1,
                        help="Number of cells in Z")
    parser.add_argument("--convert-to-meters", type=float, default=1.0,
                        help="Scale factor for vertex coordinates")
    parser.add_argument("--grading-x", type=float, default=1.0,
                        help="X grading ratio")
    parser.add_argument("--grading-y", type=float, default=1.0,
                        help="Y grading ratio")
    parser.add_argument("--grading-z", type=float, default=1.0,
                        help="Z grading ratio")
    parser.add_argument("--patches", default=None,
                        help="Comma-separated name:type pairs "
                             "(e.g., inlet:patch,outlet:patch,walls:wall)")
    parser.add_argument("--run-blockmesh", action="store_true",
                        help="Run blockMesh after generating dict")
    parser.add_argument("--foam-bashrc", default=None,
                        help="Path to OpenFOAM etc/bashrc")
    parser.add_argument("--output", default=None,
                        help="Output JSON summary file")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
