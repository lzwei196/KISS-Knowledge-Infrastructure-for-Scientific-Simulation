#!/usr/bin/env python3
"""
convert_parameters_to_quincy.py
Convert and validate PFT (Plant Functional Type) parameters for QUINCY.

Manages QUINCY's coupled C-N-P parameters including:
  - Photosynthesis: Vcmax25, Jmax25, quantum yield, activation energies
  - N-limitation: leaf N content, Vcmax-N slope (QUINCY key feature)
  - Stomatal conductance: Ball-Berry g1 parameter
  - Respiration: maintenance (leaf/stem/root), growth fraction
  - Soil decomposition: CENTURY-like base rates, Q10, moisture response
  - Phenology: LAI min/max, temperature response
  - Stoichiometry: C:N ratios (leaf, root, wood), C:P ratios, N:P ratios
  - Leaf traits: SLA, leaf longevity

Follows validate -> process -> validate pattern.

Usage:
    # Validate a parameter JSON file
    python convert_parameters_to_quincy.py --fin params.json --operation validate

    # Create default parameters for a PFT
    python convert_parameters_to_quincy.py --operation defaults --pft enf \\
        --fout enf_params.json

    # Modify a parameter
    python convert_parameters_to_quincy.py --fin params.json --operation modify \\
        --param vcmax25 --value 55.0 --fout modified_params.json

    # Query a parameter
    python convert_parameters_to_quincy.py --fin params.json --operation query \\
        --param vcmax25

    # List all parameters
    python convert_parameters_to_quincy.py --fin params.json --operation list
"""

import os
import sys
import json
import copy
import argparse
from typing import Dict, List, Any, Optional


# ============================================================================
# Physical range checks for QUINCY parameters
# ============================================================================

PARAMETER_RANGES = {
    # Photosynthesis
    "vcmax25": (10.0, 120.0, "umol/m2/s",
                "Max carboxylation rate at 25C"),
    "jmax_vcmax_ratio": (1.2, 2.8, "-",
                         "Jmax/Vcmax ratio at 25C"),
    "alpha_j": (0.1, 0.5, "mol/mol",
                "Quantum yield of electron transport"),
    "theta_j": (0.5, 1.0, "-",
                "Curvature of light response"),
    "ea_vcmax": (40000, 90000, "J/mol",
                 "Activation energy for Vcmax"),
    "ea_jmax": (30000, 60000, "J/mol",
                "Activation energy for Jmax"),

    # N-limitation (QUINCY key feature)
    "n_leaf_ref": (0.5, 4.0, "gN/m2_leaf",
                   "Reference leaf N content"),
    "vcmax_n_slope": (10.0, 50.0, "umol/s/gN",
                      "Vcmax per unit leaf N"),

    # Stomatal conductance (Ball-Berry)
    "g1_bb": (2.0, 15.0, "-",
              "Ball-Berry slope parameter"),

    # LAI and phenology
    "lai_max": (1.0, 12.0, "m2/m2",
                "Maximum LAI"),
    "lai_min": (0.0, 8.0, "m2/m2",
                "Minimum LAI (evergreen base)"),
    "lai_t_opt": (5.0, 30.0, "degC",
                  "Temperature for max LAI"),
    "lai_t_range": (5.0, 25.0, "degC",
                    "Temperature range for LAI response"),

    # Autotrophic respiration
    "r_maint_leaf": (0.002, 0.06, "umol/m2leaf/s",
                     "Leaf maintenance respiration at 25C"),
    "r_maint_stem": (0.05, 2.0, "umol/m2ground/s",
                     "Stem maintenance respiration at 25C"),
    "r_maint_root": (0.05, 1.5, "umol/m2ground/s",
                     "Root maintenance respiration at 25C"),
    "r_growth_frac": (0.15, 0.35, "-",
                      "Growth respiration fraction of NPP"),
    "ea_rd": (30000, 60000, "J/mol",
              "Activation energy for dark respiration"),

    # Soil / heterotrophic respiration (CENTURY-like)
    "rh_base": (0.3, 5.0, "umol/m2/s",
                "Base heterotrophic respiration rate at Tref"),
    "rh_q10": (1.2, 3.5, "-",
               "Q10 temperature sensitivity for Rh"),
    "rh_t_ref": (5.0, 25.0, "degC",
                 "Reference temperature for Rh"),
    "rh_precip_scale": (0.005, 0.1, "-",
                        "Precipitation scaling for moisture effect"),
    "rh_precip_opt": (1.0, 8.0, "mm/day",
                      "Optimal precipitation for decomposition"),

    # Carbon use efficiency
    "cue_ref": (0.3, 0.6, "-",
                "Reference carbon use efficiency"),

    # Leaf traits
    "sla": (3.0, 50.0, "m2/kgC",
            "Specific leaf area"),
    "leaf_longevity": (0.3, 10.0, "years",
                       "Leaf lifespan"),

    # C:N:P stoichiometry
    "cn_leaf": (15.0, 80.0, "gC/gN",
                "Leaf C:N ratio"),
    "cn_root": (20.0, 120.0, "gC/gN",
                "Fine root C:N ratio"),
    "cn_wood": (100.0, 800.0, "gC/gN",
                "Wood C:N ratio"),
    "cp_leaf": (200.0, 1500.0, "gC/gP",
                "Leaf C:P ratio"),
    "np_leaf": (5.0, 40.0, "gN/gP",
                "Leaf N:P ratio"),
}


