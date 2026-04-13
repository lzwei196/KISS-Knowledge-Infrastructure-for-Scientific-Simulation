#!/usr/bin/env python3
"""
generate_cism_config.py -- Generate CISM .config files from parameters.

Creates the INI-style configuration file required by cism_driver. The config
file contains sections: [grid], [time], [options], [ho_options], [parameters],
[CF default], [CF input], [CF output], and optionally [CF forcing], [sigma],
[isostasy], [GTHF].

CRITICAL NOTES:
  - Section names are case-sensitive and must match exactly (dt_014 trap)
  - Grid spacing (dew, dns) must be in METERS, not km (dt_006 trap)
  - Geothermal heat flux is NEGATIVE for upward (dt_003 trap)
  - default_flwa typical range: 1e-18 to 1e-15 Pa^-n s^-1 (dt_002 trap)
  - When dycore=2 (Glissade), evolution must be 3 or 4, not 0 (dt_007 trap)
  - which_ho_sparse=4 requires Trilinos; use 3 for PCG fallback (dt_005 trap)

Usage:
    # Dome test (SIA)
    python generate_cism_config.py --test dome --dycore 0 --output dome.config

    # Higher-order Greenland
    python generate_cism_config.py --ewn 301 --nsn 561 --upn 11 --dew 5000 \
        --tstart 0 --tend 1000 --dt 0.5 --dycore 2 --ho_approx 4 \
        --input_nc greenland.nc --output greenland.config

    # From JSON parameter file
    python generate_cism_config.py --from_json params.json --output run.config
"""

import argparse
import json
import sys
import os


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_params(params):
    """Validate configuration parameters before writing."""
    errors = []
    warnings = []

    # dt_006: grid spacing check
    if params.get("dew", 0) < 10:
        errors.append(
            f"dew={params['dew']} too small -- must be in meters, not km (dt_006)"
        )
    if params.get("dns", 0) < 10:
        errors.append(
            f"dns={params['dns']} too small -- must be in meters, not km (dt_006)"
        )

    # dt_002: flow rate factor
    flwa = params.get("default_flwa", 1e-16)
    if flwa < 1e-25:
        warnings.append(
            f"default_flwa={flwa} extremely small -- no ice dynamics (dt_002)"
        )
    if flwa > 1e-10:
        warnings.append(
            f"default_flwa={flwa} extremely large -- unstable flow"
        )

    # dt_003: geothermal sign
    geo = params.get("geothermal", -42e-3)
    if geo > 0:
        errors.append(
            f"geothermal={geo} positive -- CISM requires NEGATIVE = upward (dt_003)"
        )

    # dt_007: Glissade + evolution=0
    if params.get("dycore", 0) == 2 and params.get("evolution", 3) == 0:
        errors.append(
            "dycore=2 (Glissade) with evolution=0 (pseudo-diffusion) -- "
            "use evolution=3 or 4 (dt_007)"
        )

    # dt_005: Trilinos check
    if params.get("which_ho_sparse", 3) == 4:
        warnings.append(
            "which_ho_sparse=4 requires Trilinos. If not built with Trilinos, "
            "use 3 (Glissade PCG) (dt_005)"
        )

    # dt_009: output frequency
    tend = params.get("tend", 0)
    tstart = params.get("tstart", 0)
    dt = params.get("dt", 1)
    freq = params.get("output_freq", 1)
    if dt > 0 and freq > 0:
        total_steps = (tend - tstart) / dt
        if freq > total_steps:
            warnings.append(
                f"output frequency={freq} > total steps={total_steps:.0f} -- "
                f"no output will be written (dt_009)"
            )

    for e in errors:
        print(f"VALIDATION ERROR: {e}")
    for w in warnings:
        print(f"WARNING: {w}")

    if errors:
        sys.exit(1)
    print("Parameter validation passed.")


# ---------------------------------------------------------------------------
# Config writer
# ---------------------------------------------------------------------------

