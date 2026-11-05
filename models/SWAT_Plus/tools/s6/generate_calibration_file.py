#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_calibration_file
Stage:        s6_calibration_parameters
Description:  Create calibration.cal with parameter adjustments for SWAT+.
              Change types: absval (set), abschg (add), pctchg (percent change).

Every requested value must be a finite number (NaN / Infinity are rejected
with exit 1 before any file is touched). Every requested STRUCTURAL parameter
(aquifer.aqu / parameters.bsn / hydrology.hyd / soils.sol) must really be
written: a missing file, a missing column, a malformed data row or zero edited
rows is a processing error (exit 2) and NO file is modified. Names that rev59
never applies (dt_045 no-ops, names absent from cal_parms.cal) are dropped with
a warning and listed under `dropped_parameters`, never under the applied lists.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, re, logging, json, math
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
    # STRUCTURAL basin/hydrology/soil params (dt_045): these names are DECLARED
    # in cal_parms.cal but the rev59 binary never applies them from
    # calibration.cal (bit-identical output, measured at Zijingguan 2026-07-10).
    # SKILL.md's parameter table routes them to their real home file; this tool
    # now performs that routing instead of writing silent no-op rows.
    "msk_co1":   {"range": (0, 10), "recommended_type": "absval", "obj_typ": "bsn-struct"},
    "msk_co2":   {"range": (0, 10), "recommended_type": "absval", "obj_typ": "bsn-struct"},
    "msk_x":     {"range": (0, 0.5), "recommended_type": "absval", "obj_typ": "bsn-struct"},
    "cn3_swf":   {"range": (0, 1), "recommended_type": "absval", "obj_typ": "hyd-struct"},
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
    # col_name is what the edit uses (the header must name it); col is the
    # documented position in the rev59 layout above.
    "rchg_dp":  {"col": 13, "col_name": "rchg_dp",  "absmin": 0.0,   "absmax": 1.0},
    "spec_yld": {"col": 14, "col_name": "spec_yld", "absmin": 0.001, "absmax": 0.5},
    # revap_co stays a calibration.cal row (cal_only), NOT a structural edit:
    # the calibration runner writes and reads back a `revap_co` row in
    # calibration.cal, so routing it here breaks the runner's readback.
}

# parameters.bsn: title line, header line of column names, ONE data row.
# surlag / Muskingum weights are calibration.cal no-ops in rev59 (every `bsn`
# object name is — dt_045); the real values live in these named columns.
STRUCTURAL_BSN = {
    "surlag":  {"col_name": "surq_lag", "absmin": 0.05, "absmax": 24.0},
    "msk_co1": {"col_name": "msk_co1",  "absmin": 0.0,  "absmax": 10.0},
    "msk_co2": {"col_name": "msk_co2",  "absmin": 0.0,  "absmax": 10.0},
    "msk_x":   {"col_name": "msk_x",    "absmin": 0.0,  "absmax": 0.5},
}

# hydrology.hyd: title, header (name + 14 columns), one row per hyd object.
# canmx/perco/cn3_swf cannot be changed from calibration.cal (canmx is a
# dt_045 no-op; perco/cn3_swf are not calibratable names at all).
STRUCTURAL_HYD = {
    "canmx":   {"col_name": "can_max", "absmin": 0.0, "absmax": 100.0},
    "perco":   {"col_name": "perco",   "absmin": 0.0, "absmax": 1.0},
    "cn3_swf": {"col_name": "cn3_swf", "absmin": 0.0, "absmax": 1.0},
}

# soils.sol layer rows are exactly 14 floats:
#   dp bd awc soil_k carbon clay silt sand rock alb usle_k ec caco3 ph
# awc (index 2) is a dt_045 calibration.cal no-op; edit the layer rows.
# Bounds = the model's documented valid band for awc (cal_parms.cal obj_typ
# sol absmin/absmax, mm_H2O/mm), same as calib_run.py's SOL_AWC_PHYS_RANGE —
# a tighter cap here would silently clamp valid pctchg results.
STRUCTURAL_SOL = {
    "awc": {"col": 2, "absmin": 0.01, "absmax": 1.0},
}

