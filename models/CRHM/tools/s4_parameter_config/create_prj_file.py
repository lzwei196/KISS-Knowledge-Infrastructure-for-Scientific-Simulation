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
import re
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
        # ClassObs.cpp:68-72 diagnostic params. Only written when explicitly
        # overridden (--param_overrides), so default .prj files stay unchanged.
        # ClimChng_precip is the documented master VOLUME/PBIAS knob in SKILL.md
        # (multiplicative precip correction applied inside CRHM, no .obs rewrite).
        "ClimChng_flag": {"default": 0, "min": 0, "max": 1, "unit": "-",
                          "description": "0=maintain RH, 1=keep Vp within Vsat max",
                          "per_hru": True, "optional": True},
        "ClimChng_t": {"default": 0, "min": -50, "max": 50, "unit": "C",
                       "description": "Additive temperature change",
                       "per_hru": True, "optional": True},
        "ClimChng_precip": {"default": 1.0, "min": 0.0, "max": 10, "unit": "-",
                            "description": "Multiplicative precip change (PBIAS knob)",
                            "per_hru": True, "optional": True},
    },
    # Ranges and defaults below are transcribed from Classpbsm.cpp declparam()
    # (CRHM 4.7_16), not guessed. N_S/A_S are decldiagparam (diagnostic) there,
    # so they are marked optional and emitted only when explicitly overridden.
    "PBSM": {
        "fetch": {"default": 1000.0, "min": 300, "max": 10000, "unit": "m",
                  "description": "Fetch distance for blowing snow", "per_hru": True},
        "Ht": {"default": 0.3, "min": 0.001, "max": 100, "unit": "m",
               "description": "Vegetation height for snow trapping", "per_hru": True},
        # Classpbsm.cpp: "[0.0, 1.0]", range -10..10. NEGATIVE is meaningful --
        # it terminates the drift cascade ("all drift deposited") -- and the old
        # min of 0 made that mode unreachable through --param_overrides.
        "distrib": {"default": 0.0, "min": -10, "max": 10, "unit": "-",
                    "description": "Drift distribution fraction; >0 receives blown "
                                   "snow, <0 deposits all drift, 0 lets excess leave "
                                   "the domain. Cascades in HRU order, so HRUs must "
                                   "be ordered by ASCENDING vegetation height.",
                    "per_hru": True},
        "N_S": {"default": 320, "min": 1, "max": 500, "unit": "1/m^2",
                "description": "Vegetation number density (diagnostic)",
                "per_hru": True, "optional": True},
        "A_S": {"default": 0.003, "min": 0.0, "max": 2.0, "unit": "m",
                "description": "Stalk diameter (diagnostic)",
                "per_hru": True, "optional": True},
        # Classpbsm.cpp:132 decldiagparam("inhibit_bs", NHRU, "[0]", "0", "1"),
        # backed by `const long* inhibit_bs` -- an INTEGER switch, so pass 0/1.
        # SKILL.md "PBSM PROCESS-ACTIVITY GATE" RULE 2: the CRHM default is 0,
        # so omitting the line runs prairie blowing-snow physics inside forest
        # HRUs, which dag.yaml safety.validation_limits declares invalid. The
        # shipped Pomeroy projects write it explicitly (badlake.prj:178
        # "pbsm inhibit_bs <0 to 1>"; smithcreek.prj:457 puts the 1 on its
        # Ht = 6 m HRU). It was absent from this table, so `--param_overrides
        # "pbsm inhibit_bs"` was rejected as an unknown key and RULE 2 was
        # UNREACHABLE through the KI. optional=True => emitted ONLY when
        # explicitly overridden, so no existing .prj changes.
        "inhibit_bs": {"default": 0, "min": 0, "max": 1, "unit": "-",
                       "description": "Inhibit blowing snow on this HRU "
                                      "(1 = inhibit; set on every canopy HRU)",
                       "per_hru": True, "optional": True},
    },
    # Names and <min to max> transcribed from ClassSnobalCRHM.cpp declparam(),
    # lines 143-157. The previous table declared "T_g" (the binary declares
    # "hru_T_g"), and max fields ABOVE the declared ranges for max_z_s_0
    # (1.0 vs 0.35) and z_u/z_T (20 vs 10.0) -- which _clamped() silently
    # clamps, running a different model than the .prj states.
    "SnobalCRHM": {
        "hru_T_g": {"default": -4.0, "min": -50, "max": 50, "unit": "C",
                    "description": "Ground temperature at bottom of snowpack", "per_hru": True},
        "max_z_s_0": {"default": 0.1, "min": 0.0, "max": 0.35, "unit": "m",
                      "description": "Maximum active layer thickness", "per_hru": True},
        "z_u": {"default": 10.0, "min": 0.0, "max": 10.0, "unit": "m",
                "description": "Height of wind measurement (CMFD wind is 10 m)", "per_hru": True},
        "z_T": {"default": 2.0, "min": 0.0, "max": 10.0, "unit": "m",
                "description": "Height of air temp & vapour pressure measurement", "per_hru": True},
        "z_0": {"default": 0.005, "min": 0.0001, "max": 0.1, "unit": "m",
                "description": "Roughness length (open stubble/steppe snow surface)", "per_hru": True},
        "hru_rho_snow": {"default": 100.0, "min": 50, "max": 1000, "unit": "kg/m^3",
                         "description": "Density of falling snow", "per_hru": True},
    },
    # ebsm carries exactly ONE knob here, and it is optional=True so the line is
    # written ONLY when a caller explicitly overrides it -- every ebsm chain that
    # does not ask for it keeps byte-identical .prj output (the KI's standing rule
    # at :277 is that emitting a name the binary does not declare is worse than
    # emitting none, and Qe_subl_from_SWE is a decldiagparam, not a declparam).
    # Classebsm.cpp:81 declares <0 to 1> default [0]: with 0, the latent-heat
    # sublimation mass ebsm ALREADY computes (Qe_subl = Qe_ebsm/2.83) is added to
    # Qmelt and never leaves the pack; with 1 it is taken from SWE. This is the
    # TERTIARY arm of the Hulunbuir over-accumulation fix -- a partial one, since
    # both ebsm daily branches are gated on meltflag==1 (Classebsm.cpp:199,222)
    # and Classalbedo.cpp:150-182 holds meltflag at 0 through midwinter.
    "ebsm": {
        "Qe_subl_from_SWE": {"default": 0, "min": 0, "max": 1, "unit": "-",
                             "description": "0 - add latent-heat sublimation to Qmelt "
                                            "(original), 1 - take Qe_subl from SWE",
                             "per_hru": True, "optional": True},
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
        # Groundwater/subsurface conductances. Emitted ONLY when overridden, so
        # existing .prj output is byte-identical unless asked otherwise. These
        # are the knobs behind SKILL.md's highest-leverage documented fix (the
        # Bow "groundwater-baseflow lesson"): without them the tool could not
        # write the GW recipe at all and every validated basin hand-edited the .prj.
        "soil_gw_K": {"default": 1.0, "min": 0, "max": 100, "unit": "mm/d",
                      "description": "Soil -> groundwater recharge rate",
                      "per_hru": True, "optional": True},
        "gw_K": {"default": 0.1, "min": 0, "max": 100, "unit": "mm/d",
                 "description": "Groundwater release rate (SLOW sustains winter baseflow)",
                 "per_hru": True, "optional": True},
        "rechr_ssr_K": {"default": 1.0, "min": 0, "max": 100, "unit": "mm/d",
                        "description": "Recharge-zone -> subsurface runoff rate",
                        "per_hru": True, "optional": True},
        "lower_ssr_K": {"default": 2.0, "min": 0, "max": 100, "unit": "mm/d",
                        "description": "Lower-zone -> subsurface runoff rate",
                        "per_hru": True, "optional": True},
        "soil_ssr_runoff": {"default": 1, "min": 0, "max": 1, "unit": "-",
                            "description": "1 = subsurface routes the freshet",
                            "per_hru": True, "optional": True},
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
        # In-channel routing storage + lags. Emitted only when overridden.
        # SKILL.md (Blue River lesson): Kstorage governs the post-peak RECESSION
        # SHAPE, orthogonal to obs_elev which moves the peak TIMING.
        "Kstorage": {"default": 0.0, "min": 0, "max": 200, "unit": "d",
                     "description": "In-channel storage constant",
                     "per_hru": True, "optional": True},
        "Lag": {"default": 0.0, "min": 0, "max": 10000, "unit": "h",
                "description": "In-channel lag", "per_hru": True, "optional": True},
        "runLag": {"default": 0.0, "min": 0, "max": 10000, "unit": "h",
                   "description": "Surface runoff lag", "per_hru": True, "optional": True},
        "ssrLag": {"default": 0.0, "min": 0, "max": 10000, "unit": "h",
                   "description": "Subsurface runoff lag", "per_hru": True, "optional": True},
        "gwLag": {"default": 0.0, "min": 0, "max": 10000, "unit": "h",
                  "description": "Groundwater lag", "per_hru": True, "optional": True},
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

# ---------------------------------------------------------------------------
# Module-name aliases: DEFAULT_PARAMS above is keyed on the CAPITALISED GUI
# module names, but the validated chains -- and therefore every .prj this tool
# has ever written -- use the lower-case CLASSIC module names. The parameter
# loop skipped any module missing from DEFAULT_PARAMS, so `pbsm` silently got
# NO parameter block at all: fetch, Ht and distrib, the entire blowing-snow
# parameterisation that derive_parameters.py exists to compute, were never
# written to any .prj and CRHM fell back to its built-in defaults. Verified on
# the validated Yingluoxia .prj (2026-07-23): it declares `pbsm CRHM 11/20/17`
# in Modules and not one pbsm parameter line. `--param_overrides "pbsm fetch"`
# was likewise rejected as an unknown key, which is how this surfaced.
#
# Only pbsm is aliased. intcp/albedo/ebsm/netall have no verified parameter
# table here, and emitting a parameter name the binary does not declare is
# worse than emitting none.
#
# NOTE FOR VALIDATED MOUNTAIN BASINS: with this fix their next .prj WILL carry
# derived pbsm fetch/Ht/distrib for the first time, so their published metrics
# should be re-verified rather than assumed unchanged.
# "pbsmSnobal" is the blowing-snow module built to pair with SnobalCRHM: it does
# NOT declare its own SWE (it declputvar's into the Snobal pack, ClasspbsmSnobal
# .cpp:130-132) and it is the ONLY module that declares hru_drift / hru_subl,
# which SnobalCRHM declgetvar's at ClassSnobalCRHM.cpp:170-171. Its fetch / Ht /
# distrib / N_S / A_S declparam lines (ClasspbsmSnobal.cpp:110-118) are
# character-for-character identical to Classpbsm.cpp:116-124, so the PBSM table
# is exactly right for it. Without this alias _param_table() returns None and
# pbsmSnobal silently runs on binary defaults -- fetch 1000 m for every HRU and
# distrib 0, i.e. no inter-HRU drift transport at all -- discarding the derived
# land-cover fetch/Ht and the exposure-based distrib that derive_parameters.py
# computed. Additive: no chain shipped today contains pbsmSnobal.
MODULE_PARAM_ALIAS = {"pbsm": "PBSM", "pbsmSnobal": "PBSM"}


def _param_table(module_name):
    """DEFAULT_PARAMS table for a module, resolving classic/GUI name aliases."""
    if module_name in DEFAULT_PARAMS:
        return DEFAULT_PARAMS[module_name]
    alias = MODULE_PARAM_ALIAS.get(module_name)
    return DEFAULT_PARAMS.get(alias) if alias else None


def _clamped(value, param_info, key, hru_label=None):
    """Format a value for the .prj, forced inside its declared <min to max>.

    EVERY value this tool writes goes through here, because a .prj line that
    declares <300 to 10000> and carries 30 is not an error CRHM reports -- it
    clamps the value SILENTLY and runs a different model than the file
    describes (triplet dt_006). Out-of-range values reaching here are not
    hypothetical: `pbsm fetch` is declared <300 to 10000> m while s1 records a
    landscape fetch of 30 m for conifer, 50 m for deciduous and 100 m for
    shrub, so any forested HRU without a derived fetch lands under the floor.

    An override is still a HARD error (_override_values) -- an operator who
    typed a value deserves a failure, not a correction. A value that came from
    the land cover or a default is clamped and LOGGED, so the .prj is
    self-consistent and the adjustment is visible.
    """
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value)  # non-numeric; validate_outputs will catch it
    lo, hi = float(param_info["min"]), float(param_info["max"])
    c = min(hi, max(lo, x))
    if c == x:
        return str(value)
    logger.warning("%s%s = %g is outside the declared range <%g to %g>; writing "
                   "%g instead (CRHM would have clamped it silently).",
                   key, f" [HRU {hru_label}]" if hru_label is not None else "",
                   x, lo, hi, c)
    return str(int(c)) if float(c).is_integer() else str(c)


