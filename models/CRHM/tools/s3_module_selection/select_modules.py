#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      select_modules
Stage:        s3_module_selection
Description:  Configure CRHM module chain based on basin landscape type.

CRHM modules form a chain: output of one module feeds input to the next.
The ORDER MATTERS -- modules declare variables with declvar() and retrieve
variables from upstream modules with declgetvar(). If a module calls
declgetvar("SWE") but no earlier module produces SWE, the run fails.

Module Categories:
  - REQUIRED: basin, global, obs -- always first
  - RADIATION: Slope_Qsi, Annan -- slope/aspect corrections
  - CANOPY: CRHMCanopy, CRHMCanopyClearing -- forest interception
  - SNOW: SnobalCRHM, PBSM (prairie blowing snow), Needle (needle-leaf sublimation)
  - INFILTRATION: GreenAmpt (unfrozen), PrairieInfil (frozen soil), Greencrack
  - SOIL: Soil, SoilX, SoilDS -- soil moisture and drainage
  - ROUTING: Netroute, Netroute_D, Netroute_M, REWroute -- HRU-to-HRU routing

Landscape-specific chains:
  PRAIRIE:  basin > global > obs > PBSM > PrairieInfil > Soil > Netroute
  MOUNTAIN: basin > global > obs > Slope_Qsi > SnobalCRHM > GreenAmpt > Soil > Netroute
  FOREST:   basin > global > obs > CRHMCanopy > SnobalCRHM > GreenAmpt > Soil > Netroute
  ARCTIC:   basin > global > obs > PBSM > SnobalCRHM > PrairieInfil > Soil > REWroute

Inputs:
  --basin_type:  prairie, mountain, forest, arctic, mixed
  --processes:   Comma-separated process overrides
  --output_path: Output module chain JSON

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