# dt_045 no-ops with NO structural home in this deck layout: never write them
# to calibration.cal (SWAT+ reads the row and silently ignores it).
NOOP_DROP = {"delay", "dep_imp"}


class StructuralEditError(RuntimeError):
    """A requested structural parameter could not be written to its deck file."""


def _new_value(old, pcfg, absmin, absmax, where=""):
    # value was checked finite in validate_inputs; the deck's own old value and
    # the result are checked here so a NaN/inf can never be clamped into a
    # valid-looking bound.
    if not math.isfinite(old):
        raise StructuralEditError(f"{where}: existing value {old!r} is not finite")
    ct = pcfg["change_type"]
    v = float(pcfg["value"])
    if ct == "pctchg":
        nv = old * (1.0 + v / 100.0)
    elif ct == "abschg":
        nv = old + v
    else:
        nv = v
    if not math.isfinite(nv):
        raise StructuralEditError(f"{where}: new value {nv!r} is not finite")
    return max(absmin, min(absmax, nv))


def _replace_token(line, idx, new_text):
    """Return `line` with only whitespace-separated token `idx` replaced.
    Every other token keeps its exact original text (and the line layout), so
    an edit of one column never re-rounds unrelated values."""
    spans = [m.span() for m in re.finditer(r"\S+", line)]
    a, b = spans[idx]
    old_w = b - a
    return line[:a] + new_text.rjust(old_w) + line[b:]


