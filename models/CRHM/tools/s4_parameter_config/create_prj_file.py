#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      create_prj_file
Stage:        s4_parameter_config
Description:  Generate CRHM .prj project file from HRU config, modules, and parameters.

.prj File Format (section-delimited by ######):
  ######
  Dimensions:      nhru N, nlay N, nobs N
  ######
  Macros:           macro definitions (optional)
  ######
  Observations:     path to .obs file(s)
  ######
  Dates:            start_date end_date (YYYY M D format)
  ######
  Modules:          +module_name source version
  ######
  Parameters:       parameter values per HRU
  ######
  Initial_State:    initial conditions (optional)
  ######
  Final_State:      end-of-run state (optional)
  ######
  Summary_period:   aggregation period
  ######
  Display_Variable: output variable selection
  ######

CRITICAL FORMAT RULES:
  - Sections MUST be delimited by exactly "######" on its own line
  - Parameter values are SPACE-separated, one row per parameter
  - Parameter declaration: "Module parameter_name <min to max>"
  - nhru values per parameter (one per HRU)
  - Values MUST be within the declared <min to max> range
  - Observation file paths: use RELATIVE paths from the directory
    where CRHM is invoked, or ABSOLUTE paths

Inputs:
  --hru_config:    HRU configuration JSON
  --module_chain:  Module chain JSON
  --obs_path:      Path to .obs file
  --start_date:    YYYY M D
  --end_date:      YYYY M D
  --output_path:   Output .prj file

Exit codes:
  0 -- success
  1 -- input validation failed
  2 -- processing error
  3 -- output validation failed
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Default parameter values by module
# Format: {module: {param: {default, min, max, description, unit}}}
DEFAULT_PARAMS = {
    "basin": {
        "basin_area": {"default": 100.0, "min": 0, "max": 1e12, "unit": "km2",
                       "description": "Total basin area"},
        "hru_area": {"default": 10.0, "min": 0, "max": 1e12, "unit": "km2",
                     "description": "Area of each HRU", "per_hru": True},
        "hru_elev": {"default": 500.0, "min": 0, "max": 9000, "unit": "m",
                     "description": "Mean elevation of each HRU", "per_hru": True},
        "hru_lat": {"default": 51.0, "min": -90, "max": 90, "unit": "deg",
                    "description": "Latitude of each HRU", "per_hru": True},
        "hru_GSL": {"default": 0.0, "min": -90, "max": 90, "unit": "deg",
                    "description": "Ground slope of each HRU", "per_hru": True},
        "hru_ASL": {"default": 0.0, "min": 0, "max": 360, "unit": "deg",
                    "description": "Aspect (azimuth from north)", "per_hru": True},
    },
    "obs": {
        "obs_elev": {"default": 0, "min": 0, "max": 100000, "unit": "m",
                     "description": "Observation/forcing station elevation",
                     "ndefn": True},  # special: 2 values, not per_hru
        "lapse_rate": {"default": 0.75, "min": 0, "max": 2, "unit": "C/100m",
                       "description": "Temperature lapse rate (Fang 2013: 0.75)", "per_hru": True},
        "precip_elev_adj": {"default": 0.0, "min": -1, "max": 1, "unit": "1/100m",
                            "description": "Precip adjustment per 100m elev diff (Belly River: 0.0005 alpine, 0 valley)",
                            "per_hru": True},
        "catchadjust": {"default": 0, "min": 0, "max": 4, "unit": "-",
                        "description": "Wind undercatch: 0=none, 1=Nipher, 3=Smith-Alter, 4=Kochendorfer",
                        "per_hru": True},
        "snow_rain_determination": {"default": 0, "min": 0, "max": 2, "unit": "-",
                                    "description": "0=air temp (robust default), 1=ice bulb, 2=Harder (needs qhum)",
                                    "per_hru": True},
    },
    "PBSM": {
        "fetch": {"default": 1000.0, "min": 10, "max": 10000, "unit": "m",
                  "description": "Fetch distance for blowing snow", "per_hru": True},
        "Ht": {"default": 0.3, "min": 0.001, "max": 100, "unit": "m",
               "description": "Vegetation height for snow trapping", "per_hru": True},
        "distrib": {"default": 1.0, "min": 0, "max": 10, "unit": "-",
                    "description": "Blowing snow distribution factor", "per_hru": True},
        "N_S": {"default": 1.0, "min": 0, "max": 10, "unit": "-",
                "description": "Number of sub-areas in drift pattern", "per_hru": True},
        "A_S": {"default": 1.0, "min": 0, "max": 10, "unit": "-",
                "description": "Area weight of sub-areas", "per_hru": True},
    },
    "SnobalCRHM": {
        "T_g": {"default": -4.0, "min": -40, "max": 5, "unit": "C",
                "description": "Ground temperature at bottom of snowpack", "per_hru": True},
        "max_z_s_0": {"default": 0.1, "min": 0.01, "max": 1.0, "unit": "m",
                      "description": "Maximum active layer depth", "per_hru": True},
        "z_u": {"default": 2.0, "min": 0.5, "max": 20, "unit": "m",
                "description": "Wind measurement height", "per_hru": True},
        "z_T": {"default": 2.0, "min": 0.5, "max": 20, "unit": "m",
                "description": "Temperature measurement height", "per_hru": True},
    },
    "PrairieInfil": {
        "fallstat": {"default": 1, "min": 0, "max": 3, "unit": "-",
                     "description": "Fall soil moisture condition (0=dry,1=typical,2=wet,3=saturated)"},
        "major": {"default": 2, "min": 0, "max": 5, "unit": "-",
                  "description": "Major melt event index"},
        "PriorInfiltration": {"default": 1, "min": 0, "max": 2, "unit": "-",
                              "description": "Prior infiltration state"},
    },
    "GreenAmpt": {
        "soil_type": {"default": 4, "min": 0, "max": 12, "unit": "-",
                      "description": "USDA texture: 0=water,1=sand,...,4=loam,...,11=clay,12=pavement",
                      "per_hru": True},
        "soil_moist_max": {"default": 375.0, "min": 0, "max": 5000, "unit": "mm",
                           "description": "Max available water (field_cap - wilt) × root_depth",
                           "per_hru": True},
        "soil_moist_init": {"default": 187.0, "min": 0, "max": 2500, "unit": "mm",
                            "description": "Initial soil moisture", "per_hru": True},
    },
    "Soil": {
        "soil_rechr_max": {"default": 60.0, "min": 0, "max": 350, "unit": "mm",
                           "description": "Max recharge zone storage (upper 30cm)", "per_hru": True},
        "soil_rechr_init": {"default": 30.0, "min": 0, "max": 250, "unit": "mm",
                            "description": "Initial recharge zone storage", "per_hru": True},
        "soil_moist_max": {"default": 375.0, "min": 0, "max": 5000, "unit": "mm",
                           "description": "Max total soil moisture", "per_hru": True},
        "soil_moist_init": {"default": 187.0, "min": 0, "max": 5000, "unit": "mm",
                            "description": "Initial soil moisture", "per_hru": True},
        "gw_max": {"default": 375.0, "min": 0, "max": 5000, "unit": "mm",
                   "description": "Max groundwater storage", "per_hru": True},
        "gw_init": {"default": 0.0, "min": 0, "max": 5000, "unit": "mm",
                    "description": "Initial groundwater storage", "per_hru": True},
        "Sdmax": {"default": 0.0, "min": 0, "max": 5000, "unit": "mm",
                  "description": "Max depression storage", "per_hru": True},
    },
    "Netroute": {
        "order": {"default": 1, "min": 1, "max": 1000, "unit": "-",
                  "description": "HRU routing process order", "per_hru": True},
        "whereto": {"default": 0, "min": 0, "max": 1000, "unit": "-",
                    "description": "Route to: 0=outlet, N=HRU N", "per_hru": True},
        "runKstorage": {"default": 0.0, "min": 0, "max": 200, "unit": "d",
                        "description": "Surface runoff storage constant", "per_hru": True},
        "ssrKstorage": {"default": 0.0, "min": 0, "max": 200, "unit": "d",
                        "description": "Subsurface runoff storage constant", "per_hru": True},
        "gwKstorage": {"default": 0.0, "min": 0, "max": 200, "unit": "d",
                       "description": "Groundwater storage constant", "per_hru": True},
        "Sdmax": {"default": 0.0, "min": 0, "max": 1000, "unit": "mm",
                  "description": "Max depression storage (Netroute)", "per_hru": True},
    },
    "evap": {
        "evap_type": {"default": 0, "min": 0, "max": 2, "unit": "-",
                      "description": "0=Granger (Fang §12), 1=Priestley-Taylor, 2=Penman-Monteith",
                      "per_hru": True},
        "F_Qg": {"default": 0.1, "min": 0, "max": 1, "unit": "-",
                 "description": "Ground heat flux fraction (Granger and Gray, 1990)", "per_hru": True},
        "Zwind": {"default": 10, "min": 0.01, "max": 100, "unit": "m",
                  "description": "Wind measurement height", "per_hru": True},
    },
    "walmsley_wind": {
        "A": {"default": 0.0, "min": 0, "max": 4.4, "unit": "-",
              "description": "Walmsley topographic wind coeff (Walmsley 1989)", "per_hru": True},
        "B": {"default": 0.0, "min": 0, "max": 2, "unit": "-",
              "description": "Walmsley topographic wind coeff", "per_hru": True},
        "L": {"default": 1000, "min": 40, "max": 1e6, "unit": "m",
              "description": "Upwind length at half height", "per_hru": True},
        "Walmsley_Ht": {"default": 0, "min": -1000, "max": 1000, "unit": "m",
                        "description": "Height relative to reference", "per_hru": True},
    },
    "crack": {
        "fallstat": {"default": 50, "min": -1, "max": 100, "unit": "%",
                     "description": "Fall soil saturation (Fang §3.2.5: from autumn SM measurements)",
                     "per_hru": True},
        "Major": {"default": 5, "min": 1, "max": 100, "unit": "mm/d",
                  "description": "Major melt threshold", "per_hru": True},
    },
    "CRHMCanopy": {
        "LAI": {"default": 3.0, "min": 0, "max": 15, "unit": "m2/m2",
                "description": "Leaf area index", "per_hru": True},
        "Sbar": {"default": 6.6, "min": 0, "max": 20, "unit": "kg/m2",
                 "description": "Maximum snow interception capacity", "per_hru": True},
        "Zcanopy": {"default": 10.0, "min": 0.1, "max": 50, "unit": "m",
                    "description": "Canopy height", "per_hru": True},
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description="Create CRHM .prj file")
    parser.add_argument("--hru_config", type=str, required=True, help="HRU config JSON")
    parser.add_argument("--module_chain", type=str, required=True, help="Module chain JSON")
    parser.add_argument("--obs_path", type=str, required=True, help="Path to .obs file")
    parser.add_argument("--start_date", type=str, required=True, help="Start date YYYY M D")
    parser.add_argument("--end_date", type=str, required=True, help="End date YYYY M D")
    parser.add_argument("--output_path", type=str, required=True, help="Output .prj file")
    parser.add_argument("--output_vars", type=str, default="",
                        help="Comma-separated output variables (e.g., SWE,snowmelt,outflow)")
    parser.add_argument("--derived_params", type=str, default="",
                        help="JSON from derive_parameters.py (overrides defaults)")
    return parser.parse_args()


def validate_inputs(hru_config, module_chain, obs_path, start_date, end_date, output_path):
    errors = []
    if not Path(hru_config).exists():
        errors.append(f"HRU config not found: {hru_config}")
    if not Path(module_chain).exists():
        errors.append(f"Module chain not found: {module_chain}")
    if not Path(obs_path).exists():
        errors.append(f"Obs file not found: {obs_path}")
    if not output_path:
        errors.append("Output path not set")
    # Validate date format
    for date_str, label in [(start_date, "start"), (end_date, "end")]:
        parts = date_str.strip().split()
        if len(parts) != 3:
            errors.append(f"{label}_date must be 'YYYY M D' format, got: {date_str}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process(hru_config_path, module_chain_path, obs_path, start_date, end_date, output_path, output_vars, derived_params_path=""):
    """Generate .prj file."""
    with open(hru_config_path) as f:
        hru_config = json.load(f)

    # Load derived parameters (from derive_parameters.py) if available
    derived = {}
    if derived_params_path and Path(derived_params_path).exists():
        with open(derived_params_path) as f:
            derived = json.load(f)
        logger.info("Using derived parameters from %s", derived_params_path)
    with open(module_chain_path) as f:
        mod_config = json.load(f)

    nhru = hru_config["nhru"]
    modules = mod_config["module_chain"]
    hrus = hru_config["hrus"]

    lines = []

    # Version header
    lines.append("Version NON DLL 4.02")
    lines.append(f"Generated by CRHM Knowledge Infrastructure")
    lines.append("")

    # Dimensions
    lines.append("######")
    lines.append("Dimensions:")
    lines.append("######")
    lines.append(f"nhru {nhru}")
    lines.append(f"nlay 1")
    lines.append(f"nobs 1")
    lines.append("")

    # Macros (empty)
    lines.append("######")
    lines.append("Macros:")
    lines.append("######")
    lines.append("")

    # Observations
    lines.append("######")
    lines.append("Observations:")
    lines.append("######")
    lines.append(str(obs_path))
    lines.append("")

    # Dates
    lines.append("######")
    lines.append("Dates:")
    lines.append("######")
    lines.append(start_date.strip())
    lines.append(end_date.strip())
    lines.append("")

    # Modules — MUST use flat format (not Macro group format)
    # The Macro format (Basin_Group Macro + +module lines) is GUI-only.
    # The CLI binary crashes with "Unknown Module: Basin_Group" if Macros are used.
    # Flat format: each module on its own line as "module_name CRHM date"
    # The dates are version stamps — use values from validated Belly River .prj
    MODULE_DATES = {
        'basin': '02/24/12', 'global': '12/19/19', 'obs': '04/17/18',
        'calcsun': '10/01/13', 'Slope_Qsi': '07/14/11', 'walmsley_wind': '06/21/07',
        'intcp': '02/24/15', 'pbsm': '11/20/17', 'PBSM': '11/20/17',
        'albedo': '08/11/11', 'ebsm': '01/18/16', 'SnobalCRHM': '01/18/16',
        'netall': '04/04/22', 'crack': '04/04/22', 'PrairieInfil': '04/04/22',
        'GreenAmpt': '04/04/22', 'evap': '03/18/22',
        'Soil': '04/05/22', 'Netroute': '04/05/22', 'REWroute': '04/05/22',
        'CRHMCanopy': '02/24/15',
    }
    lines.append("######")
    lines.append("Modules:")
    lines.append("######")
    for mod in modules:
        date = MODULE_DATES.get(mod, '04/20/06')
        lines.append(f"{mod} CRHM {date}")
    # NO empty line here — CRHM parses blank lines as empty module names

    # Parameters
    lines.append("######")
    lines.append("Parameters:")
    lines.append("######")

    for mod in modules:
        if mod not in DEFAULT_PARAMS:
            continue
        for param_name, param_info in DEFAULT_PARAMS[mod].items():
            pmin = param_info["min"]
            pmax = param_info["max"]
            lines.append(f"{mod} {param_name} <{pmin} to {pmax}>")

            if param_info.get("ndefn", False):
                # Special dimension (e.g., obs_elev has 2 values)
                derived_obs = derived.get("obs", {})
                val = derived_obs.get(param_name, param_info["default"])
                lines.append(f"{val} {val}")  # same elevation for temp and precip
                continue

            if param_info.get("per_hru", False):
                # Generate one value per HRU
                values = []
                # Check derived params for this parameter (all sections)
                derived_vals = None
                for section in ('soil', 'routing', 'obs', 'evap', 'walmsley_wind', 'pbsm', 'crack'):
                    v = derived.get(section, {}).get(param_name)
                    if v is not None:
                        derived_vals = v
                        break

                for hi, hru in enumerate(hrus):
                    # Priority: derived > hru_config > default
                    if derived_vals and hi < len(derived_vals):
                        values.append(str(derived_vals[hi]))
                    elif param_name == "hru_area":
                        values.append(str(round(hru["area_km2"], 4)))
                    elif param_name == "hru_elev":
                        values.append(str(round(hru["mean_elevation_m"], 1)))
                    elif param_name == "Ht":
                        ht = max(param_info["min"], hru.get("veg_height_m", param_info["default"]))
                        values.append(str(ht))
                    elif param_name == "fetch":
                        values.append(str(hru.get("fetch_m", param_info["default"])))
                    else:
                        values.append(str(param_info["default"]))
                # Write in rows of max 16 values
                for i in range(0, len(values), 16):
                    lines.append(" ".join(values[i:i+16]))
            else:
                lines.append(str(param_info["default"]))

    # Add basin_area
    total_area = sum(h["area_km2"] for h in hrus)
    lines.append(f"Shared basin_area <0 to 1e12>")
    lines.append(str(round(total_area, 4)))
    lines.append("")

    # Initial_State (empty)
    lines.append("######")
    lines.append("Initial_State:")
    lines.append("######")
    lines.append("")

    # Final_State (empty)
    lines.append("######")
    lines.append("Final_State:")
    lines.append("######")
    lines.append("")

    # Summary_period
    lines.append("######")
    lines.append("Summary_period:")
    lines.append("######")
    lines.append("Daily")
    lines.append("")

    # Display_Variable
    lines.append("######")
    lines.append("Display_Variable:")
    lines.append("######")
    if output_vars:
        for v in output_vars.split(","):
            lines.append(v.strip())
    else:
        # Default output variables — format: "module variable hru_indices"
        # These MUST include the module name prefix (CRHM ignores entries without it)
        # Validated against working belly_river_v6.prj
        routing_mod = "Netroute" if "Netroute" in modules else "REWroute" if "REWroute" in modules else None
        snow_mod = "SnobalCRHM" if "SnobalCRHM" in modules else "ebsm" if "ebsm" in modules else None
        hru_all = " ".join(str(i+1) for i in range(nhru))
        if routing_mod:
            lines.append(f"{routing_mod} basinflow 1")
            lines.append(f"{routing_mod} basingw 1")
        if snow_mod:
            lines.append(f"{snow_mod} SWE {hru_all}")
        lines.append(f"Soil soil_moist {hru_all}")
        if "evap" in modules:
            lines.append(f"evap hru_actet {hru_all}")
    lines.append("")

    # Display_Observation (empty)
    lines.append("######")
    lines.append("Display_Observation:")
    lines.append("######")
    lines.append("")

    # Write .prj file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        f.write("\n".join(lines))

    logger.info(f"Created .prj file with {nhru} HRUs, {len(modules)} modules")
    return str(output_file)


def validate_outputs(output_path):
    errors = []
    p = Path(output_path)
    if not p.exists():
        errors.append(f"Output file not created: {output_path}")
    elif p.stat().st_size == 0:
        errors.append("Output file is empty")
    else:
        content = p.read_text()
        required_sections = ["Dimensions:", "Observations:", "Dates:", "Modules:", "Parameters:"]
        for section in required_sections:
            if section not in content:
                errors.append(f"Missing section: {section}")
        if "nhru" not in content:
            errors.append("nhru not declared in Dimensions")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs(args.hru_config, args.module_chain, args.obs_path,
                    args.start_date, args.end_date, args.output_path)

    try:
        output_path = process(args.hru_config, args.module_chain, args.obs_path,
                              args.start_date, args.end_date, args.output_path, args.output_vars,
                              args.derived_params)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)
    print(json.dumps({"status": "success", "output": output_path}))
    sys.exit(0)