def write_config(output_path, params):
    """Write CISM .config file."""
    lines = []

    # [grid]
    lines.append("[grid]")
    lines.append(f"upn = {params.get('upn', 11)}")
    lines.append(f"ewn = {params.get('ewn', 31)}")
    lines.append(f"nsn = {params.get('nsn', 31)}")
    lines.append(f"dew = {params.get('dew', 2000.0)}")
    lines.append(f"dns = {params.get('dns', 2000.0)}")
    lines.append("")

    # [time]
    lines.append("[time]")
    lines.append(f"tstart = {params.get('tstart', 0.0)}")
    lines.append(f"tend = {params.get('tend', 200000.0)}")
    lines.append(f"dt = {params.get('dt', 1.0)}")
    dt_diag = params.get("dt_diag", params.get("dt", 1.0))
    lines.append(f"dt_diag = {dt_diag}")
    lines.append(f"ntem = {params.get('ntem', 1)}")
    lines.append(f"ndiag = {params.get('ndiag', 1)}")
    if "idiag" in params:
        lines.append(f"idiag = {params['idiag']}")
    if "jdiag" in params:
        lines.append(f"jdiag = {params['jdiag']}")
    lines.append("")

    # [options]
    dycore = params.get("dycore", 0)
    lines.append("[options]")
    lines.append(f"dycore = {dycore}")
    lines.append(f"temperature = {params.get('temperature', 1)}")
    lines.append(f"flow_law = {params.get('flow_law', 0)}")

    # Auto-set evolution for Glissade
    if dycore == 2:
        evolution = params.get("evolution", 3)
        if evolution == 0:
            evolution = 3  # Fix dt_007
    else:
        evolution = params.get("evolution", 0)
    lines.append(f"evolution = {evolution}")

    lines.append(f"marine_margin = {params.get('marine_margin', 0)}")
    lines.append(f"basal_water = {params.get('basal_water', 0)}")
    lines.append(f"isostasy = {params.get('isostasy', 0)}")
    if "slip_coeff" in params:
        lines.append(f"slip_coeff = {params['slip_coeff']}")
    if "basal_mass_balance" in params:
        lines.append(f"basal_mass_balance = {params['basal_mass_balance']}")
    lines.append("")

    # [ho_options] - only when dycore=2
    if dycore == 2:
        lines.append("[ho_options]")
        lines.append(f"which_ho_approx = {params.get('which_ho_approx', 2)}")
        lines.append(f"which_ho_babc = {params.get('which_ho_babc', 4)}")
        lines.append(f"which_ho_efvs = {params.get('which_ho_efvs', 2)}")

        # dt_005: fallback to PCG if no Trilinos
        sparse = params.get("which_ho_sparse", 3)
        lines.append(f"which_ho_sparse = {sparse}")
        lines.append(f"which_ho_nonlinear = {params.get('which_ho_nonlinear', 0)}")

        if "which_ho_precond" in params:
            lines.append(f"which_ho_precond = {params['which_ho_precond']}")
        if "glissade_maxiter" in params:
            lines.append(f"glissade_maxiter = {params['glissade_maxiter']}")
        lines.append("")

    # [parameters]
    lines.append("[parameters]")
    lines.append(f"default_flwa = {params.get('default_flwa', 1.0e-16)}")
    lines.append(f"ice_limit = {params.get('ice_limit', 1.0)}")

    geo = params.get("geothermal", -42.0e-3)
    if geo > 0:
        geo = -geo  # Fix dt_003
    lines.append(f"geothermal = {geo}")

    if "flow_enhancement_factor" in params:
        lines.append(f"flow_enhancement_factor = {params['flow_enhancement_factor']}")
    if "beta_grounded_min" in params:
        lines.append(f"beta_grounded_min = {params['beta_grounded_min']}")
    if "btrac_const" in params:
        lines.append(f"btrac_const = {params['btrac_const']}")
    if "periodic_offset_ew" in params:
        lines.append(f"periodic_offset_ew = {params['periodic_offset_ew']}")
    if "periodic_offset_ns" in params:
        lines.append(f"periodic_offset_ns = {params['periodic_offset_ns']}")
    lines.append("")

    # [CF default]
    lines.append("[CF default]")
    lines.append(f"title = {params.get('title', 'CISM simulation')}")
    if "comment" in params:
        lines.append(f"comment = {params['comment']}")
    lines.append("")

    # [CF input]
    input_nc = params.get("input_nc", "input.nc")
    lines.append("[CF input]")
    lines.append(f"name = {input_nc}")
    lines.append(f"time = {params.get('input_time', 1)}")
    lines.append("")

    # [CF output]
    output_nc = params.get("output_nc", "output.nc")
    lines.append("[CF output]")
    lines.append(f"name = {output_nc}")
    lines.append(f"frequency = {params.get('output_freq', 1000)}")
    output_vars = params.get(
        "output_vars",
        "thk usurf topg uvel vvel temp acab bmlt velnorm"
    )
    lines.append(f"variables = {output_vars}")
    if "xtype" in params:
        lines.append(f"xtype = {params['xtype']}")
    lines.append("")

    # [CF forcing] (optional)
    if "forcing_nc" in params:
        lines.append("[CF forcing]")
        lines.append(f"name = {params['forcing_nc']}")
        lines.append("")

    # [sigma] (optional)
    if "sigma_levels" in params:
        lines.append("[sigma]")
        lines.append(f"sigma_levels = {params['sigma_levels']}")
        lines.append("")

    # [isostasy] (optional)
    if params.get("isostasy", 0) == 1:
        lines.append("[isostasy]")
        lines.append(f"lithosphere = {params.get('lithosphere', 1)}")
        lines.append(f"asthenosphere = {params.get('asthenosphere', 1)}")
        lines.append("")

    config_text = "\n".join(lines) + "\n"

    with open(output_path, "w") as f:
        f.write(config_text)

    print(f"Written config: {output_path}")
    print(f"  Sections: {sum(1 for l in lines if l.startswith('['))}")
    return config_text


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

