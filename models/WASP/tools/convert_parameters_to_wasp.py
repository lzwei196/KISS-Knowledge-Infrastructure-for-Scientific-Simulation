#!/usr/bin/env python3
"""
convert_parameters_to_wasp.py -- Convert lake and kinetic parameters to WASP format.

Generates the parameter set required by the WASP water quality model:
  1. Lake morphometry (depth, area, volume)
  2. BOD-DO kinetic parameters (kd, ka, SOD, BOD0)
  3. Thermal stratification parameters (T_surface, T_bottom, thermo_depth, thermo_width)
  4. Seasonal temperature model parameters (T_mean, amplitude, phase)

Supports three modes:
  - lake-preset: Use built-in presets for known lakes (Erie, DeGray, Jordan, Mead)
  - manual:      Specify all parameters directly via CLI
  - from-csv:    Read parameters from a CSV file

CRITICAL UNIT TRAPS:
  - Lake area must be in km2. If in hectares, divide by 100 (dt_012).
  - Lake volume must be in m3. If in acre-ft, multiply by 1233.48 (dt_014).
  - Depth must be in meters. If in feet, multiply by 0.3048 (dt_005).
  - BOD decay rate kd must be in 1/d. If in 1/h, multiply by 24 (dt_010).
  - Reaeration rate ka must be in 1/d. If in 1/h, multiply by 24 (dt_011).
  - SOD (sediment oxygen demand) must be in g O2/m2/d. Typical range 0.1-3.0.

Usage:
    python convert_parameters_to_wasp.py \\
        --lake-preset erie \\
        --output params.json

    python convert_parameters_to_wasp.py \\
        --z-max-m 20 --z-mean-m 8 --area-km2 25.7 \\
        --kd 0.1 --ka 0.5 --bod0 3.0 \\
        --t-mean 15 --amplitude 10 --phase 130 \\
        --output params.json

    python convert_parameters_to_wasp.py \\
        --from-csv lake_params.csv \\
        --depth-unit ft --area-unit ha \\
        --output params.json
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None


# ---- Unit conversion constants ------------------------------------------------
FT_TO_M = 0.3048
HA_TO_KM2 = 0.01
ACRE_FT_TO_M3 = 1233.48
M2_TO_KM2 = 1e-6
HR_TO_DAY = 24.0


# ---- Lake presets -------------------------------------------------------------
# Sources: EPA NLA, USGS, state monitoring agencies
LAKE_PRESETS = {
    "erie": {
        "name": "Lake Erie (Central Basin)",
        "morphometry": {
            "z_max_m": 25.6,
            "z_mean_m": 18.3,
            "area_km2": 25745.0,
            "volume_m3": 484.0e9,
        },
        "kinetics": {
            "kd": 0.10,        # 1/d, BOD deoxygenation rate
            "ka": 0.51,        # 1/d, reaeration rate
            "BOD0": 3.0,       # mg/L, background BOD loading
            "DO_offset": 0.0,  # mg/L, systematic DO correction
            "SOD": 1.0,        # g O2/m2/d, sediment oxygen demand
        },
        "thermal": {
            "T_surface": 22.0,  # deg C, summer epilimnion
            "T_bottom": 8.0,    # deg C, hypolimnion
            "thermo_depth": 15.0,  # m
            "thermo_width": 3.0,   # m
        },
        "seasonal": {
            "T_mean": 9.53,       # deg C, from calibration
            "amplitude": 11.63,   # deg C
            "phase": 129.5,       # DOY
        },
        "hypo_depletion_rate": 0.05,  # per meter below thermocline
        "latitude": 41.5,        # degrees N
    },
    "degray": {
        "name": "DeGray Lake (Arkansas)",
        "morphometry": {
            "z_max_m": 59.4,
            "z_mean_m": 16.2,
            "area_km2": 54.6,
            "volume_m3": 883.5e6,
        },
        "kinetics": {
            "kd": 0.08,
            "ka": 0.35,
            "BOD0": 2.0,
            "DO_offset": 0.0,
            "SOD": 0.8,
        },
        "thermal": {
            "T_surface": 28.0,
            "T_bottom": 8.0,
            "thermo_depth": 10.0,
            "thermo_width": 2.5,
        },
        "seasonal": {
            "T_mean": 16.0,
            "amplitude": 10.0,
            "phase": 130.0,
        },
        "hypo_depletion_rate": 0.04,
        "latitude": 34.2,
    },
    "jordan": {
        "name": "Jordan Lake (North Carolina)",
        "morphometry": {
            "z_max_m": 17.4,
            "z_mean_m": 4.9,
            "area_km2": 56.7,
            "volume_m3": 277.8e6,
        },
        "kinetics": {
            "kd": 0.15,
            "ka": 0.60,
            "BOD0": 5.0,
            "DO_offset": 0.0,
            "SOD": 1.5,
        },
        "thermal": {
            "T_surface": 28.0,
            "T_bottom": 15.0,
            "thermo_depth": 5.0,
            "thermo_width": 1.5,
        },
        "seasonal": {
            "T_mean": 18.0,
            "amplitude": 9.0,
            "phase": 125.0,
        },
        "hypo_depletion_rate": 0.08,
        "latitude": 35.7,
    },
    "mead": {
        "name": "Lake Mead (Nevada/Arizona)",
        "morphometry": {
            "z_max_m": 162.0,
            "z_mean_m": 55.0,
            "area_km2": 660.0,
            "volume_m3": 36.7e9,
        },
        "kinetics": {
            "kd": 0.05,
            "ka": 0.20,
            "BOD0": 1.5,
            "DO_offset": 0.0,
            "SOD": 0.3,
        },
        "thermal": {
            "T_surface": 27.0,
            "T_bottom": 12.0,
            "thermo_depth": 25.0,
            "thermo_width": 5.0,
        },
        "seasonal": {
            "T_mean": 16.0,
            "amplitude": 8.0,
            "phase": 135.0,
        },
        "hypo_depletion_rate": 0.02,
        "latitude": 36.1,
    },
}


# ---- Parameter bounds ---------------------------------------------------------
PARAM_BOUNDS = {
    # Morphometry
    "z_max_m":       (1.0, 600.0),      # m
    "z_mean_m":      (0.5, 300.0),      # m
    "area_km2":      (0.01, 100000.0),  # km2
    "volume_m3":     (1e3, 1e15),       # m3

    # Kinetics
    "kd":            (0.01, 0.5),       # 1/d
    "ka":            (0.1, 2.0),        # 1/d
    "BOD0":          (0.5, 20.0),       # mg/L
    "DO_offset":     (-3.0, 3.0),       # mg/L
    "SOD":           (0.05, 5.0),       # g O2/m2/d

    # Thermal
    "T_surface":     (5.0, 35.0),       # deg C
    "T_bottom":      (2.0, 20.0),       # deg C
    "thermo_depth":  (1.0, 100.0),      # m
    "thermo_width":  (0.1, 20.0),       # m

    # Seasonal
    "T_mean":        (2.0, 30.0),       # deg C
    "amplitude":     (3.0, 18.0),       # deg C
    "phase":         (60.0, 200.0),     # DOY

    # DO profile
    "hypo_depletion_rate": (0.005, 0.2),  # per m below thermocline
}


def validate_inputs(args):
    """Validate all inputs before processing. Returns list of errors."""
    errors = []

    if args.from_csv and not os.path.isfile(args.from_csv):
        errors.append(f"Parameter CSV not found: {args.from_csv}")

    if args.lake_preset:
        preset_key = args.lake_preset.lower().strip()
        if preset_key not in LAKE_PRESETS:
            known = ", ".join(sorted(LAKE_PRESETS.keys()))
            errors.append(
                f"Unknown lake preset '{args.lake_preset}'. "
                f"Known presets: {known}")

    # If manual mode, check required morphometry parameters
    if not args.lake_preset and not args.from_csv:
        if args.z_max_m is None:
            errors.append("--z-max-m required when not using --lake-preset or --from-csv")

    if args.depth_unit not in ["m", "ft"]:
        errors.append(f"Invalid depth unit '{args.depth_unit}'. Must be 'm' or 'ft'.")

    if args.area_unit not in ["km2", "ha", "m2"]:
        errors.append(f"Invalid area unit '{args.area_unit}'. Must be 'km2', 'ha', or 'm2'.")

    if args.volume_unit not in ["m3", "acre-ft"]:
        errors.append(
            f"Invalid volume unit '{args.volume_unit}'. Must be 'm3' or 'acre-ft'.")

    if args.rate_unit not in ["1/d", "1/h"]:
        errors.append(
            f"Invalid rate unit '{args.rate_unit}'. Must be '1/d' or '1/h'.")

    return errors


def convert_depth_to_m(value, from_unit):
    """Convert depth to meters.

    CRITICAL: Using feet as meters places the thermocline 3x too deep,
    causing the model to predict isothermal profiles (dt_005).
    """
    if from_unit == "m":
        return value
    elif from_unit == "ft":
        return value * FT_TO_M
    else:
        raise ValueError(f"Unknown depth unit: {from_unit}")


def convert_area_to_km2(value, from_unit):
    """Convert lake area to km2.

    CRITICAL: Using hectares as km2 makes the lake 100x too large,
    affecting volume calculations and SOD scaling (dt_012).
    """
    if from_unit == "km2":
        return value
    elif from_unit == "ha":
        return value * HA_TO_KM2
    elif from_unit == "m2":
        return value * M2_TO_KM2
    else:
        raise ValueError(f"Unknown area unit: {from_unit}")


def convert_volume_to_m3(value, from_unit):
    """Convert volume to cubic meters.

    CRITICAL: Acre-feet are commonly used for US reservoirs (dt_014).
    """
    if from_unit == "m3":
        return value
    elif from_unit == "acre-ft":
        return value * ACRE_FT_TO_M3
    else:
        raise ValueError(f"Unknown volume unit: {from_unit}")


def convert_rate_to_per_day(value, from_unit):
    """Convert decay/reaeration rate to 1/d.

    CRITICAL: Using hourly rates in a daily model makes BOD decay
    24x too fast, depleting oxygen almost instantly (dt_010).
    """
    if from_unit == "1/d":
        return value
    elif from_unit == "1/h":
        return value * HR_TO_DAY
    else:
        raise ValueError(f"Unknown rate unit: {from_unit}")


def load_params_from_csv(csv_path, depth_unit, area_unit, volume_unit,
                         rate_unit, log):
    """Load parameters from a CSV file.

    Expected columns: parameter, value (and optionally: unit, description).
    """
    if pd is None:
        raise ImportError("pandas required for CSV loading")

    df = pd.read_csv(csv_path)
    log.append(f"Loaded parameter CSV: {csv_path} ({len(df)} rows)")

    params = {}
    for _, row in df.iterrows():
        name = str(row.get("parameter", row.get("name", ""))).strip()
        value = float(row.get("value", 0))

        # Apply unit conversion based on parameter type
        if name in ("z_max_m", "z_mean_m", "thermo_depth", "thermo_width"):
            value = convert_depth_to_m(value, depth_unit)
        elif name == "area_km2":
            value = convert_area_to_km2(value, area_unit)
        elif name == "volume_m3":
            value = convert_volume_to_m3(value, volume_unit)
        elif name in ("kd", "ka"):
            value = convert_rate_to_per_day(value, rate_unit)

        params[name] = value
        log.append(f"  {name} = {value}")

    return params


def estimate_volume(z_mean_m, area_km2):
    """Estimate lake volume from mean depth and surface area.

    Volume = z_mean * area
    """
    area_m2 = area_km2 * 1e6
    return z_mean_m * area_m2


def estimate_thermal_from_morphometry(z_max_m, latitude):
    """Estimate thermal stratification parameters from lake depth and latitude.

    Deeper lakes have deeper thermoclines. Lower latitudes have warmer surface T.
    These are rough initial estimates for calibration.
    """
    # Thermocline depth: roughly 1/3 to 2/3 of max depth, deeper in larger lakes
    thermo_depth = min(z_max_m * 0.4, 30.0)
    thermo_width = max(1.0, thermo_depth * 0.15)

    # Surface temperature from latitude
    # Approximate: T_surface = 35 - 0.3 * latitude (summer peak)
    T_surface = max(15.0, min(32.0, 35.0 - 0.3 * abs(latitude)))

    # Bottom temperature: 4 C for deep temperate lakes, warmer for shallow/tropical
    if z_max_m > 30:
        T_bottom = 4.0 + max(0, (abs(latitude) - 50) * -0.1)
    else:
        T_bottom = T_surface - min(z_max_m * 0.5, 15.0)
        T_bottom = max(4.0, T_bottom)

    return T_surface, T_bottom, thermo_depth, thermo_width


def estimate_seasonal_from_latitude(latitude):
    """Estimate seasonal temperature model parameters from latitude.

    Higher latitudes have larger seasonal amplitude and later phase.
    """
    T_mean = max(2.0, 30.0 - 0.5 * abs(latitude))
    amplitude = max(3.0, min(16.0, 0.3 * abs(latitude)))
    phase = 120.0 + max(0, (abs(latitude) - 30) * 0.5)

    return T_mean, amplitude, phase


def process(args):
    """Generate WASP parameter set."""
    log = []

    params = {
        "morphometry": {},
        "kinetics": {},
        "thermal": {},
        "seasonal": {},
        "hypo_depletion_rate": 0.05,
        "latitude": 40.0,
    }

    if args.lake_preset:
        # Use preset
        preset_key = args.lake_preset.lower().strip()
        preset = LAKE_PRESETS[preset_key]
        log.append(f"Using lake preset: {preset['name']}")

        params["morphometry"] = dict(preset["morphometry"])
        params["kinetics"] = dict(preset["kinetics"])
        params["thermal"] = dict(preset["thermal"])
        params["seasonal"] = dict(preset["seasonal"])
        params["hypo_depletion_rate"] = preset["hypo_depletion_rate"]
        params["latitude"] = preset["latitude"]
        params["lake_name"] = preset["name"]

        # Allow CLI overrides on top of preset
        if args.kd is not None:
            params["kinetics"]["kd"] = args.kd
        if args.ka is not None:
            params["kinetics"]["ka"] = args.ka
        if args.bod0 is not None:
            params["kinetics"]["BOD0"] = args.bod0
        if args.t_mean is not None:
            params["seasonal"]["T_mean"] = args.t_mean
        if args.amplitude is not None:
            params["seasonal"]["amplitude"] = args.amplitude
        if args.phase is not None:
            params["seasonal"]["phase"] = args.phase

    elif args.from_csv:
        # Load from CSV
        csv_params = load_params_from_csv(
            args.from_csv, args.depth_unit, args.area_unit,
            args.volume_unit, args.rate_unit, log)

        # Distribute into categories
        for key in ("z_max_m", "z_mean_m", "area_km2", "volume_m3"):
            if key in csv_params:
                params["morphometry"][key] = csv_params[key]
        for key in ("kd", "ka", "BOD0", "DO_offset", "SOD"):
            if key in csv_params:
                params["kinetics"][key] = csv_params[key]
        for key in ("T_surface", "T_bottom", "thermo_depth", "thermo_width"):
            if key in csv_params:
                params["thermal"][key] = csv_params[key]
        for key in ("T_mean", "amplitude", "phase"):
            if key in csv_params:
                params["seasonal"][key] = csv_params[key]
        if "hypo_depletion_rate" in csv_params:
            params["hypo_depletion_rate"] = csv_params["hypo_depletion_rate"]
        if "latitude" in csv_params:
            params["latitude"] = csv_params["latitude"]

    else:
        # Manual mode: build from CLI args
        log.append("Using manually specified parameters")

        # Morphometry (with unit conversion)
        z_max = convert_depth_to_m(args.z_max_m, args.depth_unit)
        z_mean = convert_depth_to_m(args.z_mean_m, args.depth_unit) \
            if args.z_mean_m else z_max * 0.4
        area = convert_area_to_km2(args.area_km2, args.area_unit) \
            if args.area_km2 else 10.0

        if args.volume_m3:
            volume = convert_volume_to_m3(args.volume_m3, args.volume_unit)
        else:
            volume = estimate_volume(z_mean, area)
            log.append(f"  Volume estimated from z_mean * area = {volume:.2e} m3")

        params["morphometry"] = {
            "z_max_m": z_max,
            "z_mean_m": z_mean,
            "area_km2": area,
            "volume_m3": volume,
        }

        # Kinetics (with unit conversion)
        kd = convert_rate_to_per_day(args.kd, args.rate_unit) \
            if args.kd else 0.10
        ka = convert_rate_to_per_day(args.ka, args.rate_unit) \
            if args.ka else 0.50
        params["kinetics"] = {
            "kd": kd,
            "ka": ka,
            "BOD0": args.bod0 if args.bod0 else 3.0,
            "DO_offset": args.do_offset if args.do_offset else 0.0,
            "SOD": args.sod if args.sod else 1.0,
        }

        # Latitude
        lat = args.latitude if args.latitude else 40.0
        params["latitude"] = lat

        # Thermal (estimate if not provided)
        if args.t_surface is not None:
            params["thermal"] = {
                "T_surface": args.t_surface,
                "T_bottom": args.t_bottom if args.t_bottom else 8.0,
                "thermo_depth": convert_depth_to_m(
                    args.thermo_depth, args.depth_unit) \
                    if args.thermo_depth else z_max * 0.4,
                "thermo_width": args.thermo_width if args.thermo_width else 2.0,
            }
        else:
            T_s, T_b, td, tw = estimate_thermal_from_morphometry(z_max, lat)
            params["thermal"] = {
                "T_surface": T_s,
                "T_bottom": T_b,
                "thermo_depth": td,
                "thermo_width": tw,
            }
            log.append("  Thermal params estimated from morphometry + latitude")

        # Seasonal (estimate if not provided)
        if args.t_mean is not None:
            params["seasonal"] = {
                "T_mean": args.t_mean,
                "amplitude": args.amplitude if args.amplitude else 10.0,
                "phase": args.phase if args.phase else 130.0,
            }
        else:
            Tm, amp, ph = estimate_seasonal_from_latitude(lat)
            params["seasonal"] = {
                "T_mean": Tm,
                "amplitude": amp,
                "phase": ph,
            }
            log.append("  Seasonal params estimated from latitude")

        # Hypolimnetic depletion
        params["hypo_depletion_rate"] = args.hypo_depletion \
            if args.hypo_depletion else 0.05

    # Log all parameters
    log.append("\nFinal parameter set:")
    for category, cat_params in params.items():
        if isinstance(cat_params, dict):
            log.append(f"\n  {category}:")
            for name, val in cat_params.items():
                if isinstance(val, float):
                    log.append(f"    {name:20s} = {val:.4f}")
                else:
                    log.append(f"    {name:20s} = {val}")
        elif isinstance(cat_params, (int, float)):
            log.append(f"  {category:22s} = {cat_params}")

    return params, log


def validate_output_params(params, log):
    """Verify all parameters are within valid ranges."""
    ok = True
    warnings = []

    def check_bound(name, value, category=""):
        nonlocal ok
        if name in PARAM_BOUNDS:
            lo, hi = PARAM_BOUNDS[name]
            if value < lo or value > hi:
                warnings.append(
                    f"[ERROR] {category}.{name} = {value} outside "
                    f"valid range [{lo}, {hi}]")
                ok = False
            elif value == lo or value == hi:
                warnings.append(
                    f"[WARN] {category}.{name} = {value} at range boundary "
                    f"[{lo}, {hi}]")

    # Check morphometry
    for name, val in params.get("morphometry", {}).items():
        check_bound(name, val, "morphometry")

    # Check kinetics
    for name, val in params.get("kinetics", {}).items():
        check_bound(name, val, "kinetics")

    # Check thermal
    for name, val in params.get("thermal", {}).items():
        check_bound(name, val, "thermal")

    # Check seasonal
    for name, val in params.get("seasonal", {}).items():
        check_bound(name, val, "seasonal")

    check_bound("hypo_depletion_rate", params.get("hypo_depletion_rate", 0.05))

    # Physics cross-checks
    morph = params.get("morphometry", {})
    thermal = params.get("thermal", {})
    kinetics = params.get("kinetics", {})
    seasonal = params.get("seasonal", {})

    # Mean depth should not exceed max depth
    if morph.get("z_mean_m", 0) > morph.get("z_max_m", 999):
        warnings.append(
            "[ERROR] z_mean > z_max -- mean depth cannot exceed maximum depth")
        ok = False

    # Thermocline should be within lake depth
    if thermal.get("thermo_depth", 0) > morph.get("z_max_m", 999):
        warnings.append(
            "[WARN] thermo_depth > z_max -- thermocline deeper than lake")

    # Surface should be warmer than bottom (summer stratification)
    if thermal.get("T_surface", 20) < thermal.get("T_bottom", 5):
        warnings.append(
            "[WARN] T_surface < T_bottom -- inverted stratification "
            "(only valid for winter conditions)")

    # ka should generally exceed kd for DO recovery
    if kinetics.get("ka", 0.5) < kinetics.get("kd", 0.1):
        warnings.append(
            "[INFO] ka < kd -- reaeration slower than deoxygenation. "
            "This produces a persistent DO sag without recovery.")

    # Seasonal amplitude should be positive
    if seasonal.get("amplitude", 10) < 0:
        warnings.append(
            "[WARN] Negative seasonal amplitude -- use positive value")

    log.extend(warnings)
    return ok


def main():
    parser = argparse.ArgumentParser(
        description="Convert lake/kinetic parameters to WASP format")

    # Mode selection
    parser.add_argument("--lake-preset", default=None,
                        help="Use built-in lake preset (erie, degray, jordan, mead)")
    parser.add_argument("--from-csv", default=None,
                        help="Load parameters from CSV file")

    # Morphometry (manual mode)
    parser.add_argument("--z-max-m", type=float, default=None,
                        help="Maximum lake depth")
    parser.add_argument("--z-mean-m", type=float, default=None,
                        help="Mean lake depth (default: 0.4 * z_max)")
    parser.add_argument("--area-km2", type=float, default=None,
                        help="Lake surface area")
    parser.add_argument("--volume-m3", type=float, default=None,
                        help="Lake volume (estimated from z_mean*area if omitted)")

    # Kinetics (manual mode)
    parser.add_argument("--kd", type=float, default=None,
                        help="BOD deoxygenation rate (default: 0.10 /d)")
    parser.add_argument("--ka", type=float, default=None,
                        help="Reaeration rate (default: 0.50 /d)")
    parser.add_argument("--bod0", type=float, default=None,
                        help="Background BOD loading (default: 3.0 mg/L)")
    parser.add_argument("--do-offset", type=float, default=None,
                        help="Systematic DO correction (default: 0.0 mg/L)")
    parser.add_argument("--sod", type=float, default=None,
                        help="Sediment oxygen demand (default: 1.0 g O2/m2/d)")

    # Thermal (manual mode)
    parser.add_argument("--t-surface", type=float, default=None,
                        help="Summer epilimnion temperature (deg C)")
    parser.add_argument("--t-bottom", type=float, default=None,
                        help="Hypolimnion temperature (deg C)")
    parser.add_argument("--thermo-depth", type=float, default=None,
                        help="Thermocline depth (m)")
    parser.add_argument("--thermo-width", type=float, default=None,
                        help="Thermocline transition width (m)")

    # Seasonal (manual mode)
    parser.add_argument("--t-mean", type=float, default=None,
                        help="Annual mean surface temperature (deg C)")
    parser.add_argument("--amplitude", type=float, default=None,
                        help="Seasonal temperature amplitude (deg C)")
    parser.add_argument("--phase", type=float, default=None,
                        help="Day of year of temperature peak offset")

    # DO profile
    parser.add_argument("--hypo-depletion", type=float, default=None,
                        help="Hypolimnetic DO depletion rate (per m below thermo)")

    # Latitude
    parser.add_argument("--latitude", type=float, default=None,
                        help="Lake latitude in degrees (for estimation)")

    # Unit options
    parser.add_argument("--depth-unit", default="m",
                        choices=["m", "ft"],
                        help="Input depth unit (default: m)")
    parser.add_argument("--area-unit", default="km2",
                        choices=["km2", "ha", "m2"],
                        help="Input area unit (default: km2)")
    parser.add_argument("--volume-unit", default="m3",
                        choices=["m3", "acre-ft"],
                        help="Input volume unit (default: m3)")
    parser.add_argument("--rate-unit", default="1/d",
                        choices=["1/d", "1/h"],
                        help="Input rate unit for kd, ka (default: 1/d)")

    # Output
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    args = parser.parse_args()

    # Step 1: validate inputs
    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Step 2: process
    result = process(args)
    if isinstance(result, tuple):
        params, log = result
    else:
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Step 3: validate outputs
    params_ok = validate_output_params(params, log)

    # Step 4: build output
    output_data = {
        "status": "success" if params_ok else "warning",
        "model": "WASP",
        "parameters": params,
        "bounds": {name: list(bounds) for name, bounds in PARAM_BOUNDS.items()},
        "param_details": {
            "morphometry": {
                "z_max_m":  {"unit": "m",   "description": "Maximum lake depth"},
                "z_mean_m": {"unit": "m",   "description": "Mean lake depth"},
                "area_km2": {"unit": "km2", "description": "Lake surface area"},
                "volume_m3":{"unit": "m3",  "description": "Total lake volume"},
            },
            "kinetics": {
                "kd":       {"unit": "1/d",        "description": "BOD deoxygenation rate (Streeter-Phelps)"},
                "ka":       {"unit": "1/d",        "description": "Atmospheric reaeration rate"},
                "BOD0":     {"unit": "mg/L",       "description": "Background BOD loading"},
                "DO_offset":{"unit": "mg/L",       "description": "Systematic DO correction"},
                "SOD":      {"unit": "g O2/m2/d",  "description": "Sediment oxygen demand"},
            },
            "thermal": {
                "T_surface":    {"unit": "deg C", "description": "Summer epilimnion temperature"},
                "T_bottom":     {"unit": "deg C", "description": "Hypolimnion temperature"},
                "thermo_depth": {"unit": "m",     "description": "Thermocline depth (max dT/dz)"},
                "thermo_width": {"unit": "m",     "description": "Thermocline transition width"},
            },
            "seasonal": {
                "T_mean":    {"unit": "deg C", "description": "Annual mean surface temperature"},
                "amplitude": {"unit": "deg C", "description": "Seasonal temperature swing"},
                "phase":     {"unit": "DOY",   "description": "Day of year peak offset"},
            },
        },
        "note": "These are initial estimates. Calibrate against observed T and DO.",
        "log": log,
    }

    # Step 5: write output
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2)

    # Print summary
    for line in log:
        print(line)
    print(f"\nOutput written to {args.output}")


if __name__ == "__main__":
    main()
