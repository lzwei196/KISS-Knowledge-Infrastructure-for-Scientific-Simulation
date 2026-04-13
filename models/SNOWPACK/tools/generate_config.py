#!/usr/bin/env python3
"""
generate_config.py — Generate SNOWPACK INI configuration file.

Purpose:
    Creates a complete SNOWPACK .ini configuration file with all required
    sections: [General], [Input], [Output], [Snowpack], [SnowpackAdvanced],
    and [Filters]. Supports multiple model variants and parametrization choices.

CRITICAL NOTES:
    - CALCULATION_STEP_LENGTH is in SECONDS (not minutes). Default: 900 (15 min).
      Setting 15 → 15-second timestep (60× slower, potential instability).
    - HEIGHT_OF_METEO_VALUES and HEIGHT_OF_WIND_VALUE must match actual
      sensor installation heights. Wrong values → systematic flux bias.
    - SW_MODE must match available radiation data:
      INCOMING (only ISWR), REFLECTED (only RSWR), BOTH (ISWR + RSWR).
    - FORCING must match available inputs:
      ATMOS (full energy balance), MASSBAL (simplified mass balance).
    - Paths use forward slashes even on Windows (MeteoIO requirement).

Output INI format:
    Standard Windows-style INI with [Section] headers and KEY = VALUE pairs.

Usage:
    python generate_config.py \\
        --output io.ini \\
        --station_id MST96 \\
        --meteo_path ./input \\
        --output_path ./output \\
        --calculation_step 900 \\
        --variant DEFAULT

    python generate_config.py \\
        --output io_polar.ini \\
        --station_id DOME_C \\
        --meteo_path ./input \\
        --output_path ./output \\
        --variant POLAR \\
        --sw_mode INCOMING \\
        --stability MONIN_OBUKHOV \\
        --water_transport RICHARDSEQUATION
"""

import argparse
import json
import os
import sys
from pathlib import Path


# Variant presets: parameter overrides for common deployment environments
VARIANT_PRESETS = {
    "DEFAULT": {
        "ATMOSPHERIC_STABILITY": "MO_MICHLMAYR",
        "ROUGHNESS_LENGTH": 0.002,
        "ALBEDO_PARAMETERIZATION": "LEHNING_2",
        "HN_DENSITY_PARAMETERIZATION": "LEHNING_NEW",
        "METAMORPHISM_MODEL": "DEFAULT",
        "VISCOSITY_MODEL": "DEFAULT",
        "WATERTRANSPORTMODEL_SNOW": "BUCKET",
        "WATERTRANSPORTMODEL_SOIL": "BUCKET",
        "SNOW_EROSION": "TRUE",
    },
    "POLAR": {
        "ATMOSPHERIC_STABILITY": "MO_HOLTSLAG",
        "ROUGHNESS_LENGTH": 0.001,
        "ALBEDO_PARAMETERIZATION": "LEHNING_2",
        "HN_DENSITY_PARAMETERIZATION": "LEHNING_NEW",
        "METAMORPHISM_MODEL": "DEFAULT",
        "VISCOSITY_MODEL": "DEFAULT",
        "WATERTRANSPORTMODEL_SNOW": "BUCKET",
        "WATERTRANSPORTMODEL_SOIL": "BUCKET",
        "SNOW_EROSION": "TRUE",
    },
    "NIED": {
        "ATMOSPHERIC_STABILITY": "MO_MICHLMAYR",
        "ROUGHNESS_LENGTH": 0.002,
        "ALBEDO_PARAMETERIZATION": "NIED",
        "HN_DENSITY_PARAMETERIZATION": "NIED",
        "METAMORPHISM_MODEL": "NIED",
        "VISCOSITY_MODEL": "KOJIMA",
        "WATERTRANSPORTMODEL_SNOW": "NIED",
        "WATERTRANSPORTMODEL_SOIL": "BUCKET",
        "SNOW_EROSION": "FALSE",
    },
}


def validate_inputs(args):
    """Validate configuration parameters."""
    errors = []

    if args.variant not in VARIANT_PRESETS:
        errors.append(f"Unknown variant: {args.variant}. "
                       f"Choose from: {list(VARIANT_PRESETS.keys())}")

    if args.calculation_step < 1 or args.calculation_step > 3600:
        errors.append(f"calculation_step {args.calculation_step}s out of range [1, 3600]")

    if args.calculation_step < 60:
        # Not an error but a warning
        print(f"WARNING: Very small timestep ({args.calculation_step}s) — "
              f"did you mean minutes? SNOWPACK expects SECONDS.",
              file=sys.stderr)

    valid_sw_modes = ["INCOMING", "REFLECTED", "BOTH"]
    if args.sw_mode not in valid_sw_modes:
        errors.append(f"sw_mode must be one of {valid_sw_modes}")

    valid_forcing = ["ATMOS", "MASSBAL"]
    if args.forcing not in valid_forcing:
        errors.append(f"forcing must be one of {valid_forcing}")

    if args.height_meteo <= 0 or args.height_meteo > 50:
        errors.append(f"height_meteo {args.height_meteo}m seems implausible")

    if args.height_wind <= 0 or args.height_wind > 100:
        errors.append(f"height_wind {args.height_wind}m seems implausible")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)
    return errors