# ============================================================================
# Default parameters by PFT
# ============================================================================

PFT_DEFAULTS = {
    "enf": {
        "name": "Evergreen Needleleaf Forest",
        "description": "Boreal/temperate coniferous (e.g., Scots pine, Norway spruce)",
        "params": {
            "vcmax25": 45.0,
            "jmax_vcmax_ratio": 1.9,
            "alpha_j": 0.3,
            "theta_j": 0.9,
            "ea_vcmax": 65330,
            "ea_jmax": 43540,
            "n_leaf_ref": 1.8,
            "vcmax_n_slope": 25.0,
            "g1_bb": 6.0,
            "lai_max": 5.5,
            "lai_min": 3.5,
            "lai_t_opt": 15.0,
            "lai_t_range": 15.0,
            "r_maint_leaf": 0.015,
            "r_maint_stem": 0.4,
            "r_maint_root": 0.3,
            "r_growth_frac": 0.25,
            "ea_rd": 46390,
            "rh_base": 1.8,
            "rh_q10": 2.0,
            "rh_t_ref": 15.0,
            "rh_precip_scale": 0.02,
            "rh_precip_opt": 2.5,
            "cue_ref": 0.45,
            "sla": 6.0,
            "leaf_longevity": 3.0,
            "cn_leaf": 40.0,
            "cn_root": 60.0,
            "cn_wood": 350.0,
            "cp_leaf": 600.0,
            "np_leaf": 15.0,
        },
    },
    "dbf": {
        "name": "Deciduous Broadleaf Forest",
        "description": "Temperate deciduous (e.g., oak, beech, maple)",
        "params": {
            "vcmax25": 60.0,
            "jmax_vcmax_ratio": 1.8,
            "alpha_j": 0.35,
            "theta_j": 0.9,
            "ea_vcmax": 65330,
            "ea_jmax": 43540,
            "n_leaf_ref": 2.5,
            "vcmax_n_slope": 30.0,
            "g1_bb": 8.0,
            "lai_max": 6.0,
            "lai_min": 0.5,
            "lai_t_opt": 20.0,
            "lai_t_range": 10.0,
            "r_maint_leaf": 0.02,
            "r_maint_stem": 0.5,
            "r_maint_root": 0.35,
            "r_growth_frac": 0.25,
            "ea_rd": 46390,
            "rh_base": 2.0,
            "rh_q10": 2.0,
            "rh_t_ref": 15.0,
            "rh_precip_scale": 0.02,
            "rh_precip_opt": 3.0,
            "cue_ref": 0.45,
            "sla": 20.0,
            "leaf_longevity": 0.5,
            "cn_leaf": 28.0,
            "cn_root": 45.0,
            "cn_wood": 300.0,
            "cp_leaf": 450.0,
            "np_leaf": 16.0,
        },
    },
    "ebf": {
        "name": "Evergreen Broadleaf Forest",
        "description": "Tropical evergreen (e.g., tropical rainforest)",
        "params": {
            "vcmax25": 40.0,
            "jmax_vcmax_ratio": 1.7,
            "alpha_j": 0.28,
            "theta_j": 0.9,
            "ea_vcmax": 65330,
            "ea_jmax": 43540,
            "n_leaf_ref": 1.5,
            "vcmax_n_slope": 22.0,
            "g1_bb": 10.0,
            "lai_max": 7.0,
            "lai_min": 5.0,
            "lai_t_opt": 28.0,
            "lai_t_range": 8.0,
            "r_maint_leaf": 0.018,
            "r_maint_stem": 0.6,
            "r_maint_root": 0.4,
            "r_growth_frac": 0.25,
            "ea_rd": 46390,
            "rh_base": 2.5,
            "rh_q10": 1.8,
            "rh_t_ref": 25.0,
            "rh_precip_scale": 0.015,
            "rh_precip_opt": 5.0,
            "cue_ref": 0.40,
            "sla": 12.0,
            "leaf_longevity": 2.0,
            "cn_leaf": 30.0,
            "cn_root": 50.0,
            "cn_wood": 250.0,
            "cp_leaf": 800.0,
            "np_leaf": 22.0,
        },
    },
    "c3grass": {
        "name": "C3 Grassland",
        "description": "Temperate/cool-season grassland",
        "params": {
            "vcmax25": 55.0,
            "jmax_vcmax_ratio": 1.8,
            "alpha_j": 0.35,
            "theta_j": 0.9,
            "ea_vcmax": 65330,
            "ea_jmax": 43540,
            "n_leaf_ref": 2.2,
            "vcmax_n_slope": 28.0,
            "g1_bb": 9.0,
            "lai_max": 4.0,
            "lai_min": 0.3,
            "lai_t_opt": 18.0,
            "lai_t_range": 12.0,
            "r_maint_leaf": 0.02,
            "r_maint_stem": 0.1,
            "r_maint_root": 0.4,
            "r_growth_frac": 0.25,
            "ea_rd": 46390,
            "rh_base": 2.2,
            "rh_q10": 2.0,
            "rh_t_ref": 15.0,
            "rh_precip_scale": 0.025,
            "rh_precip_opt": 3.0,
            "cue_ref": 0.45,
            "sla": 25.0,
            "leaf_longevity": 0.5,
            "cn_leaf": 25.0,
            "cn_root": 40.0,
            "cn_wood": 200.0,
            "cp_leaf": 400.0,
            "np_leaf": 14.0,
        },
    },
}


