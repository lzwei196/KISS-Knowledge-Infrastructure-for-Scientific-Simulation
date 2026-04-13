#!/usr/bin/env python3
"""
convert_parameters_to_lpjguess.py
Convert site and PFT ecophysiological parameters to LPJ-GUESS parameter JSON.

LPJ-GUESS (analytic reimplementation) uses parameters controlling:
  - Light Use Efficiency GPP model
  - Q10-based autotrophic respiration
  - Q10-based heterotrophic respiration (decomposition)
  - Optional: leaf-level traits (SLA, leaf N, Vcmax) for Farquhar scaling

This tool:
  1. validate_inputs() - checks parameter ranges, catches unit traps
  2. Converts/derives parameters from various input formats
  3. validate_outputs() - checks the final parameter set for consistency

UNIT TRAPS:
  - SLA: can be m2/kgC or m2/gC (factor of 1000 difference!)
  - Leaf N: can be gN/m2_leaf or %dry_mass (completely different quantities)
  - Vcmax: must be at 25 deg C reference temperature (not instantaneous)
  - VPD parameters: must be in hPa (not kPa or Pa)
  - Temperature parameters: must be in deg C (not K)

Usage:
    # From PFT name (use built-in defaults)
    python convert_parameters_to_lpjguess.py \\
        --pft temperate_broadleaf_deciduous \\
        --output params.json

    # From explicit parameters
    python convert_parameters_to_lpjguess.py \\
        --lue-max 1.8 --t-opt 22 --vpd-1 30 \\
        --ra-base 0.45 --rh-base 2.5 --rh-q10 2.2 \\
        --output params.json

    # From leaf traits (derive LUE from Vcmax/SLA/leafN)
    python convert_parameters_to_lpjguess.py \\
        --pft custom \\
        --vcmax-base 60 --sla 25.0 --leaf-n 2.0 \\
        --output params.json
"""

import os
import sys
import json
import math
import argparse


# ============================================================================
# Default PFT parameter sets
# ============================================================================

# LPJ-GUESS PFT parameter defaults (analytic model parameters)
PFT_DEFAULTS = {
    "boreal_needleleaf_evergreen": {
        "LUE_max": 1.2,
        "T_opt": 15.0,
        "T_min": -4.0,
        "T_max": 35.0,
        "VPD_0": 10.0,
        "VPD_1": 30.0,
        "SW_in_scale": 0.48,
        "Ra_base": 0.55,
        "Ra_Q10": 2.0,
        "Ra_Tref": 15.0,
        "Rh_base": 1.5,
        "Rh_Q10": 2.0,
        "Rh_Tref": 15.0,
        "C_pool_scale": 1.0,
        "description": "Boreal needleleaf evergreen (e.g., Picea, Pinus sylvestris)",
    },
    "temperate_needleleaf_evergreen": {
        "LUE_max": 1.5,
        "T_opt": 18.0,
        "T_min": -2.0,
        "T_max": 38.0,
        "VPD_0": 10.0,
        "VPD_1": 35.0,
        "SW_in_scale": 0.48,
        "Ra_base": 0.50,
        "Ra_Q10": 2.0,
        "Ra_Tref": 15.0,
        "Rh_base": 2.0,
        "Rh_Q10": 2.0,
        "Rh_Tref": 15.0,
        "C_pool_scale": 1.0,
        "description": "Temperate needleleaf evergreen (e.g., Picea abies, Pinus taeda)",
    },
    "temperate_broadleaf_deciduous": {
        "LUE_max": 1.8,
        "T_opt": 22.0,
        "T_min": -2.0,
        "T_max": 40.0,
        "VPD_0": 10.0,
        "VPD_1": 35.0,
        "SW_in_scale": 0.48,
        "Ra_base": 0.48,
        "Ra_Q10": 2.0,
        "Ra_Tref": 15.0,
        "Rh_base": 2.2,
        "Rh_Q10": 2.0,
        "Rh_Tref": 15.0,
        "C_pool_scale": 1.0,
        "description": "Temperate broadleaf deciduous (e.g., Fagus, Quercus, Acer)",
    },
    "tropical_broadleaf_evergreen": {
        "LUE_max": 2.0,
        "T_opt": 28.0,
        "T_min": 5.0,
        "T_max": 45.0,
        "VPD_0": 12.0,
        "VPD_1": 40.0,
        "SW_in_scale": 0.48,
        "Ra_base": 0.50,
        "Ra_Q10": 1.8,
        "Ra_Tref": 25.0,
        "Rh_base": 3.0,
        "Rh_Q10": 1.8,
        "Rh_Tref": 25.0,
        "C_pool_scale": 1.0,
        "description": "Tropical broadleaf evergreen (rainforest)",
    },
    "c3_grassland": {
        "LUE_max": 1.6,
        "T_opt": 20.0,
        "T_min": -2.0,
        "T_max": 40.0,
        "VPD_0": 10.0,
        "VPD_1": 30.0,
        "SW_in_scale": 0.48,
        "Ra_base": 0.50,
        "Ra_Q10": 2.0,
        "Ra_Tref": 15.0,
        "Rh_base": 2.5,
        "Rh_Q10": 2.2,
        "Rh_Tref": 15.0,
        "C_pool_scale": 1.0,
        "description": "C3 grassland / meadow",
    },
    "c4_grassland": {
        "LUE_max": 2.2,
        "T_opt": 30.0,
        "T_min": 5.0,
        "T_max": 48.0,
        "VPD_0": 15.0,
        "VPD_1": 45.0,
        "SW_in_scale": 0.48,
        "Ra_base": 0.45,
        "Ra_Q10": 1.8,
        "Ra_Tref": 25.0,
        "Rh_base": 2.5,
        "Rh_Q10": 2.0,
        "Rh_Tref": 25.0,
        "C_pool_scale": 1.0,
        "description": "C4 grassland / savanna grass",
    },
    "mediterranean_shrub": {
        "LUE_max": 1.3,
        "T_opt": 22.0,
        "T_min": 0.0,
        "T_max": 42.0,
        "VPD_0": 12.0,
        "VPD_1": 40.0,
        "SW_in_scale": 0.48,
        "Ra_base": 0.50,
        "Ra_Q10": 2.0,
        "Ra_Tref": 15.0,
        "Rh_base": 1.8,
        "Rh_Q10": 2.0,
        "Rh_Tref": 15.0,
        "C_pool_scale": 1.0,
        "description": "Mediterranean evergreen shrubland / maquis",
    },
}