def process(args):
    """Generate the INI configuration file."""
    preset = VARIANT_PRESETS[args.variant].copy()

    # Apply user overrides
    if args.stability:
        preset["ATMOSPHERIC_STABILITY"] = args.stability
    if args.water_transport:
        preset["WATERTRANSPORTMODEL_SNOW"] = args.water_transport

    # Build INI content
    lines = []

    # [General]
    lines.append("[General]")
    lines.append(f"BUFFER_SIZE = 370")
    lines.append(f"BUFF_BEFORE = 1.5")
    lines.append("")

    # [Input]
    lines.append("[Input]")
    lines.append(f"COORDSYS = LATLON")
    lines.append(f"TIME_ZONE = {args.timezone}")
    lines.append(f"METEO = SMET")
    lines.append(f"METEOPATH = {args.meteo_path}")
    lines.append(f"STATION1 = {args.station_id}")
    lines.append(f"SNOWPATH = {args.meteo_path}")
    lines.append(f"SNOW = SMET")
    lines.append("")

    # [Output]
    lines.append("[Output]")
    lines.append(f"COORDSYS = LATLON")
    lines.append(f"TIME_ZONE = {args.timezone}")
    lines.append(f"METEOPATH = {args.output_path}")
    lines.append(f"METEO = SMET")
    lines.append(f"PROFILE_FORMAT = PRO")
    lines.append(f"TS_WRITE = TRUE")
    lines.append(f"TS_START = 0.0")
    lines.append(f"TS_DAYS_BETWEEN = {args.ts_days_between}")
    lines.append(f"PROF_WRITE = TRUE")
    lines.append(f"PROF_START = 0.0")
    lines.append(f"PROF_DAYS_BETWEEN = {args.prof_days_between}")
    lines.append(f"OUT_HEAT = TRUE")
    lines.append(f"OUT_LW = TRUE")
    lines.append(f"OUT_SW = TRUE")
    lines.append(f"OUT_MASS = TRUE")
    lines.append(f"OUT_T = TRUE")
    lines.append(f"OUT_STAB = FALSE")
    lines.append(f"OUT_HAZ = FALSE")
    lines.append(f"OUT_CANOPY = {'TRUE' if args.canopy else 'FALSE'}")
    lines.append("")

    # [Snowpack]
    lines.append("[Snowpack]")
    lines.append(f"CALCULATION_STEP_LENGTH = {args.calculation_step:.1f}")
    lines.append(f"FORCING = {args.forcing}")
    lines.append(f"SW_MODE = {args.sw_mode}")
    lines.append(f"ATMOSPHERIC_STABILITY = {preset['ATMOSPHERIC_STABILITY']}")
    lines.append(f"ROUGHNESS_LENGTH = {preset['ROUGHNESS_LENGTH']}")
    lines.append(f"HEIGHT_OF_METEO_VALUES = {args.height_meteo:.1f}")
    lines.append(f"HEIGHT_OF_WIND_VALUE = {args.height_wind:.1f}")
    lines.append(f"GEO_HEAT = {args.geo_heat:.2f}")
    lines.append(f"CANOPY = {'TRUE' if args.canopy else 'FALSE'}")
    lines.append("")

    # [SnowpackAdvanced]
    lines.append("[SnowpackAdvanced]")
    lines.append(f"VARIANT = {args.variant}")
    lines.append(f"ALBEDO_PARAMETERIZATION = {preset['ALBEDO_PARAMETERIZATION']}")
    lines.append(f"SNOW_ALBEDO = PARAMETERIZED")
    lines.append(f"HN_DENSITY = PARAMETERIZED")
    lines.append(f"HN_DENSITY_PARAMETERIZATION = {preset['HN_DENSITY_PARAMETERIZATION']}")
    lines.append(f"METAMORPHISM_MODEL = {preset['METAMORPHISM_MODEL']}")
    lines.append(f"VISCOSITY_MODEL = {preset['VISCOSITY_MODEL']}")
    lines.append(f"WATERTRANSPORTMODEL_SNOW = {preset['WATERTRANSPORTMODEL_SNOW']}")
    lines.append(f"WATERTRANSPORTMODEL_SOIL = {preset['WATERTRANSPORTMODEL_SOIL']}")
    lines.append(f"SNOW_EROSION = {preset['SNOW_EROSION']}")
    lines.append(f"MINIMUM_L_ELEMENT = 0.01")
    lines.append(f"MAX_NUMBER_MEAS_TEMPERATURES = 5")
    lines.append(f"NEW_SNOW_GRAIN_SIZE = 0.2")
    lines.append(f"HOAR_DENSITY_BURIED = 125.0")
    lines.append(f"HOAR_DENSITY_SURF = 100.0")
    lines.append(f"HOAR_THRESH_RH = 0.97")
    lines.append(f"HOAR_THRESH_TA = 1.2")
    lines.append(f"HOAR_THRESH_VW = 3.5")
    lines.append("")

    # [Filters] — MeteoIO data filtering
    lines.append("[Filters]")
    lines.append(f"TA::filter1 = min_max")
    lines.append(f"TA::arg1::min = 190")
    lines.append(f"TA::arg1::max = 340")
    lines.append(f"RH::filter1 = min_max")
    lines.append(f"RH::arg1::min = 0.01")
    lines.append(f"RH::arg1::max = 1.2")
    lines.append(f"VW::filter1 = min_max")
    lines.append(f"VW::arg1::min = -1")
    lines.append(f"VW::arg1::max = 70")
    lines.append(f"ISWR::filter1 = min_max")
    lines.append(f"ISWR::arg1::min = -10")
    lines.append(f"ISWR::arg1::max = 1500")
    lines.append(f"ILWR::filter1 = min_max")
    lines.append(f"ILWR::arg1::min = 100")
    lines.append(f"ILWR::arg1::max = 600")
    lines.append(f"PSUM::filter1 = min")
    lines.append(f"PSUM::arg1::min = -0.1")
    lines.append(f"HS::filter1 = min")
    lines.append(f"HS::arg1::min = 0.0")
    lines.append("")

    # Write file
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    content = "\n".join(lines)
    with open(args.output, "w") as f:
        f.write(content)

    result = {
        "status": "success",
        "output_file": args.output,
        "variant": args.variant,
        "station_id": args.station_id,
        "calculation_step_seconds": args.calculation_step,
        "forcing_mode": args.forcing,
        "sw_mode": args.sw_mode,
        "stability_scheme": preset["ATMOSPHERIC_STABILITY"],
        "water_transport": preset["WATERTRANSPORTMODEL_SNOW"],
        "n_sections": 6,
    }
    return result


