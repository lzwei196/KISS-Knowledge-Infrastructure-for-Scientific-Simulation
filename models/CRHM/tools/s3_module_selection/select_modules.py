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
            REJECTED -- no module declares 'snowmelt' for PrairieInfil.
            Use 'prairie_reduced'.
  PRAIRIE_REDUCED: basin > global > obs > calcsun > intcp > pbsmSnobal >
            albedo > SnobalCRHM > netall > crack > evap > Soil > Netroute
            SnobalCRHM MUST be paired with pbsmSnobal, never plain pbsm
            (segfault, triplet dt_v012).
  MOUNTAIN_REDUCED (the validated chain): basin > global > obs > calcsun >
            intcp > pbsm > albedo > ebsm > netall > crack > evap > Soil > Netroute
  FOREST / MIXED / ARCTIC presets are listed in LANDSCAPE_CHAINS but are
            REFUSED by validate_chain(): they use GUI class names the CLI
            binary does not register (CRHMCanopy, CRHMCanopyClearing, PBSM,
            PrairieInfil, REWroute) and SnobalCRHM without pbsmSnobal. They
            never ran with this binary.

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
    # ------------------------------------------------------------------ #
    # The lower-case classic-CRHM modules that EVERY validated chain in
    # SKILL.md actually uses. They were absent from this database, so
    # validate_chain() reported the validated 13-module chain as eight
    # "Unknown module" ERRORs -- which trained everyone to ignore
    # chain_validation entirely, and hid the real structural faults below.
    # ------------------------------------------------------------------ #
    "walmsley_wind": {
        "category": "wind",
        "description": "Walmsley topographic wind speed-up over ridges and slopes",
        "provides": ["hru_u_adj", "Walmsley_u"],
        "requires": ["hru_u"],
        "order_hint": 4,
        "key_params": ["A", "B", "L", "Walmsley_Ht"],
    },
    "calcsun": {
        "category": "radiation",
        "description": "Solar geometry: sun angles, day length, extraterrestrial radiation",
        "provides": ["SunMax", "QdroD", "QdfoD", "Qdro", "Qdfo", "cosxs", "cosxsflat"],
        "requires": ["hru_lat"],
        "order_hint": 4,
    },
    "intcp": {
        "category": "canopy",
        "description": "Canopy interception of rain and snow; emits the canopy-adjusted "
                       "precipitation (net_rain/net_snow) that the whole snow chain reads",
        "provides": ["net_rain", "net_snow", "net_p", "intcp_evap", "Subl_Cpy"],
        "requires": ["hru_rain", "hru_snow", "hru_t", "hru_u"],
        "order_hint": 5,
        "key_params": ["Ht", "LAI", "Sbar", "CanopyClearing"],
    },
    "pbsm": {
        "category": "blowing_snow",
        "description": "Prairie Blowing Snow Model (classic): wind transport, sublimation, "
                       "redistribution; declares the SWE state",
        "provides": ["SWE", "Subl", "drift_in", "drift_out", "snowdepth",
                     "cumSubl", "cumDriftIn", "cumDriftOut"],
        "requires": ["net_snow", "hru_u", "hru_t", "hru_rh"],
        "order_hint": 6,
        "key_params": ["fetch", "Ht", "distrib", "N_S", "A_S", "inhibit_bs"],
    },
    # The blowing-snow module built to pair with SnobalCRHM. It keeps NO
    # snowpack of its own: it declputvar's SWE / z_s / rho INTO the Snobal pack
    # (ClasspbsmSnobal.cpp:130-132) and it is the ONLY module that declares
    # hru_drift / hru_subl (ClasspbsmSnobal.cpp:74,76), which SnobalCRHM
    # declgetvar's at ClassSnobalCRHM.cpp:170-171. Plain pbsm declares
    # Subl / Drift instead (Classpbsm.cpp:76,78), so pbsm + SnobalCRHM leaves
    # those two pointers NULL and the binary segfaults on the first timestep
    # (triplet dt_v012). See the pairing checks in validate_chain().
    "pbsmSnobal": {
        "category": "blowing_snow",
        "description": "Prairie Blowing Snow Model for the Snobal snowpack: wind "
                       "transport and sublimation taken from SnobalCRHM's SWE; "
                       "declares hru_drift / hru_subl, declares NO SWE of its own",
        "provides": ["hru_subl", "hru_drift", "Drift_out", "Drift_in", "snowdepth",
                     "cumSubl", "cumDrift", "cumDriftIn"],
        "requires": ["net_snow", "hru_u", "hru_t", "hru_ea"],
        "order_hint": 6,
        "key_params": ["fetch", "Ht", "distrib", "N_S", "A_S", "inhibit_bs"],
    },
    "albedo": {
        "category": "snowmelt",
        "description": "Snow albedo accumulation/decay",
        "provides": ["Albedo", "snowcover"],
        "requires": ["SWE", "net_snow"],
        "order_hint": 7,
        "key_params": ["Albedo_bare", "Albedo_snow"],
    },
    "ebsm": {
        "category": "snowmelt",
        "description": "Energy-balance snowmelt (Gray & Landine)",
        "provides": ["snowmelt", "snowmeltD", "meltflag", "cumsnowmelt"],
        "requires": ["SWE", "Albedo", "net_rain", "net_snow"],
        "order_hint": 8,
        "key_params": ["tfactor", "nfactor"],
    },
    "netall": {
        "category": "radiation",
        "description": "Net all-wave radiation over snow and bare ground",
        "provides": ["Qn", "Qnsn", "Qsisn", "net_rad"],
        "requires": ["Albedo"],
        "order_hint": 8,
    },
    "crack": {
        "category": "infiltration",
        "description": "Frozen-soil infiltration (Gray's equation) with crack/macropore flow",
        "provides": ["infil", "runoff", "meltrunoff", "crackstat", "cuminfil"],
        "requires": ["snowmelt", "net_rain"],
        "order_hint": 9,
        "key_params": ["fallstat", "Major", "infDays"],
    },
    "evap": {
        "category": "evaporation",
        "description": "Evapotranspiration (Granger land / Priestley-Taylor water)",
        "provides": ["hru_actet", "hru_evap", "cumhru_actet"],
        "requires": ["hru_t", "hru_rh"],
        "order_hint": 9,
        "key_params": ["evap_type", "Ht", "inhibit_evap"],
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
        "description": "Canadian Prairie (LEGACY, REJECTED -- structurally broken, "
                       "use 'prairie_reduced')",
        "modules": ["basin", "global", "obs", "intcp", "PBSM", "PrairieInfil",
                    "Soil", "Netroute"],
        "rationale": "PBSM handles blowing snow transport/sublimation. PrairieInfil handles "
                     "frozen soil infiltration. NOT VALIDATED in this KI, and it carries no "
                     "energy-balance melt (no albedo/netall/ebsm), so simulated SWE ablates "
                     "on the wrong physics -- use 'prairie_reduced' for any run scored on "
                     "SWE or discharge. 'intcp' was added because the chain otherwise has no "
                     "provider for net_rain/net_snow and CRHM segfaults (dt_v006). KEPT ONLY "
                     "AS A NAMED FAILURE: with no melt module at all, nothing declares "
                     "'snowmelt' and PrairieInfil's declgetvar cannot resolve, so this chain "
                     "is not merely unvalidated, it is unrunnable. validate_inputs() rejects "
                     "it (see DEPRECATED_CHAINS); the entry stays so the rejection can "
                     "explain itself instead of reading as an unknown basin_type.",
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
    "mountain_reduced": {
        "description": "Mountain (VALIDATED reduced chain) -- energy-balance melt, blowing snow, frozen soil",
        "modules": ["basin", "global", "obs", "calcsun", "intcp", "pbsm", "albedo",
                    "ebsm", "netall", "crack", "evap", "Soil", "Netroute"],
        "rationale": "The 13-module chain ACTUALLY used by every validated CRHM mountain basin "
                     "in SKILL.md (Bow, St.Mary, Ghost, Coldwater, Similkameen, Kaslo, Gold, "
                     "Blue, Blaeberry, Kootenay, Canoe, Crowsnest, Dore). It is the 'mountain' "
                     "chain MINUS Slope_Qsi and walmsley_wind, which need per-HRU aspect/slope "
                     "(hru_ASL/hru_GSL) and Walmsley A/B/L terrain-speedup parameters that "
                     "derive_parameters.py cannot source for a generic basin; left at their "
                     "zero defaults they add no physics but do add failure modes. Retains the "
                     "full cold-regions set: pbsm (blowing-snow redistribution + sublimation), "
                     "albedo+ebsm+netall (energy-balance snowmelt), crack (frozen-soil "
                     "infiltration, Gray's equation), intcp (canopy interception).",
    },
    "prairie_reduced": {
        "description": "Prairie / open steppe -- blowing snow, MASS-BALANCE "
                       "snowpack (SnobalCRHM), frozen soil",
        "modules": ["basin", "global", "obs", "calcsun", "intcp", "pbsmSnobal",
                    "albedo", "SnobalCRHM", "netall", "crack", "evap", "Soil",
                    "Netroute"],
        "rationale": "The legacy 'prairie' chain (PBSM > PrairieInfil > Soil > Netroute) "
                     "has NEVER been validated in this KI and carries NO energy-balance "
                     "melt at all -- no albedo, no netall, no ebsm -- so a flat cold "
                     "steppe would accumulate and ablate snow on the wrong physics, which "
                     "is fatal when SWE is the scored variable. This preset keeps the "
                     "radiation / canopy / frozen-soil / soil / routing modules of the "
                     "13-module chain every validated CRHM basin uses ('mountain_reduced') "
                     "and swaps its snow pair pbsm + ebsm for pbsmSnobal + SnobalCRHM "
                     "(see the two revision notes). Blowing snow enters through "
                     "pbsmSnobal, whose fetch/Ht/distrib come from the HRU land cover. "
                     "STATUS: this chain RUNS (Hulunbuir open steppe 49.4N 120.5E, "
                     "2003-2014, and a one-HRU Nenjiang site) but it is NOT a validated "
                     "pass: the Hulunbuir SWE score was NSE -0.46, KGE 0.20, r 0.73 "
                     "(retest 2026-07-26). The Hulunbuir result quoted in SKILL.md was "
                     "made with the ebsm chain, now 'prairie_ebsm_legacy'.",
        "revision_2026_07_26": "ebsm REPLACED by SnobalCRHM. Evidence, Hulunbuir "
                     "open steppe 2002-2014 area-weighted: cumhru_snow 980.7 mm, "
                     "cumSubl 13.8 mm (1.4% of snowfall), cumQe_subl 0.0 mm, peak "
                     "SWE 45-87% of each water year's snowfall -- the chain had NO "
                     "mid-winter ablation sink. ebsm is melt-only and its whole "
                     "daily block is gated on meltflag==1 (Classebsm.cpp:199,222), "
                     "which Classalbedo.cpp:150-182 holds at 0 all winter when "
                     "hru_tmax < -6 C; its one sublimation path is behind "
                     "Qe_subl_from_SWE, default [0] and never written by this KI. "
                     "evap never touches SWE (Classevap.cpp has no snow term). "
                     "SnobalCRHM ablates via turbulent latent flux E_s every "
                     "timestep, ungated (ClassSnobalCRHM.cpp:66, "
                     "ClassSnobalBase.cpp:724,1039). albedo is RETAINED because "
                     "SnobalCRHM reads Albedo from it (ClassSnobalCRHM.cpp:172). "
                     "[Two claims in the first version of this note were wrong and "
                     "are corrected by revision_2026_10_02: 'pbsm still supplies "
                     "hru_drift/hru_subl' and 'SnobalCRHM reads Qsisn_Var/"
                     "Qlisn_Var from netall'.]",
        "revision_2026_10_02": "pbsm REPLACED by pbsmSnobal. The 07-26 chain "
                     "(pbsm + SnobalCRHM) never ran: SnobalCRHM declgetvar's "
                     "hru_drift / hru_subl (ClassSnobalCRHM.cpp:170-171, used at "
                     ":316-317) and ONLY pbsmSnobal declares them "
                     "(ClasspbsmSnobal.cpp:74,76); plain pbsm declares Subl / "
                     "Drift (Classpbsm.cpp:76,78). The pointers stay NULL "
                     "(ClassSnobalCRHM.h:57-58), CRHM reports nothing, and the "
                     "first timestep segfaults: banner, '0% complete.', exit -11, "
                     "a two-row output file (triplet dt_v012). Seen on the server "
                     "2026-07-26 (Hulunbuir RETEST_A, header-only output) and "
                     "again 2026-10-02 (one-HRU Nenjiang site, exit -11, 112 "
                     "bytes). pbsm + SnobalCRHM would also carry two separate SWE "
                     "states. CRHM's own registered model 'Prairie using Qsi and "
                     "Snobal' (NewModules.cpp:278) pairs pbsmSnobal with "
                     "SnobalCRHM. Plain SnobalCRHM is variation 0 and reads Qsi / "
                     "Qli from the .obs (ClassSnobalCRHM.cpp:182-186); netall does "
                     "not provide Qsisn_Var / Qlisn_Var and does not need to. "
                     "Module order MATTERS to the binary: the .prj order is "
                     "the execution order. albedo stays BEFORE SnobalCRHM, as "
                     "in CRHM's registered model; this order and the registered "
                     "order (netall, pbsmSnobal, albedo, evap, SnobalCRHM) give "
                     "byte-identical output on the Nenjiang test, while "
                     "SnobalCRHM before albedo gives a different result "
                     "(tested 2026-10-02).",
    },

    "prairie_ebsm_legacy": {
        "description": "Prairie / open steppe, PRE-2026-07-26 melt-only chain "
                       "(ebsm). Kept for reproducibility ONLY -- it has no "
                       "mid-winter snow ablation sink and over-accumulates SWE "
                       "by ~2x in cold-dry continental steppe. Do not select it "
                       "for a run scored on SWE.",
        "modules": ["basin", "global", "obs", "calcsun", "intcp", "pbsm", "albedo",
                    "ebsm", "netall", "crack", "evap", "Soil", "Netroute"],
        "rationale": "Superseded by prairie_reduced. See its revision_2026_07_26 note.",
    },

    "forest": {
        "description": "Boreal/temperate forest -- canopy interception, sublimation",
        "modules": ["basin", "global", "obs", "CRHMCanopy", "SnobalCRHM", "GreenAmpt", "Soil", "Netroute"],
        "rationale": "CRHMCanopy handles interception/sublimation. SnobalCRHM for sub-canopy melt.",
    },
    "arctic": {
        "description": "Arctic/subarctic -- permafrost, blowing snow, minimal vegetation",
        "modules": ["basin", "global", "obs", "intcp", "PBSM", "SnobalCRHM",
                    "PrairieInfil", "Soil", "REWroute"],
        "rationale": "PBSM for blowing snow. PrairieInfil for frozen ground. REWroute for "
                     "wetland routing. UNVALIDATED in this KI. 'intcp' was added because the "
                     "chain otherwise has no provider for net_rain/net_snow and CRHM "
                     "segfaults (dt_v006).",
    },
    "mixed": {
        "description": "Mixed landscape -- forest clearings, variable terrain",
        "modules": ["basin", "global", "obs", "CRHMCanopyClearing", "SnobalCRHM", "GreenAmpt", "Soil", "Netroute"],
        "rationale": "CRHMCanopyClearing handles forest/clearing mix. SnobalCRHM for general melt.",
    },
}


