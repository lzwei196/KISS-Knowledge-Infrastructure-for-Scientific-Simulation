#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_calibration_file
Stage:        s6_calibration_parameters
Description:  Create calibration.cal with parameter adjustments for SWAT+.
              Change types: absval (set), abschg (add), pctchg (percent change).

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

PARAMETER_SET = {}  # {"cn2": {"change_type": "pctchg", "value": -10}, ...}
OUTPUT_DIR = ""

if len(sys.argv) >= 3:
    PARAMETER_SET = json.loads(sys.argv[1])
    OUTPUT_DIR = sys.argv[2]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Valid SWAT+ calibration parameters with ranges and recommended change types
VALID_PARAMS = {
    "cn2":       {"range": (-50, 50), "recommended_type": "pctchg", "obj_typ": "hru"},
    "esco":      {"range": (0, 1), "recommended_type": "absval", "obj_typ": "hru"},
    "epco":      {"range": (0, 1), "recommended_type": "absval", "obj_typ": "hru"},
    "awc":       {"range": (-50, 50), "recommended_type": "pctchg", "obj_typ": "hru"},
    "k":         {"range": (-50, 50), "recommended_type": "pctchg", "obj_typ": "hru"},
    "surlag":    {"range": (0.05, 24), "recommended_type": "absval", "obj_typ": "bsn"},
    # rev59 cal_parms.cal names; alpha_bf/gw_delay are SWAT2012 aliases kept for
    # back-compat and rewritten to alpha/delay before calibration.cal is written.
    "alpha":     {"range": (0, 1), "recommended_type": "absval", "obj_typ": "aqu"},
    "delay":     {"range": (0, 500), "recommended_type": "absval", "obj_typ": "aqu"},
    "alpha_bf":  {"range": (0, 1), "recommended_type": "absval", "obj_typ": "aqu"},
    "gw_delay":  {"range": (0, 500), "recommended_type": "absval", "obj_typ": "aqu"},
    "revap_co":  {"range": (0.02, 0.2), "recommended_type": "absval", "obj_typ": "aqu"},
    "flo_min":   {"range": (0, 5000), "recommended_type": "absval", "obj_typ": "aqu"},
    "revap_min": {"range": (0, 500), "recommended_type": "absval", "obj_typ": "aqu"},
    "perco":     {"range": (0, 1), "recommended_type": "absval", "obj_typ": "hru"},
    "lat_ttime": {"range": (0, 180), "recommended_type": "absval", "obj_typ": "hru"},
    "canmx":     {"range": (0, 100), "recommended_type": "absval", "obj_typ": "hru"},
    "nperco":    {"range": (0, 1), "recommended_type": "absval", "obj_typ": "bsn"},
    "pperco":    {"range": (10, 17.5), "recommended_type": "absval", "obj_typ": "bsn"},
    "cdn":       {"range": (0, 3), "recommended_type": "absval", "obj_typ": "bsn"},
    "sdnco":     {"range": (0, 1), "recommended_type": "absval", "obj_typ": "bsn"},
    "phoskd":    {"range": (100, 200), "recommended_type": "absval", "obj_typ": "bsn"},
    "usle_p":    {"range": (0, 1), "recommended_type": "absval", "obj_typ": "hru"},
    # STRUCTURAL aquifer params (see STRUCTURAL_AQU below): NOT in cal_parms.cal,
    # so a calibration.cal line for them is SILENTLY IGNORED (dt_013). This tool
    # intercepts them and edits aquifer.aqu directly instead.
    "rchg_dp":   {"range": (0, 1), "recommended_type": "absval", "obj_typ": "aqu-struct"},
    "spec_yld":  {"range": (0.001, 0.5), "recommended_type": "absval", "obj_typ": "aqu-struct"},
}

# Aquifer parameters that live ONLY in aquifer.aqu and are absent from
# cal_parms.cal, so calibration.cal cannot touch them (exactly like perco /
# cn3_swf in hydrology.hyd). Keyed to the 0-indexed column in aquifer.aqu data
# rows: id name aqu_init gw_flo gw_dp gw_ht no3_n sol_p ptl_n ptl_p bf_max
#       alpha_bf revap_co RCHG_DP SPEC_YLD hl_no3n flo_min revap_min
#                          ^col13  ^col14
# rchg_dp = fraction of soil percolation diverted to the DEEP aquifer and lost
# from the local stream water balance. It is the dominant VOLUME lever for
# humid basins that still OVER-predict after cn2 and esco are already maxed
# (Wangjiaba: raising rchg_dp 0.30->0.78 cut full-period PBIAS +34% -> ~0 with
# ZERO timing lag, because it removes baseflow volume uniformly without the
# phase shift that channel-slowing introduces). Physically it lumps un-modeled
# consumptive losses (irrigation withdrawal, flood diversion/detention, regional
# groundwater pumping) for heavily human-impacted basins.
STRUCTURAL_AQU = {
    "rchg_dp":  {"col": 13, "absmin": 0.0,   "absmax": 1.0},
    "spec_yld": {"col": 14, "absmin": 0.001, "absmax": 0.5},
}