# Short aliases for common PFT names
PFT_ALIASES = {
    "enf": "temperate_needleleaf_evergreen",
    "bnf": "boreal_needleleaf_evergreen",
    "bne": "boreal_needleleaf_evergreen",
    "tne": "temperate_needleleaf_evergreen",
    "dbf": "temperate_broadleaf_deciduous",
    "tbd": "temperate_broadleaf_deciduous",
    "ebf": "tropical_broadleaf_evergreen",
    "tbe": "tropical_broadleaf_evergreen",
    "gra": "c3_grassland",
    "c3g": "c3_grassland",
    "c4g": "c4_grassland",
    "shr": "mediterranean_shrub",
    "msh": "mediterranean_shrub",
}


# ============================================================================
# Input validation
# ============================================================================

def validate_inputs(params):
    """
    Validate parameter values for physical plausibility.

    Parameters
    ----------
    params : dict
        Parameter dictionary to validate

    Returns
    -------
    tuple of (errors, warnings)
    """
    errors = []
    warnings = []

    # LUE parameters
    lue = params.get("LUE_max")
    if lue is not None:
        if lue < 0:
            errors.append(f"LUE_max={lue} must be positive")
        elif lue < 0.1:
            warnings.append(f"LUE_max={lue} very low (<0.1 gC/MJ)")
        elif lue > 5.0:
            warnings.append(f"LUE_max={lue} very high (>5.0 gC/MJ)")

    # Temperature parameters
    t_opt = params.get("T_opt")
    t_min = params.get("T_min")
    t_max = params.get("T_max")
    if t_opt is not None and t_min is not None and t_max is not None:
        if t_min >= t_opt:
            errors.append(f"T_min ({t_min}) must be < T_opt ({t_opt})")
        if t_opt >= t_max:
            errors.append(f"T_opt ({t_opt}) must be < T_max ({t_max})")
        if t_min > 200:
            errors.append(
                f"T_min={t_min} -- looks like Kelvin! Must be in deg C."
            )
        if t_opt > 200:
            errors.append(
                f"T_opt={t_opt} -- looks like Kelvin! Must be in deg C."
            )

    # VPD parameters
    vpd_0 = params.get("VPD_0")
    vpd_1 = params.get("VPD_1")
    if vpd_0 is not None:
        if vpd_0 < 0:
            errors.append(f"VPD_0={vpd_0} must be non-negative")
        if vpd_0 > 100:
            warnings.append(
                f"VPD_0={vpd_0} very high -- units should be hPa (not Pa)"
            )
    if vpd_1 is not None:
        if vpd_1 <= 0:
            errors.append(f"VPD_1={vpd_1} must be positive")
        if vpd_1 < 1:
            warnings.append(
                f"VPD_1={vpd_1} very low -- units should be hPa (not kPa)"
            )

    # Respiration parameters
    ra_base = params.get("Ra_base")
    if ra_base is not None:
        if ra_base < 0 or ra_base > 1:
            errors.append(f"Ra_base={ra_base} must be between 0 and 1 (fraction of GPP)")

    for q10_name in ["Ra_Q10", "Rh_Q10"]:
        q10 = params.get(q10_name)
        if q10 is not None:
            if q10 < 1.0:
                errors.append(f"{q10_name}={q10} must be >= 1.0")
            elif q10 > 5.0:
                warnings.append(f"{q10_name}={q10} very high (typical 1.5-3.0)")

    rh_base = params.get("Rh_base")
    if rh_base is not None:
        if rh_base < 0:
            errors.append(f"Rh_base={rh_base} must be non-negative")
        if rh_base > 20:
            warnings.append(f"Rh_base={rh_base} very high (typical 1-5 umol/m2/s)")

    # Optional leaf trait parameters
    sla = params.get("SLA")
    if sla is not None:
        if sla < 1:
            warnings.append(
                f"SLA={sla} -- if in m2/gC, multiply by 1000 for m2/kgC"
            )
        if sla > 100:
            warnings.append(
                f"SLA={sla} very high -- units should be m2/kgC"
            )

    vcmax = params.get("Vcmax_base")
    if vcmax is not None:
        if vcmax < 0:
            errors.append(f"Vcmax_base={vcmax} must be non-negative")
        if vcmax > 200:
            warnings.append(f"Vcmax_base={vcmax} unusually high (typical 20-80 umol/m2/s)")

    leaf_n = params.get("leaf_N")
    if leaf_n is not None:
        if leaf_n < 0:
            errors.append(f"leaf_N={leaf_n} must be non-negative")
        if leaf_n > 10:
            warnings.append(f"leaf_N={leaf_n} high -- if in %dry_mass, convert to gN/m2")

    # Print results
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)

    return errors, warnings