# Reads that may be satisfied by a module listed LATER in the chain. The .prj
# order is the execution order, and albedo and SnobalCRHM read each other
# (albedo reads SWE, SnobalCRHM reads Albedo), so one of the two reads must be
# a timestep old. CRHM's registered model "Prairie using Qsi and Snobal"
# (NewModules.cpp:278: ... pbsmSnobal, albedo, evap, SnobalCRHM#2 ...) puts
# albedo FIRST. With pbsmSnobal there is no earlier SWE declarer at all (it
# keeps no pack), so the plain order check would refuse CRHM's own order.
LATER_PROVIDER_OK = {
    ("albedo", "SWE"): {"SnobalCRHM"},
}

# Module names the CRHM CLI binary registers: every AddModule() call in
# crhmcode/src/modules/newmodules/NewModules.cpp (Program Version 4.7_16,
# crhmcode commit b6f7e70). A name outside this set gives "Unknown Module:
# <name>" followed by a segfault (rc 139, empty output). Verified 2026-10-02 on
# the 'forest' (CRHMCanopy), 'mixed' (CRHMCanopyClearing) and 'arctic' (PBSM)
# presets, which use the GUI class names instead of the registered names.
BINARY_MODULES = frozenset("""
Shared NOP basin global obs intcp Grow_Crop calcsun NO_pbsm pbsm sbsm Annandale
ebsm longVt Slope_Qsi albedo netall evap evapD evap_Resist evapD_Resist
ShuttleWallace ShuttleWallaceD crack PrairieInfiltration Ayers Greencrack
GreenAmpt frozen frozenAyers Soil evapX SoilX SoilDetention SoilPrairie glacier
glacier_debris Glacier_debris_cover SWESlope ICEflow Netroute Netroute_D
Netroute_M Netroute_M_D REW_route REW_route_stream REW_route2 SnobalCRHM
pbsmSnobal Canopy CanopyClearing CanopyClearingGap NeedleLeaf walmsley_wind XG
XGAyers SetSoil Volumetric tsurface albedo_param albedo_obs albedo_Richard
albedo_Baker albedo_Winstral Ht_obs obs_par frostdepth Qmelt Quinton Qdrift
SimpleSnow Kevin Tsnow K_Estimate Snobal interception lake_evap TestSparse HMSA
IceBulb 3D_param MeltRunoff_Lag MeltRunoff_Kstorage FlowInSnow Exec
contribution albedo_obs2 winter_meltflag z_s_and_rho WQ_Test
WQ_Soil_BGC_substitute WQ_Soil WQ_Netroute WQ_Netroute_M_D WQ_pbsm
WQ_pbsmSnobal WQ_Soil_BGC WQ_mass_to_conc Grow_crops_annually
WQ_Gen_Mass_Var_Netroute WQ_Gen_Mass_Var_Soil lapse_rate_Monthly_Mod
Glacier_melt_debris_cover_estimate_Mod
""".split())

