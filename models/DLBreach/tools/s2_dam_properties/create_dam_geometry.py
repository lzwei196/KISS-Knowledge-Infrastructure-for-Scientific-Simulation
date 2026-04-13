#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
==========================================
Tool ID:      create_dam_geometry
Stage:        s2_dam_properties
Description:  Generate DLBreach embankment geometry cards from user inputs
              or lookup from GRanD (Global Reservoir and Dam) database.

Inputs:
  --height_m:            Embankment height in meters (crest to base)
  --crest_width_m:       Crest width in meters
  --upstream_slope_vh:   Upstream slope as V/H ratio
  --downstream_slope_vh: Downstream slope as V/H ratio
  --length_m:            Embankment base length in meters (max breach width)
  --dam_name:            Dam name for GRanD lookup (alternative to manual)
  --output:              Output JSON file path

Outputs:
  - JSON with geometry_cards (text), validation results, computed properties

Exit codes:
  0 -- success
  1 -- invalid geometry parameters
  2 -- GRanD lookup failed
  3 -- output validation failed
"""

import sys
import json
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typical dam geometry ranges (for validation)
# ---------------------------------------------------------------------------
VALID_RANGES = {
    "height_m": (1.0, 300.0),          # Nurek dam is 300m
    "crest_width_m": (1.0, 50.0),
    "upstream_slope_vh": (0.1, 2.0),    # V/H: 0.1 = very gentle, 2.0 = very steep
    "downstream_slope_vh": (0.1, 2.0),
    "length_m": (5.0, 5000.0),
}

# Typical embankment dam slopes (V/H) by dam type
TYPICAL_SLOPES = {
    "earthfill_homogeneous": {"upstream": 0.33, "downstream": 0.40},
    "earthfill_zoned": {"upstream": 0.40, "downstream": 0.50},
    "rockfill": {"upstream": 0.50, "downstream": 0.57},
}


def validate_geometry(height, crest_width, us_slope, ds_slope, length):
    """Validate geometry parameters are physically consistent."""
    errors = []
    warnings = []

    params = {
        "height_m": height,
        "crest_width_m": crest_width,
        "upstream_slope_vh": us_slope,
        "downstream_slope_vh": ds_slope,
        "length_m": length,
    }

    for name, value in params.items():
        if value is None:
            errors.append(f"{name} is required")
            continue
        lo, hi = VALID_RANGES[name]
        if value < lo or value > hi:
            errors.append(f"{name}={value} outside valid range [{lo}, {hi}]")

    if not errors:
        # Compute base width from geometry
        base_width = crest_width + height / us_slope + height / ds_slope
        if length < base_width:
            warnings.append(
                f"Embankment_Length ({length}m) < computed base width ({base_width:.1f}m). "
                f"Length is the max breach bottom width, not the dam crest length."
            )
        if length < crest_width:
            errors.append(f"length ({length}m) must be >= crest_width ({crest_width}m)")

    return errors, warnings


def generate_geometry_cards(height, crest_width, us_slope, ds_slope, length):
    """Generate the 5 embankment geometry cards."""
    cards = []
    cards.append(f"Embankment_Height              {height:.2f}          ! in m")
    cards.append(f"Embankment_Crest_Width         {crest_width:.2f}          ! in m")
    cards.append(f"Embankment_Upstream_Slope      {us_slope:.4f}        ! V/H")
    cards.append(f"Embankment_Downstream_Slope    {ds_slope:.4f}        ! V/H")
    cards.append(f"Embankment_Length              {length:.2f}          ! in m")
    return "\n".join(cards)


def compute_properties(height, crest_width, us_slope, ds_slope, length):
    """Compute derived properties for informational output."""
    base_width = crest_width + height / us_slope + height / ds_slope
    cross_section_area = 0.5 * (crest_width + base_width) * height
    us_face_length = height / us_slope * (1 + us_slope**2)**0.5
    ds_face_length = height / ds_slope * (1 + ds_slope**2)**0.5

    return {
        "base_width_m": round(base_width, 2),
        "cross_section_area_m2": round(cross_section_area, 2),
        "upstream_face_length_m": round(us_face_length, 2),
        "downstream_face_length_m": round(ds_face_length, 2),
        "volume_per_meter_m3": round(cross_section_area, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Create DLBreach dam geometry cards")
    parser.add_argument("--height_m", type=float, help="Embankment height (m)")
    parser.add_argument("--crest_width_m", type=float, help="Crest width (m)")
    parser.add_argument("--upstream_slope_vh", type=float, help="Upstream slope (V/H)")
    parser.add_argument("--downstream_slope_vh", type=float, help="Downstream slope (V/H)")
    parser.add_argument("--length_m", type=float, help="Embankment length / max breach width (m)")
    parser.add_argument("--dam_name", type=str, help="Dam name for GRanD lookup")
    parser.add_argument("--output", type=str, help="Output JSON path")
    args = parser.parse_args()

    result = {
        "geometry_cards": None,
        "properties": None,
        "validation_errors": [],
        "validation_warnings": [],
        "status": "error",
    }

    # GRanD lookup mode
    if args.dam_name and not args.height_m:
        logger.info(f"GRanD lookup requested for: {args.dam_name}")
        result["status"] = "grand_lookup_not_implemented"
        result["validation_errors"].append(
            "GRanD database lookup not yet implemented. "
            "Please provide geometry parameters manually (--height_m, --crest_width_m, etc.) "
            "or look up the dam in GRanD (http://globaldamwatch.org/grand/) and provide values."
        )
        print(json.dumps(result, indent=2))
        sys.exit(2)

    # Validate inputs
    errors, warnings = validate_geometry(
        args.height_m, args.crest_width_m,
        args.upstream_slope_vh, args.downstream_slope_vh,
        args.length_m
    )

    result["validation_errors"] = errors
    result["validation_warnings"] = warnings

    if errors:
        logger.error(f"Validation errors: {errors}")
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Generate cards
    cards_text = generate_geometry_cards(
        args.height_m, args.crest_width_m,
        args.upstream_slope_vh, args.downstream_slope_vh,
        args.length_m
    )
    result["geometry_cards"] = cards_text

    # Compute properties
    props = compute_properties(
        args.height_m, args.crest_width_m,
        args.upstream_slope_vh, args.downstream_slope_vh,
        args.length_m
    )
    result["properties"] = props
    result["status"] = "success"

    if warnings:
        logger.warning(f"Warnings: {warnings}")

    logger.info(f"Geometry cards generated. Base width: {props['base_width_m']}m")

    # Save output
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2))
        logger.info(f"Output saved to {args.output}")

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