# ============================================================================
# Output validation
# ============================================================================

def validate_outputs(params):
    """
    Validate the final parameter set for internal consistency.

    Returns True if the parameter set is usable.
    """
    warnings = []

    # Check all required parameters are present
    required = ["LUE_max", "T_opt", "T_min", "T_max", "VPD_0", "VPD_1",
                "SW_in_scale", "Ra_base", "Ra_Q10", "Ra_Tref",
                "Rh_base", "Rh_Q10", "Rh_Tref", "C_pool_scale"]

    missing = [p for p in required if p not in params]
    if missing:
        print(f"ERROR: Missing required parameters: {missing}", file=sys.stderr)
        return False

    # Cross-parameter consistency checks
    if params["T_min"] >= params["T_max"]:
        warnings.append(
            f"T_min ({params['T_min']}) >= T_max ({params['T_max']}): "
            f"no photosynthesis possible"
        )

    # Check that NPP can be positive (Ra_base < 1)
    if params["Ra_base"] >= 1.0:
        warnings.append(
            f"Ra_base={params['Ra_base']} >= 1.0: NPP will always be <= 0"
        )

    # Check CUE (carbon use efficiency) at reference temperature
    cue_at_ref = 1.0 - params["Ra_base"]
    if cue_at_ref < 0.2:
        warnings.append(
            f"CUE at Tref = {cue_at_ref:.2f} is very low (<0.2). "
            f"Check Ra_base."
        )

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if not warnings:
        print("Output parameters validated: all values consistent and within ranges")
    return True


# ============================================================================
# Trait-based parameter derivation
# ============================================================================

