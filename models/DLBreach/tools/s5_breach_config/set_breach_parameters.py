#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
==========================================
Tool ID:      set_breach_parameters
Stage:        s5_breach_config
Description:  Generate DLBreach breach mode, sediment properties, Manning's n,
              initial breach, and other configuration cards.

Inputs:
  --breach_mode:       1=overtopping, 2=piping
  --overtopping_mode:  1=surface erosion (non-cohesive), 2=headcut (cohesive), 3=composite
  --sediment_type:     1=noncohesive, 2=cohesive
  --sediment_diameter: Sediment diameter in meters
  --specific_gravity:  Sediment specific gravity (default 2.65)
  --porosity:          Sediment porosity (default 0.35)
  --clay_content:      Clay content fraction 0-1
  --cohesion_pa:       Cohesion in Pa
  --internal_friction: Internal friction coefficient tan(phi)
  --manning_n:         Manning's n for breach (default auto)
  --kd:                Cohesive erosion coefficient kd (cm3/N-s, cohesive only)
  --tauc:              Critical shear stress tauc (Pa, cohesive only)
  --lambda_adapt:      Non-equilibrium adaptation length (non-cohesive, default 6.0)
  --init_breach_depth: Initial overtopping breach depth (m, default 0.2)
  --init_breach_width: Initial overtopping breach width (m, default 1.0)
  --init_pipe_depth:   Initial pipe depth from top (m, piping mode)
  --init_pipe_width:   Initial pipe width (m, piping mode)
  --breach_location:   1.0=one-sided, 2.0=two-sided (default 2.0)
  --upstream_wsl:      Initial upstream water level (m above base)
  --downstream_wsl:    Initial downstream water level (m above base)
  --hard_bottom:       Hard bottom elevation (m, negative=below base)
  --output:            Output JSON path

Outputs:
  - JSON with parameter_cards text, parameter summary, validation

Exit codes:
  0 -- success
  1 -- invalid parameter values
  2 -- inconsistent parameter combination
  3 -- output validation failed
"""

import sys
import json
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# Recommended Manning's n formula coefficients
# n = (n_grain^(3/2) + n_form^(3/2))^(2/3) where n_grain = d50^(1/6) / A_n
# A_n = 16 for lab, 12 for field cases (Wu 2016, Ch. 5)
def estimate_manning_n(sediment_diameter, is_cohesive=False, is_field=True):
    """Estimate Manning's n from sediment diameter."""
    if is_cohesive:
        return 0.016  # Recommended for cohesive (Wu 2016)
    else:
        a_n = 12.0 if is_field else 16.0
        n_grain = sediment_diameter ** (1.0 / 6.0) / a_n
        return round(max(n_grain, 0.015), 4)


