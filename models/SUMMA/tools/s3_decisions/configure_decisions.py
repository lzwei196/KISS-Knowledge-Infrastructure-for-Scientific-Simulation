#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      configure_decisions
Stage:        s3_decisions
Description:  Generate the SUMMA model decisions file. This is SUMMA's unique
              feature: selecting physics options for 30+ categories covering
              snow, soil, vegetation, radiation, groundwater, and numerics.

              Validates that selected options are valid for each decision
              category and checks known incompatibilities.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OUTPUT_FILE = ""

# Decisions dictionary: override these to customize physics
# Any decision not specified here uses SUMMA's internal default
DECISIONS = {}

# ---------------------------------------------------------------------------
# Complete decision catalog with all valid options
# Source: mDecisions.f90 in SUMMA source code
# ---------------------------------------------------------------------------
VALID_DECISIONS = {
    # Soil and vegetation tables
    'soilCatTbl':  ['STAS', 'STAS-RUC', 'ROSETTA'],
    'vegeParTbl':  ['USGS', 'MODIFIED_IGBP_MODIS_NOAH'],
    # Stomatal resistance
    'soilStress':  ['NoahType', 'CLM_Type', 'SiB_Type'],
    'stomResist':  ['BallBerry', 'Jarvis', 'simpleResistance', 'BallBerryFlex', 'BallBerryTest'],
    # Ball-Berry sub-options (only relevant if stomResist=BallBerry*)
    'bbTempFunc':  ['q10Func', 'Arrhenius'],
    'bbHumdFunc':  ['humidLeafSurface', 'scaledHyperbolic'],
    'bbElecFunc':  ['linear', 'linearJmax', 'quadraticJmax'],
    'bbCO2point':  ['origBWB', 'Leuning'],
    'bbNumerics':  ['NoahMPsolution', 'newtonRaphson'],
    'bbAssimFnc':  ['colimitation', 'minFunc'],
    'bbCanIntg8':  ['constantScaling', 'laiScaling'],
    # Numerical methods
    'num_method':  ['itertive', 'non_iter', 'itersurf'],
    'fDerivMeth':  ['numericl', 'analytic'],
    # LAI
    'LAI_method':  ['monTable', 'specified'],
    # Canopy interception
    'cIntercept':  ['sparseCanopy', 'storageFunc', 'notPopulatedYet'],
    # Soil water
    'f_Richards':  ['moisture', 'mixdform'],
    'groundwatr':  ['qTopmodl', 'bigBuckt', 'noXplict'],
    'hc_profile':  ['constant', 'pow_prof'],
    # Boundary conditions
    'bcUpprTdyn':  ['presTemp', 'nrg_flux', 'zeroFlux'],
    'bcLowrTdyn':  ['presTemp', 'zeroFlux'],
    'bcUpprSoiH':  ['presHead', 'liq_flux'],
    'bcLowrSoiH':  ['presHead', 'bottmPsi', 'drainage', 'zeroFlux'],
    # Vegetation traits
    'veg_traits':  ['Raupach_BLM1994', 'CM_QJRMS1988', 'vegTypeTable'],
    'rootProfil':  ['powerLaw', 'doubleExp'],
    'canopyEmis':  ['simplExp', 'difTrans'],
    # Snow
    'snowIncept':  ['stickySnow', 'lightSnow'],
    'windPrfile':  ['exponential', 'logBelowCanopy'],
    'astability':  ['standard', 'louisinv', 'mahrtexp'],
    'compaction':  ['consettl', 'anderson'],
    'snowLayers':  ['jrdn1991', 'CLM_2010'],
    'thCondSnow':  ['tyen1965', 'melr1977', 'jrdn1991', 'smnv2000'],
    'thCondSoil':  ['funcSoilWet', 'mixConstit', 'hanssonVZJ'],
    # Radiation
    'canopySrad':  ['noah_mp', 'CLM_2stream', 'UEB_2stream', 'NL_scatter', 'BeersLaw'],
    'alb_method':  ['conDecay', 'varDecay'],
    # Groundwater connectivity
    'spatial_gw':  ['localColumn', 'singleBasin'],
    # Routing
    'subRouting':  ['timeDlay', 'qInstant'],
    # Snow density
    'snowDenNew':  ['hedAndPom', 'anderson', 'pahaut_76', 'constDens'],
}

