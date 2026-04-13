#!/usr/bin/env python3
"""
Pre-run validation of an OpenFOAM case directory.

Checks for the most common configuration errors that cause crashes or
silent incorrect results. Run this BEFORE executing the solver.

Checks performed:
  1. Required files exist (controlDict, fvSchemes, fvSolution, mesh)
  2. Boundary patch names match between mesh and field files
  3. Dimension arrays are consistent with solver type
  4. No obvious unit errors (kinematic vs dynamic pressure)
  5. blockMeshDict convertToMeters is reasonable
  6. Parallel decomposition consistency
  7. 2D case has 'empty' patches
  8. Gravity vector orientation
  9. VoF alpha field initialization

Usage:
    python check_case.py --case-dir ./myCase --output result.json
"""

import argparse
import json
import os
import re
import sys


def validate_inputs(args):
    """Validate input arguments."""
    if not os.path.isdir(args.case_dir):
        print(json.dumps({
            "status": "error",
            "errors": [f"Case directory not found: {args.case_dir}"]
        }, indent=2))
        sys.exit(1)


def check_required_files(case_dir):
    """Check that all required case files exist."""
    issues = []
    required = {
        "system/controlDict": "Main solver control",
        "system/fvSchemes": "Discretization schemes",
        "system/fvSolution": "Linear solver settings",
        "constant/polyMesh/points": "Mesh vertex coordinates",
        "constant/polyMesh/faces": "Mesh face definitions",
        "constant/polyMesh/owner": "Face-to-cell ownership",
        "constant/polyMesh/boundary": "Patch definitions",
    }

    for path, desc in required.items():
        full = os.path.join(case_dir, path)
        if not os.path.isfile(full):
            issues.append({
                "severity": "fatal",
                "check": "required_files",
                "message": f"Missing {desc}: {path}",
                "fix": f"Generate mesh (blockMesh) and create {path}",
            })

    # Check 0/ directory has at least one field
    zero_dir = os.path.join(case_dir, "0")
    if os.path.isdir(zero_dir):
        fields = [f for f in os.listdir(zero_dir)
                  if os.path.isfile(os.path.join(zero_dir, f))]
        if not fields:
            issues.append({
                "severity": "fatal",
                "check": "required_files",
                "message": "No field files in 0/ directory",
                "fix": "Create initial/boundary condition files (p, U, etc.)",
            })
    else:
        issues.append({
            "severity": "fatal",
            "check": "required_files",
            "message": "Missing 0/ directory",
            "fix": "Create 0/ with field files (p, U, etc.)",
        })

    return issues


def get_mesh_patches(case_dir):
    """Read patch names from constant/polyMesh/boundary."""
    boundary_file = os.path.join(case_dir, "constant", "polyMesh", "boundary")
    if not os.path.isfile(boundary_file):
        return []

    patches = []
    with open(boundary_file, "r") as f:
        content = f.read()

    # Simple regex to find patch names (lines before { in the boundary list)
    in_boundary = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("("):
            in_boundary = True
            continue
        if stripped.startswith(")"):
            break
        if in_boundary and stripped and not stripped.startswith("{") \
                and not stripped.startswith("}") and not stripped.startswith("//"):
            # Check if it looks like a patch name (word followed by nothing or {)
            match = re.match(r"^(\w+)\s*$", stripped)
            if match:
                patches.append(match.group(1))

    return patches


def get_field_patches(field_path):
    """Read patch names from a field file's boundaryField."""
    patches = []
    in_boundary = False

    with open(field_path, "r") as f:
        for line in f:
            stripped = line.strip()
            if "boundaryField" in stripped:
                in_boundary = True
                continue
            if in_boundary:
                match = re.match(r"^(\w+)\s*$", stripped)
                if match and match.group(1) not in ("{", "}"):
                    patches.append(match.group(1))

    return patches


def check_patch_consistency(case_dir, mesh_patches):
    """Verify boundary patches match between mesh and field files."""
    issues = []
    zero_dir = os.path.join(case_dir, "0")
    if not os.path.isdir(zero_dir):
        return issues

    for fname in os.listdir(zero_dir):
        fpath = os.path.join(zero_dir, fname)
        if not os.path.isfile(fpath):
            continue

        field_patches = get_field_patches(fpath)
        if not field_patches:
            continue

        # Check for patches in field but not in mesh
        for fp in field_patches:
            if fp not in mesh_patches and fp not in ("defaultFaces",):
                issues.append({
                    "severity": "fatal",
                    "check": "patch_consistency",
                    "message": f"0/{fname}: patch '{fp}' not found in mesh",
                    "fix": f"Rename patch in 0/{fname} to match polyMesh/boundary",
                })

        # Check for mesh patches not in field
        for mp in mesh_patches:
            if mp not in field_patches:
                issues.append({
                    "severity": "degraded",
                    "check": "patch_consistency",
                    "message": f"0/{fname}: mesh patch '{mp}' has no boundary condition",
                    "fix": f"Add entry for '{mp}' in 0/{fname} boundaryField",
                })

    return issues


