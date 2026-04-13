#!/usr/bin/env python3
"""
convert_fates_params.py — FATES Parameter File Validator and Converter

Reads a FATES JSON parameter file, validates parameter ranges and units,
and optionally modifies parameters for a target PFT configuration.

Follows validate → process → validate pattern.

Usage:
    python convert_fates_params.py --fin fates_params_default.json --operation validate
    python convert_fates_params.py --fin fates_params_default.json --operation modify \
        --param fates_leaf_vcmax25top --pft-index 0 --value 65.0 --fout custom.json
    python convert_fates_params.py --fin fates_params_default.json --operation list
    python convert_fates_params.py --fin fates_params_default.json --operation query \
        --param fates_leaf_vcmax25top
"""

import argparse
import json
import os
import sys
import copy
from typing import Dict, List, Any, Optional, Tuple

# ─── Physical range checks for key parameters ───────────────────────────────
PARAMETER_RANGES = {
    # Allometry
    "fates_allom_d2h1":      (0.01, 200.0, "m", "DBH-to-height coefficient"),
    "fates_allom_d2h2":      (-2.0, 2.0, "-", "DBH-to-height exponent"),
    "fates_allom_d2bl1":     (0.001, 10.0, "kgC", "DBH-to-leaf biomass coefficient"),
    "fates_allom_dbh_maxheight": (1.0, 500.0, "cm", "DBH at max height"),
    "fates_wood_density":    (0.1, 1.5, "g/cm³", "Wood density"),

    # Photosynthesis
    "fates_leaf_vcmax25top":  (5.0, 150.0, "µmol/m²/s", "Max carboxylation rate at 25°C"),
    "fates_leaf_slatop":      (0.001, 0.1, "m²/gC", "Specific leaf area at canopy top"),

    # Turnover and mortality
    "fates_turnover_leaf":    (0.3, 20.0, "yr", "Leaf longevity"),
    "fates_turnover_fnrt":    (0.3, 20.0, "yr", "Fine root longevity"),
    "fates_mort_scalar_cstarvation": (0.01, 20.0, "-", "C-starvation mortality scalar"),
    "fates_mort_scalar_hydrfailure": (0.01, 20.0, "-", "Hydraulic failure mortality scalar"),
    "fates_mort_bmort":       (0.0, 0.1, "1/yr", "Background mortality rate"),

    # Fire
    "fates_fire_nignitions":  (0.0, 1.0, "ignitions/km²/day", "Lightning ignition density"),
    "fates_fire_alpha_SH":    (0.0, 1.0, "-", "Scorch height parameter"),

    # Recruitment
    "fates_recruit_seed_supplement": (0.0, 10.0, "kgC/m²/yr", "External seed supplement"),
    "fates_recruit_hgt_min":  (0.01, 5.0, "m", "Minimum recruit height"),

    # Phenology
    "fates_phen_drought_threshold": (-10.0, 0.0, "MPa", "Drought phenology threshold"),
    "fates_phen_cold_size_threshold": (0.0, 100.0, "cm", "Cold deciduous size threshold"),
}

# ─── Expected dimensions ────────────────────────────────────────────────────
EXPECTED_DIMENSIONS = {
    "fates_pft": 14,
    "fates_NCWD": 4,
    "fates_litterclass": 6,
    "fates_hydr_organs": 4,
    "fates_plant_organs": 4,
}

PFT_NAMES = [
    "broadleaf_evergreen_tropical",
    "needleleaf_evergreen_extratropical",
    "needleleaf_colddecid_extratropical",
    "broadleaf_evergreen_extratropical",
    "broadleaf_hydrodecid_tropical",
    "broadleaf_colddecid_extratropical",
    "broadleaf_evergreen_shrub",
    "broadleaf_hydrodecid_shrub",
    "broadleaf_colddecid_shrub",
    "arctic_c3_grass",
    "cool_c3_grass",
    "c4_grass",
    "c3_crop",
    "c4_crop",
]