def _declared_range_violations(content):
    """Re-read the written Parameters block; report any value out of range.

    Independent of how the value was produced -- derived, land cover, default
    or override -- so a new value source cannot reintroduce the silent-clamp
    failure without this catching it at exit.
    """
    parts = content.split("######")
    body = None
    for i, part in enumerate(parts):
        if part.strip() == "Parameters:" and i + 1 < len(parts):
            body = parts[i + 1]
            break
    if body is None:
        return ["Parameters section not found"]

    decl_re = re.compile(r"^(\S+\s+\S+)\s+<\s*(\S+)\s+to\s+(\S+)\s*>$")
    violations = []
    declared = None
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = decl_re.match(stripped)
        if m:
            declared = (m.group(1), float(m.group(2)), float(m.group(3)))
            continue
        if declared is None:
            continue
        name, lo, hi = declared
        for token in stripped.split():
            try:
                v = float(token)
            except ValueError:
                violations.append(f"'{name}' has non-numeric value '{token}'")
                continue
            if not (lo <= v <= hi):
                violations.append(
                    f"'{name}' value {token} outside declared <{lo} to {hi}> "
                    f"-- CRHM would clamp it SILENTLY")
    return violations


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
    parser.add_argument("--param_overrides", type=str, default="",
                        help="JSON file path OR inline JSON of parameter overrides keyed "
                             "'<Module> <param>', e.g. '{\"obs obs_elev\": 3600, "
                             "\"Soil gw_max\": [1200,1500,1800]}'. Scalars are broadcast "
                             "to all HRUs. Unknown keys, wrong-length lists and "
                             "out-of-range values are hard errors (CRHM clamps silently).")
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