def _edit_named_table(path, params, spec_map, label, errors, pending):
    """Edit named columns of a title/header/data-rows table (parameters.bsn,
    hydrology.hyd). Every non-blank data row must have the header width; every
    requested column must exist; at least one row must be edited. On any problem
    the error is recorded and nothing is queued for writing."""
    if not path.exists():
        errors.append(f"{label} params {list(params)} requested but {path.name} "
                      f"not found in {path.parent}")
        return {}
    L = path.read_text().splitlines()
    if len(L) < 3:
        errors.append(f"{path.name}: fewer than 3 lines (title, header, data); "
                      f"{list(params)} NOT applied")
        return {}
    hdr = L[1].split()
    cols = {}
    for pname in params:
        cn = spec_map[pname]["col_name"]
        if cn not in hdr:
            errors.append(f"{path.name} has no column '{cn}' for {pname}")
        else:
            cols[pname] = hdr.index(cn)
    if len(cols) != len(params):
        return {}
    out, n_rows, bad = L[:2], 0, []
    for lineno, ln in enumerate(L[2:], start=3):
        t = ln.split()
        if not t:
            out.append(ln); continue
        if len(t) != len(hdr):
            bad.append(f"line {lineno} has {len(t)} fields, header has {len(hdr)}")
            continue
        for pname, pcfg in params.items():
            spec = spec_map[pname]; i = cols[pname]
            nv = _new_value(float(t[i]), pcfg, spec["absmin"], spec["absmax"],
                            f"{path.name} line {lineno} {pname}")
            ln = _replace_token(ln, i, f"{nv:.5f}")
        n_rows += 1
        out.append(ln)
    if bad:
        errors.append(f"{path.name}: malformed data rows ({'; '.join(bad[:5])}); "
                      f"{list(params)} NOT applied")
        return {}
    if n_rows == 0:
        errors.append(f"{path.name}: no data rows; {list(params)} NOT applied")
        return {}
    pending[path] = "\n".join(out) + "\n"
    return {k: {"file": path.name, "rows": n_rows, "value": v["value"],
                "change_type": v["change_type"]} for k, v in params.items()}

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
    if not isinstance(PARAMETER_SET, dict):
        errors.append(f"PARAMETER_SET must be a JSON object, got {type(PARAMETER_SET).__name__}")
    for pname, pconfig in (PARAMETER_SET.items() if isinstance(PARAMETER_SET, dict) else []):
        if pname not in VALID_PARAMS:
            errors.append(f"Unknown parameter: {pname}")
        if not isinstance(pconfig, dict):
            errors.append(f"Config for {pname} must be an object with change_type and value")
            continue
        if "change_type" not in pconfig:
            errors.append(f"Missing change_type for {pname}")
        elif pconfig["change_type"] not in ["absval", "abschg", "pctchg"]:
            errors.append(f"Invalid change_type for {pname}: {pconfig['change_type']}")
        # value is REQUIRED (no silent default of 0) and must be a finite number:
        # json.loads accepts NaN/Infinity, which the old clamp turned into a
        # valid-looking bound (e.g. perco NaN -> 1.00000).
        if "value" not in pconfig:
            errors.append(f"Missing value for {pname}")
            continue
        v = pconfig["value"]
        try:
            if isinstance(v, bool):
                raise TypeError("boolean")
            fv = float(v)
        except (TypeError, ValueError):
            errors.append(f"value for {pname} must be a number, got {v!r}")
            continue
        if not math.isfinite(fv):
            errors.append(f"value for {pname} must be finite, got {v!r}")
            continue
        pconfig["value"] = fv
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    cal_path = output_dir / "calibration.cal"
    warnings = []
    errors = []          # structural failures -> exit 2, nothing written
    pending = {}         # path -> new text; written only if errors stays empty
    struct_applied = {}

    # --- STRUCTURAL aquifer params (rchg_dp, spec_yld): edit aquifer.aqu in
    # place. calibration.cal CANNOT change these (not in cal_parms.cal); a
    # cal line for them is silently ignored. This mirrors how perco/cn3_swf
    # must be set in hydrology.hyd, not calibration.cal.
    struct_params = {k: v for k, v in PARAMETER_SET.items() if k in STRUCTURAL_AQU}
    cal_only = {k: v for k, v in PARAMETER_SET.items() if k not in STRUCTURAL_AQU}
    if struct_params:
        struct_applied.update(_edit_named_table(output_dir / "aquifer.aqu", struct_params,
                                                STRUCTURAL_AQU, "Structural aquifer", errors, pending))

    # --- STRUCTURAL basin params (surlag, msk_co1/2, msk_x): parameters.bsn ---
    bsn_params = {k: v for k, v in cal_only.items() if k in STRUCTURAL_BSN}
    for k in bsn_params:
        del cal_only[k]
    if bsn_params:
        struct_applied.update(_edit_named_table(output_dir / "parameters.bsn", bsn_params,
                                                STRUCTURAL_BSN, "Structural bsn", errors, pending))

    # --- STRUCTURAL hydrology params (canmx, perco, cn3_swf): hydrology.hyd ---
    hyd_params = {k: v for k, v in cal_only.items() if k in STRUCTURAL_HYD}
    for k in hyd_params:
        del cal_only[k]
    if hyd_params:
        struct_applied.update(_edit_named_table(output_dir / "hydrology.hyd", hyd_params,
                                                STRUCTURAL_HYD, "Structural hyd", errors, pending))

    # --- STRUCTURAL soil params (awc): soils.sol layer rows ---
    # Layout read exactly as SWAT+ soil_db_read.f90 reads it: title line,
    # header line, then per soil one row `name nly hyd_grp dp_tot anion_excl
    # perc_crk texture` followed by exactly `nly` layer rows of 14 values
    # (z bd awc k cbn clay silt sand rock alb usle_k ec cal ph; awc = index 2).
    # Every soil and every layer is checked; a malformed or missing layer is an
    # error and nothing is written. Only the awc token is rewritten; all other
    # tokens keep their original text.
    sol_params = {k: v for k, v in cal_only.items() if k in STRUCTURAL_SOL}
    for k in sol_params:
        del cal_only[k]
    if sol_params:
        s_path = output_dir / "soils.sol"
        if not s_path.exists():
            errors.append(f"Structural soil params {list(sol_params)} requested "
                          f"but soils.sol not found in {output_dir}")
        else:
            L = s_path.read_text().splitlines()
            out_s, n_layer, n_soil, bad = L[:2], 0, 0, []
            i = 2
            while i < len(L):
                t = L[i].split()
                if not t:                       # blank line between soils
                    out_s.append(L[i]); i += 1; continue
                lineno = i + 1
                try:
                    nly = int(t[1]) if len(t) >= 7 else None
                except ValueError:
                    nly = None
                if nly is None or nly < 1:
                    bad.append(f"line {lineno}: expected a soil row 'name nly hyd_grp dp_tot "
                               f"anion_excl perc_crk texture' with nly >= 1, got {len(t)} fields")
                    break
                out_s.append(L[i]); n_soil += 1
                for j in range(1, nly + 1):
                    k_i = i + j
                    if k_i >= len(L):
                        bad.append(f"soil {t[0]} (line {lineno}): declares {nly} layers, "
                                   f"file ends after {j - 1}")
                        break
                    lt = L[k_i].split()
                    try:
                        vals = [float(x) for x in lt]
                    except ValueError:
                        vals = None
                    if vals is None or len(lt) != 14:
                        bad.append(f"soil {t[0]} layer {j} (line {k_i + 1}): expected 14 numbers, "
                                   f"got {len(lt)} fields")
                        break
                    ln = L[k_i]
                    for pname, pcfg in sol_params.items():
                        spec = STRUCTURAL_SOL[pname]
                        nv = _new_value(vals[spec["col"]], pcfg, spec["absmin"], spec["absmax"],
                                        f"soils.sol line {k_i + 1} {pname}")
                        ln = _replace_token(ln, spec["col"], f"{nv:.5f}")
                    out_s.append(ln); n_layer += 1
                if bad:
                    break
                i += nly + 1
            if bad:
                errors.append(f"soils.sol: malformed ({'; '.join(bad)}); "
                              f"{list(sol_params)} NOT applied")
            elif n_layer == 0:
                errors.append("soils.sol: no soils/layer rows found; "
                              f"{list(sol_params)} NOT applied")
            else:
                pending[s_path] = "\n".join(out_s) + "\n"
                struct_applied.update({k: {"file": "soils.sol", "rows": n_layer, "soils": n_soil,
                                           "value": v["value"], "change_type": v["change_type"]}
                                       for k, v in sol_params.items()})

    # Every requested structural parameter must be applied, or nothing is written.
    if errors:
        for e in errors:
            logger.error(e)
        raise StructuralEditError(f"{len(errors)} structural edit(s) failed; no file modified: "
                                  + " | ".join(errors))
    for path, text in pending.items():
        path.write_text(text)
        logger.info(f"Applied structural params to {path.name}: "
                    f"{ {k: v['value'] for k, v in struct_applied.items() if v['file'] == path.name} }")

    # Rewrite legacy SWAT2012 names to their rev59 spellings BEFORE the no-op
    # drop, so a request for e.g. `gw_delay` is recognised as `delay` and
    # dropped too, instead of slipping past the drop and still writing a
    # silent no-op calibration.cal row.
    ALIASES = {"alpha_bf": "alpha", "gw_delay": "delay"}
    cal_only = {ALIASES.get(k, k): v for k, v in cal_only.items()}

    # --- dt_045 no-ops with no structural home: never write silent no-op rows
    dropped = {}
    for k in [k for k in cal_only if k in NOOP_DROP]:
        dropped[k] = "dt_045 no-op with no structural home"
        warnings.append(f"DROPPED '{k}': rev59 never applies it from "
                        f"calibration.cal (dt_045) and it has no structural home.")
        del cal_only[k]

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
    # ignores it — the parameter simply never applies. The legacy SWAT2012 names were
    # already aliased above (before the no-op drop); here, DROP anything the project's
    # own cal_parms.cal does not declare (e.g. perco / cn3_swf, which live in
    # hydrology.hyd) with a loud warning instead of a no-op row.
    known = None
    cp = output_dir / "cal_parms.cal"
    if cp.exists():
        try:
            known = {ln.split()[0].lower() for ln in cp.read_text().splitlines()[2:] if ln.split()}
        except Exception as e:
            warnings.append(f"could not parse cal_parms.cal ({e}); not filtering parameter names")
    if known:
        for k in [k for k in cal_only if k.lower() not in known]:
            dropped[k] = f"absent from {cp.name}"
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
            chg_val = pconfig["value"]

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
        "calibration_cal_parameters": list(cal_only),
        # kept for back-compat with existing callers: every structural param applied
        "structural_aqu_applied": {k: v["value"] for k, v in struct_applied.items()},
        "structural_applied": struct_applied,
        "dropped_parameters": dropped,
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