# Complete CRHM module database
# Each module: provides (output vars), requires (input vars from other modules)
MODULE_DB = {
    "basin": {
        "category": "required",
        "description": "Basin properties: area, elevation, location",
        "provides": ["hru_area", "hru_elev", "hru_lat", "basin_area"],
        "requires": [],
        "order_hint": 1,
    },
    "global": {
        "category": "required",
        "description": "Global radiation and temperature calculations",
        "provides": ["Qsi", "Qso", "Qlisn", "Qliso", "SunMax", "QdroD", "QdfoD"],
        "requires": ["hru_lat"],
        "order_hint": 2,
    },
    "obs": {
        "category": "required",
        "description": "Read observation files and distribute to HRUs",
        "provides": ["hru_t", "hru_rh", "hru_u", "hru_p", "hru_ea", "hru_rain", "hru_snow"],
        "requires": [],
        "order_hint": 3,
    },
    "Slope_Qsi": {
        "category": "radiation",
        "description": "Correct solar radiation for slope and aspect",
        "provides": ["Qsi_slope"],
        "requires": ["Qsi", "hru_elev"],
        "order_hint": 4,
    },
    "Annan": {
        "category": "radiation",
        "description": "Estimate radiation from temperature range (Annandale method)",
        "provides": ["Qsi_estimated"],
        "requires": ["hru_t"],
        "order_hint": 4,
    },
    "CRHMCanopy": {
        "category": "canopy",
        "description": "Forest canopy interception, sublimation, drip, throughfall",
        "provides": ["net_snow", "net_rain", "intcp_evap", "Subl_Cpy"],
        "requires": ["hru_snow", "hru_rain", "hru_t", "hru_rh", "hru_u", "Qsi"],
        "order_hint": 5,
    },
    "CRHMCanopyClearing": {
        "category": "canopy",
        "description": "Combined canopy + clearing HRU processing",
        "provides": ["net_snow", "net_rain", "intcp_evap"],
        "requires": ["hru_snow", "hru_rain", "hru_t", "hru_rh", "hru_u", "Qsi"],
        "order_hint": 5,
    },
    "PBSM": {
        "category": "blowing_snow",
        "description": "Prairie Blowing Snow Model - transport, sublimation, redistribution",
        "provides": ["SWE", "Subl", "drift_in", "drift_out", "cumSubl", "cumDriftIn", "cumDriftOut"],
        "requires": ["hru_snow", "hru_t", "hru_rh", "hru_u"],
        "order_hint": 6,
        "key_params": ["fetch", "Ht", "distrib", "N_S", "A_S"],
    },
    "SnobalCRHM": {
        "category": "snowmelt",
        "description": "Energy-balance snowmelt (Snobal algorithm adapted for CRHM)",
        "provides": ["SWE", "snowmelt", "snowmeltD", "Qm", "z_s"],
        "requires": ["hru_snow", "hru_rain", "hru_t", "hru_rh", "hru_u", "Qsi"],
        "order_hint": 7,
    },
    "HMSA": {
        "category": "snowmelt",
        "description": "Simplified temperature-index snowmelt",
        "provides": ["SWE", "snowmelt"],
        "requires": ["hru_snow", "hru_t"],
        "order_hint": 7,
    },
    "Needle": {
        "category": "sublimation",
        "description": "Needle-leaf forest sublimation (intercepted snow)",
        "provides": ["Subl_needle"],
        "requires": ["hru_snow", "hru_t", "hru_rh", "hru_u"],
        "order_hint": 6,
    },
    "GreenAmpt": {
        "category": "infiltration",
        "description": "Green-Ampt infiltration for unfrozen soil",
        "provides": ["infil", "runoff", "meltrunoff"],
        "requires": ["snowmelt", "hru_rain"],
        "order_hint": 8,
    },
    "PrairieInfil": {
        "category": "infiltration",
        "description": "Frozen soil infiltration (Gray's equation for Canadian prairies)",
        "provides": ["infil", "runoff", "meltrunoff", "crackstat"],
        "requires": ["SWE", "snowmelt", "hru_rain", "hru_t"],
        "order_hint": 8,
        "key_params": ["fallstat", "major", "PriorInfiltration"],
    },
    "Greencrack": {
        "category": "infiltration",
        "description": "Green-Ampt with macropore (crack) flow for frozen clay soils",
        "provides": ["infil", "runoff", "meltrunoff"],
        "requires": ["SWE", "snowmelt", "hru_rain"],
        "order_hint": 8,
    },
    "Soil": {
        "category": "soil",
        "description": "Soil moisture, evapotranspiration, groundwater recharge",
        "provides": ["soil_moist", "soil_rechr", "ET_act", "gw_flow", "soil_runoff"],
        "requires": ["infil", "hru_t", "hru_rh"],
        "order_hint": 9,
    },
    "SoilX": {
        "category": "soil",
        "description": "Extended soil module with more layers",
        "provides": ["soil_moist", "soil_rechr", "ET_act", "gw_flow"],
        "requires": ["infil", "hru_t", "hru_rh"],
        "order_hint": 9,
    },
    "SoilDS": {
        "category": "soil",
        "description": "Dual-storage soil module",
        "provides": ["soil_moist", "soil_rechr", "ET_act"],
        "requires": ["infil", "hru_t"],
        "order_hint": 9,
    },
    "Netroute": {
        "category": "routing",
        "description": "Network routing between HRUs using Muskingum-Cunge",
        "provides": ["outflow", "inflow", "WS_outflow"],
        "requires": ["soil_runoff", "hru_area"],
        "order_hint": 10,
        "key_params": ["route_n", "route_L", "route_S0", "route_order"],
    },
    "Netroute_D": {
        "category": "routing",
        "description": "Distributed network routing (daily timestep)",
        "provides": ["outflow", "inflow"],
        "requires": ["soil_runoff", "hru_area"],
        "order_hint": 10,
    },
    "Netroute_M": {
        "category": "routing",
        "description": "Multiple-outlet network routing",
        "provides": ["outflow", "inflow"],
        "requires": ["soil_runoff", "hru_area"],
        "order_hint": 10,
    },
    "REWroute": {
        "category": "routing",
        "description": "Representative Elementary Watershed routing",
        "provides": ["WS_outflow", "outflow"],
        "requires": ["soil_runoff", "hru_area"],
        "order_hint": 10,
    },
}

# Pre-built module chains by landscape type
LANDSCAPE_CHAINS = {
    "prairie": {
        "description": "Canadian Prairie -- wind-exposed, blowing snow, frozen soil",
        "modules": ["basin", "global", "obs", "PBSM", "PrairieInfil", "Soil", "Netroute"],
        "rationale": "PBSM handles blowing snow transport/sublimation. PrairieInfil handles frozen soil infiltration.",
    },
    "mountain": {
        "description": "Mountain -- steep slopes, energy-balance melt, deep snowpack",
        "modules": ["basin", "global", "obs", "calcsun", "Slope_Qsi", "walmsley_wind",
                     "intcp", "pbsm", "albedo", "ebsm", "netall", "crack", "evap",
                     "Soil", "Netroute"],
        "rationale": "Full chain from validated Belly River (05AD005) .prj. calcsun+Slope_Qsi "
                     "for terrain radiation; walmsley_wind for ridge speedup; intcp+pbsm for "
                     "interception+blowing snow; albedo+ebsm for energy-balance melt; netall "
                     "for net radiation; crack for frozen soil infiltration; evap for ET.",
    },
    "forest": {
        "description": "Boreal/temperate forest -- canopy interception, sublimation",
        "modules": ["basin", "global", "obs", "CRHMCanopy", "SnobalCRHM", "GreenAmpt", "Soil", "Netroute"],
        "rationale": "CRHMCanopy handles interception/sublimation. SnobalCRHM for sub-canopy melt.",
    },
    "arctic": {
        "description": "Arctic/subarctic -- permafrost, blowing snow, minimal vegetation",
        "modules": ["basin", "global", "obs", "PBSM", "SnobalCRHM", "PrairieInfil", "Soil", "REWroute"],
        "rationale": "PBSM for blowing snow. PrairieInfil for frozen ground. REWroute for wetland routing.",
    },
    "mixed": {
        "description": "Mixed landscape -- forest clearings, variable terrain",
        "modules": ["basin", "global", "obs", "CRHMCanopyClearing", "SnobalCRHM", "GreenAmpt", "Soil", "Netroute"],
        "rationale": "CRHMCanopyClearing handles forest/clearing mix. SnobalCRHM for general melt.",
    },
}


