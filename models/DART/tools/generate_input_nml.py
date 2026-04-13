#!/usr/bin/env python3
"""
generate_input_nml.py — Generate DART input.nml namelist files.

CRITICAL:
  - Fortran namelist format requires .true./.false. (with dots) for booleans.
  - Strings must be single-quoted: 'value' (not double-quoted).
  - Arrays are comma-separated: 1.0, 1.0 (for 2-element prior/posterior).
  - The & prefix and / terminator are required for every namelist block.
  - inf_flavor is a 2-element array: [prior, posterior]. Setting only one
    value will leave the other at default (typically 0).
  - cutoff units depend on location module: radians for threed_sphere,
    fraction for oned.

Output format: Standard Fortran namelist file (input.nml).

Usage:
  python generate_input_nml.py \\
      --model lorenz_63 \\
      --ens_size 20 \\
      --output input.nml

  python generate_input_nml.py \\
      --model lorenz_96 \\
      --ens_size 40 \\
      --cutoff 0.2 \\
      --inf_flavor_prior 2 \\
      --inf_initial_prior 1.02 \\
      --output input.nml

  python generate_input_nml.py \\
      --model custom \\
      --ens_size 80 \\
      --cutoff 0.05 \\
      --inf_flavor_prior 2 \\
      --inf_flavor_posterior 0 \\
      --async_mode 2 \\
      --adv_ens_command './advance_model.sh' \\
      --output input.nml
"""

import argparse
import json
import sys
import os
from pathlib import Path


# Model presets with sensible defaults
MODEL_PRESETS = {
    "lorenz_63": {
        "model_nml": {
            "sigma": 10.0,
            "r": 28.0,
            "b": 2.6666666666667,
            "deltat": 0.01,
            "time_step_days": 0,
            "time_step_seconds": 3600,
            "solver": "'RK2'",
        },
        "location": "oned",
        "obs_types": ["'../../../observations/forward_operators/obs_def_1d_state_mod.f90'"],
        "quantity_files": ["'../../../assimilation_code/modules/observations/oned_quantities_mod.f90'"],
        "default_cutoff": 1000000.0,  # No localization for small model
    },
    "lorenz_96": {
        "model_nml": {
            "model_size": 40,
            "forcing": 8.00,
            "delta_t": 0.05,
            "time_step_days": 0,
            "time_step_seconds": 3600,
        },
        "location": "oned",
        "obs_types": ["'../../../observations/forward_operators/obs_def_1d_state_mod.f90'"],
        "quantity_files": ["'../../../assimilation_code/modules/observations/oned_quantities_mod.f90'"],
        "default_cutoff": 0.2,
    },
    "custom": {
        "model_nml": {},
        "location": "threed_sphere",
        "obs_types": [],
        "quantity_files": [],
        "default_cutoff": 0.2,
    },
}