# ============================================================================
# Validation: Stage 1 (inputs)
# ============================================================================

def validate_inputs(args):
    """
    Validate command-line inputs and file existence.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments

    Returns
    -------
    list of str
        Error messages (empty if valid)
    """
    errors = []

    if args.operation in ("validate", "modify", "query", "list"):
        if not args.fin:
            errors.append("--fin required for this operation")
        elif not os.path.isfile(args.fin):
            errors.append(f"Input file not found: {args.fin}")

    if args.operation == "modify":
        if not args.param:
            errors.append("--param required for modify operation")
        if args.value is None:
            errors.append("--value required for modify operation")
        if not args.fout:
            errors.append("--fout required for modify operation")

    if args.operation == "query" and not args.param:
        errors.append("--param required for query operation")

    if args.operation == "defaults":
        if not args.pft:
            errors.append("--pft required for defaults operation")
        elif args.pft not in PFT_DEFAULTS:
            errors.append(
                f"Unknown PFT '{args.pft}'. "
                f"Valid: {list(PFT_DEFAULTS.keys())}")
        if not args.fout:
            errors.append("--fout required for defaults operation")

    if errors:
        for e in errors:
            print(f"INPUT ERROR: {e}", file=sys.stderr)

    return errors


# ============================================================================
# Parameter range validation
# ============================================================================