def classify_basin_type(hru_config_path):
    """Auto-detect basin type from HRU config.

    Classification based on Pomeroy et al. (2007) CRHM design principles:
    - Mountain: relief > 500m, mixed alpine/forest land cover
    - Prairie: flat (relief < 300m), grassland/cropland, mid-latitude
    - Forest: dominated by forest, moderate relief
    - Arctic: high latitude (>60°N) or tundra land cover
    - Mixed: forest clearings or diverse landscape

    Args:
        hru_config_path: path to hru_config.json from S1

    Returns:
        basin_type string: 'prairie', 'mountain', 'forest', 'arctic', 'mixed'
    """
    import json
    with open(hru_config_path) as f:
        cfg = json.load(f)

    hrus = cfg['hrus']
    elev_range = cfg.get('elevation_range_m', [0, 0])
    if isinstance(elev_range, (list, tuple)) and len(elev_range) >= 2:
        relief = elev_range[1] - elev_range[0]
    else:
        elevs = [h['mean_elevation_m'] for h in hrus]
        relief = max(elevs) - min(elevs)

    # Get dominant land cover (by area)
    lc_area = {}
    total_area = 0
    mean_lat = 0
    for h in hrus:
        lc = h.get('land_cover_name', 'grassland')
        area = h.get('area_km2', 1)
        lc_area[lc] = lc_area.get(lc, 0) + area
        total_area += area
        mean_lat += h.get('mean_lat', h.get('center_lat', 50)) * area

    mean_lat /= max(total_area, 1)
    lc_fracs = {k: v / max(total_area, 1) for k, v in lc_area.items()}

    # Forest fraction
    forest_frac = sum(v for k, v in lc_fracs.items()
                      if 'forest' in k or 'conif' in k or 'decid' in k)
    # Open fraction (prairie/grassland/cropland)
    open_frac = sum(v for k, v in lc_fracs.items()
                    if k in ('open_prairie', 'grassland', 'cropland'))
    # Alpine fraction
    alpine_frac = lc_fracs.get('alpine', 0) + lc_fracs.get('bare', 0)

    # Classification logic
    if abs(mean_lat) > 60:
        basin_type = 'arctic'
        reason = f"latitude {mean_lat:.1f}° (>60°)"
    elif relief > 500:
        basin_type = 'mountain'
        reason = f"relief {relief:.0f}m (>500m)"
    elif relief < 300 and open_frac > 0.5:
        basin_type = 'prairie'
        reason = f"relief {relief:.0f}m (<300m), open fraction {open_frac:.0%}"
    elif forest_frac > 0.6:
        basin_type = 'forest'
        reason = f"forest fraction {forest_frac:.0%} (>60%)"
    elif forest_frac > 0.3 and open_frac > 0.2:
        basin_type = 'mixed'
        reason = f"forest {forest_frac:.0%} + open {open_frac:.0%}"
    else:
        basin_type = 'mountain'  # default for complex terrain
        reason = f"default (relief={relief:.0f}m, forest={forest_frac:.0%})"

    logger.info(f"Auto-detected basin type: {basin_type} ({reason})")
    return basin_type


def parse_args():
    parser = argparse.ArgumentParser(description="Select CRHM module chain")
    parser.add_argument("--basin_type", type=str, default="",
                        choices=list(LANDSCAPE_CHAINS.keys()) + [""],
                        help="Basin landscape type (auto-detected if omitted)")
    parser.add_argument("--hru_config", type=str, default="",
                        help="HRU config JSON for auto basin type detection")
    parser.add_argument("--processes", type=str, default="",
                        help="Comma-separated process overrides (e.g., blowing_snow,canopy)")
    parser.add_argument("--output_path", type=str, required=True,
                        help="Output module chain JSON file")
    return parser.parse_args()