def validate_inputs(args):
    """Pre-processing validation."""
    errors = []

    if args.ens_size < 2:
        errors.append(f"ens_size must be >= 2, got {args.ens_size}")

    if args.cutoff is not None and args.cutoff <= 0:
        errors.append(f"cutoff must be > 0, got {args.cutoff}")

    if args.inf_flavor_prior not in (0, 2, 3, 4, 5):
        errors.append(
            f"inf_flavor_prior must be 0,2,3,4,5 — got {args.inf_flavor_prior}"
        )

    if args.inf_flavor_posterior not in (0, 2, 3, 4, 5):
        errors.append(
            f"inf_flavor_posterior must be 0,2,3,4,5 — got {args.inf_flavor_posterior}"
        )

    if args.inf_flavor_posterior == 4 and args.inf_flavor_prior == 4:
        errors.append(
            "RTPS (inf_flavor=4) should only be applied to posterior, not both"
        )

    if args.async_mode not in (0, 2, 4):
        errors.append(f"async_mode must be 0, 2, or 4 — got {args.async_mode}")

    if args.async_mode in (2, 4) and not args.adv_ens_command:
        errors.append(
            "adv_ens_command required when async_mode is 2 or 4"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def fmt_bool(val):
    """Format boolean for Fortran namelist. Must include dots."""
    return ".true." if val else ".false."


def fmt_str(val):
    """Format string for Fortran namelist. Must use single quotes."""
    if val.startswith("'") and val.endswith("'"):
        return val
    return f"'{val}'"


def fmt_arr(vals, fmt_func=str):
    """Format array for Fortran namelist (comma-separated)."""
    return ", ".join(fmt_func(v) for v in vals)


def generate_filter_nml(args, preset):
    """Generate &filter_nml block."""
    cutoff = args.cutoff if args.cutoff is not None else preset["default_cutoff"]

    lines = []
    lines.append("&filter_nml")
    lines.append(f"   async                    = {args.async_mode}")
    if args.adv_ens_command:
        lines.append(f"   adv_ens_command          = {fmt_str(args.adv_ens_command)}")
    lines.append(f"   ens_size                 = {args.ens_size}")
    lines.append(f"   obs_sequence_in_name     = 'obs_seq.out'")
    lines.append(f"   obs_sequence_out_name    = 'obs_seq.final'")
    lines.append(f"   init_time_days           = -1")
    lines.append(f"   init_time_seconds        = -1")
    lines.append(f"   first_obs_days           = -1")
    lines.append(f"   first_obs_seconds        = -1")
    lines.append(f"   last_obs_days            = -1")
    lines.append(f"   last_obs_seconds         = -1")
    lines.append(f"   num_output_state_members = {args.ens_size}")
    lines.append(f"   num_output_obs_members   = {args.ens_size}")
    lines.append(f"   output_interval          = 1")
    lines.append(f"   output_members           = {fmt_bool(True)}")
    lines.append(f"   output_mean              = {fmt_bool(True)}")
    lines.append(f"   output_sd                = {fmt_bool(True)}")
    lines.append(f"   stages_to_write          = 'preassim', 'analysis', 'output'")
    # Inflation — 2-element arrays: [prior, posterior]
    lines.append(f"   inf_flavor               = {args.inf_flavor_prior}, {args.inf_flavor_posterior}")
    lines.append(f"   inf_initial_from_restart = {fmt_bool(False)}, {fmt_bool(False)}")
    lines.append(f"   inf_sd_initial_from_restart = {fmt_bool(False)}, {fmt_bool(False)}")
    lines.append(f"   inf_initial              = {args.inf_initial_prior}, {args.inf_initial_posterior}")
    lines.append(f"   inf_sd_initial           = 0.6, 0.0")
    lines.append(f"   inf_damping              = {args.inf_damping}, 1.0")
    lines.append(f"   inf_lower_bound          = 1.0, 1.0")
    lines.append(f"   inf_upper_bound          = 1000000.0, 1000000.0")
    lines.append(f"   inf_sd_lower_bound       = 0.6, 0.6")
    lines.append(f"   inf_deterministic        = {fmt_bool(True)}, {fmt_bool(True)}")
    lines.append(f"   /")
    return "\n".join(lines)


def generate_assim_tools_nml(args, preset):
    """Generate &assim_tools_nml block."""
    cutoff = args.cutoff if args.cutoff is not None else preset["default_cutoff"]
    lines = []
    lines.append("&assim_tools_nml")
    lines.append(f"   cutoff                     = {cutoff}")
    lines.append(f"   sort_obs_inc               = {fmt_bool(False)}")
    lines.append(f"   spread_restoration         = {fmt_bool(False)}")
    lines.append(f"   sampling_error_correction  = {fmt_bool(args.sampling_error_correction)}")
    lines.append(f"   adaptive_localization_threshold = -1")
    lines.append(f"   output_localization_diagnostics = {fmt_bool(False)}")
    lines.append(f"   /")
    return "\n".join(lines)


def generate_model_nml(args, preset):
    """Generate &model_nml block from preset."""
    model_params = preset["model_nml"]
    if not model_params:
        return "&model_nml\n   /\n"
    lines = ["&model_nml"]
    for k, v in model_params.items():
        lines.append(f"   {k:30s} = {v}")
    lines.append("   /")
    return "\n".join(lines)


def generate_preprocess_nml(args, preset):
    """Generate &preprocess_nml block."""
    lines = []
    lines.append("&preprocess_nml")
    lines.append("   input_obs_def_mod_file  = '../../../observations/forward_operators/DEFAULT_obs_def_mod.F90'")
    lines.append("   output_obs_def_mod_file = '../../../observations/forward_operators/obs_def_mod.f90'")
    lines.append("   input_obs_qty_mod_file  = '../../../assimilation_code/modules/observations/DEFAULT_obs_kind_mod.F90'")
    lines.append("   output_obs_qty_mod_file = '../../../assimilation_code/modules/observations/obs_kind_mod.f90'")
    if preset["obs_types"]:
        obs_str = ",\n                               ".join(preset["obs_types"])
        lines.append(f"   obs_type_files          = {obs_str}")
    if preset["quantity_files"]:
        qty_str = ",\n                               ".join(preset["quantity_files"])
        lines.append(f"   quantity_files          = {qty_str}")
    lines.append("   overwrite_output        = .true.")
    lines.append("   /")
    return "\n".join(lines)


def generate_obs_sequence_nml():
    """Generate &obs_sequence_nml block."""
    return (
        "&obs_sequence_nml\n"
        "   write_binary_obs_sequence = .false.\n"
        "   read_binary_file_format   = 'native'\n"
        "   /\n"
    )


def generate_obs_kind_nml():
    """Generate &obs_kind_nml block."""
    return (
        "&obs_kind_nml\n"
        "   assimilate_these_obs_types = 'RAW_STATE_VARIABLE'\n"
        "   evaluate_these_obs_types   = ''\n"
        "   /\n"
    )


def generate_utilities_nml():
    """Generate &utilities_nml block."""
    return (
        "&utilities_nml\n"
        "   module_details = .false.\n"
        "   termlevel      = 2\n"
        "   logfilename    = 'dart_log.out'\n"
        "   nmlfilename    = 'dart_log.nml'\n"
        "   /\n"
    )


def generate_perfect_model_obs_nml():
    """Generate &perfect_model_obs_nml block."""
    return (
        "&perfect_model_obs_nml\n"
        "   read_input_state_from_file = .true.\n"
        "   single_file_in             = .true.\n"
        "   input_state_files          = 'perfect_input.nc'\n"
        "   write_output_state_to_file = .true.\n"
        "   single_file_out            = .true.\n"
        "   output_state_files         = 'perfect_output.nc'\n"
        "   obs_seq_in_file_name       = 'obs_seq.in'\n"
        "   obs_seq_out_file_name      = 'obs_seq.out'\n"
        "   init_time_days             = -1\n"
        "   init_time_seconds          = -1\n"
        "   first_obs_days             = -1\n"
        "   first_obs_seconds          = -1\n"
        "   last_obs_days              = -1\n"
        "   last_obs_seconds           = -1\n"
        "   async                      = 0\n"
        "   adv_ens_command            = './advance_model.csh'\n"
        "   trace_execution            = .true.\n"
        "   output_timestamps          = .true.\n"
        "   /\n"
    )


def generate_cov_cutoff_nml():
    """Generate &cov_cutoff_nml block."""
    return (
        "&cov_cutoff_nml\n"
        "   select_localization = 1\n"
        "   /\n"
    )


def generate_location_nml(location_type):
    """Generate &location_nml block."""
    if location_type == "threed_sphere":
        return (
            "&location_nml\n"
            "   horiz_dist_only = .true.\n"
            "   /\n"
        )
    return "&location_nml\n   /\n"


def process(args):
    """Generate complete input.nml content."""
    preset = MODEL_PRESETS.get(args.model, MODEL_PRESETS["custom"])

    sections = []
    sections.append(generate_filter_nml(args, preset))
    sections.append(generate_perfect_model_obs_nml())
    sections.append(generate_assim_tools_nml(args, preset))
    sections.append(generate_model_nml(args, preset))
    sections.append(generate_preprocess_nml(args, preset))
    sections.append(generate_obs_sequence_nml())
    sections.append(generate_obs_kind_nml())
    sections.append(generate_utilities_nml())
    sections.append(generate_cov_cutoff_nml())
    sections.append(generate_location_nml(preset["location"]))

    return "\n\n".join(sections) + "\n"


def validate_outputs(content, args):
    """Post-processing validation of generated namelist."""
    warnings = []

    # Check that all namelists are properly terminated
    ampersand_count = content.count("&")
    slash_count = content.count("\n   /")
    if ampersand_count != slash_count:
        warnings.append(
            f"CRITICAL: {ampersand_count} namelist blocks but {slash_count} "
            f"terminators. Fortran will fail to parse."
        )

    # Check for common format errors
    if '".true."' in content or '"' in content:
        warnings.append(
            "CRITICAL: Double quotes found. Fortran namelists require "
            "single quotes for strings."
        )

    # Warn about localization for small models
    preset = MODEL_PRESETS.get(args.model, MODEL_PRESETS["custom"])
    cutoff = args.cutoff if args.cutoff is not None else preset["default_cutoff"]
    if cutoff > 100 and args.model not in ("lorenz_63",):
        warnings.append(
            f"WARNING: cutoff={cutoff} is very large. This effectively disables "
            f"localization, which may cause filter divergence for realistic models."
        )

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Generate DART input.nml namelist file"
    )
    parser.add_argument("--model", default="lorenz_63",
                        help="Model preset: lorenz_63, lorenz_96, custom")
    parser.add_argument("--ens_size", type=int, default=20,
                        help="Ensemble size (default: 20)")
    parser.add_argument("--cutoff", type=float, default=None,
                        help="Localization cutoff (units depend on location module)")
    parser.add_argument("--inf_flavor_prior", type=int, default=0,
                        help="Prior inflation: 0=none, 2=adaptive, 3=uniform, 4=RTPS, 5=enhanced")
    parser.add_argument("--inf_flavor_posterior", type=int, default=0,
                        help="Posterior inflation flavor")
    parser.add_argument("--inf_initial_prior", type=float, default=1.0,
                        help="Initial prior inflation value")
    parser.add_argument("--inf_initial_posterior", type=float, default=1.0,
                        help="Initial posterior inflation value")
    parser.add_argument("--inf_damping", type=float, default=0.9,
                        help="Inflation damping factor (0.5-1.0)")
    parser.add_argument("--async_mode", type=int, default=0,
                        help="Model advance mode: 0=Fortran, 2=shell, 4=parallel")
    parser.add_argument("--adv_ens_command", default="",
                        help="Shell command for async model advance")
    parser.add_argument("--sampling_error_correction", action="store_true",
                        help="Enable sampling error correction")
    parser.add_argument("--output", required=True,
                        help="Output input.nml file path")

    args = parser.parse_args()

    # Step 1: validate
    validate_inputs(args)

    # Step 2: process
    content = process(args)

    # Step 3: validate output
    warnings = validate_outputs(content, args)

    # Step 4: write
    with open(args.output, "w") as f:
        f.write(content)

    # Step 5: report
    result = {
        "status": "success",
        "output_file": args.output,
        "model": args.model,
        "ens_size": args.ens_size,
        "inf_flavor": [args.inf_flavor_prior, args.inf_flavor_posterior],
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2), file=sys.stderr)
    print(f"Wrote input.nml to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
