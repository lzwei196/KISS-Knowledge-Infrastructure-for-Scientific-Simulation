#!/usr/bin/env python3
"""
generate_config.py — Generate DHSVM input configuration file.

Assembles a complete DHSVM configuration file from parameters, file paths,
and optional template. Validates all sections and warns about common
configuration errors.

CRITICAL traps:
  - Date format is MM/DD/YYYY-HH (NOT ISO)
  - Time step is in hours (NOT seconds)
  - Grid spacing is in meters
  - Lapse rates are per-meter (NOT per-km)

Usage:
  python generate_config.py --template base.txt --dem-file input/dem.bin \\
      --forcing-dir forcing/ --soil-params soil.json --output INPUT.MyBasin

  python generate_config.py --nrows 425 --ncols 300 --cellsize 90 \\
      --north 5331870 --west 628440 --start 10/01/1970-00 --end 10/01/1971-00 \\
      --timestep 3 --dem-file dem.bin --mask-file mask.bin \\
      --forcing-dir forcing/ --output INPUT.Test
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


# --------------------------------------------------------------------------- #
# Default constants
# --------------------------------------------------------------------------- #
DEFAULT_CONSTANTS = {
    "Ground Roughness": 0.01,
    "Snow Roughness": 0.03,
    "Rain Threshold": -0.45,
    "Snow Threshold": 0.46,
    "Snow Water Capacity": 0.06,
    "Reference Height": 75.0,
    "Rain LAI Multiplier": 0.0001,
    "Snow LAI Multiplier": 0.0005,
    "Min Intercepted Snow": 0.005,
    "Outside Basin Value": 0,
    "Temperature Lapse Rate": -0.0065,
    "Precipitation Lapse Rate": 0.0000030,
}

DEFAULT_OPTIONS = {
    "Format": "BIN",
    "Extent": "BASIN",
    "Gradient": "TOPOGRAPHY",
    "Flow Routing": "NETWORK",
    "Sensible Heat Flux": "FALSE",
    "Sediment": "FALSE",
    "Sediment Input File": "NONE",
    "Overland Routing": "KINEMATIC",
    "Infiltration": "STATIC",
    "Interpolation": "NEAREST",
    "MM5": "FALSE",
    "QPF": "FALSE",
    "PRISM": "FALSE",
    "Gridded Met data": "FALSE",
    "Canopy radiation attenuation mode": "FIXED",
    "Shading": "FALSE",
    "Snotel": "FALSE",
    "Outside": "FALSE",
    "Rhoverride": "FALSE",
    "Precipitation Source": "STATION",
    "Wind Source": "STATION",
    "Temperature lapse rate": "CONSTANT",
    "Precipitation lapse rate": "CONSTANT",
    "Variable Light Transmittance": "FALSE",
    "Canopy Gapping": "FALSE",
    "Snow Sliding": "FALSE",
    "Stream Temperature": "FALSE",
}


def validate_inputs(args):
    """Validate configuration inputs."""
    errors = []

    # Check required files
    if args.dem_file and not os.path.isfile(args.dem_file):
        errors.append(f"DEM file not found: {args.dem_file}")
    if args.mask_file and not os.path.isfile(args.mask_file):
        errors.append(f"Mask file not found: {args.mask_file}")
    if args.forcing_dir and not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory not found: {args.forcing_dir}")

    # Validate grid parameters
    if args.nrows and args.nrows < 1:
        errors.append(f"nrows must be positive: {args.nrows}")
    if args.ncols and args.ncols < 1:
        errors.append(f"ncols must be positive: {args.ncols}")
    if args.cellsize and args.cellsize <= 0:
        errors.append(f"cellsize must be positive: {args.cellsize}")

    # Validate dates
    if args.start:
        try:
            parse_dhsvm_date(args.start)
        except ValueError:
            errors.append(f"Invalid start date: {args.start}. "
                          "Use MM/DD/YYYY-HH")
    if args.end:
        try:
            parse_dhsvm_date(args.end)
        except ValueError:
            errors.append(f"Invalid end date: {args.end}. Use MM/DD/YYYY-HH")

    # Validate timestep
    if args.timestep and args.timestep not in [1, 2, 3, 6, 12, 24]:
        errors.append(f"Unusual timestep: {args.timestep} hr")

    # Validate lapse rates (common trap: C/km instead of C/m)
    if args.temp_lapse:
        if abs(args.temp_lapse) > 0.1:
            errors.append(f"Temperature lapse rate {args.temp_lapse} looks "
                          "like C/km. DHSVM expects C/m (e.g., -0.0065)")

    if args.precip_lapse:
        if args.precip_lapse > 0.01:
            errors.append(f"Precipitation lapse rate {args.precip_lapse} "
                          "seems too large. DHSVM expects m/m "
                          "(e.g., 0.000003)")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def parse_dhsvm_date(datestr):
    """Parse DHSVM date format MM/DD/YYYY-HH."""
    for fmt in ["%m/%d/%Y-%H", "%m/%d/%Y-%H:%M:%S"]:
        try:
            return datetime.strptime(datestr.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse: {datestr}")


def load_soil_params(filepath):
    """Load soil parameters from JSON."""
    with open(filepath, "r") as f:
        data = json.load(f)
    return data.get("soil_types", data)


def process(args):
    """Generate DHSVM configuration file."""
    sections = []

    # ---- [OPTIONS] ----
    options = dict(DEFAULT_OPTIONS)
    if args.flow_routing:
        options["Flow Routing"] = args.flow_routing
    if args.gridded_met:
        options["Gridded Met data"] = "TRUE"
        options["Precipitation Source"] = "GRID"
        options["Wind Source"] = "GRID"

    sections.append(format_section("OPTIONS", options))

    # ---- [AREA] ----
    area = {}
    area["Coordinate System"] = args.coord_system or "UTM"
    if args.north:
        area["Extreme North"] = args.north
    if args.west:
        area["Extreme West"] = args.west
    if args.center_lat:
        area["Center Latitude"] = args.center_lat
    if args.center_lon:
        area["Center Longitude"] = args.center_lon
    if args.time_zone_meridian:
        area["Time Zone Meridian"] = args.time_zone_meridian
    if args.nrows:
        area["Number of Rows"] = args.nrows
    if args.ncols:
        area["Number of Columns"] = args.ncols
    if args.cellsize:
        area["Grid spacing"] = args.cellsize

    sections.append(format_section("AREA", area))

    # ---- [TIME] ----
    time_sec = {}
    time_sec["Time Step"] = args.timestep or 3
    if args.start:
        time_sec["Model Start"] = args.start
    if args.end:
        time_sec["Model End"] = args.end

    sections.append(format_section("TIME", time_sec))

    # ---- [CONSTANTS] ----
    constants = dict(DEFAULT_CONSTANTS)
    if args.temp_lapse:
        constants["Temperature Lapse Rate"] = args.temp_lapse
    if args.precip_lapse:
        constants["Precipitation Lapse Rate"] = args.precip_lapse
    if args.ref_height:
        constants["Reference Height"] = args.ref_height

    sections.append(format_section("CONSTANTS", constants))

    # ---- [TERRAIN] ----
    terrain = {}
    if args.dem_file:
        terrain["DEM File"] = args.dem_file
    if args.mask_file:
        terrain["Basin Mask File"] = args.mask_file

    sections.append(format_section("TERRAIN", terrain))

    # ---- [ROUTING] ----
    routing = {}
    if args.stream_map:
        routing["Stream Map File"] = args.stream_map
    if args.stream_network:
        routing["Stream Network File"] = args.stream_network
    if args.stream_class:
        routing["Stream Class File"] = args.stream_class

    if routing:
        sections.append(format_section("ROUTING", routing))

    # ---- [METEOROLOGY] ----
    met = {}
    if args.forcing_dir:
        met["Met File Path"] = args.forcing_dir
    if args.met_stations:
        met["Number of Stations"] = args.met_stations
    if args.grid_decimal:
        met["GRID_DECIMAL"] = args.grid_decimal

    if met:
        sections.append(format_section("METEOROLOGY", met))

    # ---- [SOILS] ----
    if args.soil_params and os.path.isfile(args.soil_params):
        soil_data = load_soil_params(args.soil_params)
        soil_sec = format_soil_section(soil_data, args.soil_map)
        sections.append(soil_sec)

    # ---- [OUTPUT] ----
    output_sec = {}
    if args.output_dir_model:
        output_sec["Output Directory"] = args.output_dir_model
    sections.append(format_section("OUTPUT", output_sec))

    config_text = "\n\n".join(sections) + "\n"

    result = {
        "status": "success",
        "sections": len(sections),
        "config_length": len(config_text),
    }

    # Write config file
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(config_text)
        result["output_file"] = args.output

    return result


def format_section(name, params):
    """Format a config section."""
    lines = [f"[{name}]"]
    max_key_len = max((len(k) for k in params), default=0)
    for key, val in params.items():
        padding = " " * (max_key_len - len(key) + 4)
        lines.append(f"{key}{padding}= {val}")
    return "\n".join(lines)


def format_soil_section(soil_types, soil_map=None):
    """Format the [SOILS] section with full parameter tables."""
    lines = ["[SOILS]"]

    if soil_map:
        lines.append(f"Soil Map File            = {soil_map}")

    if isinstance(soil_types, dict):
        n_types = len(soil_types)
    else:
        n_types = 1
        soil_types = {"1": soil_types}

    lines.append(f"Number of Soil Types     = {n_types}")
    lines.append("")

    for sid, params in soil_types.items():
        lines.append(f"# Soil type {sid}")
        lines.append(f"Soil Description       {sid}  = Type {sid}")
        lines.append(f"Lateral Conductivity   {sid}  = "
                      f"{params.get('lateral_conductivity', 1e-5)}")
        lines.append(f"Exponential Decrease   {sid}  = "
                      f"{params.get('exponential_decrease', 3.0)}")
        lines.append(f"Depth Threshold        {sid}  = "
                      f"{params.get('depth_threshold', 1.2)}")
        lines.append(f"Maximum Infiltration   {sid}  = "
                      f"{params.get('maximum_infiltration', 5e-5)}")
        lines.append(f"Capillary Drive        {sid}  = "
                      f"{params.get('capillary_drive', 0.07)}")
        lines.append(f"Surface Albedo         {sid}  = "
                      f"{params.get('surface_albedo', 0.2)}")
        lines.append(f"Manning n              {sid}  = "
                      f"{params.get('mannings_n', 0.013)}")

        nlayers = params.get("number_of_layers", 3)
        lines.append(f"Number of Soil Layers  {sid}  = {nlayers}")

        depths = params.get("layer_depths_m", [0.5, 1.0, 1.5])
        lines.append(f"Depth of Layer         {sid}  = "
                      + " ".join(f"{d}" for d in depths))

        for prop_name, key in [
            ("Porosity", "porosity"),
            ("Pore Size Distribution", "pore_size_distribution"),
            ("Bubbling Pressure", "bubbling_pressure_m"),
            ("Field Capacity", "field_capacity"),
            ("Wilting Point", "wilting_point"),
            ("Bulk Density", "bulk_density_kgm3"),
            ("Vertical Conductivity", "vertical_conductivity_ms"),
            ("Thermal Conductivity", "thermal_conductivity_Wm_K"),
            ("Thermal Capacity", "thermal_capacity_Jm3_K"),
        ]:
            vals = params.get(key, [0.4] * nlayers)
            lines.append(f"{prop_name:26s} {sid}  = "
                          + " ".join(f"{v}" for v in vals))
        lines.append("")

    return "\n".join(lines)


def validate_outputs(result):
    """Validate generated configuration."""
    if result.get("status") != "success":
        return result

    warnings = []

    output_file = result.get("output_file")
    if output_file and os.path.isfile(output_file):
        with open(output_file, "r") as f:
            text = f.read()

        required_sections = ["OPTIONS", "AREA", "TIME", "CONSTANTS", "TERRAIN"]
        for sec in required_sections:
            if f"[{sec}]" not in text:
                warnings.append(f"Missing section: [{sec}]")

        # Check for common issues
        if "Temperature Lapse Rate" in text:
            match = re.search(r"Temperature Lapse Rate\s*=\s*([\d.e+-]+)",
                              text)
            if match:
                val = float(match.group(1))
                if abs(val) > 0.1:
                    warnings.append("Temp lapse rate looks like C/km, "
                                    "should be C/m")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate DHSVM input configuration file")

    # Grid parameters
    parser.add_argument("--nrows", type=int, help="Number of rows")
    parser.add_argument("--ncols", type=int, help="Number of columns")
    parser.add_argument("--cellsize", type=float, help="Grid spacing (m)")
    parser.add_argument("--north", type=float, help="Extreme north coordinate")
    parser.add_argument("--west", type=float, help="Extreme west coordinate")
    parser.add_argument("--center-lat", type=float, help="Center latitude")
    parser.add_argument("--center-lon", type=float, help="Center longitude")
    parser.add_argument("--coord-system", default="UTM",
                        help="Coordinate system (default: UTM)")
    parser.add_argument("--time-zone-meridian", type=float,
                        help="Time zone meridian (degrees)")

    # Time parameters
    parser.add_argument("--start", help="Start date MM/DD/YYYY-HH")
    parser.add_argument("--end", help="End date MM/DD/YYYY-HH")
    parser.add_argument("--timestep", type=int, default=3,
                        help="Timestep in hours (default: 3)")

    # File paths
    parser.add_argument("--dem-file", help="Path to DEM binary file")
    parser.add_argument("--mask-file", help="Path to basin mask file")
    parser.add_argument("--soil-map", help="Path to soil type map")
    parser.add_argument("--soil-params", help="Soil parameters JSON file")
    parser.add_argument("--forcing-dir", help="Met forcing directory")
    parser.add_argument("--stream-map", help="Stream map file")
    parser.add_argument("--stream-network", help="Stream network file")
    parser.add_argument("--stream-class", help="Stream class file")

    # Met options
    parser.add_argument("--met-stations", type=int,
                        help="Number of met stations")
    parser.add_argument("--grid-decimal", type=int, default=5,
                        help="GRID_DECIMAL for met file names")
    parser.add_argument("--gridded-met", action="store_true",
                        help="Use gridded meteorological data")

    # Physical constants
    parser.add_argument("--temp-lapse", type=float,
                        help="Temperature lapse rate (C/m)")
    parser.add_argument("--precip-lapse", type=float,
                        help="Precipitation lapse rate (m/m)")
    parser.add_argument("--ref-height", type=float,
                        help="Reference height (m)")
    parser.add_argument("--flow-routing",
                        choices=["NETWORK", "UNIT_HYDROGRAPH"],
                        help="Flow routing method")

    # Output
    parser.add_argument("--template", help="Template config file to modify")
    parser.add_argument("--output-dir-model",
                        help="Model output directory path")
    parser.add_argument("--output", help="Output config file path")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if not args.output:
        print(output_json)
    else:
        print(output_json, file=sys.stderr)


if __name__ == "__main__":
    main()
