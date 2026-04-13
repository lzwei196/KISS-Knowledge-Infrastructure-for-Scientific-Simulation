#!/usr/bin/env python3
"""
soil_texture_classification.py
==============================
Classify soil into USDA texture classes using the texture triangle,
given sand and clay percentages.

Uses soil_texture_setter() from rzwqm_file.py.  Standalone function
with no file I/O -- purely computational.

Inputs:
    sand_pct  - Sand content as a percentage (0-100)
    clay_pct  - Clay content as a percentage (0-100)
    (Silt is computed as 100 - sand - clay)

Outputs:
    USDA textural class name (string).

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
SAND_PCT = ""   # Sand percentage (0-100)
CLAY_PCT = ""   # Clay percentage (0-100)

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))

# Valid USDA texture classes
VALID_TEXTURE_CLASSES = [
    'sand', 'loamy sand', 'sandy loam', 'loam', 'silt loam', 'silt',
    'sandy clay loam', 'clay loam', 'silty clay loam',
    'sandy clay', 'silty clay', 'clay'
]


def validate_inputs(sand_str, clay_str):
    """Validate sand and clay percentage inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    sand = None
    clay = None

    if not sand_str and sand_str != 0:
        errors.append("SAND_PCT is required.")
    else:
        try:
            sand = float(sand_str)
        except (ValueError, TypeError):
            errors.append(f"SAND_PCT '{sand_str}' is not a valid number.")

    if not clay_str and clay_str != 0:
        errors.append("CLAY_PCT is required.")
    else:
        try:
            clay = float(clay_str)
        except (ValueError, TypeError):
            errors.append(f"CLAY_PCT '{clay_str}' is not a valid number.")

    if sand is not None and clay is not None:
        if sand < 0 or clay < 0:
            errors.append("Sand and clay percentages must be non-negative.")
        if sand + clay > 100:
            errors.append(f"Sand ({sand}) + Clay ({clay}) = {sand + clay}, exceeds 100%.")

    if errors:
        return False, "; ".join(errors), None

    silt = 100 - sand - clay
    return True, "", {
        'sand': sand,
        'clay': clay,
        'silt': round(silt, 2)
    }


def process(args):
    """
    Classify soil texture using the USDA texture triangle.
    Returns (success, error_msg, result_dict).
    """
    from rzwqm_file import soil_texture_setter

    sand = args['sand']
    clay = args['clay']

    try:
        texture_class = soil_texture_setter(sand, clay)
        result = {
            'sand_pct': sand,
            'clay_pct': clay,
            'silt_pct': args['silt'],
            'texture_class': texture_class
        }
        return True, "", result

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(result):
    """Validate that the classification produced a recognized texture class."""
    errors = []

    texture = result.get('texture_class', '')
    if texture == 'na' or texture not in VALID_TEXTURE_CLASSES:
        errors.append(
            f"Texture class '{texture}' is not a recognized USDA class. "
            f"This may indicate the sand/clay combination falls outside "
            f"standard triangle boundaries."
        )

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    sand_str = sys.argv[1] if len(sys.argv) > 1 else SAND_PCT
    clay_str = sys.argv[2] if len(sys.argv) > 2 else CLAY_PCT

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(sand_str, clay_str)
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
            f"Sand={result['sand_pct']}%, Clay={result['clay_pct']}%, "
            f"Silt={result['silt_pct']}% => {result['texture_class']}"
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