def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Stage 1: Validate command-line inputs and file existence."""
    errors = []

    if not os.path.isfile(args.fin):
        errors.append(f"Input file not found: {args.fin}")

    if args.operation == "modify":
        if not args.param:
            errors.append("--param required for modify operation")
        if args.value is None:
            errors.append("--value required for modify operation")
        if args.pft_index is not None and (args.pft_index < 0 or args.pft_index >= 14):
            errors.append(f"--pft-index must be 0-13, got {args.pft_index}")
        if not args.fout:
            errors.append("--fout required for modify operation")

    if args.operation == "query" and not args.param:
        errors.append("--param required for query operation")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2),
              file=sys.stderr)
        sys.exit(1)

    return errors


def load_param_file(filepath: str) -> Dict[str, Any]:
    """Load a FATES JSON parameter file."""
    with open(filepath, "r") as f:
        data = json.load(f)
    return data


def validate_parameter_ranges(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Check all parameters against known physical ranges."""
    warnings = []
    params = data.get("parameters", {})

    for pname, (lo, hi, unit, desc) in PARAMETER_RANGES.items():
        if pname not in params:
            continue
        pdata = params[pname]
        values = pdata.get("data", [])

        # Flatten nested lists
        flat = []
        if isinstance(values, list):
            for v in values:
                if isinstance(v, list):
                    flat.extend(v)
                else:
                    flat.append(v)
        else:
            flat = [values]

        for i, val in enumerate(flat):
            if val is None:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            if fval < lo or fval > hi:
                warnings.append({
                    "parameter": pname,
                    "index": i,
                    "value": fval,
                    "expected_range": f"[{lo}, {hi}]",
                    "unit": unit,
                    "description": desc,
                    "severity": "warning",
                })
    return warnings