def get_preset(name):
    """Return preset parameter dictionaries for standard test cases."""
    presets = {
        "dome": {
            "ewn": 31, "nsn": 31, "upn": 11,
            "dew": 2000.0, "dns": 2000.0,
            "tstart": 0.0, "tend": 200000.0, "dt": 10.0,
            "dycore": 0, "temperature": 1, "flow_law": 0,
            "evolution": 0, "default_flwa": 1.0e-16,
            "geothermal": -42.0e-3,
            "input_nc": "dome.nc", "output_nc": "dome.out.nc",
            "output_freq": 10000, "title": "CISM dome test case",
            "output_vars": "thk usurf uvel vvel temp acab bmlt",
        },
        "dome_ho": {
            "ewn": 31, "nsn": 31, "upn": 11,
            "dew": 2000.0, "dns": 2000.0,
            "tstart": 0.0, "tend": 200000.0, "dt": 1.0,
            "dycore": 2, "temperature": 1, "flow_law": 0,
            "evolution": 3, "default_flwa": 1.0e-16,
            "which_ho_approx": 2, "which_ho_babc": 4,
            "which_ho_efvs": 2, "which_ho_sparse": 3,
            "which_ho_nonlinear": 0,
            "geothermal": -42.0e-3,
            "input_nc": "dome.nc", "output_nc": "dome_ho.out.nc",
            "output_freq": 10000, "title": "CISM dome HO test case",
            "output_vars": "thk usurf uvel vvel velnorm temp acab bmlt",
        },
        "shelf": {
            "ewn": 41, "nsn": 41, "upn": 5,
            "dew": 5000.0, "dns": 5000.0,
            "tstart": 0.0, "tend": 0.0, "dt": 1.0,
            "dycore": 2, "temperature": 0, "flow_law": 0,
            "evolution": 3,
            "which_ho_approx": 1, "which_ho_babc": 5,
            "which_ho_efvs": 2, "which_ho_sparse": 3,
            "default_flwa": 5.7e-18,
            "input_nc": "shelf.nc", "output_nc": "shelf.out.nc",
            "output_freq": 1, "title": "CISM shelf test case",
        },
        "stream": {
            "ewn": 50, "nsn": 12, "upn": 5,
            "dew": 5000.0, "dns": 5000.0,
            "tstart": 0.0, "tend": 0.0, "dt": 1.0,
            "dycore": 2, "temperature": 0, "flow_law": 0,
            "evolution": 3,
            "which_ho_approx": 4, "which_ho_babc": 15,
            "which_ho_efvs": 2, "which_ho_sparse": 3,
            "default_flwa": 5.7e-18,
            "input_nc": "stream.nc", "output_nc": "stream.out.nc",
            "output_freq": 1, "title": "CISM stream test case",
        },
    }
    return presets.get(name, {})


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_config(path):
    """Validate the generated config file by re-reading it."""
    required_sections = {"grid", "time", "options", "parameters",
                         "CF default", "CF input", "CF output"}
    found_sections = set()

    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                found_sections.add(line[1:-1])

    missing = required_sections - found_sections
    if missing:
        print(f"WARNING: Missing config sections: {missing}")
        return False

    print(f"Config validation passed: {path}")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate CISM configuration files"
    )
    parser.add_argument("--test", choices=["dome", "dome_ho", "shelf", "stream"],
                        help="Use preset test case")
    parser.add_argument("--from_json", help="Load params from JSON file")
    parser.add_argument("--output", default="cism.config",
                        help="Output config file path")

    # Override individual parameters
    parser.add_argument("--ewn", type=int)
    parser.add_argument("--nsn", type=int)
    parser.add_argument("--upn", type=int)
    parser.add_argument("--dew", type=float)
    parser.add_argument("--dns", type=float)
    parser.add_argument("--tstart", type=float)
    parser.add_argument("--tend", type=float)
    parser.add_argument("--dt", type=float)
    parser.add_argument("--dycore", type=int)
    parser.add_argument("--ho_approx", type=int, dest="which_ho_approx")
    parser.add_argument("--input_nc")
    parser.add_argument("--output_nc")
    parser.add_argument("--default_flwa", type=float)
    parser.add_argument("--geothermal", type=float)

    args = parser.parse_args()

    # Build params dict
    if args.test:
        params = get_preset(args.test)
    elif args.from_json:
        with open(args.from_json) as f:
            params = json.load(f)
    else:
        params = get_preset("dome")  # default

    # Apply overrides from command line
    for key in ["ewn", "nsn", "upn", "dew", "dns", "tstart", "tend", "dt",
                "dycore", "which_ho_approx", "input_nc", "output_nc",
                "default_flwa", "geothermal"]:
        val = getattr(args, key, None)
        if val is not None:
            params[key] = val

    # Validate -> Write -> Validate output
    validate_params(params)
    write_config(args.output, params)
    validate_config(args.output)


if __name__ == "__main__":
    main()
