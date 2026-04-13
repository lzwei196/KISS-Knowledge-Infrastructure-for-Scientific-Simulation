#!/usr/bin/env python3
"""
Assign cross-section geometry to SWMM conduits.

Reads conduit definitions (from JSON or CSV) and assigns or updates
cross-section parameters. Supports all standard SWMM shapes:
  - CIRCULAR (geom1=diameter)
  - RECT_CLOSED (geom1=height, geom2=width)
  - RECT_OPEN (geom1=height, geom2=width)
  - TRAPEZOIDAL (geom1=height, geom2=bottom_width, geom3=left_slope, geom4=right_slope)
  - TRIANGULAR (geom1=height, geom2=top_width)
  - ARCH (geom1=height, geom2=width)
  - HORIZ_ELLIPSE (geom1=height, geom2=width)
  - VERT_ELLIPSE (geom1=height, geom2=width)
  - IRREGULAR (geom1=transect_id)
  - CUSTOM (geom1=depth, geom2=shape_curve_id)

Outputs:
  - JSON file with conduit cross-section definitions
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

# Valid SWMM cross-section shapes and required geometry parameters
VALID_SHAPES = {
    "CIRCULAR":       {"geom1": "diameter_m",  "geom2": None, "geom3": None, "geom4": None},
    "FORCE_MAIN":     {"geom1": "diameter_m",  "geom2": None, "geom3": None, "geom4": None},
    "FILLED_CIRCULAR": {"geom1": "diameter_m", "geom2": "fill_depth_m", "geom3": None, "geom4": None},
    "RECT_CLOSED":    {"geom1": "height_m",    "geom2": "width_m", "geom3": None, "geom4": None},
    "RECT_OPEN":      {"geom1": "height_m",    "geom2": "width_m", "geom3": None, "geom4": None},
    "TRAPEZOIDAL":    {"geom1": "height_m",    "geom2": "bottom_width_m", "geom3": "left_slope", "geom4": "right_slope"},
    "TRIANGULAR":     {"geom1": "height_m",    "geom2": "top_width_m", "geom3": None, "geom4": None},
    "HORIZ_ELLIPSE":  {"geom1": "height_m",    "geom2": "width_m", "geom3": None, "geom4": None},
    "VERT_ELLIPSE":   {"geom1": "height_m",    "geom2": "width_m", "geom3": None, "geom4": None},
    "ARCH":           {"geom1": "height_m",    "geom2": "width_m", "geom3": None, "geom4": None},
    "PARABOLIC":      {"geom1": "height_m",    "geom2": "top_width_m", "geom3": None, "geom4": None},
    "POWER":          {"geom1": "height_m",    "geom2": "top_width_m", "geom3": "exponent", "geom4": None},
    "IRREGULAR":      {"geom1": "transect_id", "geom2": None, "geom3": None, "geom4": None},
    "CUSTOM":         {"geom1": "depth_m",     "geom2": "shape_curve_id", "geom3": None, "geom4": None},
}


def load_conduits(path):
    """Load conduits from JSON or CSV."""
    ext = Path(path).suffix.lower()
    if ext == ".json":
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and "conduits" in data:
            return data["conduits"]
        return data
    elif ext == ".csv":
        conduits = []
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                conduits.append({
                    "id": row["id"],
                    "from_node": row.get("from_node", ""),
                    "to_node": row.get("to_node", ""),
                    "length": float(row.get("length", 100)),
                    "roughness": float(row.get("roughness", 0.013)),
                    "shape": row.get("shape", "CIRCULAR"),
                    "geom1": float(row.get("geom1", 0.6)),
                    "geom2": float(row.get("geom2", 0.0)),
                    "geom3": float(row.get("geom3", 0.0)),
                    "geom4": float(row.get("geom4", 0.0)),
                })
        return conduits
    else:
        print(f"ERROR: Unsupported file format: {ext}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Assign cross-section geometry to SWMM conduits"
    )
    parser.add_argument("--conduits", required=True,
                        help="Conduit definitions (JSON or CSV)")
    parser.add_argument("--default_shape", default="CIRCULAR",
                        choices=list(VALID_SHAPES.keys()),
                        help="Default cross-section shape (default: CIRCULAR)")
    parser.add_argument("--default_diameter", type=float, default=0.6,
                        help="Default diameter/height in meters (default: 0.6)")
    parser.add_argument("--default_width", type=float, default=None,
                        help="Default width in meters (for rectangular shapes)")
    parser.add_argument("--override_all", action="store_true",
                        help="Override all existing cross-section assignments")
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    if not os.path.isfile(args.conduits):
        print(f"ERROR: File not found: {args.conduits}", file=sys.stderr)
        sys.exit(1)

    conduits = load_conduits(args.conduits)
    print(f"Loaded {len(conduits)} conduits")

    xsections = []
    updated = 0

    for c in conduits:
        conduit_id = c["id"]
        shape = c.get("shape", "").strip().upper()

        # Determine if we need to assign defaults
        needs_default = (
            args.override_all
            or not shape
            or shape not in VALID_SHAPES
            or c.get("geom1", 0) <= 0
        )

        if needs_default:
            shape = args.default_shape
            geom1 = args.default_diameter
            geom2 = args.default_width if args.default_width else (
                args.default_diameter if shape in ("RECT_CLOSED", "RECT_OPEN") else 0.0
            )
            geom3 = 0.0
            geom4 = 0.0
            if shape == "TRAPEZOIDAL":
                geom2 = args.default_width or args.default_diameter * 2
                geom3 = 2.0  # left slope
                geom4 = 2.0  # right slope
            updated += 1
        else:
            geom1 = c.get("geom1", args.default_diameter)
            geom2 = c.get("geom2", 0.0)
            geom3 = c.get("geom3", 0.0)
            geom4 = c.get("geom4", 0.0)

        xsections.append({
            "conduit_id": conduit_id,
            "shape": shape,
            "geom1": geom1,
            "geom2": geom2,
            "geom3": geom3,
            "geom4": geom4,
            "barrels": int(c.get("barrels", 1)),
        })

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "xsections": xsections,
        "metadata": {
            "n_conduits": len(xsections),
            "n_updated": updated,
            "default_shape": args.default_shape,
            "default_diameter": args.default_diameter,
        },
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nCross-sections written: {output_path}")
    print(f"  Total: {len(xsections)}, Updated to defaults: {updated}")
    shapes_used = set(x["shape"] for x in xsections)
    print(f"  Shapes: {', '.join(sorted(shapes_used))}")


if __name__ == "__main__":
    main()
