#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      create_soil_profile
Stage:        s2_soil_profile
Description:  Creates a Soil object from built-in type or custom layers.
              Validates hydraulic properties and layer structure.

Inputs:
  - soil_type: Built-in soil type name or 'custom' (string)
  - layers: List of layer dicts for custom soil (list, optional)
  - dz: Compartment thickness list (list, optional)

Outputs:
  - soil: Configured Soil instance (in-memory)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOIL_TYPE = "SandyLoam"      # Built-in or 'custom'
CUSTOM_LAYERS = []           # e.g., [{'thickness': 0.3, 'thWP': 0.10, 'thFC': 0.22, 'thS': 0.41, 'Ksat': 1200, 'penetrability': 100}]
TEXTURE_LAYERS = []          # e.g., [{'thickness': 0.3, 'Sand': 55, 'Clay': 15, 'OrgMat': 2, 'penetrability': 100}]
DZ = [0.1] * 12              # Compartment thickness

BUILTIN_SOILS = [
    'Clay', 'ClayLoam', 'Default', 'Loam', 'LoamySand', 'Sand',
    'SandyClay', 'SandyClayLoam', 'SandyLoam', 'Silt', 'SiltClay',
    'SiltClayLoam', 'SiltLoam', 'Paddy', 'ac_TunisLocal', 'custom',
]


def validate_inputs():
    errors = []
    if SOIL_TYPE not in BUILTIN_SOILS:
        errors.append(f"Unknown soil type '{SOIL_TYPE}'. Must be one of: {BUILTIN_SOILS}")
    if SOIL_TYPE == 'custom' and not CUSTOM_LAYERS and not TEXTURE_LAYERS:
        errors.append("Custom soil requires at least one layer in CUSTOM_LAYERS or TEXTURE_LAYERS")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(soil):
    errors = []
    if soil.nLayer < 1:
        errors.append("Soil has no layers defined")
    prof = soil.profile.dropna(subset=['th_wp', 'th_fc', 'th_s'])
    for _, row in prof.drop_duplicates(subset='Layer').iterrows():
        if row['th_wp'] >= row['th_fc']:
            errors.append(f"Layer {row['Layer']}: th_wp ({row['th_wp']}) >= th_fc ({row['th_fc']})")
        if row['th_fc'] >= row['th_s']:
            errors.append(f"Layer {row['Layer']}: th_fc ({row['th_fc']}) >= th_s ({row['th_s']})")
        if row['Ksat'] <= 0:
            errors.append(f"Layer {row['Layer']}: Ksat ({row['Ksat']}) <= 0")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def process():
    try:
        from aquacrop import Soil
    except ImportError:
        logger.error("aquacrop package not installed. Run: pip install aquacrop")
        sys.exit(2)

    if SOIL_TYPE != 'custom':
        soil = Soil(SOIL_TYPE, dz=DZ)
    else:
        soil = Soil('custom', dz=DZ)
        for layer in CUSTOM_LAYERS:
            soil.add_layer(
                thickness=layer['thickness'],
                thWP=layer['thWP'],
                thFC=layer['thFC'],
                thS=layer['thS'],
                Ksat=layer['Ksat'],
                penetrability=layer.get('penetrability', 100)
            )
        for layer in TEXTURE_LAYERS:
            soil.add_layer_from_texture(
                thickness=layer['thickness'],
                Sand=layer['Sand'],
                Clay=layer['Clay'],
                OrgMat=layer.get('OrgMat', 1.0),
                penetrability=layer.get('penetrability', 100)
            )

    logger.info(f"Soil created: type={soil.Name}, nLayer={soil.nLayer}, zSoil={soil.zSoil}m")
    return soil


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        soil = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(soil)
    logger.info("Tool completed successfully.")
    sys.exit(0)
