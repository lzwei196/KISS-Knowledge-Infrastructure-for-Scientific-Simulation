#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      generate_mhm_parameters
Stage:        s3_mpr
Description:  Generate mhm_parameter.nml with literature-informed default values.

This tool copies the default parameter file from the mHM source and optionally
adjusts parameter values based on climate zone or basin characteristics.

The ~70 global parameters are organized by process:
- Interception (1 param): canopyInterceptionFactor
- Snow (8 params): snowThreshold, degreeDayFactor (3 land types), max (3)
- Soil moisture (17 params): PTF coefficients, root fractions, infiltration
- Direct runoff (1 param): imperviousStorageCapacity
- PET (varies by method): 3-7 params depending on processCase(5)
- Interflow (5 params): storage, recession, Ks
- Percolation (3 params): recharge coefficients
- Routing (varies): Muskingum or celerity params
- Geology (10 params): GeoParam baseflow recession

Inputs:
  - CONFIG_PATH: config.json
  - CLIMATE_ZONE: optional hint for default values ("humid", "semi-arid", "cold", "tropical")

Outputs:
  - mhm_parameter.nml in run directory
"""

import sys
import os
import json
import logging
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = ""
CLIMATE_ZONE = "default"  # "humid", "semi-arid", "cold", "tropical"
MHM_PARAM_TEMPLATE = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"), "model/mhm_src/mhm_parameter.nml")

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--climate_zone", default="default")
    args = parser.parse_args()
    CONFIG_PATH = args.config
    CLIMATE_ZONE = args.climate_zone


###############################################################################
# Climate-zone-aware parameter presets
#
# These override the mHM source-tree defaults (tuned for the Mosel/Germany)
# with literature-informed starting points for different climates.
# Format: parameter_name -> value
#
# References:
#   - Samaniego et al. (2010) HESS: MPR calibrated values for European basins
#   - Rakovec et al. (2016) WRR: pan-European mHM parameters
#   - Kumar et al. (2013) WRR: Indian basins with mHM
#   - Mizukami et al. (2017) JAMES: North American parameter transfer study
###############################################################################

# Mapping of climate zone aliases to a canonical name
_ZONE_ALIASES = {
    # humid subtropical / monsoon (e.g., Yangtze, SE USA, SE Australia)
    "humid_subtropical": "humid_subtropical",
    "humid": "humid_subtropical",
    "monsoon": "humid_subtropical",
    # semi-arid (e.g., Yellow River, Great Plains, Sahel)
    "semi_arid": "semi_arid",
    "semi-arid": "semi_arid",
    "arid": "semi_arid",
    "dryland": "semi_arid",
    # cold / boreal / alpine
    "cold_alpine": "cold_alpine",
    "cold": "cold_alpine",
    "alpine": "cold_alpine",
    "boreal": "cold_alpine",
    "continental": "cold_alpine",
    # tropical (equatorial, high P, high T)
    "tropical": "tropical",
    "equatorial": "tropical",
}

# Climate-zone parameter overrides.
# Only parameters whose optimal values are known to differ strongly across
# climates are overridden; the remaining ~50 parameters keep template defaults.
CLIMATE_PRESETS = {
    "humid_subtropical": {
        # Higher interception in dense broadleaf forests
        "canopyInterceptionFactor":           0.30,
        # Warmer snow threshold (less snow in subtropical climates)
        "snowTreshholdTemperature":            2.0,
        # Faster snowmelt where it does snow
        "degreeDayFactor_forest":              2.5,
        "degreeDayFactor_pervious":            1.5,
        # Higher infiltration shape factor: more saturation-excess in monsoon
        "infiltrationShapeFactor":             2.5,
        # Larger interflow storage (deep soils, high water table)
        "interflowStorageCapacityFactor":    150.0,
        # Steeper interflow recession (fast response)
        "interflowRecession_slope":            5.0,
        # Moderate recharge coefficient
        "rechargeCoefficient":                25.0,
        # Faster baseflow recession (humid = responsive aquifers)
        "GeoParam(1,:)":                     200.0,
        "GeoParam(2,:)":                     200.0,
        "GeoParam(3,:)":                     200.0,
        "GeoParam(4,:)":                     200.0,
    },
    "semi_arid": {
        # Low interception (sparse vegetation)
        "canopyInterceptionFactor":           0.15,
        # Higher snow threshold (continental cold)
        "snowTreshholdTemperature":            0.5,
        "degreeDayFactor_forest":              1.0,
        "degreeDayFactor_pervious":            0.5,
        # High infiltration shape (rapid Hortonian overland flow on crusted soils)
        "infiltrationShapeFactor":             3.5,
        # Smaller interflow storage (thin soils)
        "interflowStorageCapacityFactor":     100.0,
        # Slower interflow recession
        "interflowRecession_slope":            3.0,
        # Low recharge
        "rechargeCoefficient":                10.0,
        # Slow baseflow recession (deep water table, long memory)
        "GeoParam(1,:)":                      50.0,
        "GeoParam(2,:)":                      50.0,
        "GeoParam(3,:)":                      50.0,
        "GeoParam(4,:)":                      50.0,
    },
    "cold_alpine": {
        # Moderate interception (needleleaf)
        "canopyInterceptionFactor":           0.20,
        # Cold snow threshold
        "snowTreshholdTemperature":           -1.0,
        # Slower snowmelt (cold, short melt season)
        "degreeDayFactor_forest":              1.0,
        "degreeDayFactor_pervious":            0.3,
        "maxDegreeDayFactor_forest":           5.0,
        "maxDegreeDayFactor_pervious":         6.0,
        # Lower infiltration shape (frozen ground can act as impervious)
        "infiltrationShapeFactor":             2.0,
        # Lower interflow storage
        "interflowStorageCapacityFactor":     120.0,
        "interflowRecession_slope":            4.0,
        # Moderate recharge
        "rechargeCoefficient":                20.0,
        # Moderate baseflow
        "GeoParam(1,:)":                     150.0,
        "GeoParam(2,:)":                     150.0,
        "GeoParam(3,:)":                     150.0,
        "GeoParam(4,:)":                     150.0,
    },
    "tropical": {
        # High interception (dense tropical forest)
        "canopyInterceptionFactor":           0.35,
        # No snow
        "snowTreshholdTemperature":            2.0,
        "degreeDayFactor_forest":              0.5,
        "degreeDayFactor_pervious":            0.5,
        # High infiltration shape (intense convective rain)
        "infiltrationShapeFactor":             3.0,
        # High interflow storage (deep lateritic soils)
        "interflowStorageCapacityFactor":     180.0,
        # Fast interflow
        "interflowRecession_slope":            8.0,
        # High recharge
        "rechargeCoefficient":                40.0,
        # Moderate-fast baseflow
        "GeoParam(1,:)":                     250.0,
        "GeoParam(2,:)":                     250.0,
        "GeoParam(3,:)":                     250.0,
        "GeoParam(4,:)":                     250.0,
    },
}


def apply_climate_presets(nml_path, zone):
    """Modify parameter values in mhm_parameter.nml based on climate zone.

    The namelist format is:
      paramName = lower, upper, value, FLAG, SCALING
    We only change the 'value' field (3rd comma-separated item) while keeping
    the bounds, flag, and scaling unchanged.
    """
    canonical = _ZONE_ALIASES.get(zone)
    if canonical is None:
        logger.warning(f"Unknown climate zone '{zone}'. Valid: {sorted(_ZONE_ALIASES.keys())}. Using template defaults.")
        return 0

    presets = CLIMATE_PRESETS[canonical]
    logger.info(f"Applying climate zone presets: {canonical} ({len(presets)} parameters)")

    with open(nml_path) as f:
        lines = f.readlines()

    n_applied = 0
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip comments and group headers
        if stripped.startswith('!') or stripped.startswith('&') or stripped == '/' or not stripped:
            new_lines.append(line)
            continue

        # Try to match a parameter assignment
        if '=' in stripped:
            param_name = stripped.split('=')[0].strip()
            if param_name in presets:
                # Parse the existing right-hand side
                rhs = stripped.split('=', 1)[1]
                parts = [p.strip() for p in rhs.split(',')]
                if len(parts) >= 5:
                    old_val = float(parts[2])
                    new_val = presets[param_name]
                    # Clamp to bounds
                    lower = float(parts[0])
                    upper = float(parts[1])
                    clamped = max(lower, min(upper, new_val))
                    if clamped != new_val:
                        logger.warning(f"  {param_name}: preset {new_val} clamped to [{lower}, {upper}] -> {clamped}")
                    parts[2] = f"{clamped:12.4f}" if abs(clamped) < 100 else f"{clamped:12.1f}"
                    # Reconstruct line preserving leading whitespace
                    leading = line[:len(line) - len(line.lstrip())]
                    new_rhs = ", ".join(p.strip() for p in parts)
                    new_line = f"{leading}{param_name.ljust(40)} = {new_rhs}\n"
                    new_lines.append(new_line)
                    logger.info(f"  {param_name}: {old_val} -> {clamped}")
                    n_applied += 1
                    continue

        new_lines.append(line)

    with open(nml_path, 'w') as f:
        f.writelines(new_lines)

    logger.info(f"Applied {n_applied} / {len(presets)} climate zone overrides")
    return n_applied


def validate_inputs():
    errors = []
    if not CONFIG_PATH or not Path(CONFIG_PATH).exists():
        errors.append(f"Config not found: {CONFIG_PATH}")
    if not Path(MHM_PARAM_TEMPLATE).exists():
        errors.append(f"Parameter template not found: {MHM_PARAM_TEMPLATE}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    config = json.load(open(CONFIG_PATH))
    run_dir = Path(config["output_dir"])
    out_path = run_dir / "mhm_parameter.nml"

    # Start from template
    shutil.copy2(MHM_PARAM_TEMPLATE, out_path)
    logger.info(f"Copied default parameters from {MHM_PARAM_TEMPLATE}")

    # Apply climate-zone-aware presets if requested
    n_overrides = 0
    if CLIMATE_ZONE and CLIMATE_ZONE != "default":
        n_overrides = apply_climate_presets(out_path, CLIMATE_ZONE)

    # Count parameters
    n_total = 0
    n_calibrated = 0
    with open(out_path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('!') and not line.startswith('&'):
                parts = line.split('=')
                if len(parts) == 2:
                    vals = parts[1].split(',')
                    if len(vals) >= 5:
                        n_total += 1
                        try:
                            if int(vals[3].strip()) == 1:
                                n_calibrated += 1
                        except (ValueError, IndexError):
                            pass

    logger.info(f"Parameters: {n_total} total, {n_calibrated} flagged for calibration")

    result = {
        "status": "success",
        "parameter_file": str(out_path),
        "n_parameters": n_total,
        "n_calibrated": n_calibrated,
        "climate_zone": CLIMATE_ZONE,
        "n_climate_overrides": n_overrides,
    }
    print(json.dumps(result, indent=2))
    return str(out_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Parameter file not created: {output_path}")
        sys.exit(3)


if __name__ == "__main__":
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