def validate_parameters(args):
    """Validate parameter combinations."""
    errors = []
    warnings = []

    if args.breach_mode not in [1, 2]:
        errors.append(f"breach_mode must be 1 (overtopping) or 2 (piping), got {args.breach_mode}")

    if args.breach_mode == 1 and args.overtopping_mode not in [1, 2, 3]:
        errors.append(f"overtopping_mode must be 1, 2, or 3, got {args.overtopping_mode}")

    if args.sediment_type not in [1, 2]:
        errors.append(f"sediment_type must be 1 (noncohesive) or 2 (cohesive), got {args.sediment_type}")

    # Check consistency and apply Wu 2016 defaults for cohesive sediment
    if args.sediment_type == 2:
        if args.kd is None:
            args.kd = 10.0  # Wu 2016 Ch.5: range 2.5-30, midpoint default
            warnings.append("kd defaulted to 10.0 cm³/N-s (Wu 2016 range: 2.5-30). Sensitivity analysis recommended.")
        if args.tauc is None:
            args.tauc = 0.15  # Wu 2016 Ch.5: 0.15 Pa used in all 35 test cases
            warnings.append("tauc defaulted to 0.15 Pa (Wu 2016 recommendation for all cohesive cases)")
        if args.sediment_diameter is None:
            args.sediment_diameter = 0.00003  # Wu 2016: 0.03mm for cohesive flocs
        if args.manning_n is None:
            args.manning_n = 0.016  # Wu 2016: suggested for cohesive
    else:
        # Non-cohesive defaults
        if args.sediment_diameter is not None and args.manning_n is None:
            # Wu 2016 Eq 3.6: n = An × d50^(1/6), An=12 for field
            args.manning_n = 12.0 * (args.sediment_diameter ** (1.0/6.0))
            warnings.append(f"Manning's n auto-computed from d50: n = 12 × {args.sediment_diameter}^(1/6) = {args.manning_n:.4f} (Wu 2016 Eq. 3.6)")
        if args.lambda_adapt is None:
            args.lambda_adapt = 6.0  # Wu 2016: 6.0 field, 3.0 lab

    if args.sediment_type == 1 and args.overtopping_mode == 2:
        warnings.append("Overtopping_Mode=2 (headcut) is for cohesive sediment, but sediment_type=1 (noncohesive)")

    if args.sediment_diameter is not None:
        if args.sediment_diameter <= 0:
            errors.append("sediment_diameter must be positive")
        if args.sediment_type == 2 and args.sediment_diameter > 0.001:
            warnings.append(f"For cohesive sediment, diameter is typically ~0.00003m (floc size), got {args.sediment_diameter}m")

    if args.upstream_wsl is not None and args.upstream_wsl <= 0:
        warnings.append(f"upstream_wsl={args.upstream_wsl} <= 0; water level should be positive (above embankment base)")

    return errors, warnings


def generate_cards(args):
    """Generate all breach parameter cards."""
    cards = []

    # Breach mode
    mode_comment = "overtopping" if args.breach_mode == 1 else "piping"
    cards.append(f"Breach_Mode    {args.breach_mode}    ! {mode_comment}")

    # Overtopping sub-mode
    if args.breach_mode == 1:
        ot_comments = {1: "surface erosion (non-cohesive)", 2: "headcut (cohesive)", 3: "composite with clay core"}
        cards.append(f"Overtopping_Mode    {args.overtopping_mode}    ! {ot_comments.get(args.overtopping_mode, '')}")

    # Breach location
    if args.breach_location is not None:
        loc_comment = "two-sided" if args.breach_location == 2.0 else "one-sided"
        cards.append(f"Breach_Location    {args.breach_location:.1f}    ! {loc_comment}")

    # Initial breach
    if args.breach_mode == 1:
        depth = args.init_breach_depth if args.init_breach_depth else 0.2
        width = args.init_breach_width if args.init_breach_width else 1.0
        cards.append(f"Initial_Overtopping_Breach    {depth:.2f}, {width:.2f}    ! depth, width in m")
    else:
        depth = args.init_pipe_depth if args.init_pipe_depth else 5.0
        width = args.init_pipe_width if args.init_pipe_width else 0.1
        cards.append(f"Initial_Piping_Breach    {depth:.2f}, {width:.2f}    ! depth_from_top, width in m")

    # Sediment properties
    cards.append("")
    sed_comment = "noncohesive" if args.sediment_type == 1 else "cohesive"
    cards.append(f"Noncohesive_or_Cohesive_Sediment    {args.sediment_type}    ! {sed_comment}")

    if args.sediment_diameter is not None:
        cards.append(f"Sediment_Diameter    {args.sediment_diameter:.6f}    ! in m")
    cards.append(f"Sediment_Specific_Gravity    {args.specific_gravity:.2f}")
    cards.append(f"Sediment_Porosity    {args.porosity:.2f}")
    if args.clay_content is not None:
        cards.append(f"Sediment_Clay_Content    {args.clay_content:.2f}    ! fraction 0-1")
    if args.cohesion_pa is not None:
        cards.append(f"Sediment_Cohesion    {args.cohesion_pa:.1f}    ! in Pa")
    if args.internal_friction is not None:
        cards.append(f"Sediment_Internal_Friction    {args.internal_friction:.4f}    ! tan(phi)")

    # Non-cohesive adaptation length
    if args.sediment_type == 1:
        lam = args.lambda_adapt if args.lambda_adapt else 6.0
        cards.append(f"Noncohesive_Sed_Adaptation_Lamda    {lam:.1f}    ! unitless (6.0 field, 3.0 lab)")

    # Cohesive erosion parameters
    if args.sediment_type == 2:
        if args.kd is not None:
            cards.append(f"Cohesive_Soil_Erosion_kd    {args.kd:.2f}    ! cm^3/N-s")
        if args.tauc is not None:
            cards.append(f"Cohesive_Soil_Erosion_Tauc    {args.tauc:.4f}    ! Pa")

    # Manning's n
    cards.append("")
    if args.manning_n is not None:
        manning = args.manning_n
    else:
        manning = estimate_manning_n(
            args.sediment_diameter if args.sediment_diameter else 0.001,
            is_cohesive=(args.sediment_type == 2),
        )
    cards.append(f"Breach_Manning_n    {manning:.4f}")

    # Hard bottom
    if args.hard_bottom is not None:
        cards.append(f"Hard_Bottom_Elevation    {args.hard_bottom:.2f}    ! in m")

    # Initial water levels
    cards.append("")
    if args.upstream_wsl is not None and args.downstream_wsl is not None:
        cards.append(f"Initial_Up&Downstream_WSL    {args.upstream_wsl:.2f}, {args.downstream_wsl:.2f}    ! in m")

    return "\n".join(cards)


