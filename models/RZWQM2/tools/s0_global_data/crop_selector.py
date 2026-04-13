#!/usr/bin/env python3
"""
crop_selector.py
================
Select DSSAT crop model files for a given crop name or VIC vegetation class.

Maps common crop names to DSSAT file prefixes (cultivar, ecotype, species)
and returns file paths and a default cultivar ID.

Supports all 41 crops in the RZWQM2 DSSAT database. Optionally maps VIC
AVHRR vegetation classes (1-15) to crop types.

Inputs:
    crop_name       - Common crop name (e.g., "maize", "wheat", "soybean")
    dssat_db_path   - Path to DSSAT database directory (optional)
    vic_veg_class   - VIC AVHRR vegetation class number (optional, alternative to crop_name)
    region          - Region hint for cultivar selection (optional: "tropical", "temperate")

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json
import glob

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
CROP_NAME = ""          # Common crop name
DSSAT_DB_PATH = ""      # Path to DSSAT database directory
VIC_VEG_CLASS = ""      # VIC AVHRR vegetation class (1-15), alternative to crop_name
REGION = ""             # Region hint: "tropical", "temperate", "boreal"

# ---------------------------------------------------------------------------
# CROP MAPPING
# ---------------------------------------------------------------------------
CROP_TO_DSSAT = {
    'barley':         'BACER040',
    'maize':          'MZCER040',
    'corn':           'MZCER040',
    'wheat':          'WHCER040',
    'rice':           'RICER040',
    'sorghum':        'SGCER040',
    'millet':         'MLCER040',
    'foxtail_millet': 'MLCER040',
    'proso_millet':   'MLCER040',
    'soybean':        'SBGRO040',
    'peanut':         'PNGRO040',
    'cotton':         'COGRO040',
    'potato':         'PTSUB040',
    'tomato':         'TMGRO040',
    'bean':           'BNGRO040',
    'dry_bean':       'BNGRO040',
    'chickpea':       'CHGRO040',
    'cowpea':         'CPGRO040',
    'pepper':         'PRGRO040',
    'sunflower':      'SUOIL040',
    'sugarcane':      'SCCAN040',
    'alfalfa':        'ALFRM040',
    'cabbage':        'CBGRO040',
    'faba_bean':      'FBGRO040',
    'velvetbean':     'VBGRO040',
    'triticale':      'TRCER040',
    'canola':         'CNGRO040',
    'bermudagrass':   'BMFRM040',
    'beet_sugar':     'BSCER040',
}

# VIC AVHRR vegetation classes -> default crop mapping
VIC_VEG_TO_CROP = {
    1:  None,         # Evergreen Needleleaf Forest
    2:  None,         # Evergreen Broadleaf Forest
    3:  None,         # Deciduous Needleleaf Forest
    4:  None,         # Deciduous Broadleaf Forest
    5:  None,         # Mixed Forest
    6:  'alfalfa',    # Woodland -> pasture proxy
    7:  'alfalfa',    # Wooded Grasslands
    8:  'alfalfa',    # Closed Shrublands
    9:  'alfalfa',    # Open Shrublands
    10: 'alfalfa',    # Grasslands
    11: 'maize',      # Croplands -> default to maize
    12: None,         # Bare Ground
    13: None,         # Urban
    14: None,         # Urban
    15: None,         # Ice/Snow
}

# Region-specific crop refinements for VIC cropland class (11)
VIC_CROPLAND_BY_REGION = {
    'tropical':  'rice',
    'temperate': 'maize',
    'boreal':    'wheat',
}


def validate_inputs(crop_name, dssat_db_path, vic_veg_class, region):
    """Validate inputs."""
    errors = []

    if not crop_name and not vic_veg_class:
        errors.append("Either CROP_NAME or VIC_VEG_CLASS is required.")

    # Resolve crop from VIC class if needed
    resolved_crop = None
    if vic_veg_class:
        try:
            veg_class = int(vic_veg_class)
            if veg_class not in VIC_VEG_TO_CROP:
                errors.append(f"VIC_VEG_CLASS={veg_class} not recognized (valid: 1-15).")
            else:
                resolved_crop = VIC_VEG_TO_CROP[veg_class]
                if resolved_crop is None:
                    errors.append(
                        f"VIC_VEG_CLASS={veg_class} is non-agricultural (forest/urban/bare). "
                        f"No DSSAT crop mapping available."
                    )
                elif veg_class == 11 and region:
                    resolved_crop = VIC_CROPLAND_BY_REGION.get(region.lower(), resolved_crop)
        except ValueError:
            errors.append(f"VIC_VEG_CLASS must be an integer, got: {vic_veg_class}")

    if crop_name:
        resolved_crop = crop_name.strip().lower()

    if resolved_crop and resolved_crop not in CROP_TO_DSSAT:
        errors.append(
            f"Unknown crop: '{resolved_crop}'. "
            f"Supported: {sorted(CROP_TO_DSSAT.keys())}"
        )

    # Find DSSAT database path
    if not dssat_db_path:
        # Try default locations
        candidates = [
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'databases', 'DSSAT'),
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'linux', 'DSSAT'),
        ]
        for c in candidates:
            if os.path.isdir(os.path.abspath(c)):
                dssat_db_path = os.path.abspath(c)
                break

    if dssat_db_path and not os.path.isdir(dssat_db_path):
        errors.append(f"DSSAT_DB_PATH does not exist: {dssat_db_path}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'crop_name': resolved_crop,
        'dssat_db_path': dssat_db_path,
        'dssat_prefix': CROP_TO_DSSAT.get(resolved_crop, ''),
        'region': region.strip().lower() if region else None,
    }


def process(args):
    """
    Look up DSSAT files for the selected crop.
    Returns (success, error_msg, result).
    """
    crop_name = args['crop_name']
    dssat_prefix = args['dssat_prefix']
    dssat_db_path = args['dssat_db_path']

    try:
        result = {
            'crop_name': crop_name,
            'dssat_prefix': dssat_prefix,
            'cultivar_file': None,
            'ecotype_file': None,
            'species_file': None,
            'default_cultivar_id': None,
            'cultivar_count': 0,
        }

        if dssat_db_path:
            # Find cultivar file
            cul_pattern = os.path.join(dssat_db_path, f"{dssat_prefix}.CUL")
            cul_files = glob.glob(cul_pattern)
            if cul_files:
                result['cultivar_file'] = cul_files[0]
                # Parse first cultivar ID
                with open(cul_files[0], encoding='ISO-8859-1') as f:
                    count = 0
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('*') and not line.startswith('!') and not line.startswith('@'):
                            parts = line.split()
                            if parts:
                                if result['default_cultivar_id'] is None:
                                    result['default_cultivar_id'] = parts[0]
                                count += 1
                    result['cultivar_count'] = count

            # Find ecotype file
            eco_pattern = os.path.join(dssat_db_path, f"{dssat_prefix}.ECO")
            eco_files = glob.glob(eco_pattern)
            if eco_files:
                result['ecotype_file'] = eco_files[0]

            # Find species file
            spe_pattern = os.path.join(dssat_db_path, f"{dssat_prefix}.SPE")
            spe_files = glob.glob(spe_pattern)
            if spe_files:
                result['species_file'] = spe_files[0]

        return True, "", result

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(result):
    """Check that at least the prefix was resolved."""
    if not result or not result.get('dssat_prefix'):
        return False, "No DSSAT prefix resolved."
    return True, ""


def main():
    crop_name = sys.argv[1] if len(sys.argv) > 1 else CROP_NAME
    dssat_db_path = sys.argv[2] if len(sys.argv) > 2 else DSSAT_DB_PATH
    vic_veg_class = sys.argv[3] if len(sys.argv) > 3 else VIC_VEG_CLASS
    region = sys.argv[4] if len(sys.argv) > 4 else REGION

    valid, err, args = validate_inputs(crop_name, dssat_db_path, vic_veg_class, region)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    success, err, result = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    valid, err = validate_outputs(result)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "result": result,
        "message": (
            f"Crop '{result['crop_name']}' -> DSSAT prefix '{result['dssat_prefix']}'. "
            f"{result['cultivar_count']} cultivars available."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