def validate_dimensions(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Check dimension sizes against expected values."""
    warnings = []
    dims = data.get("dimensions", {})

    for dname, expected in EXPECTED_DIMENSIONS.items():
        actual = dims.get(dname)
        if actual is not None and actual != expected:
            warnings.append({
                "dimension": dname,
                "expected": expected,
                "actual": actual,
                "severity": "info",
                "note": f"Non-standard {dname} size (expected {expected}, got {actual})",
            })
    return warnings


def validate_pft_consistency(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Check that PFT-dimensioned parameters have correct array lengths."""
    warnings = []
    params = data.get("parameters", {})
    n_pft = data.get("dimensions", {}).get("fates_pft", 14)

    for pname, pdata in params.items():
        dims = pdata.get("dims", [])
        if "fates_pft" in dims:
            values = pdata.get("data", [])
            if isinstance(values, list):
                # Single-dimension PFT parameter
                if len(dims) == 1 and len(values) != n_pft:
                    warnings.append({
                        "parameter": pname,
                        "expected_length": n_pft,
                        "actual_length": len(values),
                        "severity": "error",
                        "note": f"PFT array length mismatch",
                    })
    return warnings


def list_parameters(data: Dict[str, Any]) -> str:
    """List all parameters with their dimensions and units."""
    params = data.get("parameters", {})
    lines = []
    lines.append(f"{'Parameter':<50} {'Dims':<30} {'Units':<20} {'Type':<10}")
    lines.append("-" * 110)

    for pname in sorted(params.keys()):
        pdata = params[pname]
        dims = ", ".join(pdata.get("dims", []))
        units = pdata.get("units", "")
        dtype = pdata.get("dtype", "")
        lines.append(f"{pname:<50} {dims:<30} {units:<20} {dtype:<10}")

    return "\n".join(lines)


def query_parameter(data: Dict[str, Any], param_name: str) -> str:
    """Query a specific parameter with full details."""
    params = data.get("parameters", {})
    if param_name not in params:
        return f"Parameter '{param_name}' not found in file."

    pdata = params[param_name]
    lines = [
        f"Parameter: {param_name}",
        f"  Long name: {pdata.get('long_name', 'N/A')}",
        f"  Units: {pdata.get('units', 'N/A')}",
        f"  Type: {pdata.get('dtype', 'N/A')}",
        f"  Dimensions: {pdata.get('dims', [])}",
        f"  Data: {pdata.get('data', [])}",
    ]

    # Add PFT labels if appropriate
    if "fates_pft" in pdata.get("dims", []) and len(pdata.get("dims", [])) == 1:
        values = pdata.get("data", [])
        lines.append("  Per-PFT values:")
        for i, (name, val) in enumerate(zip(PFT_NAMES, values)):
            lines.append(f"    PFT {i} ({name}): {val}")

    # Check against known ranges
    if param_name in PARAMETER_RANGES:
        lo, hi, unit, desc = PARAMETER_RANGES[param_name]
        lines.append(f"  Physical range: [{lo}, {hi}] {unit}")

    return "\n".join(lines)


def modify_parameter(data: Dict[str, Any], param_name: str,
                     pft_index: Optional[int], value: float) -> Dict[str, Any]:
    """Modify a parameter value in the data structure."""
    result = copy.deepcopy(data)
    params = result.get("parameters", {})

    if param_name not in params:
        print(f"Error: Parameter '{param_name}' not found.", file=sys.stderr)
        sys.exit(1)

    pdata = params[param_name]

    if pft_index is not None:
        # Modify a specific PFT index
        if isinstance(pdata["data"], list) and pft_index < len(pdata["data"]):
            old_val = pdata["data"][pft_index]
            pdata["data"][pft_index] = value
            print(f"Modified {param_name}[{pft_index}]: {old_val} → {value}",
                  file=sys.stderr)
        else:
            print(f"Error: Index {pft_index} out of range for {param_name}.",
                  file=sys.stderr)
            sys.exit(1)
    else:
        # Modify scalar or all values
        if isinstance(pdata["data"], list):
            old_val = pdata["data"]
            pdata["data"] = [value] * len(pdata["data"])
            print(f"Modified all {param_name} values to {value}", file=sys.stderr)
        else:
            old_val = pdata["data"]
            pdata["data"] = value
            print(f"Modified {param_name}: {old_val} → {value}", file=sys.stderr)

    return result


def validate_outputs(result: Any, operation: str) -> List[str]:
    """Stage 3: Validate operation results."""
    warnings = []

    if operation == "validate" and isinstance(result, dict):
        range_warnings = result.get("range_warnings", [])
        dim_warnings = result.get("dimension_warnings", [])
        pft_warnings = result.get("pft_warnings", [])

        if len(range_warnings) > 0:
            warnings.append(
                f"{len(range_warnings)} parameters outside expected physical ranges")
        if any(w.get("severity") == "error" for w in pft_warnings):
            warnings.append("PFT array length mismatches detected — parameter file may be corrupt")

    if operation == "modify" and isinstance(result, dict):
        # Re-validate the modified file
        range_w = validate_parameter_ranges(result)
        if range_w:
            for w in range_w:
                warnings.append(
                    f"Modified value for {w['parameter']}[{w['index']}] = {w['value']} "
                    f"outside range {w['expected_range']} {w['unit']}")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="FATES parameter file validator and converter")
    parser.add_argument("--fin", required=True, help="Input JSON parameter file")
    parser.add_argument("--fout", help="Output JSON parameter file (for modify)")
    parser.add_argument("--operation", required=True,
                        choices=["validate", "list", "query", "modify"],
                        help="Operation to perform")
    parser.add_argument("--param", help="Parameter name (for query/modify)")
    parser.add_argument("--pft-index", type=int, default=None,
                        help="PFT index 0-13 (for modify)")
    parser.add_argument("--value", type=float, default=None,
                        help="New value (for modify)")
    parser.add_argument("--report", help="Write validation report to JSON file")
    args = parser.parse_args()

    # Stage 1: Validate inputs
    validate_inputs(args)

    # Stage 2: Process
    data = load_param_file(args.fin)

    if args.operation == "validate":
        range_warnings = validate_parameter_ranges(data)
        dim_warnings = validate_dimensions(data)
        pft_warnings = validate_pft_consistency(data)

        result = {
            "status": "success",
            "file": args.fin,
            "n_parameters": len(data.get("parameters", {})),
            "dimensions": data.get("dimensions", {}),
            "range_warnings": range_warnings,
            "dimension_warnings": dim_warnings,
            "pft_warnings": pft_warnings,
            "total_warnings": len(range_warnings) + len(dim_warnings) + len(pft_warnings),
        }

        if args.report:
            with open(args.report, "w") as f:
                json.dump(result, f, indent=2)
            print(f"Report written to {args.report}", file=sys.stderr)

        print(json.dumps(result, indent=2))
        output_warnings = validate_outputs(result, "validate")

    elif args.operation == "list":
        output = list_parameters(data)
        print(output)
        output_warnings = []

    elif args.operation == "query":
        output = query_parameter(data, args.param)
        print(output)
        output_warnings = []

    elif args.operation == "modify":
        modified = modify_parameter(data, args.param, args.pft_index, args.value)
        with open(args.fout, "w") as f:
            json.dump(modified, f, indent=2)
        print(f"Modified file written to {args.fout}", file=sys.stderr)

        output_warnings = validate_outputs(modified, "modify")

    # Print warnings
    if output_warnings:
        print("\n--- Output Validation Warnings ---", file=sys.stderr)
        for w in output_warnings:
            print(f"  WARNING: {w}", file=sys.stderr)

    summary = {
        "status": "success",
        "operation": args.operation,
        "input_file": args.fin,
        "output_file": args.fout,
        "warnings": output_warnings,
    }
    print(json.dumps(summary, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