# Known INCOMPATIBLE combinations — from mDecisions.f90 source code
# (decision1, option1, decision2, option2, reason)
# Severity: 'error' = SUMMA will crash, 'warning' = runs but options ignored
INCOMPATIBILITIES = [
    # --- HARD CONSTRAINTS (SUMMA crashes with err=20) ---
    # mDecisions.f90:660-662
    ('groundwatr', 'qTopmodl', 'bcLowrSoiH', 'drainage',
     'ERROR: qTopmodl requires bcLowrSoiH=zeroFlux (mDecisions.f90:660)'),
    ('groundwatr', 'qTopmodl', 'bcLowrSoiH', 'presHead',
     'ERROR: qTopmodl requires bcLowrSoiH=zeroFlux (mDecisions.f90:660)'),
    ('groundwatr', 'qTopmodl', 'bcLowrSoiH', 'bottmPsi',
     'ERROR: qTopmodl requires bcLowrSoiH=zeroFlux (mDecisions.f90:660)'),
    # mDecisions.f90:669-671
    ('groundwatr', 'qTopmodl', 'hc_profile', 'constant',
     'ERROR: qTopmodl requires hc_profile=pow_prof (mDecisions.f90:669)'),
    # mDecisions.f90:675-681
    ('spatial_gw', 'singleBasin', 'groundwatr', 'qTopmodl',
     'ERROR: singleBasin requires groundwatr=bigBuckt (mDecisions.f90:675)'),
    ('spatial_gw', 'singleBasin', 'groundwatr', 'noXplict',
     'ERROR: singleBasin requires groundwatr=bigBuckt (mDecisions.f90:675)'),
    # soilLiqFlx.f90:305-308 — numericl derivatives completely disabled
    ('fDerivMeth', 'numericl', 'f_Richards', 'mixdform',
     'ERROR: numericl derivatives cannot compute cross-derivatives for coupled hydro-thermal (soilLiqFlx.f90:305)'),
    ('fDerivMeth', 'numericl', 'f_Richards', 'moisture',
     'ERROR: numericl derivatives cannot compute cross-derivatives for coupled hydro-thermal (soilLiqFlx.f90:305)'),
    # --- SOFT CONSTRAINTS (runs but options are ignored) ---
    ('stomResist', 'Jarvis', 'bbTempFunc', '*',
     'WARNING: Ball-Berry sub-options (bb*) are ignored when stomResist=Jarvis'),
    ('stomResist', 'simpleResistance', 'bbTempFunc', '*',
     'WARNING: Ball-Berry sub-options are ignored when stomResist=simpleResistance'),
    ('f_Richards', 'moisture', 'bcLowrSoiH', 'presHead',
     'ERROR: Pressure head lower BC requires mixdform Richards equation'),
]

# Recommended "safe default" decision set
# Based on Reynolds Mountain reference case (the SUMMA-shipped working test).
# Previous defaults had 3 FATAL incompatibilities:
#   1. fDerivMeth=numericl — crashes immediately (cross-derivatives error)
#   2. groundwatr=qTopmodl + bcLowrSoiH=drainage — qTopmodl requires zeroFlux
#   3. groundwatr=qTopmodl + hc_profile must be pow_prof (was correct but fragile)
# Fixed 2026-04-11: all defaults now match Reynolds Mountain reference.
DEFAULT_DECISIONS = {
    'soilCatTbl':  'STAS',
    'vegeParTbl':  'USGS',               # NA basins: USGS (with IGBP→USGS crosswalk). Non-NA: override to MODIFIED_IGBP_MODIS_NOAH
    'soilStress':  'NoahType',
    'stomResist':  'BallBerry',
    'bbTempFunc':  'q10Func',
    'bbHumdFunc':  'humidLeafSurface',
    'bbElecFunc':  'linear',
    'bbCO2point':  'origBWB',
    'bbNumerics':  'NoahMPsolution',
    'bbAssimFnc':  'colimitation',
    'bbCanIntg8':  'constantScaling',
    'num_method':  'itertive',
    'fDerivMeth':  'analytic',            # FIX: numericl is BROKEN — crashes with cross-derivatives error
    'LAI_method':  'monTable',
    'cIntercept':  'storageFunc',
    'f_Richards':  'mixdform',
    'groundwatr':  'noXplict',            # FIX: qTopmodl requires zeroFlux+pow_prof; noXplict is safest default
    'hc_profile':  'constant',            # FIX: matches noXplict; pow_prof only needed for qTopmodl
    'bcUpprTdyn':  'nrg_flux',
    'bcLowrTdyn':  'zeroFlux',
    'bcUpprSoiH':  'liq_flux',
    'bcLowrSoiH':  'drainage',            # OK: free drainage is safe with noXplict groundwater
    'veg_traits':  'Raupach_BLM1994',
    'rootProfil':  'powerLaw',
    'canopyEmis':  'difTrans',
    'snowIncept':  'lightSnow',
    'windPrfile':  'logBelowCanopy',
    'astability':  'louisinv',
    'compaction':  'anderson',
    'snowLayers':  'CLM_2010',
    'thCondSnow':  'smnv2000',
    'thCondSoil':  'funcSoilWet',
    'canopySrad':  'CLM_2stream',
    'alb_method':  'varDecay',
    'spatial_gw':  'localColumn',
    'subRouting':  'timeDlay',
    'snowDenNew':  'anderson',
}

# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Configure SUMMA decisions")
    parser.add_argument("--output", required=True, help="Output decisions file path")
    parser.add_argument("--decisions", type=str, default="",
                        help="JSON string of decisions to override defaults")
    parser.add_argument("--use_defaults", action="store_true",
                        help="Start from safe defaults, apply overrides on top")
    args = parser.parse_args()
    OUTPUT_FILE = args.output
    if args.decisions:
        DECISIONS = json.loads(args.decisions)
    if args.use_defaults:
        merged = dict(DEFAULT_DECISIONS)
        merged.update(DECISIONS)
        DECISIONS = merged


def validate_inputs():
    errors = []
    if not OUTPUT_FILE:
        errors.append("OUTPUT_FILE is not set")

    # Validate each decision
    for key, value in DECISIONS.items():
        if key not in VALID_DECISIONS:
            errors.append(f"Unknown decision: '{key}'. Valid decisions: {list(VALID_DECISIONS.keys())}")
        elif value not in VALID_DECISIONS[key]:
            errors.append(f"Invalid option '{value}' for decision '{key}'. "
                          f"Valid options: {VALID_DECISIONS[key]}")

    # Check incompatibilities — hard errors (from Fortran source) vs soft warnings
    for d1, o1, d2, o2, reason in INCOMPATIBILITIES:
        if d1 in DECISIONS and d2 in DECISIONS:
            if DECISIONS[d1] == o1 and (o2 == '*' or DECISIONS[d2] == o2):
                if reason.startswith('ERROR:'):
                    errors.append(reason)
                else:
                    logger.warning(reason)

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_path):
    errors = []
    if not Path(output_path).exists():
        errors.append(f"Output not created: {output_path}")
    else:
        with open(output_path) as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith('!')]
            if len(lines) == 0:
                errors.append("Decisions file is empty")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def process():
    """Generate decisions file."""
    os.makedirs(os.path.dirname(OUTPUT_FILE) or '.', exist_ok=True)

    # Start from defaults if DECISIONS is empty
    if not DECISIONS:
        logger.info("No decisions specified, using safe defaults")
        decisions = dict(DEFAULT_DECISIONS)
    else:
        decisions = dict(DECISIONS)

    # Write decisions file
    with open(OUTPUT_FILE, 'w') as f:
        f.write("! ====================================================================\n")
        f.write("! SUMMA Model Decisions File\n")
        f.write("! Generated by configure_decisions.py (Knowledge Infrastructure)\n")
        f.write("! ====================================================================\n")
        f.write("! Format: keyword   option   ! comment\n")
        f.write("! ====================================================================\n\n")

        # Group decisions by category for readability
        categories = {
            'Tables': ['soilCatTbl', 'vegeParTbl'],
            'Stomatal resistance': ['soilStress', 'stomResist'],
            'Ball-Berry options': ['bbTempFunc', 'bbHumdFunc', 'bbElecFunc',
                                   'bbCO2point', 'bbNumerics', 'bbAssimFnc', 'bbCanIntg8'],
            'Numerical methods': ['num_method', 'fDerivMeth'],
            'LAI': ['LAI_method'],
            'Canopy': ['cIntercept', 'canopyEmis', 'canopySrad'],
            'Soil water': ['f_Richards', 'groundwatr', 'hc_profile', 'thCondSoil'],
            'Boundary conditions': ['bcUpprTdyn', 'bcLowrTdyn', 'bcUpprSoiH', 'bcLowrSoiH'],
            'Vegetation': ['veg_traits', 'rootProfil'],
            'Snow': ['snowIncept', 'windPrfile', 'astability', 'compaction',
                     'snowLayers', 'thCondSnow', 'snowDenNew', 'alb_method'],
            'Spatial structure': ['spatial_gw', 'subRouting'],
        }

        for category, keys in categories.items():
            has_any = any(k in decisions for k in keys)
            if has_any:
                f.write(f"! --- {category} ---\n")
                for key in keys:
                    if key in decisions:
                        # Pad for alignment
                        f.write(f"{key:<20s} {decisions[key]:<30s} ! options: {VALID_DECISIONS.get(key, [])}\n")
                f.write("\n")

        # Write any remaining decisions not in categories
        categorized = set()
        for keys in categories.values():
            categorized.update(keys)
        remaining = {k: v for k, v in decisions.items() if k not in categorized}
        if remaining:
            f.write("! --- Other ---\n")
            for key, value in remaining.items():
                f.write(f"{key:<20s} {value}\n")

    n_decisions = len(decisions)
    logger.info(f"Decisions file written: {OUTPUT_FILE} ({n_decisions} decisions)")

    print(json.dumps({
        "status": "success",
        "n_decisions": n_decisions,
        "output": OUTPUT_FILE,
        "decisions": decisions
    }))

    return OUTPUT_FILE


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