def validate_inputs(basin_type, output_path):
    errors = []
    if basin_type not in LANDSCAPE_CHAINS:
        errors.append(f"Unknown basin_type: {basin_type}. Must be one of: {list(LANDSCAPE_CHAINS.keys())}")
    if not output_path:
        errors.append("Output path not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_chain(modules):
    """
    Verify module chain: all declgetvar dependencies satisfied by earlier modules.

    Returns list of warnings/errors.
    """
    issues = []
    provided_vars = set()

    for mod_name in modules:
        if mod_name not in MODULE_DB:
            issues.append(f"ERROR: Unknown module '{mod_name}'")
            continue

        mod = MODULE_DB[mod_name]
        # Check that all required variables are provided by earlier modules
        for req_var in mod["requires"]:
            if req_var not in provided_vars:
                # Check if it could be satisfied by obs
                if req_var.startswith("hru_"):
                    continue  # obs module provides hru_* variables
                issues.append(
                    f"WARNING: Module '{mod_name}' requires '{req_var}' but no earlier module provides it"
                )

        # Add this module's outputs to provided set
        provided_vars.update(mod["provides"])

    return issues


def process(basin_type, processes, output_path):
    """Build module chain configuration."""
    chain = LANDSCAPE_CHAINS[basin_type]
    modules = list(chain["modules"])

    # Apply process overrides
    if processes:
        process_list = [p.strip() for p in processes.split(",")]
        for proc in process_list:
            if proc == "blowing_snow" and "PBSM" not in modules:
                # Insert PBSM before infiltration
                for i, m in enumerate(modules):
                    if MODULE_DB.get(m, {}).get("category") == "infiltration":
                        modules.insert(i, "PBSM")
                        break
            elif proc == "canopy" and not any(m.startswith("CRHMCanopy") for m in modules):
                for i, m in enumerate(modules):
                    if MODULE_DB.get(m, {}).get("category") in ("blowing_snow", "snowmelt"):
                        modules.insert(i, "CRHMCanopy")
                        break
            elif proc == "sublimation" and "Needle" not in modules:
                for i, m in enumerate(modules):
                    if MODULE_DB.get(m, {}).get("category") == "snowmelt":
                        modules.insert(i, "Needle")
                        break

    # Validate chain
    issues = validate_chain(modules)
    for issue in issues:
        if issue.startswith("ERROR"):
            logger.error(issue)
        else:
            logger.warning(issue)

    # Build output
    module_details = []
    for i, mod_name in enumerate(modules):
        mod = MODULE_DB.get(mod_name, {})
        module_details.append({
            "order": i + 1,
            "name": mod_name,
            "category": mod.get("category", "unknown"),
            "description": mod.get("description", ""),
            "provides": mod.get("provides", []),
            "requires": mod.get("requires", []),
            "key_params": mod.get("key_params", []),
        })

    config = {
        "basin_type": basin_type,
        "description": chain["description"],
        "rationale": chain["rationale"],
        "module_chain": [m["name"] for m in module_details],
        "modules": module_details,
        "chain_validation": issues if issues else ["PASS: all dependencies satisfied"],
        "prj_module_declaration": _format_prj_modules(modules),
    }

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(config, f, indent=2)

    logger.info(f"Module chain ({basin_type}): {' > '.join(modules)}")
    return str(output_file)


def _format_prj_modules(modules):
    """Generate the Modules section for a .prj file."""
    lines = []
    for mod in modules:
        lines.append(f" +{mod} CRHM 04/20/06")
    return "\n".join(lines)


def validate_outputs(output_path):
    errors = []
    if not Path(output_path).exists():
        errors.append(f"Output file not created: {output_path}")
    else:
        with open(output_path) as f:
            config = json.load(f)
        chain = config.get("module_chain", [])
        if len(chain) < 3:
            errors.append("Module chain has fewer than 3 modules (need at least basin, global, obs)")
        if chain and chain[0] != "basin":
            errors.append("First module must be 'basin'")
        if chain and len(chain) > 1 and chain[1] != "global":
            errors.append("Second module must be 'global'")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    # Auto-detect basin type if not provided
    basin_type = args.basin_type
    if not basin_type and args.hru_config:
        basin_type = classify_basin_type(args.hru_config)
    elif not basin_type:
        logger.error("Either --basin_type or --hru_config is required")
        sys.exit(1)

    validate_inputs(basin_type, args.output_path)

    try:
        output_path = process(basin_type, args.processes, args.output_path)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)
    print(json.dumps({"status": "success", "output": output_path}))
    sys.exit(0)