# GUI / class names used in MODULE_DB and the unvalidated presets -> the name
# the binary actually registers. Used only to make the refusal say what to type.
BINARY_NAME_HINTS = {
    "CRHMCanopy": "Canopy",
    "CRHMCanopyClearing": "CanopyClearing",
    "PBSM": "pbsm (or pbsmSnobal with SnobalCRHM)",
    "PrairieInfil": "PrairieInfiltration",
    "REWroute": "REW_route",
    "Needle": "NeedleLeaf",
    "Annan": "Annandale",
    "SoilDS": "SoilDetention",
}


# Auto-detected landscape classes with no runnable chain -> the chain used
# instead (see __main__).
AUTODETECT_FALLBACK = {
    "forest": "mountain_reduced",
    "mixed": "mountain_reduced",
    "arctic": "mountain_reduced",
}

# Presets that are no longer selectable, and what to use instead. A chain here
# fails validate_chain() structurally, so letting it through only moves the
# failure into CRHM. Rejecting it by name lets the tool say WHICH validated
# preset replaces it.
DEPRECATED_CHAINS = {
    "prairie": (
        "prairie_reduced",
        "the legacy 'prairie' chain carries no melt module (no ebsm/SnobalCRHM/"
        "HMSA), so nothing provides 'snowmelt' for PrairieInfil and the chain "
        "cannot run. 'prairie_reduced' is the validated 13-module chain for the "
        "same landscape.",
    ),
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
    # Prefer per-HRU mean elevations for relief (always present); fall back to
    # an explicit elevation_range_m only if it carries a real (non-degenerate)
    # span. BUGFIX: the old default [0,0] is truthy, so a config lacking
    # elevation_range_m silently produced relief=0 and mis-classified genuine
    # mountain basins (1600-2400 m HRUs) as 'prairie'.
    elev_range = cfg.get('elevation_range_m')
    hru_elevs = [h['mean_elevation_m'] for h in hrus if 'mean_elevation_m' in h]
    relief = 0
    if hru_elevs:
        relief = max(hru_elevs) - min(hru_elevs)
    if (isinstance(elev_range, (list, tuple)) and len(elev_range) >= 2
            and (elev_range[1] - elev_range[0]) > relief):
        relief = elev_range[1] - elev_range[0]

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
    # Open fraction = TREELESS, wind-exposed surfaces, i.e. everything PBSM
    # blowing-snow transport applies to. 'crop_stubble', 'bare_ground' and
    # 'alpine_tundra' were missing, so a steppe domain whose dominant HRU came
    # back as crop_stubble (the Hulunbuir case: 52% stubble + 35% prairie)
    # scored open_frac 0.35 and fell through to the 'mountain' default.
    open_frac = sum(v for k, v in lc_fracs.items()
                    if k in ('open_prairie', 'grassland', 'cropland',
                             'crop_stubble', 'bare_ground', 'alpine_tundra'))
    # Alpine fraction
    alpine_frac = lc_fracs.get('alpine', 0) + lc_fracs.get('bare', 0)

    # Classification logic
    if abs(mean_lat) > 60:
        basin_type = 'arctic'
        reason = f"latitude {mean_lat:.1f}° (>60°)"
    elif relief > 500:
        basin_type = 'mountain'
        reason = f"relief {relief:.0f}m (>500m)"
    elif relief < 500 and open_frac > 0.5:
        # Flat + open -> prairie/steppe. Routed to the VALIDATED 13-module chain,
        # NOT the legacy 4-process 'prairie' chain, which has no energy-balance
        # melt (see the prairie_reduced rationale). The relief cut-off is 500 m
        # (matching the mountain test above) rather than 300 m: a genuinely flat
        # steppe still shows a few hundred metres of range over a regional domain
        # -- Hulunbuir spans 609-1016 m of gentle rise and was falling through to
        # the 'mountain' default.
        basin_type = 'prairie_reduced'
        reason = f"relief {relief:.0f}m (<500m), open fraction {open_frac:.0%}"
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
                        help="Basin landscape type (auto-detected if omitted). "
                             "Deprecated presets are listed but rejected: "
                             + ", ".join(f"{k} -> {v[0]}" for k, v in DEPRECATED_CHAINS.items()))
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
    elif basin_type in DEPRECATED_CHAINS:
        replacement, why = DEPRECATED_CHAINS[basin_type]
        errors.append(f"basin_type '{basin_type}' is no longer selectable: {why} "
                      f"Re-run with --basin_type {replacement}.")
    if not output_path:
        errors.append("Output path not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_chain(modules, allow_later=False):
    """
    Verify module chain: all declgetvar dependencies satisfied by earlier modules.

    Returns list of warnings/errors.
    """
    issues = []
    provided_vars = set()
    # Variations use the same structural dependencies as their base module.
    # Keep suffixes in the emitted project, but never let them bypass guards.
    modules = [name.split("#", 1)[0] for name in modules]

    for mod_name in modules:
        # "SnobalCRHM#2" is module SnobalCRHM, variation 2
        db_name = mod_name.split("#", 1)[0]
        if db_name not in MODULE_DB:
            issues.append(f"ERROR: Unknown module '{mod_name}'")
            continue

        mod = MODULE_DB[db_name]
        # Check that all required variables are provided by earlier modules.
        #
        # This is an ERROR, not a warning. A declgetvar() with no earlier
        # provider is the same class of fault as the segfault checks below --
        # CRHM resolves variables by name at chain-build time, and a name
        # nothing declares does not degrade the run, it ends it. Reporting it
        # as a WARNING meant process() emitted the chain anyway: the legacy
        # 'prairie' preset (basin>global>obs>intcp>PBSM>PrairieInfil>Soil>
        # Netroute) has NO snowmelt provider -- no ebsm, no SnobalCRHM, no HMSA
        # -- so PrairieInfil's declgetvar("snowmelt") cannot resolve, yet the
        # tool wrote the chain out and the failure surfaced downstream in CRHM.
        for req_var in mod["requires"]:
            if req_var not in provided_vars:
                # Imported projects can use CRHM's registered forward-reference
                # order (e.g. netall before albedo). Still require a provider.
                if allow_later and any(req_var in MODULE_DB.get(name, {}).get("provides", [])
                                       for name in modules):
                    continue
                # Check if it could be satisfied by obs
                if req_var.startswith("hru_"):
                    continue  # obs module provides hru_* variables
                # A read that CRHM's own registered models resolve from a
                # LATER module (the value is one timestep old).
                if LATER_PROVIDER_OK.get((mod_name, req_var), set()).intersection(modules):
                    continue
                issues.append(
                    f"ERROR: Module '{mod_name}' requires '{req_var}' but no earlier "
                    f"module provides it"
                )

        # Add this module's outputs to provided set
        provided_vars.update(mod["provides"])

    # --- HARD structural checks (these crash the CLI binary, not just warn) ---
    #
    # net_rain / net_snow. pbsm, albedo, ebsm and crack all read the CANOPY-
    # ADJUSTED precipitation (net_rain / net_snow), which ONLY a canopy module
    # emits (intcp / CRHMCanopy / CRHMCanopyClearing). Drop the canopy module --
    # a natural thing to try on treeless steppe, where interception is nil --
    # and the binary does not raise a missing-variable error: it SEGFAULTS
    # (verified 2026-07-25, CRHM 4.7_16, chain basin>global>obs>calcsun>pbsm>
    # albedo>ebsm>netall>crack>evap>Soil>Netroute -> "core dumped" after the
    # banner, leaving a 70-byte header-only output file). Keep intcp in the
    # chain even for grassland: with a 0.3 m canopy it passes precipitation
    # through essentially untouched, and it is what every validated .prj does.
    canopy_mods = {"intcp", "CRHMCanopy", "CRHMCanopyClearing"}
    net_p_consumers = {"pbsm", "PBSM", "albedo", "ebsm", "netall", "crack"}
    used_consumers = sorted(net_p_consumers.intersection(modules))
    if used_consumers and not canopy_mods.intersection(modules):
        issues.append(
            "ERROR: chain contains " + ", ".join(used_consumers) +
            " but NO canopy module (intcp/CRHMCanopy/CRHMCanopyClearing) to provide "
            "net_rain/net_snow. CRHM SEGFAULTS on this chain instead of reporting a "
            "missing variable -- add 'intcp' (see triplet dt_v006)."
        )

    # pbsm must be present when SWE is wanted: the binary's wildcard SWE search
    # segfaults without it (SKILL.md Belly River lesson dt_v002).
    if "ebsm" in modules and not {"pbsm", "PBSM", "SnobalCRHM", "HMSA"}.intersection(modules):
        issues.append(
            "ERROR: 'ebsm' present but no snowpack module (pbsm/SnobalCRHM) declares SWE "
            "-- CRHM segfaults on the wildcard SWE search (dt_v002)."
        )

    # Snobal pairing (dt_v012). SnobalCRHM / SnobalX declgetvar hru_drift and
    # hru_subl unconditionally (ClassSnobalCRHM.cpp:170-171, ClassSnobalX.cpp:
    # 158-159) and read them every timestep. Only pbsmSnobal / WQ_pbsmSnobal
    # declare them. The generic 'requires' loop above cannot see this: it skips
    # every hru_* name on the assumption that obs provides it, which is how the
    # pbsm + SnobalCRHM chain passed this function and then core-dumped.
    snobal_mods = sorted({"SnobalCRHM", "SnobalX"}.intersection(modules))
    drift_providers = {"pbsmSnobal", "WQ_pbsmSnobal"}.intersection(modules)
    if snobal_mods and not drift_providers:
        issues.append(
            "ERROR: chain contains " + ", ".join(snobal_mods) + " but no module "
            "that declares hru_drift / hru_subl (only 'pbsmSnobal' does; plain "
            "'pbsm' declares Subl / Drift). CRHM leaves the two pointers NULL "
            "and SEGFAULTS on the first timestep with no message -- use "
            "'pbsmSnobal' as the blowing-snow module (see triplet dt_v012)."
        )
    # Plain pbsm next to a Snobal pack: both declare their own SWE state and
    # each adds net_snow to its own pack (Classpbsm.cpp:74, ClassSnobalCRHM.cpp
    # :95) -- two snowpacks fed the same snowfall.
    plain_pbsm = sorted({"pbsm", "PBSM"}.intersection(modules))
    if snobal_mods and plain_pbsm:
        issues.append(
            "ERROR: chain contains " + ", ".join(plain_pbsm) + " together with "
            + ", ".join(snobal_mods) + ". Both declare their own SWE, so the "
            "chain would carry two snowpacks fed the same snowfall -- replace "
            "it with 'pbsmSnobal' (see triplet dt_v012)."
        )
    # The other direction: pbsmSnobal has no pack of its own. It declputvar's
    # SWE, z_s and rho (ClasspbsmSnobal.cpp:130-132); z_s and rho exist only in
    # a Snobal module.
    if drift_providers and not snobal_mods:
        issues.append(
            "ERROR: chain contains " + ", ".join(sorted(drift_providers)) +
            " but no Snobal snowpack (SnobalCRHM). pbsmSnobal keeps no SWE of "
            "its own; it writes into the Snobal pack's SWE / z_s / rho. With an "
            "ebsm chain use plain 'pbsm' instead (see triplet dt_v012)."
        )

    # Module names the binary does not register. CRHM prints "Unknown Module:
    # <name>" and then segfaults (rc 139, empty output). Checked against the
    # AddModule() list in NewModules.cpp (CRHM 4.7_16, crhmcode b6f7e70).
    for mod_name in modules:
        base = mod_name.split("#", 1)[0]
        if base not in BINARY_MODULES:
            hint = BINARY_NAME_HINTS.get(base)
            issues.append(
                f"ERROR: '{mod_name}' is not a module name the CRHM binary "
                "registers (NewModules.cpp); CRHM prints 'Unknown Module' and "
                "segfaults." + (f" The binary's name is '{hint}'." if hint else "")
            )

    return issues


def process(basin_type, processes, output_path):
    """Build module chain configuration."""
    chain = LANDSCAPE_CHAINS[basin_type]
    modules = list(chain["modules"])

    # Apply process overrides.
    #
    # An override is a no-op when the chain already has a module for that
    # process, and it only ever adds a name the binary registers. The old code
    # compared against the GUI names, so `--processes blowing_snow` added
    # "PBSM" to a chain that already had pbsm, `canopy` added "CRHMCanopy" next
    # to intcp and `sublimation` added "Needle" -- none of which the CLI binary
    # knows ("Unknown Module", then a segfault).
    if processes:
        process_list = [p.strip() for p in processes.split(",") if p.strip()]
        blowing = {"pbsm", "pbsmSnobal", "WQ_pbsm", "WQ_pbsmSnobal"}
        canopy = {"intcp", "Canopy", "CanopyClearing", "CanopyClearingGap"}
        for proc in process_list:
            if proc == "blowing_snow":
                have = sorted(blowing.intersection(modules))
                if have:
                    logger.info("--processes blowing_snow: chain already has %s; "
                                "nothing added.", ", ".join(have))
                    continue
                # the module that fits the chain's snowpack (dt_v012)
                add = "pbsmSnobal" if "SnobalCRHM" in modules else "pbsm"
                for i, m in enumerate(modules):
                    if MODULE_DB.get(m, {}).get("category") in ("snowmelt", "infiltration"):
                        modules.insert(i, add)
                        break
                else:
                    logger.error("--processes blowing_snow: no snowmelt or infiltration "
                                 "module in the chain to place %s before.", add)
                    sys.exit(1)
            elif proc == "canopy":
                have = sorted(canopy.intersection(modules))
                if have:
                    logger.info("--processes canopy: chain already has %s (the canopy / "
                                "net-precipitation module); nothing added.", ", ".join(have))
                    continue
                logger.error("--processes canopy: this chain has no canopy module and the "
                             "tool has no validated one to add; use a preset that "
                             "carries 'intcp'.")
                sys.exit(1)
            elif proc == "sublimation":
                logger.error("--processes sublimation is not supported: it used to add "
                             "'Needle', which the CLI binary does not register (its name "
                             "is 'NeedleLeaf', never run or parameterised by this KI). "
                             "Snow sublimation is already in the chains: pbsm / pbsmSnobal "
                             "(blowing snow) and SnobalCRHM (surface).")
                sys.exit(1)
            else:
                logger.error("Unknown --processes entry '%s'. Known: blowing_snow, canopy.",
                             proc)
                sys.exit(1)

    # Validate chain
    issues = validate_chain(modules)
    fatal = [i for i in issues if i.startswith("ERROR")]
    for issue in issues:
        if issue.startswith("ERROR"):
            logger.error(issue)
        else:
            logger.warning(issue)
    # FAIL CLOSED. These errors are the chains CRHM cannot run: an unresolved
    # declgetvar (a module requiring a variable no earlier module declares), a
    # missing canopy provider for net_rain/net_snow, a missing SWE declarer, a
    # Snobal pack without pbsmSnobal (dt_v012), an unknown module name or one
    # the binary does not register. All but the first SEGFAULT the CLI binary. Emitting the
    # chain anyway just moves the failure to a core dump inside a detached run,
    # with a 70-byte output file and no diagnosis. The legacy 'prairie' preset
    # trips the declgetvar check (PrairieInfil needs 'snowmelt', which no module
    # in that chain declares) and is rejected earlier by name in
    # validate_inputs(); this stays as the check that catches the same fault
    # arriving from a --processes override or a hand-edited preset.
    if fatal:
        logger.error("Refusing to emit a module chain with %d structural error(s); "
                     "this chain would crash CRHM, not just run badly.", len(fatal))
        sys.exit(1)

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
        # The landscape classes 'forest', 'mixed' and 'arctic' have no chain
        # that runs with the CLI binary (their presets use unregistered module
        # names and are refused below). An auto-detected basin must still get a
        # chain: fall back to the validated 13-module chain, which is what the
        # forested mountain basins in SKILL.md were validated with (intcp is
        # its canopy module), and say so. An explicit --basin_type forest /
        # mixed / arctic is still refused.
        if basin_type in AUTODETECT_FALLBACK:
            logger.warning(
                "Landscape detected as '%s', but this KI has no chain for it that the "
                "CRHM binary can run. Using '%s' (the validated 13-module chain) "
                "instead. It has no dedicated forest-canopy or permafrost module; "
                "treat canopy snow and frozen-ground results with care.",
                basin_type, AUTODETECT_FALLBACK[basin_type])
            basin_type = AUTODETECT_FALLBACK[basin_type]
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