def main():
    parser = argparse.ArgumentParser(description="Set DLBreach breach parameters")
    parser.add_argument("--breach_mode", type=int, required=True, choices=[1, 2])
    parser.add_argument("--overtopping_mode", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--sediment_type", type=int, required=True, choices=[1, 2])
    parser.add_argument("--sediment_diameter", type=float)
    parser.add_argument("--specific_gravity", type=float, default=2.65)
    parser.add_argument("--porosity", type=float, default=0.35)
    parser.add_argument("--clay_content", type=float)
    parser.add_argument("--cohesion_pa", type=float)
    parser.add_argument("--internal_friction", type=float)
    parser.add_argument("--manning_n", type=float)
    parser.add_argument("--kd", type=float, help="Cohesive erosion kd (cm3/N-s)")
    parser.add_argument("--tauc", type=float, help="Critical shear tauc (Pa)")
    parser.add_argument("--lambda_adapt", type=float, help="Non-equilibrium adaptation lambda")
    parser.add_argument("--init_breach_depth", type=float)
    parser.add_argument("--init_breach_width", type=float)
    parser.add_argument("--init_pipe_depth", type=float)
    parser.add_argument("--init_pipe_width", type=float)
    parser.add_argument("--breach_location", type=float, default=2.0)
    parser.add_argument("--upstream_wsl", type=float)
    parser.add_argument("--downstream_wsl", type=float)
    parser.add_argument("--hard_bottom", type=float)
    parser.add_argument("--output", type=str)
    args = parser.parse_args()

    result = {
        "parameter_cards": None,
        "parameter_summary": {},
        "validation_errors": [],
        "validation_warnings": [],
        "status": "error",
    }

    errors, warnings = validate_parameters(args)
    result["validation_errors"] = errors
    result["validation_warnings"] = warnings

    if errors:
        logger.error(f"Validation errors: {errors}")
        print(json.dumps(result, indent=2))
        sys.exit(1)

    cards_text = generate_cards(args)
    result["parameter_cards"] = cards_text
    result["parameter_summary"] = {
        "breach_mode": "overtopping" if args.breach_mode == 1 else "piping",
        "sediment_type": "noncohesive" if args.sediment_type == 1 else "cohesive",
        "overtopping_mode": args.overtopping_mode if args.breach_mode == 1 else None,
        "breach_location": "two-sided" if args.breach_location == 2.0 else "one-sided",
    }
    result["status"] = "success"

    if warnings:
        logger.warning(f"Warnings: {warnings}")

    logger.info("Breach parameter cards generated")

    if args.output:
        from pathlib import Path
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2))

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