def derive_lue_from_traits(vcmax_base, sla, leaf_n=None):
    """
    Estimate LUE_max from leaf-level traits.

    Uses a simplified Farquhar-to-LUE conversion:
        LUE_max ~ 0.035 * Vcmax_base  (empirical scaling, gC/MJ)

    If leaf_N and SLA are provided, also estimates Vcmax:
        Vcmax ~ 25 * leaf_N / SLA  (from Kattge et al. 2009)

    Parameters
    ----------
    vcmax_base : float or None
        Maximum carboxylation rate at 25 C (umol CO2/m2/s)
    sla : float
        Specific leaf area (m2/kgC)
    leaf_n : float or None
        Leaf nitrogen content (gN/m2_leaf)

    Returns
    -------
    dict with derived LUE_max and any intermediate values
    """
    derived = {}

    # If Vcmax not given, estimate from leaf N and SLA
    if vcmax_base is None and leaf_n is not None and sla is not None:
        # Kattge et al. (2009): Vcmax = f(Narea)
        # Narea in gN/m2_leaf, Vcmax in umol/m2/s
        vcmax_base = 25.0 * leaf_n
        derived["Vcmax_estimated_from_leafN"] = round(vcmax_base, 2)
        print(f"  Estimated Vcmax_base = {vcmax_base:.1f} umol/m2/s from leaf_N={leaf_n}")

    if vcmax_base is not None:
        # Empirical LUE ~ 0.035 * Vcmax (rough scaling)
        lue_max = 0.035 * vcmax_base
        lue_max = max(0.5, min(lue_max, 4.0))  # clamp to realistic range
        derived["LUE_max"] = round(lue_max, 3)
        derived["Vcmax_base"] = vcmax_base
        print(f"  Derived LUE_max = {lue_max:.3f} gC/MJ from Vcmax={vcmax_base}")

    if sla is not None:
        derived["SLA"] = sla

    if leaf_n is not None:
        derived["leaf_N"] = leaf_n

    return derived


# ============================================================================
# Main conversion function
# ============================================================================

def convert_parameters(pft=None, output_path=None, overrides=None,
                       vcmax_base=None, sla=None, leaf_n=None):
    """
    Generate LPJ-GUESS parameter set.

    Follows the validate-process-validate pattern:
    1. Start from PFT defaults (or blank)
    2. Apply trait-based derivations if provided
    3. Apply explicit overrides
    4. Validate final parameter set

    Parameters
    ----------
    pft : str or None
        PFT name or alias (e.g., "enf", "temperate_broadleaf_deciduous")
    output_path : str or None
        Path to write JSON output
    overrides : dict or None
        Explicit parameter overrides
    vcmax_base : float or None
        Vcmax at 25C for trait-based derivation
    sla : float or None
        Specific leaf area (m2/kgC)
    leaf_n : float or None
        Leaf N content (gN/m2_leaf)

    Returns
    -------
    dict with final parameter set
    """
    # --- Step 1: Start from PFT defaults ---
    if pft is not None:
        # Resolve alias
        pft_key = PFT_ALIASES.get(pft.lower(), pft.lower())
        if pft_key in PFT_DEFAULTS:
            params = dict(PFT_DEFAULTS[pft_key])
            print(f"Starting from PFT defaults: {pft_key}")
            print(f"  {params.get('description', '')}")
        else:
            available = list(PFT_DEFAULTS.keys()) + list(PFT_ALIASES.keys())
            print(f"WARNING: Unknown PFT '{pft}'. Available: {available}",
                  file=sys.stderr)
            print("  Starting from generic temperate defaults")
            params = dict(PFT_DEFAULTS["temperate_needleleaf_evergreen"])
    else:
        # Start from generic defaults
        params = dict(PFT_DEFAULTS["temperate_needleleaf_evergreen"])
        print("No PFT specified; using temperate_needleleaf_evergreen defaults")

    # --- Step 2: Trait-based derivation ---
    if vcmax_base is not None or (sla is not None and leaf_n is not None):
        print("Deriving parameters from leaf traits...")
        derived = derive_lue_from_traits(vcmax_base, sla, leaf_n)
        # Only override LUE_max from traits if explicitly derived
        if "LUE_max" in derived:
            params["LUE_max"] = derived["LUE_max"]
        # Store trait info for reference
        for k, v in derived.items():
            if k not in params:
                params[k] = v

    # --- Validate intermediate state ---
    errors, _ = validate_inputs(params)
    if errors:
        print("ERROR: Parameter validation failed before applying overrides",
              file=sys.stderr)
        return None

    # --- Step 3: Apply explicit overrides ---
    if overrides:
        print(f"Applying {len(overrides)} explicit overrides...")
        for k, v in overrides.items():
            if k in params:
                old_val = params[k]
                params[k] = v
                print(f"  {k}: {old_val} -> {v}")
            else:
                params[k] = v
                print(f"  {k}: (new) {v}")

    # --- Step 4: Final validation ---
    errors, _ = validate_inputs(params)
    if errors:
        print("ERROR: Final parameter validation failed", file=sys.stderr)
        return None

    ok = validate_outputs(params)
    if not ok:
        print("ERROR: Output validation failed", file=sys.stderr)
        return None

    # --- Write output ---
    if output_path:
        # Remove non-serializable description before writing
        out_params = {k: v for k, v in params.items()}
        with open(output_path, "w") as f:
            json.dump(out_params, f, indent=2)
        print(f"Parameters written to {output_path}")

    return params