# Recommended starting calibration presets by climate zone
# Based on validated Bengbu (humid subtropical, NSE=0.757) and literature
CALIBRATION_PRESETS = {
    # DIRECTION-AWARE humid presets. Select by the UNCALIBRATED PBIAS sign:
    #   PBIAS > 0 (sim too WET / over-predicts, e.g. Bengbu +253%) -> _overpredict
    #   PBIAS < 0 (sim too DRY / under-predicts, e.g. Xixian -32%) -> _underpredict
    # The old single "humid_subtropical" was the _overpredict recipe applied to
    # ALL humid basins; on an under-predicting basin its cn2 -50% strips the
    # storm-runoff signal (collapses r) and esco 0.15 maxes ET (worsens PBIAS).
    "humid_subtropical_overpredict": {
        "cn2": {"change_type": "pctchg", "value": -50},   # Reduce excessive surface runoff
        "esco": {"change_type": "absval", "value": 0.15},  # Maximize ET to cut yield
        "cn3_swf": {"change_type": "absval", "value": 0.0}, # Disable wet-season CN3 amplification
        "perco": {"change_type": "absval", "value": 0.75},  # Enhance deep percolation
    },
    "humid_subtropical_underpredict": {
        "cn2": {"change_type": "pctchg", "value": 5},     # Preserve/raise surface runoff (NOT -50)
        "esco": {"change_type": "absval", "value": 0.85},  # Restrict ET to upper soil -> more yield
        "perco": {"change_type": "absval", "value": 0.50},  # Neutral percolation, retain water
    },
    # Back-compat alias defaults to the over-predict recipe (historical behavior).
    "humid_subtropical": {
        "cn2": {"change_type": "pctchg", "value": -50},
        "esco": {"change_type": "absval", "value": 0.15},
        "cn3_swf": {"change_type": "absval", "value": 0.0},
        "perco": {"change_type": "absval", "value": 0.75},
    },
    "semi_arid": {
        "cn2": {"change_type": "pctchg", "value": -20},
        "esco": {"change_type": "absval", "value": 0.50},
        "perco": {"change_type": "absval", "value": 0.30},
    },
    "tropical": {
        "cn2": {"change_type": "pctchg", "value": -40},
        "esco": {"change_type": "absval", "value": 0.20},
        "perco": {"change_type": "absval", "value": 0.60},
    },
    "continental": {
        "cn2": {"change_type": "pctchg", "value": -30},
        "esco": {"change_type": "absval", "value": 0.30},
        "alpha_bf": {"change_type": "absval", "value": 0.05},
    },
    "default": {
        "cn2": {"change_type": "pctchg", "value": -30},
        "esco": {"change_type": "absval", "value": 0.30},
    },
}