def validate_outputs(result):
    """Check output for common configuration pitfalls."""
    warnings = []

    step = result.get("calculation_step_seconds", 900)
    if step > 900:
        warnings.append(f"Timestep {step}s > 15 min — may cause solver instability")
    if step < 60:
        warnings.append(f"Timestep {step}s < 1 min — very slow, was this intentional?")

    if result.get("forcing_mode") == "MASSBAL":
        warnings.append("MASSBAL forcing ignores radiation — only for simple mass balance")

    if warnings:
        result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate SNOWPACK INI configuration file"
    )
    parser.add_argument("--output", required=True, help="Output .ini file path")
    parser.add_argument("--station_id", required=True)
    parser.add_argument("--meteo_path", default="./input",
                        help="Path to meteorological input files")
    parser.add_argument("--output_path", default="./output",
                        help="Path for simulation output")
    parser.add_argument("--variant", default="DEFAULT",
                        choices=list(VARIANT_PRESETS.keys()))
    parser.add_argument("--calculation_step", type=float, default=900,
                        help="Timestep in SECONDS (default: 900 = 15 min)")
    parser.add_argument("--forcing", default="ATMOS",
                        choices=["ATMOS", "MASSBAL"])
    parser.add_argument("--sw_mode", default="BOTH",
                        choices=["INCOMING", "REFLECTED", "BOTH"])
    parser.add_argument("--stability", default=None,
                        help="Override stability scheme")
    parser.add_argument("--water_transport", default=None,
                        help="Override water transport model")
    parser.add_argument("--height_meteo", type=float, default=2.0,
                        help="Height of temperature/humidity sensor (m)")
    parser.add_argument("--height_wind", type=float, default=10.0,
                        help="Height of wind sensor (m)")
    parser.add_argument("--geo_heat", type=float, default=0.06,
                        help="Geothermal heat flux (W/m²)")
    parser.add_argument("--timezone", type=int, default=0,
                        help="UTC offset (hours)")
    parser.add_argument("--ts_days_between", type=float, default=0.041667,
                        help="Time series output interval (days; 0.041667 ≈ 1 hr)")
    parser.add_argument("--prof_days_between", type=float, default=1.0,
                        help="Profile output interval (days)")
    parser.add_argument("--canopy", action="store_true",
                        help="Enable canopy module")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