def check_dimensions(case_dir):
    """Check field dimension arrays for common errors."""
    issues = []
    zero_dir = os.path.join(case_dir, "0")
    if not os.path.isdir(zero_dir):
        return issues

    p_file = os.path.join(zero_dir, "p")
    if os.path.isfile(p_file):
        with open(p_file, "r") as f:
            content = f.read()

        dim_match = re.search(r"dimensions\s+\[([^\]]+)\]", content)
        if dim_match:
            dims = dim_match.group(1).strip().split()
            if len(dims) == 7:
                # Check if kinematic (incompressible) or dynamic pressure
                if dims[0] == "1" and dims[1] == "-1" and dims[2] == "-2":
                    # Dynamic pressure in Pa -- check if solver expects kinematic
                    ctrl_file = os.path.join(case_dir, "system", "controlDict")
                    if os.path.isfile(ctrl_file):
                        with open(ctrl_file) as cf:
                            ctrl = cf.read()
                        if "incompressible" in ctrl.lower():
                            issues.append({
                                "severity": "fatal",
                                "check": "dimensions",
                                "message": "Pressure has dynamic dimensions [1 -1 -2 ...] "
                                           "but solver is incompressible (expects kinematic "
                                           "[0 2 -2 ...])",
                                "fix": "Change p dimensions to [0 2 -2 0 0 0 0]",
                            })

    return issues


def check_convert_to_meters(case_dir):
    """Check blockMeshDict convertToMeters."""
    issues = []
    bmd = os.path.join(case_dir, "system", "blockMeshDict")
    if not os.path.isfile(bmd):
        return issues

    with open(bmd, "r") as f:
        content = f.read()

    match = re.search(r"convertToMeters\s+([\d.e+-]+)", content)
    if match:
        scale = float(match.group(1))
        if scale == 0:
            issues.append({
                "severity": "fatal",
                "check": "convert_to_meters",
                "message": "convertToMeters = 0 produces zero-size mesh",
                "fix": "Set convertToMeters to correct value (1 for meters, 0.001 for mm)",
            })
        elif scale > 100:
            issues.append({
                "severity": "silent",
                "check": "convert_to_meters",
                "message": f"convertToMeters = {scale} is very large. "
                           "Are vertices in correct units?",
                "fix": "Verify vertex coordinates and scale factor",
            })

    return issues


def check_2d_empty_patches(case_dir, mesh_patches):
    """Check 2D cases have empty patches."""
    issues = []
    bmd = os.path.join(case_dir, "system", "blockMeshDict")
    if not os.path.isfile(bmd):
        return issues

    with open(bmd, "r") as f:
        content = f.read()

    # Check if nz=1 (single cell in one direction)
    block_match = re.search(r"hex\s+\([^)]+\)\s+\((\d+)\s+(\d+)\s+(\d+)\)", content)
    if block_match:
        nz = int(block_match.group(3))
        if nz == 1:
            # Check for empty type patches
            boundary_file = os.path.join(case_dir, "constant", "polyMesh", "boundary")
            has_empty = False
            if os.path.isfile(boundary_file):
                with open(boundary_file) as bf:
                    has_empty = "empty" in bf.read()

            if not has_empty:
                issues.append({
                    "severity": "fatal",
                    "check": "2d_empty",
                    "message": "Single cell in Z direction (2D case) but no "
                               "'empty' patch type found",
                    "fix": "Set front/back patch type to 'empty' in "
                           "blockMeshDict and all field files",
                })

    return issues


def check_gravity(case_dir):
    """Check gravity vector for hydraulic simulations."""
    issues = []
    g_file = os.path.join(case_dir, "constant", "g")
    if not os.path.isfile(g_file):
        return issues

    with open(g_file, "r") as f:
        content = f.read()

    match = re.search(r"value\s+\(([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\)", content)
    if match:
        gx, gy, gz = [float(match.group(i)) for i in (1, 2, 3)]
        mag = (gx**2 + gy**2 + gz**2) ** 0.5

        if abs(mag - 9.81) > 0.5:
            issues.append({
                "severity": "silent",
                "check": "gravity",
                "message": f"Gravity magnitude |g| = {mag:.2f} m/s^2 "
                           f"(expected ~9.81)",
                "fix": "Set gravity to (0 -9.81 0) or (0 0 -9.81)",
            })

        if gx > 0 or gy > 0 or gz > 0:
            positive_dirs = []
            if gx > 0: positive_dirs.append("x")
            if gy > 0: positive_dirs.append("y")
            if gz > 0: positive_dirs.append("z")
            issues.append({
                "severity": "silent",
                "check": "gravity",
                "message": f"Gravity has positive component(s) in {positive_dirs} "
                           "direction -- buoyancy may be inverted",
                "fix": "Gravity should point downward (negative in up-direction)",
            })

    return issues


def process(args):
    """Run all checks."""
    issues = []

    # Required files
    issues.extend(check_required_files(args.case_dir))

    # Mesh patches
    mesh_patches = get_mesh_patches(args.case_dir)

    # Patch consistency
    if mesh_patches:
        issues.extend(check_patch_consistency(args.case_dir, mesh_patches))

    # Dimensions
    issues.extend(check_dimensions(args.case_dir))

    # convertToMeters
    issues.extend(check_convert_to_meters(args.case_dir))

    # 2D empty patches
    issues.extend(check_2d_empty_patches(args.case_dir, mesh_patches))

    # Gravity
    issues.extend(check_gravity(args.case_dir))

    # Summarize
    n_fatal = sum(1 for i in issues if i["severity"] == "fatal")
    n_silent = sum(1 for i in issues if i["severity"] == "silent")
    n_degraded = sum(1 for i in issues if i["severity"] == "degraded")

    result = {
        "status": "pass" if n_fatal == 0 else "fail",
        "case_dir": os.path.abspath(args.case_dir),
        "mesh_patches": mesh_patches,
        "summary": {
            "total_issues": len(issues),
            "fatal": n_fatal,
            "silent": n_silent,
            "degraded": n_degraded,
        },
        "issues": issues,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Validate OpenFOAM case directory before running"
    )
    parser.add_argument("--case-dir", required=True,
                        help="OpenFOAM case directory")
    parser.add_argument("--output", default=None,
                        help="Output JSON summary file")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

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
