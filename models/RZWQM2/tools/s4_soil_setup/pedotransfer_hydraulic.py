#!/usr/bin/env python3
"""
pedotransfer_hydraulic.py
=========================
Estimate Brooks-Corey hydraulic parameters from soil texture class or
from measured water retention values.

Uses soil_default_setter() for texture-based defaults, and the estimation
functions pore_size_distribution_estimate(), B_estimate(),
bubbling_pressure_estimate(), C2_estimate(), N2_estimate(), fc10_estimate()
from rzwqm_file.py.

Two modes of operation:
  MODE 1 (texture only): Provide texture_class to get default parameters.
  MODE 2 (measured):     Provide texture_class + measured fc33, fc15, ws, wr,
                         ksat to compute refined Brooks-Corey parameters.

Inputs:
    texture_class   - USDA texture class (required)
    fc33            - Field capacity at 333 cm (optional, for mode 2)
    fc15            - Wilting point at 15000 cm (optional, for mode 2)
    ws              - Saturated water content (optional, for mode 2)
    wr              - Residual water content (optional, for mode 2)
    ksat            - Saturated hydraulic conductivity cm/hr (optional, for mode 2)

Outputs:
    Dictionary with Brooks-Corey hydraulic parameters:
        ws, wr, bubbling_pressure, pore_size_dist, fc33, fc10, fc15, ksat,
        N2, B, C2

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
TEXTURE_CLASS = ""      # USDA texture class (required)
FC33 = ""               # Field capacity at 1/3 bar (optional)
FC15 = ""               # Wilting point at 15 bar (optional)
WS = ""                 # Saturated water content (optional)
WR = ""                 # Residual water content (optional)
KSAT = ""               # Saturated hydraulic conductivity cm/hr (optional)

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))

VALID_TEXTURE_CLASSES = [
    'sand', 'loamy sand', 'sandy loam', 'loam', 'siltyloam', 'silt loam',
    'silt', 'sandy clay loam', 'clay loam', 'silty clay loam ',
    'sandy clay', 'silty clay', 'clay'
]


def _parse_optional_float(val, name):
    """Parse a value that may be empty/None. Returns (value_or_None, error_or_None)."""
    if val is None or val == '' or val == 'None':
        return None, None
    try:
        return float(val), None
    except (ValueError, TypeError):
        return None, f"{name} '{val}' is not a valid number."


def validate_inputs(texture_class, fc33_str, fc15_str, ws_str, wr_str, ksat_str):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not texture_class:
        errors.append("TEXTURE_CLASS is required.")

    # Normalize texture class for lookup
    tc_normalized = texture_class.strip().lower() if texture_class else ''

    # Parse optional measured values
    fc33, e = _parse_optional_float(fc33_str, 'FC33')
    if e:
        errors.append(e)
    fc15, e = _parse_optional_float(fc15_str, 'FC15')
    if e:
        errors.append(e)
    ws, e = _parse_optional_float(ws_str, 'WS')
    if e:
        errors.append(e)
    wr, e = _parse_optional_float(wr_str, 'WR')
    if e:
        errors.append(e)
    ksat, e = _parse_optional_float(ksat_str, 'KSAT')
    if e:
        errors.append(e)

    # Determine mode
    measured_vals = [fc33, fc15, ws, wr, ksat]
    has_any_measured = any(v is not None for v in measured_vals)
    has_all_measured = all(v is not None for v in measured_vals)

    mode = 'default'
    if has_any_measured:
        if not has_all_measured:
            errors.append(
                "For measured mode, all of fc33, fc15, ws, wr, ksat must be provided. "
                "Missing values will be filled from texture defaults."
            )
            # Not an error; we'll fill from defaults. Clear this.
            errors = [e for e in errors if 'must be provided' not in e]
        mode = 'measured'

    # Validate physical constraints on measured values
    if fc33 is not None and fc15 is not None:
        if fc15 > fc33:
            errors.append(f"FC15 ({fc15}) should not exceed FC33 ({fc33}).")
    if ws is not None and wr is not None:
        if wr >= ws:
            errors.append(f"WR ({wr}) must be less than WS ({ws}).")
    if ksat is not None and ksat <= 0:
        errors.append(f"KSAT must be positive, got {ksat}.")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'texture_class': tc_normalized,
        'fc33': fc33,
        'fc15': fc15,
        'ws': ws,
        'wr': wr,
        'ksat': ksat,
        'mode': mode
    }


def process(args):
    """
    Estimate Brooks-Corey parameters.
    Returns (success, error_msg, result_dict).
    """
    from rzwqm_file import (
        soil_default_setter,
        pore_size_distribution_estimate,
        B_estimate,
        bubbling_pressure_estimate,
        C2_estimate,
        N2_estimate,
        fc10_estimate
    )

    texture_class = args['texture_class']
    mode = args['mode']

    try:
        # Get default values for the texture class
        # Handle texture class key variations in the default dict
        try:
            defaults = soil_default_setter(texture_class)
        except KeyError:
            # Try common alternative keys
            alt_keys = {
                'silt loam': 'siltyloam',
                'siltyloam': 'silt loam',
                'silty clay loam': 'silty clay loam ',  # note trailing space in original
            }
            alt = alt_keys.get(texture_class)
            if alt:
                defaults = soil_default_setter(alt)
            else:
                return False, f"Unknown texture class: '{texture_class}'", None

        if mode == 'default':
            # Return the defaults directly, plus computed N2
            psd = defaults['pore_size_dist']
            n2 = N2_estimate(psd)
            b = B_estimate(defaults['fc33'], defaults['wr'], psd)
            bp = defaults['bubbling_pressure']
            fc10 = fc10_estimate(defaults['ws'], defaults['wr'], bp, psd)
            # N1 defaults to 0 in the original code
            c2 = C2_estimate(bp, psd, defaults['ksat'], 0)

            result = {
                'mode': 'texture_defaults',
                'texture_class': texture_class,
                'ws': defaults['ws'],
                'wr': defaults['wr'],
                'bubbling_pressure': round(bp, 4),
                'pore_size_dist': round(psd, 4),
                'fc33': round(defaults['fc33'], 4),
                'fc15': round(defaults['fc15'], 4),
                'fc10': round(fc10, 4),
                'ksat': defaults['ksat'],
                'N2': round(n2, 4),
                'B': round(b, 4),
                'C2': round(c2, 6),
            }
            return True, "", result

        else:
            # Measured mode: use provided values, fill gaps from defaults
            fc33 = args['fc33'] if args['fc33'] is not None else defaults['fc33']
            fc15 = args['fc15'] if args['fc15'] is not None else defaults['fc15']
            ws = args['ws'] if args['ws'] is not None else defaults['ws']
            wr = args['wr'] if args['wr'] is not None else defaults['wr']
            ksat = args['ksat'] if args['ksat'] is not None else defaults['ksat']

            # Compute Brooks-Corey parameters from measured values
            psd = pore_size_distribution_estimate(fc33, fc15, wr)
            n2 = N2_estimate(psd)
            b = B_estimate(fc33, wr, psd)
            bp = bubbling_pressure_estimate(ws, psd, wr, b)
            fc10_val = fc10_estimate(ws, wr, bp, psd)
            c2 = C2_estimate(bp, psd, ksat, 0)

            result = {
                'mode': 'measured_estimate',
                'texture_class': texture_class,
                'ws': round(ws, 4),
                'wr': round(wr, 4),
                'bubbling_pressure': round(bp, 4),
                'pore_size_dist': round(psd, 4),
                'fc33': round(fc33, 4),
                'fc15': round(fc15, 4),
                'fc10': round(fc10_val, 4),
                'ksat': round(ksat, 4),
                'N2': round(n2, 4),
                'B': round(b, 4),
                'C2': round(c2, 6),
            }
            return True, "", result

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(result):
    """Validate that the computed parameters are physically reasonable."""
    errors = []

    if result.get('pore_size_dist', 0) <= 0:
        errors.append(f"Pore size distribution ({result['pore_size_dist']}) should be positive.")
    if result.get('bubbling_pressure', 0) <= 0:
        errors.append(f"Bubbling pressure ({result['bubbling_pressure']}) should be positive.")
    if result.get('ws', 0) <= result.get('wr', 0):
        errors.append(f"WS ({result['ws']}) must be greater than WR ({result['wr']}).")
    if result.get('fc33', 0) < result.get('fc15', 0):
        errors.append(f"FC33 ({result['fc33']}) should be >= FC15 ({result['fc15']}).")
    if result.get('ksat', 0) <= 0:
        errors.append(f"KSAT ({result['ksat']}) must be positive.")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    texture_class = sys.argv[1] if len(sys.argv) > 1 else TEXTURE_CLASS
    fc33_str = sys.argv[2] if len(sys.argv) > 2 else FC33
    fc15_str = sys.argv[3] if len(sys.argv) > 3 else FC15
    ws_str = sys.argv[4] if len(sys.argv) > 4 else WS
    wr_str = sys.argv[5] if len(sys.argv) > 5 else WR
    ksat_str = sys.argv[6] if len(sys.argv) > 6 else KSAT

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(texture_class, fc33_str, fc15_str, ws_str, wr_str, ksat_str)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, result = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(result)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "result": result,
        "message": (
            f"Mode={result['mode']}: pore_size_dist={result['pore_size_dist']}, "
            f"bubbling_pressure={result['bubbling_pressure']}, ksat={result['ksat']}"
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