def validate_parameter_ranges(params):
    """
    Check all parameters against known physical ranges.

    Parameters
    ----------
    params : dict
        Parameter name -> value dictionary

    Returns
    -------
    list of dict
        Warning/error records
    """
    warnings = []

    for pname, value in params.items():
        if pname not in PARAMETER_RANGES:
            continue

        lo, hi, unit, desc = PARAMETER_RANGES[pname]

        try:
            fval = float(value)
        except (TypeError, ValueError):
            warnings.append({
                "parameter": pname,
                "value": value,
                "issue": "Non-numeric value",
                "severity": "error",
            })
            continue

        if fval < lo or fval > hi:
            severity = "error" if (fval < lo * 0.5 or fval > hi * 2) else "warning"
            warnings.append({
                "parameter": pname,
                "value": fval,
                "expected_range": f"[{lo}, {hi}]",
                "unit": unit,
                "description": desc,
                "severity": severity,
                "hint": _get_param_hint(pname, fval, lo, hi),
            })

    return warnings


def _get_param_hint(pname, value, lo, hi):
    """Generate helpful hint for likely parameter errors."""
    if pname == "vcmax25" and value > 200:
        return "Value may be in nmol/m2/s instead of umol/m2/s (divide by 1000)"
    if pname == "sla" and value < 1:
        return "Value may be in m2/gC instead of m2/kgC (multiply by 1000)"
    if pname == "sla" and value > 100:
        return "Check units: QUINCY expects m2/kgC (not cm2/g)"
    if pname == "n_leaf_ref" and value > 10:
        return "Value may be in mgN/m2 instead of gN/m2 (divide by 1000)"
    if pname == "ea_vcmax" and value < 100:
        return "Value may be in kJ/mol instead of J/mol (multiply by 1000)"
    if pname in ("cn_leaf", "cn_root", "cn_wood") and value < 5:
        return "Value may be N:C ratio instead of C:N ratio (take reciprocal)"
    return ""


# ============================================================================
# Consistency checks
# ============================================================================

def validate_parameter_consistency(params):
    """
    Check parameter consistency (relationships between parameters).

    Parameters
    ----------
    params : dict
        Parameter dictionary

    Returns
    -------
    list of dict
        Consistency warnings
    """
    warnings = []

    # LAI: min should be <= max
    if "lai_min" in params and "lai_max" in params:
        if params["lai_min"] > params["lai_max"]:
            warnings.append({
                "check": "lai_min > lai_max",
                "values": f"lai_min={params['lai_min']}, lai_max={params['lai_max']}",
                "severity": "error",
                "hint": "Minimum LAI must be <= maximum LAI",
            })

    # Vcmax25 and N-limitation: effective Vcmax should be achievable
    if "vcmax25" in params and "vcmax_n_slope" in params and "n_leaf_ref" in params:
        vcmax_eff = params["vcmax_n_slope"] * params["n_leaf_ref"]
        if vcmax_eff > params["vcmax25"] * 1.5:
            warnings.append({
                "check": "N-limited Vcmax exceeds cap by >50%",
                "values": (f"vcmax_n_slope * n_leaf_ref = {vcmax_eff:.1f}, "
                           f"vcmax25 cap = {params['vcmax25']:.1f}"),
                "severity": "info",
                "hint": "Effective Vcmax is always capped at vcmax25",
            })
        if vcmax_eff < params["vcmax25"] * 0.3:
            warnings.append({
                "check": "N-limitation is very strong",
                "values": (f"vcmax_n_slope * n_leaf_ref = {vcmax_eff:.1f}, "
                           f"vcmax25 = {params['vcmax25']:.1f}"),
                "severity": "warning",
                "hint": "Strong N-limitation reduces GPP significantly",
            })

    # C:N:P stoichiometric consistency
    if "cn_leaf" in params and "cp_leaf" in params and "np_leaf" in params:
        expected_np = params["cp_leaf"] / params["cn_leaf"]
        actual_np = params["np_leaf"]
        if abs(expected_np - actual_np) / max(actual_np, 1) > 0.2:
            warnings.append({
                "check": "N:P ratio inconsistent with C:N and C:P",
                "values": (f"C:P/C:N = {expected_np:.1f}, "
                           f"stated N:P = {actual_np:.1f}"),
                "severity": "warning",
                "hint": "N:P should approximately equal C:P / C:N",
            })

    # Jmax/Vcmax ratio
    if "jmax_vcmax_ratio" in params:
        ratio = params["jmax_vcmax_ratio"]
        if ratio < 1.5 or ratio > 2.5:
            warnings.append({
                "check": "Jmax/Vcmax ratio outside typical range [1.5, 2.5]",
                "values": f"jmax_vcmax_ratio = {ratio:.2f}",
                "severity": "warning",
                "hint": "Typical values: 1.67 (tropical) to 2.1 (boreal)",
            })

    return warnings