def process(hru_config_path, module_chain_path, obs_path, start_date, end_date, output_path, output_vars, derived_params_path="", param_overrides=None):
    """Generate .prj file."""
    with open(hru_config_path) as f:
        hru_config = json.load(f)

    overrides = dict(param_overrides or {})

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

    # --param_overrides: highest-priority source, keyed "<Module> <param>".
    # SKILL.md's tuning recipes (obs_elev, ClimChng_precip, the gw_max /
    # gw_init / Kstorage triplets) were previously applied by hand-editing the
    # generated .prj, which is exactly the kind of off-tool step that
    # reintroduces format bugs. An unknown key is a hard error, never a silent
    # no-op -- a silently-dropped override reads as "the knob did nothing".
    unknown = [k for k in overrides
               if len(k.split()) < 2
               or _param_table(k.split()[0]) is None
               or k.split(None, 1)[1] not in _param_table(k.split()[0])]
    if unknown:
        raise ValueError(f"Unknown param_overrides keys (module/param not in "
                         f"DEFAULT_PARAMS): {unknown}")
    inactive = [k for k in overrides if k.split()[0] not in modules]
    if inactive:
        raise ValueError(f"param_overrides target modules that are NOT in the "
                         f"module chain (they would be ignored): {inactive}")

    def _override_values(key, param_info):
        """Normalise an override to the list of values this param needs."""
        v = overrides[key]
        if not isinstance(v, (list, tuple)):
            v = [v] * (nhru if param_info.get("per_hru") else 1)
        if param_info.get("per_hru") and len(v) != nhru:
            raise ValueError(f"param_overrides['{key}'] has {len(v)} values, "
                             f"expected {nhru} (one per HRU)")
        for x in v:
            if not (float(param_info["min"]) <= float(x) <= float(param_info["max"])):
                raise ValueError(f"param_overrides['{key}'] value {x} outside "
                                 f"declared range <{param_info['min']} to "
                                 f"{param_info['max']}> -- CRHM would clamp it SILENTLY")
        return [str(x) for x in v]

    total_area = sum(h["area_km2"] for h in hrus)
    for mod in modules:
        table = _param_table(mod)
        if table is None:
            continue
        for param_name, param_info in table.items():
            key = f"{mod} {param_name}"
            if param_info.get("optional", False) and key not in overrides:
                continue  # diagnostic param: emit only when explicitly set
            pmin = param_info["min"]
            pmax = param_info["max"]
            # CRITICAL: basin geometry (hru_area/hru_elev/hru_lat/GSL/ASL and
            # basin_area) MUST be declared "Shared", never "basin <param>".
            # CRHM resolves each module's parameters as "<Module> <param>"
            # first, then "Shared <param>" (ClassModule.cpp declparam) -- a
            # "basin hru_area" line is visible ONLY to the basin module, so
            # Netroute silently runs with its default hru_area=[1] km2 and
            # basinflow comes out ~basin-area-fold too small (Heihe 2026-07:
            # 9908 km2 basin -> discharge ~1700x under, NSE pinned at -1.0).
            # obs likewise never sees hru_elev, so no lapse-rate banding.
            # Every working example (shipped badlake.prj, validated Belly v6)
            # declares these Shared.
            prefix = "Shared" if mod == "basin" else mod
            lines.append(f"{prefix} {param_name} <{pmin} to {pmax}>")
            if mod == "basin" and param_name == "basin_area":
                v = overrides.get(key)
                if v is not None:
                    lines.append(str(v))
                else:
                    lines.append(_clamped(round(total_area, 4), param_info, key))
                continue

            if param_info.get("ndefn", False):
                # Special dimension (e.g., obs_elev has 2 values)
                if key in overrides:
                    val = _override_values(key, param_info)[0]
                else:
                    derived_obs = derived.get("obs", {})
                    val = _clamped(derived_obs.get(param_name, param_info["default"]),
                                   param_info, key)
                lines.append(f"{val} {val}")  # same elevation for temp and precip
                continue

            if key in overrides:
                values = _override_values(key, param_info)
                if param_info.get("per_hru", False):
                    for i in range(0, len(values), 16):
                        lines.append(" ".join(values[i:i + 16]))
                else:
                    lines.append(values[0])
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
                    # Priority: derived > hru_config > default. Every branch
                    # ends in _clamped() so no source can put an out-of-range
                    # value in the file.
                    hru_label = hru.get("hru_id", hi + 1)
                    if derived_vals and hi < len(derived_vals):
                        raw = derived_vals[hi]
                    elif param_name == "hru_area":
                        raw = round(hru["area_km2"], 4)
                    elif param_name == "hru_elev":
                        raw = round(hru["mean_elevation_m"], 1)
                    elif param_name == "hru_lat":
                        # BUGFIX: this used to fall through to the 51.0 default,
                        # i.e. every .prj claimed the basin was at 51 deg N.
                        # calcsun/Slope_Qsi derive day length and solar geometry
                        # from hru_lat, so a wrong latitude silently mistimes
                        # melt energy. Harmless for the Canadian validation set
                        # (all ~49-53 N), badly wrong anywhere else.
                        lat = hru.get("center_lat", hru.get("mean_lat"))
                        if lat is None:
                            lat = hru_config.get("latitude")
                        if lat is None:
                            logger.warning(
                                "No basin latitude in hru_config -- hru_lat falls "
                                "back to %.1f deg. Re-run create_hru_config.py to "
                                "record the centroid.", param_info["default"])
                            lat = param_info["default"]
                        raw = round(float(lat), 4)
                    elif param_name == "Ht":
                        raw = max(param_info["min"],
                                  hru.get("veg_height_m", param_info["default"]))
                    elif param_name == "fetch":
                        # hru_config carries TWO fetch fields: `fetch_m` is the
                        # LANDSCAPE fetch (30 m under conifer, 50 m deciduous,
                        # 100 m shrub) and `pbsm_fetch_m` is the same quantity
                        # inside the range Classpbsm.cpp declares, <300 to
                        # 10000>. Only the latter may be written. Writing the
                        # raw landscape value is what made a forested default
                        # .prj declare <300 to 10000> and carry 30 -- silently
                        # clamped by CRHM, i.e. the dt_006 failure again.
                        # Configs written before s1 emitted pbsm_fetch_m fall
                        # back to fetch_m, and _clamped() reports the fix.
                        raw = hru.get("pbsm_fetch_m",
                                      hru.get("fetch_m", param_info["default"]))
                    else:
                        raw = param_info["default"]
                    values.append(_clamped(raw, param_info, key, hru_label))
                # Write in rows of max 16 values
                for i in range(0, len(values), 16):
                    lines.append(" ".join(values[i:i+16]))
            else:
                lines.append(_clamped(param_info["default"], param_info, key))

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
        errors.extend(_declared_range_violations(content))
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def _load_overrides(spec):
    """--param_overrides accepts a JSON file path or inline JSON."""
    if not spec:
        return {}
    if Path(spec).exists():
        with open(spec) as f:
            return json.load(f)
    return json.loads(spec)


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs(args.hru_config, args.module_chain, args.obs_path,
                    args.start_date, args.end_date, args.output_path)

    try:
        output_path = process(args.hru_config, args.module_chain, args.obs_path,
                              args.start_date, args.end_date, args.output_path, args.output_vars,
                              args.derived_params, _load_overrides(args.param_overrides))
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)
    print(json.dumps({"status": "success", "output": output_path}))
    sys.exit(0)