# ============================================================================
# CLI entry point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert site/PFT parameters to LPJ-GUESS parameter JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Available PFT names:\n"
            "  boreal_needleleaf_evergreen (alias: bne, bnf)\n"
            "  temperate_needleleaf_evergreen (alias: enf, tne)\n"
            "  temperate_broadleaf_deciduous (alias: dbf, tbd)\n"
            "  tropical_broadleaf_evergreen (alias: ebf, tbe)\n"
            "  c3_grassland (alias: gra, c3g)\n"
            "  c4_grassland (alias: c4g)\n"
            "  mediterranean_shrub (alias: shr, msh)\n"
        ),
    )
    parser.add_argument("--pft", default=None,
                        help="PFT name or alias for defaults")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    # Explicit parameter overrides
    parser.add_argument("--lue-max", type=float, default=None,
                        help="LUE_max (gC/MJ PAR)")
    parser.add_argument("--t-opt", type=float, default=None,
                        help="Optimal temperature (deg C)")
    parser.add_argument("--t-min", type=float, default=None,
                        help="Min photosynthesis temperature (deg C)")
    parser.add_argument("--t-max", type=float, default=None,
                        help="Max photosynthesis temperature (deg C)")
    parser.add_argument("--vpd-0", type=float, default=None,
                        help="VPD threshold for GPP decline (hPa)")
    parser.add_argument("--vpd-1", type=float, default=None,
                        help="VPD half-inhibition point (hPa)")
    parser.add_argument("--ra-base", type=float, default=None,
                        help="Ra_base: autotrophic resp fraction of GPP")
    parser.add_argument("--ra-q10", type=float, default=None,
                        help="Q10 for maintenance respiration")
    parser.add_argument("--rh-base", type=float, default=None,
                        help="Rh_base: base heterotrophic respiration (umol/m2/s)")
    parser.add_argument("--rh-q10", type=float, default=None,
                        help="Q10 for decomposition")

    # Trait-based derivation
    parser.add_argument("--vcmax-base", type=float, default=None,
                        help="Vcmax at 25C (umol CO2/m2/s)")
    parser.add_argument("--sla", type=float, default=None,
                        help="Specific Leaf Area (m2/kgC)")
    parser.add_argument("--leaf-n", type=float, default=None,
                        help="Leaf N content (gN/m2_leaf)")

    # Load from existing JSON
    parser.add_argument("--from-json", default=None,
                        help="Load base parameters from existing JSON file")

    args = parser.parse_args()

    # Build overrides from CLI arguments
    overrides = {}
    cli_map = {
        "lue_max": "LUE_max", "t_opt": "T_opt", "t_min": "T_min",
        "t_max": "T_max", "vpd_0": "VPD_0", "vpd_1": "VPD_1",
        "ra_base": "Ra_base", "ra_q10": "Ra_Q10",
        "rh_base": "Rh_base", "rh_q10": "Rh_Q10",
    }
    for cli_name, param_name in cli_map.items():
        val = getattr(args, cli_name, None)
        if val is not None:
            overrides[param_name] = val

    # Load base from JSON if specified
    if args.from_json and os.path.isfile(args.from_json):
        print(f"Loading base parameters from {args.from_json}")
        with open(args.from_json) as f:
            base_params = json.load(f)
        # Merge: base from JSON, then PFT defaults get overridden
        if not overrides:
            overrides = base_params
        else:
            overrides = {**base_params, **overrides}

    result = convert_parameters(
        pft=args.pft,
        output_path=args.output,
        overrides=overrides if overrides else None,
        vcmax_base=args.vcmax_base,
        sla=args.sla,
        leaf_n=args.leaf_n,
    )

    if result is None:
        sys.exit(1)

    # Print summary
    print("\n--- Parameter Summary ---")
    for k, v in sorted(result.items()):
        if isinstance(v, float):
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")

    sys.exit(0)