# ============================================================================
# Validation: Stage 3 (outputs)
# ============================================================================

def validate_outputs(result, operation):
    """
    Final validation of operation results.

    Parameters
    ----------
    result : dict or Any
        Operation result
    operation : str
        Operation type

    Returns
    -------
    list of str
        Output warnings
    """
    warnings = []

    if operation == "validate" and isinstance(result, dict):
        range_warnings = result.get("range_warnings", [])
        consistency_warnings = result.get("consistency_warnings", [])

        n_errors = sum(1 for w in range_warnings if w.get("severity") == "error")
        n_errors += sum(1 for w in consistency_warnings
                        if w.get("severity") == "error")

        if n_errors > 0:
            warnings.append(
                f"{n_errors} parameters have critical issues (out of range or inconsistent)")
        if len(range_warnings) > 0:
            warnings.append(
                f"{len(range_warnings)} parameters outside expected physical ranges")

    if operation == "modify" and isinstance(result, dict):
        params = result.get("params", {})
        range_w = validate_parameter_ranges(params)
        for w in range_w:
            if w.get("severity") == "error":
                warnings.append(
                    f"Modified value {w['parameter']}={w['value']} "
                    f"outside range {w['expected_range']} {w['unit']}")

    if operation == "defaults" and isinstance(result, dict):
        params = result.get("params", {})
        range_w = validate_parameter_ranges(params)
        if range_w:
            warnings.append(
                f"Default parameters have {len(range_w)} range warnings "
                f"(should be zero -- check PFT_DEFAULTS table)")

    return warnings


# ============================================================================
# Operations
# ============================================================================