def validate_inputs():
    errors = []
    if not PARAMETER_SET:
        errors.append("No parameters provided")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    for pname, pconfig in PARAMETER_SET.items():
        if pname not in VALID_PARAMS:
            errors.append(f"Unknown parameter: {pname}")
        if "change_type" not in pconfig:
            errors.append(f"Missing change_type for {pname}")
        elif pconfig["change_type"] not in ["absval", "abschg", "pctchg"]:
            errors.append(f"Invalid change_type for {pname}: {pconfig['change_type']}")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    cal_path = output_dir / "calibration.cal"
    warnings = []
    struct_applied = {}

    # --- STRUCTURAL aquifer params (rchg_dp, spec_yld): edit aquifer.aqu in
    # place. calibration.cal CANNOT change these (not in cal_parms.cal); a
    # cal line for them is silently ignored. This mirrors how perco/cn3_swf
    # must be set in hydrology.hyd, not calibration.cal.
    struct_params = {k: v for k, v in PARAMETER_SET.items() if k in STRUCTURAL_AQU}
    cal_only = {k: v for k, v in PARAMETER_SET.items() if k not in STRUCTURAL_AQU}
    if struct_params:
        aqu_path = output_dir / "aquifer.aqu"
        if not aqu_path.exists():
            warnings.append(f"Structural aquifer params {list(struct_params)} requested "
                            f"but aquifer.aqu not found in {output_dir}; skipped.")
        else:
            L = aqu_path.read_text().splitlines()
            out_a = L[:2]
            for ln in L[2:]:
                p = ln.split()
                if len(p) < 16:
                    out_a.append(ln); continue
                for pname, pcfg in struct_params.items():
                    spec = STRUCTURAL_AQU[pname]; col = spec["col"]
                    ct = pcfg.get("change_type", "absval"); v = float(pcfg.get("value", 0))
                    if ct == "pctchg":   newv = float(p[col]) * (1.0 + v / 100.0)
                    elif ct == "abschg": newv = float(p[col]) + v
                    else:                newv = v               # absval
                    newv = max(spec["absmin"], min(spec["absmax"], newv))
                    p[col] = f"{newv:.5f}"
                out_a.append("   ".join(p))
            aqu_path.write_text("\n".join(out_a) + "\n")
            struct_applied = struct_params
            logger.info(f"Applied structural aquifer params to aquifer.aqu: "
                        f"{ {k: v.get('value') for k, v in struct_params.items()} }")

    # SWAT+ calibration.cal format (verified against the working
    # chaohe_2000_2010 cn2_test3 example and SWAT+ cal_parmread source):
    #   line 1: free-text title
    #   line 2: INTEGER count of parameter rows that follow
    #   line 3: column header
    #   line 4+: one row per parameter
    # The PREVIOUS version wrote the column header as line 2 (no count line).
    # SWAT+ then reads "cal_parm..." as the integer count, the read fails, and
    # ZERO parameters are applied — calibration is silently ignored (sim
    # discharge identical to uncalibrated; PBIAS unchanged). This was the root
    # cause of the Wangjiaba cn2=-50% preset having no effect on runoff.
    # The final column is OBJ_TOT (integer count of objects; 0 = apply to all
    # objects of that type), NOT a text obj_typ — writing "hru" there breaks
    # the integer read of that column.
    # rev59's cal_parms.cal names the baseflow recession `alpha` and the groundwater
    # delay `delay`. SWAT+ reads an unmatched NAME row, fails to match, and SILENTLY
    # ignores it — the parameter simply never applies. Alias the legacy SWAT2012 names
    # and DROP anything the project's own cal_parms.cal does not declare (e.g. perco /
    # cn3_swf, which live in hydrology.hyd) with a loud warning instead of a no-op row.
    ALIASES = {"alpha_bf": "alpha", "gw_delay": "delay"}
    cal_only = {ALIASES.get(k, k): v for k, v in cal_only.items()}

    known = None
    cp = output_dir / "cal_parms.cal"
    if cp.exists():
        try:
            known = {ln.split()[0].lower() for ln in cp.read_text().splitlines()[2:] if ln.split()}
        except Exception as e:
            warnings.append(f"could not parse cal_parms.cal ({e}); not filtering parameter names")
    if known:
        dropped = [k for k in cal_only if k.lower() not in known]
        for k in dropped:
            warnings.append(f"DROPPED '{k}': absent from {cp.name}. SWAT+ would have "
                            f"silently ignored this row (it is not a calibratable name).")
            del cal_only[k]

    n = len(cal_only)
    with open(cal_path, 'w') as f:
        f.write("calibration.cal: written by SWAT+ knowledge infrastructure\n")
        f.write(f"{n}\n")
        f.write(f"{'NAME':<14s}{'CHG_TYP':<11s}{'VAL':>12s}{'CONDS':>9s}"
                f"{'LYR1':>9s}{'LYR2':>9s}{'YEAR1':>9s}{'YEAR2':>9s}"
                f"{'DAY1':>9s}{'DAY2':>9s}{'OBJ_TOT':>9s}\n")

        for pname, pconfig in cal_only.items():
            chg_type = pconfig["change_type"]
            chg_val = pconfig.get("value", 0)

            # Warn if using absval for spatially variable params
            if pname in ["cn2", "awc", "k"] and chg_type == "absval":
                warnings.append(f"WARNING: Using absval for {pname} destroys spatial variability. Use pctchg instead.")

            f.write(f"{pname:<14s}{chg_type:<11s}{chg_val:>12.3f}{'0':>9s}"
                    f"{'0':>9s}{'0':>9s}{'0':>9s}{'0':>9s}"
                    f"{'0':>9s}{'0':>9s}{'0':>9s}\n")

    for w in warnings:
        logger.warning(w)

    logger.info(f"Wrote calibration.cal with {len(cal_only)} parameters")
    return {
        "status": "success",
        "calibration_cal": str(cal_path),
        "n_parameters": len(cal_only),
        "structural_aqu_applied": {k: v.get("value") for k, v in struct_applied.items()},
        "warnings": warnings
    }

def validate_outputs(result):
    if not Path(result["calibration_cal"]).exists():
        logger.error("calibration.cal not created"); sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