def load_param_file(filepath):
    """Load QUINCY parameter JSON file."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    return data


def do_validate(filepath):
    """Validate a parameter file."""
    data = load_param_file(filepath)
    params = data.get("params", data)

    range_warnings = validate_parameter_ranges(params)
    consistency_warnings = validate_parameter_consistency(params)

    result = {
        "status": "success",
        "file": filepath,
        "n_parameters": len(params),
        "pft": data.get("pft", "unknown"),
        "range_warnings": range_warnings,
        "consistency_warnings": consistency_warnings,
        "total_warnings": len(range_warnings) + len(consistency_warnings),
    }
    return result


def do_defaults(pft, output_path):
    """Generate default parameter file for a PFT."""
    if pft not in PFT_DEFAULTS:
        print(f"ERROR: Unknown PFT '{pft}'", file=sys.stderr)
        sys.exit(1)

    pft_info = PFT_DEFAULTS[pft]
    data = {
        "model": "QUINCY",
        "version": "1.0",
        "pft": pft,
        "pft_name": pft_info["name"],
        "description": pft_info["description"],
        "params": copy.deepcopy(pft_info["params"]),
        "parameter_metadata": {},
    }

    # Add metadata from PARAMETER_RANGES
    for pname in pft_info["params"]:
        if pname in PARAMETER_RANGES:
            lo, hi, unit, desc = PARAMETER_RANGES[pname]
            data["parameter_metadata"][pname] = {
                "unit": unit,
                "description": desc,
                "valid_range": [lo, hi],
            }

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"Default {pft} parameters written to {output_path}")
    return data


def do_modify(filepath, param_name, value, output_path):
    """Modify a parameter value."""
    data = load_param_file(filepath)
    params = data.get("params", data)

    if param_name not in params:
        # Check if it is a valid QUINCY parameter
        if param_name in PARAMETER_RANGES:
            print(f"Parameter '{param_name}' not in file but is a valid "
                  f"QUINCY parameter. Adding it.", file=sys.stderr)
        else:
            print(f"WARNING: '{param_name}' is not a recognized QUINCY parameter",
                  file=sys.stderr)

    old_val = params.get(param_name, "N/A")
    params[param_name] = value
    if "params" in data:
        data["params"] = params

    print(f"Modified {param_name}: {old_val} -> {value}", file=sys.stderr)

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"Modified file written to {output_path}", file=sys.stderr)
    return data


def do_query(filepath, param_name):
    """Query a specific parameter."""
    data = load_param_file(filepath)
    params = data.get("params", data)

    lines = []
    if param_name in params:
        lines.append(f"Parameter: {param_name}")
        lines.append(f"  Value: {params[param_name]}")
        lines.append(f"  PFT: {data.get('pft', 'unknown')}")

        if param_name in PARAMETER_RANGES:
            lo, hi, unit, desc = PARAMETER_RANGES[param_name]
            lines.append(f"  Unit: {unit}")
            lines.append(f"  Description: {desc}")
            lines.append(f"  Valid range: [{lo}, {hi}]")

            val = params[param_name]
            try:
                fval = float(val)
                if lo <= fval <= hi:
                    lines.append(f"  Status: OK (within range)")
                else:
                    lines.append(f"  Status: WARNING (outside range [{lo}, {hi}])")
            except (TypeError, ValueError):
                pass
    else:
        lines.append(f"Parameter '{param_name}' not found in file.")
        if param_name in PARAMETER_RANGES:
            lo, hi, unit, desc = PARAMETER_RANGES[param_name]
            lines.append(f"  (Valid QUINCY parameter: {desc}, [{lo}-{hi}] {unit})")

    return "\n".join(lines)


def do_list(filepath):
    """List all parameters in a file."""
    data = load_param_file(filepath)
    params = data.get("params", data)

    lines = []
    lines.append(f"{'Parameter':<25} {'Value':<15} {'Unit':<20} {'Description'}")
    lines.append("-" * 90)

    for pname in sorted(params.keys()):
        if pname.startswith("_") or pname in ("model", "version", "pft",
                                               "pft_name", "description",
                                               "parameter_metadata"):
            continue
        value = params[pname]
        if pname in PARAMETER_RANGES:
            _, _, unit, desc = PARAMETER_RANGES[pname]
        else:
            unit = ""
            desc = ""
        lines.append(f"{pname:<25} {str(value):<15} {unit:<20} {desc}")

    return "\n".join(lines)


# ============================================================================
# CLI entry point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="QUINCY PFT parameter converter and validator. "
                    "Manages coupled C-N-P parameters for QUINCY simulations."
    )
    parser.add_argument("--fin", default=None,
                        help="Input JSON parameter file")
    parser.add_argument("--fout", default=None,
                        help="Output JSON parameter file")
    parser.add_argument("--operation", required=True,
                        choices=["validate", "defaults", "modify", "query", "list"],
                        help="Operation to perform")
    parser.add_argument("--param", default=None,
                        help="Parameter name (for query/modify)")
    parser.add_argument("--value", type=float, default=None,
                        help="New value (for modify)")
    parser.add_argument("--pft", default=None,
                        choices=list(PFT_DEFAULTS.keys()),
                        help="PFT type (for defaults)")
    parser.add_argument("--report", default=None,
                        help="Write validation report to JSON file")
    args = parser.parse_args()

    # Stage 1: Validate inputs
    errors = validate_inputs(args)
    if errors:
        sys.exit(1)

    # Stage 2: Process
    if args.operation == "validate":
        result = do_validate(args.fin)
        print(json.dumps(result, indent=2))
        output_warnings = validate_outputs(result, "validate")

    elif args.operation == "defaults":
        result = do_defaults(args.pft, args.fout)
        output_warnings = validate_outputs(result, "defaults")

    elif args.operation == "modify":
        result = do_modify(args.fin, args.param, args.value, args.fout)
        output_warnings = validate_outputs(result, "modify")

    elif args.operation == "query":
        output = do_query(args.fin, args.param)
        print(output)
        output_warnings = []

    elif args.operation == "list":
        output = do_list(args.fin)
        print(output)
        output_warnings = []

    # Stage 3: Report output warnings
    if output_warnings:
        print("\n--- Output Validation Warnings ---", file=sys.stderr)
        for w in output_warnings:
            print(f"  WARNING: {w}", file=sys.stderr)

    if args.report and args.operation == "validate":
        with open(args.report, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Report written to {args.report}", file=sys.stderr)

    summary = {
        "status": "success" if not output_warnings else "completed_with_warnings",
        "operation": args.operation,
        "input_file": args.fin,
        "output_file": args.fout,
        "warnings": output_warnings,
    }
    print(json.dumps(summary, indent=2), file=sys.stderr)
